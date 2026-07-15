"""Email-body structured parser backed by the Anthropic SDK."""
from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    import anthropic


class ParsedItem(BaseModel):
    name: str
    qty: int
    qty_unit: str = "each"
    item_number: str | None = None


class ParsedRequest(BaseModel):
    recipient: str
    address: str
    items: list[ParsedItem]


class ParserError(Exception):
    """Base class for parser-level failures."""


class ParserRefused(ParserError):
    """Claude refused to parse the message."""


class ParserSchemaError(ParserError):
    """Claude returned a response that did not match ParsedRequest."""


_SYSTEM_PROMPT = """\
You extract structured shipping data from sample-request emails.

Return a ParsedRequest with:
- recipient: the person who should receive the sample
- address: the ship-to address as a single human-readable string
- items: list of items requested, each with name, qty, optional qty_unit
  (default "each"), and optional item_number if explicitly present in the body

The body may be informal, contain typos, or use mixed formatting. Do your best
to extract; if the body really has no shipping intent, return an empty items
list rather than refusing.
"""


def parse_request_body(
    body: str,
    subject: str,
    *,
    client: "anthropic.Anthropic | None" = None,
    model: str = "claude-opus-4-8",
) -> ParsedRequest:
    if client is None:                          # pragma: no cover - real-call path
        import anthropic
        client = anthropic.Anthropic()

    response = client.messages.parse(
        model=model,
        max_tokens=2048,
        system=_SYSTEM_PROMPT,
        output_format=ParsedRequest,
        messages=[{
            "role": "user",
            "content": f"Subject: {subject}\n\n{body}",
        }],
    )

    if getattr(response, "stop_reason", "") == "refusal":
        raise ParserRefused("Claude refused to parse the message")

    parsed = getattr(response, "parsed_output", None)
    if parsed is None:
        raise ParserSchemaError("Claude response did not match ParsedRequest schema")

    return parsed
