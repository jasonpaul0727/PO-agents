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
