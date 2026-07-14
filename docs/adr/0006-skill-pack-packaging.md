# ADR 0006: Skill Pack Packaging

## Status

Accepted

## Context

PawnLogic supports Skill Packs as optional instruction bundles that extend
agent behavior for specific domains (e.g., CTF). Before this ADR:

- It was unclear whether third-party Skill Packs should be included in PyPI
  wheels or kept external.
- `pawnlogic[ctf]` installs CTF tooling dependencies, but the relationship
  between the extra and skill content was ambiguous.
- PyPI extras cannot conditionally add or remove files from the same wheel,
  making it impossible to ship optional content via extras alone.

## Decision

1. **External by default:** Third-party Skill Packs are user-installed assets,
   not mandatory runtime package contents. Users install them explicitly into
   `~/.pawnlogic/skills` with `/sp install <repo_url>` or by copying a local
   directory.
2. **No wheel content:** `pawnlogic[ctf]` installs CTF tooling dependencies
   only. It does not install third-party Skill Pack markdown, support files,
   or an original PawnLogic CTF knowledge base.
3. **No redistribution without notice:** Third-party skill content must not be
   redistributed in PyPI artifacts, release archives, Docker images, or
   generated bundled-skill directories until `THIRD_PARTY_NOTICES.md` records
   the upstream URL, commit/release, license, copyright notice, and
   redistribution decision.
4. **Gitattributes:** Source-checkout skill assets that must stay out of
   generated release archives use `.gitattributes export-ignore`.

## Consequences

The PyPI wheel contains no `skills/` directory. The build verification step
checks that the wheel has zero skill files.

Users who want CTF skills install them separately. The README and GUIDE document
this explicitly.

Changing skill-pack packaging or installation behavior requires updating
README, GUIDE, THIRD_PARTY_NOTICES.md, CHANGELOG.md, and the packaging tests.
