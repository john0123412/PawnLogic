# Triage Labels

PawnLogic uses five canonical triage labels for issue classification. These
labels apply to both local `.scratch/` issues and GitHub Issues when the
repository has them configured.

## Labels

| Label | Meaning | Who acts |
|-------|---------|----------|
| `needs-triage` | Newly filed, not yet classified. | Maintainer |
| `needs-info` | Insufficient detail to act; waiting on reporter. | Reporter |
| `ready-for-agent` | Classified, scoped, and safe for an autonomous agent to pick up. | Agent |
| `ready-for-human` | Requires human judgment, external access, or maintainer authorization. | Maintainer |
| `wontfix` | Declined or out of scope. | Maintainer |

## Workflow

1. New issues start as `needs-triage`.
2. Maintainer triages: adds detail requests (`needs-info`), scopes for agent
   (`ready-for-agent`), flags for human (`ready-for-human`), or closes (`wontfix`).
3. Agents pick up `ready-for-agent` items only.
4. If an agent encounters ambiguity or a blocked dependency, it re-labels
   `needs-info` or `ready-for-human` and stops.

## Repository Labels

When configuring GitHub Issues, create these labels in the repository settings.
Currently only `wontfix` exists as a built-in GitHub label. The other four must
be created manually or via the GitHub API before they can be assigned to issues.
