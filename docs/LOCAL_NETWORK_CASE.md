# Local Network case study

Observed model:

```text
System Settings
  -> privacy daemon/cache layer and/or LaunchServices app registry
  -> GUI list
```

Not proven:

```text
System Settings
  -> direct SELECT from TCC.access where service = kTCCServiceLocalNetwork
```

Run:

```bash
mse trace local-network ~/Desktop/mse-trace
```

## Manual cleanup verification

The LaunchServices Local Network reference case now has a read-only manual remediation lifecycle:

```text
Diagnosis
  -> Cleanup Checklist
  -> Manual Cleanup
  -> Cleanup Verification
```

`mse launchservices cleanup-checklist` explains which remaining non-automatic LaunchServices sources require user action. After the user performs those actions, `mse launchservices verify-cleanup` verifies the current LaunchServices snapshot against the expected post-cleanup state.

Cleanup verification is evidence-driven and read-only. It does not delete files, unregister LaunchServices entries, run repair commands, change planner behavior, change diagnostic rules, or alter solver behavior.

The verifier separates findings into `Verified`, `Still Present`, `Unexpected`, and `Unknown` so a report can distinguish successful manual cleanup from persistent stale generations, newly appeared stale generations, and updater ownership that cannot be proven from the current snapshot alone.

## NetworkExtension state observation

The remaining Local Network unknown is treated as a separate read-only producer layer:

```text
NetworkExtension / Local Network preference state
  -> application identity records
  -> System Settings / SecurityPrivacyExtension presentation
  -> Local Network authorization behavior
```

`mse networkextension state` observes candidate NetworkExtension and Local Network preference artifacts when they are readable. The command records only what is present in observed files: artifact paths, bundle identifiers, application UUIDs, team identifiers, preference timestamps, preference generation values when textual, application path references, and textual references to Chrome, Edge, Chromium, GoogleUpdater, SecurityPrivacyExtension, System Settings, and LaunchServices.

The output uses four meanings deliberately:

- `Observed`: directly present in an inspected artifact.
- `Correlated`: reserved for future comparison logic; the state command does not currently correlate separate producers.
- `Inferred`: reserved for future analysis; the state command does not infer missing platform state.
- `Unknown`: not safely observable from the inspected artifacts.

Local Network differs from normal TCC permissions because current evidence does not show it behaving as a plain `TCC.access` service row. Apple DTS discussions, Chromium reports, Apple Feedback FB15681423 / FB15683070, and observed system behavior point to additional persistent state involving NetworkExtension preferences, LaunchServices identity, code signing identity, application UUIDs, System Settings, and SecurityPrivacyExtension. This project therefore treats NetworkExtension state as an independent producer instead of folding it into LaunchServices or TCC.

The NetworkExtension state engine is strictly read-only. It does not repair, delete, mutate preferences, rebuild caches, reset authorization, escalate privileges, reboot, or trigger planner/solver/diagnostic changes. Support bundles include `networkextension-state.json` and `networkextension-state.txt`, and bundle diffs include a `NetworkExtension State Diff` section for deterministic before/after comparison.

Research note: the observed Local Network behavior is consistent with publicly discussed macOS Local Network issues, including Apple Feedback FB15681423 and Chromium reports. The implementation remains independent of undocumented platform behavior: it relies only on collected LaunchServices evidence, trace artifacts when supplied, NetworkExtension preference observations when readable, and deterministic snapshot comparison.
