# Local Network JSON contracts

This document defines the stable machine-readable contracts emitted by the Local Network commands when `--json` is used.

Default human-readable output is unchanged unless `--json` is explicitly passed.

## Compatibility policy

- Top-level keys are emitted in the documented order.
- Existing required keys are append-only: consumers may rely on them remaining present.
- New optional keys may be added after the required key sequence.
- Array order is deterministic and meaningful.
- Consumers should ignore unknown object keys for forwards compatibility.
- Commands remain read-only by default; JSON output never means a repair was executed.

## `mse solve local-network --json`

Required top-level keys, in order:

1. `command`
2. `diagnosis`
3. `evidence`
4. `matched_rules`
5. `repair_candidates`
6. `next_action`

### Evidence item contract

Each `evidence` item contains:

1. `id` — stable evidence ID, for example `LN-E001`.
2. `title` — short human-readable title.
3. `detail` — evidence detail string.
4. `source` — source subsystem, for example `tcc`, `launchservices`, or `trace`.
5. `present` — boolean.
6. `confidence` — number from `0.0` to `1.0`.
7. `provenance` — deterministic list of provenance labels.

Evidence is ordered by evidence ID.

### Matched rule contract

Each `matched_rules` item contains:

1. `id`
2. `diagnosis_id`
3. `matched_required_evidence`
4. `matched_optional_evidence`
5. `matched_conflicting_evidence`
6. `confidence_contribution`
7. `repair_recommendations`
8. `explanation`

### Repair candidate contract

Each repair candidate and `next_action` contains:

1. `id`
2. `title`
3. `risk`
4. `manual_action`
5. `expected_result`
6. `verification_command`
7. `fallback_branch`
8. `evidence_ids`

Examples:

- `docs/examples/local-network-json/solve-typical-diagnosis.json`
- `docs/examples/local-network-json/solve-trace-only-evidence.json`
- `docs/examples/local-network-json/solve-no-evidence.json`

## `mse verify local-network --json`

Required top-level keys, in order:

1. `command`
2. `status`
3. `branch_id`
4. `transition`
5. `expected_change`
6. `observed_result`
7. `current_diagnosis`
8. `evidence_ids`
9. `continues_workflow`
10. `next_repair_candidate`
11. `next_action`
12. `retry_guidance`
13. `fallback_guidance`

`status` is one of `SUCCESS`, `FAILED`, or `RETRY`.

`transition` is one of:

- `workflow-complete`
- `advance`
- `fallback-to-current-plan`
- `retry-current-branch`

`next_repair_candidate` is either `null` or a repair candidate object with the same shape documented for solve output.

`next_action` contains:

- `type` — the transition.
- `step` — concrete next-step text.
- `command` — command to run next, or `null` if no command applies.

Example:

- `docs/examples/local-network-json/verify-fallback.json`

## `mse trace local-network --json`

Required top-level keys, in order:

1. `command`
2. `out`
3. `analysis`
4. `signals`
5. `candidate_paths`
6. `next_action`

`analysis` contains, in order:

1. `created_at`
2. `keyword_hits`
3. `signal_counts`
4. `correlation_summary`
5. `timeline_events`

`signals` duplicates `analysis.correlation_summary` for support/UI consumers that need the primary signal list without parsing the larger analysis object.

`next_action` contains:

- `type`: `inspect-solve`
- `command`: `mse solve local-network --trace <out>`

Example:

- `docs/examples/local-network-json/trace-correlated-signals.json`

## Example scenarios

- Typical diagnosis: stale Chrome/Google LaunchServices evidence ranks manual Chrome reinstall first.
- Trace-only evidence: trace signals rank focused trace/trace inspection before manual app repair.
- Fallback verification: unknown or currently unranked branch falls back to the current evidence-ranked plan.
- No-evidence case: no repair is recommended; the next action is a focused trace.
