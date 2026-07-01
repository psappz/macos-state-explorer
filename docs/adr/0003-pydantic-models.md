# 0003 Pydantic Models

## Context

LaunchServices records contain many optional fields and derived attributes. Passing unstructured dictionaries through parsing, grouping, analysis, and reports increases the chance of misspelled keys and inconsistent defaults.

## Decision

Represent LaunchServices records with Pydantic models, starting with `LaunchServicesRecord`. Use explicit optional fields for known LaunchServices attributes and a `fields` dictionary for unknown data. Serialize model instances with `model_dump(mode="python")` at collector boundaries.

Analysis outputs, such as bundle groups and preferred registrations, should also use Pydantic models when they cross module boundaries.

## Consequences

The code gets stronger validation and clearer interfaces while preserving JSON-compatible output. Tests can construct records directly without duplicating parser text. Adding new LaunchServices fields requires updating the model intentionally.
