# LaunchServices remediation planning

Selective LaunchServices remediation is generation-based because individual stale registrations rarely tell the whole story. Chrome-family apps register app bundles, helpers, frameworks, and updater-adjacent components across versions. Planning at the generation level keeps related registrations together, avoids mixing unrelated Google apps into Chrome cleanup, and makes each candidate auditable before any future mutation exists.

This PR is intentionally plan-only. It emits deterministic human and JSON plans, safety classifications, skipped-generation reasons, and verification commands, but it does not delete files, unregister bundles, reset LaunchServices, or mutate any system database.

Execution must be implemented separately after real-world plan validation. The plan output should first be checked against live LaunchServices data to confirm that active generations, valid iOS placeholders, system apps, unrelated Google apps, and current updater generations are never selected for cleanup.
