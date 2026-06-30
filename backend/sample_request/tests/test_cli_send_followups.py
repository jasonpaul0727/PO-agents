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
    # During seeding, freeze time to before the release to prevent followups from being sent
    seed_time = S.parse_iso(released_iso) - timedelta(hours=24)
    run_tick(config, gmail=fake_gmail, parser_fn=lambda b, s: parsed, now=lambda: seed_time)
    draft = fake_gmail.drafts_created[0]
    sent = fake_gmail.inject_sent(
        to=config.warehouse_email,
        subject=draft["subject"],
        body=draft["body"],
        internal_date=released_iso,
    )
    run_tick(config, gmail=fake_gmail, parser_fn=lambda b, s: None, now=lambda: seed_time)
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
