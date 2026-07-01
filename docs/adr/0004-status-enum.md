# 0004 Status Enum

## Context

LaunchServices classification status is used by parsing, grouping, reports, canonical registration analysis, and tests. Raw string statuses are easy to mistype and make it harder to know which states are supported.

## Decision

Use `LaunchServicesStatus(StrEnum)` as the canonical representation for LaunchServices statuses. The enum defines:

- `ACTIVE`
- `STALE`
- `ORPHANED`
- `MISSING_VOLUME`
- `DUPLICATE`
- `SHADOWED`
- `SUPERSEDED`
- `BROKEN`
- `UNKNOWN`

Project code should compare enum members rather than raw strings. String literals for statuses should only appear in the enum definition.

## Consequences

Status handling is type-safe and discoverable. JSON compatibility is preserved because `StrEnum` serializes as the existing status strings. Adding new status states requires an explicit enum change and corresponding test coverage.
