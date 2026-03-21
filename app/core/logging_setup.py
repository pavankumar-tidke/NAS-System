"""
NAS-style console logs: [HH:MM:SS.mmm] LEVEL (pid): message
Matches the pattern used by other services in the stack (e.g. Brain on :7000).
"""

from __future__ import annotations

import logging
import sys
import time
from typing import Final

_LOG_NAME: Final = "nas"
_CONFIGURED = False


class NASLogFormatter(logging.Formatter):
    """Local time + milliseconds, process id, like: [12:30:53.752] INFO (8884): ..."""

    def format(self, record: logging.LogRecord) -> str:
        lt = time.localtime(record.created)
        ts = time.strftime("%H:%M:%S", lt) + f".{int(record.msecs):03d}"
        return f"[{ts}] {record.levelname} ({record.process}): {record.getMessage()}"


def setup_nas_logging() -> None:
    """Attach a single stdout handler with NASLogFormatter to the `nas` logger."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    log = logging.getLogger(_LOG_NAME)
    log.handlers.clear()
    log.setLevel(logging.INFO)
    log.propagate = False

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(NASLogFormatter())
    log.addHandler(handler)


def get_nas_logger() -> logging.Logger:
    """Application / startup logger (call setup_nas_logging() once at import)."""
    return logging.getLogger(_LOG_NAME)
