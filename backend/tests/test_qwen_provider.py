import json
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest

from app.core.config import Settings
from app.shared.ai import provider
from app.shared.ai.provider import AIError, Photo
from app.shared.ai.qwen import QwenProvider


def response(payload):
    return {"choices": [{"message": {"content": f"<think>ignore</think>\n{json.dumps(payload)}"}}]}


async def test_qwen_extraction_sends_both_images_and_normalizes_output(monkeypatch, caplog):
    settings = Settings(
        ai_provider="qwen", qwen_base_url="https://example.test/v1/", qwen_log_analysis=True
    )
    monkeypatch.setattr(provider, "get_settings", lambda: settings)
    ai = provider.get_ai_provider()
    assert isinstance(ai, QwenProvider)
    assert ai.base_url == "https://example.test/v1"
    raw = {
        "category": "Phone",
        "color": "BLACK",
        "brand": "Apple",
        "description": "Black phone with a scratch",
        "public_summary": "Black Apple phone",
        "confidence": 0.0,
        "private_attributes": [
            {"type": "damage", "value": "scratch", "strength": "distinctive", "confidence": 1.2},
            {"type": "alien", "value": "blue label", "strength": "unknown"},
        ],
    }
    request = Mock(side_effect=[{"data": [{"id": "test-qwen"}]}, response(raw)])
    monkeypatch.setattr(ai, "_request", request)
    with caplog.at_level("INFO", logger="uvicorn.error"):
        result = await ai.extract_attributes([Photo(b"a"), Photo(b"b", "image/png")], "finder note")
    message = next(
        msg for msg in caplog.messages if msg.startswith("[QWEN] Bildanalyse OK (2 Fotos): ")
    )
    assert json.loads(message.split(": ", 1)[1])["description"] == "Black phone with a scratch"
    assert (result.category, result.color, result.brand, result.confidence) == (
        "phone",
        "black",
        "Apple",
        0.0,
    )
    assert [(a.type, a.strength, a.confidence) for a in result.private_attributes] == [
        ("damage", "distinctive", 1.0),
        ("other", "generic", 0.6),
    ]
    assert request.call_args_list[0].args == ("GET", "/models")
    method, path, body = request.call_args_list[1].args
    assert (method, path, body["model"]) == ("POST", "/chat/completions", "test-qwen")
    assert "iPhone 17 Pro and iPhone 18 Pro" in body["messages"][0]["content"]
    assert "An empty list is valid." in body["messages"][0]["content"]
    content = body["messages"][1]["content"]
    assert [part["image_url"]["url"] for part in content if part["type"] == "image_url"] == [
        "data:image/jpeg;base64,YQ==",
        "data:image/png;base64,Yg==",
    ]
    assert content[-1]["text"] == "Finder's note: finder note"


async def test_qwen_compatibility_retry_and_scores(monkeypatch):
    ai = QwenProvider(Settings(qwen_model="test-qwen"))
    payloads = []

    def request(method, path, body):
        payloads.append(body.copy())
        if len(payloads) == 1:
            raise HTTPError("https://example.test/v1", 400, "Unsupported options", {}, None)
        return response({"scores": [0.85, -0.2]})

    monkeypatch.setattr(ai, "_request", request)
    assert await ai.compare_texts("my phone", ["black phone", "umbrella"]) == [0.85, 0]
    assert payloads[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert "response_format" not in payloads[1] and "chat_template_kwargs" not in payloads[1]


async def test_qwen_surfaces_bad_or_unavailable_responses(monkeypatch):
    ai = QwenProvider(Settings(qwen_model="test-qwen"))
    request = Mock(
        side_effect=[
            TimeoutError(),
            response({"scores": [0]}),
        ]
    )
    monkeypatch.setattr(ai, "_request", request)
    with pytest.raises(AIError):
        await ai.extract_attributes([], "black phone")
    with pytest.raises(AIError):
        await ai.compare_texts("cat sticker", ["cat sticker", "new tablet"])


async def test_qwen_does_not_call_api_for_empty_candidates(monkeypatch):
    ai = QwenProvider(Settings(qwen_model="test-qwen"))
    request = Mock()
    monkeypatch.setattr(ai, "_request", request)
    assert await ai.compare_texts("query", []) == []
    request.assert_not_called()


async def test_qwen_verifies_evidence_with_finder_photo_in_same_request(monkeypatch):
    ai = QwenProvider(Settings(qwen_model="test-qwen"))
    description = "A round key with a yello cap. It has a crack near the top."
    finding = {
        "quote": "round key with a yello cap",
        "kind": "arrangement",
        "status": "confirmed",
        "photo_index": 0,
    }
    request = Mock(return_value=response({"findings": [finding]}))
    monkeypatch.setattr(ai, "_request", request)
    results = await ai.verify_photos([Photo(b"a")], description)
    assert [entry.model_dump(exclude_defaults=True) for entry in results] == [finding]
    content = request.call_args.args[2]["messages"][1]["content"]
    assert content[0]["image_url"]["url"] == "data:image/jpeg;base64,YQ=="
    assert json.loads(content[1]["text"])["description"] == description


async def test_qwen_recognizes_model_alternatives_separately(monkeypatch):
    ai = QwenProvider(Settings(qwen_model="test-qwen"))
    request = Mock(
        return_value=response(
            {
                "category": "phone",
                "model": None,
                "model_candidates": ["iPhone 13", "iPhone 14"],
                "less_likely_models": ["iPhone 12"],
                "observations": {"model": "estimated"},
                "description": "Black iPhone in a magnetic-ring case.",
            }
        )
    )
    monkeypatch.setattr(ai, "_request", request)
    result = await ai.extract_attributes([Photo(b"a")], "")
    assert result.model is None
    assert result.model_candidates == ["iPhone 13", "iPhone 14"]
    assert result.less_likely_models == ["iPhone 12"]
    assert result.observations["model"] == "estimated"


@pytest.mark.parametrize(
    ("observation", "exact", "candidates"),
    [
        (None, None, ["iPhone 13"]),
        ("estimated", None, ["iPhone 13"]),
        ("unreadable", None, []),
        ("observed", "iPhone 13", []),
    ],
)
async def test_qwen_only_keeps_observed_models_as_exact(
    monkeypatch, observation, exact, candidates
):
    ai = QwenProvider(Settings(qwen_model="test-qwen"))
    raw = {
        "category": "phone",
        "brand": "Apple",
        "model": "iPhone 13",
        "observations": {"model": observation} if observation else {},
        "description": "Apple iPhone in a protective case.",
        "private_attributes": [],
    }
    monkeypatch.setattr(ai, "_request", Mock(return_value=response(raw)))
    result = await ai.extract_attributes([Photo(b"a")], "")
    assert result.model == exact
    assert result.model_candidates == candidates
    assert result.private_attributes == []


async def test_qwen_keeps_visible_features_with_nonnumeric_confidence(monkeypatch):
    ai = QwenProvider(Settings(qwen_model="test-qwen"))
    raw = {
        "category": "phone",
        "confidence": "strong",
        "private_attributes": [
            {"type": "sticker_or_mark", "value": "MINT LAB", "confidence": "strong"}
        ],
    }
    monkeypatch.setattr(ai, "_request", Mock(return_value=response(raw)))
    result = await ai.extract_attributes([Photo(b"a")], "")
    assert result.confidence == 0.0
    [mark] = result.private_attributes
    assert mark.value == "MINT LAB" and mark.confidence == 0.0
