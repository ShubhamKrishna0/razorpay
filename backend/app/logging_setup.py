"""Structured-ish logging that reads well in Render's log stream."""

from __future__ import annotations

import logging
import sys

from app.config import settings

_FORMAT = "%(asctime)s %(levelname)-7s %(name)-28s %(message)s"


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt="%H:%M:%S"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())
    for noisy in ("httpx", "httpcore", "urllib3", "anthropic._base_client"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
