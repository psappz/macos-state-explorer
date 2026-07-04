# LaunchServices persistent mutation validation

## Observed real-world result

A real `mse launchservices execute-plan --confirm` run reported `SUCCESS` with generation count moving from 28 to 21 and every executed generation reporting verification success. An immediate fresh analysis then produced the same LaunchServices remediation plan, the same obsolete Chrome generations, the same Local Network evidence, and a support-bundle diff with no removed or changed evidence.

## Why the previous SUCCESS was incorrect

The previous verifier treated command completion plus aggregate generation-count improvement as success. That was insufficient because it did not prove that the exact executed generation disappeared from durable LaunchServices state. A count can change for unrelated reasons, and an unregister command can return successfully while the same registration is later observed again by a fresh analyzer.

## Mutation versus persistent state change

- **Mutation** means a LaunchServices primitive was attempted, including the exact API/command/file/call and return information.
- **Persistent LaunchServices state change** means a completely fresh post-mutation snapshot no longer contains the exact executed generation and its target registration IDs.

Only persistent removal is successful remediation.

## Result model

`execute-plan --confirm` now reports one of these mutation results:

- `MUTATED_AND_REMOVED`: mutation primitive completed and fresh analysis no longer contains the executed generation.
- `MUTATED_BUT_REGENERATED`: mutation primitive completed, but fresh analysis still reports the executed generation. The audit records the inferred regeneration source when available.
- `NO_MUTATION`: no LaunchServices mutation primitive was attempted, or preconditions blocked execution before mutation.
- `MUTATION_FAILED`: the mutation primitive returned a non-zero result.
- `UNKNOWN`: the command reached a state that cannot be classified deterministically.

Only `MUTATED_AND_REMOVED` exits as successful remediation.

## Verification contract

After every mutation, the command reconstructs a fresh LaunchServices snapshot from system/disk APIs (`fast=False`), reruns generation analysis, computes a generation diff, and gates Local Network evidence on persistent generation removal. Local Network evidence cannot be considered improved when the executed generation persists or is regenerated.

## Audit contract

Each generation audit event records mutation primitives with API, command, file, LaunchServices call, return value, errno, stdout/stderr, OSStatus, and affected registration IDs, followed by the fresh-analysis verification and generation counts.
