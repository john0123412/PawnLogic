# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.4.3   | ✅ Yes     |
| 0.4.2   | ✅ Yes     |
| 0.4.1   | ✅ Yes     |
| 0.4.0   | ✅ Yes     |
| 0.3.13  | ✅ Yes     |
| 0.3.12  | ✅ Yes     |
| 0.3.11  | ✅ Yes     |
| 0.3.10  | ✅ Yes     |
| 0.3.9   | ✅ Yes     |
| 0.3.8   | ✅ Yes     |
| 0.3.7   | ✅ Yes     |
| 0.3.6   | ✅ Yes     |
| 0.3.5   | ✅ Yes     |
| 0.3.4   | ✅ Yes     |
| 0.3.3   | ✅ Yes     |
| 0.3.2   | ✅ Yes     |
| 0.3.1   | ✅ Yes     |
| 0.3.0   | ✅ Yes     |
| 0.2.3   | ⚠️ Upgrade recommended |
| 0.2.2   | ⚠️ Upgrade recommended |
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
- **Docker escape and egress** — containers default to `network_mode=none`. The
  tool contract accepts only `none`, `bridge`, and `host`; `bridge`/`host` and
  airlock package installs require explicit capability-only authorization.
  Unknown modes, including `container:<id>` sharing, are rejected before the
  Docker SDK is called. Memory, CPU, and PID limits remain enforced.
- **CTF workflow boundaries** — CTF tools and skill packs are intended for legal CTFs, authorized labs, and systems you own or have permission to test
- **Network targets** — built-in HTTP(S) adapters evaluate normalized targets,
  DNS answers, and every redirect through the shared Network Policy; special
  address ranges are denied and private targets require explicit authorization.
  The direct `urllib` transport pins DNS answers at policy-check time and fails
  closed without a pin; a configured upstream proxy owns its hop's DNS and
  socket. Browser transports (Patchright and Scrapling) use a mandatory
  loopback proxy. Each CONNECT authority and each single plain-HTTP request
  is checked before forwarding, and only policy-time pinned addresses are
  dialed. Both Chromium paths disable HTTP/2 and QUIC to prevent cross-origin
  connection pooling, explicitly proxy loopback destinations, request Service
  Worker blocking, and apply the WebRTC non-proxied UDP restriction. Context route
  guards remain defense in depth; Chromium does not surface redirect hops to
  them. Patchright 1.63 implements `service_workers="block"` with a JavaScript
  shim that the native prototype method bypasses; Worker connections remain subject
  to the proxy independently of routing. Failed guard installation closes the context, and Scrapling setup is
  verified on every retry. Confirmed private grants preserve the confirmation
  pins and operation token; scope exit and proxy stop close existing sockets.
  Outside an operation, private background requests cannot prompt or acquire
  grants. Overlapping operations and unavailable proxies fail closed.
  Plain HTTP uses `Connection: close`, strips proxy/hop-by-hop headers, and
  rejects chunked uploads, upgrades, `Expect`, and bodies over 8 MiB. CONNECT
  preserves end-to-end TLS and enforces destinations, not encrypted content;
  this is not an OS sandbox. Active handlers are bounded to 16 with a 10-second
  idle/read/write timeout.
- **Extension activation** — installed Extensions remain disabled until explicit
  enablement; compatibility and contribution names are validated before code is
  allowed to register capabilities
- **Security distribution boundary** — proposed penetration-testing Extensions
  must be packaged and published independently from core, require a valid
  engagement scope, and remain subject to host Operation/Network Policy
- **Delegated execution** — model requests cannot expand Provider, Tool, network,
  or cost authority. Two-worker execution requires a forkable task context,
  task-local workspace/output/cancellation, and task-isolated file Tools; every
  non-isolated concurrent Tool path fails closed before handler execution
