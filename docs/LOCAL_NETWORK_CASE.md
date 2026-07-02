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

Research note: the observed Local Network behavior is consistent with publicly discussed macOS Local Network issues, including Apple Feedback FB15681423 and Chromium reports. The implementation remains independent of undocumented platform behavior: it relies only on collected LaunchServices evidence, trace artifacts when supplied, and deterministic snapshot comparison.
