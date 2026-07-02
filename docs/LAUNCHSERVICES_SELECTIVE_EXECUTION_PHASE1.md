# LaunchServices selective execution — Phase 1

Phase 1 is the first milestone that may mutate LaunchServices state. Execution is intentionally narrower than the planner.

## Executable scope

`mse launchservices execute-plan --confirm` executes only remediation steps that are all of the following:

- safety classification: `PLAN_ONLY_SAFE`
- product family: `Google Chrome`
- action: `plan_unregister_obsolete_generation`
- generation still exists at execution time
- generation is still obsolete/stale
- generation is not active
- registration count and target registration paths still match the plan

The mutation is minimal and deterministic: each target registration path is passed to the system `lsregister -u <path>` command. The command does not rebuild the entire LaunchServices database after every step.

## Blocked in Phase 1

The following generations remain `NOT_EXECUTED` even when present in the plan:

- mounted or nonexistent installer volume generations under `/Volumes/...`
- Trash generations
- GoogleUpdater generations
- EdgeUpdater generations
- active Chrome generations
- active Edge generations
- unknown generations
- Apple/system registrations
- any non-Chrome product-family step

Manual-review candidates must be reviewed and promoted by a later milestone before execution is possible.

## Verification and stop behavior

Before every executable step, the CLI re-checks the planned generation invariants. After every mutation, it runs the LaunchServices generation analyzer and Local Network solver against the post-mutation snapshot.

Execution stops immediately and returns `FAILED` if any expected invariant or verification result changes unexpectedly. Remaining plan steps are left untouched.

## Audit

`--audit-log <path>` writes one JSONL audit entry per attempted generation. Each event records the generation id, registration ids, commands, before/after generation counts, verification, errors, and rollback metadata.

## Future milestones

Future milestones may add explicit review and confirmation flows for mounted installer generations, Trash generations, updater generations, and non-Chrome browser families. Those flows must add their own safety tests and must not reuse the Phase 1 Chrome-only gate implicitly.
