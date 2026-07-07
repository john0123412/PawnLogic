# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.2.2   | ✅ Yes     |
| 0.2.1   | ⚠️ Upgrade recommended |
| 0.2.0   | ⚠️ Upgrade recommended |
| 0.1.7   | ⚠️ Upgrade recommended |
| 0.1.6   | ⚠️ Upgrade recommended |
| 0.1.5   | ⚠️ Upgrade recommended |
| 0.1.4   | ⚠️ Upgrade recommended |
| 0.1.3   | ⚠️ Upgrade recommended |
| 0.1.2   | ⚠️ Upgrade recommended |
| 0.1.1   | ⚠️ Upgrade recommended |
| 0.1.0   | ⚠️ Upgrade recommended |
| 0.0.10  | ⚠️ Upgrade recommended |
| 0.0.1 – 0.0.9 | ⚠️ Upgrade recommended |
| < 0.0.1 | ❌ No      |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Please report security issues by emailing: **junjohn05@gmail.com**

Include in your report:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (optional)

You will receive a response within **72 hours**. If the issue is confirmed, a patch will be released as soon as possible and credited to you (unless you prefer to stay anonymous).

## Scope

Areas of particular concern for this project:

- **API key exposure** — keys stored in `~/.pawnlogic/.env`, never in the project directory
- **Host shell execution** — `run_shell` uses an operation policy before subprocess startup; high-risk commands require interactive confirmation, critical operations are denied by default, and non-interactive / `--eval` paths fail closed when confirmation would be required
- **Misuse classification** — `DANGEROUS_PATTERNS` in `config/security.py` is retained as a risk classifier only; it is not a sandbox boundary and cannot stop a malicious local user
- **Path traversal** — Docker file mounts are workspace-bound by default, including read-only mounts; write-capable file operations are resolved inside the workspace jail
- **Docker escape** — containers run with `network_mode=none`, memory/CPU/PID limits
- **CTF workflow boundaries** — CTF tools and skill packs are intended for legal CTFs, authorized labs, and systems you own or have permission to test
