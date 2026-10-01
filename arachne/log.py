"""Logging helpers."""

from __future__ import annotations

import logging
import sys
from typing import Optional

_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_DEFAULT_LEVEL = logging.WARNING

_configured = False


def configure(level: int | str = _DEFAULT_LEVEL, fmt: str = _FORMAT) -> None:
    """Configure the root ``arachne`` logger (idempotent)."""
    global _configured
    logger = logging.getLogger("arachne")
    logger.setLevel(level)
    if not _configured:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(fmt))
        logger.addHandler(handler)
        logger.propagate = False
        _configured = True


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return a child logger of ``arachne``, configuring defaults on first use."""
    if not _configured:
        configure()
    base = "arachne"
    return logging.getLogger(base if not name else f"{base}.{name}")


def set_level(level: int | str) -> None:
    """Convenience to change verbosity, e.g. ``set_level(logging.DEBUG)``."""
    configure(level=level)
