from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MOCK_REPORTING_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "PrivateFind"
    database_url: str = "mysql+asyncmy://privatefind:privatefind@localhost:3306/privatefind"
    secret_key: str = "change-me"  # signs session cookies and hashes codes/device keys
    session_max_age_s: int = 7 * 24 * 3600

    storage_dir: Path = Path("storage/photos")
    max_photo_bytes: int = 5 * 1024 * 1024
    max_photos: int = 3

    ai_provider: Literal["mock", "claude", "qwen"] = "mock"
    # Explicit local reporting sandbox. Never grants real-AI or hardware readiness.
    app_env: Literal["production", "development", "test"] = "production"
    allow_mock_ai_reports: bool = False
    claude_model: str = "claude-opus-5-5"
    qwen_base_url: str = ""
    qwen_api_key: SecretStr = SecretStr("")
    qwen_model: str = ""
    qwen_timeout: float = Field(default=25, gt=0)
    qwen_log_analysis: bool = False
    ai_max_attempts: int = 3
    ai_retry_base_delay_s: float = 1.0  # backoff: 1s, 4s, 16s

    deposit_code_ttl_min: int = 15
    pickup_code_ttl_h: int = 48

    max_failed_claims: int = 3
    claim_cooldown_h: int = 24

    locations: list[str] = [
        "library",
        "student_center",
        "engineering_building",
        "lecture_hall",
        "cafeteria",
        "gym",
        "dormitory",
        "outdoor",
        "other",
    ]

    @model_validator(mode="after")
    def validate_mock_reporting(self) -> Self:
        if self.allow_mock_ai_reports:
            if self.app_env != "development":
                raise ValueError("ALLOW_MOCK_AI_REPORTS requires APP_ENV=development")
            if self.ai_provider != "mock":
                raise ValueError("ALLOW_MOCK_AI_REPORTS requires AI_PROVIDER=mock")
            if self.database_url != MOCK_REPORTING_DATABASE_URL:
                raise ValueError(
                    "ALLOW_MOCK_AI_REPORTS requires the dedicated in-memory test database: "
                    + MOCK_REPORTING_DATABASE_URL
                )
        return self

    @property
    def mock_reporting_enabled(self) -> bool:
        return (
            self.allow_mock_ai_reports
            and self.app_env == "development"
            and self.ai_provider == "mock"
            and self.database_url == MOCK_REPORTING_DATABASE_URL
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
