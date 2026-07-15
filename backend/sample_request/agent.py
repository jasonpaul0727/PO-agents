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
