"""Standalone OAuth setup for sample-request.

Run once after placing `secrets/credentials.json` (downloaded from Google
Cloud Console) to obtain `secrets/token.json` and pre-create the five
operational Gmail labels.

    .venv/bin/python3 -m backend.sample_request.auth
"""
from __future__ import annotations

import sys

from backend.sample_request.config import load_config
from backend.sample_request.gmail_client import (
    LABEL_NAMES,
    GmailClient,
    load_credentials,
)


def main() -> int:
    try:
        cfg = load_config()
    except ValueError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    if not cfg.credentials_path.exists():
        print(
            f"OAuth credentials missing at {cfg.credentials_path}.\n"
            "1. Open Google Cloud Console -> APIs & Services -> Credentials\n"
            "2. Create OAuth client ID (Desktop) -> Download JSON\n"
            f"3. Save it as {cfg.credentials_path}\n"
            "4. Re-run this command.",
            file=sys.stderr,
        )
        return 1

    print(f"Running OAuth flow with creds {cfg.credentials_path}...")
    load_credentials(cfg.token_path, cfg.credentials_path)
    print(f"Token written to {cfg.token_path}.")

    print("Ensuring Gmail labels exist...")
    client = GmailClient(cfg.token_path, cfg.credentials_path)
    ids = client.ensure_labels(list(LABEL_NAMES))
    for name in LABEL_NAMES:
        print(f"  {name}: {ids[name]}")

    print("\nNext: create a Gmail filter in the web UI matching "
          "`subject:\"sample request\"` and apply the "
          "`sample-request/pending-release` label.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
