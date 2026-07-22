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
    run_agent_tick,
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


from pathlib import Path
from backend.sample_request.config import Config
from backend.sample_request.cli import TickResult, _build_parser


def _make_cfg(tmp_path: Path) -> Config:
    return Config(
        warehouse_email="warehouse@example.com",
        anthropic_api_key="sk-test",
        state_file=tmp_path / ".state.json",
        log_path=tmp_path / "tick.log",
    )


def _mock_ant_with_immediate_stop():
    """Return an ant_client whose tool_runner yields nothing (stops immediately)."""
    ant = MagicMock()
    ant.beta.messages.tool_runner.return_value = iter([])
    return ant


def test_run_agent_tick_saves_state_and_returns_tick_result(tmp_path):
    cfg = _make_cfg(tmp_path)
    gmail = FakeGmailClient()
    ant = _mock_ant_with_immediate_stop()
    result = run_agent_tick(cfg, gmail=gmail, ant_client=ant)
    assert isinstance(result, TickResult)
    assert result.outcome == "ok"
    assert cfg.state_file.exists()
    saved = json.loads(cfg.state_file.read_text())
    assert saved["meta"]["last_tick_outcome"] == "ok"
    # tool_runner invoked with expected args
    call = ant.beta.messages.tool_runner.call_args
    assert call.kwargs["model"] == cfg.po_model
    assert call.kwargs["system"] == SYSTEM_PROMPT
    assert len(call.kwargs["tools"]) == 12
    assert call.kwargs["messages"][0]["role"] == "user"


def test_run_agent_tick_outcome_failed_on_runner_exception(tmp_path):
    cfg = _make_cfg(tmp_path)
    gmail = FakeGmailClient()
    ant = MagicMock()

    def _explode(*args, **kwargs):
        raise RuntimeError("runner blew up")

    ant.beta.messages.tool_runner.side_effect = _explode
    result = run_agent_tick(cfg, gmail=gmail, ant_client=ant)
    assert result.outcome == "failed"
    assert cfg.state_file.exists()
    assert json.loads(cfg.state_file.read_text())["meta"]["last_tick_outcome"] == "failed"


def test_tick_parser_accepts_agent_flag():
    parser = _build_parser()
    args = parser.parse_args(["tick", "--agent"])
    assert args.agent is True
    assert args.dry_run is False


def test_tick_parser_default_agent_false():
    parser = _build_parser()
    args = parser.parse_args(["tick"])
    assert args.agent is False


def test_tick_parser_rejects_agent_with_dry_run(capsys):
    parser = _build_parser()
    import pytest
    with pytest.raises(SystemExit):
        parser.parse_args(["tick", "--agent", "--dry-run"])


def _tools_by_name(tools: list) -> dict:
    return {t.name: t for t in tools}


def _make_scripted_runner(script):
    """script: list of callables taking (tools_by_name) -> None.
    Each callable simulates a Claude turn that invokes selected tools.
    Returns a factory suitable for ant.beta.messages.tool_runner.side_effect.
    """
    def _factory(**kwargs):
        tools = _tools_by_name(kwargs["tools"])
        for step in script:
            step(tools)
        return iter([])
    return _factory


def test_e2e_ingest_new_pending_email(tmp_path):
    """Scenario 1: 1 pending email → parse → create_release_draft."""
    cfg = _make_cfg(tmp_path)
    gmail = FakeGmailClient()
    msg = gmail.inject_pending(
        from_="customer@example.com", to="sales@example.com",
        subject="Sample please",
        body="Please send 3 cases of Item #190 orange bowls to Mike Chen, 1412 W 37th Pl Los Angeles CA 90007",
    )
    ant = MagicMock()

    def step1(tools):
        # Simulate Claude: list, parse, create_draft
        pending = json.loads(tools["list_pending_emails"]())
        assert len(pending) == 1
        entry = pending[0]
        parse_result = json.loads(tools["parse_email_content"](
            subject=entry["subject"], body=entry["body_excerpt"],
        ))
        assert parse_result["ok"] is True
        draft_result = json.loads(tools["create_release_draft"](
            thread_id=entry["thread_id"], message_id=entry["message_id"],
            subject=entry["subject"], from_=entry["from"],
            received_at=entry["received_at"],
            parsed_json_str=json.dumps(parse_result["parsed"]),
        ))
        assert draft_result["ok"] is True

    # Patch parse_request_body so no real Claude call is made.
    parsed = ParsedRequest(
        recipient="Mike Chen",
        address="1412 W 37th Pl Los Angeles CA 90007",
        items=[ParsedItem(name="orange bowl", qty=3, qty_unit="cases",
                          item_number="190")],
    )
    with patch(
        "backend.sample_request.agent.parse_request_body",
        return_value=parsed,
    ):
        ant.beta.messages.tool_runner.side_effect = _make_scripted_runner(
            [step1])
        result = run_agent_tick(cfg, gmail=gmail, ant_client=ant)

    assert result.outcome == "ok"
    assert result.ingested == 1
    assert len(gmail.drafts_created) == 1
    saved = json.loads(cfg.state_file.read_text())
    assert len(saved["requests"]) == 1
    assert saved["requests"][0]["status"] == "draft_created"
    assert "sample-request/draft-ready" in gmail.labels_on(msg.message_id)


def test_e2e_ship_detection_from_warehouse_reply(tmp_path):
    """Scenario 2: released request + warehouse reply with UPS → mark_shipped."""
    cfg = _make_cfg(tmp_path)
    gmail = FakeGmailClient()
    orig = gmail.inject_pending(from_="c@e", to="s@e", subject="s", body="b")
    rec = gmail.inject_sent(to="warehouse@example.com",
                            subject="Release Request: x",
                            body="please release")
    warehouse_tid = rec["thread_id"]
    gmail.inject_thread_reply(
        warehouse_tid, from_="warehouse@example.com",
        body="Shipped; tracking 1ZA123456789012345",
    )
    # Seed state to released
    state = S._empty_state()
    S.add_request(
        state, thread_id=orig.thread_id, message_id=orig.message_id,
        subject="s", from_="c@e", received_at="2026-07-14T00:00:00Z",
        parsed={"recipient": "A", "address": "x", "items": []},
    )
    S.mark_draft_created(state, orig.thread_id, draft_id="d1")
    S.mark_released(state, orig.thread_id, release_message_id="r1",
                    warehouse_thread_id=warehouse_tid,
                    released_at="2026-07-14T01:00:00Z")
    S.save_state(cfg.state_file, state)

    ant = MagicMock()

    def step1(tools):
        released = json.loads(tools["list_released_requests"]())
        assert len(released) == 1
        thread_id = released[0]["thread_id"]
        wt = released[0]["warehouse_thread_id"]
        thread = json.loads(tools["read_warehouse_thread"](thread_id=wt))
        # Extract tracking (Claude would do this via regex/reasoning)
        import re
        matches = [re.search(r"1Z[0-9A-Z]{16}", m["body_excerpt"])
                   for m in thread]
        tracking = next((m.group(0) for m in matches if m), None)
        assert tracking == "1ZA123456789012345"
        result = json.loads(tools["mark_shipped"](
            thread_id=thread_id, ups_tracking_no=tracking,
        ))
        assert result["ok"] is True

    ant.beta.messages.tool_runner.side_effect = _make_scripted_runner([step1])
    result = run_agent_tick(cfg, gmail=gmail, ant_client=ant)

    assert result.outcome == "ok"
    assert result.shipped == 1
    saved = json.loads(cfg.state_file.read_text())
    assert saved["requests"][0]["status"] == "shipped"
    assert saved["requests"][0]["ups_tracking_no"] == "1ZA123456789012345"
    assert "sample-request/shipped" in gmail.labels_on(orig.message_id)


def test_e2e_send_followup_when_stale(tmp_path):
    """Scenario 3: released > 4h with no reply → send_followup_reply."""
    cfg = _make_cfg(tmp_path)
    gmail = FakeGmailClient()
    orig = gmail.inject_pending(from_="c@e", to="s@e", subject="s", body="b")
    rec = gmail.inject_sent(to="warehouse@example.com",
                            subject="Release Request: x", body="please")
    warehouse_tid = rec["thread_id"]
    state = S._empty_state()
    S.add_request(
        state, thread_id=orig.thread_id, message_id=orig.message_id,
        subject="s", from_="c@e", received_at="2026-07-14T00:00:00Z",
        parsed={"recipient": "Alice", "address": "x",
                "items": [{"name": "cup", "qty": 1, "qty_unit": "each"}]},
    )
    S.mark_draft_created(state, orig.thread_id, draft_id="d1")
    # released 5 hours ago
    old_ts = "2026-07-14T00:00:00Z"
    S.mark_released(state, orig.thread_id, release_message_id="r1",
                    warehouse_thread_id=warehouse_tid, released_at=old_ts)
    S.save_state(cfg.state_file, state)
    ant = MagicMock()

    def step1(tools):
        released = json.loads(tools["list_released_requests"]())
        result = json.loads(tools["send_followup_reply"](
            thread_id=released[0]["thread_id"], escalation_level=1,
        ))
        assert result["ok"] is True

    ant.beta.messages.tool_runner.side_effect = _make_scripted_runner([step1])
    result = run_agent_tick(cfg, gmail=gmail, ant_client=ant)

    assert result.followups == 1
    saved = json.loads(cfg.state_file.read_text())
    assert len(saved["requests"][0]["follow_ups"]) == 1
