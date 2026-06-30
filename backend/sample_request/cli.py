"""Sample-request CLI: tick / status / init.

The `tick` subcommand is the cron entry point. It composes:
  1. ingest          (this task)
  2. detect_sent     (Task 11)
  3. check_shipments (Task 12)
  4. send_followups  (Task 13)
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from pydantic import BaseModel

from backend.sample_request import state as S
from backend.sample_request.config import Config, load_config
from backend.sample_request.log import make_tick_id, setup_logger
from backend.sample_request.parser import ParsedRequest, parse_request_body
from backend.sample_request.sender import build_release_email


LABEL_PENDING = "sample-request/pending-release"
LABEL_DRAFT = "sample-request/draft-ready"
LABEL_RELEASED = "sample-request/released"
LABEL_SHIPPED = "sample-request/shipped"
LABEL_ATTENTION = "sample-request/needs-attention"


class TickResult(BaseModel):
    ingested: int = 0
    detected_sent: int = 0
    shipped: int = 0
    followups: int = 0
    errors: int = 0
    outcome: str = "ok"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- ingest step ----------------------------------------------------------

def _ingest(cfg: Config, gmail, parser_fn, state: dict, log, *, dry_run: bool) -> int:
    msgs = gmail.fetch_pending()
    count = 0
    for msg in msgs:
        existing = next(
            (r for r in state["requests"]
             if r.get("original_message_id") == msg.message_id),
            None,
        )
        if existing is not None:
            # Already in state — just restore the label invariant and move on.
            log.info(
                "ingest skip: already in state",
                extra={"step": "ingest", "thread_id": msg.thread_id},
            )
            if not dry_run:
                gmail.relabel(
                    msg.message_id, remove=[LABEL_PENDING], add=[LABEL_DRAFT],
                )
            continue

        parsed = parser_fn(msg.body, msg.subject)
        subject, body = build_release_email(parsed, msg.subject, msg.from_)

        if dry_run:
            log.info(
                "ingest dry-run: would create draft",
                extra={
                    "step": "ingest",
                    "thread_id": msg.thread_id,
                    "subject": subject,
                },
            )
        else:
            draft_id = gmail.create_draft(
                to=cfg.warehouse_email,
                subject=subject,
                body=body,
                in_reply_to=None,
            )
            gmail.relabel(
                msg.message_id, remove=[LABEL_PENDING], add=[LABEL_DRAFT],
            )
            S.add_request(
                state,
                thread_id=msg.thread_id,
                message_id=msg.message_id,
                subject=msg.subject,
                from_=msg.from_,
                received_at=msg.internal_date,
                parsed=parsed.model_dump(),
            )
            S.mark_draft_created(state, msg.thread_id, draft_id=draft_id)
            log.info(
                "draft created",
                extra={
                    "step": "ingest",
                    "thread_id": msg.thread_id,
                    "draft_id": draft_id,
                },
            )
        count += 1
    return count


def _detect_sent(cfg: Config, gmail, state: dict, log, *, dry_run: bool) -> int:
    count = 0
    for req in state["requests"]:
        if req.get("status") != "draft_created":
            continue
        # Look for a sent message whose subject matches the release email
        # we drafted. We don't have the draft's subject stored; reconstruct it.
        sent = gmail.fetch_sent_to(
            to=cfg.warehouse_email,
            subject_prefix=f"Release Request: {req['subject']}",
        )
        if not sent:
            continue
        sent.sort(key=lambda m: m.internal_date)
        match = sent[0]
        if dry_run:
            log.info(
                "detect_sent dry-run: would mark released",
                extra={
                    "step": "detect_sent",
                    "thread_id": req["thread_id"],
                    "release_message_id": match.message_id,
                },
            )
        else:
            S.mark_released(
                state,
                req["thread_id"],
                release_message_id=match.message_id,
                warehouse_thread_id=match.thread_id,
                released_at=match.internal_date,
            )
            gmail.relabel(
                req["original_message_id"],
                remove=[LABEL_DRAFT],
                add=[LABEL_RELEASED],
            )
            log.info(
                "detected sent",
                extra={
                    "step": "detect_sent",
                    "thread_id": req["thread_id"],
                    "release_message_id": match.message_id,
                },
            )
        count += 1
    return count


def _check_shipments(cfg: Config, gmail, state: dict, log, *, dry_run: bool) -> int:
    count = 0
    for req in state["requests"]:
        if req.get("status") != "released":
            continue
        warehouse_thread = req.get("warehouse_thread_id")
        if not warehouse_thread:
            continue
        thread = gmail.fetch_thread(warehouse_thread)
        tracking = None
        for m in thread:
            blob = f"{m.subject}\n{m.body}"
            match = S.UPS_TRACKING_RE.search(blob)
            if match:
                tracking = match.group(0)
                break
        if tracking is None:
            continue
        if dry_run:
            log.info(
                "check_shipments dry-run: would mark shipped",
                extra={
                    "step": "check_shipments",
                    "thread_id": req["thread_id"],
                    "tracking": tracking,
                },
            )
        else:
            S.mark_shipped(state, req["thread_id"], tracking)
            gmail.relabel(
                req["original_message_id"],
                remove=[LABEL_RELEASED],
                add=[LABEL_SHIPPED],
            )
            log.info(
                "shipped",
                extra={
                    "step": "check_shipments",
                    "thread_id": req["thread_id"],
                    "tracking": tracking,
                },
            )
        count += 1
    return count


def _send_followups(cfg: Config, gmail, state: dict, log, *, dry_run: bool, now_fn) -> int:
    count = 0
    threshold = cfg.followup_threshold_hours
    for req in state["requests"]:
        if req.get("status") != "released":
            continue
        last = S.last_contact_at(req)
        hours_since = (now_fn() - last).total_seconds() / 3600.0
        if hours_since < threshold:
            continue
        warehouse_thread = req.get("warehouse_thread_id")
        if not warehouse_thread:
            continue
        n_th = len(req.get("follow_ups", [])) + 1
        from backend.sample_request.sender import build_followup_email
        body = build_followup_email(req, n_th)
        if dry_run:
            log.info(
                "send_followups dry-run: would reply",
                extra={
                    "step": "send_followups",
                    "thread_id": req["thread_id"],
                    "n_th": n_th,
                },
            )
        else:
            new_msg_id = gmail.reply_in_thread(warehouse_thread, body)
            # See spec §4: 2s sleep so subsequent `last_contact_at` queries
            # don't outrun Gmail's index update.
            time.sleep(2)
            S.record_followup(state, req["thread_id"], message_id=new_msg_id)
            log.info(
                "follow-up sent",
                extra={
                    "step": "send_followups",
                    "thread_id": req["thread_id"],
                    "n_th": n_th,
                    "message_id": new_msg_id,
                },
            )
        count += 1
    return count


# ---- run_tick orchestrator ------------------------------------------------

def run_tick(
    cfg: Config,
    *,
    gmail,
    parser_fn: Callable[[str, str], ParsedRequest],
    dry_run: bool = False,
    now: Callable[[], datetime] | None = None,
) -> TickResult:
    now_fn = now or _now
    tick_id = make_tick_id()
    log = setup_logger(cfg.log_path, tick_id)
    log.info("tick start", extra={"step": "tick", "dry_run": dry_run})

    state_path = (
        cfg.state_file.with_suffix(cfg.state_file.suffix + f".dryrun.{tick_id}")
        if dry_run else cfg.state_file
    )
    state = S.load_state(cfg.state_file)
    result = TickResult()

    try:
        result.ingested = _ingest(cfg, gmail, parser_fn, state, log, dry_run=dry_run)
        result.detected_sent = _detect_sent(cfg, gmail, state, log, dry_run=dry_run)
        result.shipped = _check_shipments(cfg, gmail, state, log, dry_run=dry_run)
        result.followups = _send_followups(
            cfg, gmail, state, log, dry_run=dry_run, now_fn=now_fn,
        )
    except Exception as exc:           # noqa: BLE001 — surface but keep going
        log.exception("tick failed", extra={"step": "tick"})
        result.outcome = "failed"
        S.update_meta(state, last_tick_at=_iso(now_fn()), last_tick_outcome="failed")
        S.save_state(state_path, state)
        return result

    outcome = "ok" if result.errors == 0 else "partial"
    result.outcome = outcome
    S.update_meta(state, last_tick_at=_iso(now_fn()), last_tick_outcome=outcome)
    S.save_state(state_path, state)
    log.info(
        "tick complete",
        extra={"step": "tick", "stats": result.model_dump()},
    )
    return result


# ---- CLI entry ------------------------------------------------------------

def _cmd_tick(args: argparse.Namespace) -> int:
    cfg = load_config()
    from backend.sample_request.gmail_client import GmailClient

    gmail = GmailClient(cfg.token_path, cfg.credentials_path)

    import anthropic
    ant = anthropic.Anthropic(api_key=cfg.anthropic_api_key)

    def parser_fn(body: str, subject: str) -> ParsedRequest:
        return parse_request_body(body, subject, client=ant, model=cfg.po_model)

    result = run_tick(cfg, gmail=gmail, parser_fn=parser_fn, dry_run=args.dry_run)
    return 0 if result.outcome != "failed" else 1


def _cmd_status(args: argparse.Namespace) -> int:
    # Full implementation in Task 16; placeholder so argparse wiring works.
    print("status: not yet implemented — see plan Task 16")
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    cfg = load_config()
    if cfg.state_file.exists() and not args.force:
        print(f"state file already exists at {cfg.state_file} (use --force)", file=sys.stderr)
        return 1
    S.save_state(cfg.state_file, S._empty_state())     # noqa: SLF001
    print(f"initialized empty state file at {cfg.state_file}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="backend.sample_request")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("tick", help="Run one tick cycle")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=_cmd_tick)

    sp = sub.add_parser("status", help="Pretty-print state")
    sp.set_defaults(func=_cmd_status)

    sp = sub.add_parser("init", help="Create empty state file")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=_cmd_init)

    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":                                # pragma: no cover
    raise SystemExit(main())
