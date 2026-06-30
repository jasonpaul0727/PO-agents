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
        body="Shipped via UPS. Tracking: 1ZA123456789012345 — ETA 2 days.",
    )
    result = run_tick(config, gmail=fake_gmail, parser_fn=lambda b, s: None)
    assert result.shipped == 1
    state = S.load_state(config.state_file)
    req = state["requests"][0]
    assert req["status"] == "shipped"
    assert req["ups_tracking_no"] == "1ZA123456789012345"
    assert req["shipped_at"] is not None
    assert "sample-request/shipped" in fake_gmail.labels_on(orig_id)
    assert "sample-request/released" not in fake_gmail.labels_on(orig_id)
