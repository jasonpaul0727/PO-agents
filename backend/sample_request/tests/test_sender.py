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
