# Security Policy

## Supported Versions

This project is currently in active early development. Security fixes are handled on the main development line.

## Reporting a Vulnerability

Please do not open a public issue for sensitive security concerns.

Report vulnerabilities privately to the repository maintainers. Include:

- A concise description of the issue.
- Steps to reproduce, if safe to share.
- The affected command or module.
- Any logs or output with personal information removed.

## Safety Scope

Open State Diagnostics & Repair Framework is intended to be read-only. Security-sensitive changes must not:

- Reset TCC.
- Delete caches.
- Unregister applications.
- Modify system settings.
- Require elevated privileges unless explicitly reviewed and documented.

If a proposed change needs privileged access, document why it is necessary and how it avoids modifying system state.
