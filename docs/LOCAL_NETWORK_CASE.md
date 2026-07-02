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

## NetworkExtension identity correlation

`mse networkextension correlate` is the next read-only step after state observation. It compares identities across existing evidence sources rather than adding repair behavior.

The correlation graph can use only observable identity fields:

- LaunchServices generation and registration records
- bundle identifier
- application UUID
- Team ID
- code signing identity when present in readable evidence
- executable or application path
- NetworkExtension preference records
- trace identity fields
- RunningBoard identity strings present in supplied trace analysis
- SecurityPrivacyExtension references present in preference or trace artifacts

For each Chrome generation the command reports one of four relationships:

- `confirmed_identical`: strong observable identity, for example a shared application UUID plus supporting fields.
- `probable_identical`: multiple non-conflicting observable fields match, but the identity is not proven by a shared UUID.
- `conflicting_identity`: observable fields disagree; every conflict is listed.
- `no_observable_relationship`: no safe observed relationship exists between the generation and NetworkExtension identity records.

The graph keeps evidence classes separate:

- `Observed`: directly present in LaunchServices, NetworkExtension artifacts, or supplied traces.
- `Correlated`: produced by comparing two or more observed fields.
- `Inferred`: not used for identity proof; filename-only matches are not sufficient.
- `Unknown`: required evidence is missing or not readable.

NetworkExtension preference evidence is additionally binding-aware:

- `structurally_bound_identity`: one structured preference object binds exactly one bundle identifier to its UUID, Team ID, path, or signing fields.
- `raw_text_reference_only`: a bundle identifier appears only in broad serialized text. It remains evidence that the string was present, but its neighboring UUID, Team ID, and path values are not assigned to that bundle.
- `ambiguous_preference_reference`: a structured preference object contains multiple bundle identifiers or otherwise cannot safely bind one identity field set to one bundle.

This PR 48 binding step reduces false identity graph nodes. It does not change diagnosis, repair, planner behavior, solver ranking, cleanup, or confidence. A Chrome generation may still report `no_observable_relationship`; the reason should now say whether only raw or ambiguous preference evidence was present.

This correlation may identify shared UUIDs, reused bundle identifiers, shared Team IDs, shared executable paths, trace identity matches, and conflicting identity records. It still does not prove the true producer unless observable evidence connects a producer action to the stale registration. Missing producer evidence remains `Unknown`.

Support bundles include `networkextension-correlation.json` and `networkextension-correlation.txt`, and bundle diffs include `NetworkExtension Correlation Diff`.

## NetworkExtension raw-reference attribution

`mse networkextension raw-references` is a narrow read-only attribution step for cases where identity correlation finds many `raw_text_reference_only` hits but no safe identity edge. It answers where Chrome-related strings live so a future human-reviewed design can decide whether a preference artifact is worth inspecting.

For each Chrome/Chromium/Google-related raw reference the command reports:

- artifact path and artifact label
- recoverable plist key path when structured parsing succeeds
- value type, matched token, and redacted surrounding context
- reference category such as `chrome_bundle_id`, `chrome_code_sign_clone`, `chrome_path`, `launchservices_reference`, `securityprivacyextension_reference`, or `generic_chromium_text`
- binding status: `structurally_bound_identity`, `raw_text_reference_only`, or `ambiguous_preference_reference`
- safety classification: `inspect_only`, `candidate_local_network_store`, `broad_cache_or_blob`, or `not_actionable`
- the reason the reference is or is not actionable

Raw-reference attribution does not infer identity edges from text, does not change the correlation graph, and does not change diagnosis, solver, planner, repair ranking, cleanup, or confidence. Broad cache/blob references remain evidence only; they are not promoted into identity or deletion candidates.

Support bundles include `networkextension-raw-references.json` and `networkextension-raw-references.txt`, and bundle diffs include `NetworkExtension Raw References Diff`.

## NetworkExtension object graph decoder

`mse networkextension object-graph` is the next read-only investigation step for NetworkExtension preference artifacts that store Chrome references inside NSKeyedArchiver-style `$objects[...]` arrays. Raw references are observable, but they remain non-actionable unless object graph context proves they are part of an actionable policy or client record. This command adds that context without changing identity correlation or remediation behavior.

For each Chrome/Chromium/code-sign-clone hit, the decoder reports:

- artifact name and decoded object index such as `$objects[143]`
- value type and matched token
- recoverable object key path when present
- parent chain and child/sibling object relationships from `plistlib.UID` references
- nearest dictionary keys and neighboring object indices
- binding classification: `policy_record_candidate`, `client_identity_candidate`, `cache_or_blob_reference`, `raw_archive_reference`, or `unknown_object_context`
- safety classification: `read_only`, `not_actionable`, `inspect_only`, or `potential_future_repair_candidate`
- explanation of why the evidence is only investigatory

The decoder does not infer identity bindings unless the NSKeyedArchiver object graph structurally supports them. It does not classify anything as deletable. It does not mutate, delete, reset, repair, rewrite plists, clear caches, restart services, change diagnosis, change solver ranking, change planner behavior, or change confidence. This PR is read-only and does not solve or repair the Local Network issue.

Support bundles include `networkextension-object-graph.json` and `networkextension-object-graph.txt`, and bundle diffs include `NetworkExtension Object Graph Diff` for decoded artifacts, referenced object indices, binding classifications, safety classifications, and parent-chain summaries.

Research note: the observed Local Network behavior is consistent with publicly discussed macOS Local Network issues, including Apple Feedback FB15681423 and Chromium reports. The implementation remains independent of undocumented platform behavior: it relies only on collected LaunchServices evidence, trace artifacts when supplied, NetworkExtension preference observations when readable, and deterministic snapshot comparison.
