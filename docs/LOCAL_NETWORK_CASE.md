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

## NetworkExtension repair-candidate analysis

`mse networkextension repair-candidates` is still strictly read-only. It does not repair anything and does not recommend automatic deletion. It evaluates decoded NSKeyedArchiver client identity records so a future human-reviewed design can see which records might require more investigation.

For every decoded Chrome client identity record the command reports:

- identity type, signing identifier, executable path, and code-sign-clone usage
- object graph location and parent dictionary
- whether the record appears complete, duplicated, active, historical, or orphaned
- whether it references an installed application, references only a code-sign-clone path, and whether the executable currently exists
- whether the record could ever be safely removed; current implementation always reports `false`
- whether additional runtime evidence is required before any future manual action
- deterministic safety classification: `never_delete`, `not_actionable`, `manual_only`, `potential_future_repair_candidate`, or `requires_runtime_confirmation`
- deterministic explanation for the classification

Insufficient evidence is explicit. Incomplete records are `not_actionable`. Installed or active records require runtime confirmation. Code-sign-clone-only and orphaned-looking records remain manual-review evidence only; they are not deletion instructions. The command does not mutate, delete, reset, repair, rewrite plists, clear caches, restart services, change diagnosis, change solver ranking, change planner behavior, or change confidence.

Support bundles include `networkextension-repair-candidates.json` and `networkextension-repair-candidates.txt`, and bundle diffs include `NetworkExtension Repair Candidate Diff` for candidate object references, safety classifications, duplicate counts, orphaned counts, and code-sign-clone-only counts.

## NetworkExtension candidate runtime validation

`mse networkextension validate-candidates` is the next narrow read-only validation step for repair candidates. It takes the decoded client identity records from repair-candidate analysis and compares them with observable runtime evidence: filesystem path presence, parent app/container presence, installed app presence, code-sign-clone/temp-container path shape, LaunchServices entry matches, and a best-effort current process snapshot.

For every candidate the command reports:

- artifact, object reference, signing identifier, executable path, and parent-chain context
- runtime status: `runtime_present`, `runtime_absent`, `active_installed_app`, `stale_code_sign_clone`, `stale_missing_executable`, `ambiguous`, or `unverifiable`
- evidence booleans for executable, parent bundle, installed app, code-sign-clone path, temp-container path, LaunchServices generation match, and running process match when observable
- actionability flags that remain `still_read_only`, `requires_manual_confirmation`, and `never_auto_delete`
- deterministic explanation of why the status is evidence only

Runtime absence is evidence, not permission to delete. Missing `/private/var/.../com.google.Chrome.code_sign_clone/...` paths and missing executable paths can support a stale or absent classification, but the command never recommends automatic deletion. It does not mutate, delete, reset, repair, rewrite plists, clear caches, restart services, change diagnosis, change solver ranking, change planner behavior, or change confidence.

Support bundles include `networkextension-candidate-validation.json` and `networkextension-candidate-validation.txt`, and bundle diffs include `NetworkExtension Candidate Validation Diff` for candidate refs, runtime status changes, runtime-absent deltas, stale-record deltas, and unverifiable-record deltas.

## NetworkExtension repair plan preview

`mse networkextension repair-plan-preview` is a strictly read-only preview layer on top of repair-candidate analysis and runtime validation. It groups validated stale candidate records so a future manual repair design can see what would be reviewed, but it does not execute, write, delete, reset, unload, reload, kill, reboot, or mutate anything.

The preview groups stale records by:

- plist artifact
- parent object record
- SigningIdentifier
- executable path class
- validation status

Every group is marked `preview_only` and every report keeps `mutation_performed: false`. The only automatic execution recommendation is `never`.

Group classifications are intentionally conservative:

- `stale_code_sign_clone_preview_target`
- `stale_missing_executable_preview_target`
- `unsafe_without_manual_confirmation`
- `never_auto_delete`

The preview also records mandatory manual preconditions for any future human-reviewed repair: user-reviewed support bundle, backup of affected plist, Chrome not running, System Settings closed, post-change reboot required, and post-change verification required. It records automatic-execution blockers: NSKeyedArchiver mutation risk, object graph integrity risk, macOS private preference format, and runtime absence alone being insufficient.

This command does not add deletion, plist writing, repair execution, solver behavior, planner behavior, diagnosis changes, ranking changes, confidence changes, or remediation behavior. Support bundles include `networkextension-repair-plan-preview.json` and `networkextension-repair-plan-preview.txt`, and bundle diffs include `NetworkExtension Repair Plan Preview Diff` for preview group additions/removals, classification changes, and preview target deltas.

## NetworkExtension repair transaction package

`mse networkextension repair-transaction-package` is a strictly read-only transaction/package layer on top of validated repair-plan-preview groups. It describes exactly what a future manual or separately guarded repair would need to review, but it is not executable by this tool.

For every preview group the package records:

- source artifact path/name, artifact type, and SHA256 digest when the source artifact is readable
- mandatory backup requirement and rollback requirement
- affected parent object record such as `$objects[137]`
- grouped preview target IDs and candidate object references
- validation status, executable path class, and `SigningIdentifier`
- manual preconditions and execution blockers inherited from the preview layer
- post-change verification commands
- explicit `read_only: true`, `mutation_performed: false`, `executable_by_tool: false`, and automatic execution recommendation `never`

The transaction package does not edit plists, delete records, reset services, execute repair, change solver/planner/ranking/confidence behavior, or mutate the system. Support bundles include `networkextension-repair-transaction-package.json` and `networkextension-repair-transaction-package.txt`, and bundle diffs include `NetworkExtension Repair Transaction Package Diff` for transaction additions/removals, validation status changes, and backup/rollback deltas.

## NetworkExtension manual repair runbook

`mse networkextension manual-repair-runbook` is the first mutation-capable design artifact, but macos-state-explorer itself remains completely read-only. The command consumes the previous NetworkExtension evidence layers—identity correlation, raw references, object graph decoding, repair candidates, runtime validation, repair-plan preview, and repair transaction package—and emits a deterministic operator specification for a future experienced macOS engineer to review.

For every transaction the runbook records:

- transaction ID, source artifact, SHA256, parent object, candidate object refs, SigningIdentifier, validation status, and executable path class
- repair class and expected manual mutation semantics: object removal, object rewrite, UID rewiring, array changes, dictionary changes, and object-count delta
- objects that must remain untouched, objects requiring reindexing, objects requiring UID remapping, and objects requiring archive regeneration
- affected object graph details: object index/class, parent chain, referenced UIDs, referencing objects, dictionary keys, array memberships, incoming/outgoing references, dependency graph, deletion independence, and graph-rewrite requirement
- safety analysis for single-object deletion, dictionary update, array compaction, UID rewrite, archive rebuild, multiple object removal, cross-reference update, and complete archive regeneration
- repair difficulty (`trivial`, `low`, `medium`, `high`, or `unsafe`) with deterministic explanation
- failure modes, rollback requirements, verification commands, and expected verification outcome

The runbook never writes plists, never edits NSKeyedArchiver archives, never deletes objects, never rewires UIDs, never compacts arrays, never rebuilds archives, never executes repair, and never recommends automatic execution. It is generated documentation only. Support bundles include `networkextension-manual-repair-runbook.json` and `networkextension-manual-repair-runbook.txt`, and bundle diffs include `NetworkExtension Manual Repair Runbook Diff` for runbook additions/removals, difficulty changes, transaction deltas, and archive-regeneration deltas.

## NetworkExtension repair simulation

`mse networkextension repair-simulation` is still strictly read-only. It consumes the manual repair runbook / transaction-package data and simulates the planned object removals against an in-memory temporary copy of the affected NSKeyedArchiver plist. It does not write back to the system artifact.

The simulation performs the same categories that a future human-reviewed repair would need to reason about:

- planned `$objects[...]` removal for the stale transaction records
- deterministic `plistlib.UID` remapping after object compaction
- array compaction when removed UIDs disappear from array members
- dictionary cleanup when dictionary values point at removed UIDs
- binary plist reserialization of the temporary copy
- re-parse validation of the serialized temporary copy
- fresh object-graph, candidate-validation, and repair-plan evaluation against the simulated result

The JSON contract deliberately records `read_only: true`, `mutation_performed: false`, `system_artifact_modified: false`, `executable_by_tool: false`, and `automatic_execution_recommendation: "never"`. Safety verdicts are limited to `simulation_passed`, `simulation_failed`, and `simulation_inconclusive`; none of them authorizes automatic repair.

The command does not modify real files, delete objects from the live plist, reset services, change diagnosis, change ranking, change confidence, change solver behavior, change repair execution behavior, or alter LaunchServices behavior. Support bundles include `networkextension-repair-simulation.json` and `networkextension-repair-simulation.txt`, and bundle diffs include `NetworkExtension Repair Simulation Diff`.

## NetworkExtension generated repair artifact

`mse networkextension generate-repair-artifact` is a guarded offline artifact-generation layer on top of the transaction package, manual runbook, and repair simulation. It recomputes those inputs in the same process and refuses to write an artifact unless the in-process simulation result is successful (`simulation_passed`).

The command may create only an offline generated plist artifact and metadata. It never installs the artifact, never overwrites the source plist, never copies anything back into a live preference location, never deletes or resets anything, never unloads/reloads NetworkExtension services, and never restarts services. Output paths under `/Library`, `/System`, `/private/var/db`, `/Library/Preferences`, or the inspected live NetworkExtension plist are rejected fail-closed.

The JSON contract records the hard safety flags:

- `read_only: true`
- `mutation_performed: false`
- `system_artifact_modified: false`
- `executable_by_tool: false`
- `automatic_execution_recommendation: "never"`
- `offline_generated: true`
- `installed: false`

Artifact metadata includes source artifact metadata, source SHA256, generated artifact SHA256, removed object refs, UID rewrite count, array change count, dictionary change count, simulation verdict, validation result, and reparse status. After writing the offline plist, the command reparses it immediately and fails closed if parsing fails.

Support bundles include `networkextension-repair-artifact.plist`, `networkextension-repair-artifact.json`, and `networkextension-repair-artifact.txt`. Bundle diffs include `NetworkExtension Repair Artifact Diff` for generated artifact IDs, validation-result changes, object-removal deltas, UID rewrite deltas, and generated artifact hash changes.

Research note: the observed Local Network behavior is consistent with publicly discussed macOS Local Network issues, including Apple Feedback FB15681423 and Chromium reports. The implementation remains independent of undocumented platform behavior: it relies only on collected LaunchServices evidence, trace artifacts when supplied, NetworkExtension preference observations when readable, and deterministic snapshot comparison.
