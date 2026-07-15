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

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from backend.sample_request import state as S
from backend.sample_request.cli import (
    LABEL_PENDING, LABEL_DRAFT, LABEL_RELEASED, LABEL_SHIPPED, LABEL_ATTENTION,
)
from backend.sample_request.parser import ParsedRequest, parse_request_body
from backend.sample_request.sender import build_release_email


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
        S.mark_shipped(ctx.state, thread_id, ups_tracking_no)
        req = S.find_request(ctx.state, thread_id)
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


def build_tools(ctx: AgentContext) -> list:
    """Build the list of @beta_tool-decorated functions bound to ctx."""
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
