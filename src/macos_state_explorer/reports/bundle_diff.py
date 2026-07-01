from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BundleDiffItem:
    id: str
    title: str | None = None
    detail: str | None = None
    present: bool | None = None
    source: str | None = None
    confidence: float | None = None
    diagnosis_id: str | None = None
    explanation: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"id": self.id}
        if self.title is not None:
            payload["title"] = self.title
        if self.detail is not None:
            payload["detail"] = self.detail
        if self.present is not None:
            payload["present"] = self.present
        if self.source is not None:
            payload["source"] = self.source
        if self.confidence is not None:
            payload["confidence"] = self.confidence
        if self.diagnosis_id is not None:
            payload["diagnosis_id"] = self.diagnosis_id
        if self.explanation is not None:
            payload["explanation"] = self.explanation
        return payload


@dataclass(frozen=True)
class BundleDiffResult:
    before_path: Path
    after_path: Path
    resolved_diagnoses: tuple[BundleDiffItem, ...]
    remaining_diagnoses: tuple[BundleDiffItem, ...]
    new_diagnoses: tuple[BundleDiffItem, ...]
    removed_evidence: tuple[BundleDiffItem, ...]
    remaining_evidence: tuple[BundleDiffItem, ...]
    new_evidence: tuple[BundleDiffItem, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "command": "diff bundles",
            "schema_version": 1,
            "before": {"path": str(self.before_path)},
            "after": {"path": str(self.after_path)},
            "summary": {
                "status": self.status,
                "resolved_diagnosis_count": len(self.resolved_diagnoses),
                "remaining_diagnosis_count": len(self.remaining_diagnoses),
                "new_diagnosis_count": len(self.new_diagnoses),
                "removed_evidence_count": len(self.removed_evidence),
                "remaining_evidence_count": len(self.remaining_evidence),
                "new_evidence_count": len(self.new_evidence),
            },
            "diagnoses": {
                "resolved": [item.to_json_dict() for item in self.resolved_diagnoses],
                "remaining": [item.to_json_dict() for item in self.remaining_diagnoses],
                "new": [item.to_json_dict() for item in self.new_diagnoses],
            },
            "evidence": {
                "removed": [item.to_json_dict() for item in self.removed_evidence],
                "remaining": [item.to_json_dict() for item in self.remaining_evidence],
                "new": [item.to_json_dict() for item in self.new_evidence],
            },
        }

    @property
    def status(self) -> str:
        has_improvement = bool(self.resolved_diagnoses or self.removed_evidence)
        has_regression = bool(self.new_diagnoses or self.new_evidence)
        if has_improvement and has_regression:
            return "mixed"
        if has_improvement:
            return "improved"
        if has_regression:
            return "regressed"
        return "unchanged"

    def render_text(self) -> str:
        lines = [
            "Bundle comparison",
            f"- Before: {self.before_path}",
            f"- After: {self.after_path}",
            f"- Status: {self.status}",
            "",
            "Summary",
            f"- Resolved diagnoses: {len(self.resolved_diagnoses)}",
            f"- Remaining diagnoses: {len(self.remaining_diagnoses)}",
            f"- New diagnoses: {len(self.new_diagnoses)}",
            f"- Removed evidence: {len(self.removed_evidence)}",
            f"- Remaining evidence: {len(self.remaining_evidence)}",
            f"- New evidence: {len(self.new_evidence)}",
        ]
        lines.extend(_render_item_section("Resolved diagnoses", self.resolved_diagnoses))
        lines.extend(_render_item_section("Remaining diagnoses", self.remaining_diagnoses))
        lines.extend(_render_item_section("New diagnoses", self.new_diagnoses))
        lines.extend(_render_item_section("Removed evidence", self.removed_evidence))
        lines.extend(_render_item_section("Remaining evidence", self.remaining_evidence))
        lines.extend(_render_item_section("New evidence", self.new_evidence))
        return "\n".join(lines)


def compare_support_bundles(before_path: Path, after_path: Path) -> BundleDiffResult:
    before_path = before_path.expanduser()
    after_path = after_path.expanduser()
    before_report = _load_report_json(before_path)
    after_report = _load_report_json(after_path)

    before_diagnoses = _diagnosis_items(before_report)
    after_diagnoses = _diagnosis_items(after_report)
    before_evidence = _present_evidence_items(before_report)
    after_evidence = _present_evidence_items(after_report)

    return BundleDiffResult(
        before_path=before_path,
        after_path=after_path,
        resolved_diagnoses=tuple(_items_in_left_only(before_diagnoses, after_diagnoses)),
        remaining_diagnoses=tuple(_items_in_both(before_diagnoses, after_diagnoses)),
        new_diagnoses=tuple(_items_in_left_only(after_diagnoses, before_diagnoses)),
        removed_evidence=tuple(_items_in_left_only(before_evidence, after_evidence)),
        remaining_evidence=tuple(_items_in_both(before_evidence, after_evidence)),
        new_evidence=tuple(_items_in_left_only(after_evidence, before_evidence)),
    )


def _load_report_json(bundle_path: Path) -> dict[str, Any]:
    report_path = bundle_path / "report.json"
    if not report_path.is_file():
        raise ValueError(f"Missing report.json in bundle: {bundle_path}")
    try:
        payload = json.loads(report_path.read_text())
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid report.json in bundle: {bundle_path}: {error.msg}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid report.json in bundle: {bundle_path}: expected object")
    return payload


def _diagnosis_items(report: dict[str, Any]) -> dict[str, BundleDiffItem]:
    rules = report.get("matched_rules", [])
    if not isinstance(rules, list):
        return {}
    items: dict[str, BundleDiffItem] = {}
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        rule_id = rule.get("id")
        if not isinstance(rule_id, str) or not rule_id:
            continue
        if rule_id in items:
            continue
        diagnosis_id = rule.get("diagnosis_id")
        explanation = rule.get("explanation")
        items[rule_id] = BundleDiffItem(
            id=rule_id,
            diagnosis_id=diagnosis_id if isinstance(diagnosis_id, str) else None,
            explanation=explanation if isinstance(explanation, str) else None,
        )
    return items


def _present_evidence_items(report: dict[str, Any]) -> dict[str, BundleDiffItem]:
    evidence = report.get("evidence", [])
    if not isinstance(evidence, list):
        return {}
    items: dict[str, BundleDiffItem] = {}
    for entry in evidence:
        if not isinstance(entry, dict) or entry.get("present") is not True:
            continue
        evidence_id = entry.get("id")
        if not isinstance(evidence_id, str) or not evidence_id:
            continue
        if evidence_id in items:
            continue
        confidence = entry.get("confidence")
        items[evidence_id] = BundleDiffItem(
            id=evidence_id,
            title=entry.get("title") if isinstance(entry.get("title"), str) else None,
            detail=entry.get("detail") if isinstance(entry.get("detail"), str) else None,
            present=True,
            source=entry.get("source") if isinstance(entry.get("source"), str) else None,
            confidence=confidence if isinstance(confidence, int | float) else None,
        )
    return items


def _items_in_left_only(
    left: dict[str, BundleDiffItem],
    right: dict[str, BundleDiffItem],
) -> list[BundleDiffItem]:
    return [left[item_id] for item_id in sorted(left) if item_id not in right]


def _items_in_both(
    left: dict[str, BundleDiffItem],
    right: dict[str, BundleDiffItem],
) -> list[BundleDiffItem]:
    return [left[item_id] for item_id in sorted(left) if item_id in right]


def _render_item_section(title: str, items: tuple[BundleDiffItem, ...]) -> list[str]:
    lines = ["", title]
    if not items:
        lines.append("- none")
        return lines
    for item in items:
        suffix = f" — {item.title}" if item.title else ""
        lines.append(f"- {item.id}{suffix}")
    return lines
