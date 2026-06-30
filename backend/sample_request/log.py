"""Structured JSON line logger for sample-request tick runs."""
from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "sample_request"


def make_tick_id() -> str:
    return secrets.token_hex(4)


class _JsonFormatter(logging.Formatter):
    _LEVEL_MAP = {"WARNING": "WARN", "CRITICAL": "FATAL"}
    _STANDARD = {
        "name", "msg", "args", "levelname", "levelno", "pathname",
        "filename", "module", "exc_info", "exc_text", "stack_info",
        "lineno", "funcName", "created", "msecs", "relativeCreated",
        "thread", "threadName", "processName", "process", "message",
        "taskName",
    }

    def __init__(self, tick_id: str) -> None:
        super().__init__()
        self._tick_id = tick_id

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc)
        payload = {
            "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "level": self._LEVEL_MAP.get(record.levelname, record.levelname),
            "tick_id": self._tick_id,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in self._STANDARD or key.startswith("_"):
                continue
            payload[key] = value
        return json.dumps(payload, ensure_ascii=False)


def setup_logger(log_path: Path, tick_id: str) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(LOGGER_NAME)
    # Clear previous handlers so re-setup picks up the new tick_id.
    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()

    handler = RotatingFileHandler(
        log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(_JsonFormatter(tick_id))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger
