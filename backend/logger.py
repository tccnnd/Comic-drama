"""Centralized logging configuration for the Comic Drama backend."""

from __future__ import annotations

import logging
import os


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger for the given module name.

    The log level defaults to INFO and can be overridden via the LOG_LEVEL
    environment variable (e.g. DEBUG, WARNING, ERROR).
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
        level = getattr(logging, level_name, logging.INFO)

        handler = logging.StreamHandler()
        handler.setLevel(level)

        formatter = logging.Formatter(
            fmt="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)

        logger.addHandler(handler)
        logger.setLevel(level)

    return logger
