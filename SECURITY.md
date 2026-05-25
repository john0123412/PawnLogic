# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.0.1   | ✅ Yes     |
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
- **Shell injection** — `DANGEROUS_PATTERNS` blocklist in `config/security.py`
- **Path traversal** — RW mounts restricted to `~/.pawnlogic/workspace` in `docker_sandbox.py`
- **Docker escape** — containers run with `network_mode=none`, memory/CPU/PID limits
