# ADR 0002: ProviderRuntime Shares Provider Operations

## Status

Accepted

## Context

Provider behavior is user-facing and appears in several interfaces:

- `/provider` and `/model` slash commands.
- Provider TUI flows.
- Startup and test helpers.

Before ProviderRuntime, connection tests, model fetching, activation, API key
saving, and error formatting were partially duplicated between command and TUI
code. Duplication made it easy for one interface to report a clear HTTP 403 or
502 while another showed a lower-level transport error or hung waiting for a
provider response.

## Decision

Centralize provider operations in `core.provider_runtime`:

- `test_connection`
- `fetch_models`
- `save_key`
- `set_active`

Commands and TUI code should call this runtime layer rather than reimplementing
provider IO, key persistence, activation rules, or model registration.

Provider-facing errors use the shared API error formatting path so HTTP status
codes, retry notices, and transport failures are reported consistently.

## Consequences

The command layer and TUI layer stay thin. They handle prompts, selection, and
rendering, while ProviderRuntime owns the provider operation semantics.

Tests can validate ProviderRuntime once and keep command/TUI tests focused on
routing and presentation.

Future provider behavior changes should start in ProviderRuntime. Interface
layers may customize wording or layout, but should not fork the operation
rules.
