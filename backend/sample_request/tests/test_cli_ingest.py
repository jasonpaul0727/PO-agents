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
