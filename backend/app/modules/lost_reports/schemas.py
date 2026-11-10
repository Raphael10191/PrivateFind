from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.shared.vocab import Category, Color


class LostReportIn(BaseModel):
    category: Category
    location: str = Field(max_length=50)
    lost_at: datetime
    color: Color | None = None
    brand: str | None = Field(default=None, max_length=50)
    model: str | None = Field(default=None, max_length=100)
    description: str = Field(min_length=3, max_length=1000)


class LostReportOut(LostReportIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    created_at: datetime
