from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.shared.vocab import Category, Color, category_key


class LostReportFields(BaseModel):
    category: Category = "other"
    location: str = Field(default="other", max_length=50)
    lost_at: datetime | None = None
    color: Color | None = None
    brand: str | None = Field(default=None, max_length=50)
    model: str | None = Field(default=None, max_length=100)
    material: str | None = Field(default=None, max_length=50)
    unique_marks: str | None = Field(default=None, max_length=1000)


class LostReportIn(LostReportFields):
    description: str = Field(min_length=3, max_length=1000)

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, value):
        return category_key(value) if isinstance(value, str) else value


class LostReportOut(LostReportFields):
    model_config = ConfigDict(from_attributes=True)

    id: int
    description: str | None
    status: str
    created_at: datetime
