# Sample-Request Multi-Agent Upgrade — Design Spec

- **Date:** 2026-07-23
- **Status:** Approved design, pending implementation plan
- **Scope:** New execution mode alongside the existing single-agent mode (no removal of existing code)

## Goal

The existing `sample_request` agent (`backend/sample_request/agent.py`) is one Claude
agent holding all 12 tools; it decides tool order itself each tick, and self-polices
high-risk actions (shipment confirmation, escalation follow-ups) via instructions in
its own system prompt — there is no independent check before those actions commit.

This upgrade splits that single agent into four cooperating roles and adds an
explicit review gate in front of the two highest-risk actions, closing that gap.
It reuses the existing tool implementations and Anthropic's Tool Runner — no new
framework, no change to Gmail/state semantics.

## Non-goals

- No new capabilities beyond what the current 12 tools already do (no carrier API
  integration, no direct customer/buyer contact — those remain explicitly out of
  scope, per the existing "never reply to the customer" guardrail).
- No removal of the existing single-agent mode. `agent.py` and `run_agent_tick` are
  untouched.
- No migration of existing state-file schema.

## Architecture

```
cli.py tick --agent=multi
        │
        ▼
run_multi_agent_tick(cfg, gmail, ant_client)     [new: multi_agent.py]
        │
        ├─ 1. Planner tool_runner (read-only tools)
        │      → PlannerDecision{run_intake, run_fulfillment, notes}
        │
        ├─ 2. Intake Agent tool_runner   (if run_intake)
        │      tools: list_pending_emails, parse_email_content,
        │              create_release_draft, check_sent_folder,
        │              mark_release_sent, record_failure
        │      → writes state directly (low-risk actions, unchanged from today)
        │
        ├─ 3. Fulfillment Agent tool_runner   (if run_fulfillment)
        │      tools: list_released_requests, read_warehouse_thread,
        │              get_state_summary, record_failure,
        │              send_followup_reply (levels 1-2, executes directly),
        │              propose_mark_shipped (NEW),
        │              propose_send_followup_reply (NEW, level >= 3 only)
        │      → propose_* calls register a Proposal, do not write state
        │
        ├─ 4. QA Agent tool_runner   (only if any proposals were registered)
        │      tools: list_pending_proposals, read_warehouse_thread,
        │              approve_action, reject_action
        │      → independently re-checks evidence (e.g. re-reads the warehouse
        │        thread itself to confirm the UPS tracking number rather than
        │        trusting Fulfillment Agent's claim), then approves or rejects
        │        each proposal
        │
        └─ 5. Orchestrator commit (plain Python, no LLM call)
               → for each approved proposal: call the existing underlying
                 function (_tool_mark_shipped / _tool_send_followup_reply)
               → for each rejected proposal: call flag_needs_attention
               → merge action counters from all roles into one TickResult
```

Four (or fewer — steps 2-4 are conditionally skipped) separate `tool_runner`
invocations per tick, chained by plain Python, not one shared conversation.
Each role gets its own system prompt and its own restricted tool subset.

## Components

**`PlannerDecision`** (pydantic): `{run_intake: bool, run_fulfillment: bool, notes: str}`.
Deliberately coarse — the Planner decides *whether* to run each phase (e.g. skip
Intake entirely when the mailbox has nothing pending, saving an API call), not
*which* specific items to process. Item-level decisions stay with the worker that
already queries them via its own read tools; duplicating that into the plan would
be redundant state to keep in sync.

**`Proposal`** (pydantic): `{id: str, kind: Literal["mark_shipped", "send_followup_reply"], thread_id: str, params: dict, status: Literal["pending","approved","rejected"], reason: str | None}`.
Held in an in-memory `ProposalStore` scoped to a single tick (a plain list passed
by reference into both the Fulfillment and QA contexts) — not persisted into
`state.json`; a proposal that doesn't get resolved within its tick is abandoned
(the underlying request stays in its prior state and will surface again next tick
via `list_released_requests`).

**New tools** (`propose_mark_shipped`, `propose_send_followup_reply`,
`list_pending_proposals`, `approve_action`, `reject_action`) live in
`multi_agent.py`. They wrap the *existing* `_tool_mark_shipped` /
`_tool_send_followup_reply` functions from `agent.py` (imported, not
duplicated) — those functions become the "commit" step the Orchestrator calls
after QA approval, unchanged from their current implementation.

**Why QA gets `read_warehouse_thread`**: if QA could only see the proposal's
self-reported tracking number, it would be rubber-stamping, not reviewing. Giving
it the same read tool Fulfillment used lets it independently pull the thread and
verify the UPS regex match itself before approving.

## Data flow / state changes

- `state.json` schema is unchanged. Multi-agent mode reads/writes the same
  `requests` list as single-agent mode — they are interchangeable on a
  per-tick basis (you could run single-agent mode on Monday and multi-agent
  mode on Tuesday against the same state file).
- The only new runtime data is the tick-scoped `ProposalStore`, which never
  touches disk.

## Error handling

- **Planner call fails** (exception, not a tool error): log it, fall back to a
  safe default of `run_intake=True, run_fulfillment=True` — losing the
  optimization but not losing correctness.
- **Intake or Fulfillment call fails outright**: log it, record an error in that
  role's action counter, continue the tick (the other phase still runs). Same
  behavior as today's single-agent mode on tool-level failures.
- **QA call fails outright**: fail closed. Any proposal still `pending` at the
  end of the tick is *not* auto-approved and *not* silently dropped — the
  Orchestrator calls `flag_needs_attention` on it. A stuck QA call must never
  result in an unreviewed shipment confirmation going through.
- Per-tool error handling within each role (the existing `record_failure` /
  3-strikes-to-`flag_needs_attention` pattern) is unchanged.

## Testing

- Existing tool-level tests (`test_agent.py` and the underlying `_tool_*`
  function tests) are untouched — the commit-time functions they cover didn't
  change.
- New tests in `test_multi_agent.py`:
  - `propose_mark_shipped` registers a `Proposal` and does not mutate state.
  - Orchestrator commits only `approved` proposals and calls
    `flag_needs_attention` for `rejected` ones.
  - **QA rejection blocks the transition**: given a QA agent (faked) that
    rejects a `mark_shipped` proposal, assert the request's status in state is
    unchanged (not `shipped`) and `flag_needs_attention` was called.
  - Planner failure falls back to running both phases.
  - QA failure leaves proposals `pending` and triggers `flag_needs_attention`
    rather than auto-approving.
  - One end-to-end integration test with four faked `tool_runner` turns
    (Planner → Intake → Fulfillment → QA) exercising a full tick.
- Fakes follow the existing pattern in `tests/conftest.py`
  (`FakeGmailClient` + a stubbed `tool_runner` per role).
