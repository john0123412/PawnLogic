---
name: ctf-automation
description: Orchestrator for CTF triage: fingerprint binaries, detect manifests (package.json/Cargo/go.mod/foundry.toml), find crypto/forensics/AI artefacts, emit JSON+markdown dispatch pointers into ctf-*/SKILL.md PRI. Bundles pwnsetup/cryptosetup/websetup/foreniq/aiprobe scripts. CTFd client (ctfd.py) for sync/triage/submit workflow.
license: MIT
compatibility: Requires bash, Python 3, jq. Optional: checksec, rabin2, patchelf, ffuf, httpx, katana, nuclei, subfinder, multimon-ng, sox, pulseview, sagemath. Missing-tool detection prints exact install command instead of crashing.
allowed-tools: Bash Read Write Edit Glob Grep
metadata:
  user-invocable: "true"
  argument-hint: "<challenge-dir> [--json] [--category pwn|crypto|web|forensics|ai]"
---

# CTF Automation — one-shot triage and category setup

All scripts live in this directory. Every script emits JSON to stdout (when `--json` is given) so you can pipe into `jq` or the next stage of a chain.

## Entry point: triage

```bash
bash /home/ubuntu/.claude/skills/ctf-automation/triage.sh <challenge-dir>
```

Outputs:

1. `<challenge-dir>/.ctf-triage.json` — machine-readable fingerprint
2. `<challenge-dir>/.ctf-triage.md` — markdown report with **pointers into `ctf-*/SKILL.md#pattern-recognition-index`**

After triage, pick the indicated category script:

| If triage flags       | Run next                                      |
|-----------------------|-----------------------------------------------|
| `elf_dynamic=true`    | `pwnsetup.sh <binary>`                        |
| `crypto_artefacts>0`  | `python3 cryptosetup.py <challenge-dir>`      |
| `web_urls>0`          | `websetup.sh <url>`                           |
| `forensics_artefacts` | `foreniq.sh <file>`                           |
| `ai_endpoint`         | `python3 aiprobe.py <url>`                    |

## Tool inventory philosophy

Each script performs a `command -v` check for every external tool it uses. Missing tools do **not** crash — they print the exact `apt install …` / `go install …` / `pip install …` command for the missing binary and continue on what remains available.

## Scripts in this directory

- `triage.sh` — master triage; emits JSON + markdown pointing to Pattern Recognition Index sections
- `pwnsetup.sh` — `checksec` → detect libc → `libc.rip` lookup → `patchelf` → generate `exploit.py` pwntools template pre-wired for local+remote
- `cryptosetup.py` — parses challenge files; detects RSA (n,e,c), ECDSA sigs (r,s), lattice shapes, post-quantum params (Kyber/Dilithium/Falcon); generates a Sage script stub with correct imports
- `websetup.sh` — chained recon: `subfinder` → `httpx` → `katana` → `ffuf` → `nuclei`, merges to single JSON
- `foreniq.sh` — RF/audio/logic-analyzer pipeline: GQRX UDP / file → `sox` 22050Hz mono → `multimon-ng -a POCSAG512/1200/2400 -f alpha`; `.sr` files → `pulseview` CLI export
- `aiprobe.py` — LLM endpoint auto-attack: argument injection on tool-allow-lists, DNS rebind, language-guardrail-gap, metadata exfil, reverse-order prompt, literal-policy flip. Emits finding JSON per attack.
- `ctfd.py` — CTFd platform client: sync challenges + download files, run triage on workspace, submit flags, show progress, pick next challenge.

## CTFd workflow (ctfd.py)

Full competition workflow against any CTFd instance:

```bash
SKILLS=~/.claude/skills/ctf-automation

# 1. init workspace (once per CTF)
python3 $SKILLS/ctfd.py init \
  --url https://ctf.example.com \
  --token <your-api-token> \
  --out ./workspace

# 2. download all challenges + files
python3 $SKILLS/ctfd.py sync --dir ./workspace

# 3. fingerprint everything
python3 $SKILLS/ctfd.py triage --dir ./workspace

# 4. pick next target (lowest points first)
python3 $SKILLS/ctfd.py next --dir ./workspace
# → prints: Dir, connection info, triage hint

# 5. work the challenge … find flag …

# 6. submit
python3 $SKILLS/ctfd.py submit "CTF{...}" --chal challenge-name --dir ./workspace

# 7. loop back to step 4
python3 $SKILLS/ctfd.py status --dir ./workspace
```

Workspace layout written by `sync`:
```
workspace/
  .ctfd.json          ← config + challenge index
  pwn/
    heap-overflow/
      vuln  libc.so.6 Dockerfile
      .meta.json       ← id, pts, description, connection_info
      .triage.json     ← from triage step
      .solved          ← written on correct submit
  web/
    login-bypass/
      ...
```

`next` sorts unsolved challenges by points (easiest first); filter by category with `--category pwn`.

## Pattern Recognition dispatch

`triage.sh` reads the file list and dependency manifests, then writes pointers like:

```
ctf-pwn/SKILL.md#pattern-recognition-index → row "MAP_FIXED exposed"
ctf-crypto/SKILL.md#pattern-recognition-index → row "post-quantum KEM"
ctf-misc/ai-ml.md → section "Argument injection on allow-listed tools"
```

The calling agent (`/solve-challenge`) reads the markdown report and dispatches to the skill(s) indicated. This replaces guessing the category from the user prompt — we dispatch on **what is actually in the challenge folder**.

## Chain example

```bash
DIR=/tmp/ch-42
bash triage.sh "$DIR" --json | jq '.hints[]'
# If hints mention "libc":
bash pwnsetup.sh "$DIR/vuln"
# If hints mention "ai_endpoint":
python3 aiprobe.py http://chal.example/api --json > findings.json
```

## Exit codes

- `0` — triage ran, report written
- `2` — directory does not exist / unreadable
- `3` — no recognisable artefacts (empty, or only text README)

Never exit `1`; that's reserved for unexpected script errors, which indicate a bug to fix.



---

<!-- Source: _round2_additions.md -->

# Round-2 additions staging (2026-04-22)

Tracking file — records what's been appended to which ctf-* file. Do not delete; future audits reference it.

| Target file | Sections appended |
|---|---|
| ctf-pwn/advanced-exploits-2.md | vkfs coord-indexed FS overflow · MIPS `$gp`-pivot fake-GOT · FILE UAF + fstr bridge · cross-thread `alloca` stack smash · ObjC Isa-pointer UAF RCE · ARM64 PAC-key exfil via bounds-mismatch AAR · seccomp `cmp`-timing blind oracle · Traefik `X-Forwarded-*` → Flask pivot chain |
| ctf-pwn/advanced-exploits.md | HoS-via-C++-vtable (adjacent-size fudge + vmethod dispatch) |
| ctf-pwn/kernel-advanced.md | folly zero-copy page aliasing (vmsplice-gift → vm_insert_page TOCTOU) |
| ctf-pwn/sandbox-escape.md | io_uring `NO_MMAP` seccomp escape · SCM_RIGHTS fd smuggling across sandbox · coredump-race before in-memory wipe · eBPF FSM syscall-sequence gate |
| ctf-crypto/zkp-and-advanced.md | halo2 blinding-omission Lagrange recovery · LogUp/ProtoStar char-repetition bypass · Noir `sha256_var` trailing-byte under-constraint |
| ctf-crypto/ecc-attacks.md | genus-1 obfuscated variety → Weierstrass + hybrid BSGS/MOV/NFS · py_ecc Jacobian no-curve-check invalid-point |
| ctf-crypto/exotic-crypto.md | ePrint scheme killer linear-algebra patterns · CSIDH/group-action sign-leak oracle · Kzber/UOV post-quantum heuristics |
| ctf-crypto/rsa-attacks.md | Manger's attack (RSA-OAEP first-byte oracle) · structured-prime polynomial factorisation |
| ctf-crypto/modern-ciphers.md | Shamir t-of-n with roots-of-unity evaluation → FFT recovery · single-round AES linear inversion |
| ctf-crypto/advanced-math.md | Hill/printable-ASCII modulus off-by-one · MD5+SHA1 dual-suffix Joux multicollision cascade · GEA-1/2 LFSR rank-deficient key recovery · `dream_multiply` digit-concatenation Diophantine |
| ctf-crypto/prng.md | Legendre-symbol bit oracle → GF(p) state recovery |
| ctf-web/auth-and-access.md | PHP `parse_url()` vs `readfile()` double-colon host divergence · Next.js Next-Action header + trustHostHeader SSRF chain · race on shared token Map between Node workers · Chrome extension DNR→CDP→Puppeteer config.js RCE chain |
| ctf-web/server-side-advanced.md | JWT `base64_decode(strict=false)` request-smuggling + NFKD filename fold · Go handler shared package `err` TOCTOU · Vite dev-server proto-pollution → spawn_sync RCE · NFS handle forgery across exported subtree · JS `String.replace` single-match traversal · WordPress `wp_ajax_nopriv_*` update_option privilege escalation · ORM type-confusion `{$gt:0}` + zipslip + unhandled-promise worker-poison · Firebird `ALTER DATABASE ADD DIFFERENCE FILE` → webshell · TAR/ELF polyglot upload-to-RCE · S3 presigned-URL path traversal to private prefix |
| ctf-web/server-side-deser.md | HQLi → H2 `CREATE ALIAS` → jdk.jshell JDWP RCE chain |
| ctf-web/client-side.md | CSS `@starting-style`/attribute-selector parser-crash oracle · xs-leak via `performance.memory.usedJSHeapSize` heap delta |
| ctf-web/web3.md | Solidity `private` storage leak via `eth_getStorageAt` · SELFDESTRUCT+CREATE2 code-swap post-size-check · Ethereum `txpool_content` snoop/front-run · cross-function reentrancy (guarded vs unguarded pair) |
| ctf-reverse/patterns-ctf-2.md | `perf_event_open` instruction-count side-channel byte oracle · VM architecture misidentification (stack pretending register) + banned-byte synthesis |
| ctf-reverse/languages-compiled.md | `.pyc` PEP-552 magic-header forgery · Go interface/itab `GoReSym` vtable restore · eBPF kprobe FSM gated by syscall-sequence |
| ctf-reverse/tools-advanced.md | TTF GSUB ligature steganography (`ttx -t GSUB` DAG reverse) · AVX2 lane-wise Z3 lifting |
| ctf-misc/ai-ml.md | Agent file-read via unscoped `fetch_article(url)` tool (file:// scheme accepted) · Keras Lambda `marshal+base64` stego container + `safe_mode=False` RCE |
| ctf-misc/pyjails.md | `literal_eval` dict-for-list type confusion → WOTS/OTS signature index reuse |
| ctf-forensics/network-advanced.md | UA-gated C2 URL-path hex-XOR exfil |
| ctf-malware/scripts-and-obfuscation.md | VSCode `.vsix` `onStartupFinished` activation event → marshal/b64 child_process exfil |
| SKILL.md — pwn/crypto/web/reverse/forensics/misc/malware | Pattern Recognition Index rows added for the above |
| SKILL.md — app-system/malware/osint | NEW Pattern Recognition Index section created |
