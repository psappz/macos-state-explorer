from __future__ import annotations

from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    id: str
    title: str
    summary: str
    source: str
    severity: str
    confidence: float = Field(ge=0, le=1)
    data: dict[str, object] = Field(default_factory=dict)


class EvidenceSet(BaseModel):
    items: list[EvidenceItem] = Field(default_factory=list)
