"""Verification: --dry-run path makes no Gmail writes and writes a sidecar state file."""
from __future__ import annotations

from backend.sample_request import state as S
from backend.sample_request.cli import run_tick
from backend.sample_request.parser import ParsedItem, ParsedRequest


def test_dry_run_no_draft_no_relabel_writes_sidecar_state(config, fake_gmail):
    msg = fake_gmail.inject_pending(
        from_="c@example.com", to="me@example.com",
        subject="Sample request — dryrun", body="b",
    )
    parsed = ParsedRequest(
        recipient="R", address="A",
        items=[ParsedItem(name="X", qty=1)],
    )

    result = run_tick(
        config,
        gmail=fake_gmail,
        parser_fn=lambda b, s: parsed,
        dry_run=True,
    )

    assert result.ingested == 1
    assert fake_gmail.drafts_created == []
    # label unchanged
    assert "sample-request/pending-release" in fake_gmail.labels_on(msg.message_id)
    assert "sample-request/draft-ready" not in fake_gmail.labels_on(msg.message_id)
    # canonical state untouched
    canonical = S.load_state(config.state_file)
    assert canonical["requests"] == []
    # sidecar exists
    sidecars = list(config.state_file.parent.glob(config.state_file.name + ".dryrun.*"))
    assert len(sidecars) == 1
