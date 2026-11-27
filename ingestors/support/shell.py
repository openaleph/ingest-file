import logging
import re
import shutil
import subprocess
import threading

from servicelayer import env

from ingestors.exc import ProcessingException
from ingestors.util import path_string

log = logging.getLogger(__name__)

# `LEVEL:logger:message`, python's default logging format, which is what a
# subprocess running python leaves its records in
LOG_LINE = re.compile(r"(DEBUG|INFO|WARNING|ERROR|CRITICAL):[\w.]*:(.*)", re.DOTALL)
LOG_LEVELS = logging.getLevelNamesMapping()


def log_output(output, prefix, logger, level=logging.INFO):
    """Log the output of a subprocess, so it goes through our logger instead of
    landing on the worker's stdout. Takes captured output or a pipe to read."""
    if output is None:
        return
    if isinstance(output, (str, bytes)):
        output = output.splitlines()
    for line in output:
        if isinstance(line, bytes):
            line = line.decode("utf-8", "replace")
        line = line.rstrip()
        if not line:
            continue
        match = LOG_LINE.fullmatch(line)
        if match is None:
            logger.log(level, "%s: %s", prefix, line)
        else:
            name, message = match.groups()
            logger.log(LOG_LEVELS[name], "%s: %s", prefix, message)


def forward_output(stream, prefix, logger, level=logging.INFO):
    """Log what a running subprocess writes, in a thread of its own. Draining
    the pipe also keeps the process from blocking on a full one."""

    def drain():
        try:
            with stream:
                log_output(stream, prefix, logger, level)
        except (OSError, ValueError):
            pass  # the pipe was closed on us, e.g. by a killed process

    thread = threading.Thread(target=drain, name=f"logs-{prefix}", daemon=True)
    thread.start()
    return thread


class ShellSupport(object):
    """Provides helpers for shell commands."""

    #: Conversion time before the job gets cancelled.
    COMMAND_TIMEOUT = 10 * 60

    @classmethod
    def find_command(cls, name):
        config_name = "%s_BIN" % name
        config_name = config_name.replace("-", "_").upper()
        return env.get(config_name, shutil.which(name))

    def exec_command(self, command, *args):
        binary = self.find_command(command)
        if binary is None:
            raise RuntimeError("Program not found: %s" % command)
        cmd = [binary]
        cmd.extend([path_string(a) for a in args])
        try:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as ose:
            raise ProcessingException("Error: %s" % ose) from ose
        with process:
            # logged as it comes, so nothing buffers the hours of output a
            # readpst run can produce. Its stdout is progress chatter, stderr
            # is where these tools complain
            logs = [
                forward_output(process.stdout, command, log, logging.DEBUG),
                forward_output(process.stderr, command, log),
            ]
            try:
                code = process.wait(self.COMMAND_TIMEOUT)
            except subprocess.TimeoutExpired as timeout:
                process.kill()
                raise ProcessingException("Processing timed out.") from timeout
            for thread in logs:
                thread.join(1)  # the last lines, before `with` closes the pipes

        if code != 0:
            raise ProcessingException("Failed: %s" % " ".join(cmd))

    def assert_outfile(self, path):
        if not path.exists():
            raise ProcessingException("File missing: {}".format(path))
