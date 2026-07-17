# `backend.sample_request` — Gmail-API sample request automation

Replaces the Claude-session-based executor. Driven by cron every 2 hours.

See the design spec at
`docs/superpowers/specs/2026-06-29-sample-request-gmail-api-design.md`.

## CLI

```
.venv/bin/python3 -m backend.sample_request tick           # cron entry point
.venv/bin/python3 -m backend.sample_request tick --dry-run # no Gmail writes
.venv/bin/python3 -m backend.sample_request status         # readable table of state
.venv/bin/python3 -m backend.sample_request init           # create empty state
.venv/bin/python3 -m backend.sample_request init --force   # overwrite
.venv/bin/python3 -m backend.sample_request.auth           # one-time OAuth setup
```

The shim `scripts/sample_followup_tick.py` delegates to `cli.main`. The
legacy subcommands `plan` / `mark-shipped` / `record-followup` are no longer
exposed — use `tick` / `status` instead.

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

## One-time setup

1. **Google Cloud Console**
   - Create (or reuse) a project; enable the **Gmail API**.
   - **OAuth consent screen** → User Type **External** → add your Gmail
     address as a **Test user**.
   - **Credentials** → **Create OAuth client ID** → **Desktop app** →
     download the JSON.
   - Save the JSON as `secrets/credentials.json` in the repo root.

2. **Run the OAuth flow**

   ```bash
   .venv/bin/python3 -m backend.sample_request.auth
   ```

   - A browser tab opens; sign in and grant access.
   - `secrets/token.json` is created. The five Gmail labels
     `sample-request/{pending-release,draft-ready,released,shipped,needs-attention}`
     are created automatically.

3. **Create the Gmail filter** (Gmail web UI):
   - **Search mail** → click filter icon → **Has the words:**
     `subject:"sample request"`.
   - **Create filter** → tick **Apply the label** → choose
     `sample-request/pending-release` → **Create filter**.

4. **Reset state for the new pipeline** (clears the old Claude-driven row):

   ```bash
   .venv/bin/python3 -m backend.sample_request init --force
   ```

5. **Dry-run verification**

   ```bash
   .venv/bin/python3 -m backend.sample_request tick --dry-run
   ```

   - Inspect `logs/sample_request_tick.log` for the JSON lines.
   - Inspect any `.sample_requests_state.json.dryrun.*` files created in
     the repo root. Confirm parsed `recipient` / `address` / `items` look
     right for any test emails you have queued.

6. **Install the crontab line**

   ```bash
   crontab -e
   ```

   Add (note the absolute venv path — system Python is PEP-668 locked
   and would fail with `externally-managed-environment`):

   ```
   # sample request tick — every 2 hours
   0 */2 * * * cd /home/paul2/workspace/po-agents && /home/paul2/workspace/po-agents/.venv/bin/python3 -m backend.sample_request tick >> logs/sample_request_cron.log 2>&1
   ```

## Manual smoke checklist

See [TESTING.md](TESTING.md) for the full 6-case manual test checklist
(happy path, idempotency, follow-up escalation, bad tracking, dirty input,
agent mode), including recommended execution order and cleanup steps.

## Operational notes

- Logs: `logs/sample_request_tick.log` (10 MB × 5 rotation).
- Errors-to-watch: tick exit code 1, appearance of
  `sample-request/needs-attention` label on any email, or any state row
  whose `tick_errors` count is ≥ 3.
- The state file at `.sample_requests_state.json` is safe to inspect
  but should not be edited by hand while a tick is running.
