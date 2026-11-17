import json
from unittest.mock import Mock
from urllib.error import HTTPError

from app.core.config import Settings
from app.shared.ai import provider
from app.shared.ai.provider import Photo
from app.shared.ai.qwen import QwenProvider


def response(payload):
    return {"choices": [{"message": {"content": f"<think>ignore</think>\n{json.dumps(payload)}"}}]}


async def test_qwen_extraction_sends_both_images_and_normalizes_output(monkeypatch):
    settings = Settings(ai_provider="qwen", qwen_base_url="https://example.test/v1/")
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
    result = await ai.extract_attributes([Photo(b"a"), Photo(b"b", "image/png")], "finder note")
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


async def test_qwen_detail_matrix_maps_original_ids_in_one_request(monkeypatch):
    ai = QwenProvider(Settings(qwen_model="test-qwen"))
    attrs = [(51, "damage", "cracked screen"), (79, "other", "car wallpaper")]
    evidence = [(2, "other", "Riss"), (8, "accessory", "Auto")]
    request = Mock(return_value=response({"scores": [[0.92, 0.1], [0.05, 0.88]]}))
    monkeypatch.setattr(ai, "_request", request)
    assert await ai.verify_details(attrs, evidence) == {
        (51, 2): 0.92,
        (51, 8): 0.1,
        (79, 2): 0.05,
        (79, 8): 0.88,
    }
    assert request.call_count == 1


async def test_qwen_falls_back_on_bad_or_unavailable_responses(monkeypatch):
    ai = QwenProvider(Settings(qwen_model="test-qwen"))
    request = Mock(
        side_effect=[
            TimeoutError(),
            response({"scores": [0]}),
            response({"scores": [[0.4], [0.2]]}),
        ]
    )
    monkeypatch.setattr(ai, "_request", request)
    assert (await ai.extract_attributes([], "black phone")).category == "phone"
    assert await ai.compare_texts("cat sticker", ["cat sticker", "new tablet"]) == [1.0, 0.0]
    assert await ai.verify_details([(1, "damage", "scratch")], [(7, "other", "scratch")]) == {
        (1, 7): 1.0,
    }


async def test_qwen_does_not_call_api_for_empty_candidates_or_details(monkeypatch):
    ai = QwenProvider(Settings(qwen_model="test-qwen"))
    request = Mock()
    monkeypatch.setattr(ai, "_request", request)
    assert await ai.compare_texts("query", []) == []
    assert await ai.verify_details([], [(0, "other", "value")]) == {}
    request.assert_not_called()
