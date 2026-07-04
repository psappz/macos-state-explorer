# Generic Evidence/Support Export Framework

`mse export evidence-bundle` is a registry-driven export layer for packaging diagnostic evidence for different audiences, targets, and issue engines.

The export core is intentionally generic. It does not know about Apple, Local Network, LaunchServices, CDN, DNS, WAAP, or any future engine. It resolves one provider by this tuple:

- `audience` — who the bundle is prepared for, such as `vendor-feedback`, `github-issue`, `internal-runbook`, or `customer-report`.
- `target` — the vendor or target context, such as `apple`, `akamai`, `aws`, `cloudflare`, or `generic`.
- `issue` — the diagnostic provider/engine, such as `local-network` now and future CDN/DNS/WAAP/cloud engines later.

Initial implementation:

```bash
mse export evidence-bundle \
  --audience vendor-feedback \
  --target apple \
  --issue local-network \
  --output ./apple-local-network-feedback
```

The initial provider packages the existing Local Network support report into an export directory containing:

- `manifest.json` — deterministic export metadata and artifact list.
- `vendor-feedback.md` — audience-specific summary for vendor feedback.
- `support-bundle/` — existing Local Network diagnostic/support artifacts.

## Extension model

New exports should register a provider instead of adding target-specific logic to the core:

```python
registry.register(
    audience="customer-report",
    target="akamai",
    issue="cdn-dns",
    provider=MyCdnDnsCustomerReportProvider(),
)
```

Provider modules may use domain-specific report builders, but `exports.framework` must remain domain-neutral.

## Design boundaries

- Export core owns request normalization, provider lookup, manifest writing, and unsupported-combination errors.
- Provider modules own audience/target/issue-specific artifact generation.
- Existing report/support-bundle contracts remain reusable inputs; export providers should not mutate diagnostic state.
- Adding a new vendor or engine should require a new provider registration and tests, not edits to the export core dispatch logic.
