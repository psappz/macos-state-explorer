# LaunchServices Outcome Engine

## Phase 1 lifecycle

Phase 1 intentionally separates the LaunchServices workflow into deterministic read-only and narrowly confirmed stages:

1. diagnosis: collect the current LaunchServices and Local Network evidence without mutation.
2. generation analysis: group Chromium-family registrations into product generations so active, obsolete, Trash, mounted-installer, updater, unknown, and system-adjacent evidence are visible separately.
3. planning: classify generations into safe plan-only candidates, manual-review candidates, active protected generations, and unknown blocked generations.
4. execution: when explicitly confirmed, execute only PLAN_ONLY_SAFE Chrome obsolete generations. No manual-review, active, unknown, installer, Trash, updater, Apple, system, or unrelated registrations are mutated.
5. validation: rebuild a fresh LaunchServices analysis after mutation and count remediation only when the planned generation is persistently removed.
6. outcome: explain the remaining state and whether safe automatic remediation has reached its limit.

## Why outcome is pure analysis

The Outcome Engine does not add repair actions, does not mutate LaunchServices, and does not change remediation planning. It consumes the generation analyzer and planner outputs, then assigns exactly one outcome state per generation:

- COMPLETED
- REMAINING_PLAN_SAFE
- MANUAL_REVIEW_REQUIRED
- BLOCKED_ACTIVE
- BLOCKED_UNKNOWN
- NOT_APPLICABLE

The resulting `LaunchServicesOutcome` is deterministic: IDs and timestamps are stable for regression tests and support-bundle comparison.

## History-aware outcome

`mse launchservices outcome --audit-log <jsonl>` incorporates confirmed `launchservices execute-plan` run-level audit records. Current PLAN_ONLY_SAFE generations are no longer reported as plainly eligible when history shows they were already attempted and did not persistently disappear. The outcome summary distinguishes `eligible_not_attempted`, `attempted_removed`, `attempted_no_persistent_change`, `attempted_unknown`, `manual_review_required`, and `blocked_active`, then reports automatic remediation as `AVAILABLE`, `EXHAUSTED`, `INCOMPLETE`, or `UNKNOWN`.

Audit history is analysis input only; it never triggers mutation.

## Manual-review terminal state

Manual-review generations intentionally terminate automatic execution. Trash generations, mounted installer generations, updater generations, active generations, and unknown registrations can still explain persistent Local Network evidence, but they are outside Phase 1's safe mutation contract. When no `REMAINING_PLAN_SAFE` generations remain, `automatic_remediation_complete` is true even if LaunchServices evidence is unchanged.

manual-review generations intentionally terminate automatic execution because Phase 1 has no safe deterministic mutation contract for them.

This is the expected terminal state for Phase 1: no additional safe automatic execution exists, and further progress requires manual review.
