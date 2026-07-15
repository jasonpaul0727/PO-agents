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
        response.parsed_output = None
    else:
        response.stop_reason = "end_turn"
        response.parsed_output = parsed
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
    assert call.kwargs["output_format"] is ParsedRequest


def test_parse_refusal_raises():
    client = _fake_client(None, refusal=True)
    with pytest.raises(ParserRefused):
        parse_request_body("anything", "subj", client=client)


def test_parse_schema_failure_raises():
    """If the SDK returns no parsed object (e.g. malformed JSON), raise."""
    response = MagicMock()
    response.stop_reason = "end_turn"
    response.parsed_output = None
    client = MagicMock()
    client.messages.parse.return_value = response
    with pytest.raises(ParserSchemaError):
        parse_request_body("body", "subj", client=client)


def test_parsed_item_defaults_qty_unit_to_each():
    item = ParsedItem(name="Widget", qty=1)
    assert item.qty_unit == "each"
    assert item.item_number is None
