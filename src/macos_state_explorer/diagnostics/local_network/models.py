from __future__ import annotations

from pydantic import BaseModel, Field


class HistoricalEvidenceSummary(BaseModel):
    launchservices_stale_count: int = 0
    tcc_missing_localnetwork_rows: bool = False


class CurrentFunctionalState(BaseModel):
    status: str = "UNKNOWN"
    local_network_ui: str = "unknown"
    chrome_entry_count: int | None = None
    permission_enabled: bool | None = None
    communication: str = "unknown"
    networkextension: str = "unknown"


class ConfidenceScores(BaseModel):
    historical_confidence: float = Field(default=0.0, ge=0, le=1)
    failure_confidence: float = Field(default=0.0, ge=0, le=1)


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
    historical_evidence: HistoricalEvidenceSummary = Field(default_factory=HistoricalEvidenceSummary)
    functional_state: CurrentFunctionalState = Field(default_factory=CurrentFunctionalState)
    current_risk: str = "UNKNOWN"
    diagnosis_state: str = "UNKNOWN"
    confidence_scores: ConfidenceScores = Field(default_factory=ConfidenceScores)
    conclusion: str = ""
