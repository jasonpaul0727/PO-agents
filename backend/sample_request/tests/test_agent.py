"""Tests for the tool-using agent layer."""
from __future__ import annotations

from backend.sample_request.agent import (
    AgentContext,
    SYSTEM_PROMPT,
    build_tools,
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


def test_build_tools_returns_empty_list_when_no_tools_registered_yet():
    ctx = AgentContext(gmail=None, cfg=None, state={})
    assert build_tools(ctx) == []
