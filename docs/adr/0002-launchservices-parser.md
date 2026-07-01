# 0002 LaunchServices Parser

## Context

`lsregister -dump` produces text output with repeated records, inconsistent field presence, path suffixes, and occasional error lines such as missing bundle nodes. A single large regular expression is brittle and makes it hard to retain unknown fields for later analysis.

## Decision

Parse LaunchServices dumps block by block in `macos_state_explorer.launchservices.parser`. Each block is scanned line by line. Known fields are mapped onto typed record attributes, unknown fields are retained, and derived values are computed during parsing:

- cleaned paths
- expanded home paths
- path existence
- volume path and existence
- missing node detection
- initial classification

The collector calls `parse_lsdump()` and serializes the resulting records.

## Consequences

The parser is easier to test with small fixture strings and can tolerate partial records. Unknown fields are preserved for future work. Classification can be improved without changing CLI commands or the raw collection step.
