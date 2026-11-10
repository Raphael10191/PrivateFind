from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "PrivateFind"
    database_url: str = "mysql+asyncmy://privatefind:privatefind@localhost:3306/privatefind"
    secret_key: str = "change-me"  # signs session cookies and hashes codes/device keys
    session_max_age_s: int = 7 * 24 * 3600

    storage_dir: Path = Path("storage/photos")
    max_photo_bytes: int = 5 * 1024 * 1024
    max_photos: int = 3

    ai_provider: str = "mock"  # "mock" | "claude"
    claude_model: str = "claude-opus-5-5"
    ai_max_attempts: int = 3
    ai_retry_base_delay_s: float = 1.0  # backoff: 1s, 4s, 16s

    deposit_code_ttl_min: int = 15
    pickup_code_ttl_h: int = 48

    match_threshold: int = 60
    max_candidates: int = 3

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
