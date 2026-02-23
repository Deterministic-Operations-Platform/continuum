# Core Contracts (Python v0.1)

This document describes the active runtime contracts implemented by the Python engine in `continuum/`.

## Runtime scope

- Deterministic scenario execution
- Plugin-based step dispatch
- Resume/selective execution controls
- Evidence emission for every run (success or failure)

## Scenario contract

Top-level:

- `name` (required)
- `rail` (required)
- `vars` (optional mapping)
- `services` (optional mapping)
- `steps` (required non-empty array)
- `cleanup_steps` (optional array)

Step-level:

- `name` (required non-empty string)
- `type` (required non-empty string)
- `key` or `id` (optional stable selector)
- `with` (optional mapping)
- `always` (optional boolean)
- `dependsOn` (optional array of step keys)
- `retry` (optional retry policy)
- `publish` (optional map of `$.details.*` expressions)

## CLI contract

Executable commands:

- `continuum status`
- `continuum run <scenario>`
- `continuum validate <scenario>`
- `continuum plan <scenario>`
- `continuum publish --run-id <id>`

## Evidence contract

Each run under `runs/<run-id>/` always includes:

- `scenario.yaml`
- `context.json`
- `summary.json`
- `manifest.json`

`events.log` may also exist depending on runtime/plugin behavior.

## Notes on non-Python implementations

TS/Java implementations are currently non-authoritative and staged under `experimental/` until they implement this same contract.
