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
