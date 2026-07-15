"""Tests for the tool-using agent layer."""
from __future__ import annotations

import json

from backend.sample_request import state as S
from backend.sample_request.agent import (
    AgentContext,
    SYSTEM_PROMPT,
    _tool_check_sent_folder,
    _tool_get_state_summary,
    _tool_list_pending_emails,
    _tool_list_released_requests,
    _tool_read_warehouse_thread,
    build_tools,
)
from backend.sample_request.tests.fake_gmail import FakeGmailClient


def _make_ctx(gmail=None, state=None):
    return AgentContext(
        gmail=gmail or FakeGmailClient(),
        cfg=None,
        state=state if state is not None else S._empty_state(),
    )


def test_system_prompt_mentions_sample_request_role():
    assert "sample" in SYSTEM_PROMPT.lower()
    assert "warehouse" in SYSTEM_PROMPT.lower()


def test_agent_context_has_action_counters():
    ctx = AgentContext(gmail=None, cfg=None, state={})
    assert set(ctx.actions.keys()) == {
        "ingested", "detected_sent", "shipped",
        "followups", "flagged", "errors",
    }
    assert all(v == 0 for v in ctx.actions.values())


def test_list_pending_emails_returns_pending_msgs_as_json():
    gmail = FakeGmailClient()
    gmail.inject_pending(
        from_="customer@example.com",
        to="sales@example.com",
        subject="Please send samples",
        body="Send 2 cases of Item #42 to Alice, 100 Main St",
    )
    ctx = _make_ctx(gmail=gmail)
    payload = json.loads(_tool_list_pending_emails(ctx))
    assert isinstance(payload, list)
    assert len(payload) == 1
    entry = payload[0]
    assert entry["from"] == "customer@example.com"
    assert entry["subject"] == "Please send samples"
    assert "Send 2 cases" in entry["body_excerpt"]
    assert "message_id" in entry and "thread_id" in entry


def test_list_pending_emails_empty_when_no_pending():
    ctx = _make_ctx()
    assert json.loads(_tool_list_pending_emails(ctx)) == []


def test_list_released_requests_includes_released_only():
    state = S._empty_state()
    S.add_request(
        state, thread_id="t1", message_id="m1", subject="s",
        from_="c@e", received_at="2026-07-14T00:00:00Z",
        parsed={"recipient": "Alice", "address": "x", "items": []},
    )
    S.mark_draft_created(state, "t1", draft_id="d1")
    S.mark_released(state, "t1", release_message_id="r1",
                    warehouse_thread_id="wt1",
                    released_at="2026-07-14T01:00:00Z")

    S.add_request(
        state, thread_id="t2", message_id="m2", subject="s2",
        from_="c@e", received_at="2026-07-14T00:00:00Z",
        parsed={"recipient": "Bob", "address": "y", "items": []},
    )

    ctx = _make_ctx(state=state)
    payload = json.loads(_tool_list_released_requests(ctx))
    assert len(payload) == 1
    assert payload[0]["thread_id"] == "t1"
    assert payload[0]["recipient"] == "Alice"
    assert payload[0]["warehouse_thread_id"] == "wt1"
    assert payload[0]["follow_ups_count"] == 0


def test_get_state_summary_counts_by_status():
    state = S._empty_state()
    for tid, status in [("a", "draft_created"), ("b", "released"),
                        ("c", "released"), ("d", "shipped")]:
        S.add_request(
            state, thread_id=tid, message_id=f"m-{tid}", subject="s",
            from_="c@e", received_at="2026-07-14T00:00:00Z",
            parsed={"recipient": "X", "address": "y", "items": []},
        )
        state["requests"][-1]["status"] = status
    ctx = _make_ctx(state=state)
    summary = json.loads(_tool_get_state_summary(ctx))
    assert summary["total"] == 4
    assert summary["by_status"] == {
        "draft_created": 1, "released": 2, "shipped": 1,
    }


class _Cfg:
    warehouse_email = "warehouse@example.com"


def test_read_warehouse_thread_returns_all_messages_in_thread():
    gmail = FakeGmailClient()
    # Seed a sent release message so the thread exists.
    rec = gmail.inject_sent(
        to="warehouse@example.com",
        subject="Release Request: samples",
        body="please release",
    )
    thread_id = rec["thread_id"]
    gmail.inject_thread_reply(thread_id, from_="warehouse@example.com",
                              body="Shipped, tracking 1ZA123456789012345")
    ctx = AgentContext(gmail=gmail, cfg=_Cfg(), state=S._empty_state())
    payload = json.loads(_tool_read_warehouse_thread(ctx, thread_id))
    assert len(payload) == 2
    assert "1ZA123456789012345" in payload[1]["body_excerpt"]
    assert payload[0]["from"] == "me@example.com"


def test_read_warehouse_thread_empty_for_unknown_thread():
    ctx = AgentContext(gmail=FakeGmailClient(), cfg=_Cfg(),
                       state=S._empty_state())
    assert json.loads(_tool_read_warehouse_thread(ctx, "nope")) == []


def test_check_sent_folder_returns_matching_sent_msgs():
    gmail = FakeGmailClient()
    gmail.inject_sent(to="warehouse@example.com",
                      subject="Release Request: Please send samples",
                      body="x")
    gmail.inject_sent(to="warehouse@example.com",
                      subject="Unrelated email",
                      body="y")
    ctx = AgentContext(gmail=gmail, cfg=_Cfg(), state=S._empty_state())
    matches = json.loads(_tool_check_sent_folder(
        ctx, "Release Request: Please send samples"))
    assert len(matches) == 1
    assert matches[0]["subject"].startswith("Release Request")


def test_build_tools_returns_five_tools_after_task_3():
    ctx = AgentContext(gmail=FakeGmailClient(), cfg=_Cfg(),
                       state=S._empty_state())
    assert len(build_tools(ctx)) == 5
