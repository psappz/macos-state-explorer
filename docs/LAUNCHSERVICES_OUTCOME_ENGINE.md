# LaunchServices Outcome Engine

## Phase 1 lifecycle

Phase 1 intentionally separates the LaunchServices workflow into deterministic read-only and narrowly confirmed stages:

1. diagnosis: collect the current LaunchServices and Local Network evidence without mutation.
2. generation analysis: group Chromium-family registrations into application generations so active, obsolete, Trash, mounted-installer, updater, unknown, and system-adjacent evidence are visible separately.
3. planning: classify generations into safe plan-only candidates, manual-review candidates, active protected generations, and unknown blocked generations.
4. execution: when explicitly confirmed, execute only PLAN_ONLY_SAFE Chrome obsolete generations. No manual-review, active, unknown, installer, Trash, updater, Apple, system, or unrelated registrations are mutated.
5. validation: rebuild a fresh LaunchServices analysis after mutation and count remediation only when the planned generation is persistently removed.
6. outcome: explain the remaining state and whether safe automatic remediation has reached its limit.
7. registration provenance: explain who likely produced each relevant registration, why it persists, what may regenerate it, and which consumers can use it.
8. producer evidence: acquire observed producer/consumer signals separately from modeled provenance before any further repair milestone is considered.
9. trace correlation: distinguish isolated observations from events that share a supported time-window/process context.
10. high-fidelity trace acquisition: normalize timestamp, process, PID, thread, executable, subsystem, source, path, operation, confidence, and raw reference fields for descriptive timelines.
11. regeneration analysis: classify evidence about which observed or correlated source recreates LaunchServices registrations after removal.
12. cleanup checklist: produce a read-only, deterministic manual execution checklist for remaining non-automatic sources.

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

`mse launchservices outcome --audit-log <jsonl>` incorporates confirmed `launchservices execute-plan` audit records. `--audit-log` may be repeated; JSONL records are aggregated in the provided order.

The reader accepts current run-level `launchservices_execute_plan_run` records and legacy per-generation `launchservices_execute_plan_generation` records. Legacy generation records map `verification.generation_removed: true` to `attempted_removed`, `verification.generation_removed: false` to `attempted_no_persistent_change`, and records with errors to an unknown/failed attempted state.

Current snapshot state wins over history: if a generation is present now but prior audit history says it was removed, the outcome reports `attempted_but_present_again` rather than `eligible_not_attempted`.

Current PLAN_ONLY_SAFE generations are no longer reported as plainly eligible when history shows they were already attempted and did not persistently disappear. The outcome summary distinguishes `eligible_not_attempted`, `attempted_removed`, `attempted_no_persistent_change`, `attempted_unknown`, `attempted_but_present_again`, `manual_review_required`, and `blocked_active`, then reports automatic remediation as `AVAILABLE`, `EXHAUSTED`, `INCOMPLETE`, or `UNKNOWN`.

Audit history is analysis input only; it never triggers mutation. Audit-informed outcome is propagated into Local Network summaries and support bundles when `--audit-log` is provided, including `mse report local-network --bundle --audit-log <jsonl>`.

## Registration Provenance Engine

Phase 2 moves from repair to provenance. The Registration Provenance Engine is pure analysis: it does not mutate LaunchServices, does not add repair functionality, and does not change planner behavior. For each relevant registration it records registration identity, application family, generation, path, producer, producer confidence, producer reasoning, persistence source, regeneration source, consumer set, confidence, and evidence.

The model only reports what available evidence supports. Unknown producers, persistence sources, or regeneration sources remain `Unknown`/`unknown` with low confidence rather than speculative labels. Provenance output is available through `mse launchservices provenance`, Local Network summaries, support bundles as `provenance.json` and `provenance.txt`, and support-bundle provenance diff.

## LaunchServices Producer Evidence investigation

Phase 2 is investigation-driven and keeps the Chrome Local Network reference case as the highest priority. `mse launchservices producer-evidence` is a pure-analysis command that answers what evidence supports current provenance claims without mutation, repair actions, planner changes, or execution changes.

Modeled provenance must be separated from observed producer evidence, observed consumer evidence, inferred persistence mechanism, and unknown signals. Snapshot signals such as lsregister dump paths, bundle identifiers, missing paths, Trash paths, mounted-volume paths, updater paths, active application paths, and `.csstore` candidate files are reported as observed evidence. Trace-backed signals such as SecurityPrivacyExtension `.csstore` reads, System Settings Privacy UI activity, and RunningBoard activity are observed only when a trace is supplied. SecurityPrivacyExtension plus `.csstore` access in the same trace window/process context is reported as observed consumer evidence, not merely modeled provenance. Without a trace, those signals are explicitly reported as unknown rather than implied.

The repository remains `macos-state-explorer`; WASP Prism is the future public project identity.

## Trace Correlation Evidence investigation

`mse trace correlate <trace-dir>` is pure analysis that asks whether observed trace events can be correlated, not just whether they happened. It preserves three layers: observed signals, supported correlations, and cautious inferences. Two observations are never promoted to a correlation unless the trace supplies supporting evidence such as a shared process and same time window.

Trace correlation is used by Local Network summaries and support bundles as `trace-correlation.json` and `trace-correlation.txt`, with bundle diff support for added, removed, or changed correlations. This investigation remains scoped to the Chrome Local Network reference case and does not add repair, planner, mutation, or new Diagnostic Engine behavior.

## High-Fidelity Trace Acquisition investigation

`mse trace timeline <trace-dir>` is descriptive evidence acquisition. It normalizes existing trace artifacts into a deterministic timeline schema with timestamp, process, PID, parent PID, thread ID, executable path, subsystem, source, file path, operation, signal, confidence, and raw reference fields where the source supports them.

The timeline does not change diagnosis, repair ranking, planner behavior, or mutation scope. Its purpose is to provide higher-resolution evidence for later temporal/process correlation attempts. Local Network summaries include a compact timeline summary, support bundles include `trace-timeline.json` and `trace-timeline.txt`, and bundle diff reports Trace Timeline Diff.

## Regeneration Analysis Engine

`mse launchservices regeneration` is pure analysis that asks who or what appears to recreate LaunchServices registrations after removal. It consumes LaunchServices generations, audit history, producer/provenance context, high-fidelity trace timelines, and trace correlation evidence when available.

Every claim is categorized as `Observed`, `Correlated`, `Inferred`, or `Unknown`. Only Observed and Correlated evidence may drive high confidence. Unknown evidence remains explicit and low-confidence; the engine must not invent a PID, process, regenerator, or repair action.

The Regeneration Analysis Engine does not mutate LaunchServices, does not add repair functionality, does not change planner behavior, does not change solver behavior, and does not change diagnosis. Local Network reports include a compact regeneration summary, support bundles include `regeneration.json` and `regeneration.txt`, and bundle diff reports Regeneration Diff.

## Cleanup Checklist manual safety bridge

`mse launchservices cleanup-checklist` is pure read-only guidance for the Chrome Local Network reference case. It turns the remaining non-automatic LaunchServices sources into deterministic manual checklist items without adding deletion, unregister, eject, reset, planner execution, solver, repair, or diagnosis behavior.

Checklist items are separated into Trash registrations, mounted installer registrations, updater registrations, and unknown-regenerator Chrome application generations. Each item includes generation identity, producer, regenerator if known, confidence, classification, paths, registration identifiers, why automatic cleanup is not recommended, exact manual action, verification command, and expected post-condition.

The command is conservative by design: Trash cleanup requires Finder inspection and disposal judgment; mounted installers require manual eject/reboot or System Settings relaunch; updater-owned paths require manual review or vendor updater cleanup; unknown Chrome application generations recommend manual Chrome reinstall only after Trash and mounted installer branches are cleared. Local Network reports include a compact cleanup checklist summary, support bundles include `cleanup-checklist.json` and `cleanup-checklist.txt`, and bundle diff reports Cleanup Checklist Diff.

## Manual-review terminal state

Manual-review generations intentionally terminate automatic execution. Trash generations, mounted installer generations, updater generations, active generations, and unknown registrations can still explain persistent Local Network evidence, but they are outside Phase 1's safe mutation contract. When no `REMAINING_PLAN_SAFE` generations remain, `automatic_remediation_complete` is true even if LaunchServices evidence is unchanged.

manual-review generations intentionally terminate automatic execution because Phase 1 has no safe deterministic mutation contract for them.

This is the expected terminal state for Phase 1: no additional safe automatic execution exists, and further progress requires manual review.
