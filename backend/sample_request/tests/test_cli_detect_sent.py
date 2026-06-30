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
