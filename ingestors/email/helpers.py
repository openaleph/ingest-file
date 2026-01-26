import re
from pathlib import Path

from ingestors.exc import ProcessingException


def fix_rfc822(file_path: Path) -> bytes:
    try:
        headers_done = False
        with open(file_path, "rb") as fh:
            lines = fh.readlines()
            # find broken headers and fix them
            fixed_lines = []
            # the header key can have \s before and after ":"
            pattern = re.compile(rb"^([A-Za-z0-9-]+\s?:)\s")
            for line in lines:
                if headers_done:
                    fixed_lines.append(line)
                else:
                    # the first empty line + \n ends the headers
                    if line == b"\n":
                        fixed_lines.append(line)
                        headers_done = True
                        continue
                    # the boundary value is part of the Content-Type header
                    # sometimes on a new line starting with \t
                    if not line[:1].isalpha():
                        fixed_lines.append(line)
                        continue
                    # all headers must contain ":"
                    match = re.match(pattern, line)
                    if not match:
                        # if ":" is missing
                        # insert it after the header key
                        idx_space = line.index(b" ")
                        line = line[:idx_space] + b":" + line[idx_space:]
                    fixed_lines.append(line)
        return b"".join(fixed_lines)
    except (ValueError, IndexError) as err:
        raise ProcessingException(f"Cannot parse email: {err}") from err
