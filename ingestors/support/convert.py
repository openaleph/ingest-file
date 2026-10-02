import atexit
import logging
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
import xmlrpc.client
from contextlib import contextmanager
from ctypes.util import find_library
from urllib.parse import urlsplit
from uuid import uuid4

from followthemoney.helpers import entity_filename
from prometheus_client import Counter

from ingestors.exc import ProcessingException
from ingestors.settings import Settings
from ingestors.support.cache import CacheSupport
from ingestors.support.temp import TempFileSupport

log = logging.getLogger(__name__)
settings = Settings()

LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
# unoserver waits 7 seconds before it listens, and LibreOffice has to come up
LISTENER_START_TIMEOUT = 60
# an inline listener kills a conversion after the convert timeout itself; the
# client waits this much longer, so it gets that answer rather than giving up
# first and converting the same stuck document once more by spawning
LISTENER_GRACE = 30
# glibc's malloc keeps the heap LibreOffice frees after a document, so the
# running listeners grow with every convert call; jemalloc, set up like this,
# frees it up.
JEMALLOC_CONF = "background_thread:true,dirty_decay_ms:1000,muzzy_decay_ms:0"


class UnoserverUnavailable(Exception):
    """The unoserver listener cannot be reached, started, or is wedged past
    the conversion timeout. Callers degrade to the LibreOffice spawn path."""


def free_ports(count):
    """Distinct local ports nothing listens on right now."""
    sockets = [socket.socket() for _ in range(count)]
    try:
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        return [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


class InlineUnoserver:
    """A unoserver listener owned by one worker thread, used when no
    `INGESTORS_UNOSERVER_URI` is configured: started on the thread's first
    conversion and kept for the next ones, like tika-python keeps its server.
    unoserver converts one document at a time, so each thread gets a listener
    of its own (own ports, own LibreOffice profile) instead of queueing behind
    a shared one. A listener that exited, e.g. after a conversion timeout, is
    started again; one that fails to start is not tried again in this thread,
    which then spawns LibreOffice per document."""

    _local = threading.local()
    _running: set["InlineUnoserver"] = set()
    _lock = threading.Lock()

    def __init__(self):
        self.process = None
        self.uri = None
        self.failed = False
        self.thread = threading.current_thread()

    @classmethod
    def for_thread(cls) -> "InlineUnoserver":
        listener = getattr(cls._local, "listener", None)
        if listener is None:
            listener = cls._local.listener = cls()
        return listener

    def ensure(self, timeout) -> str | None:
        """The uri of this thread's running listener, starting it if needed.
        None if it can't be started."""
        if self.failed:
            return None
        if self.process is None or self.process.poll() is not None:
            self.stop_orphaned()
            try:
                self.start(timeout)
            except UnoserverUnavailable as exc:
                self.failed = True
                log.warning(
                    "Inline unoserver failed to start (%s), this thread spawns "
                    "LibreOffice per document from now on",
                    exc,
                )
                return None
        return self.uri

    def start(self, timeout):
        executable = shutil.which("unoserver")
        if executable is None:
            raise UnoserverUnavailable("unoserver is not installed")
        port, uno_port = free_ports(2)
        self.uri = f"http://127.0.0.1:{port}"
        # LibreOffice inherits it through unoserver. Ahead of what the worker
        # preloads already (the image has libgomp)
        env, jemalloc = None, find_library("jemalloc")
        if jemalloc is not None:
            preload = " ".join(filter(None, (jemalloc, os.getenv("LD_PRELOAD"))))
            env = {**os.environ, "LD_PRELOAD": preload, "MALLOC_CONF": JEMALLOC_CONF}
        log.info("Starting inline unoserver on %s (jemalloc: %s)", self.uri, jemalloc)
        self.process = subprocess.Popen(
            [
                executable,
                "--interface",
                "127.0.0.1",
                "--port",
                str(port),
                "--uno-port",
                str(uno_port),
                "--conversion-timeout",
                str(timeout),
            ],
            stdin=subprocess.DEVNULL,
            env=env,
        )
        with self._lock:
            self._running.add(self)
        # it binds its port before LibreOffice is connected, but only answers
        # once it is: a reply to `info` means it is ready to convert
        proxy = xmlrpc.client.ServerProxy(self.uri, transport=_TimeoutTransport(5))
        deadline = time.monotonic() + LISTENER_START_TIMEOUT
        while self.process.poll() is None and time.monotonic() < deadline:
            try:
                proxy.info()
                return
            except OSError:
                time.sleep(0.5)
        self.stop()
        raise UnoserverUnavailable(f"no listener on {self.uri}")

    def stop(self):
        with self._lock:
            self._running.discard(self)
        if self.process is not None and self.process.poll() is None:
            # unoserver passes the signal on to its LibreOffice
            self.process.terminate()
            try:
                self.process.wait(15)
            except subprocess.TimeoutExpired:
                self.process.kill()

    @classmethod
    def stop_orphaned(cls):
        """Stop the listeners of threads that ended, e.g. with the executor of
        an event loop that finished: nothing would use them again."""
        with cls._lock:
            listeners = [x for x in cls._running if not x.thread.is_alive()]
        for listener in listeners:
            listener.stop()

    @classmethod
    def stop_all(cls):
        """Stop the listeners of all threads, so none outlives the worker."""
        with cls._lock:
            listeners = list(cls._running)
        for listener in listeners:
            listener.stop()


atexit.register(InlineUnoserver.stop_all)


class SpawnProfiles:
    """LibreOffice profiles for spawning, each used by one conversion at a time
    and kept for the next ones. LibreOffice starts itself a second time once it
    has set up a fresh profile, which more than doubles a short conversion; and
    it hands its document to a LibreOffice already running on the same
    profile, which loses some of them."""

    _free: list[str] = []
    _lock = threading.Lock()

    @classmethod
    @contextmanager
    def borrow(cls):
        with cls._lock:
            profile = cls._free.pop() if cls._free else None
        if profile is None:
            profile = tempfile.mkdtemp(prefix="soffice-profile-")
        try:
            yield profile
        finally:
            with cls._lock:
                cls._free.append(profile)

    @classmethod
    def remove_all(cls):
        with cls._lock:
            profiles, cls._free = cls._free, []
        for profile in profiles:
            shutil.rmtree(profile, ignore_errors=True)


atexit.register(SpawnProfiles.remove_all)


def run_soffice(cmd, timeout):
    """Run LibreOffice to its end. `soffice` is a wrapper that runs the actual
    LibreOffice as its child: unless the whole process group is killed on a
    timeout, LibreOffice keeps running, and keeps its profile busy."""
    process = subprocess.Popen(cmd, start_new_session=True)
    try:
        process.wait(timeout)
    except BaseException:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        raise
    if process.returncode != 0:
        raise subprocess.CalledProcessError(process.returncode, cmd)


class _TimeoutTransport(xmlrpc.client.Transport):
    """xmlrpc.client has no timeout support; a hung LibreOffice behind the
    listener must not block the worker forever."""

    def __init__(self, timeout):
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host):
        connection = super().make_connection(host)
        connection.timeout = self._timeout
        return connection


PDF_CACHE_ACCESSED = Counter(
    "ingestfile_pdf_cache_accessed",
    "Number of times the PDF cache has been accessed, by cache status",
    ["status"],
)


class DocumentConvertSupport(CacheSupport, TempFileSupport):
    """Provides helpers for UNO document conversion."""

    def document_to_pdf(self, unique_tmpdir, file_path, entity):
        key = self.cache_key("pdf", entity.first("contentHash"))
        pdf_hash = self.tags.get(key)
        if pdf_hash is not None:
            file_name = entity_filename(entity, extension="pdf")
            path = self.manager.load(pdf_hash, file_name=file_name)
            if path is not None:
                PDF_CACHE_ACCESSED.labels(status="hit").inc()
                log.info("Using PDF cache: %s", file_name)
                entity.set("pdfHash", pdf_hash)
                return path

        PDF_CACHE_ACCESSED.labels(status="miss").inc()
        pdf_file = self._document_to_pdf(unique_tmpdir, file_path, entity)
        if pdf_file is not None:
            content_hash = self.manager.store(pdf_file)
            entity.set("pdfHash", content_hash)
            self.tags.set(key, content_hash)
        return pdf_file

    def _document_to_pdf(
        self, unique_tmpdir, file_path, entity, timeout=settings.convert_timeout
    ):
        """Converts an office document to PDF through a unoserver listener:
        the configured one, else this thread's own (`InlineUnoserver`)."""
        uri, client_timeout, listener = self.settings.unoserver_uri, timeout, None
        if not uri:
            listener = InlineUnoserver.for_thread()
            uri = listener.ensure(timeout)
            client_timeout = timeout + LISTENER_GRACE
        if uri:
            try:
                return self._document_to_pdf_unoserver(
                    uri, unique_tmpdir, file_path, entity, client_timeout
                )
            except UnoserverUnavailable as exc:
                if listener is not None:
                    # it died or is wedged: the next document gets a fresh one
                    listener.stop()
                log.warning(
                    "unoserver unavailable (%s), falling back to LibreOffice spawn",
                    exc,
                )
        return self._document_to_pdf_spawn(unique_tmpdir, file_path, entity, timeout)

    def _document_to_pdf_unoserver(
        self, uri, unique_tmpdir, file_path, entity, timeout
    ):
        """Convert through a persistent unoserver listener (XML-RPC, unoserver
        API v3) instead of paying a LibreOffice process start per document.

        One attempt, no retries: connection failures and timeouts raise
        UnoserverUnavailable so the caller degrades to the spawn path for
        this document only — a wedged or busy listener must never queue work
        behind it (see the convert-document history, alephdata/ingest-file#395).
        Conversion errors for broken/encrypted documents raise
        ProcessingException without touching the spawn path, since the spawn
        would fail on those all the same, just slower.
        """
        log.info("Converting [%s] to PDF via unoserver", entity)
        # a name of its own for every call: listeners outlive a conversion, and
        # the spawn fallback may run in the same directory right after
        out_file = os.path.join(unique_tmpdir, f"{uuid4().hex}.pdf")
        # A listener on localhost shares our filesystem: hand it paths and
        # let it read/write directly. A remote listener gets the bytes over
        # XML-RPC and returns the PDF the same way.
        local = urlsplit(uri).hostname in LOCAL_HOSTS
        inpath = os.path.abspath(str(file_path)) if local else None
        indata = None
        if not local:
            with open(file_path, "rb") as fh:
                indata = fh.read()
        proxy = xmlrpc.client.ServerProxy(
            uri, allow_none=True, transport=_TimeoutTransport(timeout)
        )
        try:
            # convert(inpath, indata, outpath, convert_to, filtername,
            #         filter_options, update_index, infiltername, password)
            # `password` needs unoserver >= 3.5 (the listener image ships
            # 3.7), older servers fault on the 9th argument.
            result = proxy.convert(
                inpath,
                indata,
                out_file if local else None,
                "pdf",
                None,
                [],
                True,
                None,
                None,
            )
        except xmlrpc.client.Fault as exc:
            raise ProcessingException("Could not be converted to PDF") from exc
        except OSError as exc:
            raise UnoserverUnavailable(str(exc)) from exc
        if not local:
            data = result.data if result is not None else None
            if not data:
                raise ProcessingException("Could not be converted to PDF")
            with open(out_file, "wb") as fh:
                fh.write(data)
        if not os.path.exists(out_file) or os.stat(out_file).st_size == 0:
            raise ProcessingException("Could not be converted to PDF")
        log.info(f"Successfully converted {out_file} via unoserver")
        return out_file

    def _document_to_pdf_spawn(
        self, unique_tmpdir, file_path, entity, timeout=settings.convert_timeout
    ):
        """Converts an office document to PDF by spawning a LibreOffice process
        per document."""
        file_name = entity_filename(entity)
        log.info("Converting [%s] to PDF", entity)

        # a fresh directory per call: the PDF is found by listing it
        pdf_output_dir = tempfile.mkdtemp(dir=unique_tmpdir)
        try:
            with SpawnProfiles.borrow() as profile:
                cmd = [
                    settings.soffice_bin,
                    "-env:UserInstallation=file://{}".format(profile),
                    "--nologo",
                    "--headless",
                    "--nocrashreport",
                    "--nodefault",
                    "--norestore",
                    "--nolockcheck",
                    "--invisible",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    pdf_output_dir,
                    file_path,
                ]
                log.info(f"Starting LibreOffice: {cmd} with timeout {timeout}")
                try:
                    run_soffice(cmd, timeout)
                except Exception as e:
                    raise ProcessingException("Could not be converted to PDF") from e

            for file_name in os.listdir(pdf_output_dir):
                if not file_name.endswith(".pdf"):
                    continue
                out_file = os.path.join(pdf_output_dir, file_name)
                if os.stat(out_file).st_size == 0:
                    continue
                log.info(f"Successfully converted {out_file}")
                return out_file
            raise ProcessingException("Could not be converted to PDF")
        except Exception as e:
            raise ProcessingException("Could not be converted to PDF") from e
