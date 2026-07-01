from __future__ import annotations

from time import time
from uuid import uuid4
from typing import Any
from pydantic import BaseModel, Field


class Evidence(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    source: str
    detail: str
    confidence: float = Field(default=1.0, ge=0, le=1)
    timestamp: float = Field(default_factory=time)
    raw: dict[str, Any] = Field(default_factory=dict)


class Observation(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    collector: str
    started_at: float
    ended_at: float
    payload: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class Hypothesis(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    confidence: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


class Snapshot(BaseModel):
    schema_version: int = 1
    created_at: float = Field(default_factory=time)
    host: str
    observations: list[Observation] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
