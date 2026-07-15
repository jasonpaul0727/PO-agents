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
from typing import Callable, TypeVar

from googleapiclient.errors import HttpError
from pydantic import BaseModel

from backend.sample_request import state as S
from backend.sample_request.config import Config, load_config
from backend.sample_request.log import make_tick_id, setup_logger
from backend.sample_request.parser import ParsedRequest, parse_request_body
from backend.sample_request.sender import build_release_email

T = TypeVar("T")

_TRANSIENT_STATUS = {429, 500, 502, 503, 504}


class TransientError(Exception):
    """Raised when retries are exhausted on a transient Gmail error."""


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, HttpError):
        try:
            return exc.resp.status in _TRANSIENT_STATUS
        except AttributeError:
            return False
    return isinstance(exc, (TimeoutError, ConnectionError))


def _retry(
    call,
    *,
    retries: int = 3,
    base: float = 1.0,
    sleep_fn=time.sleep,
):
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return call()
        except Exception as exc:                     # noqa: BLE001
            if not _is_transient(exc):
                raise
            last_exc = exc
            sleep_fn(base * (4 ** attempt))          # 1s, 4s, 16s
    raise TransientError(str(last_exc)) from last_exc


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

def _record_pending_message_error(
    cfg: Config, gmail, state: dict, log, msg, *,
    step: str, exc: Exception, raw_excerpt: str | None,
) -> None:
    """Record a per-message error for a request that has not yet been
    added to state (i.e. failed during ingest before `add_request`).
    Failure counts are persisted in `state.ingest_failure_counts` (see
    Task 4) so escalation survives across ticks. The counter is cleared
    once the message successfully becomes a tracked request."""
    log.error(
        f"{step} failed",
        extra={
            "step": step,
            "thread_id": msg.thread_id,
            "error_class": exc.__class__.__name__,
            "error": str(exc)[:500],
        },
    )
    n = S.bump_ingest_failure(state, msg.message_id)
    if n >= 3:
        gmail.relabel(msg.message_id, remove=[], add=[LABEL_ATTENTION])
        log.warning(
            "needs-attention label added",
            extra={"step": step, "thread_id": msg.thread_id, "failures": n},
        )


def _ingest(cfg: Config, gmail, parser_fn, state: dict, log, *, dry_run: bool) -> tuple[int, int]:
    """Returns (ingested, errors)."""
    msgs = gmail.fetch_pending()
    count = 0
    errors = 0
    for msg in msgs:
        existing = next(
            (r for r in state["requests"]
             if r.get("original_message_id") == msg.message_id),
            None,
        )
        if existing is not None:
            log.info(
                "ingest skip: already in state",
                extra={"step": "ingest", "thread_id": msg.thread_id},
            )
            if not dry_run:
                gmail.relabel(
                    msg.message_id, remove=[LABEL_PENDING], add=[LABEL_DRAFT],
                )
            continue

        try:
            parsed = parser_fn(msg.body, msg.subject)
        except Exception as exc:                     # noqa: BLE001
            errors += 1
            _record_pending_message_error(
                cfg, gmail, state, log, msg,
                step="parser",
                exc=exc,
                raw_excerpt=msg.body,
            )
            continue

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
            count += 1
            continue

        try:
            draft_id = _retry(lambda: gmail.create_draft(
                to=cfg.warehouse_email,
                subject=subject,
                body=body,
                in_reply_to=None,
            ))
        except Exception as exc:                     # noqa: BLE001
            errors += 1
            _record_pending_message_error(
                cfg, gmail, state, log, msg,
                step="create_draft",
                exc=exc,
                raw_excerpt=None,
            )
            continue

        # relabel + state writes are *not* wrapped in tick_errors — relabel
        # failure is FATAL per spec §5 (it propagates and the outer run_tick
        # catch sets outcome="failed").
        gmail.relabel(msg.message_id, remove=[LABEL_PENDING], add=[LABEL_DRAFT])
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
        S.reset_ingest_failure(state, msg.message_id)
        log.info(
            "draft created",
            extra={
                "step": "ingest",
                "thread_id": msg.thread_id,
                "draft_id": draft_id,
            },
        )
        count += 1
    return count, errors


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


def _send_followups(cfg: Config, gmail, state: dict, log, *, dry_run: bool, now_fn) -> tuple[int, int]:
    """Returns (followups_sent, errors)."""
    count = 0
    errors = 0
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
            count += 1
            continue
        try:
            new_msg_id = _retry(lambda: gmail.reply_in_thread(warehouse_thread, body))
        except Exception as exc:                     # noqa: BLE001
            errors += 1
            n = S.append_tick_error(
                state, req["thread_id"],
                step="send_followups",
                error_class=exc.__class__.__name__,
                message=str(exc)[:500],
            )
            log.error(
                "send_followups failed",
                extra={
                    "step": "send_followups",
                    "thread_id": req["thread_id"],
                    "failures": n,
                },
            )
            if n >= 3:
                gmail.relabel(
                    req["original_message_id"], remove=[], add=[LABEL_ATTENTION],
                )
                log.warning(
                    "needs-attention label added",
                    extra={"step": "send_followups", "thread_id": req["thread_id"]},
                )
            continue
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
    return count, errors


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
        ingested, ingest_errs = _ingest(cfg, gmail, parser_fn, state, log, dry_run=dry_run)
        result.ingested = ingested
        result.errors += ingest_errs

        result.detected_sent = _detect_sent(cfg, gmail, state, log, dry_run=dry_run)
        result.shipped = _check_shipments(cfg, gmail, state, log, dry_run=dry_run)

        followups, fu_errs = _send_followups(
            cfg, gmail, state, log, dry_run=dry_run, now_fn=now_fn,
        )
        result.followups = followups
        result.errors += fu_errs
    except Exception:
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


def _render_status(state: dict) -> str:
    requests = state.get("requests", [])
    meta = state.get("meta", {})
    header = (
        f"last tick: {meta.get('last_tick_at') or 'never'} "
        f"({meta.get('last_tick_outcome') or '-'})"
    )
    if not requests:
        return f"{header}\nNo sample requests on file.\n"
    lines = [header, ""]
    lines.append(
        f"{'thread':<22} {'status':<14} {'recipient':<20} "
        f"{'released_at':<22} {'follow-ups':<12} {'errors':<6}"
    )
    lines.append("-" * 100)
    for r in requests:
        parsed = r.get("parsed") or {}
        lines.append(
            f"{r.get('thread_id','')!s:<22} "
            f"{r.get('status','')!s:<14} "
            f"{parsed.get('recipient','')!s:<20} "
            f"{r.get('released_at') or '-':<22} "
            f"follow-ups: {len(r.get('follow_ups') or [])!s:<3}  "
            f"errors: {len(r.get('tick_errors') or [])}"
        )
    return "\n".join(lines) + "\n"


def _cmd_status(args: argparse.Namespace) -> int:
    cfg = load_config()
    state = S.load_state(cfg.state_file)
    sys.stdout.write(_render_status(state))
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
