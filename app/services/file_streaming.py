"""
Range requests for video streaming (206 Partial Content).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path


def parse_range_header(range_header: str | None, file_size: int) -> tuple[int, int] | None:
    """
    Parse ``Range: bytes=start-end`` (or open-ended). Returns (start, end) inclusive.
    """
    if not range_header or not range_header.strip().lower().startswith("bytes="):
        return None
    spec = range_header.split("=", 1)[1].strip()
    m = re.match(r"^(\d*)-(\d*)$", spec)
    if not m:
        return None
    start_s, end_s = m.group(1), m.group(2)
    if start_s == "" and end_s != "":
        length = int(end_s)
        if length <= 0:
            return None
        start = max(0, file_size - length)
        end = file_size - 1
    elif start_s != "" and end_s == "":
        start = int(start_s)
        end = file_size - 1
    elif start_s != "" and end_s != "":
        start, end = int(start_s), int(end_s)
    else:
        return None
    if start < 0 or start >= file_size:
        return None
    end = min(end, file_size - 1)
    if end < start:
        return None
    return start, end


def iter_file_bytes(path: Path, start: int, end: int, chunk: int = 1024 * 512) -> Iterator[bytes]:
    """Read [start, end] inclusive in chunks (512 KiB default for Pi)."""
    to_read = end - start + 1
    with path.open("rb") as f:
        f.seek(start)
        while to_read > 0:
            n = min(chunk, to_read)
            block = f.read(n)
            if not block:
                break
            to_read -= len(block)
            yield block
