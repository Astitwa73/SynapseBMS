"""Logging setup.

The simulation runs on a background thread, where an unhandled exception is
invisible by default: the thread dies, the main program keeps going, and the
dashboard simply stops updating with no explanation. Structured logs with thread
names are what make that failure legible.
"""

from __future__ import annotations

import logging

LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"
TIME_FORMAT = "%H:%M:%S"


def configure_logging(level: int = logging.INFO) -> None:
    """Install a console log handler. Safe to call more than once."""
    logging.basicConfig(level=level, format=LOG_FORMAT, datefmt=TIME_FORMAT, force=True)
