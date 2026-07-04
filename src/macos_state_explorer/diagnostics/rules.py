from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Protocol, Sequence


class DiagnosticEvidence(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def present(self) -> bool: ...


@dataclass(frozen=True)
class DiagnosticRule:
    id: str
    diagnosis_id: str
    required_evidence: tuple[str, ...] = ()
    optional_evidence: tuple[str, ...] = ()
    conflicting_evidence: tuple[str, ...] = ()
    confidence: float = 0.0
    repair_recommendations: tuple[str, ...] = ()
    explanation: str = ""
    priority: int = 100


@dataclass(frozen=True)
class RuleMatch:
    rule_id: str
    diagnosis_id: str
    matched_required_evidence: tuple[str, ...]
    matched_optional_evidence: tuple[str, ...]
    matched_conflicting_evidence: tuple[str, ...]
    confidence_contribution: float
    repair_recommendations: tuple[str, ...]
    explanation: str

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        ordered: list[str] = []
        for evidence_id in (*self.matched_required_evidence, *self.matched_optional_evidence):
            if evidence_id not in ordered:
                ordered.append(evidence_id)
        return tuple(ordered)


@dataclass(frozen=True)
class DiagnosisAggregate:
    diagnosis_id: str
    matches: tuple[RuleMatch, ...]
    confidence: float
    repair_recommendations: tuple[str, ...]
    evidence_ids: tuple[str, ...]


class RuleEngine:
    def __init__(self, rules: Sequence[DiagnosticRule]) -> None:
        self._rules = tuple(sorted(rules, key=lambda rule: (rule.priority, rule.id)))

    def evaluate(self, evidence: Sequence[DiagnosticEvidence]) -> list[RuleMatch]:
        present_ids = {item.id for item in evidence if item.present}
        matches: list[RuleMatch] = []
        for rule in self._rules:
            required = tuple(item for item in rule.required_evidence if item in present_ids)
            missing_required = set(rule.required_evidence) - present_ids
            conflicting = tuple(item for item in rule.conflicting_evidence if item in present_ids)
            if missing_required or conflicting:
                continue
            optional = tuple(item for item in rule.optional_evidence if item in present_ids)
            matches.append(
                RuleMatch(
                    rule_id=rule.id,
                    diagnosis_id=rule.diagnosis_id,
                    matched_required_evidence=required,
                    matched_optional_evidence=optional,
                    matched_conflicting_evidence=conflicting,
                    confidence_contribution=rule.confidence,
                    repair_recommendations=rule.repair_recommendations,
                    explanation=rule.explanation,
                )
            )
        return matches

    def diagnose(self, evidence: Sequence[DiagnosticEvidence]) -> OrderedDict[str, DiagnosisAggregate]:
        grouped: OrderedDict[str, list[RuleMatch]] = OrderedDict()
        for match in self.evaluate(evidence):
            grouped.setdefault(match.diagnosis_id, []).append(match)

        diagnoses: OrderedDict[str, DiagnosisAggregate] = OrderedDict()
        for diagnosis_id, matches in grouped.items():
            repairs: list[str] = []
            evidence_ids: list[str] = []
            for match in matches:
                for repair in match.repair_recommendations:
                    if repair not in repairs:
                        repairs.append(repair)
                for evidence_id in match.evidence_ids:
                    if evidence_id not in evidence_ids:
                        evidence_ids.append(evidence_id)
            diagnoses[diagnosis_id] = DiagnosisAggregate(
                diagnosis_id=diagnosis_id,
                matches=tuple(matches),
                confidence=round(min(0.99, sum(match.confidence_contribution for match in matches)), 2),
                repair_recommendations=tuple(repairs),
                evidence_ids=tuple(evidence_ids),
            )
        return diagnoses
