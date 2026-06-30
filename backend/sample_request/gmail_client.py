"""Gmail API thin wrapper.

This file is intentionally not unit-tested (see spec §6). Integration tests
use FakeGmailClient (tests/fake_gmail.py) which mirrors this surface.
Verify behaviour via the manual smoke checklist in README.md.
"""
from __future__ import annotations

import base64
import email
import email.message
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
]

LABEL_NAMES = (
    "sample-request/pending-release",
    "sample-request/draft-ready",
    "sample-request/released",
    "sample-request/shipped",
    "sample-request/needs-attention",
)


@dataclass
class GmailMessage:
    message_id: str
    thread_id: str
    from_: str
    to: str
    subject: str
    body: str
    internal_date: str          # ISO UTC


def load_credentials(token_path: Path, credentials_path: Path) -> Credentials:
    creds: Credentials | None = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(
            str(token_path), GMAIL_SCOPES
        )
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json())
        return creds
    if not credentials_path.exists():
        raise FileNotFoundError(
            f"OAuth credentials not found at {credentials_path}. "
            "Run `.venv/bin/python3 -m backend.sample_request.auth` first."
        )
    flow = InstalledAppFlow.from_client_secrets_file(
        str(credentials_path), GMAIL_SCOPES
    )
    creds = flow.run_local_server(port=0)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    return creds


def _internal_date_iso(ms_str: str) -> str:
    dt = datetime.fromtimestamp(int(ms_str) / 1000.0, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _extract_body(payload: dict) -> str:
    if "parts" in payload:
        for part in payload["parts"]:
            mime = part.get("mimeType", "")
            if mime == "text/plain":
                data = part.get("body", {}).get("data")
                if data:
                    return base64.urlsafe_b64decode(data + "==").decode(
                        "utf-8", errors="replace"
                    )
        for part in payload["parts"]:
            txt = _extract_body(part)
            if txt:
                return txt
    data = payload.get("body", {}).get("data")
    if data:
        return base64.urlsafe_b64decode(data + "==").decode(
            "utf-8", errors="replace"
        )
    return ""


def _headers_to_dict(headers: list[dict]) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in headers}


class GmailClient:
    def __init__(self, token_path: Path, credentials_path: Path) -> None:
        self._creds = load_credentials(token_path, credentials_path)
        self._svc = build("gmail", "v1", credentials=self._creds, cache_discovery=False)
        self._label_cache: dict[str, str] = {}

    # ---- reads ------------------------------------------------------------

    def fetch_pending(self) -> list[GmailMessage]:
        label_id = self.ensure_labels(
            ["sample-request/pending-release"]
        )["sample-request/pending-release"]
        listing = self._svc.users().messages().list(
            userId="me", labelIds=[label_id], maxResults=50,
        ).execute()
        return [self._get_message(m["id"]) for m in listing.get("messages", [])]

    def fetch_sent_to(self, to: str, subject_prefix: str) -> list[GmailMessage]:
        query = f'from:me to:{to} subject:"{subject_prefix}" newer_than:1d'
        listing = self._svc.users().messages().list(
            userId="me", q=query, maxResults=50,
        ).execute()
        return [self._get_message(m["id"]) for m in listing.get("messages", [])]

    def fetch_thread(self, thread_id: str) -> list[GmailMessage]:
        thread = self._svc.users().threads().get(
            userId="me", id=thread_id, format="full",
        ).execute()
        return [self._to_gmail_message(m) for m in thread.get("messages", [])]

    def _get_message(self, message_id: str) -> GmailMessage:
        msg = self._svc.users().messages().get(
            userId="me", id=message_id, format="full",
        ).execute()
        return self._to_gmail_message(msg)

    def _to_gmail_message(self, msg: dict) -> GmailMessage:
        payload = msg.get("payload", {})
        headers = _headers_to_dict(payload.get("headers", []))
        return GmailMessage(
            message_id=msg["id"],
            thread_id=msg["threadId"],
            from_=headers.get("from", ""),
            to=headers.get("to", ""),
            subject=headers.get("subject", ""),
            body=_extract_body(payload),
            internal_date=_internal_date_iso(msg["internalDate"]),
        )

    # ---- writes -----------------------------------------------------------

    def create_draft(
        self,
        to: str,
        subject: str,
        body: str,
        in_reply_to: str | None = None,
    ) -> str:
        mime = email.message.EmailMessage()
        mime["To"] = to
        mime["Subject"] = subject
        if in_reply_to:
            mime["In-Reply-To"] = in_reply_to
            mime["References"] = in_reply_to
        mime.set_content(body)
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
        draft = self._svc.users().drafts().create(
            userId="me", body={"message": {"raw": raw}},
        ).execute()
        return draft["id"]

    def reply_in_thread(self, thread_id: str, body: str) -> str:
        thread = self._svc.users().threads().get(
            userId="me", id=thread_id, format="metadata",
            metadataHeaders=["Subject", "From", "Message-ID"],
        ).execute()
        first = thread["messages"][0]
        headers = _headers_to_dict(first.get("payload", {}).get("headers", []))
        subj = headers.get("subject", "")
        if not subj.lower().startswith("re:"):
            subj = f"Re: {subj}"
        in_reply_to = headers.get("message-id", "")
        recipient = headers.get("from", "")

        mime = email.message.EmailMessage()
        mime["To"] = recipient
        mime["Subject"] = subj
        if in_reply_to:
            mime["In-Reply-To"] = in_reply_to
            mime["References"] = in_reply_to
        mime.set_content(body)
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
        sent = self._svc.users().messages().send(
            userId="me",
            body={"raw": raw, "threadId": thread_id},
        ).execute()
        return sent["id"]

    # ---- labels -----------------------------------------------------------

    def ensure_labels(self, names: list[str]) -> dict[str, str]:
        if all(n in self._label_cache for n in names):
            return {n: self._label_cache[n] for n in names}
        existing = self._svc.users().labels().list(userId="me").execute()
        by_name = {l["name"]: l["id"] for l in existing.get("labels", [])}
        out: dict[str, str] = {}
        for n in names:
            if n in by_name:
                out[n] = by_name[n]
            else:
                created = self._svc.users().labels().create(
                    userId="me",
                    body={
                        "name": n,
                        "labelListVisibility": "labelShow",
                        "messageListVisibility": "show",
                    },
                ).execute()
                out[n] = created["id"]
            self._label_cache[n] = out[n]
        return out

    def relabel(
        self,
        message_id: str,
        remove: list[str],
        add: list[str],
    ) -> None:
        ids = self.ensure_labels(list({*remove, *add}))
        self._svc.users().messages().modify(
            userId="me",
            id=message_id,
            body={
                "removeLabelIds": [ids[n] for n in remove if n in ids],
                "addLabelIds": [ids[n] for n in add if n in ids],
            },
        ).execute()
