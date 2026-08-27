"""backend/logger 统一日志配置测试（T2.4）。"""

from __future__ import annotations

import logging
from unittest.mock import patch

import backend.logger as logger_mod
from backend.logger import get_logger


def test_get_logger_has_console_and_file_handlers():
    """get_logger 返回的 logger 含 StreamHandler 且格式统一，propagate 关闭。"""
    log = get_logger("test.t24.handlers")
    try:
        assert log.handlers, "logger 应有 handler"
        assert any(isinstance(h, logging.StreamHandler) for h in log.handlers)
        assert log.propagate is False, "应关闭 propagate 避免双写"
        for h in log.handlers:
            fmt = h.formatter._fmt if h.formatter else ""
            assert "%(asctime)s" in fmt and "%(levelname)s" in fmt
    finally:
        for h in list(log.handlers):
            log.removeHandler(h)


def test_warning_level_writes_to_log_file(tmp_path, monkeypatch):
    """WARNING+ 落盘 logs/backend.log；INFO 不落盘。"""
    log_file = tmp_path / "logs" / "backend.log"
    monkeypatch.setattr(logger_mod, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(logger_mod, "LOG_FILE", log_file)
    monkeypatch.setattr(logger_mod, "_file_handler", None)  # 重置模块级单例

    log = get_logger("test.t24.file")
    try:
        log.info("info should NOT be in file")
        log.warning("warning SHOULD be in file")
        for h in list(log.handlers):
            log.removeHandler(h)
    finally:
        monkeypatch.setattr(logger_mod, "_file_handler", None)

    text = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
    assert "warning SHOULD be in file" in text
    assert "info should NOT be in file" not in text
    assert "[test.t24.file] WARNING" in text  # 格式统一：模块名 + 级别


def test_log_file_handler_is_shared_singleton(monkeypatch):
    """文件 handler 为模块级共享单例（同一实例复用于多个 logger）。"""
    monkeypatch.setattr(logger_mod, "_file_handler", None)
    h1 = logger_mod._get_file_handler()
    h2 = logger_mod._get_file_handler()
    assert h1 is h2
    assert h1.level == logging.WARNING
