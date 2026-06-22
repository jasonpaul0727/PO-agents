from pathlib import Path

import pytest

from backend.models import ExtractedPO, POHeader, LineItem
from backend.repository import Repository

SEED = Path(__file__).resolve().parents[1] / "backend" / "seed"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def repo() -> Repository:
    return Repository(db_path=":memory:", seed_dir=str(SEED))


@pytest.fixture
def valid_po() -> ExtractedPO:
    return ExtractedPO(
        header=POHeader(customer="ACME Corp", po_number="PO-1001", ship_to="123 Main St"),
        line_items=[LineItem(item_number="ITEM-1002", order_quantity=40, unit_price=5.0)],
    )


class FakeParseResponse:
    def __init__(self, parsed):
        self.parsed_output = parsed


class FakeClient:
    """Stand-in for anthropic.Anthropic — returns a preset ExtractedPO from messages.parse."""

    def __init__(self, parsed: ExtractedPO):
        self._parsed = parsed
        self.calls = []

        class _Messages:
            def __init__(self, outer):
                self._outer = outer

            def parse(self, **kwargs):
                self._outer.calls.append(kwargs)
                return FakeParseResponse(self._outer._parsed)

        self.messages = _Messages(self)


@pytest.fixture
def fake_client(valid_po):
    return FakeClient(valid_po)
