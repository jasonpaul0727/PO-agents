"""Tests for the JSON line logger."""
from __future__ import annotations

import json
import re
from pathlib import Path

from backend.sample_request.log import make_tick_id, setup_logger


def test_make_tick_id_is_8_hex_chars():
    tid = make_tick_id()
    assert re.fullmatch(r"[0-9a-f]{8}", tid)


def test_make_tick_id_is_random():
    seen = {make_tick_id() for _ in range(100)}
    assert len(seen) > 95   # vanishingly unlikely to collide


def test_setup_logger_writes_json_lines_with_tick_id(tmp_path):
    log_path = tmp_path / "tick.log"
    logger = setup_logger(log_path, "deadbeef")
    logger.info("hello", extra={"step": "ingest", "thread_id": "abc"})
    logger.warning("careful", extra={"step": "send_followups"})

    lines = log_path.read_text().splitlines()
    assert len(lines) == 2

    first = json.loads(lines[0])
    assert first["level"] == "INFO"
    assert first["tick_id"] == "deadbeef"
    assert first["step"] == "ingest"
    assert first["thread_id"] == "abc"
    assert first["msg"] == "hello"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", first["ts"])

    second = json.loads(lines[1])
    assert second["level"] == "WARN"
    assert second["step"] == "send_followups"


def test_setup_logger_idempotent_no_duplicate_handlers(tmp_path):
    log_path = tmp_path / "tick.log"
    logger = setup_logger(log_path, "aaaaaaaa")
    logger = setup_logger(log_path, "bbbbbbbb")
    logger.info("once")
    lines = log_path.read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["tick_id"] == "bbbbbbbb"
