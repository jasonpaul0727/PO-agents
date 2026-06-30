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

After setup, verify the end-to-end pipeline by hand:

- [ ] Send yourself an email — **Subject:** `Sample request — smoke 1`,
      **Body:** any recipient + address + items in free-form text.
- [ ] Within a few seconds, confirm the Gmail filter applies the
      `sample-request/pending-release` label.
- [ ] Run `.venv/bin/python3 -m backend.sample_request tick --dry-run`. Check
      the log file and the `.dryrun.*` state sidecar for a sensible
      `ParsedRequest`.
- [ ] Run `.venv/bin/python3 -m backend.sample_request tick` (live). Confirm:
  - A new draft appears in Gmail Drafts addressed to your configured
    warehouse email.
  - The original email's label flips from `pending-release` →
    `draft-ready`.
  - `.venv/bin/python3 -m backend.sample_request status` lists the request as
    `draft_created`.
- [ ] Open the draft in Gmail and click **Send**.
- [ ] Wait for the next cron tick (or run `tick` manually). Confirm:
  - `status` reports `released`.
  - The original email's label flips `draft-ready` → `released`.
- [ ] Reply to the warehouse thread (from the warehouse account or by
      sending yourself a UPS-bearing reply) with a body containing
      `Tracking: 1ZA123456789012345`.
- [ ] Run `tick`. Confirm `status` becomes `shipped`, label flips
      `released` → `shipped`, and `ups_tracking_no` is set.
- [ ] Optionally, leave a `released` request without a UPS reply for
      more than `SAMPLE_REQUEST_FOLLOWUP_HOURS` and confirm the next
      `tick` auto-sends a follow-up reply on the warehouse thread.

## Operational notes

- Logs: `logs/sample_request_tick.log` (10 MB × 5 rotation).
- Errors-to-watch: tick exit code 1, appearance of
  `sample-request/needs-attention` label on any email, or any state row
  whose `tick_errors` count is ≥ 3.
- The state file at `.sample_requests_state.json` is safe to inspect
  but should not be edited by hand while a tick is running.
