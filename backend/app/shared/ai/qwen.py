"""Qwen via a vLLM server with an OpenAI-compatible API."""

import asyncio
import base64
import json
import logging
import re
from typing import get_args
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from app.core.config import Settings
from app.shared.ai.claude import COMPARE_SYSTEM, EXTRACT_SYSTEM
from app.shared.ai.mock import MockAIProvider
from app.shared.ai.provider import (
    DETAIL_SYSTEM,
    AIError,
    DetailAttribute,
    DetailScores,
    Photo,
    bounded_score,
    detail_input,
    detail_scores,
)
from app.shared.ai.schemas import Extraction
from app.shared.vocab import Category, Color, EvidenceType, Strength

log = logging.getLogger(__name__)
RESPONSE_ERRORS = (AIError, OSError, ValueError, KeyError, IndexError, TypeError, AttributeError)

EXTRACT_HINT = """
Use the manufacturer's name for brand, for example Apple instead of iPhone.
Look at every photo for cases, damage, stickers, engravings, wallpaper, text and accessories.
Prefer 3 to 6 distinctive private attributes when visible. Use short, concrete values in English.
Include a model attribute only when the exact model is recognizable.
Keep all identifying details in description and private_attributes, away from public_summary.
Return one JSON object with category, color, brand, public_summary, description, confidence
and private_attributes. Each attribute has type, value, strength and confidence."""

COMPARE_HINT = """
Return JSON with a "scores" list containing one number per candidate, in order."""


def _json_object(content: str) -> dict:
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.S)
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end < start:
        raise AIError("Qwen returned no JSON object")
    return json.loads(content[start : end + 1])


def _clean_extraction(raw: dict, note: str) -> Extraction:
    category = str(raw.get("category") or "other").lower().replace(" ", "_")
    if category not in get_args(Category):
        category = "other"
    color = str(raw.get("color") or "").lower()
    attributes = []
    for attr in raw.get("private_attributes") or []:
        if not isinstance(attr, dict) or not (value := str(attr.get("value") or "").strip()):
            continue
        kind = str(attr.get("type") or "other").lower()
        strength = str(attr.get("strength") or "generic").lower()
        attributes.append(
            {
                "type": kind if kind in get_args(EvidenceType) else "other",
                "value": value[:200],
                "strength": strength if strength in get_args(Strength) else "generic",
                "confidence": bounded_score(attr.get("confidence", 0.6)),
            }
        )
    return Extraction.model_validate(
        {
            "category": category,
            "color": color if color in get_args(Color) else None,
            "brand": str(raw["brand"])[:50] if raw.get("brand") else None,
            "public_summary": str(raw.get("public_summary") or category)[:200],
            "description": str(raw.get("description") or note or category),
            "private_attributes": attributes,
            "confidence": bounded_score(raw.get("confidence", 0.6)),
        }
    )


class QwenProvider:
    def __init__(self, settings: Settings):
        self.base_url = settings.qwen_base_url.rstrip("/")
        self.api_key = settings.qwen_api_key.get_secret_value()
        self.model = settings.qwen_model
        self.timeout = settings.qwen_timeout
        self.max_photos = settings.max_photos
        self.mock = MockAIProvider()

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        if not self.base_url:
            raise AIError("QWEN_BASE_URL is missing")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(
            self.base_url + path,
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers=headers,
        )
        opener = build_opener(ProxyHandler({}))
        with opener.open(request, timeout=self.timeout) as response:
            return json.load(response)

    def _chat_sync(self, system: str, content: list[dict]) -> dict:
        if not self.model:
            self.model = self._request("GET", "/models")["data"][0]["id"]
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
            "temperature": 0,
            "max_tokens": 4096,
            "response_format": {"type": "json_object"},
            "chat_template_kwargs": {"enable_thinking": False},
        }
        try:
            response = self._request("POST", "/chat/completions", body)
        except HTTPError as exc:
            if exc.code != 400:
                raise
            exc.close()
            # Older vLLM servers may reject these structured-output options.
            body.pop("response_format")
            body.pop("chat_template_kwargs")
            response = self._request("POST", "/chat/completions", body)
        return _json_object(response["choices"][0]["message"]["content"] or "")

    async def _chat(self, system: str, content: list[dict]) -> dict:
        return await asyncio.wait_for(
            asyncio.to_thread(self._chat_sync, system, content), timeout=self.timeout
        )

    async def extract_attributes(self, photos: list[Photo], note: str) -> Extraction:
        content = []
        for photo in photos[: self.max_photos]:
            image = base64.standard_b64encode(photo.data).decode()
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{photo.media_type};base64,{image}"},
                }
            )
        content.append({"type": "text", "text": f"Finder's note: {note or '(none)'}"})
        try:
            return _clean_extraction(await self._chat(EXTRACT_SYSTEM + EXTRACT_HINT, content), note)
        except RESPONSE_ERRORS as exc:
            log.warning("Qwen extraction failed (%s); using mock", type(exc).__name__)
            return await self.mock.extract_attributes(photos, note)

    async def compare_texts(self, query: str, candidates: list[str]) -> list[float]:
        if not candidates:
            return []
        text = json.dumps({"lost": query, "found": candidates}, ensure_ascii=False)
        try:
            raw = await self._chat(COMPARE_SYSTEM + COMPARE_HINT, [{"type": "text", "text": text}])
            scores = [bounded_score(value) for value in raw["scores"]]
            if len(scores) != len(candidates):
                raise AIError("Qwen similarity count does not match candidates")
            return scores
        except RESPONSE_ERRORS as exc:
            log.warning("Qwen text comparison failed (%s); using mock", type(exc).__name__)
            return await self.mock.compare_texts(query, candidates)

    async def verify_details(
        self, attrs: list[DetailAttribute], evidence: list[str]
    ) -> DetailScores:
        if not attrs or not evidence:
            return {}
        try:
            content = [{"type": "text", "text": detail_input(attrs, evidence)}]
            raw = await self._chat(DETAIL_SYSTEM, content)
            return detail_scores(attrs, evidence, raw["scores"])
        except RESPONSE_ERRORS as exc:
            log.warning("Qwen detail comparison failed (%s); using mock", type(exc).__name__)
            return await self.mock.verify_details(attrs, evidence)
