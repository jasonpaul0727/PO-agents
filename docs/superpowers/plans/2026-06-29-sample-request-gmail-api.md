# Sample Request Gmail-API Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Claude-session-based sample-request executor with a pure-Python module (`backend/sample_request/`) that talks to Gmail directly via OAuth, driven by cron every 2 hours.

**Architecture:** Externally-triggered, stateless tick. Cron runs `python3 -m backend.sample_request tick` every 2 hours; one process completes all work for the cycle and exits. Authoritative state lives in Gmail labels (`sample-request/pending-release`, `draft-ready`, `released`, `shipped`, `needs-attention`); `.sample_requests_state.json` is a metadata cache. Hybrid send mode: first release email is a Gmail *draft* (human reviews & sends), follow-ups are auto-sent.

**Tech Stack:** Python 3.12, anthropic SDK (parsing), `google-api-python-client` / `google-auth` / `google-auth-oauthlib` (Gmail), pydantic v2, pytest.

## Global Constraints

- Python: 3.12 (project baseline).
- `requirements.txt` floors: `google-api-python-client>=2.140`, `google-auth>=2.34`, `google-auth-oauthlib>=1.2`, `google-auth-httplib2>=0.2`. Reuse existing `anthropic>=0.69`, `pydantic>=2.9`, `python-dotenv>=1.0`.
- State file path: `.sample_requests_state.json` at repo root (unchanged).
- OAuth credentials path: `secrets/credentials.json`; token cache: `secrets/token.json`. `secrets/` is gitignored.
- Log path: `logs/sample_request_tick.log`, rotated at 10 MB, keep 5.
- Gmail label namespace: `sample-request/<state>`. The five labels are `pending-release`, `draft-ready`, `released`, `shipped`, `needs-attention`.
- UPS tracking regex: `\b1Z[0-9A-Z]{16}\b` (already in old script; do not change).
- Default follow-up threshold: 4 hours.
- Crontab: `0 */2 * * *` (every 2 hours).
- All new code uses `from __future__ import annotations` and PEP 604 type hints, matching the existing script's style.
- Spec is the source of truth: `docs/superpowers/specs/2026-06-29-sample-request-gmail-api-design.md`.

---

## File Structure

```
backend/sample_request/
├── __init__.py
├── __main__.py            # enables `python -m backend.sample_request <cmd>`
├── cli.py                 # argparse entry, orchestrates tick steps
├── auth.py                # standalone OAuth setup runner
├── gmail_client.py        # Gmail API thin wrapper (OAuth + reads + writes + labels)
├── parser.py              # Claude structured parsing via anthropic.messages.parse
├── sender.py              # release & follow-up email body builders
├── state.py               # state.json load/save + schema v2 helpers
├── config.py              # pydantic Config + load_config from env
├── log.py                 # JSON logging setup
├── README.md              # one-time setup + smoke checklist
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── fake_gmail.py      # in-memory test double for GmailClient
    ├── test_config.py
    ├── test_log.py
    ├── test_state.py
    ├── test_parser.py
    ├── test_sender.py
    ├── test_cli_ingest.py
    ├── test_cli_detect_sent.py
    ├── test_cli_check_shipments.py
    ├── test_cli_send_followups.py
    ├── test_cli_errors.py
    ├── test_cli_dry_run.py
    └── test_cli_status.py

scripts/sample_followup_tick.py  # reduced to 5-line shim delegating to cli.main
secrets/.gitkeep                  # placeholder so empty dir is in repo
logs/.gitkeep
```

---

## Task 1: Bootstrap deps, directories, .env, .gitignore

**Files:**
- Modify: `requirements.txt`
- Modify: `.env.example`
- Modify: `.gitignore`
- Create: `backend/sample_request/__init__.py`
- Create: `backend/sample_request/__main__.py`
- Create: `backend/sample_request/tests/__init__.py`
- Create: `secrets/.gitkeep`
- Create: `logs/.gitkeep`

**Interfaces:**
- Consumes: nothing
- Produces: `python3 -m backend.sample_request --help` (will print argparse help once `cli.py` arrives in Task 10; for now, `__main__.py` raises NotImplementedError if invoked)

- [ ] **Step 1: Append Gmail libraries to `requirements.txt`**

Open `requirements.txt`, append at end:

```
# ---- sample-request module ----
google-api-python-client>=2.140
google-auth>=2.34
google-auth-oauthlib>=1.2
google-auth-httplib2>=0.2
```

- [ ] **Step 2: Append sample-request env vars to `.env.example`**

Open `.env.example`, append at end:

```
# ---- sample request module ----
SAMPLE_REQUEST_WAREHOUSE_EMAIL=warehouse@example.com
SAMPLE_REQUEST_FOLLOWUP_HOURS=4
SAMPLE_REQUEST_STATE_FILE=.sample_requests_state.json
SAMPLE_REQUEST_TOKEN_PATH=secrets/token.json
SAMPLE_REQUEST_CREDS_PATH=secrets/credentials.json
SAMPLE_REQUEST_LOG_PATH=logs/sample_request_tick.log
# anthropic reuses existing ANTHROPIC_API_KEY / PO_MODEL
```

- [ ] **Step 3: Add ignores to `.gitignore`**

Append at end of `.gitignore`:

```
# sample-request secrets and runtime artefacts
secrets/
!secrets/.gitkeep
.sample_requests_state.json.dryrun.*
logs/sample_request_*.log*
```

- [ ] **Step 4: Create empty directory placeholders**

```bash
mkdir -p backend/sample_request/tests secrets logs
touch secrets/.gitkeep logs/.gitkeep
```

- [ ] **Step 5: Create `backend/sample_request/__init__.py`**

```python
"""Sample-request Gmail-API integration.

See docs/superpowers/specs/2026-06-29-sample-request-gmail-api-design.md.
"""
```

- [ ] **Step 6: Create `backend/sample_request/__main__.py`**

```python
"""Entry point for `python -m backend.sample_request`."""
from __future__ import annotations

import sys


def main() -> int:
    try:
        from backend.sample_request.cli import main as cli_main
    except ImportError:
        # cli.py is implemented in Task 10; until then, fail loudly.
        print(
            "backend.sample_request.cli not implemented yet — see plan Task 10",
            file=sys.stderr,
        )
        return 2
    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 7: Create `backend/sample_request/tests/__init__.py`** (empty file)

```bash
: > backend/sample_request/tests/__init__.py
```

- [ ] **Step 8: Install new dependencies and sanity-check imports**

Run:

```bash
pip install -r requirements.txt
python3 -c "import googleapiclient, google.oauth2.credentials, google_auth_oauthlib.flow; print('ok')"
```

Expected output: `ok`

- [ ] **Step 9: Verify `python -m backend.sample_request` errors cleanly (cli.py not yet present)**

Run:

```bash
python3 -m backend.sample_request 2>&1 ; echo "exit=$?"
```

Expected output:

```
backend.sample_request.cli not implemented yet — see plan Task 10
exit=2
```

- [ ] **Step 10: Commit**

```bash
git add requirements.txt .env.example .gitignore \
  backend/sample_request/__init__.py \
  backend/sample_request/__main__.py \
  backend/sample_request/tests/__init__.py \
  secrets/.gitkeep logs/.gitkeep
git commit -m "feat(sample_request): bootstrap module scaffolding and Gmail deps"
```

---

## Task 2: `config.py` — Config dataclass and `load_config`

**Files:**
- Create: `backend/sample_request/config.py`
- Create: `backend/sample_request/tests/test_config.py`

**Interfaces:**
- Consumes: process environment variables
- Produces:
  ```python
  class Config(pydantic.BaseModel):
      warehouse_email: str
      followup_threshold_hours: float = 4.0
      state_file: Path
      token_path: Path
      credentials_path: Path
      log_path: Path
      anthropic_api_key: str
      po_model: str = "claude-opus-4-8"

  def load_config(env: Mapping[str, str] | None = None) -> Config
      # raises ValueError listing all missing required env vars
  ```

- [ ] **Step 1: Write the failing tests**

Create `backend/sample_request/tests/test_config.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/sample_request/tests/test_config.py -v`

Expected: 4 failures with `ImportError` or `ModuleNotFoundError: backend.sample_request.config`.

- [ ] **Step 3: Implement `config.py`**

Create `backend/sample_request/config.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/sample_request/tests/test_config.py -v`

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/sample_request/config.py backend/sample_request/tests/test_config.py
git commit -m "feat(sample_request): config loader with env validation"
```

---

## Task 3: `log.py` — JSON line logger with tick_id

**Files:**
- Create: `backend/sample_request/log.py`
- Create: `backend/sample_request/tests/test_log.py`

**Interfaces:**
- Consumes: `Config.log_path`
- Produces:
  ```python
  def make_tick_id() -> str                                # 8-char hex
  def setup_logger(log_path: Path, tick_id: str) -> logging.Logger
      # writes JSON lines to log_path (RotatingFileHandler 10MB x 5)
      # every record carries tick_id automatically
  ```

- [ ] **Step 1: Write the failing tests**

Create `backend/sample_request/tests/test_log.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/sample_request/tests/test_log.py -v`

Expected: 4 failures with `ModuleNotFoundError: backend.sample_request.log`.

- [ ] **Step 3: Implement `log.py`**

Create `backend/sample_request/log.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/sample_request/tests/test_log.py -v`

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/sample_request/log.py backend/sample_request/tests/test_log.py
git commit -m "feat(sample_request): JSON line logger with tick_id"
```

---

## Task 4: `state.py` — migrated state functions + schema v2 helpers

**Files:**
- Create: `backend/sample_request/state.py`
- Create: `backend/sample_request/tests/test_state.py`

**Interfaces:**
- Consumes: `Config.state_file`
- Produces:
  ```python
  SCHEMA_VERSION = 2
  UPS_TRACKING_RE = re.compile(r"\b1Z[0-9A-Z]{16}\b")

  def now_iso() -> str
  def parse_iso(ts: str) -> datetime
  def load_state(path: Path) -> dict                    # returns dict with meta+requests
  def save_state(path: Path, state: dict) -> None       # atomic via tmp+rename
  def find_request(state: dict, thread_id: str) -> dict | None
  def last_contact_at(req: dict) -> datetime

  def add_request(state, *, thread_id, message_id, subject, from_, received_at, parsed) -> dict
  def mark_draft_created(state, thread_id, draft_id, draft_created_at=None) -> None
  def mark_released(state, thread_id, release_message_id, warehouse_thread_id, released_at) -> None
  def mark_shipped(state, thread_id, tracking, shipped_at=None) -> None
  def record_followup(state, thread_id, message_id, sent_at=None) -> None
  def append_tick_error(state, thread_id, *, step, error_class, message, raw_excerpt=None) -> int
  def update_meta(state, *, last_tick_at, last_tick_outcome) -> None
  def bump_ingest_failure(state, message_id: str) -> int
  def reset_ingest_failure(state, message_id: str) -> None
  ```

- [ ] **Step 1: Write the failing tests**

Create `backend/sample_request/tests/test_state.py`:

```python
"""Tests for state.py — schema v2, migration, and mutation helpers."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.sample_request import state as S


def _seed_v1(path: Path) -> None:
    """Write an old-schema (no meta) state file with one released request."""
    path.write_text(json.dumps({
        "requests": [{
            "thread_id": "T1",
            "original_message_id": "M1",
            "subject": "Sample request to Polar",
            "from": "yanxiabu001@gmail.com",
            "received_at": "2026-06-29T09:18:05Z",
            "parsed": {"recipient": "Y", "address": "A", "items": []},
            "warehouse_thread_id": "W1",
            "release_message_id": "W1",
            "released_at": "2026-06-29T09:21:17Z",
            "follow_ups": [],
            "ups_tracking_no": None,
            "shipped_at": None,
            "status": "released",
        }]
    }))


def test_load_state_missing_file_returns_empty_v2(tmp_path):
    state = S.load_state(tmp_path / "missing.json")
    assert state == {
        "meta": {
            "schema_version": 2,
            "last_tick_at": None,
            "last_tick_outcome": None,
        },
        "requests": [],
        "ingest_failure_counts": {},
    }


def test_load_state_v1_file_is_upgraded_in_memory(tmp_path):
    p = tmp_path / "s.json"
    _seed_v1(p)
    state = S.load_state(p)
    assert state["meta"]["schema_version"] == 2
    assert state["meta"]["last_tick_at"] is None
    assert len(state["requests"]) == 1
    assert state["requests"][0]["status"] == "released"


def test_save_state_writes_atomic_and_round_trips(tmp_path):
    p = tmp_path / "s.json"
    state = S.load_state(p)
    state["requests"].append({"thread_id": "X"})
    S.save_state(p, state)
    reloaded = json.loads(p.read_text())
    assert reloaded["requests"] == [{"thread_id": "X"}]
    # tmp file should not linger
    assert not (tmp_path / "s.json.tmp").exists()


def test_add_request_appends_and_returns_record(tmp_path):
    state = S.load_state(tmp_path / "s.json")
    req = S.add_request(
        state,
        thread_id="T2", message_id="M2",
        subject="Sample request — test", from_="x@y.z",
        received_at="2026-06-29T22:00:00Z",
        parsed={"recipient": "Bob", "address": "1 St", "items": []},
    )
    assert req["status"] == "draft_created"
    assert req["draft_id"] is None
    assert req["follow_ups"] == []
    assert req["tick_errors"] == []
    assert state["requests"][-1] is req


def test_add_request_rejects_duplicate_message_id(tmp_path):
    state = S.load_state(tmp_path / "s.json")
    S.add_request(
        state, thread_id="T1", message_id="M1",
        subject="s", from_="x", received_at="2026-06-29T00:00:00Z",
        parsed={},
    )
    with pytest.raises(ValueError, match="duplicate"):
        S.add_request(
            state, thread_id="T1b", message_id="M1",
            subject="s", from_="x", received_at="2026-06-29T00:00:00Z",
            parsed={},
        )


def test_mark_draft_created_sets_fields(tmp_path):
    state = S.load_state(tmp_path / "s.json")
    S.add_request(state, thread_id="T", message_id="M", subject="s",
                  from_="x", received_at="2026-06-29T00:00:00Z", parsed={})
    S.mark_draft_created(state, "T", draft_id="d-1")
    req = S.find_request(state, "T")
    assert req["draft_id"] == "d-1"
    assert req["draft_created_at"] is not None


def test_mark_released_transitions_status(tmp_path):
    state = S.load_state(tmp_path / "s.json")
    S.add_request(state, thread_id="T", message_id="M", subject="s",
                  from_="x", received_at="2026-06-29T00:00:00Z", parsed={})
    S.mark_draft_created(state, "T", draft_id="d-1")
    S.mark_released(
        state, "T",
        release_message_id="W1",
        warehouse_thread_id="W1",
        released_at="2026-06-29T10:00:00Z",
    )
    req = S.find_request(state, "T")
    assert req["status"] == "released"
    assert req["release_message_id"] == "W1"
    assert req["warehouse_thread_id"] == "W1"
    assert req["released_at"] == "2026-06-29T10:00:00Z"


def test_mark_shipped_validates_ups_regex(tmp_path):
    state = S.load_state(tmp_path / "s.json")
    S.add_request(state, thread_id="T", message_id="M", subject="s",
                  from_="x", received_at="2026-06-29T00:00:00Z", parsed={})
    with pytest.raises(ValueError, match="UPS"):
        S.mark_shipped(state, "T", "not-a-real-tracking")
    S.mark_shipped(state, "T", "1ZA1234567890123456")
    req = S.find_request(state, "T")
    assert req["status"] == "shipped"
    assert req["ups_tracking_no"] == "1ZA1234567890123456"


def test_record_followup_appends_and_sets_last_contact(tmp_path):
    state = S.load_state(tmp_path / "s.json")
    S.add_request(state, thread_id="T", message_id="M", subject="s",
                  from_="x", received_at="2026-06-29T00:00:00Z", parsed={})
    S.mark_released(state, "T", "W", "W", "2026-06-29T10:00:00Z")
    S.record_followup(state, "T", message_id="F1", sent_at="2026-06-29T15:00:00Z")
    S.record_followup(state, "T", message_id="F2", sent_at="2026-06-29T19:00:00Z")
    req = S.find_request(state, "T")
    assert [f["message_id"] for f in req["follow_ups"]] == ["F1", "F2"]
    assert S.last_contact_at(req).isoformat() == "2026-06-29T19:00:00+00:00"


def test_append_tick_error_caps_at_ten_returns_count(tmp_path):
    state = S.load_state(tmp_path / "s.json")
    S.add_request(state, thread_id="T", message_id="M", subject="s",
                  from_="x", received_at="2026-06-29T00:00:00Z", parsed={})
    counts = [
        S.append_tick_error(
            state, "T", step="parser",
            error_class="ValidationError", message=f"err{i}",
        )
        for i in range(12)
    ]
    req = S.find_request(state, "T")
    assert counts[-1] == 10                         # capped
    assert len(req["tick_errors"]) == 10
    assert req["tick_errors"][0]["message"] == "err2"   # oldest two evicted
    assert req["tick_errors"][-1]["message"] == "err11"


def test_update_meta_writes_back(tmp_path):
    state = S.load_state(tmp_path / "s.json")
    S.update_meta(state, last_tick_at="2026-06-29T22:00:00Z", last_tick_outcome="ok")
    assert state["meta"]["last_tick_at"] == "2026-06-29T22:00:00Z"
    assert state["meta"]["last_tick_outcome"] == "ok"


def test_bump_and_reset_ingest_failure(tmp_path):
    state = S.load_state(tmp_path / "s.json")
    assert S.bump_ingest_failure(state, "M1") == 1
    assert S.bump_ingest_failure(state, "M1") == 2
    assert S.bump_ingest_failure(state, "M2") == 1
    assert state["ingest_failure_counts"] == {"M1": 2, "M2": 1}
    S.reset_ingest_failure(state, "M1")
    assert "M1" not in state["ingest_failure_counts"]
    assert state["ingest_failure_counts"] == {"M2": 1}
    # reset is idempotent on absent keys
    S.reset_ingest_failure(state, "missing")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/sample_request/tests/test_state.py -v`

Expected: 12 failures with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `state.py`**

Create `backend/sample_request/state.py`:

```python
"""State file (`.sample_requests_state.json`) load/save and mutations."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 2
UPS_TRACKING_RE = re.compile(r"\b1Z[0-9A-Z]{16}\b")
_MAX_TICK_ERRORS = 10


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def _empty_state() -> dict:
    return {
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "last_tick_at": None,
            "last_tick_outcome": None,
        },
        "requests": [],
        "ingest_failure_counts": {},
    }


def _upgrade(state: dict) -> dict:
    """In-memory migration of any older schema to v2. Never writes to disk
    on its own — the next save_state call persists the upgraded form."""
    if "meta" not in state:
        state["meta"] = {
            "schema_version": SCHEMA_VERSION,
            "last_tick_at": None,
            "last_tick_outcome": None,
        }
    state["meta"]["schema_version"] = SCHEMA_VERSION
    state.setdefault("requests", [])
    state.setdefault("ingest_failure_counts", {})
    for req in state["requests"]:
        req.setdefault("draft_id", None)
        req.setdefault("draft_created_at", None)
        req.setdefault("detect_sent_at", None)
        req.setdefault("tick_errors", [])
    return state


def load_state(path: Path) -> dict:
    if not path.exists():
        return _empty_state()
    with path.open("r", encoding="utf-8") as f:
        return _upgrade(json.load(f))


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    tmp.replace(path)


def find_request(state: dict, thread_id: str) -> dict | None:
    for req in state.get("requests", []):
        if req.get("thread_id") == thread_id:
            return req
    return None


def _find_by_message_id(state: dict, message_id: str) -> dict | None:
    for req in state.get("requests", []):
        if req.get("original_message_id") == message_id:
            return req
    return None


def last_contact_at(req: dict) -> datetime:
    follow_ups = req.get("follow_ups") or []
    if follow_ups:
        return parse_iso(follow_ups[-1]["sent_at"])
    return parse_iso(req["released_at"])


def add_request(
    state: dict,
    *,
    thread_id: str,
    message_id: str,
    subject: str,
    from_: str,
    received_at: str,
    parsed: dict,
) -> dict:
    if _find_by_message_id(state, message_id) is not None:
        raise ValueError(f"duplicate original_message_id: {message_id}")
    req = {
        "thread_id": thread_id,
        "original_message_id": message_id,
        "subject": subject,
        "from": from_,
        "received_at": received_at,
        "parsed": parsed,
        "warehouse_thread_id": None,
        "release_message_id": None,
        "released_at": None,
        "follow_ups": [],
        "ups_tracking_no": None,
        "shipped_at": None,
        "status": "draft_created",
        "draft_id": None,
        "draft_created_at": None,
        "detect_sent_at": None,
        "tick_errors": [],
    }
    state.setdefault("requests", []).append(req)
    return req


def _require(state: dict, thread_id: str) -> dict:
    req = find_request(state, thread_id)
    if req is None:
        raise KeyError(f"thread_id not found: {thread_id}")
    return req


def mark_draft_created(
    state: dict,
    thread_id: str,
    draft_id: str,
    draft_created_at: str | None = None,
) -> None:
    req = _require(state, thread_id)
    req["draft_id"] = draft_id
    req["draft_created_at"] = draft_created_at or now_iso()
    req["status"] = "draft_created"


def mark_released(
    state: dict,
    thread_id: str,
    release_message_id: str,
    warehouse_thread_id: str,
    released_at: str,
) -> None:
    req = _require(state, thread_id)
    req["release_message_id"] = release_message_id
    req["warehouse_thread_id"] = warehouse_thread_id
    req["released_at"] = released_at
    req["detect_sent_at"] = now_iso()
    req["status"] = "released"


def mark_shipped(
    state: dict,
    thread_id: str,
    tracking: str,
    shipped_at: str | None = None,
) -> None:
    if not UPS_TRACKING_RE.fullmatch(tracking):
        raise ValueError(
            f"tracking {tracking!r} does not match UPS regex {UPS_TRACKING_RE.pattern}"
        )
    req = _require(state, thread_id)
    req["ups_tracking_no"] = tracking
    req["shipped_at"] = shipped_at or now_iso()
    req["status"] = "shipped"


def record_followup(
    state: dict,
    thread_id: str,
    message_id: str,
    sent_at: str | None = None,
) -> None:
    req = _require(state, thread_id)
    req.setdefault("follow_ups", []).append({
        "sent_at": sent_at or now_iso(),
        "message_id": message_id,
    })


def append_tick_error(
    state: dict,
    thread_id: str,
    *,
    step: str,
    error_class: str,
    message: str,
    raw_excerpt: str | None = None,
) -> int:
    req = _require(state, thread_id)
    errs = req.setdefault("tick_errors", [])
    errs.append({
        "at": now_iso(),
        "step": step,
        "error_class": error_class,
        "message": message,
        "raw_excerpt": (raw_excerpt or "")[:500] or None,
    })
    if len(errs) > _MAX_TICK_ERRORS:
        del errs[: len(errs) - _MAX_TICK_ERRORS]
    return len(errs)


def update_meta(
    state: dict,
    *,
    last_tick_at: str,
    last_tick_outcome: str,
) -> None:
    state.setdefault("meta", {})
    state["meta"]["schema_version"] = SCHEMA_VERSION
    state["meta"]["last_tick_at"] = last_tick_at
    state["meta"]["last_tick_outcome"] = last_tick_outcome


def bump_ingest_failure(state: dict, message_id: str) -> int:
    """Increment and return the consecutive-failure count for a message that
    failed ingest before it could become a tracked request."""
    counts = state.setdefault("ingest_failure_counts", {})
    counts[message_id] = counts.get(message_id, 0) + 1
    return counts[message_id]


def reset_ingest_failure(state: dict, message_id: str) -> None:
    """Drop the failure counter for a message (called when it succeeds or
    is no longer relevant)."""
    counts = state.setdefault("ingest_failure_counts", {})
    counts.pop(message_id, None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/sample_request/tests/test_state.py -v`

Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/sample_request/state.py backend/sample_request/tests/test_state.py
git commit -m "feat(sample_request): state schema v2 with migration and mutation helpers"
```

---

## Task 5: `parser.py` — Claude structured parsing of request body

**Files:**
- Create: `backend/sample_request/parser.py`
- Create: `backend/sample_request/tests/test_parser.py`

**Interfaces:**
- Consumes: `Config.anthropic_api_key`, `Config.po_model`
- Produces:
  ```python
  class ParsedItem(BaseModel):
      name: str
      qty: int
      qty_unit: str = "each"
      item_number: str | None = None

  class ParsedRequest(BaseModel):
      recipient: str
      address: str
      items: list[ParsedItem]

  class ParserError(Exception): ...
  class ParserRefused(ParserError): ...
  class ParserSchemaError(ParserError): ...

  def parse_request_body(
      body: str,
      subject: str,
      *,
      client: anthropic.Anthropic | None = None,
      model: str = "claude-opus-4-8",
  ) -> ParsedRequest
  ```

- [ ] **Step 1: Write the failing tests**

Create `backend/sample_request/tests/test_parser.py`:

```python
"""Tests for parser.py — Claude structured parsing of email body."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.sample_request.parser import (
    ParsedItem,
    ParsedRequest,
    ParserRefused,
    ParserSchemaError,
    parse_request_body,
)


def _fake_client(parsed: ParsedRequest | None, *, refusal: bool = False):
    """Build a fake anthropic.Anthropic that returns a stubbed parse result."""
    response = MagicMock()
    if refusal:
        response.stop_reason = "refusal"
        response.parsed = None
    else:
        response.stop_reason = "end_turn"
        response.parsed = parsed
    client = MagicMock()
    client.messages.parse.return_value = response
    return client


def test_parse_returns_validated_model():
    expected = ParsedRequest(
        recipient="Bob",
        address="1 Main St",
        items=[ParsedItem(name="Widget", qty=3, qty_unit="case")],
    )
    client = _fake_client(expected)
    result = parse_request_body(
        body="please send 3 cases of Widget to Bob at 1 Main St",
        subject="Sample request",
        client=client,
        model="claude-opus-4-8",
    )
    assert result == expected
    # also confirm the SDK got our schema + the right model
    call = client.messages.parse.call_args
    assert call.kwargs["model"] == "claude-opus-4-8"
    assert call.kwargs["response_model"] is ParsedRequest


def test_parse_refusal_raises():
    client = _fake_client(None, refusal=True)
    with pytest.raises(ParserRefused):
        parse_request_body("anything", "subj", client=client)


def test_parse_schema_failure_raises():
    """If the SDK returns no parsed object (e.g. malformed JSON), raise."""
    response = MagicMock()
    response.stop_reason = "end_turn"
    response.parsed = None
    client = MagicMock()
    client.messages.parse.return_value = response
    with pytest.raises(ParserSchemaError):
        parse_request_body("body", "subj", client=client)


def test_parsed_item_defaults_qty_unit_to_each():
    item = ParsedItem(name="Widget", qty=1)
    assert item.qty_unit == "each"
    assert item.item_number is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/sample_request/tests/test_parser.py -v`

Expected: 4 failures with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `parser.py`**

Create `backend/sample_request/parser.py`:

```python
"""Email-body structured parser backed by the Anthropic SDK."""
from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    import anthropic


class ParsedItem(BaseModel):
    name: str
    qty: int
    qty_unit: str = "each"
    item_number: str | None = None


class ParsedRequest(BaseModel):
    recipient: str
    address: str
    items: list[ParsedItem]


class ParserError(Exception):
    """Base class for parser-level failures."""


class ParserRefused(ParserError):
    """Claude refused to parse the message."""


class ParserSchemaError(ParserError):
    """Claude returned a response that did not match ParsedRequest."""


_SYSTEM_PROMPT = """\
You extract structured shipping data from sample-request emails.

Return a ParsedRequest with:
- recipient: the person who should receive the sample
- address: the ship-to address as a single human-readable string
- items: list of items requested, each with name, qty, optional qty_unit
  (default "each"), and optional item_number if explicitly present in the body

The body may be informal, contain typos, or use mixed formatting. Do your best
to extract; if the body really has no shipping intent, return an empty items
list rather than refusing.
"""


def parse_request_body(
    body: str,
    subject: str,
    *,
    client: "anthropic.Anthropic | None" = None,
    model: str = "claude-opus-4-8",
) -> ParsedRequest:
    if client is None:                          # pragma: no cover - real-call path
        import anthropic
        client = anthropic.Anthropic()

    response = client.messages.parse(
        model=model,
        max_tokens=2048,
        system=_SYSTEM_PROMPT,
        response_model=ParsedRequest,
        messages=[{
            "role": "user",
            "content": f"Subject: {subject}\n\n{body}",
        }],
    )

    if getattr(response, "stop_reason", "") == "refusal":
        raise ParserRefused("Claude refused to parse the message")

    parsed = getattr(response, "parsed", None)
    if parsed is None:
        raise ParserSchemaError("Claude response did not match ParsedRequest schema")

    return parsed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/sample_request/tests/test_parser.py -v`

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/sample_request/parser.py backend/sample_request/tests/test_parser.py
git commit -m "feat(sample_request): Claude-backed structured email parser"
```

---

## Task 6: `sender.py` — release & follow-up email body builders

**Files:**
- Create: `backend/sample_request/sender.py`
- Create: `backend/sample_request/tests/test_sender.py`

**Interfaces:**
- Consumes: `ParsedRequest`, request dicts from state
- Produces:
  ```python
  def build_release_email(
      parsed: ParsedRequest,
      original_subject: str,
      original_sender: str,
  ) -> tuple[str, str]                # (subject, body)

  def build_followup_email(req: dict, n_th: int) -> str   # body only
  ```

- [ ] **Step 1: Write the failing tests**

Create `backend/sample_request/tests/test_sender.py`:

```python
"""Tests for sender.py — email body builders."""
from __future__ import annotations

import pytest

from backend.sample_request.parser import ParsedItem, ParsedRequest
from backend.sample_request.sender import build_followup_email, build_release_email


def _parsed() -> ParsedRequest:
    return ParsedRequest(
        recipient="Yanxia Patrick",
        address="1412 W 37 Pl",
        items=[
            ParsedItem(item_number="190", name="Kid snack salmon", qty=3, qty_unit="case"),
            ParsedItem(name="Widget", qty=1),
        ],
    )


def test_build_release_subject_format():
    subj, _ = build_release_email(
        _parsed(),
        original_subject="Sample request to Polar",
        original_sender="yanxiabu001@gmail.com",
    )
    assert subj == "Release Request: Sample request to Polar - Yanxia Patrick"


def test_build_release_body_has_recipient_address_items_and_ups_ask():
    _, body = build_release_email(
        _parsed(),
        original_subject="Sample request to Polar",
        original_sender="yanxiabu001@gmail.com",
    )
    assert "Recipient: Yanxia Patrick" in body
    assert "Ship-To Address: 1412 W 37 Pl" in body
    assert "Item #190 | Kid snack salmon | Qty: 3 case" in body
    assert "Widget | Qty: 1 each" in body
    assert "UPS tracking number" in body
    assert "yanxiabu001@gmail.com" in body          # "on behalf of"


def test_followup_text_differs_by_index():
    req = {
        "parsed": _parsed().model_dump(),
        "subject": "Sample request to Polar",
        "released_at": "2026-06-29T09:21:17Z",
    }
    b1 = build_followup_email(req, 1)
    b2 = build_followup_email(req, 2)
    b3 = build_followup_email(req, 3)
    assert b1 != b2 != b3
    assert "follow" in b1.lower() or "checking in" in b1.lower()
    assert "Yanxia Patrick" in b1
    assert "Item #190" in b1


def test_followup_index_out_of_range_uses_strongest_template():
    req = {
        "parsed": _parsed().model_dump(),
        "subject": "Sample request to Polar",
        "released_at": "2026-06-29T09:21:17Z",
    }
    big = build_followup_email(req, 99)
    assert big == build_followup_email(req, 3)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/sample_request/tests/test_sender.py -v`

Expected: 4 failures with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `sender.py`**

Create `backend/sample_request/sender.py`:

```python
"""Compose release-request and follow-up email bodies."""
from __future__ import annotations

from backend.sample_request.parser import ParsedRequest


def _format_item_line(item: dict) -> str:
    item_no = item.get("item_number")
    name = item["name"]
    qty = item["qty"]
    unit = item.get("qty_unit") or "each"
    if item_no:
        return f"- Item #{item_no} | {name} | Qty: {qty} {unit}"
    return f"- {name} | Qty: {qty} {unit}"


def build_release_email(
    parsed: ParsedRequest,
    original_subject: str,
    original_sender: str,
) -> tuple[str, str]:
    subject = f"Release Request: {original_subject} - {parsed.recipient}"

    item_lines = "\n".join(_format_item_line(i.model_dump()) for i in parsed.items)
    body = (
        "Hi Warehouse,\n\n"
        "Please release the following sample shipment:\n\n"
        f"Recipient: {parsed.recipient}\n"
        f"Ship-To Address: {parsed.address}\n\n"
        "Items:\n"
        f"{item_lines}\n\n"
        "Please reply to this thread with the UPS tracking number "
        "(format: 1Z…) once shipped.\n\n"
        "Thanks,\n"
        f"PO Intake Agent (on behalf of {original_sender})\n"
    )
    return subject, body


_FOLLOWUP_TEMPLATES = (
    # n=1: gentle nudge
    "Hi Warehouse,\n\n"
    "Just following up on the release request for {recipient} (sent {released_at}).\n"
    "Could you confirm whether this has shipped? When it has, please reply\n"
    "with the UPS tracking number (1Z…).\n\n"
    "Items requested:\n{items}\n\n"
    "Thanks,\n"
    "PO Intake Agent\n",

    # n=2: firmer ping
    "Hi Warehouse,\n\n"
    "Checking in again on the release request for {recipient} (sent {released_at}).\n"
    "We haven't seen a UPS tracking number come back yet — could you let me\n"
    "know the current status?\n\n"
    "Items:\n{items}\n\n"
    "Thanks,\n"
    "PO Intake Agent\n",

    # n>=3: escalation
    "Hi Warehouse,\n\n"
    "This is a final automated follow-up on the sample release request for\n"
    "{recipient} (sent {released_at}). The request has been outstanding for\n"
    "several cycles without a shipment confirmation.\n\n"
    "Please respond with either (a) the UPS tracking number, or (b) why the\n"
    "shipment is blocked.\n\n"
    "Items:\n{items}\n\n"
    "Thanks,\n"
    "PO Intake Agent\n",
)


def build_followup_email(req: dict, n_th: int) -> str:
    idx = min(max(n_th, 1), len(_FOLLOWUP_TEMPLATES)) - 1
    template = _FOLLOWUP_TEMPLATES[idx]
    parsed = req["parsed"]
    items_block = "\n".join(_format_item_line(i) for i in parsed.get("items", []))
    return template.format(
        recipient=parsed.get("recipient", "unknown"),
        released_at=req.get("released_at", "earlier"),
        items=items_block,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/sample_request/tests/test_sender.py -v`

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/sample_request/sender.py backend/sample_request/tests/test_sender.py
git commit -m "feat(sample_request): release and follow-up email body builders"
```

---

## Task 7: `tests/conftest.py` + `tests/fake_gmail.py` — in-memory Gmail test double

**Files:**
- Create: `backend/sample_request/tests/conftest.py`
- Create: `backend/sample_request/tests/fake_gmail.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  ```python
  class FakeGmailMessage(NamedTuple):
      message_id: str
      thread_id: str
      from_: str
      to: str
      subject: str
      body: str
      internal_date: str

  class FakeGmailClient:
      # same surface as GmailClient (Task 8)
      def fetch_pending(self) -> list[FakeGmailMessage]
      def fetch_sent_to(self, to: str, subject_prefix: str) -> list[FakeGmailMessage]
      def fetch_thread(self, thread_id: str) -> list[FakeGmailMessage]
      def create_draft(self, to, subject, body, in_reply_to=None) -> str
      def reply_in_thread(self, thread_id, body) -> str
      def relabel(self, message_id, remove, add) -> None
      def ensure_labels(self, names) -> dict[str, str]

      # test helpers (not on real client)
      def inject_pending(...) -> FakeGmailMessage
      def inject_thread_reply(thread_id, from_, body, internal_date=None) -> FakeGmailMessage
      def labels_on(message_id) -> set[str]
      def fail_next(method_name, times=1, exc=...)  # raise on next N calls
  ```

> No tests for this task — it is a test fixture. Subsequent CLI tests will exercise it.

- [ ] **Step 1: Create `backend/sample_request/tests/conftest.py`**

```python
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
```

- [ ] **Step 2: Create `backend/sample_request/tests/fake_gmail.py`**

```python
"""In-memory test double for GmailClient.

This is what the integration tests run against. The real GmailClient
(Task 8) provides the same surface against the Gmail API.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable


@dataclass
class FakeGmailMessage:
    message_id: str
    thread_id: str
    from_: str
    to: str
    subject: str
    body: str
    internal_date: str   # ISO UTC


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeGmailClient:
    """Test double for GmailClient with the same public surface."""

    def __init__(self) -> None:
        self._messages: dict[str, FakeGmailMessage] = {}
        self._threads: dict[str, list[str]] = defaultdict(list)
        self._labels_on: dict[str, set[str]] = defaultdict(set)
        self._labels_known: dict[str, str] = {}
        self._next_id = 1
        self._next_draft_id = 1
        self.drafts_created: list[dict] = []
        self.sent: list[dict] = []
        self._fail_plan: dict[str, list[Exception]] = defaultdict(list)

    # ---- public surface ---------------------------------------------------

    def fetch_pending(self) -> list[FakeGmailMessage]:
        self._maybe_fail("fetch_pending")
        return [
            self._messages[mid]
            for mid, labels in self._labels_on.items()
            if "sample-request/pending-release" in labels and mid in self._messages
        ]

    def fetch_sent_to(self, to: str, subject_prefix: str) -> list[FakeGmailMessage]:
        self._maybe_fail("fetch_sent_to")
        return [
            FakeGmailMessage(**s)
            for s in self.sent
            if s["to"] == to and s["subject"].startswith(subject_prefix)
        ]

    def fetch_thread(self, thread_id: str) -> list[FakeGmailMessage]:
        self._maybe_fail("fetch_thread")
        return [
            self._messages[mid]
            for mid in self._threads.get(thread_id, [])
            if mid in self._messages
        ]

    def create_draft(
        self,
        to: str,
        subject: str,
        body: str,
        in_reply_to: str | None = None,
    ) -> str:
        self._maybe_fail("create_draft")
        draft_id = f"draft-{self._next_draft_id}"
        self._next_draft_id += 1
        self.drafts_created.append({
            "draft_id": draft_id,
            "to": to,
            "subject": subject,
            "body": body,
            "in_reply_to": in_reply_to,
        })
        return draft_id

    def reply_in_thread(self, thread_id: str, body: str) -> str:
        self._maybe_fail("reply_in_thread")
        msg_id = self._mint_id("reply")
        # Pull subject from first message in the thread, prefixed with Re:
        first = self._messages[self._threads[thread_id][0]]
        subj = first.subject if first.subject.startswith("Re:") else f"Re: {first.subject}"
        msg = FakeGmailMessage(
            message_id=msg_id,
            thread_id=thread_id,
            from_="me@example.com",
            to=first.from_,
            subject=subj,
            body=body,
            internal_date=_now_iso(),
        )
        self._messages[msg_id] = msg
        self._threads[thread_id].append(msg_id)
        return msg_id

    def relabel(
        self,
        message_id: str,
        remove: list[str],
        add: list[str],
    ) -> None:
        self._maybe_fail("relabel")
        for name in remove:
            self._labels_on[message_id].discard(name)
        for name in add:
            self._labels_on[message_id].add(name)

    def ensure_labels(self, names: list[str]) -> dict[str, str]:
        self._maybe_fail("ensure_labels")
        for n in names:
            self._labels_known.setdefault(n, f"label-{len(self._labels_known)+1}")
        return {n: self._labels_known[n] for n in names}

    # ---- test helpers -----------------------------------------------------

    def inject_pending(
        self,
        from_: str,
        to: str,
        subject: str,
        body: str,
        internal_date: str | None = None,
    ) -> FakeGmailMessage:
        mid = self._mint_id("msg")
        tid = self._mint_id("thread")
        msg = FakeGmailMessage(
            message_id=mid, thread_id=tid, from_=from_, to=to,
            subject=subject, body=body,
            internal_date=internal_date or _now_iso(),
        )
        self._messages[mid] = msg
        self._threads[tid].append(mid)
        self._labels_on[mid].add("sample-request/pending-release")
        return msg

    def inject_sent(
        self,
        to: str,
        subject: str,
        body: str,
        thread_id: str | None = None,
        internal_date: str | None = None,
    ) -> dict:
        """Simulate the user having clicked Send on a draft (or a manual send)."""
        message_id = self._mint_id("sent")
        thread_id = thread_id or self._mint_id("thread")
        record = {
            "message_id": message_id,
            "thread_id": thread_id,
            "from_": "me@example.com",
            "to": to,
            "subject": subject,
            "body": body,
            "internal_date": internal_date or _now_iso(),
        }
        self.sent.append(record)
        self._messages[message_id] = FakeGmailMessage(**record)
        self._threads[thread_id].append(message_id)
        return record

    def inject_thread_reply(
        self,
        thread_id: str,
        from_: str,
        body: str,
        internal_date: str | None = None,
    ) -> FakeGmailMessage:
        mid = self._mint_id("reply")
        msg = FakeGmailMessage(
            message_id=mid, thread_id=thread_id, from_=from_,
            to="me@example.com", subject="Re: …",
            body=body,
            internal_date=internal_date or _now_iso(),
        )
        self._messages[mid] = msg
        self._threads[thread_id].append(mid)
        return msg

    def labels_on(self, message_id: str) -> set[str]:
        return set(self._labels_on.get(message_id, set()))

    def fail_next(
        self,
        method_name: str,
        times: int = 1,
        exc: Exception | Callable[[], Exception] | None = None,
    ) -> None:
        """Arm `times` upcoming calls to method_name to raise `exc`."""
        if exc is None:
            exc = RuntimeError(f"forced failure in {method_name}")
        for _ in range(times):
            self._fail_plan[method_name].append(
                exc() if callable(exc) else exc
            )

    # ---- internals --------------------------------------------------------

    def _mint_id(self, prefix: str) -> str:
        self._next_id += 1
        return f"{prefix}-{self._next_id:05d}"

    def _maybe_fail(self, method_name: str) -> None:
        plan = self._fail_plan.get(method_name)
        if plan:
            raise plan.pop(0)
```

- [ ] **Step 3: Confirm fixtures import cleanly**

Run: `pytest backend/sample_request/tests/ -v --collect-only`

Expected: collection succeeds with all previously-passing tests listed; no `ImportError`.

- [ ] **Step 4: Commit**

```bash
git add backend/sample_request/tests/conftest.py backend/sample_request/tests/fake_gmail.py
git commit -m "test(sample_request): in-memory fake Gmail client + shared fixtures"
```

---

## Task 8: `gmail_client.py` — real Gmail API wrapper

**Files:**
- Create: `backend/sample_request/gmail_client.py`

**Interfaces:**
- Consumes: `Config.token_path`, `Config.credentials_path`
- Produces (same surface as FakeGmailClient from Task 7):
  ```python
  GMAIL_SCOPES = [
      "https://www.googleapis.com/auth/gmail.modify",
      "https://www.googleapis.com/auth/gmail.compose",
  ]
  LABEL_NAMES = (
      "sample-request/pending-release",
      "sample-request/draft-ready",
      "sample-request/released",
      "sample-request/shipped",
      "sample-request/needs-attention",
  )

  @dataclass
  class GmailMessage:
      message_id: str
      thread_id: str
      from_: str
      to: str
      subject: str
      body: str
      internal_date: str

  class GmailClient:
      def __init__(self, token_path: Path, credentials_path: Path)
      def fetch_pending(self) -> list[GmailMessage]
      def fetch_sent_to(self, to: str, subject_prefix: str) -> list[GmailMessage]
      def fetch_thread(self, thread_id: str) -> list[GmailMessage]
      def create_draft(self, to, subject, body, in_reply_to=None) -> str
      def reply_in_thread(self, thread_id, body) -> str
      def relabel(self, message_id, remove, add) -> None
      def ensure_labels(self, names) -> dict[str, str]
  ```

> No unit tests for this task — per spec §6 "Out of scope for tests", we rely on the manual smoke checklist in Task 17. Read this code carefully before committing.

- [ ] **Step 1: Implement `gmail_client.py`**

Create `backend/sample_request/gmail_client.py`:

```python
"""Gmail API thin wrapper.

This file is intentionally not unit-tested (see spec §6). Integration tests
use FakeGmailClient (tests/fake_gmail.py) which mirrors this surface.
Verify behaviour via the manual smoke checklist in README.md.
"""
from __future__ import annotations

import base64
import email
import email.message
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
]

LABEL_NAMES = (
    "sample-request/pending-release",
    "sample-request/draft-ready",
    "sample-request/released",
    "sample-request/shipped",
    "sample-request/needs-attention",
)


@dataclass
class GmailMessage:
    message_id: str
    thread_id: str
    from_: str
    to: str
    subject: str
    body: str
    internal_date: str          # ISO UTC


def load_credentials(token_path: Path, credentials_path: Path) -> Credentials:
    creds: Credentials | None = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(
            str(token_path), GMAIL_SCOPES
        )
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json())
        return creds
    if not credentials_path.exists():
        raise FileNotFoundError(
            f"OAuth credentials not found at {credentials_path}. "
            "Run `python3 -m backend.sample_request.auth` first."
        )
    flow = InstalledAppFlow.from_client_secrets_file(
        str(credentials_path), GMAIL_SCOPES
    )
    creds = flow.run_local_server(port=0)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    return creds


def _internal_date_iso(ms_str: str) -> str:
    dt = datetime.fromtimestamp(int(ms_str) / 1000.0, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _extract_body(payload: dict) -> str:
    if "parts" in payload:
        for part in payload["parts"]:
            mime = part.get("mimeType", "")
            if mime == "text/plain":
                data = part.get("body", {}).get("data")
                if data:
                    return base64.urlsafe_b64decode(data + "==").decode(
                        "utf-8", errors="replace"
                    )
        for part in payload["parts"]:
            txt = _extract_body(part)
            if txt:
                return txt
    data = payload.get("body", {}).get("data")
    if data:
        return base64.urlsafe_b64decode(data + "==").decode(
            "utf-8", errors="replace"
        )
    return ""


def _headers_to_dict(headers: list[dict]) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in headers}


class GmailClient:
    def __init__(self, token_path: Path, credentials_path: Path) -> None:
        self._creds = load_credentials(token_path, credentials_path)
        self._svc = build("gmail", "v1", credentials=self._creds, cache_discovery=False)
        self._label_cache: dict[str, str] = {}

    # ---- reads ------------------------------------------------------------

    def fetch_pending(self) -> list[GmailMessage]:
        label_id = self.ensure_labels(
            ["sample-request/pending-release"]
        )["sample-request/pending-release"]
        listing = self._svc.users().messages().list(
            userId="me", labelIds=[label_id], maxResults=50,
        ).execute()
        return [self._get_message(m["id"]) for m in listing.get("messages", [])]

    def fetch_sent_to(self, to: str, subject_prefix: str) -> list[GmailMessage]:
        query = f'from:me to:{to} subject:"{subject_prefix}" newer_than:1d'
        listing = self._svc.users().messages().list(
            userId="me", q=query, maxResults=50,
        ).execute()
        return [self._get_message(m["id"]) for m in listing.get("messages", [])]

    def fetch_thread(self, thread_id: str) -> list[GmailMessage]:
        thread = self._svc.users().threads().get(
            userId="me", id=thread_id, format="full",
        ).execute()
        return [self._to_gmail_message(m) for m in thread.get("messages", [])]

    def _get_message(self, message_id: str) -> GmailMessage:
        msg = self._svc.users().messages().get(
            userId="me", id=message_id, format="full",
        ).execute()
        return self._to_gmail_message(msg)

    def _to_gmail_message(self, msg: dict) -> GmailMessage:
        payload = msg.get("payload", {})
        headers = _headers_to_dict(payload.get("headers", []))
        return GmailMessage(
            message_id=msg["id"],
            thread_id=msg["threadId"],
            from_=headers.get("from", ""),
            to=headers.get("to", ""),
            subject=headers.get("subject", ""),
            body=_extract_body(payload),
            internal_date=_internal_date_iso(msg["internalDate"]),
        )

    # ---- writes -----------------------------------------------------------

    def create_draft(
        self,
        to: str,
        subject: str,
        body: str,
        in_reply_to: str | None = None,
    ) -> str:
        mime = email.message.EmailMessage()
        mime["To"] = to
        mime["Subject"] = subject
        if in_reply_to:
            mime["In-Reply-To"] = in_reply_to
            mime["References"] = in_reply_to
        mime.set_content(body)
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
        draft = self._svc.users().drafts().create(
            userId="me", body={"message": {"raw": raw}},
        ).execute()
        return draft["id"]

    def reply_in_thread(self, thread_id: str, body: str) -> str:
        thread = self._svc.users().threads().get(
            userId="me", id=thread_id, format="metadata",
            metadataHeaders=["Subject", "From", "Message-ID"],
        ).execute()
        first = thread["messages"][0]
        headers = _headers_to_dict(first.get("payload", {}).get("headers", []))
        subj = headers.get("subject", "")
        if not subj.lower().startswith("re:"):
            subj = f"Re: {subj}"
        in_reply_to = headers.get("message-id", "")
        recipient = headers.get("from", "")

        mime = email.message.EmailMessage()
        mime["To"] = recipient
        mime["Subject"] = subj
        if in_reply_to:
            mime["In-Reply-To"] = in_reply_to
            mime["References"] = in_reply_to
        mime.set_content(body)
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
        sent = self._svc.users().messages().send(
            userId="me",
            body={"raw": raw, "threadId": thread_id},
        ).execute()
        return sent["id"]

    # ---- labels -----------------------------------------------------------

    def ensure_labels(self, names: list[str]) -> dict[str, str]:
        if all(n in self._label_cache for n in names):
            return {n: self._label_cache[n] for n in names}
        existing = self._svc.users().labels().list(userId="me").execute()
        by_name = {l["name"]: l["id"] for l in existing.get("labels", [])}
        out: dict[str, str] = {}
        for n in names:
            if n in by_name:
                out[n] = by_name[n]
            else:
                created = self._svc.users().labels().create(
                    userId="me",
                    body={
                        "name": n,
                        "labelListVisibility": "labelShow",
                        "messageListVisibility": "show",
                    },
                ).execute()
                out[n] = created["id"]
            self._label_cache[n] = out[n]
        return out

    def relabel(
        self,
        message_id: str,
        remove: list[str],
        add: list[str],
    ) -> None:
        ids = self.ensure_labels(list({*remove, *add}))
        self._svc.users().messages().modify(
            userId="me",
            id=message_id,
            body={
                "removeLabelIds": [ids[n] for n in remove if n in ids],
                "addLabelIds": [ids[n] for n in add if n in ids],
            },
        ).execute()
```

- [ ] **Step 2: Smoke-check imports**

Run:

```bash
python3 -c "from backend.sample_request.gmail_client import GmailClient, LABEL_NAMES; print(LABEL_NAMES)"
```

Expected: tuple of 5 label names printed; no import error.

- [ ] **Step 3: Commit**

```bash
git add backend/sample_request/gmail_client.py
git commit -m "feat(sample_request): real Gmail API client with OAuth and label mgmt"
```

---

## Task 9: `auth.py` — one-time OAuth setup runner

**Files:**
- Create: `backend/sample_request/auth.py`

**Interfaces:**
- Consumes: `Config.credentials_path`, `Config.token_path`
- Produces: `python3 -m backend.sample_request.auth` performs OAuth and writes token; also creates the five operational Gmail labels.

> No unit tests — exercises a browser flow that cannot be automated. Verify via Task 17 manual smoke.

- [ ] **Step 1: Implement `auth.py`**

Create `backend/sample_request/auth.py`:

```python
"""Standalone OAuth setup for sample-request.

Run once after placing `secrets/credentials.json` (downloaded from Google
Cloud Console) to obtain `secrets/token.json` and pre-create the five
operational Gmail labels.

    python3 -m backend.sample_request.auth
"""
from __future__ import annotations

import sys

from backend.sample_request.config import load_config
from backend.sample_request.gmail_client import (
    LABEL_NAMES,
    GmailClient,
    load_credentials,
)


def main() -> int:
    try:
        cfg = load_config()
    except ValueError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    if not cfg.credentials_path.exists():
        print(
            f"OAuth credentials missing at {cfg.credentials_path}.\n"
            "1. Open Google Cloud Console -> APIs & Services -> Credentials\n"
            "2. Create OAuth client ID (Desktop) -> Download JSON\n"
            f"3. Save it as {cfg.credentials_path}\n"
            "4. Re-run this command.",
            file=sys.stderr,
        )
        return 1

    print(f"Running OAuth flow with creds {cfg.credentials_path}...")
    load_credentials(cfg.token_path, cfg.credentials_path)
    print(f"Token written to {cfg.token_path}.")

    print("Ensuring Gmail labels exist...")
    client = GmailClient(cfg.token_path, cfg.credentials_path)
    ids = client.ensure_labels(list(LABEL_NAMES))
    for name in LABEL_NAMES:
        print(f"  {name}: {ids[name]}")

    print("\nNext: create a Gmail filter in the web UI matching "
          "`subject:\"sample request\"` and apply the "
          "`sample-request/pending-release` label.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Smoke-check import (does not run OAuth)**

Run:

```bash
python3 -c "from backend.sample_request.auth import main; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add backend/sample_request/auth.py
git commit -m "feat(sample_request): one-shot OAuth setup runner + label bootstrap"
```

---

## Task 10: `cli.py` — argparse skeleton + `ingest` step + first integration test

**Files:**
- Create: `backend/sample_request/cli.py`
- Create: `backend/sample_request/tests/test_cli_ingest.py`

**Interfaces:**
- Consumes: `Config`, `GmailClient` (or `FakeGmailClient`), `parser.parse_request_body`, `sender.build_release_email`, `state.add_request` / `state.mark_draft_created`
- Produces:
  ```python
  def main(argv: list[str] | None = None) -> int
      # subcommands: tick (with --dry-run), status, init (with --force)

  def run_tick(
      cfg: Config,
      *,
      gmail: GmailClientLike,
      parser_fn: Callable[[str, str], ParsedRequest],
      dry_run: bool = False,
      now: Callable[[], datetime] | None = None,
  ) -> TickResult

  class TickResult(BaseModel):
      ingested: int
      detected_sent: int
      shipped: int
      followups: int
      errors: int
      outcome: str             # "ok" | "partial" | "failed"
  ```

  In this task only the `ingest` portion of `run_tick` is wired up; later tasks add detect_sent / check_shipments / send_followups.

- [ ] **Step 1: Write the failing test**

Create `backend/sample_request/tests/test_cli_ingest.py`:

```python
"""Integration test: tick ingest step (Task 10)."""
from __future__ import annotations

from unittest.mock import MagicMock

from backend.sample_request import state as S
from backend.sample_request.cli import run_tick
from backend.sample_request.parser import ParsedItem, ParsedRequest


def _make_parser(parsed: ParsedRequest):
    def _fn(body: str, subject: str) -> ParsedRequest:
        return parsed
    return _fn


def test_ingest_new_email_creates_draft_relabels_and_records_state(
    config, fake_gmail,
):
    msg = fake_gmail.inject_pending(
        from_="customer@example.com",
        to="me@example.com",
        subject="Sample request to Polar",
        body="please send Polar Snack 3 cases to Mike at 1 Main St",
    )
    parsed = ParsedRequest(
        recipient="Mike",
        address="1 Main St",
        items=[ParsedItem(name="Polar Snack", qty=3, qty_unit="case")],
    )

    result = run_tick(config, gmail=fake_gmail, parser_fn=_make_parser(parsed))

    assert result.ingested == 1
    assert result.errors == 0
    assert len(fake_gmail.drafts_created) == 1
    draft = fake_gmail.drafts_created[0]
    assert draft["to"] == config.warehouse_email
    assert "Release Request:" in draft["subject"]
    assert "Mike" in draft["subject"]

    state = S.load_state(config.state_file)
    assert len(state["requests"]) == 1
    req = state["requests"][0]
    assert req["status"] == "draft_created"
    assert req["draft_id"] == draft["draft_id"]
    assert req["parsed"]["recipient"] == "Mike"

    labels = fake_gmail.labels_on(msg.message_id)
    assert "sample-request/pending-release" not in labels
    assert "sample-request/draft-ready" in labels


def test_ingest_idempotent_does_not_double_draft(config, fake_gmail):
    msg = fake_gmail.inject_pending(
        from_="customer@example.com",
        to="me@example.com",
        subject="Sample request again",
        body="please send Widget",
    )
    parsed = ParsedRequest(
        recipient="Bob", address="2 Main", items=[ParsedItem(name="Widget", qty=1)],
    )
    # First tick relabels msg, but pretend the user manually put the label back.
    run_tick(config, gmail=fake_gmail, parser_fn=_make_parser(parsed))
    fake_gmail.relabel(
        msg.message_id,
        remove=["sample-request/draft-ready"],
        add=["sample-request/pending-release"],
    )

    result = run_tick(config, gmail=fake_gmail, parser_fn=_make_parser(parsed))

    assert result.ingested == 0
    assert len(fake_gmail.drafts_created) == 1   # still 1 — second skipped
    # label restored to draft-ready (label state machine)
    assert "sample-request/draft-ready" in fake_gmail.labels_on(msg.message_id)


def test_tick_writes_meta_and_returns_outcome_ok(config, fake_gmail):
    result = run_tick(config, gmail=fake_gmail, parser_fn=lambda b, s: None)
    state = S.load_state(config.state_file)
    assert state["meta"]["last_tick_outcome"] == "ok"
    assert state["meta"]["last_tick_at"] is not None
    assert result.outcome == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/sample_request/tests/test_cli_ingest.py -v`

Expected: 3 failures with `ModuleNotFoundError: backend.sample_request.cli`.

- [ ] **Step 3: Implement `cli.py` skeleton + ingest step**

Create `backend/sample_request/cli.py`:

```python
"""Sample-request CLI: tick / status / init.

The `tick` subcommand is the cron entry point. It composes:
  1. ingest          (this task)
  2. detect_sent     (Task 11)
  3. check_shipments (Task 12)
  4. send_followups  (Task 13)
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from pydantic import BaseModel

from backend.sample_request import state as S
from backend.sample_request.config import Config, load_config
from backend.sample_request.log import make_tick_id, setup_logger
from backend.sample_request.parser import ParsedRequest, parse_request_body
from backend.sample_request.sender import build_release_email


LABEL_PENDING = "sample-request/pending-release"
LABEL_DRAFT = "sample-request/draft-ready"
LABEL_RELEASED = "sample-request/released"
LABEL_SHIPPED = "sample-request/shipped"
LABEL_ATTENTION = "sample-request/needs-attention"


class TickResult(BaseModel):
    ingested: int = 0
    detected_sent: int = 0
    shipped: int = 0
    followups: int = 0
    errors: int = 0
    outcome: str = "ok"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- ingest step ----------------------------------------------------------

def _ingest(cfg: Config, gmail, parser_fn, state: dict, log, *, dry_run: bool) -> int:
    msgs = gmail.fetch_pending()
    count = 0
    for msg in msgs:
        existing = next(
            (r for r in state["requests"]
             if r.get("original_message_id") == msg.message_id),
            None,
        )
        if existing is not None:
            # Already in state — just restore the label invariant and move on.
            log.info(
                "ingest skip: already in state",
                extra={"step": "ingest", "thread_id": msg.thread_id},
            )
            if not dry_run:
                gmail.relabel(
                    msg.message_id, remove=[LABEL_PENDING], add=[LABEL_DRAFT],
                )
            continue

        parsed = parser_fn(msg.body, msg.subject)
        subject, body = build_release_email(parsed, msg.subject, msg.from_)

        if dry_run:
            log.info(
                "ingest dry-run: would create draft",
                extra={
                    "step": "ingest",
                    "thread_id": msg.thread_id,
                    "subject": subject,
                },
            )
        else:
            draft_id = gmail.create_draft(
                to=cfg.warehouse_email,
                subject=subject,
                body=body,
                in_reply_to=None,
            )
            gmail.relabel(
                msg.message_id, remove=[LABEL_PENDING], add=[LABEL_DRAFT],
            )
            S.add_request(
                state,
                thread_id=msg.thread_id,
                message_id=msg.message_id,
                subject=msg.subject,
                from_=msg.from_,
                received_at=msg.internal_date,
                parsed=parsed.model_dump(),
            )
            S.mark_draft_created(state, msg.thread_id, draft_id=draft_id)
            log.info(
                "draft created",
                extra={
                    "step": "ingest",
                    "thread_id": msg.thread_id,
                    "draft_id": draft_id,
                },
            )
        count += 1
    return count


# ---- run_tick orchestrator ------------------------------------------------

def run_tick(
    cfg: Config,
    *,
    gmail,
    parser_fn: Callable[[str, str], ParsedRequest],
    dry_run: bool = False,
    now: Callable[[], datetime] | None = None,
) -> TickResult:
    now_fn = now or _now
    tick_id = make_tick_id()
    log = setup_logger(cfg.log_path, tick_id)
    log.info("tick start", extra={"step": "tick", "dry_run": dry_run})

    state_path = (
        cfg.state_file.with_suffix(cfg.state_file.suffix + f".dryrun.{tick_id}")
        if dry_run else cfg.state_file
    )
    state = S.load_state(cfg.state_file)
    result = TickResult()

    try:
        result.ingested = _ingest(cfg, gmail, parser_fn, state, log, dry_run=dry_run)
        # detect_sent / check_shipments / send_followups arrive in later tasks
    except Exception as exc:           # noqa: BLE001 — surface but keep going
        log.exception("tick failed", extra={"step": "tick"})
        result.outcome = "failed"
        S.update_meta(state, last_tick_at=_iso(now_fn()), last_tick_outcome="failed")
        S.save_state(state_path, state)
        return result

    outcome = "ok" if result.errors == 0 else "partial"
    result.outcome = outcome
    S.update_meta(state, last_tick_at=_iso(now_fn()), last_tick_outcome=outcome)
    S.save_state(state_path, state)
    log.info(
        "tick complete",
        extra={"step": "tick", "stats": result.model_dump()},
    )
    return result


# ---- CLI entry ------------------------------------------------------------

def _cmd_tick(args: argparse.Namespace) -> int:
    cfg = load_config()
    from backend.sample_request.gmail_client import GmailClient

    gmail = GmailClient(cfg.token_path, cfg.credentials_path)

    import anthropic
    ant = anthropic.Anthropic(api_key=cfg.anthropic_api_key)

    def parser_fn(body: str, subject: str) -> ParsedRequest:
        return parse_request_body(body, subject, client=ant, model=cfg.po_model)

    result = run_tick(cfg, gmail=gmail, parser_fn=parser_fn, dry_run=args.dry_run)
    return 0 if result.outcome != "failed" else 1


def _cmd_status(args: argparse.Namespace) -> int:
    # Full implementation in Task 16; placeholder so argparse wiring works.
    print("status: not yet implemented — see plan Task 16")
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    cfg = load_config()
    if cfg.state_file.exists() and not args.force:
        print(f"state file already exists at {cfg.state_file} (use --force)", file=sys.stderr)
        return 1
    S.save_state(cfg.state_file, S._empty_state())     # noqa: SLF001
    print(f"initialized empty state file at {cfg.state_file}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="backend.sample_request")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("tick", help="Run one tick cycle")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=_cmd_tick)

    sp = sub.add_parser("status", help="Pretty-print state")
    sp.set_defaults(func=_cmd_status)

    sp = sub.add_parser("init", help="Create empty state file")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=_cmd_init)

    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":                                # pragma: no cover
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/sample_request/tests/test_cli_ingest.py -v`

Expected: 3 passed.

- [ ] **Step 5: Confirm full test suite still passes**

Run: `pytest backend/sample_request/tests/ -v`

Expected: all tests so far pass (config + log + state + parser + sender + cli_ingest).

- [ ] **Step 6: Commit**

```bash
git add backend/sample_request/cli.py backend/sample_request/tests/test_cli_ingest.py
git commit -m "feat(sample_request): cli skeleton + ingest step with idempotent dedup"
```

---

## Task 11: `cli.py` — `detect_sent` step

**Files:**
- Modify: `backend/sample_request/cli.py`
- Create: `backend/sample_request/tests/test_cli_detect_sent.py`

**Interfaces:**
- Consumes: `state.mark_released`, `gmail.fetch_sent_to`
- Produces: extends `run_tick` with the second pipeline step.

- [ ] **Step 1: Write the failing test**

Create `backend/sample_request/tests/test_cli_detect_sent.py`:

```python
"""Integration test: detect_sent step (Task 11)."""
from __future__ import annotations

from backend.sample_request import state as S
from backend.sample_request.cli import run_tick
from backend.sample_request.parser import ParsedItem, ParsedRequest


def _ingest_one(config, fake_gmail) -> str:
    msg = fake_gmail.inject_pending(
        from_="cust@example.com",
        to="me@example.com",
        subject="Sample request — A",
        body="...",
    )
    parsed = ParsedRequest(
        recipient="Mike", address="1 St",
        items=[ParsedItem(name="W", qty=1)],
    )
    run_tick(config, gmail=fake_gmail, parser_fn=lambda b, s: parsed)
    return msg.message_id


def test_detect_sent_user_has_not_sent_yet_keeps_status(config, fake_gmail):
    orig_id = _ingest_one(config, fake_gmail)
    result = run_tick(config, gmail=fake_gmail, parser_fn=lambda b, s: None)
    assert result.detected_sent == 0
    state = S.load_state(config.state_file)
    req = state["requests"][0]
    assert req["status"] == "draft_created"
    # label unchanged
    assert "sample-request/draft-ready" in fake_gmail.labels_on(orig_id)


def test_detect_sent_user_sent_transitions_to_released(config, fake_gmail):
    orig_id = _ingest_one(config, fake_gmail)
    draft = fake_gmail.drafts_created[0]
    sent_record = fake_gmail.inject_sent(
        to=config.warehouse_email,
        subject=draft["subject"],
        body=draft["body"],
        internal_date="2026-06-29T10:00:00Z",
    )

    result = run_tick(config, gmail=fake_gmail, parser_fn=lambda b, s: None)

    assert result.detected_sent == 1
    state = S.load_state(config.state_file)
    req = state["requests"][0]
    assert req["status"] == "released"
    assert req["release_message_id"] == sent_record["message_id"]
    assert req["warehouse_thread_id"] == sent_record["thread_id"]
    assert req["released_at"] == "2026-06-29T10:00:00Z"
    assert "sample-request/released" in fake_gmail.labels_on(orig_id)
    assert "sample-request/draft-ready" not in fake_gmail.labels_on(orig_id)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/sample_request/tests/test_cli_detect_sent.py -v`

Expected: 1 pass (no-send case may already pass), 1 failure (transition case fails — `detected_sent` stays 0).

- [ ] **Step 3: Add `_detect_sent` to `cli.py` and wire it into `run_tick`**

In `backend/sample_request/cli.py`, add this function after `_ingest`:

```python
def _detect_sent(cfg: Config, gmail, state: dict, log, *, dry_run: bool) -> int:
    count = 0
    for req in state["requests"]:
        if req.get("status") != "draft_created":
            continue
        # Look for a sent message whose subject matches the release email
        # we drafted. We don't have the draft's subject stored; reconstruct it.
        sent = gmail.fetch_sent_to(
            to=cfg.warehouse_email,
            subject_prefix=f"Release Request: {req['subject']}",
        )
        if not sent:
            continue
        sent.sort(key=lambda m: m.internal_date)
        match = sent[0]
        if dry_run:
            log.info(
                "detect_sent dry-run: would mark released",
                extra={
                    "step": "detect_sent",
                    "thread_id": req["thread_id"],
                    "release_message_id": match.message_id,
                },
            )
        else:
            S.mark_released(
                state,
                req["thread_id"],
                release_message_id=match.message_id,
                warehouse_thread_id=match.thread_id,
                released_at=match.internal_date,
            )
            gmail.relabel(
                req["original_message_id"],
                remove=[LABEL_DRAFT],
                add=[LABEL_RELEASED],
            )
            log.info(
                "detected sent",
                extra={
                    "step": "detect_sent",
                    "thread_id": req["thread_id"],
                    "release_message_id": match.message_id,
                },
            )
        count += 1
    return count
```

Then in `run_tick`, replace the existing try block body with:

```python
    try:
        result.ingested = _ingest(cfg, gmail, parser_fn, state, log, dry_run=dry_run)
        result.detected_sent = _detect_sent(cfg, gmail, state, log, dry_run=dry_run)
        # check_shipments / send_followups arrive in later tasks
    except Exception:
        log.exception("tick failed", extra={"step": "tick"})
        result.outcome = "failed"
        S.update_meta(state, last_tick_at=_iso(now_fn()), last_tick_outcome="failed")
        S.save_state(state_path, state)
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/sample_request/tests/test_cli_detect_sent.py -v`

Expected: 2 passed.

- [ ] **Step 5: Re-run the full suite**

Run: `pytest backend/sample_request/tests/ -v`

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/sample_request/cli.py backend/sample_request/tests/test_cli_detect_sent.py
git commit -m "feat(sample_request): detect_sent step transitions draft_created -> released"
```

---

## Task 12: `cli.py` — `check_shipments` step

**Files:**
- Modify: `backend/sample_request/cli.py`
- Create: `backend/sample_request/tests/test_cli_check_shipments.py`

**Interfaces:**
- Consumes: `state.mark_shipped`, `state.UPS_TRACKING_RE`, `gmail.fetch_thread`
- Produces: extends `run_tick` with the third pipeline step.

- [ ] **Step 1: Write the failing test**

Create `backend/sample_request/tests/test_cli_check_shipments.py`:

```python
"""Integration test: check_shipments step (Task 12)."""
from __future__ import annotations

from backend.sample_request import state as S
from backend.sample_request.cli import run_tick
from backend.sample_request.parser import ParsedItem, ParsedRequest


def _seed_released(config, fake_gmail) -> tuple[str, str]:
    msg = fake_gmail.inject_pending(
        from_="cust@example.com", to="me@example.com",
        subject="Sample request — Z", body="...",
    )
    parsed = ParsedRequest(
        recipient="Z", address="A",
        items=[ParsedItem(name="X", qty=1)],
    )
    run_tick(config, gmail=fake_gmail, parser_fn=lambda b, s: parsed)
    draft = fake_gmail.drafts_created[0]
    sent = fake_gmail.inject_sent(
        to=config.warehouse_email,
        subject=draft["subject"],
        body=draft["body"],
        internal_date="2026-06-29T10:00:00Z",
    )
    run_tick(config, gmail=fake_gmail, parser_fn=lambda b, s: None)
    return msg.message_id, sent["thread_id"]


def test_check_shipments_no_ups_keeps_state(config, fake_gmail):
    orig_id, thread_id = _seed_released(config, fake_gmail)
    fake_gmail.inject_thread_reply(
        thread_id, from_="warehouse@example.com",
        body="Got it, working on this shortly.",
    )
    result = run_tick(config, gmail=fake_gmail, parser_fn=lambda b, s: None)
    assert result.shipped == 0
    state = S.load_state(config.state_file)
    assert state["requests"][0]["status"] == "released"


def test_check_shipments_ups_present_marks_shipped(config, fake_gmail):
    orig_id, thread_id = _seed_released(config, fake_gmail)
    fake_gmail.inject_thread_reply(
        thread_id, from_="warehouse@example.com",
        body="Shipped via UPS. Tracking: 1ZA1234567890123456 — ETA 2 days.",
    )
    result = run_tick(config, gmail=fake_gmail, parser_fn=lambda b, s: None)
    assert result.shipped == 1
    state = S.load_state(config.state_file)
    req = state["requests"][0]
    assert req["status"] == "shipped"
    assert req["ups_tracking_no"] == "1ZA1234567890123456"
    assert req["shipped_at"] is not None
    assert "sample-request/shipped" in fake_gmail.labels_on(orig_id)
    assert "sample-request/released" not in fake_gmail.labels_on(orig_id)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/sample_request/tests/test_cli_check_shipments.py -v`

Expected: 1 may pass (no-UPS), 1 fails (shipped never transitions).

- [ ] **Step 3: Add `_check_shipments` and wire into `run_tick`**

In `backend/sample_request/cli.py`, add after `_detect_sent`:

```python
def _check_shipments(cfg: Config, gmail, state: dict, log, *, dry_run: bool) -> int:
    count = 0
    for req in state["requests"]:
        if req.get("status") != "released":
            continue
        warehouse_thread = req.get("warehouse_thread_id")
        if not warehouse_thread:
            continue
        thread = gmail.fetch_thread(warehouse_thread)
        tracking = None
        for m in thread:
            blob = f"{m.subject}\n{m.body}"
            match = S.UPS_TRACKING_RE.search(blob)
            if match:
                tracking = match.group(0)
                break
        if tracking is None:
            continue
        if dry_run:
            log.info(
                "check_shipments dry-run: would mark shipped",
                extra={
                    "step": "check_shipments",
                    "thread_id": req["thread_id"],
                    "tracking": tracking,
                },
            )
        else:
            S.mark_shipped(state, req["thread_id"], tracking)
            gmail.relabel(
                req["original_message_id"],
                remove=[LABEL_RELEASED],
                add=[LABEL_SHIPPED],
            )
            log.info(
                "shipped",
                extra={
                    "step": "check_shipments",
                    "thread_id": req["thread_id"],
                    "tracking": tracking,
                },
            )
        count += 1
    return count
```

Update `run_tick`'s try block to add the new call:

```python
        result.detected_sent = _detect_sent(cfg, gmail, state, log, dry_run=dry_run)
        result.shipped = _check_shipments(cfg, gmail, state, log, dry_run=dry_run)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/sample_request/tests/test_cli_check_shipments.py -v`

Expected: 2 passed.

- [ ] **Step 5: Re-run the full suite**

Run: `pytest backend/sample_request/tests/ -v`

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/sample_request/cli.py backend/sample_request/tests/test_cli_check_shipments.py
git commit -m "feat(sample_request): check_shipments step finds UPS no in warehouse thread"
```

---

## Task 13: `cli.py` — `send_followups` step

**Files:**
- Modify: `backend/sample_request/cli.py`
- Create: `backend/sample_request/tests/test_cli_send_followups.py`

**Interfaces:**
- Consumes: `state.record_followup`, `state.last_contact_at`, `sender.build_followup_email`, `gmail.reply_in_thread`
- Produces: extends `run_tick` with the fourth pipeline step.

- [ ] **Step 1: Write the failing test**

Create `backend/sample_request/tests/test_cli_send_followups.py`:

```python
"""Integration test: send_followups step (Task 13)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.sample_request import state as S
from backend.sample_request.cli import run_tick
from backend.sample_request.parser import ParsedItem, ParsedRequest


def _seed_released(config, fake_gmail, released_iso: str) -> tuple[str, str]:
    msg = fake_gmail.inject_pending(
        from_="cust@example.com", to="me@example.com",
        subject="Sample request — late", body="...",
    )
    parsed = ParsedRequest(
        recipient="Late", address="L",
        items=[ParsedItem(name="X", qty=1)],
    )
    run_tick(config, gmail=fake_gmail, parser_fn=lambda b, s: parsed)
    draft = fake_gmail.drafts_created[0]
    sent = fake_gmail.inject_sent(
        to=config.warehouse_email,
        subject=draft["subject"],
        body=draft["body"],
        internal_date=released_iso,
    )
    run_tick(config, gmail=fake_gmail, parser_fn=lambda b, s: None)
    return msg.message_id, sent["thread_id"]


def test_followup_skipped_when_recent(config, fake_gmail):
    recent = (
        datetime.now(timezone.utc) - timedelta(hours=1)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    _seed_released(config, fake_gmail, recent)
    result = run_tick(config, gmail=fake_gmail, parser_fn=lambda b, s: None)
    assert result.followups == 0


def test_followup_sent_when_threshold_exceeded(config, fake_gmail):
    stale = (
        datetime.now(timezone.utc) - timedelta(hours=5)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    orig_id, thread_id = _seed_released(config, fake_gmail, stale)
    result = run_tick(config, gmail=fake_gmail, parser_fn=lambda b, s: None)
    assert result.followups == 1
    state = S.load_state(config.state_file)
    req = state["requests"][0]
    assert len(req["follow_ups"]) == 1
    # The reply is in the warehouse thread
    thread = fake_gmail.fetch_thread(thread_id)
    assert any("Late" in m.body for m in thread)


def test_followup_message_changes_each_send(config, fake_gmail):
    stale = (
        datetime.now(timezone.utc) - timedelta(hours=20)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    _orig, thread_id = _seed_released(config, fake_gmail, stale)
    # First tick sends follow-up #1
    run_tick(config, gmail=fake_gmail, parser_fn=lambda b, s: None)
    # Pretend a lot of time passed — manually backdate last contact to stale
    state = S.load_state(config.state_file)
    state["requests"][0]["follow_ups"][-1]["sent_at"] = stale
    S.save_state(config.state_file, state)
    # Second tick sends follow-up #2 with different wording
    run_tick(config, gmail=fake_gmail, parser_fn=lambda b, s: None)
    state = S.load_state(config.state_file)
    follow_ups = state["requests"][0]["follow_ups"]
    assert len(follow_ups) == 2

    # The two replies our agent sent into the warehouse thread should
    # differ in wording — that is the whole point of escalating templates.
    thread = fake_gmail.fetch_thread(thread_id)
    agent_replies = [m for m in thread if m.from_ == "me@example.com"]
    assert len(agent_replies) >= 2
    # Compare the last two replies (the two follow-ups we just sent)
    assert agent_replies[-1].body != agent_replies[-2].body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/sample_request/tests/test_cli_send_followups.py -v`

Expected: tests fail (`followups` never increments).

- [ ] **Step 3: Add `_send_followups` and wire into `run_tick`**

In `backend/sample_request/cli.py`, add `import time` near the top imports, then add this function after `_check_shipments`:

```python
import time   # at top of file with other imports


def _send_followups(cfg: Config, gmail, state: dict, log, *, dry_run: bool, now_fn) -> int:
    count = 0
    threshold = cfg.followup_threshold_hours
    for req in state["requests"]:
        if req.get("status") != "released":
            continue
        last = S.last_contact_at(req)
        hours_since = (now_fn() - last).total_seconds() / 3600.0
        if hours_since < threshold:
            continue
        warehouse_thread = req.get("warehouse_thread_id")
        if not warehouse_thread:
            continue
        n_th = len(req.get("follow_ups", [])) + 1
        from backend.sample_request.sender import build_followup_email
        body = build_followup_email(req, n_th)
        if dry_run:
            log.info(
                "send_followups dry-run: would reply",
                extra={
                    "step": "send_followups",
                    "thread_id": req["thread_id"],
                    "n_th": n_th,
                },
            )
        else:
            new_msg_id = gmail.reply_in_thread(warehouse_thread, body)
            # See spec §4: 2s sleep so subsequent `last_contact_at` queries
            # don't outrun Gmail's index update.
            time.sleep(2)
            S.record_followup(state, req["thread_id"], message_id=new_msg_id)
            log.info(
                "follow-up sent",
                extra={
                    "step": "send_followups",
                    "thread_id": req["thread_id"],
                    "n_th": n_th,
                    "message_id": new_msg_id,
                },
            )
        count += 1
    return count
```

Update `run_tick`'s try block to add the new call (note we now thread `now_fn` to `_send_followups`):

```python
        result.shipped = _check_shipments(cfg, gmail, state, log, dry_run=dry_run)
        result.followups = _send_followups(
            cfg, gmail, state, log, dry_run=dry_run, now_fn=now_fn,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/sample_request/tests/test_cli_send_followups.py -v`

Expected: 3 passed (note: test 3 will take ~4 seconds because of the two 2-second sleeps; that is expected).

- [ ] **Step 5: Re-run the full suite**

Run: `pytest backend/sample_request/tests/ -v`

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/sample_request/cli.py backend/sample_request/tests/test_cli_send_followups.py
git commit -m "feat(sample_request): send_followups step with 4h threshold and templated body"
```

---

## Task 14: error handling — retries, tick_errors, needs-attention label

**Files:**
- Modify: `backend/sample_request/cli.py`
- Create: `backend/sample_request/tests/test_cli_errors.py`

**Interfaces:**
- Consumes: `state.append_tick_error`
- Produces:
  ```python
  class TransientError(Exception): ...    # raised by retry helper after exhausting tries

  def _retry(call: Callable[[], T], *, retries: int = 3, base: float = 1.0,
             sleep: Callable[[float], None] = time.sleep) -> T
      # exponential backoff 1s/4s/16s; transient classifier for googleapiclient HttpError
  ```
  `_ingest` and `_send_followups` wrap Gmail write calls with `_retry`; on terminal failure they append a tick_error and add the `needs-attention` label when the count hits 3. `relabel` failure remains FATAL.

- [ ] **Step 1: Write the failing tests**

Create `backend/sample_request/tests/test_cli_errors.py`:

```python
"""Integration tests: retries, tick_errors, needs-attention escalation (Task 14)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.sample_request import state as S
from backend.sample_request.cli import LABEL_ATTENTION, run_tick
from backend.sample_request.parser import (
    ParsedItem,
    ParsedRequest,
    ParserSchemaError,
)


def _parsed_ok() -> ParsedRequest:
    return ParsedRequest(
        recipient="R", address="A", items=[ParsedItem(name="X", qty=1)],
    )


def test_parser_failure_records_tick_error_and_keeps_label(config, fake_gmail):
    msg = fake_gmail.inject_pending(
        from_="c@example.com", to="me@example.com",
        subject="Sample request — bad", body="garbage",
    )

    def bad_parser(body, subject):
        raise ParserSchemaError("schema bad")

    result = run_tick(config, gmail=fake_gmail, parser_fn=bad_parser)

    assert result.errors == 1
    assert result.ingested == 0
    # label is unchanged so next tick will retry
    assert "sample-request/pending-release" in fake_gmail.labels_on(msg.message_id)
    state = S.load_state(config.state_file)
    # request not added to state yet — we don't have a parsed payload
    # but a tick-level error is recorded under meta
    assert state["meta"]["last_tick_outcome"] == "partial"


def test_three_consecutive_failures_adds_needs_attention_label(config, fake_gmail):
    msg = fake_gmail.inject_pending(
        from_="c@example.com", to="me@example.com",
        subject="Sample request — bad2", body="garbage",
    )

    def bad_parser(body, subject):
        raise ParserSchemaError("nope")

    for _ in range(3):
        run_tick(config, gmail=fake_gmail, parser_fn=bad_parser)

    assert LABEL_ATTENTION in fake_gmail.labels_on(msg.message_id)


def test_transient_gmail_failure_is_retried_then_succeeds(config, fake_gmail):
    msg = fake_gmail.inject_pending(
        from_="c@example.com", to="me@example.com",
        subject="Sample request — flaky", body="b",
    )
    # Force the first 2 create_draft attempts to raise transient errors
    from googleapiclient.errors import HttpError

    class _FakeResp:
        status = 503
        reason = "transient"

    fake_gmail.fail_next(
        "create_draft",
        times=2,
        exc=HttpError(_FakeResp(), b"flaky"),
    )

    result = run_tick(
        config,
        gmail=fake_gmail,
        parser_fn=lambda b, s: _parsed_ok(),
    )
    assert result.errors == 0
    assert result.ingested == 1
    state = S.load_state(config.state_file)
    assert state["requests"][0]["status"] == "draft_created"


def test_transient_failure_exhausted_records_error(config, fake_gmail):
    msg = fake_gmail.inject_pending(
        from_="c@example.com", to="me@example.com",
        subject="Sample request — broken", body="b",
    )
    from googleapiclient.errors import HttpError

    class _FakeResp:
        status = 503
        reason = "always"

    fake_gmail.fail_next(
        "create_draft",
        times=10,
        exc=HttpError(_FakeResp(), b"always"),
    )

    result = run_tick(
        config,
        gmail=fake_gmail,
        parser_fn=lambda b, s: _parsed_ok(),
    )
    assert result.errors == 1
    # label NOT changed -> next tick retries
    assert "sample-request/pending-release" in fake_gmail.labels_on(msg.message_id)


def test_relabel_failure_is_fatal_exit_1(config, fake_gmail):
    msg = fake_gmail.inject_pending(
        from_="c@example.com", to="me@example.com",
        subject="Sample request — relabel", body="b",
    )
    from googleapiclient.errors import HttpError

    class _FakeResp:
        status = 503
        reason = "label down"

    fake_gmail.fail_next("relabel", times=10, exc=HttpError(_FakeResp(), b"down"))

    result = run_tick(
        config,
        gmail=fake_gmail,
        parser_fn=lambda b, s: _parsed_ok(),
    )
    assert result.outcome == "failed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/sample_request/tests/test_cli_errors.py -v`

Expected: most tests fail — error handling is not yet implemented.

- [ ] **Step 3: Add retry helper + per-step error handling**

In `backend/sample_request/cli.py`, add this block of imports near the existing `import time`:

```python
import time
from typing import TypeVar

from googleapiclient.errors import HttpError

T = TypeVar("T")

_TRANSIENT_STATUS = {429, 500, 502, 503, 504}


class TransientError(Exception):
    """Raised when retries are exhausted on a transient Gmail error."""


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, HttpError):
        try:
            return exc.resp.status in _TRANSIENT_STATUS
        except AttributeError:
            return False
    return isinstance(exc, (TimeoutError, ConnectionError))


def _retry(
    call,
    *,
    retries: int = 3,
    base: float = 1.0,
    sleep_fn=time.sleep,
):
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return call()
        except Exception as exc:                     # noqa: BLE001
            if not _is_transient(exc):
                raise
            last_exc = exc
            sleep_fn(base * (4 ** attempt))          # 1s, 4s, 16s
    raise TransientError(str(last_exc)) from last_exc
```

Replace the `_ingest` function body's draft-creation block with a retry-wrapped, error-recording version. The full updated `_ingest` is:

```python
def _ingest(cfg: Config, gmail, parser_fn, state: dict, log, *, dry_run: bool) -> tuple[int, int]:
    """Returns (ingested, errors)."""
    msgs = gmail.fetch_pending()
    count = 0
    errors = 0
    for msg in msgs:
        existing = next(
            (r for r in state["requests"]
             if r.get("original_message_id") == msg.message_id),
            None,
        )
        if existing is not None:
            log.info(
                "ingest skip: already in state",
                extra={"step": "ingest", "thread_id": msg.thread_id},
            )
            if not dry_run:
                gmail.relabel(
                    msg.message_id, remove=[LABEL_PENDING], add=[LABEL_DRAFT],
                )
            continue

        try:
            parsed = parser_fn(msg.body, msg.subject)
        except Exception as exc:                     # noqa: BLE001
            errors += 1
            _record_pending_message_error(
                cfg, gmail, state, log, msg,
                step="parser",
                exc=exc,
                raw_excerpt=msg.body,
            )
            continue

        subject, body = build_release_email(parsed, msg.subject, msg.from_)

        if dry_run:
            log.info(
                "ingest dry-run: would create draft",
                extra={
                    "step": "ingest",
                    "thread_id": msg.thread_id,
                    "subject": subject,
                },
            )
            count += 1
            continue

        try:
            draft_id = _retry(lambda: gmail.create_draft(
                to=cfg.warehouse_email,
                subject=subject,
                body=body,
                in_reply_to=None,
            ))
        except Exception as exc:                     # noqa: BLE001
            errors += 1
            _record_pending_message_error(
                cfg, gmail, state, log, msg,
                step="create_draft",
                exc=exc,
                raw_excerpt=None,
            )
            continue

        # relabel + state writes are *not* wrapped in tick_errors — relabel
        # failure is FATAL per spec §5.
        gmail.relabel(msg.message_id, remove=[LABEL_PENDING], add=[LABEL_DRAFT])
        S.add_request(
            state,
            thread_id=msg.thread_id,
            message_id=msg.message_id,
            subject=msg.subject,
            from_=msg.from_,
            received_at=msg.internal_date,
            parsed=parsed.model_dump(),
        )
        S.mark_draft_created(state, msg.thread_id, draft_id=draft_id)
        S.reset_ingest_failure(state, msg.message_id)
        log.info(
            "draft created",
            extra={
                "step": "ingest",
                "thread_id": msg.thread_id,
                "draft_id": draft_id,
            },
        )
        count += 1
    return count, errors
```

Add this helper just above `_ingest`:

```python
def _record_pending_message_error(
    cfg: Config, gmail, state: dict, log, msg, *,
    step: str, exc: Exception, raw_excerpt: str | None,
) -> None:
    """Record a per-message error for a request that has not yet been
    added to state (i.e. failed during ingest before `add_request`).
    Failure counts are persisted in `state.ingest_failure_counts` (see
    Task 4) so escalation survives across ticks. The counter is cleared
    once the message successfully becomes a tracked request."""
    log.error(
        f"{step} failed",
        extra={
            "step": step,
            "thread_id": msg.thread_id,
            "error_class": exc.__class__.__name__,
            "error": str(exc)[:500],
        },
    )
    n = S.bump_ingest_failure(state, msg.message_id)
    if n >= 3:
        gmail.relabel(msg.message_id, remove=[], add=[LABEL_ATTENTION])
        log.warning(
            "needs-attention label added",
            extra={"step": step, "thread_id": msg.thread_id, "failures": n},
        )
```

Update `_send_followups` to wrap the reply with `_retry` and append `tick_errors` on terminal failure (apply the same shape as the new `_ingest`):

```python
def _send_followups(cfg: Config, gmail, state: dict, log, *, dry_run: bool, now_fn) -> tuple[int, int]:
    """Returns (followups_sent, errors)."""
    count = 0
    errors = 0
    threshold = cfg.followup_threshold_hours
    for req in state["requests"]:
        if req.get("status") != "released":
            continue
        last = S.last_contact_at(req)
        hours_since = (now_fn() - last).total_seconds() / 3600.0
        if hours_since < threshold:
            continue
        warehouse_thread = req.get("warehouse_thread_id")
        if not warehouse_thread:
            continue
        n_th = len(req.get("follow_ups", [])) + 1
        from backend.sample_request.sender import build_followup_email
        body = build_followup_email(req, n_th)
        if dry_run:
            log.info(
                "send_followups dry-run: would reply",
                extra={
                    "step": "send_followups",
                    "thread_id": req["thread_id"],
                    "n_th": n_th,
                },
            )
            count += 1
            continue
        try:
            new_msg_id = _retry(lambda: gmail.reply_in_thread(warehouse_thread, body))
        except Exception as exc:                     # noqa: BLE001
            errors += 1
            n = S.append_tick_error(
                state, req["thread_id"],
                step="send_followups",
                error_class=exc.__class__.__name__,
                message=str(exc)[:500],
            )
            log.error(
                "send_followups failed",
                extra={
                    "step": "send_followups",
                    "thread_id": req["thread_id"],
                    "failures": n,
                },
            )
            if n >= 3:
                gmail.relabel(
                    req["original_message_id"], remove=[], add=[LABEL_ATTENTION],
                )
                log.warning(
                    "needs-attention label added",
                    extra={"step": "send_followups", "thread_id": req["thread_id"]},
                )
            continue
        time.sleep(2)
        S.record_followup(state, req["thread_id"], message_id=new_msg_id)
        log.info(
            "follow-up sent",
            extra={
                "step": "send_followups",
                "thread_id": req["thread_id"],
                "n_th": n_th,
                "message_id": new_msg_id,
            },
        )
        count += 1
    return count, errors
```

Update `run_tick`'s try block to capture the new (count, errors) tuples and accumulate errors:

```python
    try:
        ingested, ingest_errs = _ingest(cfg, gmail, parser_fn, state, log, dry_run=dry_run)
        result.ingested = ingested
        result.errors += ingest_errs

        result.detected_sent = _detect_sent(cfg, gmail, state, log, dry_run=dry_run)
        result.shipped = _check_shipments(cfg, gmail, state, log, dry_run=dry_run)

        followups, fu_errs = _send_followups(
            cfg, gmail, state, log, dry_run=dry_run, now_fn=now_fn,
        )
        result.followups = followups
        result.errors += fu_errs
    except Exception:
        log.exception("tick failed", extra={"step": "tick"})
        result.outcome = "failed"
        S.update_meta(state, last_tick_at=_iso(now_fn()), last_tick_outcome="failed")
        S.save_state(state_path, state)
        return result
```

Update the outcome selection at the end:

```python
    outcome = "ok" if result.errors == 0 else "partial"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/sample_request/tests/test_cli_errors.py -v`

Expected: 5 passed (the retry test takes ~21 s due to the 1s/4s/16s sleeps; that is expected).

- [ ] **Step 5: Re-run the full suite**

Run: `pytest backend/sample_request/tests/ -v`

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/sample_request/cli.py backend/sample_request/tests/test_cli_errors.py
git commit -m "feat(sample_request): exponential-backoff retries, tick_errors, needs-attention escalation"
```

---

## Task 15: dry-run mode integration test

**Files:**
- Create: `backend/sample_request/tests/test_cli_dry_run.py`

> No production-code changes — dry-run logic is already wired in Tasks 10/11/12/13/14. This task is purely a verification + regression-guard layer.

**Interfaces:**
- Consumes: existing `run_tick(dry_run=True)`
- Produces: no new module surface.

- [ ] **Step 1: Write the test**

Create `backend/sample_request/tests/test_cli_dry_run.py`:

```python
"""Verification: --dry-run path makes no Gmail writes and writes a sidecar state file."""
from __future__ import annotations

from backend.sample_request import state as S
from backend.sample_request.cli import run_tick
from backend.sample_request.parser import ParsedItem, ParsedRequest


def test_dry_run_no_draft_no_relabel_writes_sidecar_state(config, fake_gmail):
    msg = fake_gmail.inject_pending(
        from_="c@example.com", to="me@example.com",
        subject="Sample request — dryrun", body="b",
    )
    parsed = ParsedRequest(
        recipient="R", address="A",
        items=[ParsedItem(name="X", qty=1)],
    )

    result = run_tick(
        config,
        gmail=fake_gmail,
        parser_fn=lambda b, s: parsed,
        dry_run=True,
    )

    assert result.ingested == 1
    assert fake_gmail.drafts_created == []
    # label unchanged
    assert "sample-request/pending-release" in fake_gmail.labels_on(msg.message_id)
    assert "sample-request/draft-ready" not in fake_gmail.labels_on(msg.message_id)
    # canonical state untouched
    canonical = S.load_state(config.state_file)
    assert canonical["requests"] == []
    # sidecar exists
    sidecars = list(config.state_file.parent.glob(config.state_file.name + ".dryrun.*"))
    assert len(sidecars) == 1
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest backend/sample_request/tests/test_cli_dry_run.py -v`

Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add backend/sample_request/tests/test_cli_dry_run.py
git commit -m "test(sample_request): dry-run path produces no writes and writes sidecar state"
```

---

## Task 16: `cli.py` — `status` subcommand pretty-prints state

**Files:**
- Modify: `backend/sample_request/cli.py`
- Create: `backend/sample_request/tests/test_cli_status.py`

**Interfaces:**
- Consumes: state file
- Produces: `_cmd_status` replaces the placeholder from Task 10; new helper `_render_status(state: dict) -> str`.

- [ ] **Step 1: Write the failing test**

Create `backend/sample_request/tests/test_cli_status.py`:

```python
"""Test for the status subcommand."""
from __future__ import annotations

from backend.sample_request import state as S
from backend.sample_request.cli import _render_status


def test_render_status_empty_state(tmp_path):
    state = S.load_state(tmp_path / "s.json")
    out = _render_status(state)
    assert "No sample requests on file" in out


def test_render_status_with_requests(tmp_path):
    state = S.load_state(tmp_path / "s.json")
    S.add_request(
        state, thread_id="T1", message_id="M1",
        subject="Sample request — A", from_="c@example.com",
        received_at="2026-06-29T09:00:00Z",
        parsed={"recipient": "Mike", "address": "1 St", "items": []},
    )
    S.mark_draft_created(state, "T1", draft_id="d-1")
    S.mark_released(state, "T1", "W1", "W1", "2026-06-29T10:00:00Z")
    S.record_followup(state, "T1", message_id="F1", sent_at="2026-06-29T15:00:00Z")
    S.update_meta(state, last_tick_at="2026-06-29T16:00:00Z", last_tick_outcome="ok")

    out = _render_status(state)
    assert "T1" in out
    assert "Mike" in out
    assert "released" in out
    assert "follow-ups: 1" in out
    assert "last tick: 2026-06-29T16:00:00Z (ok)" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/sample_request/tests/test_cli_status.py -v`

Expected: failures — `_render_status` undefined or returns placeholder.

- [ ] **Step 3: Implement `_render_status` and update `_cmd_status`**

In `backend/sample_request/cli.py`, add this function above `_cmd_status`:

```python
def _render_status(state: dict) -> str:
    requests = state.get("requests", [])
    meta = state.get("meta", {})
    header = (
        f"last tick: {meta.get('last_tick_at') or 'never'} "
        f"({meta.get('last_tick_outcome') or '-'})"
    )
    if not requests:
        return f"{header}\nNo sample requests on file.\n"
    lines = [header, ""]
    lines.append(
        f"{'thread':<22} {'status':<14} {'recipient':<20} "
        f"{'released_at':<22} {'follow-ups':<12} {'errors':<6}"
    )
    lines.append("-" * 100)
    for r in requests:
        parsed = r.get("parsed") or {}
        lines.append(
            f"{r.get('thread_id','')!s:<22} "
            f"{r.get('status','')!s:<14} "
            f"{parsed.get('recipient','')!s:<20} "
            f"{r.get('released_at') or '-':<22} "
            f"follow-ups: {len(r.get('follow_ups') or [])!s:<3}  "
            f"errors: {len(r.get('tick_errors') or [])}"
        )
    return "\n".join(lines) + "\n"
```

Replace `_cmd_status`'s body with:

```python
def _cmd_status(args: argparse.Namespace) -> int:
    cfg = load_config()
    state = S.load_state(cfg.state_file)
    sys.stdout.write(_render_status(state))
    return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/sample_request/tests/test_cli_status.py -v`

Expected: 2 passed.

- [ ] **Step 5: Re-run the full suite**

Run: `pytest backend/sample_request/tests/ -v`

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/sample_request/cli.py backend/sample_request/tests/test_cli_status.py
git commit -m "feat(sample_request): status subcommand prints a readable summary"
```

---

## Task 17: Reduce `scripts/sample_followup_tick.py` to a shim + README + smoke checklist

**Files:**
- Modify: `scripts/sample_followup_tick.py`
- Create: `backend/sample_request/README.md`

**Interfaces:**
- Consumes: `backend.sample_request.cli.main`
- Produces: backward-compat invocation; user-facing setup documentation.

- [ ] **Step 1: Replace `scripts/sample_followup_tick.py` with a shim**

Open `scripts/sample_followup_tick.py` and replace the **entire file** with:

```python
#!/usr/bin/env python3
"""Compatibility shim — real implementation lives in backend.sample_request.cli."""
from __future__ import annotations

from backend.sample_request.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
```

Note: the legacy subcommands `plan`, `mark-shipped`, `record-followup` were
covered by the original script but are not part of the new `cli.py` surface
(spec §3: "New subcommands (`tick`, `status`) live only on the new CLI;
legacy subcommands continue to work via this delegation."). Since the new
cli.py does not implement them, any caller still relying on them will get
a clean argparse error pointing at the available subcommands. Document
this in the README.

- [ ] **Step 2: Create `backend/sample_request/README.md`**

```markdown
# `backend.sample_request` — Gmail-API sample request automation

Replaces the Claude-session-based executor. Driven by cron every 2 hours.

See the design spec at
`docs/superpowers/specs/2026-06-29-sample-request-gmail-api-design.md`.

## CLI

```
python3 -m backend.sample_request tick           # cron entry point
python3 -m backend.sample_request tick --dry-run # no Gmail writes
python3 -m backend.sample_request status         # readable table of state
python3 -m backend.sample_request init           # create empty state
python3 -m backend.sample_request init --force   # overwrite
python3 -m backend.sample_request.auth           # one-time OAuth setup
```

The shim `scripts/sample_followup_tick.py` delegates to `cli.main`. The
legacy subcommands `plan` / `mark-shipped` / `record-followup` are no longer
exposed — use `tick` / `status` instead.

## One-time setup

1. **Google Cloud Console**
   - Create (or reuse) a project; enable the **Gmail API**.
   - **OAuth consent screen** → User Type **External** → add your Gmail
     address as a **Test user**.
   - **Credentials** → **Create OAuth client ID** → **Desktop app** →
     download the JSON.
   - Save the JSON as `secrets/credentials.json` in the repo root.

2. **Run the OAuth flow**

   ```bash
   python3 -m backend.sample_request.auth
   ```

   - A browser tab opens; sign in and grant access.
   - `secrets/token.json` is created. The five Gmail labels
     `sample-request/{pending-release,draft-ready,released,shipped,needs-attention}`
     are created automatically.

3. **Create the Gmail filter** (Gmail web UI):
   - **Search mail** → click filter icon → **Has the words:**
     `subject:"sample request"`.
   - **Create filter** → tick **Apply the label** → choose
     `sample-request/pending-release` → **Create filter**.

4. **Reset state for the new pipeline** (clears the old Claude-driven row):

   ```bash
   python3 -m backend.sample_request init --force
   ```

5. **Dry-run verification**

   ```bash
   python3 -m backend.sample_request tick --dry-run
   ```

   - Inspect `logs/sample_request_tick.log` for the JSON lines.
   - Inspect any `.sample_requests_state.json.dryrun.*` files created in
     the repo root. Confirm parsed `recipient` / `address` / `items` look
     right for any test emails you have queued.

6. **Install the crontab line**

   ```bash
   crontab -e
   ```

   Add:

   ```
   # sample request tick — every 2 hours
   0 */2 * * * cd /home/paul2/workspace/po-agents && /usr/bin/python3 -m backend.sample_request tick >> logs/sample_request_cron.log 2>&1
   ```

## Manual smoke checklist

After setup, verify the end-to-end pipeline by hand:

- [ ] Send yourself an email — **Subject:** `Sample request — smoke 1`,
      **Body:** any recipient + address + items in free-form text.
- [ ] Within a few seconds, confirm the Gmail filter applies the
      `sample-request/pending-release` label.
- [ ] Run `python3 -m backend.sample_request tick --dry-run`. Check
      the log file and the `.dryrun.*` state sidecar for a sensible
      `ParsedRequest`.
- [ ] Run `python3 -m backend.sample_request tick` (live). Confirm:
  - A new draft appears in Gmail Drafts addressed to your configured
    warehouse email.
  - The original email's label flips from `pending-release` →
    `draft-ready`.
  - `python3 -m backend.sample_request status` lists the request as
    `draft_created`.
- [ ] Open the draft in Gmail and click **Send**.
- [ ] Wait for the next cron tick (or run `tick` manually). Confirm:
  - `status` reports `released`.
  - The original email's label flips `draft-ready` → `released`.
- [ ] Reply to the warehouse thread (from the warehouse account or by
      sending yourself a UPS-bearing reply) with a body containing
      `Tracking: 1ZA1234567890123456`.
- [ ] Run `tick`. Confirm `status` becomes `shipped`, label flips
      `released` → `shipped`, and `ups_tracking_no` is set.
- [ ] Optionally, leave a `released` request without a UPS reply for
      more than `SAMPLE_REQUEST_FOLLOWUP_HOURS` and confirm the next
      `tick` auto-sends a follow-up reply on the warehouse thread.

## Operational notes

- Logs: `logs/sample_request_tick.log` (10 MB × 5 rotation).
- Errors-to-watch: tick exit code 1, appearance of
  `sample-request/needs-attention` label on any email, or any state row
  whose `tick_errors` count is ≥ 3.
- The state file at `.sample_requests_state.json` is safe to inspect
  but should not be edited by hand while a tick is running.
```

- [ ] **Step 3: Verify the shim still runs the CLI cleanly**

Run:

```bash
python3 scripts/sample_followup_tick.py --help
```

Expected: argparse help text listing `tick`, `status`, `init` subcommands.

- [ ] **Step 4: Verify full module help also works**

Run:

```bash
python3 -m backend.sample_request --help
```

Expected: same argparse help text.

- [ ] **Step 5: Commit**

```bash
git add scripts/sample_followup_tick.py backend/sample_request/README.md
git commit -m "docs(sample_request): module README + replace legacy script with shim"
```

---

## Task 18: Final cross-check, full test run, plan-execution close-out

**Files:** none.

**Interfaces:** none — verification only.

- [ ] **Step 1: Run the full project test suite**

Run:

```bash
pytest tests/ backend/sample_request/tests/ -v
```

Expected: all tests pass (existing project tests + 13 new test files for sample_request).

- [ ] **Step 2: Confirm there are no stray placeholders in the new module**

Run:

```bash
grep -rnE 'TODO|FIXME|TBD|XXX' backend/sample_request/ docs/superpowers/specs/2026-06-29-sample-request-gmail-api-design.md docs/superpowers/plans/2026-06-29-sample-request-gmail-api.md
```

Expected: zero matches (or only matches inside test fixtures' deliberate strings).

- [ ] **Step 3: Confirm `secrets/` is gitignored**

Run:

```bash
git check-ignore secrets/token.json
```

Expected output: `secrets/token.json`

- [ ] **Step 4: Confirm the shim is exec-bit clean and executable**

Run:

```bash
python3 scripts/sample_followup_tick.py status
```

Expected: prints either "No sample requests on file." (if state was reset) or the current state's table. **Exit code 0** in both cases.

- [ ] **Step 5: Hand off to manual smoke checklist**

At this point the code is shipped. Direct the user to walk through the
manual smoke checklist in `backend/sample_request/README.md` to verify
the end-to-end pipeline against their own Gmail.

- [ ] **Step 6: Final commit (if anything is dangling)**

```bash
git status
# If everything is committed, no action needed.
```

---

## Self-Review

**1. Spec coverage:** every spec section maps to at least one task:

| Spec | Implementing task(s) |
|---|---|
| §1 Background / Goal / Non-goals | covered by overall scope; non-goals enforced by Task 8 deliberately omitting them |
| §2 Architecture & tick lifecycle | Tasks 10 (ingest + orchestrator), 11 (detect_sent), 12 (check_shipments), 13 (send_followups) |
| §3 Directory layout | Tasks 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 17 |
| §3 Public CLI | Tasks 10 (tick/init), 16 (status), 9 (auth subcommand) |
| §3 Module APIs — GmailClient | Task 8 (real), Task 7 (fake) |
| §3 Module APIs — parser, sender, state, config | Tasks 5, 6, 4, 2 |
| §3 Dependency additions | Task 1 |
| §3 Shim | Task 17 |
| §4 State machine & labels | Tasks 10–13 (label transitions per step), Task 9 (label bootstrap) |
| §4 Schema v2 + migration | Task 4 |
| §4 Worked example | exercised by tests in Tasks 10–13 |
| §4 Idempotency | Task 10 step 1 test "idempotent does not double-draft"; Task 13 explicit 2-second sleep |
| §5 Error tiers + retries + tick_errors + needs-attention | Task 14 |
| §5 Structured JSON logging | Task 3 (logger), Tasks 10–14 (per-step log lines) |
| §5 Dry-run mode | Tasks 10–14 implement; Task 15 verifies |
| §5 Alerting (or absence of) | Task 17 README operational notes |
| §6 Test layers + FakeGmailClient + scenarios | Tasks 7, 10–16 |
| §6 Smoke checklist | Task 17 README |
| §7 .env / .gitignore / dirs | Task 1 |
| §7 OAuth setup procedure | Task 9 + Task 17 README |
| §7 Crontab line | Task 17 README |
| §7 Migration: `init --force` first | Task 17 README step 4 |
| §8 Future work | explicitly out of scope |
| §9 Acceptance criteria | Task 18 step 1 (pytest), Task 17 README (manual smoke) |

**2. Placeholder scan:** no `TODO` / `TBD` / `FIXME` / `XXX` in the plan body. Code blocks contain full implementations, not "similar to before" references.

**3. Type consistency cross-check:**

- `Config` constructor and `load_config` signature consistent in Tasks 2, 9, 10–14.
- `ParsedRequest` / `ParsedItem` consistent in Tasks 5, 6, 10–14.
- `GmailClient` surface in Task 8 mirrors `FakeGmailClient` in Task 7 method-for-method.
- `state.*` mutation function names match between Task 4 definitions and Tasks 10–14 callers.
- `run_tick` signature widened in Task 14 (return tuple from `_ingest` / `_send_followups`) — confirmed Task 14's run_tick body and the Task 11/12/13 increments are compatible.
- Label names defined once in Task 10 (`LABEL_*` constants) and reused everywhere — no drift.

---

## Plan complete and saved to `docs/superpowers/plans/2026-06-29-sample-request-gmail-api.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
