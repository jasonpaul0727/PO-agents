"""In-memory test double for GmailClient.

This is what the integration tests run against. The real GmailClient
(Task 8) provides the same surface against the Gmail API.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable


@dataclass
class FakeGmailMessage:
    message_id: str
    thread_id: str
    from_: str
    to: str
    subject: str
    body: str
    internal_date: str   # ISO UTC


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeGmailClient:
    """Test double for GmailClient with the same public surface."""

    def __init__(self) -> None:
        self._messages: dict[str, FakeGmailMessage] = {}
        self._threads: dict[str, list[str]] = defaultdict(list)
        self._labels_on: dict[str, set[str]] = defaultdict(set)
        self._labels_known: dict[str, str] = {}
        self._next_id = 1
        self._next_draft_id = 1
        self.drafts_created: list[dict] = []
        self.sent: list[dict] = []
        self._fail_plan: dict[str, list[Exception]] = defaultdict(list)

    # ---- public surface ---------------------------------------------------

    def fetch_pending(self) -> list[FakeGmailMessage]:
        self._maybe_fail("fetch_pending")
        return [
            self._messages[mid]
            for mid, labels in self._labels_on.items()
            if "sample-request/pending-release" in labels and mid in self._messages
        ]

    def fetch_sent_to(self, to: str, subject_prefix: str) -> list[FakeGmailMessage]:
        self._maybe_fail("fetch_sent_to")
        return [
            FakeGmailMessage(**s)
            for s in self.sent
            if s["to"] == to and s["subject"].startswith(subject_prefix)
        ]

    def fetch_thread(self, thread_id: str) -> list[FakeGmailMessage]:
        self._maybe_fail("fetch_thread")
        return [
            self._messages[mid]
            for mid in self._threads.get(thread_id, [])
            if mid in self._messages
        ]

    def create_draft(
        self,
        to: str,
        subject: str,
        body: str,
        in_reply_to: str | None = None,
    ) -> str:
        self._maybe_fail("create_draft")
        draft_id = f"draft-{self._next_draft_id}"
        self._next_draft_id += 1
        self.drafts_created.append({
            "draft_id": draft_id,
            "to": to,
            "subject": subject,
            "body": body,
            "in_reply_to": in_reply_to,
        })
        return draft_id

    def reply_in_thread(self, thread_id: str, body: str) -> str:
        self._maybe_fail("reply_in_thread")
        msg_id = self._mint_id("reply")
        # Pull subject from first message in the thread, prefixed with Re:
        first = self._messages[self._threads[thread_id][0]]
        subj = first.subject if first.subject.startswith("Re:") else f"Re: {first.subject}"
        msg = FakeGmailMessage(
            message_id=msg_id,
            thread_id=thread_id,
            from_="me@example.com",
            to=first.from_,
            subject=subj,
            body=body,
            internal_date=_now_iso(),
        )
        self._messages[msg_id] = msg
        self._threads[thread_id].append(msg_id)
        return msg_id

    def relabel(
        self,
        message_id: str,
        remove: list[str],
        add: list[str],
    ) -> None:
        self._maybe_fail("relabel")
        for name in remove:
            self._labels_on[message_id].discard(name)
        for name in add:
            self._labels_on[message_id].add(name)

    def ensure_labels(self, names: list[str]) -> dict[str, str]:
        self._maybe_fail("ensure_labels")
        for n in names:
            self._labels_known.setdefault(n, f"label-{len(self._labels_known)+1}")
        return {n: self._labels_known[n] for n in names}

    # ---- test helpers -----------------------------------------------------

    def inject_pending(
        self,
        from_: str,
        to: str,
        subject: str,
        body: str,
        internal_date: str | None = None,
    ) -> FakeGmailMessage:
        mid = self._mint_id("msg")
        tid = self._mint_id("thread")
        msg = FakeGmailMessage(
            message_id=mid, thread_id=tid, from_=from_, to=to,
            subject=subject, body=body,
            internal_date=internal_date or _now_iso(),
        )
        self._messages[mid] = msg
        self._threads[tid].append(mid)
        self._labels_on[mid].add("sample-request/pending-release")
        return msg

    def inject_sent(
        self,
        to: str,
        subject: str,
        body: str,
        thread_id: str | None = None,
        internal_date: str | None = None,
    ) -> dict:
        """Simulate the user having clicked Send on a draft (or a manual send)."""
        message_id = self._mint_id("sent")
        thread_id = thread_id or self._mint_id("thread")
        record = {
            "message_id": message_id,
            "thread_id": thread_id,
            "from_": "me@example.com",
            "to": to,
            "subject": subject,
            "body": body,
            "internal_date": internal_date or _now_iso(),
        }
        self.sent.append(record)
        self._messages[message_id] = FakeGmailMessage(**record)
        self._threads[thread_id].append(message_id)
        return record

    def inject_thread_reply(
        self,
        thread_id: str,
        from_: str,
        body: str,
        internal_date: str | None = None,
    ) -> FakeGmailMessage:
        mid = self._mint_id("reply")
        msg = FakeGmailMessage(
            message_id=mid, thread_id=thread_id, from_=from_,
            to="me@example.com", subject="Re: …",
            body=body,
            internal_date=internal_date or _now_iso(),
        )
        self._messages[mid] = msg
        self._threads[thread_id].append(mid)
        return msg

    def labels_on(self, message_id: str) -> set[str]:
        return set(self._labels_on.get(message_id, set()))

    def fail_next(
        self,
        method_name: str,
        times: int = 1,
        exc: Exception | Callable[[], Exception] | None = None,
    ) -> None:
        """Arm `times` upcoming calls to method_name to raise `exc`."""
        if exc is None:
            exc = RuntimeError(f"forced failure in {method_name}")
        for _ in range(times):
            self._fail_plan[method_name].append(
                exc() if callable(exc) else exc
            )

    # ---- internals --------------------------------------------------------

    def _mint_id(self, prefix: str) -> str:
        self._next_id += 1
        return f"{prefix}-{self._next_id:05d}"

    def _maybe_fail(self, method_name: str) -> None:
        plan = self._fail_plan.get(method_name)
        if plan:
            raise plan.pop(0)
