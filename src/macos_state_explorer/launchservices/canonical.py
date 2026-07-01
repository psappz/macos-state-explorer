from __future__ import annotations

from datetime import datetime

from macos_state_explorer.launchservices.grouping import BundleGroup
from macos_state_explorer.launchservices.models import LaunchServicesRecord, LaunchServicesStatus
from pydantic import BaseModel, Field


class PreferredRegistration(BaseModel):
    record: LaunchServicesRecord | None = None
    reason: str
    score: float = Field(ge=0)
    confidence: float = Field(ge=0, le=1)


def find_preferred_registration(group: BundleGroup) -> PreferredRegistration:
    if not group.records:
        return PreferredRegistration(
            reason="No LaunchServices records are available for this bundle.",
            score=0,
            confidence=0,
        )

    ranked_records = sorted(group.records, key=_ranking_key, reverse=True)
    preferred = ranked_records[0]
    score = _score_record(preferred)
    confidence = _confidence(preferred, ranked_records[1:])
    return PreferredRegistration(
        record=preferred,
        reason=_reason(preferred),
        score=score,
        confidence=confidence,
    )


def _ranking_key(record: LaunchServicesRecord) -> tuple[int, datetime, int, int, tuple[tuple[int, int, str], ...]]:
    return (
        record.sequence_number if record.sequence_number is not None else -1,
        _parse_registration_date(record.registration_date),
        1 if record.path_exists is True else 0,
        1 if record.classification == LaunchServicesStatus.ACTIVE else 0,
        _version_key(record.version),
    )


def _score_record(record: LaunchServicesRecord) -> float:
    score = 0.0
    if record.sequence_number is not None:
        score += 1
    if record.registration_date:
        score += 1
    if record.path_exists is True:
        score += 1
    if record.classification == LaunchServicesStatus.ACTIVE:
        score += 1
    if record.version:
        score += 1
    return score


def _confidence(preferred: LaunchServicesRecord, others: list[LaunchServicesRecord]) -> float:
    if not others:
        return 1.0

    preferred_key = _ranking_key(preferred)
    if any(_ranking_key(record) == preferred_key for record in others):
        return 0.5

    preferred_score = _score_record(preferred)
    next_score = max(_score_record(record) for record in others)
    return max(0.55, min(1.0, 0.6 + ((preferred_score - next_score) * 0.1)))


def _reason(record: LaunchServicesRecord) -> str:
    reasons: list[str] = []
    if record.sequence_number is not None:
        reasons.append(f"highest sequence number candidate: {record.sequence_number}")
    if record.registration_date:
        reasons.append(f"registration date: {record.registration_date}")
    if record.path_exists is True:
        reasons.append("path exists")
    elif record.path_exists is False:
        reasons.append("path is missing")
    if record.classification == LaunchServicesStatus.ACTIVE:
        reasons.append(f"status is {LaunchServicesStatus.ACTIVE.value}")
    else:
        reasons.append(f"status is {record.classification.value}")
    if record.version:
        reasons.append(f"version: {record.version}")
    return "; ".join(reasons) or "Selected by stable input order; no ranking signals were present."


def _parse_registration_date(value: str | None) -> datetime:
    if not value:
        return datetime.min

    for date_format in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(value, date_format)
            return parsed.replace(tzinfo=None)
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(value).replace(tzinfo=None)
    except ValueError:
        return datetime.min


def _version_key(value: str | None) -> tuple[tuple[int, int, str], ...]:
    if not value:
        return ()

    parts: list[tuple[int, int, str]] = []
    for part in value.replace("-", ".").split("."):
        if part.isdecimal():
            parts.append((1, int(part), ""))
        else:
            parts.append((0, 0, part))
    return tuple(parts)
