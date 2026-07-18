"""Tests for the real GmailClient's query construction.

Regression coverage for the draft-self-match bug: Gmail search includes
drafts unless restricted, so fetch_sent_to must scope its query to the
Sent folder (`in:sent`) or detect_sent will "detect" the draft it just
created in the same tick and mark the request released prematurely.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.sample_request.gmail_client import GmailClient


def _client_with_mock_svc():
    with patch("backend.sample_request.gmail_client.load_credentials"), \
         patch("backend.sample_request.gmail_client.build") as build_mock:
        svc = MagicMock()
        build_mock.return_value = svc
        client = GmailClient(Path("tok"), Path("creds"))
    return client, svc


def test_fetch_sent_to_query_is_scoped_to_sent_folder():
    client, svc = _client_with_mock_svc()
    list_mock = svc.users.return_value.messages.return_value.list
    list_mock.return_value.execute.return_value = {"messages": []}

    client.fetch_sent_to(to="warehouse@example.com",
                         subject_prefix="Release Request: hello")

    _, kwargs = list_mock.call_args
    q = kwargs["q"]
    assert "in:sent" in q, f"query must exclude drafts via in:sent, got: {q}"
    assert 'subject:"Release Request: hello"' in q
    assert "to:warehouse@example.com" in q
