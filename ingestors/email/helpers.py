import re
from pathlib import Path

from ingestors.exc import ProcessingException


def fix_rfc822(file_path: Path) -> bytes:
    try:
        with open(file_path, "rb") as fh:
            lines = fh.readlines()
            # find broken headers and fix them
            fixed_lines = []
            # header key; can have \s before :
            pattern = re.compile(rb"^([A-Za-z0-9-]+\s?:)\s")
            for line in lines:
                # line[0] will raise IndexError if ''
                if not line[:1].isalpha():
                    break
                match = re.match(pattern, line)
                if not match:
                    # insert : after key
                    idx_space = line.index(b" ")
                    line = line[:idx_space] + b":" + line[idx_space:]
                fixed_lines.append(line)
        return b"".join(fixed_lines)
    except (ValueError, IndexError) as err:
        raise ProcessingException(f"Cannot parse email: {err}") from err
