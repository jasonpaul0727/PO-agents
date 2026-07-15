# Overnight Autonomous Execution — Plan

**Started:** 2026-07-14
**PM:** Claude Code (Opus 4.7)
**Branch:** `auto/overnight-tasks` (based on `feat/sample-request-gmail-api`)
**Base commit:** b087c3a (fix: WSL-compatible OAuth flow)

---

## Interpretation of Task List (IMPORTANT — please verify on return)

The user's prompt contained a **placeholder task list**:

```
1. [任务一:具体描述 + 验收标准]
2. [任务二:具体描述 + 验收标准]
3. [任务三:具体描述 + 验收标准]
```

Per the "遇到歧义,选择最保守、最符合现有代码风格的方案" principle, I interpreted this as:

> Execute the 11-task implementation plan we just finalized together in this
> session: `docs/superpowers/plans/2026-07-14-sample-request-agent-layer.md`
> — adding a tool-using Claude agent layer to the sample-request module,
> with the `--agent` flag branching to the new orchestrator.

**Rationale:** the entire immediately-preceding conversation was dedicated to
brainstorming, deciding, and writing this plan. The user explicitly picked
"建议 C" (SDD execution with both subagents wired in) and picked "12 fine-grained
tools" + "niuma-yanxia-executor implements, yanxia-niuma-dev reviews".

**If this interpretation is wrong**, all work is isolated on `auto/overnight-tasks`
and can be discarded without touching `master` or `feat/sample-request-gmail-api`.

## Team Mapping

| Prompt role | Actual subagent |
|---|---|
| `backend-developer` | `niuma-yanxia-executor` (opus, project-scoped, red) |
| `qa-reviewer` | `yanxia-niuma-dev` (opus, project-scoped, blue) |

## Execution Schedule

Sequential, one task at a time (SDD pattern). Per task:

1. Dispatch `niuma-yanxia-executor` with self-contained brief (task title +
   files + full steps 1–6 copied from plan file).
2. Wait for implementer to return.
3. Controller-side sanity check: verify commit exists, tests pass.
4. Dispatch `yanxia-niuma-dev` with self-contained review brief (same task,
   plus the diff).
5. On PASS → advance to next task.
6. On FAIL → forward review notes to implementer for a fix pass. Up to 3
   iterations. If still FAIL after 3, mark SKIPPED with rationale, continue.

## Task Sequence

| # | Title | New tests |
|---|---|---|
| 1 | Scaffolding — module skeleton, AgentContext, empty build_tools | 3 |
| 2 | Read tools — list_pending_emails, list_released_requests, get_state_summary | 4 |
| 3 | Read tools — read_warehouse_thread, check_sent_folder | 4 |
| 4 | Parse tool — parse_email_content | 3 |
| 5 | Write tool — create_release_draft | 3 |
| 6 | Write tools — mark_release_sent, mark_shipped | 4 |
| 7 | Write tools — send_followup_reply, flag_needs_attention, record_failure | 4 |
| 8 | run_agent_tick orchestrator (tool_runner + state persistence) | 2 |
| 9 | CLI integration — `--agent` flag on `tick` subcommand | 3 |
| 10 | End-to-end tests (3 scenarios with driven mock ant_client) | 3 |
| 11 | Documentation + final verification | 0 |

Expected end-state: **135 tests passing** (102 baseline + 33 new).

## Guardrails Being Applied

- ✅ Never touch `master`; only `auto/overnight-tasks`.
- ✅ Commits follow **Conventional Commits** (`feat(scope): subject`, body with rationale, `Co-Authored-By` trailer).
- ✅ After every task completes and its tests are green, push the branch:
  `git push -u origin auto/overnight-tasks`. Never `--force`, never push
  to `master`.
- ✅ Never edit `.env` or `secrets/`.
- ✅ Never install new dependencies (anthropic, pydantic, google-\* already in venv).
- ✅ Never access files outside `/home/paul2/workspace/po-agents/`.
- ✅ Never skip pre-commit hooks (none configured).
- ✅ Use `.venv/bin/python3` / `.venv/bin/pytest` for every command (PEP-668).

## Progress Ledger

(Updated as work proceeds; see REPORT.md for final summary.)

| Task | Status | Attempts | Commits | Notes |
|---|---|---|---|---|
| 1  | ⏳ pending | 0 | — | — |
| 2  | ⏳ pending | 0 | — | — |
| 3  | ⏳ pending | 0 | — | — |
| 4  | ⏳ pending | 0 | — | — |
| 5  | ⏳ pending | 0 | — | — |
| 6  | ⏳ pending | 0 | — | — |
| 7  | ⏳ pending | 0 | — | — |
| 8  | ⏳ pending | 0 | — | — |
| 9  | ⏳ pending | 0 | — | — |
| 10 | ⏳ pending | 0 | — | — |
| 11 | ⏳ pending | 0 | — | — |
