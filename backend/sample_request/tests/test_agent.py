"""Tests for the tool-using agent layer."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from backend.sample_request import state as S
from backend.sample_request.agent import (
    AgentContext,
    SYSTEM_PROMPT,
    _tool_check_sent_folder,
    _tool_flag_needs_attention,
    _tool_get_state_summary,
    _tool_list_pending_emails,
    _tool_list_released_requests,
    _tool_parse_email_content,
    _tool_read_warehouse_thread,
    _tool_record_failure,
    _tool_send_followup_reply,
    build_tools,
)
from backend.sample_request.parser import ParsedItem, ParsedRequest, ParserRefused
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


class _CfgWithModel(_Cfg):
    po_model = "claude-opus-4-8"
    anthropic_api_key = "sk-test"


def _ctx_with_ant(ant_client=None):
    return AgentContext(
        gmail=FakeGmailClient(), cfg=_CfgWithModel(),
        state=S._empty_state(), ant_client=ant_client or MagicMock(),
    )


def test_parse_email_content_success():
    parsed = ParsedRequest(
        recipient="Alice", address="1 Main St",
        items=[ParsedItem(name="cup", qty=2)],
    )
    ctx = _ctx_with_ant()
    with patch(
        "backend.sample_request.agent.parse_request_body", return_value=parsed
    ) as p:
        result = json.loads(_tool_parse_email_content(
            ctx, subject="s", body="please send 2 cups to Alice"))
    p.assert_called_once()
    assert result["ok"] is True
    assert result["parsed"]["recipient"] == "Alice"
    assert result["parsed"]["items"][0]["name"] == "cup"


def test_parse_email_content_returns_error_on_refusal():
    ctx = _ctx_with_ant()
    with patch(
        "backend.sample_request.agent.parse_request_body",
        side_effect=ParserRefused("nope"),
    ):
        result = json.loads(_tool_parse_email_content(ctx, "s", "b"))
    assert result["ok"] is False
    assert result["error_class"] == "ParserRefused"
    assert "nope" in result["message"]


from backend.sample_request.agent import _tool_create_release_draft


def test_create_release_draft_creates_draft_and_updates_state():
    gmail = FakeGmailClient()
    msg = gmail.inject_pending(
        from_="c@example.com", to="sales@example.com",
        subject="need samples", body="send 2 cups to Alice",
    )
    ctx = AgentContext(
        gmail=gmail, cfg=_CfgWithModel(), state=S._empty_state(),
    )
    parsed = {
        "recipient": "Alice", "address": "1 Main St",
        "items": [{"name": "cup", "qty": 2, "qty_unit": "each",
                   "item_number": None}],
    }
    result = json.loads(_tool_create_release_draft(
        ctx,
        thread_id=msg.thread_id, message_id=msg.message_id,
        subject=msg.subject, from_=msg.from_,
        received_at=msg.internal_date,
        parsed_json_str=json.dumps(parsed),
    ))
    assert result["ok"] is True
    assert result["draft_id"].startswith("draft-")
    # State updated
    req = S.find_request(ctx.state, msg.thread_id)
    assert req is not None
    assert req["status"] == "draft_created"
    assert req["draft_id"] == result["draft_id"]
    # Labels updated
    labels = gmail.labels_on(msg.message_id)
    assert "sample-request/pending-release" not in labels
    assert "sample-request/draft-ready" in labels
    # Counter bumped
    assert ctx.actions["ingested"] == 1


def test_create_release_draft_returns_error_on_duplicate():
    gmail = FakeGmailClient()
    msg = gmail.inject_pending(
        from_="c@example.com", to="sales@example.com",
        subject="s", body="b",
    )
    ctx = AgentContext(gmail=gmail, cfg=_CfgWithModel(),
                       state=S._empty_state())
    parsed = {"recipient": "A", "address": "x",
              "items": [{"name": "cup", "qty": 1}]}
    # First call succeeds
    _tool_create_release_draft(
        ctx, thread_id=msg.thread_id, message_id=msg.message_id,
        subject=msg.subject, from_=msg.from_,
        received_at=msg.internal_date,
        parsed_json_str=json.dumps(parsed),
    )
    # Second call is a duplicate
    result = json.loads(_tool_create_release_draft(
        ctx, thread_id=msg.thread_id, message_id=msg.message_id,
        subject=msg.subject, from_=msg.from_,
        received_at=msg.internal_date,
        parsed_json_str=json.dumps(parsed),
    ))
    assert result["ok"] is False
    assert result["error_class"] == "ValueError"


from backend.sample_request.agent import (
    _tool_mark_release_sent, _tool_mark_shipped,
)


def test_mark_release_sent_transitions_state_and_labels():
    gmail = FakeGmailClient()
    msg = gmail.inject_pending(from_="c@e", to="s@e", subject="s", body="b")
    state = S._empty_state()
    S.add_request(
        state, thread_id=msg.thread_id, message_id=msg.message_id,
        subject="s", from_="c@e", received_at="2026-07-14T00:00:00Z",
        parsed={"recipient": "A", "address": "x", "items": []},
    )
    S.mark_draft_created(state, msg.thread_id, draft_id="d1")
    ctx = AgentContext(gmail=gmail, cfg=_CfgWithModel(), state=state)
    result = json.loads(_tool_mark_release_sent(
        ctx,
        thread_id=msg.thread_id,
        release_message_id="sent-1",
        warehouse_thread_id="wt-1",
        released_at="2026-07-14T01:00:00Z",
    ))
    assert result["ok"] is True
    req = S.find_request(state, msg.thread_id)
    assert req["status"] == "released"
    assert req["warehouse_thread_id"] == "wt-1"
    labels = gmail.labels_on(msg.message_id)
    assert "sample-request/released" in labels
    assert ctx.actions["detected_sent"] == 1


def test_mark_shipped_transitions_and_validates_tracking():
    gmail = FakeGmailClient()
    msg = gmail.inject_pending(from_="c@e", to="s@e", subject="s", body="b")
    state = S._empty_state()
    S.add_request(
        state, thread_id=msg.thread_id, message_id=msg.message_id,
        subject="s", from_="c@e", received_at="2026-07-14T00:00:00Z",
        parsed={"recipient": "A", "address": "x", "items": []},
    )
    S.mark_draft_created(state, msg.thread_id, draft_id="d1")
    S.mark_released(state, msg.thread_id, release_message_id="r1",
                    warehouse_thread_id="wt-1",
                    released_at="2026-07-14T01:00:00Z")
    ctx = AgentContext(gmail=gmail, cfg=_CfgWithModel(), state=state)

    # Valid UPS number (18 chars: 1Z + 16 alphanumeric).
    result = json.loads(_tool_mark_shipped(
        ctx, thread_id=msg.thread_id,
        ups_tracking_no="1ZA123456789012345",
    ))
    assert result["ok"] is True
    assert S.find_request(state, msg.thread_id)["status"] == "shipped"
    assert "sample-request/shipped" in gmail.labels_on(msg.message_id)
    assert ctx.actions["shipped"] == 1


def test_mark_shipped_rejects_bad_tracking_string():
    ctx = AgentContext(gmail=FakeGmailClient(), cfg=_CfgWithModel(),
                       state=S._empty_state())
    result = json.loads(_tool_mark_shipped(
        ctx, thread_id="t1", ups_tracking_no="NOTATRACKINGNUMBER",
    ))
    assert result["ok"] is False
    assert result["error_class"] == "ValueError"


def test_send_followup_reply_replies_in_warehouse_thread():
    gmail = FakeGmailClient()
    # Seed a warehouse thread
    rec = gmail.inject_sent(to="warehouse@example.com",
                            subject="Release Request: x",
                            body="please release")
    warehouse_tid = rec["thread_id"]
    msg = gmail.inject_pending(from_="c@e", to="s@e", subject="s", body="b")
    state = S._empty_state()
    S.add_request(
        state, thread_id=msg.thread_id, message_id=msg.message_id,
        subject="s", from_="c@e", received_at="2026-07-14T00:00:00Z",
        parsed={"recipient": "Alice", "address": "x",
                "items": [{"name": "cup", "qty": 1, "qty_unit": "each"}]},
    )
    S.mark_draft_created(state, msg.thread_id, draft_id="d1")
    S.mark_released(state, msg.thread_id, release_message_id="r1",
                    warehouse_thread_id=warehouse_tid,
                    released_at="2026-07-14T01:00:00Z")
    ctx = AgentContext(gmail=gmail, cfg=_CfgWithModel(), state=state)
    result = json.loads(_tool_send_followup_reply(
        ctx, thread_id=msg.thread_id, escalation_level=1,
    ))
    assert result["ok"] is True
    assert "reply_message_id" in result
    req = S.find_request(state, msg.thread_id)
    assert len(req["follow_ups"]) == 1
    assert ctx.actions["followups"] == 1


def test_flag_needs_attention_adds_label():
    gmail = FakeGmailClient()
    msg = gmail.inject_pending(from_="c@e", to="s@e", subject="s", body="b")
    ctx = AgentContext(gmail=gmail, cfg=_CfgWithModel(),
                       state=S._empty_state())
    result = json.loads(_tool_flag_needs_attention(
        ctx, message_id=msg.message_id, reason="repeatedly failed",
    ))
    assert result["ok"] is True
    assert "sample-request/needs-attention" in gmail.labels_on(msg.message_id)
    assert ctx.actions["flagged"] == 1


def test_record_failure_appends_and_returns_count():
    state = S._empty_state()
    S.add_request(
        state, thread_id="t1", message_id="m1", subject="s",
        from_="c@e", received_at="2026-07-14T00:00:00Z",
        parsed={"recipient": "A", "address": "x", "items": []},
    )
    ctx = AgentContext(gmail=FakeGmailClient(), cfg=_CfgWithModel(),
                       state=state)
    r1 = json.loads(_tool_record_failure(
        ctx, thread_id="t1", step="mark_shipped", error_message="boom",
    ))
    assert r1["ok"] is True and r1["failure_count"] == 1
    r2 = json.loads(_tool_record_failure(
        ctx, thread_id="t1", step="mark_shipped", error_message="boom",
    ))
    assert r2["failure_count"] == 2
    assert ctx.actions["errors"] == 2


def test_build_tools_returns_twelve_tools_after_task_7():
    assert len(build_tools(_ctx_with_ant())) == 12
