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
