from dataclasses import dataclass
from typing import Protocol

from app.core.config import get_settings
from app.shared.ai.schemas import Extraction


@dataclass
class Photo:
    data: bytes
    media_type: str = "image/jpeg"


class AIError(Exception):
    """The AI call failed or returned unusable output (retried by the caller)."""


class AIProvider(Protocol):
    async def extract_attributes(self, photos: list[Photo], note: str) -> Extraction: ...

    async def compare_texts(self, query: str, candidates: list[str]) -> list[float]:
        """Semantic similarity of `query` to each candidate, 0..1, same order."""
        ...


_override: AIProvider | None = None


def get_ai_provider() -> AIProvider:
    if _override is not None:
        return _override
    if get_settings().ai_provider == "claude":
        from app.shared.ai.claude import ClaudeProvider

        return ClaudeProvider()
    from app.shared.ai.mock import MockAIProvider

    return MockAIProvider()


def set_ai_provider(provider: AIProvider | None) -> None:
    """Swap the provider (tests, or a failing provider to test retries)."""
    global _override
    _override = provider
