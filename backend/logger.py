"""Centralized logging configuration for the Comic Drama backend (T2.4).

统一 logger 配置：
- StreamHandler：控制台输出，默认 INFO（LOG_LEVEL 可覆盖）
- FileHandler：WARNING+ 落盘 logs/backend.log（RotatingFileHandler，5MB x3），
  模块级共享单例，避免每个 logger 重复持有文件句柄
- 格式统一：%(asctime)s [%(name)s] %(levelname)s: %(message)s
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "backend.log"

_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

_file_handler: logging.Handler | None = None


def _get_file_handler() -> logging.Handler:
    """返回模块级共享的 WARNING+ 文件 handler（懒创建，单例）。"""
    global _file_handler
    if _file_handler is None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            LOG_FILE,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setLevel(logging.WARNING)
        handler.setFormatter(logging.Formatter(fmt=_FORMAT, datefmt=_DATEFMT))
        _file_handler = handler
    return _file_handler


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger for the given module name.

    The log level defaults to INFO and can be overridden via the LOG_LEVEL
    environment variable (e.g. DEBUG, WARNING, ERROR).
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
        level = getattr(logging, level_name, logging.INFO)

        console = logging.StreamHandler()
        console.setLevel(level)
        console.setFormatter(logging.Formatter(fmt=_FORMAT, datefmt=_DATEFMT))

        logger.addHandler(console)
        # WARNING+ 统一落盘（共享文件 handler）
        logger.addHandler(_get_file_handler())
        logger.setLevel(level)
        # 避免 root 重复传播导致双写
        logger.propagate = False

    return logger
