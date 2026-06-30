"""Shared pytest fixtures for sample_request tests."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.sample_request.config import Config
from backend.sample_request.tests.fake_gmail import FakeGmailClient


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(
        warehouse_email="warehouse@example.com",
        followup_threshold_hours=4.0,
        state_file=tmp_path / "state.json",
        token_path=tmp_path / "secrets" / "token.json",
        credentials_path=tmp_path / "secrets" / "credentials.json",
        log_path=tmp_path / "logs" / "tick.log",
        anthropic_api_key="sk-ant-test",
        po_model="claude-opus-4-8",
    )


@pytest.fixture
def fake_gmail() -> FakeGmailClient:
    return FakeGmailClient()
