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
    S.mark_shipped(state, "T", "1ZA123456789012345")
    req = S.find_request(state, "T")
    assert req["status"] == "shipped"
    assert req["ups_tracking_no"] == "1ZA123456789012345"


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
