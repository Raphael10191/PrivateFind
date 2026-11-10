from pydantic import BaseModel, Field

from app.shared.vocab import Category, Color, EvidenceType, Strength


class PrivateAttribute(BaseModel):
    type: EvidenceType
    value: str = Field(description="Short factual value, e.g. '4821' or 'cat sticker on back'")
    strength: Strength = Field(description="strong = unique identifier, distinctive, generic")
    confidence: float = Field(ge=0, le=1)


class Extraction(BaseModel):
    """AI output for one found item (WBS 4.3). Validated before anything is stored."""

    category: Category
    color: Color | None = None
    brand: str | None = None
    public_summary: str = Field(
        description="One short sentence safe to show publicly: category, colour, brand only."
    )
    description: str = Field(description="Full private description used for matching.")
    private_attributes: list[PrivateAttribute] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
