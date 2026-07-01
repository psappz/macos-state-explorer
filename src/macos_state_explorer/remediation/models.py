from __future__ import annotations

from pydantic import BaseModel, Field


class RemediationAction(BaseModel):
    id: str
    title: str
    description: str
    risk: str
    mode: str
    commands: list[str] = Field(default_factory=list)
    requires_confirmation: bool
    evidence_ids: list[str] = Field(default_factory=list)


class RemediationPlan(BaseModel):
    title: str
    summary: str
    actions: list[RemediationAction] = Field(default_factory=list)
