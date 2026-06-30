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
