from __future__ import annotations

from pydantic import BaseModel, Field


class DiagnosticFinding(BaseModel):
    id: str
    title: str
    summary: str
    severity: str
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)


class DiagnosticStep(BaseModel):
    id: str
    title: str
    description: str
    risk: str
    mode: str
    commands: list[str] = Field(default_factory=list)
    expected_result: str


class VerificationStep(BaseModel):
    title: str
    command: str
    expected_result: str


class LocalNetworkDiagnosis(BaseModel):
    diagnosis: str
    confidence: float = Field(ge=0, le=1)
    most_likely_cause: str
    evidence: list[DiagnosticFinding] = Field(default_factory=list)
    recommended_next_action: DiagnosticStep
    risk: str
    expected_result: str
    verification: VerificationStep
    fallback_path: list[DiagnosticStep] = Field(default_factory=list)
