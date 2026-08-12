# Third-Party Notices

This file tracks third-party attribution and redistribution decisions for
content that PawnLogic may reference, adapt, install, or package.

An entry here is not, by itself, permission to redistribute the content. Before
third-party files are included in a PyPI distribution, release artifact, Docker
image, or generated bundled-skill directory, the project must confirm the
upstream license and preserve any required copyright and notice text.

## Current Packaging Policy

PawnLogic PyPI wheels, sdists, and generated release source archives do not
bundle unclear-license third-party CTF skill packs by default. CTF skill packs
are optional extension assets installed explicitly by users, usually into
`~/.pawnlogic/skills` through `/skills install <repo_url>` or by copying a local
skill-pack directory.

The tracked source checkout may contain local development copies of CTF skill
packs while license review is pending. Those directories are configured with
`.gitattributes export-ignore` so generated release archives omit them until
their upstream source, commit, license, and notice requirements are verified.

`pawnlogic[ctf]` installs CTF tooling dependencies only. It does not grant
permission to redistribute third-party skill Markdown or support files.

## Notice Inventory

| Local content | Upstream source | License status | Redistribution decision | Notes |
|---------------|-----------------|----------------|-------------------------|-------|
| `skills/ctf_app_system` | `MateoBogo/claude-skills-ctf` in manifest; repository currently redirects to `MateoBogo/CLEAVE` | Unclear | Exclude from PyPI distributions and generated release source archives | Source-checkout development asset only until upstream license, commit, and notice text are verified. Public CTF credential examples should use placeholders. |
| `skills/ctf_automation` | `MateoBogo/claude-skills-ctf` in manifest; repository currently redirects to `MateoBogo/CLEAVE` | Unclear | Exclude from PyPI distributions and generated release source archives | Source-checkout development asset only until upstream license, commit, and notice text are verified. |
| `skills/ctf_crypto` | `MateoBogo/claude-skills-ctf` in manifest; repository currently redirects to `MateoBogo/CLEAVE` | Unclear | Exclude from PyPI distributions and generated release source archives | Source-checkout development asset only until upstream license, commit, and notice text are verified. |
| `skills/ctf_forensics` | `MateoBogo/claude-skills-ctf` in manifest; repository currently redirects to `MateoBogo/CLEAVE` | Unclear | Exclude from PyPI distributions and generated release source archives | Source-checkout development asset only until upstream license, commit, and notice text are verified. |
| `skills/ctf_malware` | `MateoBogo/claude-skills-ctf` in manifest; repository currently redirects to `MateoBogo/CLEAVE` | Unclear | Exclude from PyPI distributions and generated release source archives | Source-checkout development asset only until upstream license, commit, and notice text are verified. |
| `skills/ctf_misc` | `MateoBogo/claude-skills-ctf` in manifest; repository currently redirects to `MateoBogo/CLEAVE` | Unclear | Exclude from PyPI distributions and generated release source archives | Source-checkout development asset only until upstream license, commit, and notice text are verified. |
| `skills/ctf_osint` | `MateoBogo/claude-skills-ctf` in manifest; repository currently redirects to `MateoBogo/CLEAVE` | Unclear | Exclude from PyPI distributions and generated release source archives | Source-checkout development asset only until upstream license, commit, and notice text are verified. |
| `skills/ctf_pwn` | `MateoBogo/claude-skills-ctf` in manifest; repository currently redirects to `MateoBogo/CLEAVE` | Unclear | Exclude from PyPI distributions and generated release source archives | Source-checkout development asset only until upstream license, commit, and notice text are verified. |
| `skills/ctf_reverse` | `MateoBogo/claude-skills-ctf` in manifest; repository currently redirects to `MateoBogo/CLEAVE` | Unclear | Exclude from PyPI distributions and generated release source archives | Source-checkout development asset only until upstream license, commit, and notice text are verified. |
| `skills/ctf_web` | `MateoBogo/claude-skills-ctf` in manifest; repository currently redirects to `MateoBogo/CLEAVE` | Unclear | Exclude from PyPI distributions and generated release source archives | Source-checkout development asset only until upstream license, commit, and notice text are verified. |
| `skills/solve_challenge` | `MateoBogo/claude-skills-ctf` in manifest; repository currently redirects to `MateoBogo/CLEAVE` | Unclear | Exclude from PyPI distributions and generated release source archives | Source-checkout development asset only until upstream license, commit, and notice text are verified. |
| `skills/heap_exploit` | Local source not established in repository metadata | Unknown | Exclude from PyPI distributions and generated release source archives | Keep as source-checkout asset until authorship and redistribution status are documented. |
| `skills/demo_stack_overflow` | Manifest author is `PawnLogic` | Project-local example | May remain in the source checkout; not currently packaged in PyPI artifacts | If this example is ever packaged, keep it covered by the project license and packaging tests. |
| `skills/api-security`, `skills/apk-reverse`, `skills/attack-chain`, `skills/binary-diff`, `skills/browser-automation`, `skills/browser-extension-reverse`, `skills/case-review`, `skills/cloud-k8s`, `skills/code-audit`, `skills/database-security`, `skills/diagram-generator`, `skills/digital-forensics`, `skills/docs-generator`, `skills/dotnet-reverse`, `skills/edr-bypass-re`, `skills/email-security`, `skills/field-journal`, `skills/firmware-pentest`, `skills/ghidra-reverse`, `skills/go-rust-reverse`, `skills/hardware-security`, `skills/ida-reverse`, `skills/identity-federation`, `skills/js-reverse`, `skills/llm-security`, `skills/macos-reverse`, `skills/malware-analysis`, `skills/mobile-reverse`, `skills/ot-ics`, `skills/patch-diff-exploit`, `skills/pentest-tools`, `skills/protocol-reverse`, `skills/pwn-chain`, `skills/radare2`, `skills/radio-sdr`, `skills/reverse-engineering`, `skills/supply-chain-security`, `skills/thick-client`, `skills/threat-hunting`, `skills/wifi-wireless`, `skills/windows-ad` | `zhaoxuya520/reverse-skill` commit `cf745b8` | MIT | Exclude from PyPI distributions and generated release source archives | Source-checkout development asset. MIT license, copyright 2026 zhaoxuya520. Installed locally via copy from upstream `skills/` subdirectory. Users may enable or disable packs through the `/skills` TUI. |
| Future CTF skill packs from explicitly MIT-licensed upstream projects | To be recorded per source URL and commit | Pending per-file inventory | Blocked until notice entry is complete | Record copied/adapted files, upstream commit, and local changes before packaging. |

## Required Fields For New Entries

Every third-party skill-pack or copied content entry must record:

- Upstream repository URL.
- Upstream commit SHA, release tag, or immutable archive URL.
- License identifier and license file path.
- Copyright holder or author notice.
- Local files copied or adapted.
- Summary of PawnLogic-specific modifications.
- Whether redistribution in PyPI artifacts is allowed.
- Required notice text that must ship with redistributed files.

If any field is unknown, mark the entry as blocked and keep the content out of
redistributed artifacts.
