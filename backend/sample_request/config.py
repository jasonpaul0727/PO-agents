"""Configuration loader for the sample-request module."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from pydantic import BaseModel, ConfigDict


class Config(BaseModel):
    model_config = ConfigDict(frozen=True)

    warehouse_email: str
    followup_threshold_hours: float = 4.0
    state_file: Path = Path(".sample_requests_state.json")
    token_path: Path = Path("secrets/token.json")
    credentials_path: Path = Path("secrets/credentials.json")
    log_path: Path = Path("logs/sample_request_tick.log")
    anthropic_api_key: str
    po_model: str = "claude-opus-4-8"


_REQUIRED = ("SAMPLE_REQUEST_WAREHOUSE_EMAIL", "ANTHROPIC_API_KEY")


def load_config(env: Mapping[str, str] | None = None) -> Config:
    if env is None:
        env = os.environ

    missing = [k for k in _REQUIRED if not env.get(k)]
    if missing:
        raise ValueError(
            "missing required env vars: " + ", ".join(missing)
        )

    return Config(
        warehouse_email=env["SAMPLE_REQUEST_WAREHOUSE_EMAIL"],
        followup_threshold_hours=float(
            env.get("SAMPLE_REQUEST_FOLLOWUP_HOURS", "4.0")
        ),
        state_file=Path(env.get(
            "SAMPLE_REQUEST_STATE_FILE", ".sample_requests_state.json"
        )),
        token_path=Path(env.get(
            "SAMPLE_REQUEST_TOKEN_PATH", "secrets/token.json"
        )),
        credentials_path=Path(env.get(
            "SAMPLE_REQUEST_CREDS_PATH", "secrets/credentials.json"
        )),
        log_path=Path(env.get(
            "SAMPLE_REQUEST_LOG_PATH", "logs/sample_request_tick.log"
        )),
        anthropic_api_key=env["ANTHROPIC_API_KEY"],
        po_model=env.get("PO_MODEL", "claude-opus-4-8"),
    )
