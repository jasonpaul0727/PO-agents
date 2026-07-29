# Sample Request Gmail-API Integration — Design Spec

**Date:** 2026-06-29
**Author:** yanxiabu001@gmail.com (via Claude Code brainstorming)
**Status:** Draft, pending user review

---

## 1. Background & Goal

### Background

`scripts/sample_followup_tick.py` is a planner-only script: it reads/writes
`.sample_requests_state.json` but intentionally does **not** talk to Gmail. The
Gmail half (ingesting new sample-request emails, generating release messages,
sending follow-ups, detecting shipment) currently runs inside a Claude Code
session with Zapier-MCP attached. That means automation is only possible while
a Claude session is live — there is no way to schedule it to "just run" on the
user's machine.

### Goal

Replace the Claude-session-based executor with a pure-Python module that talks
to Gmail directly via the Gmail API (OAuth desktop client). Driven by `cron`
every 2 hours, with no LLM in the orchestration loop (Claude is only used as
a parser of free-form email bodies, via the existing `anthropic` SDK).

### Non-goals

- Web UI for sample request status (out of scope; see Future Work)
- Multi-warehouse routing (one fixed warehouse for MVP)
- Item validation against `backend/seed/items.json` (out of scope; items.json
  currently lacks human-readable names anyway)
- Notifying the customer (original sample-request sender) on shipment
- Service Account / Google Workspace deployment (personal @gmail.com only)
- CI configuration (project has no GitHub Actions today)

---

## 2. Architecture Overview

The system is an externally-triggered, stateless tick. Cron invokes
`python3 -m backend.sample_request tick` every 2 hours. A tick runs all
work for the current cycle in one process, then exits. State is fully
externalised in three places:

- **Gmail labels** — authoritative state machine for "what stage is this
  request in"
- **`.sample_requests_state.json`** — metadata cache (thread IDs, parsed
  fields, follow-up history)
- **`secrets/token.json`** — OAuth refresh token

```
┌─────────┐    cron      ┌─────────────────────────────┐
│  cron   │──── tick ───>│  backend/sample_request/cli │
└─────────┘              └────────────┬────────────────┘
                                      │
              ┌──────────────────┬────┴────┬─────────────────┐
              ▼                  ▼         ▼                 ▼
        ┌──────────┐      ┌──────────┐ ┌────────┐    ┌────────────┐
        │ gmail_   │      │ parser   │ │ sender │    │ state /    │
        │ client   │      │ (Claude) │ │ (Gmail)│    │ config     │
        └────┬─────┘      └──────────┘ └────┬───┘    └──────┬─────┘
             │                              │                │
             ▼                              ▼                ▼
        ┌─────────────┐               ┌──────────┐    ┌──────────────────┐
        │ Gmail API   │               │ Gmail API│    │ .sample_requests │
        │ (read/label)│               │ (write)  │    │  _state.json     │
        └─────────────┘               └──────────┘    └──────────────────┘
```

### Tick lifecycle (sequential inside one process)

1. **ingest** — read Gmail label `sample-request/pending-release` → Claude
   parse → write state (status=`draft_created`) → create Gmail draft →
   relabel to `sample-request/draft-ready`
2. **detect_sent** — for each request in state with `status=draft_created`,
   scan sent emails to detect if the draft has been sent by the user; on hit,
   transition to `released` and relabel `draft-ready` → `released`
3. **check_shipments** — for each `released` request, scan its warehouse
   thread for the UPS regex (`\b1Z[0-9A-Z]{16}\b`); on hit, `mark_shipped`
   and relabel to `sample-request/shipped`
4. **send_followups** — for each `released` request whose last contact is
   older than the threshold (default 4 h), reply on the warehouse thread and
   `record_followup`
5. Write final tick summary log entry and exit

### Key design decisions

- **No background process, no message queue, no webhook.** Cron is the only
  time trigger. All state external. The script can crash and restart safely
  — idempotency comes from state-file deduplication and Gmail label state.
- **Gmail labels are the source of truth.** `state.json` is a cache of
  metadata; even if it is deleted, replay will not double-send because label
  transitions decide what is processed.
- **Hybrid send mode.** First release email is created as a Gmail *draft*
  (human reviews before sending). Follow-up reminders are auto-sent.
- **OAuth secrets stay local** under `secrets/` (gitignored).

---

## 3. Components

### Directory layout

```
backend/sample_request/
├── __init__.py
├── cli.py               # argparse entry (~120 LOC)
├── auth.py              # standalone OAuth setup runner (~60 LOC)
├── gmail_client.py      # Gmail API thin wrapper (~180 LOC)
├── parser.py            # Claude structured parsing (~80 LOC)
├── sender.py            # release draft + follow-up reply builders (~100 LOC)
├── state.py             # migrated from sample_followup_tick.py + extensions (~140 LOC)
├── config.py            # .env loading + validation (~50 LOC)
├── log.py               # JSON logging setup (~30 LOC)
└── tests/               # pytest suite (see §5)

backend/sample_request/README.md   # one-time setup checklist
```

### Public CLI

```
python3 -m backend.sample_request tick           # cron entry
python3 -m backend.sample_request tick --dry-run # no writes, log "would do X"
python3 -m backend.sample_request status         # pretty-print state.json
python3 -m backend.sample_request init           # create empty state.json
python3 -m backend.sample_request init --force   # overwrite existing
python3 -m backend.sample_request.auth           # one-time OAuth flow
```

### Module APIs

**`gmail_client.GmailClient`**

```python
class GmailClient:
    def __init__(self, token_path: Path, credentials_path: Path)

    # Reads
    def fetch_pending(self) -> list[GmailMessage]
        # messages with label sample-request/pending-release
    def fetch_sent_to(self, to: str, subject_prefix: str) -> list[GmailMessage]
        # newer_than:1d, used by detect_sent
    def fetch_thread(self, thread_id: str) -> list[GmailMessage]

    # Writes
    def create_draft(
        self,
        to: str,
        subject: str,
        body: str,
        in_reply_to: str | None = None,
    ) -> str                                       # returns draft_id
    def reply_in_thread(self, thread_id: str, body: str) -> str   # returns message_id

    # Labels
    def relabel(self, message_id: str, remove: list[str], add: list[str]) -> None
    def ensure_labels(self, names: list[str]) -> dict[str, str]   # name → label_id
```

**`parser`**

```python
class ParsedItem(pydantic.BaseModel):
    name: str
    qty: int
    qty_unit: str = "each"
    item_number: str | None = None

class ParsedRequest(pydantic.BaseModel):
    recipient: str
    address: str
    items: list[ParsedItem]

def parse_request_body(body: str, subject: str) -> ParsedRequest
    # calls anthropic SDK messages.parse with PO_MODEL
    # raises ParserError on schema validation failure or refusal
```

**`sender`**

```python
def build_release_email(
    parsed: ParsedRequest,
    original_subject: str,
    original_sender: str,
) -> tuple[str, str]
    # returns (subject, body)
    # subject format: "Release Request: <original_subject> - <recipient>"

def build_followup_email(req: dict, n_th: int) -> str
    # body only (reply auto-inherits subject)
    # n_th picks from 3 increasing-urgency templates
```

**`state`** — load_state / save_state / find_request / mark_shipped /
record_followup migrated from existing script, plus:

```python
def add_request(
    state: dict,
    *,
    thread_id: str,
    message_id: str,
    subject: str,
    from_: str,
    received_at: str,
    parsed: ParsedRequest,
) -> dict                                          # returns the new request dict

def mark_draft_created(
    state: dict,
    thread_id: str,
    draft_id: str,
    draft_created_at: str | None = None,
) -> None

def mark_released(
    state: dict,
    thread_id: str,
    release_message_id: str,
    warehouse_thread_id: str,
    released_at: str,
) -> None

def append_tick_error(
    state: dict,
    thread_id: str,
    *,
    step: str,
    error_class: str,
    message: str,
    raw_excerpt: str | None = None,
) -> int                                           # returns new failure count
```

**`config`**

```python
class Config(pydantic.BaseModel):
    warehouse_email: str
    followup_threshold_hours: float = 4.0
    state_file: Path = Path(".sample_requests_state.json")
    token_path: Path = Path("secrets/token.json")
    credentials_path: Path = Path("secrets/credentials.json")
    log_path: Path = Path("logs/sample_request_tick.log")
    anthropic_api_key: str
    po_model: str = "claude-opus-4-8"

def load_config() -> Config       # raises ValueError listing missing env vars
```

### Dependency additions

To `requirements.txt`:

```
google-api-python-client>=2.140
google-auth>=2.34
google-auth-oauthlib>=1.2
google-auth-httplib2>=0.2
```

`anthropic`, `pydantic`, `python-dotenv` already present.

### Relationship to existing code

- `scripts/sample_followup_tick.py` is reduced to a 5-line shim that
  delegates to `backend.sample_request.cli.main` to preserve any existing
  cron entry or muscle memory. The four legacy subcommands
  (`plan` / `mark-shipped` / `record-followup` / `init`) continue to work
  unchanged via this delegation. New subcommands (`tick`, `status`) live
  only on the new CLI.
- Existing `.sample_requests_state.json` path is unchanged. Schema is
  backward-compatible: new code only *adds* fields, never changes or
  removes existing ones. On first read of an old file, schema_version is
  upgraded to 2 transparently.

---

## 4. Data Flow & State Machine

### Request lifecycle

```
                      cron tick 1                 cron tick N
                     ┌──────────┐               ┌──────────┐
   ┌─────────┐      │ ingest   │   ┌─────────┐ │ detect_  │   ┌──────────┐
   │ pending-│ ───> │ + draft  │──>│ draft-  │>│ sent     │──>│ released │
   │ release │      │  create  │   │ ready   │ │          │   │          │
   └─────────┘      └──────────┘   └─────────┘ └──────────┘   └────┬─────┘
   Gmail label      (Claude parse)  Gmail label  (Gmail sent  Gmail label │
   (Gmail filter                    (user reviews scan)                   │
    sets it)                         + Send)                              │
                                                                          │
                                       ┌──────────────────────────────────┤
                                       │                                  │
                                       ▼                                  ▼
                                  ┌─────────┐ check_shipments  ┌──────────────┐
                                  │ shipped │<───────────────  │ followup_sent│
                                  └─────────┘  (UPS regex)     │ (one or more)│
                                                                └──────┬───────┘
                                                                       │
                                                       send_followups  │
                                                       every 4 h until │
                                                       shipped         ▼
                                                                  (loop)
```

### Gmail label vocabulary

| Label | Who sets it | Meaning |
|---|---|---|
| `sample-request/pending-release` | Gmail filter (user creates: `subject:"sample request"` → label) | Awaiting first processing |
| `sample-request/draft-ready` | `ingest` step | Draft created in user's Drafts folder |
| `sample-request/released` | `detect_sent` step | Draft was sent; tracking shipment |
| `sample-request/shipped` | `check_shipments` step | UPS number captured; terminal |
| `sample-request/needs-attention` | error-handling, after 3 consecutive request-level failures | Human intervention required |

`auth.py` calls `ensure_labels` to create the four operational labels on
first run (Gmail label creation is idempotent). The Gmail *filter* must be
created manually by the user in Gmail web UI — documented in
`backend/sample_request/README.md` with screenshots.

### `.sample_requests_state.json` schema (v2)

Backward compatible: only adds fields. The `meta` block is new; the existing
`requests[]` records gain new optional fields.

```jsonc
{
  "meta": {
    "schema_version": 2,
    "last_tick_at": "2026-06-29T22:00:01Z",
    "last_tick_outcome": "ok"      // ok / partial / failed
  },
  "requests": [
    {
      // Existing fields (unchanged)
      "thread_id": "19f12ab1bad74fbb",
      "original_message_id": "19f12abef4371d45",
      "subject": "Sample request to Polar",
      "from": "yanxiabu001@gmail.com",
      "received_at": "2026-06-29T09:18:05Z",
      "parsed": { "recipient": "...", "address": "...", "items": [...] },
      "warehouse_thread_id": "19f12ae804a6234d",
      "release_message_id": "19f12ae804a6234d",
      "released_at": "2026-06-29T09:21:17Z",
      "follow_ups": [],
      "ups_tracking_no": null,
      "shipped_at": null,
      "status": "released",

      // New fields (all optional in old files)
      "draft_id": "r-1234567890",
      "draft_created_at": "2026-06-29T09:20:14Z",
      "detect_sent_at": "2026-06-29T09:21:17Z",
      "tick_errors": []
    }
  ]
}
```

### `status` field values

| status | Set by | Cleared by |
|---|---|---|
| `draft_created` | `ingest` after `create_draft` succeeds | `detect_sent` on hit |
| `released` | `detect_sent` on hit | `check_shipments` on hit |
| `shipped` | `check_shipments` on UPS hit | (terminal) |

`released` → `shipped` may include 0..N `follow_ups[]` appends, but `status`
does not change during that loop.

### Worked example (end-to-end)

- **T+0** — sample-request email arrives; Gmail filter sets
  `sample-request/pending-release`
- **T+45m** — cron tick:
  - `ingest`: parser returns `{recipient, address, items}`; `create_draft`
    to warehouse; relabel pending→draft-ready; state gets
    `status=draft_created` row
- **T+47m** — user opens Drafts, reviews, clicks Send
- **T+2h45m** — cron tick:
  - `detect_sent`: finds matching sent email; status→released; relabel
    draft-ready→released; warehouse_thread_id + release_message_id captured
- **T+8h** — cron tick:
  - `check_shipments`: no UPS hit
  - `send_followups`: 5h+ since last contact; reply; record_followup
- **T+15h** — warehouse replies with `Tracking: 1ZA1234567890123456`
- **T+15h05m** — cron tick:
  - `check_shipments`: UPS regex hit; `mark_shipped`; relabel released→shipped
  - Terminal; future ticks skip this request

### Idempotency & failure recovery

- Each step is **read → act → label → state**: label change precedes state
  write so that if the process crashes between them, the next tick sees the
  label change and will not re-do the action.
- Before creating a draft, `ingest` checks state for an existing request
  with the same `original_message_id`; if present, skip. This guards
  against label corruption (e.g., user manually moves a request back to
  `pending-release`).
- Follow-up reply is followed by a 2-second sleep before `record_followup`,
  giving Gmail backend time to make the new message queryable.

---

## 5. Error Handling

### Error severity

| Tier | Trigger | Behaviour |
|---|---|---|
| **FATAL** (tick exits 1) | OAuth refresh fails, credentials missing, config missing, state file corrupt, Gmail label write fails after retries | Log + stderr summary + exit 1 (cron mails the user on most systems) |
| **REQUEST_ERROR** (single request skipped) | Claude parse fails, `create_draft` fails after retries, Gmail 4xx other than 429 | Append to `tick_errors[]`, do not change label, retry next tick. After 3 consecutive failures: add `sample-request/needs-attention` label, log WARN |
| **TRANSIENT** (auto retry) | Gmail 429 / 500 / 502 / 503 / 504, network timeout | Exponential backoff: 1 s → 4 s → 16 s (3 attempts, ~21 s total). Then downgrade to REQUEST_ERROR |

### Step-level behaviour

| Step | Failure mode | Action |
|---|---|---|
| `fetch_pending` | API 429 | TRANSIENT; if exhausted, FATAL (we can't even list inbox) |
| `parse_request_body` | Schema validation / Claude API error / refusal | REQUEST_ERROR scoped to the message; log raw body excerpt (≤500 chars) |
| `create_draft` | 5xx | TRANSIENT; then REQUEST_ERROR. **Label not touched** so next tick retries |
| `relabel` | 5xx | TRANSIENT; then FATAL (label state machine integrity) |
| `save_state` | Disk IO | FATAL (label changed but state not saved → must be resolved manually) |
| `detect_sent` no hit | Not an error (user may not have clicked Send) | Silently skip, retry next tick |
| `check_shipments` no UPS | Not an error | Silently skip, retry next tick |
| `send_followups` reply fails | TRANSIENT; then REQUEST_ERROR | `last_contact_at` not updated → retried next tick |

### `tick_errors[]` structure

Each request keeps a bounded history (≤10 entries, FIFO eviction):

```json
"tick_errors": [
  {
    "at": "2026-06-29T22:14:01Z",
    "step": "parser",
    "error_class": "ValidationError",
    "message": "items[0].qty missing",
    "raw_excerpt": "Please send a sample of Polar Snack..."
  }
]
```

3 consecutive failures on the same request → `needs-attention` label is
added; `status` is left unchanged so the semantic meaning is preserved.

### Structured JSON logging

One JSON object per line, written to `logs/sample_request_tick.log`.
Rotated by `RotatingFileHandler` at 10 MB, keep 5 files.

```json
{"ts":"2026-06-29T22:14:01Z","level":"INFO","tick_id":"f3a2c1","step":"ingest","msg":"draft created","thread_id":"19f...","draft_id":"r-..."}
{"ts":"...","level":"WARN","tick_id":"f3a2c1","step":"send_followups","msg":"transient retry","attempt":2,"error":"503"}
{"ts":"...","level":"ERROR","tick_id":"f3a2c1","step":"parser","msg":"parse failed","thread_id":"19f...","error_class":"ValidationError"}
{"ts":"...","level":"INFO","tick_id":"f3a2c1","step":"tick","msg":"tick complete","stats":{"ingested":2,"detected_sent":1,"shipped":0,"followups":1,"errors":0}}
```

`tick_id` is an 8-char hex random ID per tick, for grep-ability.

### Dry-run mode (`--dry-run`)

- All Gmail write operations (`create_draft`, `relabel`, `reply_in_thread`)
  become no-ops that log `INFO "would do X"`
- `save_state` writes to `.sample_requests_state.json.dryrun.<ts>` instead
  of the canonical file
- Claude is still called (parsing is read-only and exercising it is
  exactly what we want to verify)
- Exit code identical to normal tick

`README.md` directs the user to run `tick --dry-run` immediately after
OAuth setup, verify the produced `.dryrun.*` file and log entries, then
run the real tick.

### Alerting

- Cron mails stderr to the local user (default). WSL typically has no
  `mailx` configured, so the user inspects the log file directly.
- Events worth attention: tick exit code 1, appearance of
  `sample-request/needs-attention` label, or any request whose
  `tick_errors` count is ≥3.
- No built-in Slack / SMTP alert sink. Can be added later (~50 LOC) if
  needed.

---

## 6. Testing Strategy

### Three layers

```
┌──────────────────────────────────────────────────────┐
│  Unit (~70%)                                         │
│  parser / state / sender / config — pure functions   │
├──────────────────────────────────────────────────────┤
│  Integration (~25%)                                  │
│  cli.tick end-to-end with FakeGmailClient + stubbed  │
│  Claude responses                                    │
├──────────────────────────────────────────────────────┤
│  Smoke (~5%) — manual, not in CI                     │
│  --dry-run on real Gmail; user inspects log + dryrun │
│  state file                                          │
└──────────────────────────────────────────────────────┘
```

### Unit tests

- **`test_state.py`** — load/save round-trip; `add_request` idempotency;
  `mark_shipped` UPS regex validation; `follow_ups` append ordering;
  schema_version upgrade path (old file readable by new code)
- **`test_parser.py`** — mock anthropic SDK; verify `ParsedRequest`
  mapping; missing field raises `ValidationError`; refusal raises distinct
  exception class
- **`test_sender.py`** — `build_release_email` snapshot test on fixed
  input; `build_followup_email` produces distinct text for n=1/2/3
- **`test_config.py`** — missing env vars produce clear errors (listing
  which); defaults applied correctly; Path fields normalised to absolute

### Integration tests

`backend/sample_request/tests/fake_gmail.py` implements the same surface
as `GmailClient` against in-memory dicts:

```python
class FakeGmailClient:
    def __init__(self):
        self.messages: dict[str, FakeMessage] = {}
        self.threads: dict[str, list[str]] = {}
        self.labels_on: dict[str, set[str]] = {}
        self.drafts_created: list[dict] = []
        self.sent: list[dict] = []
    # implements fetch_pending / create_draft / relabel / reply_in_thread / ...
```

Test scenarios (one test function each):

| Scenario | Expected |
|---|---|
| New email with pending-release label | ingest creates 1 draft, relabel to draft-ready, state row with status=draft_created |
| Same email seen in second tick | no duplicate draft (state dedup) |
| Draft created, user has not sent | detect_sent skips; state unchanged |
| Draft created, user has sent (FakeGmail injects matching sent) | detect_sent hits; status→released |
| Released, warehouse silent 4h+ | send_followups fires; record_followup |
| Warehouse replies with UPS number | check_shipments hits; status→shipped |
| Parser raises ValidationError | tick_errors gets 1 entry; status/label unchanged |
| 3 consecutive parser failures on same request | needs-attention label appears |
| Gmail relabel raises 5xx | TRANSIENT retries 3×; final FATAL, exit 1 |
| `--dry-run` mode | create_draft/reply/relabel are no-ops; writes .dryrun.* state |

### Smoke / acceptance (not in pytest)

Documented as a checklist in `backend/sample_request/README.md`:

1. `python3 -m backend.sample_request.auth` → browser → grant → `secrets/token.json` exists
2. Send self a test email `subject: Sample request — test 1`; verify Gmail filter applies `pending-release`
3. `python3 -m backend.sample_request tick --dry-run` → inspect log + `.sample_requests_state.json.dryrun.*`
4. `python3 -m backend.sample_request tick` → confirm a draft exists in Gmail Drafts
5. Click Send → wait next tick (or trigger manually) → verify state becomes `released`
6. `python3 -m backend.sample_request status` → pretty table is rendered

### CI

Project has no GitHub Actions today; none will be added. Test command for
the user / future CI: `pytest tests/ backend/sample_request/tests/`.

### Out of scope for tests

- Real Gmail API (all tests use FakeGmailClient)
- Real Claude API (all tests use stub responses)
- OAuth flow itself (browser interaction is not testable; classified as manual smoke)
- The 5-line `scripts/sample_followup_tick.py` shim (testing it would
  exceed its code size)

---

## 7. Configuration & Operations

### `.env` additions

Append to existing `.env.example`:

```bash
# ---- sample request module ----
SAMPLE_REQUEST_WAREHOUSE_EMAIL=yanxiabu@usc.edu
SAMPLE_REQUEST_FOLLOWUP_HOURS=4
SAMPLE_REQUEST_STATE_FILE=.sample_requests_state.json
SAMPLE_REQUEST_TOKEN_PATH=secrets/token.json
SAMPLE_REQUEST_CREDS_PATH=secrets/credentials.json
SAMPLE_REQUEST_LOG_PATH=logs/sample_request_tick.log
# anthropic reuses existing ANTHROPIC_API_KEY / PO_MODEL
```

### `.gitignore` additions

```
secrets/
.sample_requests_state.json.dryrun.*
logs/sample_request_tick.log*
```

Verify with `git check-ignore secrets/token.json` after editing.

### Directory bootstrap

```bash
mkdir -p secrets logs backend/sample_request/tests
touch secrets/.gitkeep   # so the empty dir lives in the repo
```

### One-time setup checklist (in `backend/sample_request/README.md`)

1. **Google Cloud Console** — new project (or reuse); enable Gmail API;
   OAuth consent screen → External + add yourself as Test user;
   Credentials → Create OAuth client ID → Desktop app → download JSON →
   rename to `credentials.json` → place in `secrets/`
2. **Run OAuth flow** — `python3 -m backend.sample_request.auth` → browser
   opens → consent → `secrets/token.json` is written
3. **Create Gmail filter** (UI screenshots in README) — Gmail web →
   Search options → `subject:"sample request"` → Create filter → Apply
   label `sample-request/pending-release`
4. **Dry-run verify** — `python3 -m backend.sample_request tick --dry-run`
5. **Install crontab line** — `crontab -e`:

   ```
   # sample request tick — every 2 hours
   0 */2 * * * cd /home/paul2/workspace/po-agents && /usr/bin/python3 -m backend.sample_request tick >> logs/sample_request_cron.log 2>&1
   ```

### Crontab interval

`0 */2 * * *` (every 2 hours). Twelve ticks per day. With a 4-hour
follow-up threshold this granularity is comfortably fine.

### Migration from existing state

The existing `.sample_requests_state.json` contains one record
(`thread_id=19f12ab1bad74fbb`, status `released`, no UPS) that has been
sitting >18 hours without a warehouse reply. If we adopt the new module
as-is, the first real tick will immediately auto-send a follow-up for
that record.

**Decision: as the first step of setup, run `python3 -m backend.sample_request init --force`** to reset the state file. The orphaned legacy record will be cleared
and the new pipeline starts from an empty slate. The README setup
checklist places this step explicitly before any tick run.

### Deployment target

WSL on the user's local machine. **Not** systemd, **not** Docker — cron
is sufficient.

---

## 8. Future Work (explicitly out of scope)

- FastAPI route `/sample-requests` and a card on `home.html` for visual
  status (the ERP launcher style)
- Item validation against an extended `backend/seed/items.json` that
  includes human-readable names
- Multi-warehouse routing driven by item → warehouse mapping
- Customer-side shipment notification (auto-reply to the original
  requester when UPS number is captured)
- Slack / SMTP outbound alerting on FATAL or `needs-attention`
- Migration from cron to systemd timer (for exact 100-min cadence)

---

## 9. Acceptance Criteria

1. `python3 -m backend.sample_request.auth` completes OAuth and writes
   `secrets/token.json`; rerunning is idempotent.
2. After Gmail filter is set up, sending a self-email with
   `Subject: Sample request — smoke 1` results in the
   `sample-request/pending-release` label being applied automatically.
3. `python3 -m backend.sample_request tick --dry-run` produces a
   `.sample_requests_state.json.dryrun.*` file containing a correctly
   parsed `ParsedRequest` for the smoke email, with no Gmail writes.
4. `python3 -m backend.sample_request tick` (live) creates a Gmail draft
   visible in the Drafts folder, transitions the label
   `pending-release` → `draft-ready`, and writes a `status=draft_created`
   row to state.
5. After the user clicks Send on the draft, the next tick transitions
   `status` to `released`, relabels the original email
   `draft-ready` → `released`, and populates `warehouse_thread_id` +
   `release_message_id`.
6. When the warehouse replies with a UPS-format tracking number, the
   next tick captures it via `mark_shipped`, sets `status=shipped`, and
   relabels `released` → `shipped`.
7. With no warehouse reply, after `followup_threshold_hours` has passed
   the next tick auto-sends a follow-up reply and appends a
   `follow_ups[]` entry. Repeats per tick until shipped.
8. Three consecutive request-level failures on the same email result in
   the `needs-attention` label being applied; tick continues processing
   other requests; `status` is preserved.
9. `python3 -m backend.sample_request status` renders a table of current
   requests with `status`, `released_at`, follow-up count, last contact,
   and `tick_errors` count.
10. `pytest tests/ backend/sample_request/tests/` passes.
