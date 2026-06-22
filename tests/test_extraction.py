import pytest

from backend.agents import extraction
from backend.agents.extraction import ExtractionError
from backend.models import ExtractedPO


def test_extract_po_returns_parsed_output(fake_client, valid_po):
    result = extraction.extract_po("some PO text", fake_client)
    assert isinstance(result, ExtractedPO)
    assert result.header.customer == "ACME Corp"
    # the model + schema were passed to parse
    call = fake_client.calls[0]
    assert call["output_format"] is ExtractedPO
    assert "model" in call


def test_extract_po_retries_then_raises():
    class FlakyClient:
        def __init__(self):
            self.attempts = 0

            class _M:
                def __init__(self, outer):
                    self.outer = outer

                def parse(self, **kwargs):
                    self.outer.attempts += 1
                    raise RuntimeError("api down")

            self.messages = _M(self)

    client = FlakyClient()
    with pytest.raises(ExtractionError):
        extraction.extract_po("text", client)
    assert client.attempts == 3   # initial + 2 retries
