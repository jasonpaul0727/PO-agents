"""Tests for sample-request config loader."""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.sample_request.config import Config, load_config


REQUIRED_ENV = {
    "SAMPLE_REQUEST_WAREHOUSE_EMAIL": "warehouse@example.com",
    "ANTHROPIC_API_KEY": "sk-ant-test",
}


def test_load_config_with_minimal_env_uses_defaults():
    cfg = load_config(REQUIRED_ENV)
    assert cfg.warehouse_email == "warehouse@example.com"
    assert cfg.anthropic_api_key == "sk-ant-test"
    assert cfg.followup_threshold_hours == 4.0
    assert cfg.po_model == "claude-opus-4-8"
    assert cfg.state_file == Path(".sample_requests_state.json")
    assert cfg.token_path == Path("secrets/token.json")
    assert cfg.credentials_path == Path("secrets/credentials.json")
    assert cfg.log_path == Path("logs/sample_request_tick.log")


def test_load_config_overrides_take_effect():
    env = {
        **REQUIRED_ENV,
        "SAMPLE_REQUEST_FOLLOWUP_HOURS": "6.5",
        "SAMPLE_REQUEST_STATE_FILE": "/tmp/state.json",
        "PO_MODEL": "claude-opus-4-7",
    }
    cfg = load_config(env)
    assert cfg.followup_threshold_hours == 6.5
    assert cfg.state_file == Path("/tmp/state.json")
    assert cfg.po_model == "claude-opus-4-7"


def test_load_config_missing_required_lists_all():
    with pytest.raises(ValueError) as excinfo:
        load_config({})
    msg = str(excinfo.value)
    assert "SAMPLE_REQUEST_WAREHOUSE_EMAIL" in msg
    assert "ANTHROPIC_API_KEY" in msg


def test_config_is_pydantic_model_and_immutable():
    cfg = load_config(REQUIRED_ENV)
    assert isinstance(cfg, Config)
    with pytest.raises(Exception):
        cfg.warehouse_email = "other@example.com"
