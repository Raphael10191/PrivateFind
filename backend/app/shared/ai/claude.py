"""Claude API provider: photo attribute extraction and text similarity (D5: no embeddings)."""

import base64
from typing import get_args

import anthropic
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.shared.ai.provider import AIError, Photo
from app.shared.ai.schemas import Extraction
from app.shared.vocab import Category, Color, EvidenceType

EXTRACT_SYSTEM = f"""You help a campus lost-and-found service catalogue items handed in by finders.
From the photos and the finder's note, describe the item as structured data.

Rules:
- category must be one of: {", ".join(get_args(Category))}.
- color must be one of: {", ".join(get_args(Color))} (map shades, e.g. navy -> blue), or null.
- public_summary: one short sentence with only category, colour and brand. It is shown publicly,
  so never include serial numbers, names, stickers, damage, contents or other identifying details.
- description: a complete factual description including identifying details (kept private).
- private_attributes: identifying details an owner could confirm, typed as one of:
  {", ".join(get_args(EvidenceType))}. strength: strong = unique identifier (serial number,
  engraved name), distinctive = unusual but not unique (sticker, damage), generic = common feature.
  For serial numbers store only the last 4 characters as the value.
- Only report what is visible or stated; do not guess. Lower confidence when unsure."""

COMPARE_SYSTEM = """You compare short descriptions of lost-and-found items.
For each candidate, return how likely it describes the same specific thing as the query,
from 0 (unrelated) to 1 (clearly the same), allowing for different wording and synonyms."""


class _Similarities(BaseModel):
    scores: list[float] = Field(description="One score per candidate, in the given order")


class ClaudeProvider:
    def __init__(self, client: anthropic.AsyncAnthropic | None = None):
        # Credentials come from the environment (ANTHROPIC_API_KEY); never hard-coded.
        self.client = client or anthropic.AsyncAnthropic()
        self.model = get_settings().claude_model

    async def _parse(self, system: str, content: list[dict], schema: type[BaseModel]):
        try:
            response = await self.client.messages.parse(
                model=self.model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": content}],
                output_format=schema,
            )
        except anthropic.APIError as exc:  # network, rate limit, server errors -> caller retries
            raise AIError(f"Claude API error: {exc.__class__.__name__}") from exc
        if response.stop_reason == "refusal":
            raise AIError("Claude declined the request")
        if response.parsed_output is None:
            raise AIError(f"No structured output (stop_reason={response.stop_reason})")
        return response.parsed_output

    async def extract_attributes(self, photos: list[Photo], note: str) -> Extraction:
        content: list[dict] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": p.media_type,
                    "data": base64.standard_b64encode(p.data).decode(),
                },
            }
            for p in photos
        ]
        content.append({"type": "text", "text": f"Finder's note: {note or '(none)'}"})
        return await self._parse(EXTRACT_SYSTEM, content, Extraction)

    async def compare_texts(self, query: str, candidates: list[str]) -> list[float]:
        if not candidates:
            return []
        listing = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(candidates))
        text = f"Query: {query}\n\nCandidates:\n{listing}"
        result = await self._parse(COMPARE_SYSTEM, [{"type": "text", "text": text}], _Similarities)
        if len(result.scores) != len(candidates):
            raise AIError("Similarity count does not match candidates")
        return [max(0.0, min(1.0, s)) for s in result.scores]
