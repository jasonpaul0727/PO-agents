# Sample Request Agent Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a tool-using Claude agent layer to the sample-request module. The existing hardcoded 4-step workflow (ingest → detect_sent → check_shipments → send_followups) stays; a new `--agent` flag on `tick` runs Claude with 12 fine-grained tools and lets it decide which to call.

**Architecture:** New `backend/sample_request/agent.py` module defines 12 `@beta_tool`-decorated functions (5 read + 1 parse + 6 write) that wrap existing state/gmail/sender primitives. A `run_agent_tick()` orchestrator loads state, builds tools bound to an `AgentContext`, invokes `client.beta.messages.tool_runner()`, and persists state. `cli.py`'s `_cmd_tick` gets an `--agent` flag that branches to the new orchestrator. The workflow-mode `run_tick` is unchanged; both modes coexist.

**Tech Stack:** Python 3.12, `anthropic` SDK (beta tool runner), Pydantic v2 (existing `TickResult`), existing `FakeGmailClient` for tests.

## Global Constraints

- **Python interpreter:** Always use `.venv/bin/python3`, `.venv/bin/pip`, `.venv/bin/pytest`. System Python is PEP-668 locked; `pip install` there is blocked.
- **Model:** `claude-opus-4-8` (already the default in `Config.po_model`, loaded from `.env`'s `PO_MODEL`).
- **Anthropic SDK beta tool runner:** `from anthropic import beta_tool`; `client.beta.messages.tool_runner(model=..., max_tokens=..., system=..., tools=[...], messages=[...])`. Iterate the returned runner; iteration stops when Claude has no more tool calls.
- **Parser SDK correction:** `client.messages.parse(...)` uses `output_format=<PydanticModel>` (not `response_model`) and returns `.parsed_output` (not `.parsed`). `parser.parse_request_body` already uses the correct API — reuse it.
- **UPS tracking:** validated by `state.UPS_TRACKING_RE` = `\b1Z[0-9A-Z]{16}\b`. Correct test string: `1ZA123456789012345` (18 chars total, 16 after `1Z`). Never use `1ZA1234567890123456` (19 chars, fails the regex).
- **Lazy anthropic import:** `import anthropic` and any usage of `beta_tool` / tool runner must happen inside function bodies, not at module top level, so tests that don't need the SDK still import `agent.py` cleanly. Mirror the pattern in `cli.py:_cmd_tick`.
- **Additive change:** `run_tick` (workflow) and `_cmd_tick`'s existing branch stay untouched; the `--agent` flag adds a new branch that calls `run_agent_tick`. All 102 existing tests must remain passing after every task.
- **Reuse existing primitives:** all state mutations go through `backend.sample_request.state as S` helpers (`add_request`, `mark_draft_created`, `mark_released`, `mark_shipped`, `record_followup`, `append_tick_error`, `bump_ingest_failure`, `reset_ingest_failure`, `update_meta`). Label constants (`LABEL_PENDING`, etc.) live in `cli.py` — import from there.
- **Test path:** new tests go in `backend/sample_request/tests/test_agent.py`. `conftest.py` in that directory already handles fixture wiring.
- **Never call `anthropic.Anthropic()` in tests.** Tests either (a) call `_tool_*` impl functions directly with a fake `AgentContext`, or (b) test `run_agent_tick` with a mock `ant_client` whose `.beta.messages.tool_runner()` returns a controlled iterator.
- **Cost note:** ~$0.10–0.30 per agent tick vs ~$0.005 for workflow tick. Document this in README, do not add cost caps as code (task 11's docs cover it).
- **No new dependencies.** `anthropic`, `pydantic`, `python-dotenv`, `google-*` are already in the venv.

---

### Task 1: Scaffolding — module skeleton, AgentContext, empty build_tools

**Files:**
- Create: `backend/sample_request/agent.py`
- Create: `backend/sample_request/tests/test_agent.py`

**Interfaces:**
- Consumes: `Config` from `backend.sample_request.config`, `state as S` from `backend.sample_request.state`
- Produces: `SYSTEM_PROMPT: str`, `AgentContext` dataclass, `build_tools(ctx: AgentContext) -> list`, `run_agent_tick(cfg, *, gmail, ant_client) -> TickResult` (all consumed by tasks 2–10)

- [ ] **Step 1: Write the failing test**

Create `backend/sample_request/tests/test_agent.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv/bin/pytest backend/sample_request/tests/test_agent.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'backend.sample_request.agent'`

- [ ] **Step 3: Create agent.py skeleton**

Create `backend/sample_request/agent.py`:

```python
"""Tool-using Claude agent layer for the sample-request pipeline.

Wraps the workflow primitives (ingest / detect_sent / check_shipments /
send_followups) as Anthropic tools and lets Claude decide which to call
each tick. Alternative execution mode to `cli.run_tick`; both coexist.

Consumers of this module (tests, cli.py) can import AgentContext,
SYSTEM_PROMPT, build_tools, and run_agent_tick without the `anthropic`
package being importable — the SDK is only touched inside the closure
bodies and inside run_agent_tick.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any


SYSTEM_PROMPT = """You are the sample-request operations agent for a sales team.

Your job every tick: review the sample-request mailbox and take actions
that move requests toward shipment.

Guideline workflow (not strict — you decide the order):
1. Call `list_pending_emails` to see new customer requests.
2. For each, call `parse_email_content` to extract recipient / address /
   items, then `create_release_draft` to draft a message to the warehouse.
3. Call `check_sent_folder` to detect drafts the user has manually sent;
   for each match, call `mark_release_sent`.
4. Call `list_released_requests`. For each released request:
   - Call `read_warehouse_thread` to look for a UPS tracking number
     (format: 1Z followed by 16 alphanumeric characters).
     If found, call `mark_shipped`.
   - If the request is stale (no warehouse reply in >4h), decide whether
     to send a follow-up via `send_followup_reply`.

Escalation:
- If any operation fails 3 times consecutively for the same request, call
  `flag_needs_attention` — do not keep retrying beyond that.

Constraints:
- NEVER reply directly to the customer (only to the warehouse thread).
- NEVER call `mark_shipped` without first verifying the UPS tracking
  number in the warehouse thread body.
- Do not re-parse an email that is already in state.

When you have processed everything actionable, respond with a JSON
summary of actions taken:
  {"ingested": N, "detected_sent": N, "shipped": N,
   "followups": N, "flagged": N, "errors": N}
and end your turn.
"""


@dataclass
class AgentContext:
    """Per-tick execution context passed to every tool implementation."""
    gmail: Any                      # GmailClient or FakeGmailClient
    cfg: Any                        # Config (avoid import to keep tests light)
    state: dict
    log: logging.Logger = field(
        default_factory=lambda: logging.getLogger("sample_request.agent")
    )
    actions: dict[str, int] = field(default_factory=lambda: {
        "ingested": 0,
        "detected_sent": 0,
        "shipped": 0,
        "followups": 0,
        "flagged": 0,
        "errors": 0,
    })


def build_tools(ctx: AgentContext) -> list:
    """Build the list of @beta_tool-decorated functions bound to ctx.

    Populated in subsequent tasks. Returns [] while empty so
    run_agent_tick can be exercised end-to-end during scaffolding.
    """
    return []
```

- [ ] **Step 4: Run tests to verify they pass**

```
.venv/bin/pytest backend/sample_request/tests/test_agent.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Run the full test suite for regression check**

```
.venv/bin/pytest -q
```

Expected: 105 passed (102 pre-existing + 3 new).

- [ ] **Step 6: Commit**

```bash
git add backend/sample_request/agent.py backend/sample_request/tests/test_agent.py
git commit -m "feat(sample_request): agent.py scaffolding (SYSTEM_PROMPT, AgentContext, build_tools stub)"
```

---

### Task 2: Read tools — list_pending_emails, list_released_requests, get_state_summary

**Files:**
- Modify: `backend/sample_request/agent.py`
- Modify: `backend/sample_request/tests/test_agent.py`

**Interfaces:**
- Consumes: `AgentContext` (from Task 1), `state as S`
- Produces:
  - `_tool_list_pending_emails(ctx) -> str` — JSON list of `{message_id, thread_id, from, subject, body_excerpt, received_at}`
  - `_tool_list_released_requests(ctx) -> str` — JSON list of `{thread_id, recipient, released_at, warehouse_thread_id, follow_ups_count}`
  - `_tool_get_state_summary(ctx) -> str` — JSON dict `{total, by_status: {...}, needs_attention_flagged: int}`
  - After this task, `build_tools(ctx)` returns 3 wrapped tools.

- [ ] **Step 1: Write the failing test**

Append to `backend/sample_request/tests/test_agent.py`:

```python
import json
from backend.sample_request import state as S
from backend.sample_request.agent import (
    _tool_list_pending_emails,
    _tool_list_released_requests,
    _tool_get_state_summary,
)
from backend.sample_request.tests.fake_gmail import FakeGmailClient


def _make_ctx(gmail=None, state=None):
    return AgentContext(
        gmail=gmail or FakeGmailClient(),
        cfg=None,
        state=state if state is not None else S._empty_state(),
    )


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
    )  # left in draft_created

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


def test_build_tools_returns_three_tools_after_task_2():
    ctx = _make_ctx()
    tools = build_tools(ctx)
    assert len(tools) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv/bin/pytest backend/sample_request/tests/test_agent.py -v
```

Expected: FAIL with `ImportError: cannot import name '_tool_list_pending_emails'` and the build_tools assertion failing.

- [ ] **Step 3: Implement the three impl functions and register them**

In `backend/sample_request/agent.py`, add these functions **above** `build_tools` (add `import json` and `from backend.sample_request import state as S` at the top):

```python
def _tool_list_pending_emails(ctx: AgentContext) -> str:
    msgs = ctx.gmail.fetch_pending()
    payload = [
        {
            "message_id": m.message_id,
            "thread_id": m.thread_id,
            "from": m.from_,
            "subject": m.subject,
            "body_excerpt": (m.body or "")[:2000],
            "received_at": m.internal_date,
        }
        for m in msgs
    ]
    return json.dumps(payload)


def _tool_list_released_requests(ctx: AgentContext) -> str:
    out = []
    for req in ctx.state.get("requests", []):
        if req.get("status") != "released":
            continue
        parsed = req.get("parsed") or {}
        out.append({
            "thread_id": req["thread_id"],
            "recipient": parsed.get("recipient", ""),
            "released_at": req.get("released_at"),
            "warehouse_thread_id": req.get("warehouse_thread_id"),
            "follow_ups_count": len(req.get("follow_ups") or []),
        })
    return json.dumps(out)


def _tool_get_state_summary(ctx: AgentContext) -> str:
    reqs = ctx.state.get("requests", [])
    by_status: dict[str, int] = {}
    for r in reqs:
        s = r.get("status", "unknown")
        by_status[s] = by_status.get(s, 0) + 1
    return json.dumps({
        "total": len(reqs),
        "by_status": by_status,
        "needs_attention_flagged": sum(
            1 for r in reqs if any(
                e.get("step") == "flag_needs_attention"
                for e in r.get("tick_errors") or []
            )
        ),
    })
```

Then rewrite `build_tools`:

```python
def build_tools(ctx: AgentContext) -> list:
    from anthropic import beta_tool

    @beta_tool
    def list_pending_emails() -> str:
        """List sample-request emails labeled 'pending-release' that still need drafts.

        Returns a JSON array. Each entry: {message_id, thread_id, from,
        subject, body_excerpt, received_at}. body_excerpt is capped at 2000 chars.
        """
        return _tool_list_pending_emails(ctx)

    @beta_tool
    def list_released_requests() -> str:
        """List released requests that are not yet shipped.

        Returns a JSON array. Each entry: {thread_id, recipient,
        released_at, warehouse_thread_id, follow_ups_count}.
        """
        return _tool_list_released_requests(ctx)

    @beta_tool
    def get_state_summary() -> str:
        """Return a high-level summary of current request state.

        Returns a JSON object: {total, by_status: {status: count},
        needs_attention_flagged: count}.
        """
        return _tool_get_state_summary(ctx)

    return [list_pending_emails, list_released_requests, get_state_summary]
```

- [ ] **Step 4: Run tests to verify they pass**

```
.venv/bin/pytest backend/sample_request/tests/test_agent.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Run the full test suite**

```
.venv/bin/pytest -q
```

Expected: 109 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/sample_request/agent.py backend/sample_request/tests/test_agent.py
git commit -m "feat(sample_request): agent tools (list_pending_emails, list_released_requests, get_state_summary)"
```

---

### Task 3: Read tools — read_warehouse_thread, check_sent_folder

**Files:**
- Modify: `backend/sample_request/agent.py`
- Modify: `backend/sample_request/tests/test_agent.py`

**Interfaces:**
- Consumes: `AgentContext`, `Config.warehouse_email`
- Produces:
  - `_tool_read_warehouse_thread(ctx, thread_id: str) -> str` — JSON list of `{message_id, from, subject, body_excerpt, internal_date}`
  - `_tool_check_sent_folder(ctx, subject_prefix: str) -> str` — JSON list of `{message_id, thread_id, subject, internal_date}`
  - `build_tools(ctx)` now returns 5 tools.

- [ ] **Step 1: Write the failing test**

Append to `test_agent.py`:

```python
from backend.sample_request.agent import (
    _tool_read_warehouse_thread,
    _tool_check_sent_folder,
)


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
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv/bin/pytest backend/sample_request/tests/test_agent.py -v
```

Expected: FAIL with ImportError on the new impl names.

- [ ] **Step 3: Implement the two impl functions and register them**

Add to `agent.py` above `build_tools`:

```python
def _tool_read_warehouse_thread(ctx: AgentContext, thread_id: str) -> str:
    msgs = ctx.gmail.fetch_thread(thread_id)
    payload = [
        {
            "message_id": m.message_id,
            "from": m.from_,
            "subject": m.subject,
            "body_excerpt": (m.body or "")[:2000],
            "internal_date": m.internal_date,
        }
        for m in msgs
    ]
    return json.dumps(payload)


def _tool_check_sent_folder(ctx: AgentContext, subject_prefix: str) -> str:
    msgs = ctx.gmail.fetch_sent_to(
        to=ctx.cfg.warehouse_email,
        subject_prefix=subject_prefix,
    )
    payload = [
        {
            "message_id": m.message_id,
            "thread_id": m.thread_id,
            "subject": m.subject,
            "internal_date": m.internal_date,
        }
        for m in msgs
    ]
    return json.dumps(payload)
```

Extend `build_tools` (add the two @beta_tool closures and return them):

```python
    @beta_tool
    def read_warehouse_thread(thread_id: str) -> str:
        """Read all messages in a warehouse thread.

        Use this to look for a UPS tracking number in the warehouse's reply.
        UPS format: 1Z followed by 16 alphanumeric chars, e.g. 1ZA123456789012345.
        Returns JSON array of {message_id, from, subject, body_excerpt, internal_date}.
        """
        return _tool_read_warehouse_thread(ctx, thread_id)

    @beta_tool
    def check_sent_folder(subject_prefix: str) -> str:
        """Check the Sent folder for messages to the warehouse matching a subject prefix.

        Use this to detect drafts the user has manually sent. Typical
        subject_prefix: 'Release Request: <original subject>'.
        Returns JSON array of {message_id, thread_id, subject, internal_date}.
        """
        return _tool_check_sent_folder(ctx, subject_prefix)

    return [
        list_pending_emails, list_released_requests, get_state_summary,
        read_warehouse_thread, check_sent_folder,
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

```
.venv/bin/pytest backend/sample_request/tests/test_agent.py -v
```

Expected: 11 passed.

- [ ] **Step 5: Run full suite**

```
.venv/bin/pytest -q
```

Expected: 113 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/sample_request/agent.py backend/sample_request/tests/test_agent.py
git commit -m "feat(sample_request): agent tools (read_warehouse_thread, check_sent_folder)"
```

---

### Task 4: Parse tool — parse_email_content

**Files:**
- Modify: `backend/sample_request/agent.py`
- Modify: `backend/sample_request/tests/test_agent.py`

**Interfaces:**
- Consumes: `AgentContext.cfg` (needs `po_model`, `anthropic_api_key`), existing `parser.parse_request_body`
- Produces:
  - `_tool_parse_email_content(ctx, subject: str, body: str) -> str` — JSON `{"ok": True, "parsed": {...}}` or `{"ok": False, "error_class": str, "message": str}`
  - `build_tools(ctx)` now returns 6 tools.

**Design note:** the parse tool internally calls `parser.parse_request_body`, which itself calls Claude (`client.messages.parse`). This is the "nested-Claude" pattern: the agent picks up an email, hands it to `parse_email_content`, which spins up a separate structured-output call. Cheaper than putting the raw body in the agent's own context every time.

We need an Anthropic client for the nested call. Store it on `AgentContext.ant_client` (added below).

- [ ] **Step 1: Extend AgentContext with ant_client, then write the failing test**

Change `AgentContext` in `agent.py`:

```python
@dataclass
class AgentContext:
    gmail: Any
    cfg: Any
    state: dict
    ant_client: Any = None          # optional in tests where parser is stubbed
    log: logging.Logger = field(
        default_factory=lambda: logging.getLogger("sample_request.agent")
    )
    actions: dict[str, int] = field(default_factory=lambda: {
        "ingested": 0,
        "detected_sent": 0,
        "shipped": 0,
        "followups": 0,
        "flagged": 0,
        "errors": 0,
    })
```

Append to `test_agent.py`:

```python
from unittest.mock import MagicMock, patch
from backend.sample_request.agent import _tool_parse_email_content
from backend.sample_request.parser import ParsedRequest, ParsedItem, ParserRefused


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


def test_build_tools_returns_six_tools_after_task_4():
    assert len(build_tools(_ctx_with_ant())) == 6
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv/bin/pytest backend/sample_request/tests/test_agent.py -v
```

Expected: FAIL on ImportError / missing tool count.

- [ ] **Step 3: Implement the impl function and register it**

Add to `agent.py` (import `parse_request_body` at top: `from backend.sample_request.parser import parse_request_body`):

```python
def _tool_parse_email_content(ctx: AgentContext, subject: str, body: str) -> str:
    try:
        parsed = parse_request_body(
            body, subject,
            client=ctx.ant_client,
            model=ctx.cfg.po_model,
        )
    except Exception as exc:            # noqa: BLE001
        return json.dumps({
            "ok": False,
            "error_class": exc.__class__.__name__,
            "message": str(exc)[:500],
        })
    return json.dumps({"ok": True, "parsed": parsed.model_dump()})
```

Extend `build_tools`:

```python
    @beta_tool
    def parse_email_content(subject: str, body: str) -> str:
        """Extract structured fields (recipient, address, items) from an email body.

        Internally invokes a separate Claude call for strict-schema extraction.
        Call this once per new pending email before creating a draft.
        Returns JSON: on success {"ok": true, "parsed": {recipient, address,
        items: [{name, qty, qty_unit, item_number}]}}; on failure
        {"ok": false, "error_class": str, "message": str}.
        """
        return _tool_parse_email_content(ctx, subject, body)

    return [
        list_pending_emails, list_released_requests, get_state_summary,
        read_warehouse_thread, check_sent_folder,
        parse_email_content,
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

```
.venv/bin/pytest backend/sample_request/tests/test_agent.py -v
```

Expected: 14 passed.

- [ ] **Step 5: Full suite**

```
.venv/bin/pytest -q
```

Expected: 116 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/sample_request/agent.py backend/sample_request/tests/test_agent.py
git commit -m "feat(sample_request): agent tool (parse_email_content) + AgentContext.ant_client"
```

---

### Task 5: Write tool — create_release_draft

**Files:**
- Modify: `backend/sample_request/agent.py`
- Modify: `backend/sample_request/tests/test_agent.py`

**Interfaces:**
- Consumes: `AgentContext`, `sender.build_release_email`, `state.add_request`, `state.mark_draft_created`, `LABEL_PENDING`, `LABEL_DRAFT` (import from `cli`)
- Produces:
  - `_tool_create_release_draft(ctx, thread_id, message_id, subject, from_, received_at, parsed_json_str) -> str` — JSON `{"ok": True, "draft_id": str}` or `{"ok": False, "error_class", "message"}`. Increments `ctx.actions["ingested"]` on success.
  - `build_tools(ctx)` now returns 7 tools.

**Note on tool signature:** Anthropic tools take primitive params or JSON strings. We accept `parsed_json_str` (the output of `parse_email_content`'s `parsed` field re-serialized) and parse it internally.

- [ ] **Step 1: Write the failing test**

Append to `test_agent.py`:

```python
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


def test_build_tools_returns_seven_tools_after_task_5():
    assert len(build_tools(_ctx_with_ant())) == 7
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv/bin/pytest backend/sample_request/tests/test_agent.py -v
```

Expected: FAIL on missing `_tool_create_release_draft`.

- [ ] **Step 3: Implement the impl function and register it**

Add imports at top of `agent.py`:

```python
from backend.sample_request.cli import (
    LABEL_PENDING, LABEL_DRAFT, LABEL_RELEASED, LABEL_SHIPPED, LABEL_ATTENTION,
)
from backend.sample_request.parser import ParsedRequest
from backend.sample_request.sender import build_release_email
```

Add above `build_tools`:

```python
def _tool_create_release_draft(
    ctx: AgentContext,
    *,
    thread_id: str,
    message_id: str,
    subject: str,
    from_: str,
    received_at: str,
    parsed_json_str: str,
) -> str:
    try:
        parsed_dict = json.loads(parsed_json_str)
        parsed = ParsedRequest(**parsed_dict)
        rel_subject, rel_body = build_release_email(parsed, subject, from_)
        draft_id = ctx.gmail.create_draft(
            to=ctx.cfg.warehouse_email,
            subject=rel_subject,
            body=rel_body,
            in_reply_to=None,
        )
        ctx.gmail.relabel(
            message_id, remove=[LABEL_PENDING], add=[LABEL_DRAFT],
        )
        S.add_request(
            ctx.state,
            thread_id=thread_id, message_id=message_id,
            subject=subject, from_=from_, received_at=received_at,
            parsed=parsed.model_dump(),
        )
        S.mark_draft_created(ctx.state, thread_id, draft_id=draft_id)
        S.reset_ingest_failure(ctx.state, message_id)
    except Exception as exc:                # noqa: BLE001
        ctx.actions["errors"] += 1
        return json.dumps({
            "ok": False,
            "error_class": exc.__class__.__name__,
            "message": str(exc)[:500],
        })
    ctx.actions["ingested"] += 1
    return json.dumps({"ok": True, "draft_id": draft_id})
```

Extend `build_tools`:

```python
    @beta_tool
    def create_release_draft(
        thread_id: str, message_id: str, subject: str, from_: str,
        received_at: str, parsed_json_str: str,
    ) -> str:
        """Create a Gmail draft to the warehouse, register the request in state,
        and transition the pending email's label to draft-ready.

        parsed_json_str: the "parsed" object from parse_email_content, re-serialized
        as a JSON string.
        Returns JSON {"ok": true, "draft_id": str} or
        {"ok": false, "error_class": str, "message": str}.
        """
        return _tool_create_release_draft(
            ctx,
            thread_id=thread_id, message_id=message_id,
            subject=subject, from_=from_, received_at=received_at,
            parsed_json_str=parsed_json_str,
        )

    return [
        list_pending_emails, list_released_requests, get_state_summary,
        read_warehouse_thread, check_sent_folder,
        parse_email_content, create_release_draft,
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

```
.venv/bin/pytest backend/sample_request/tests/test_agent.py -v
```

Expected: 17 passed.

- [ ] **Step 5: Full suite**

```
.venv/bin/pytest -q
```

Expected: 119 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/sample_request/agent.py backend/sample_request/tests/test_agent.py
git commit -m "feat(sample_request): agent tool (create_release_draft) + label imports"
```

---

### Task 6: Write tools — mark_release_sent, mark_shipped

**Files:**
- Modify: `backend/sample_request/agent.py`
- Modify: `backend/sample_request/tests/test_agent.py`

**Interfaces:**
- Consumes: `state.mark_released`, `state.mark_shipped`, `LABEL_DRAFT`/`LABEL_RELEASED`/`LABEL_SHIPPED`
- Produces:
  - `_tool_mark_release_sent(ctx, thread_id, release_message_id, warehouse_thread_id, released_at) -> str`
  - `_tool_mark_shipped(ctx, thread_id, ups_tracking_no) -> str`
  - `build_tools(ctx)` returns 9 tools.

- [ ] **Step 1: Write the failing test**

Append to `test_agent.py`:

```python
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


def test_build_tools_returns_nine_tools_after_task_6():
    assert len(build_tools(_ctx_with_ant())) == 9
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv/bin/pytest backend/sample_request/tests/test_agent.py -v
```

Expected: FAIL on missing imports.

- [ ] **Step 3: Implement both impl functions and register them**

Add above `build_tools`:

```python
def _tool_mark_release_sent(
    ctx: AgentContext, *,
    thread_id: str, release_message_id: str,
    warehouse_thread_id: str, released_at: str,
) -> str:
    try:
        req = S.find_request(ctx.state, thread_id)
        if req is None:
            raise KeyError(f"thread_id not found: {thread_id}")
        S.mark_released(
            ctx.state, thread_id,
            release_message_id=release_message_id,
            warehouse_thread_id=warehouse_thread_id,
            released_at=released_at,
        )
        ctx.gmail.relabel(
            req["original_message_id"],
            remove=[LABEL_DRAFT], add=[LABEL_RELEASED],
        )
    except Exception as exc:                # noqa: BLE001
        ctx.actions["errors"] += 1
        return json.dumps({
            "ok": False,
            "error_class": exc.__class__.__name__,
            "message": str(exc)[:500],
        })
    ctx.actions["detected_sent"] += 1
    return json.dumps({"ok": True})


def _tool_mark_shipped(
    ctx: AgentContext, *, thread_id: str, ups_tracking_no: str,
) -> str:
    try:
        req = S.find_request(ctx.state, thread_id)
        if req is None:
            raise KeyError(f"thread_id not found: {thread_id}")
        S.mark_shipped(ctx.state, thread_id, ups_tracking_no)
        ctx.gmail.relabel(
            req["original_message_id"],
            remove=[LABEL_RELEASED], add=[LABEL_SHIPPED],
        )
    except Exception as exc:                # noqa: BLE001
        ctx.actions["errors"] += 1
        return json.dumps({
            "ok": False,
            "error_class": exc.__class__.__name__,
            "message": str(exc)[:500],
        })
    ctx.actions["shipped"] += 1
    return json.dumps({"ok": True})
```

Extend `build_tools`:

```python
    @beta_tool
    def mark_release_sent(
        thread_id: str, release_message_id: str,
        warehouse_thread_id: str, released_at: str,
    ) -> str:
        """Record that the user has sent the release draft.

        Call this after check_sent_folder finds a matching sent message.
        Transitions state from draft_created to released and moves the
        Gmail label from draft-ready to released.
        released_at: ISO UTC timestamp string.
        """
        return _tool_mark_release_sent(
            ctx, thread_id=thread_id,
            release_message_id=release_message_id,
            warehouse_thread_id=warehouse_thread_id,
            released_at=released_at,
        )

    @beta_tool
    def mark_shipped(thread_id: str, ups_tracking_no: str) -> str:
        """Record that the warehouse has shipped the sample.

        Call this AFTER read_warehouse_thread returns a UPS tracking
        number (format: 1Z + 16 alphanumeric chars). Transitions state
        to shipped and moves the label. Rejects tracking strings that
        don't match the UPS regex.
        """
        return _tool_mark_shipped(
            ctx, thread_id=thread_id, ups_tracking_no=ups_tracking_no,
        )

    return [
        list_pending_emails, list_released_requests, get_state_summary,
        read_warehouse_thread, check_sent_folder,
        parse_email_content, create_release_draft,
        mark_release_sent, mark_shipped,
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

```
.venv/bin/pytest backend/sample_request/tests/test_agent.py -v
```

Expected: 21 passed.

- [ ] **Step 5: Full suite**

```
.venv/bin/pytest -q
```

Expected: 123 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/sample_request/agent.py backend/sample_request/tests/test_agent.py
git commit -m "feat(sample_request): agent tools (mark_release_sent, mark_shipped)"
```

---

### Task 7: Write tools — send_followup_reply, flag_needs_attention, record_failure

**Files:**
- Modify: `backend/sample_request/agent.py`
- Modify: `backend/sample_request/tests/test_agent.py`

**Interfaces:**
- Consumes: `sender.build_followup_email`, `state.record_followup`, `state.append_tick_error`, `LABEL_ATTENTION`
- Produces:
  - `_tool_send_followup_reply(ctx, thread_id, escalation_level) -> str` — sends reply, records in state
  - `_tool_flag_needs_attention(ctx, message_id, reason) -> str` — adds needs-attention label
  - `_tool_record_failure(ctx, thread_id, step, error_message) -> str` — appends tick_error, returns count
  - `build_tools(ctx)` returns 12 tools (final count).

- [ ] **Step 1: Write the failing test**

Append to `test_agent.py`:

```python
from backend.sample_request.agent import (
    _tool_send_followup_reply, _tool_flag_needs_attention,
    _tool_record_failure,
)


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
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv/bin/pytest backend/sample_request/tests/test_agent.py -v
```

Expected: FAIL on missing imports.

- [ ] **Step 3: Implement three impl functions and register them**

Add `from backend.sample_request.sender import build_release_email, build_followup_email` at top (extend existing import).

Add above `build_tools`:

```python
def _tool_send_followup_reply(
    ctx: AgentContext, *, thread_id: str, escalation_level: int,
) -> str:
    try:
        req = S.find_request(ctx.state, thread_id)
        if req is None:
            raise KeyError(f"thread_id not found: {thread_id}")
        warehouse_thread = req.get("warehouse_thread_id")
        if not warehouse_thread:
            raise ValueError(f"no warehouse_thread_id for {thread_id}")
        body = build_followup_email(req, escalation_level)
        reply_id = ctx.gmail.reply_in_thread(warehouse_thread, body)
        S.record_followup(ctx.state, thread_id, message_id=reply_id)
    except Exception as exc:                # noqa: BLE001
        ctx.actions["errors"] += 1
        return json.dumps({
            "ok": False,
            "error_class": exc.__class__.__name__,
            "message": str(exc)[:500],
        })
    ctx.actions["followups"] += 1
    return json.dumps({"ok": True, "reply_message_id": reply_id})


def _tool_flag_needs_attention(
    ctx: AgentContext, *, message_id: str, reason: str,
) -> str:
    try:
        ctx.gmail.relabel(message_id, remove=[], add=[LABEL_ATTENTION])
        ctx.log.warning(
            "needs-attention flagged",
            extra={"message_id": message_id, "reason": reason[:200]},
        )
    except Exception as exc:                # noqa: BLE001
        ctx.actions["errors"] += 1
        return json.dumps({
            "ok": False,
            "error_class": exc.__class__.__name__,
            "message": str(exc)[:500],
        })
    ctx.actions["flagged"] += 1
    return json.dumps({"ok": True})


def _tool_record_failure(
    ctx: AgentContext, *,
    thread_id: str, step: str, error_message: str,
) -> str:
    try:
        n = S.append_tick_error(
            ctx.state, thread_id,
            step=step,
            error_class="AgentReported",
            message=error_message,
        )
    except Exception as exc:                # noqa: BLE001
        return json.dumps({
            "ok": False,
            "error_class": exc.__class__.__name__,
            "message": str(exc)[:500],
        })
    ctx.actions["errors"] += 1
    return json.dumps({"ok": True, "failure_count": n})
```

Extend `build_tools` (append three closures and update return list):

```python
    @beta_tool
    def send_followup_reply(thread_id: str, escalation_level: int) -> str:
        """Send an escalating follow-up reply in the warehouse thread.

        escalation_level: 1 = gentle nudge, 2 = firmer ping,
        3+ = final warning.
        Returns JSON {"ok": true, "reply_message_id": str} or error.
        """
        return _tool_send_followup_reply(
            ctx, thread_id=thread_id, escalation_level=escalation_level,
        )

    @beta_tool
    def flag_needs_attention(message_id: str, reason: str) -> str:
        """Add the needs-attention label to a Gmail message.

        Use this after 3+ consecutive failures on the same request.
        Also useful for messages that are ambiguous or need human review.
        """
        return _tool_flag_needs_attention(
            ctx, message_id=message_id, reason=reason,
        )

    @beta_tool
    def record_failure(
        thread_id: str, step: str, error_message: str,
    ) -> str:
        """Record a failure for a specific request; returns the cumulative count.

        Call this whenever a tool returns ok=false so failure counts
        persist across ticks. When failure_count reaches 3, follow up
        with flag_needs_attention.
        """
        return _tool_record_failure(
            ctx, thread_id=thread_id, step=step, error_message=error_message,
        )

    return [
        list_pending_emails, list_released_requests, get_state_summary,
        read_warehouse_thread, check_sent_folder,
        parse_email_content, create_release_draft,
        mark_release_sent, mark_shipped,
        send_followup_reply, flag_needs_attention, record_failure,
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

```
.venv/bin/pytest backend/sample_request/tests/test_agent.py -v
```

Expected: 25 passed.

- [ ] **Step 5: Full suite**

```
.venv/bin/pytest -q
```

Expected: 127 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/sample_request/agent.py backend/sample_request/tests/test_agent.py
git commit -m "feat(sample_request): agent tools (send_followup_reply, flag_needs_attention, record_failure); tool set complete (12)"
```

---

### Task 8: run_agent_tick orchestrator (tool_runner + state persistence)

**Files:**
- Modify: `backend/sample_request/agent.py`
- Modify: `backend/sample_request/tests/test_agent.py`

**Interfaces:**
- Consumes: `AgentContext`, `build_tools`, `Config`, `state.load_state`, `state.save_state`, `state.update_meta`, `log.setup_logger`, `log.make_tick_id`, `TickResult` from `cli`
- Produces:
  - `run_agent_tick(cfg: Config, *, gmail, ant_client) -> TickResult`
  - Behavior: loads state, builds context, invokes tool_runner, iterates it to completion, catches exceptions (sets `outcome="failed"`), saves state (updates meta with `last_tick_at` / `last_tick_outcome`), returns TickResult populated from `ctx.actions`.

- [ ] **Step 1: Write the failing test**

Append to `test_agent.py`:

```python
from unittest.mock import MagicMock
from pathlib import Path
from backend.sample_request.agent import run_agent_tick
from backend.sample_request.config import Config
from backend.sample_request.cli import TickResult


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
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv/bin/pytest backend/sample_request/tests/test_agent.py -v
```

Expected: FAIL on missing `run_agent_tick`.

- [ ] **Step 3: Implement run_agent_tick**

Add these imports near the top of `agent.py`:

```python
from datetime import datetime, timezone
from backend.sample_request.log import make_tick_id, setup_logger
```

Add `run_agent_tick` at the bottom of `agent.py`:

```python
def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_agent_tick(cfg, *, gmail, ant_client):
    """Run one agent-mode tick.

    Returns a TickResult (same shape as workflow mode's run_tick).
    """
    from backend.sample_request.cli import TickResult      # local: avoid cycle

    tick_id = make_tick_id()
    log = setup_logger(cfg.log_path, tick_id)
    log.info("agent tick start", extra={"step": "agent_tick"})

    state = S.load_state(cfg.state_file)
    ctx = AgentContext(
        gmail=gmail, cfg=cfg, state=state,
        ant_client=ant_client, log=log,
    )
    tools = build_tools(ctx)

    try:
        runner = ant_client.beta.messages.tool_runner(
            model=cfg.po_model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=[{"role": "user", "content": "Run one tick cycle now."}],
        )
        for _ in runner:
            pass
    except Exception:
        log.exception("agent tick failed", extra={"step": "agent_tick"})
        S.update_meta(state, last_tick_at=_iso_now(),
                      last_tick_outcome="failed")
        S.save_state(cfg.state_file, state)
        return TickResult(**ctx.actions, outcome="failed")

    outcome = "ok" if ctx.actions["errors"] == 0 else "partial"
    S.update_meta(state, last_tick_at=_iso_now(),
                  last_tick_outcome=outcome)
    S.save_state(cfg.state_file, state)
    log.info(
        "agent tick complete",
        extra={"step": "agent_tick", "actions": ctx.actions,
               "outcome": outcome},
    )
    return TickResult(**ctx.actions, outcome=outcome)
```

**Note on TickResult:** `cli.TickResult` has fields `ingested, detected_sent, shipped, followups, errors, outcome` — no `flagged`. Since `ctx.actions` has a `flagged` key, `TickResult(**ctx.actions, ...)` will raise. Fix by extending TickResult in `cli.py` to include `flagged: int = 0`:

Edit `backend/sample_request/cli.py`, add `flagged: int = 0` to the `TickResult` class between `followups` and `errors`:

```python
class TickResult(BaseModel):
    ingested: int = 0
    detected_sent: int = 0
    shipped: int = 0
    followups: int = 0
    flagged: int = 0                       # new — used by agent mode
    errors: int = 0
    outcome: str = "ok"
```

Existing workflow-mode code doesn't set `flagged`, so it defaults to 0 — no behavior change.

- [ ] **Step 4: Run tests to verify they pass**

```
.venv/bin/pytest backend/sample_request/tests/test_agent.py -v
```

Expected: 27 passed.

- [ ] **Step 5: Full suite**

```
.venv/bin/pytest -q
```

Expected: 129 passed (all pre-existing tests still pass because `flagged` defaults to 0).

- [ ] **Step 6: Commit**

```bash
git add backend/sample_request/agent.py backend/sample_request/cli.py backend/sample_request/tests/test_agent.py
git commit -m "feat(sample_request): run_agent_tick orchestrator + TickResult.flagged field"
```

---

### Task 9: CLI integration — `--agent` flag on `tick` subcommand

**Files:**
- Modify: `backend/sample_request/cli.py`
- Modify: `backend/sample_request/tests/test_agent.py`

**Interfaces:**
- Consumes: `run_agent_tick` (from Task 8)
- Produces:
  - `tick --agent` runs `run_agent_tick`
  - `tick` (no flag) still runs `run_tick` (unchanged)
  - `--agent` and `--dry-run` are mutually exclusive (agent mode has no dry-run yet)

- [ ] **Step 1: Write the failing test**

Append to `test_agent.py`:

```python
from backend.sample_request.cli import _build_parser


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
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv/bin/pytest backend/sample_request/tests/test_agent.py -v
```

Expected: FAIL because `--agent` doesn't exist yet.

- [ ] **Step 3: Add `--agent` flag and branch in _cmd_tick**

Edit `backend/sample_request/cli.py`. Update `_build_parser` `tick` subparser section:

```python
    sp = sub.add_parser("tick", help="Run one tick cycle")
    grp = sp.add_mutually_exclusive_group()
    grp.add_argument("--dry-run", action="store_true")
    grp.add_argument(
        "--agent", action="store_true",
        help="Run in tool-using agent mode instead of the hardcoded workflow",
    )
    sp.set_defaults(func=_cmd_tick)
```

Update `_cmd_tick` to branch on `args.agent`:

```python
def _cmd_tick(args: argparse.Namespace) -> int:
    cfg = load_config()
    from backend.sample_request.gmail_client import GmailClient

    gmail = GmailClient(cfg.token_path, cfg.credentials_path)

    import anthropic
    ant = anthropic.Anthropic(api_key=cfg.anthropic_api_key)

    if args.agent:
        from backend.sample_request.agent import run_agent_tick
        result = run_agent_tick(cfg, gmail=gmail, ant_client=ant)
    else:
        def parser_fn(body: str, subject: str) -> ParsedRequest:
            return parse_request_body(body, subject, client=ant, model=cfg.po_model)

        result = run_tick(cfg, gmail=gmail, parser_fn=parser_fn, dry_run=args.dry_run)

    return 0 if result.outcome != "failed" else 1
```

- [ ] **Step 4: Run tests to verify they pass**

```
.venv/bin/pytest backend/sample_request/tests/test_agent.py -v
```

Expected: 30 passed.

- [ ] **Step 5: Full suite**

```
.venv/bin/pytest -q
```

Expected: 132 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/sample_request/cli.py backend/sample_request/tests/test_agent.py
git commit -m "feat(sample_request): --agent flag on tick subcommand"
```

---

### Task 10: End-to-end tests (3 scenarios with driven mock ant_client)

**Files:**
- Modify: `backend/sample_request/tests/test_agent.py`

**Interfaces:**
- Consumes: `run_agent_tick`, `AgentContext`, `build_tools`
- Produces: 3 end-to-end tests that drive `run_agent_tick` by mocking `ant_client.beta.messages.tool_runner()` to invoke selected tools in order, verifying real side effects on `FakeGmailClient` and state.

**Design note:** we can't easily fake the internal loop of `tool_runner`. Instead, we test at the *tool-composition* level: mock `tool_runner` to return an iterator that, when iterated, invokes the desired tool functions directly with the same `ctx`. This tests that `run_agent_tick` correctly wires state + gmail + counters, without depending on Claude's inference.

Concretely: our mock intercepts the `tools=[...]` kwarg on `tool_runner()`, extracts individual tools by name, and calls them with test-authored args to simulate what Claude would do.

- [ ] **Step 1: Write the failing tests**

Append to `test_agent.py`:

```python
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
        pending = json.loads(tools["list_pending_emails"].run())
        assert len(pending) == 1
        entry = pending[0]
        parse_result = json.loads(tools["parse_email_content"].run(
            subject=entry["subject"], body=entry["body_excerpt"],
        ))
        assert parse_result["ok"] is True
        draft_result = json.loads(tools["create_release_draft"].run(
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
        released = json.loads(tools["list_released_requests"].run())
        assert len(released) == 1
        thread_id = released[0]["thread_id"]
        wt = released[0]["warehouse_thread_id"]
        thread = json.loads(tools["read_warehouse_thread"].run(thread_id=wt))
        # Extract tracking (Claude would do this via regex/reasoning)
        import re
        matches = [re.search(r"1Z[0-9A-Z]{16}", m["body_excerpt"])
                   for m in thread]
        tracking = next((m.group(0) for m in matches if m), None)
        assert tracking == "1ZA123456789012345"
        result = json.loads(tools["mark_shipped"].run(
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
        released = json.loads(tools["list_released_requests"].run())
        result = json.loads(tools["send_followup_reply"].run(
            thread_id=released[0]["thread_id"], escalation_level=1,
        ))
        assert result["ok"] is True

    ant.beta.messages.tool_runner.side_effect = _make_scripted_runner([step1])
    result = run_agent_tick(cfg, gmail=gmail, ant_client=ant)

    assert result.followups == 1
    saved = json.loads(cfg.state_file.read_text())
    assert len(saved["requests"][0]["follow_ups"]) == 1
```

**Note on `tools["list_pending_emails"].run(...)`:** The `@beta_tool` decorator exposes the underlying callable via `.run()` or by calling the wrapper directly with kwargs. If `.run()` doesn't exist on this SDK version, the implementer should change the test to invoke the wrapped function via its `__call__` (e.g. `tools["list_pending_emails"]()`), or via `tools["list_pending_emails"].__wrapped__(...)` if the decorator preserves `__wrapped__`. **Verify during Step 2 which invocation the SDK exposes** and adjust the calls in `_make_scripted_runner`'s script accordingly.

- [ ] **Step 2: Run tests to verify they fail — and discover the correct invocation pattern**

```
.venv/bin/pytest backend/sample_request/tests/test_agent.py -v
```

Expected: FAIL. Inspect the error message to see how `@beta_tool` exposes the raw callable. Adjust `step1` in each test to use the correct pattern. **Alternative fallback**: call `_tool_list_pending_emails(ctx)` etc. directly, bypassing the wrapped tools — this is fine because the test's goal is verifying end-to-end flow, not the tool-runner integration itself (that's covered by Task 8).

If the `.run()` / direct-call approaches don't work, replace `_make_scripted_runner` with a version that captures `ctx` directly. Add this helper factory that patches `build_tools` for the test's duration:

```python
def _run_agent_tick_with_script(cfg, gmail, ant_client, script):
    """Alternate: call impl functions directly with the tick's ctx."""
    ctx_holder = {}
    original_build = build_tools

    def build_and_capture(ctx):
        ctx_holder["ctx"] = ctx
        return original_build(ctx)

    def _factory(**kwargs):
        for step in script:
            step(ctx_holder["ctx"])
        return iter([])

    ant_client.beta.messages.tool_runner.side_effect = _factory
    with patch("backend.sample_request.agent.build_tools",
               side_effect=build_and_capture):
        return run_agent_tick(cfg, gmail=gmail, ant_client=ant_client)
```

Then each step calls impl functions directly with `ctx`:

```python
def step1(ctx):
    pending = json.loads(_tool_list_pending_emails(ctx))
    ...
```

**Pick whichever approach the SDK cleanly supports.** Both prove the flow works.

- [ ] **Step 3: Fix invocation pattern in the 3 E2E tests as needed**

Iterate on Step 2 until the pattern works. Re-run:

```
.venv/bin/pytest backend/sample_request/tests/test_agent.py -v
```

- [ ] **Step 4: Verify tests pass**

Expected: 33 passed.

- [ ] **Step 5: Full suite**

```
.venv/bin/pytest -q
```

Expected: 135 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/sample_request/tests/test_agent.py
git commit -m "test(sample_request): agent E2E scenarios (ingest, ship-detection, followup)"
```

---

### Task 11: Documentation + final verification

**Files:**
- Modify: `backend/sample_request/README.md`
- Create: `backend/sample_request/AGENT.md`

**Interfaces:** none (docs only)

- [ ] **Step 1: Update README.md with agent-mode section**

Open `backend/sample_request/README.md` (read first if unfamiliar with existing structure) and add a new section near the existing "Usage" or "CLI" area:

```markdown
## Execution Modes: Workflow vs Agent

The `tick` subcommand supports two execution modes:

### Workflow mode (default)

```
.venv/bin/python3 -m backend.sample_request tick
```

Runs the hardcoded 4-step pipeline: ingest → detect_sent → check_shipments →
send_followups. Deterministic, cheap (~$0.005/tick — one Claude call for
parsing), fast. Use this for production cron.

### Agent mode (`--agent`)

```
.venv/bin/python3 -m backend.sample_request tick --agent
```

Runs Claude as a tool-using agent with 12 fine-grained tools. Claude decides
which tools to call in what order each tick. Non-deterministic, more
expensive (~$0.10–0.30/tick), slower. Use this to demo agentic behavior
or when you want the flexibility of "Claude figures out what to do".

See `AGENT.md` for the tool inventory, system prompt, and trade-offs.
```

- [ ] **Step 2: Create AGENT.md**

Create `backend/sample_request/AGENT.md`:

```markdown
# Sample-Request Agent Mode

The agent layer wraps the workflow primitives as Anthropic tools and lets
Claude drive the loop. Alternative to the hardcoded `run_tick` pipeline.

## Architecture

```
┌─────────────────────────────────────────────┐
│  cli.py --agent flag                        │
│         │                                   │
│         ▼                                   │
│  agent.run_agent_tick(cfg, gmail, ant)      │
│         │                                   │
│         ├─ load state                       │
│         ├─ AgentContext(gmail, cfg, state)  │
│         ├─ build_tools(ctx) → 12 @beta_tool │
│         │                                   │
│         ▼                                   │
│  ant.beta.messages.tool_runner(             │
│    model, system=SYSTEM_PROMPT,             │
│    tools=[12 tools],                        │
│    messages=[{"role":"user",                │
│              "content":"Run one tick..."}]  │
│  )                                          │
│         │                                   │
│         ▼                                   │
│  Claude decides each turn:                  │
│    "call list_pending_emails" → result      │
│    "call parse_email_content(...)" → result │
│    "call create_release_draft(...)" → done  │
│    ... (repeat) ...                         │
│         │                                   │
│         ▼                                   │
│  save state + TickResult                    │
└─────────────────────────────────────────────┘
```

## The 12 tools

### Read (5)
| Tool | Purpose |
|---|---|
| `list_pending_emails` | Emails labeled `sample-request/pending-release` awaiting drafts |
| `list_released_requests` | Requests in state with status=released (awaiting warehouse reply) |
| `get_state_summary` | High-level state summary (counts by status) |
| `read_warehouse_thread` | All messages in a warehouse thread (find UPS numbers) |
| `check_sent_folder` | Detect drafts the user has manually sent |

### Parse (1)
| Tool | Purpose |
|---|---|
| `parse_email_content` | Extract recipient/address/items from an email body (nested Claude call) |

### Write (6)
| Tool | Purpose |
|---|---|
| `create_release_draft` | Create warehouse draft + register in state + transition label |
| `mark_release_sent` | draft_created → released transition |
| `mark_shipped` | released → shipped transition (validates UPS regex) |
| `send_followup_reply` | Send escalating follow-up in warehouse thread |
| `flag_needs_attention` | Add `needs-attention` label after 3+ failures |
| `record_failure` | Persist a failure count for a request |

## System prompt

See `SYSTEM_PROMPT` in `agent.py`. Summary of guidance:
- Guideline workflow (Claude may deviate): ingest → detect_sent → check_shipments → send_followups.
- Escalation rule: 3 consecutive failures → `flag_needs_attention`.
- Constraints: never reply directly to customers; never `mark_shipped` without verifying UPS number; don't re-parse emails already in state.
- Return a JSON summary at end of turn.

## Trade-offs

| Dimension | Workflow | Agent |
|---|---|---|
| Cost per tick | ~$0.005 | ~$0.10–0.30 |
| Latency per tick | ~2 sec | ~30–120 sec |
| Determinism | High | Medium (LLM may pick different tool order) |
| Debuggability | Easy (Python stack) | Harder (need to trace reasoning) |
| Extensibility | New feature = new code | New feature = new tool + one prompt line |
| Resume signal | "email automation" | "**LLM agent** with 12 tools" ⭐ |

## Cost warning

Do NOT run agent mode on the current cron schedule (`*/2` = every 2 min)
without reducing frequency first — it would cost roughly $70–$300/day.
For production, set cron to `0 */2 * * *` (every 2 hours) or less
frequent, and consider gating the agent mode behind manual runs only.
```

- [ ] **Step 3: Full test suite one last time**

```
.venv/bin/pytest -q
```

Expected: 135 passed, 1 pre-existing warning (fastapi/httpx, not this branch).

- [ ] **Step 4: Verify agent.py imports cleanly and tools list is 12**

```
.venv/bin/python3 -c "
from backend.sample_request.agent import build_tools, AgentContext, SYSTEM_PROMPT
from backend.sample_request.tests.fake_gmail import FakeGmailClient
from backend.sample_request import state as S

class _C:
    warehouse_email = 'w@e'
    po_model = 'claude-opus-4-8'

ctx = AgentContext(gmail=FakeGmailClient(), cfg=_C(), state=S._empty_state())
tools = build_tools(ctx)
print(f'{len(tools)} tools registered')
for t in tools:
    print(f'  - {t.name}')
print('SYSTEM_PROMPT length:', len(SYSTEM_PROMPT))
"
```

Expected: prints `12 tools registered` followed by all 12 tool names.

- [ ] **Step 5: Verify CLI parser rejects `--agent --dry-run` and accepts `--agent`**

```
.venv/bin/python3 -m backend.sample_request tick --help
.venv/bin/python3 -m backend.sample_request tick --agent --dry-run 2>&1 | grep -i "not allowed"
```

Expected: first prints usage showing both `--dry-run` and `--agent` in a mutually exclusive group. Second prints an "argument --agent: not allowed with argument --dry-run" error.

- [ ] **Step 6: Commit**

```bash
git add backend/sample_request/README.md backend/sample_request/AGENT.md
git commit -m "docs(sample_request): agent mode README section + AGENT.md tool inventory"
```
