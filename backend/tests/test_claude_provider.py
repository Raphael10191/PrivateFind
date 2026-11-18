"""ClaudeProvider with a fake SDK client (no network, no API key needed)."""

from types import SimpleNamespace

import pytest

from app.shared.ai.claude import ClaudeProvider, _Similarities
from app.shared.ai.provider import AIError, Photo
from app.shared.ai.schemas import Extraction


class FakeMessages:
    def __init__(self, output, stop_reason="end_turn"):
        self.output = output
        self.stop_reason = stop_reason
        self.calls = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason=self.stop_reason, parsed_output=self.output)


def provider(output, stop_reason="end_turn"):
    messages = FakeMessages(output, stop_reason)
    return ClaudeProvider(client=SimpleNamespace(messages=messages)), messages


async def test_extract_sends_images_and_schema():
    ex = Extraction(
        category="wallet",
        color="brown",
        public_summary="Brown wallet",
        description="Brown leather wallet",
        confidence=0.9,
    )
    p, messages = provider(ex)
    assert await p.extract_attributes([Photo(b"\xff\xd8jpeg")], "near library") == ex
    call = messages.calls[0]
    assert call["output_format"] is Extraction
    content = call["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/jpeg"
    assert "near library" in content[-1]["text"]


async def test_refusal_raises_for_retry():
    p, _ = provider(None, stop_reason="refusal")
    with pytest.raises(AIError):
        await p.extract_attributes([], "note")


async def test_compare_texts_validates_length_and_clamps():
    p, _ = provider(_Similarities(scores=[1.4, -0.2]))
    assert await p.compare_texts("q", ["a", "b"]) == [1.0, 0.0]
    p, _ = provider(_Similarities(scores=[0.5]))
    with pytest.raises(AIError):
        await p.compare_texts("q", ["a", "b"])
    assert await p.compare_texts("q", []) == []
