# Architecture

macOS State Explorer is a read-only forensic analysis platform.

## Layers

1. Collectors  
   Read system state without modifying it.

2. Snapshot Store  
   Stores observations in a stable versioned format.

3. Inference Engine  
   Produces hypotheses from evidence.

4. Reports  
   Generates human-readable HTML and JSON reports.

5. Experiments  
   Runs before/after workflows.

## Core Concepts

- Observation
- Evidence
- Snapshot
- Hypothesis
- Experiment

## Safety

The project must not reset TCC, delete caches, unregister apps, or modify macOS system state.
