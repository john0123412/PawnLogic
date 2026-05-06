---
name: ctf-reverse
description: Reverse engineering: ELF/PE/Mach-O, WASM, .NET, APK (Flutter/Dart), Python bytecode, Go/Rust/Swift/Kotlin, custom VMs, anti-debug/anti-VM, VMProtect/Themida, eBPF, Ghidra/IDA/radare2/Frida/angr/Qiling. Dispatch on file magic + loader signature.
license: MIT
compatibility: Requires filesystem-based agent (Claude Code or similar) with bash, Python 3, and internet access for tool installation.
allowed-tools: Bash Read Write Edit Glob Grep Task WebFetch WebSearch
metadata:
  user-invocable: "false"
---

# CTF Reverse Engineering

Quick reference for RE challenges. For detailed techniques, see supporting files.

## Additional Resources

- [tools.md](tools.md) — GDB, Ghidra, radare2, IDA, Binary Ninja, Unicorn, WASM, pyc, packed
- [tools-dynamic.md](tools-dynamic.md) — Frida, angr, lldb, x64dbg, Qiling, Triton, Pin instruction-counting
- [tools-advanced.md](tools-advanced.md) — VMProtect/Themida, BinDiff, D-810/GOOMBA, TTF GSUB, AVX2 Z3 lift
- [tools-advanced-2.md](tools-advanced-2.md) — 2025-26: GB-scale PE Unicorn+angr hybrid (VirtualProtect-gated unpackers)
- [anti-analysis.md](anti-analysis.md) — Linux/Windows anti-debug, anti-VM, anti-DBI, MBA, self-hashing
- [patterns.md](patterns.md) — custom VMs, nanomites, LLVM obfuscation, S-box, SECCOMP/BPF, multi-thread
- [patterns-ctf.md](patterns-ctf.md) — comp patterns part 1: hidden opcodes, LD_PRELOAD, GBA MITM, maze kmod
- [patterns-ctf-2.md](patterns-ctf-2.md) — part 2: multi-layer brute, CVP integer, decision-tree, perf oracle, VM misident
- [patterns-ctf-3.md](patterns-ctf-3.md) — 2025-26: genetic algorithm / hill-climb over opaque additive scoring
- [languages.md](languages.md) — Python bytecode, pyarmor, UEFI, esolangs, HarmonyOS, Godot, Electron
- [languages-compiled.md](languages-compiled.md) — Go (GoReSym), Rust, Swift, Kotlin/JVM, C++ vtables, .pyc forgery
- [platforms.md](platforms.md) — Mach-O, iOS jailbreak, embedded firmware, kernel drivers, game engines, CAN
---

## Pattern Recognition Index

Dispatch on **observable binary features**, not challenge titles.

| Signal (from `file`, `readelf`, `strings`, `nm`) | Technique → file |
|---|---|
| ELF with `__libc_start_main`, small main, direct syscalls | Basic RE patterns → patterns.md |
| ELF with large unrecognised opcode-dispatch loop (switch on byte → handler) | Custom VM reversing → patterns.md |
| `readelf -l` shows RWX segment + self-writes to `.text` | Self-modifying / multi-layer decryption → patterns-ctf-2.md |
| Binary that modifies its round constants and re-encrypts output | Binary-as-keystream-oracle (patch I/O boundary) → patterns-ctf-2.md |
| `ptrace(PTRACE_TRACEME)` / `/proc/self/status TracerPid` / `rdtsc` timing | Anti-debug detection → anti-analysis.md |
| `__Py_*` or `PyMarshal` strings | Python bytecode / pyc reversing → languages.md |
| `runtime.` prefix in strings, `go.buildinfo` | Go reversing (GoReSym) → languages-compiled.md |
| Rust demangling (`_ZN`/`_RN`), `core::panicking` | Rust reversing → languages-compiled.md |
| Mach-O header `FEEDFACE`/`FEEDFACF` | macOS/iOS RE → platforms.md |
| `.wasm` magic (`00 61 73 6D`) | WASM → languages.md, ctf-misc/games-and-vms.md |
| `.apk`/`classes.dex`, `libflutter.so`, `kernel.dill` | APK / Flutter reversing → languages.md |
| Unicorn/QEMU used as a sandbox with host-side memory read helpers | Host/guest hook divergence → patterns-ctf-2.md (and ctf-pwn/advanced-exploits-2.md) |
| `.rodata` blob + XOR loop with known constants / stored expected bytes | Stack-string deobfuscation → patterns-ctf-2.md |
| `SHA-NI` instructions, per-layer key read from stdin | Multi-layer brute-force JIT → patterns-ctf-2.md |
| Per-char early-exit compare loop + local execution allowed | `perf_event_open` instruction-count oracle → patterns-ctf-2.md |
| Custom VM whose handlers are pop/push but docs claim "register-based" + banned bytes | Arch misidentification + banned-byte synthesis → patterns-ctf-2.md |
| `.pyc` with loader that checks only first 16 bytes | PEP-552 magic-header forgery → languages-compiled.md |
| Go binary with `runtime.itab` symbols intact but stripped strings | GoReSym/typelinks restore → languages-compiled.md |
| `bpftool prog list` shows non-standard eBPF prog | eBPF FSM syscall-sequence decomp → languages-compiled.md (+ ctf-pwn/sandbox-escape.md) |
| TTF/OTF with abnormally dense GSUB; glyphs named `hex_*`/`one`/`zero` | GSUB ligature stego DAG reverse → tools-advanced.md |
| AVX2 `vpaddb`/`vpshufb` in tight loop over input | Lane-wise Z3 lifting → tools-advanced.md |
| PE ≥ 500 MB, multiple `VirtualProtect(...,RWX)` + inline decrypt + `call/jmp rax` after each | Unicorn layer-graph + per-layer angr solve → tools-advanced-2.md |
| Flat chain of hundreds of `if (input[i] op const) score += kN`; win if `score >= THR` | Separability probe → hill-climb → GA → patterns-ctf-3.md |

Recognize the **artefact or opcode pattern**. The title is noise.

---

For inline code/cheatsheet quick references (grep patterns, one-liners, common payloads), see [quickref.md](quickref.md). The `Pattern Recognition Index` above is the dispatch table — always consult it first; load `quickref.md` only if you need a concrete snippet after dispatch.



---

<!-- Source: anti-analysis.md -->

# CTF Reverse - Anti-Analysis Techniques & Bypasses

Comprehensive reference for anti-debugging, anti-VM, anti-DBI, and integrity-check techniques encountered in CTF challenges, with practical bypasses.

## Table of Contents
- [Linux Anti-Debug (Advanced)](#linux-anti-debug-advanced)
  - [ptrace-Based](#ptrace-based)
  - [/proc Filesystem Checks](#proc-filesystem-checks)
  - [Timing-Based Detection](#timing-based-detection)
  - [Signal-Based Anti-Debug](#signal-based-anti-debug)
  - [Syscall-Level Evasion](#syscall-level-evasion)
- [Windows Anti-Debug (Advanced)](#windows-anti-debug-advanced)
  - [PEB-Based Checks](#peb-based-checks)
  - [NtQueryInformationProcess](#ntqueryinformationprocess)
  - [Heap Flags](#heap-flags)
  - [TLS Callbacks](#tls-callbacks)
  - [Hardware Breakpoint Detection](#hardware-breakpoint-detection)
  - [Software Breakpoint Detection (INT3 Scanning)](#software-breakpoint-detection-int3-scanning)
  - [Exception-Based Anti-Debug](#exception-based-anti-debug)
  - [NtSetInformationThread (Thread Hiding)](#ntsetinformationthread-thread-hiding)
- [Anti-VM / Anti-Sandbox](#anti-vm--anti-sandbox)
  - [CPUID Hypervisor Bit](#cpuid-hypervisor-bit)
  - [MAC Address / Hardware Fingerprinting](#mac-address--hardware-fingerprinting)
  - [Timing-Based VM Detection](#timing-based-vm-detection)
  - [File / Registry Artifacts](#file--registry-artifacts)
  - [Resource Checks (CPU Count, RAM, Disk)](#resource-checks-cpu-count-ram-disk)
- [Anti-DBI (Dynamic Binary Instrumentation)](#anti-dbi-dynamic-binary-instrumentation)
  - [Frida Detection](#frida-detection)
  - [Pin/DynamoRIO Detection](#pindynamorio-detection)
- [Code Integrity / Self-Hashing](#code-integrity--self-hashing)
- [Anti-Disassembly Techniques](#anti-disassembly-techniques)
  - [Opaque Predicates](#opaque-predicates)
  - [Junk Bytes / Overlapping Instructions](#junk-bytes--overlapping-instructions)
  - [Jump-in-the-Middle](#jump-in-the-middle)
  - [Function Chunking / Scattered Code](#function-chunking--scattered-code)
  - [Control Flow Flattening (Advanced)](#control-flow-flattening-advanced)
  - [Mixed Boolean-Arithmetic (MBA) Identification & Simplification](#mixed-boolean-arithmetic-mba-identification--simplification)
- [Comprehensive Bypass Strategies](#comprehensive-bypass-strategies)
  - [Universal Bypass Checklist](#universal-bypass-checklist)
  - [Layered Anti-Debug (Real-World Pattern)](#layered-anti-debug-real-world-pattern)
  - [Quick Reference: Check to Bypass](#quick-reference-check-to-bypass)

---

## Linux Anti-Debug (Advanced)

### ptrace-Based

**Self-ptrace (most common):**
```c
if (ptrace(PTRACE_TRACEME, 0, 0, 0) == -1) exit(1); // Already traced = debugger attached
```

**Bypasses:**
```bash
# 1. LD_PRELOAD (see patterns.md for full hook)
LD_PRELOAD=./hook.so ./binary

# 2. Patch with pwntools
python3 -c "
from pwn import *
elf = ELF('./binary', checksec=False)
elf.asm(elf.symbols.ptrace, 'xor eax, eax; ret')
elf.save('patched')
"

# 3. GDB: catch the syscall
gdb ./binary
(gdb) catch syscall ptrace
(gdb) run
# When it stops at ptrace:
(gdb) set $rax = 0
(gdb) continue

# 4. Kernel config (requires root)
echo 0 > /proc/sys/kernel/yama/ptrace_scope
```

**Double-ptrace pattern:**
```c
// Fork child to ptrace parent — blocks all other debuggers
pid_t child = fork();
if (child == 0) {
    ptrace(PTRACE_ATTACH, getppid(), 0, 0);
    // Child sits in waitpid loop, keeping parent traced
} else {
    // Parent continues with real logic
}
```
**Bypass:** Kill the watchdog child process, then attach debugger.

### /proc Filesystem Checks

```c
// TracerPid check
FILE *f = fopen("/proc/self/status", "r");
// Looks for "TracerPid:\t0" — non-zero means debugger

// /proc/self/exe link check (some debuggers change this)
readlink("/proc/self/exe", buf, sizeof(buf));

// /proc/self/maps — check for debugger libraries
grep("frida", "/proc/self/maps");
```

**Bypasses:**
```bash
# 1. LD_PRELOAD fopen/fread to fake /proc contents
# 2. Mount namespace isolation
unshare -m bash -c 'mount --bind /dev/null /proc/self/status && ./binary'

# 3. GDB: set breakpoint at fopen, change filename argument
(gdb) b fopen
(gdb) run
(gdb) set {char[20]} $rdi = "/dev/null"
(gdb) continue
```

### Timing-Based Detection

```c
// rdtsc (CPU timestamp counter)
uint64_t start = __rdtsc();
// ... code ...
uint64_t delta = __rdtsc() - start;
if (delta > THRESHOLD) exit(1);  // too slow = debugger

// clock_gettime
struct timespec ts1, ts2;
clock_gettime(CLOCK_MONOTONIC, &ts1);
// ... code ...
clock_gettime(CLOCK_MONOTONIC, &ts2);

// gettimeofday
struct timeval tv1, tv2;
gettimeofday(&tv1, NULL);
```

**Bypasses:**
```bash
# 1. Frida hook (see tools-dynamic.md for clock_gettime hook)

# 2. GDB: skip rdtsc by patching with constant
(gdb) set {unsigned char[2]} 0x401234 = {0x90, 0x90}  # NOP the rdtsc

# 3. Pin tool to fix TSC reads
# 4. faketime library
LD_PRELOAD=/usr/lib/faketime/libfaketime.so.1 FAKETIME="2024-01-01" ./binary
```

### Signal-Based Anti-Debug

```c
// SIGTRAP handler — INT3 under debugger is caught by debugger, not handler
signal(SIGTRAP, handler);
__asm__("int3");
// If handler runs: no debugger. If debugger catches: debugged.

// SIGALRM timeout — kill self if analysis takes too long
signal(SIGALRM, kill_handler);
alarm(5);

// SIGSEGV handler that does real work (see patterns.md for MBA pattern)
signal(SIGSEGV, real_logic_handler);
*(int*)0 = 0;  // deliberate crash → handler runs real code
```

**Bypasses:**
```bash
# GDB: pass signals to program instead of handling them
(gdb) handle SIGTRAP nostop pass
(gdb) handle SIGALRM ignore
(gdb) handle SIGSEGV nostop pass

# For alarm-based: patch alarm() to return immediately
```

### Syscall-Level Evasion

```c
// Direct syscall instead of libc — bypasses LD_PRELOAD hooks
long ret;
asm volatile("syscall" : "=a"(ret) : "a"(101), "D"(0), "S"(0), "d"(0), "r"(0));
// Syscall 101 = ptrace on x86_64
```

**Bypass:** Must patch the binary itself or use ptrace to intercept at syscall level.
```bash
# GDB: catch syscall
(gdb) catch syscall 101
(gdb) commands
> set $rax = 0
> continue
> end
```

---

## Windows Anti-Debug (Advanced)

### PEB-Based Checks

```c
// BeingDebugged flag (offset 0x2 in PEB)
bool debugged = NtCurrentPeb()->BeingDebugged;

// NtGlobalFlag (offset 0x68/0xBC in PEB)
// When debugger: FLG_HEAP_ENABLE_TAIL_CHECK | FLG_HEAP_ENABLE_FREE_CHECK | FLG_HEAP_VALIDATE_PARAMETERS = 0x70
DWORD flags = *(DWORD*)((BYTE*)NtCurrentPeb() + 0xBC); // 64-bit offset
if (flags & 0x70) exit(1);
```

**Bypass (x64dbg):**
```text
# ScyllaHide plugin auto-patches PEB fields
# Manual: dump PEB, zero BeingDebugged and NtGlobalFlag
```

### NtQueryInformationProcess

```c
// ProcessDebugPort (0x7)
DWORD_PTR debugPort = 0;
NtQueryInformationProcess(GetCurrentProcess(), 7, &debugPort, sizeof(debugPort), NULL);
if (debugPort != 0) exit(1);

// ProcessDebugObjectHandle (0x1E)
HANDLE debugObj = NULL;
NTSTATUS status = NtQueryInformationProcess(GetCurrentProcess(), 0x1E, &debugObj, sizeof(debugObj), NULL);
if (status == 0) exit(1); // STATUS_SUCCESS means debugger present

// ProcessDebugFlags (0x1F) — returns inverse: 0 = debugger present
DWORD noDebug = 0;
NtQueryInformationProcess(GetCurrentProcess(), 0x1F, &noDebug, sizeof(noDebug), NULL);
if (noDebug == 0) exit(1);
```

**Bypass:** Hook `NtQueryInformationProcess` to return fake values, or use ScyllaHide.

### Heap Flags

```c
// Process heap has debug flags when debugger attached
PHEAP heap = (PHEAP)GetProcessHeap();
// Flags at offset 0x70 (64-bit): should be HEAP_GROWABLE (0x2)
// ForceFlags at offset 0x74: should be 0
if (heap->Flags != 0x2 || heap->ForceFlags != 0) exit(1);
```

### TLS Callbacks

**Key technique:** TLS (Thread Local Storage) callbacks execute BEFORE `main()` / entry point.

```c
// Registered in PE header's TLS directory
void NTAPI TlsCallback(PVOID DllHandle, DWORD Reason, PVOID Reserved) {
    if (Reason == DLL_PROCESS_ATTACH) {
        if (IsDebuggerPresent()) {
            ExitProcess(1);  // Kills process before main runs
        }
    }
}

#pragma comment(linker, "/INCLUDE:_tls_used")
#pragma data_seg(".CRT$XLB")
PIMAGE_TLS_CALLBACK callbacks[] = { TlsCallback, NULL };
```

**Detection in IDA/Ghidra:** Check PE TLS Directory → AddressOfCallBacks. Functions listed there run before EP.

**Bypass:** Set breakpoint on TLS callback in x64dbg (Options → Events → TLS Callbacks), or patch the TLS directory entry.

### Hardware Breakpoint Detection

```c
// Read debug registers via GetThreadContext
CONTEXT ctx;
ctx.ContextFlags = CONTEXT_DEBUG_REGISTERS;
GetThreadContext(GetCurrentThread(), &ctx);
if (ctx.Dr0 || ctx.Dr1 || ctx.Dr2 || ctx.Dr3) exit(1);

// Also via exception handler: deliberate exception, check DR regs in handler
```

**Bypass:**
```bash
# x64dbg: use software breakpoints instead, or hook GetThreadContext
# Frida: hook GetThreadContext to zero DR registers
```

### Software Breakpoint Detection (INT3 Scanning)

```c
// CRC / hash check over code section
unsigned char *code = (unsigned char*)function_addr;
uint32_t checksum = 0;
for (int i = 0; i < code_size; i++) {
    checksum += code[i];
    if (code[i] == 0xCC) exit(1);  // INT3 = software breakpoint
}
if (checksum != EXPECTED_CHECKSUM) exit(1);
```

**Bypass:** Use hardware breakpoints (DR0-DR3) instead of software breakpoints. Or hook the scanning function.

### Exception-Based Anti-Debug

```c
// UnhandledExceptionFilter — under debugger, filter is NOT called
SetUnhandledExceptionFilter(handler);
RaiseException(EXCEPTION_ACCESS_VIOLATION, 0, 0, NULL);
// If handler runs: no debugger
// If debugger catches: debugger present

// INT 2D — debugger single-step anomaly
__asm { int 2dh }  // Debugger silently consumes the exception
// If execution continues: debugger present
```

### NtSetInformationThread (Thread Hiding)

```c
// Hide thread from debugger — stops all debug events
typedef NTSTATUS(NTAPI *pNtSIT)(HANDLE, ULONG, PVOID, ULONG);
pNtSIT NtSIT = (pNtSIT)GetProcAddress(GetModuleHandle("ntdll"), "NtSetInformationThread");
NtSIT(GetCurrentThread(), 0x11 /*ThreadHideFromDebugger*/, NULL, 0);
// After this, debugger won't see breakpoints or exceptions from this thread
```

**Bypass:** Hook `NtSetInformationThread` to ignore class 0x11, or patch the call.

---

## Anti-VM / Anti-Sandbox

### CPUID Hypervisor Bit

```c
int regs[4];
__cpuid(regs, 1);
if (regs[2] & (1 << 31)) {  // ECX bit 31 = hypervisor present
    exit(1);
}

// Hypervisor brand string
__cpuid(regs, 0x40000000);
char brand[13] = {0};
memcpy(brand, &regs[1], 12);
// "VMwareVMware", "Microsoft Hv", "KVMKVMKVM", "XenVMMXenVMM"
```

**Bypass:** Patch `cpuid` results or use `LD_PRELOAD` to hook wrapper functions.

### MAC Address / Hardware Fingerprinting

```text
Known VM MAC prefixes:
  VMware:     00:0C:29, 00:50:56
  VirtualBox: 08:00:27
  Hyper-V:    00:15:5D
  Parallels:  00:1C:42
  QEMU:       52:54:00
```

### Timing-Based VM Detection

```c
// VM exits on privileged instructions are measurably slower
uint64_t start = __rdtsc();
__cpuid(regs, 0);  // Forces VM exit
uint64_t delta = __rdtsc() - start;
if (delta > 500) { /* likely VM */ }
```

### File / Registry Artifacts

```text
Files: C:\Windows\System32\drivers\vm*.sys, vbox*.dll, VBoxService.exe
Registry: HKLM\SOFTWARE\VMware, Inc.\VMware Tools
Services: VMTools, VBoxService
Processes: vmtoolsd.exe, VBoxTray.exe, qemu-ga.exe
Linux: /sys/class/dmi/id/product_name contains "VirtualBox"|"VMware"
       dmesg | grep -i "hypervisor detected"
```

### Resource Checks (CPU Count, RAM, Disk)

```c
// Sandboxes typically have minimal resources
SYSTEM_INFO si;
GetSystemInfo(&si);
if (si.dwNumberOfProcessors < 2) exit(1);

MEMORYSTATUSEX ms;
ms.dwLength = sizeof(ms);
GlobalMemoryStatusEx(&ms);
if (ms.ullTotalPhys < 2ULL * 1024 * 1024 * 1024) exit(1); // < 2GB RAM

// Disk size check (< 60GB = sandbox)
GetDiskFreeSpaceEx("C:\\", NULL, &total, NULL);
```

**Bypass:** Use a VM configured with adequate resources (4+ CPUs, 8GB+ RAM, 100GB+ disk).

---

## Anti-DBI (Dynamic Binary Instrumentation)

### Frida Detection

```c
// 1. Check /proc/self/maps for frida-agent
FILE *f = fopen("/proc/self/maps", "r");
while (fgets(line, sizeof(line), f)) {
    if (strstr(line, "frida") || strstr(line, "gadget")) exit(1);
}

// 2. Check for Frida's default port (27042)
int sock = socket(AF_INET, SOCK_STREAM, 0);
struct sockaddr_in addr = {.sin_family=AF_INET, .sin_port=htons(27042), .sin_addr.s_addr=inet_addr("127.0.0.1")};
if (connect(sock, (struct sockaddr*)&addr, sizeof(addr)) == 0) exit(1);

// 3. Check for inline hooks (function prologue modification)
// Compare first bytes of libc functions against expected values
unsigned char *strcmp_bytes = (unsigned char *)strcmp;
if (strcmp_bytes[0] == 0xE9 || strcmp_bytes[0] == 0xFF) exit(1); // JMP = hooked

// 4. Thread name check
// Frida creates threads with names like "gmain", "gdbus", "frida-*"
DIR *dir = opendir("/proc/self/task");
while ((entry = readdir(dir))) {
    char comm_path[256];
    snprintf(comm_path, sizeof(comm_path), "/proc/self/task/%s/comm", entry->d_name);
    // Read comm and check for "gmain", "gdbus"
}

// 5. Named pipe detection (Windows)
// Frida creates \\.\pipe\frida-* named pipes
```

**Frida bypass of Frida detection:**
```javascript
// Hook the detection functions themselves
Interceptor.attach(Module.findExportByName(null, "strstr"), {
    onEnter(args) {
        this.haystack = Memory.readUtf8String(args[0]);
        this.needle = Memory.readUtf8String(args[1]);
    },
    onLeave(retval) {
        if (this.needle && (this.needle.includes("frida") || this.needle.includes("gadget"))) {
            retval.replace(ptr(0)); // Not found
        }
    }
});

// Early Frida load (before anti-DBI runs)
// Use frida-gadget as early-init shared library
```

### Pin/DynamoRIO Detection

```c
// Check for instrumentation libraries in /proc/self/maps
// Pin: "pin-", "pinbin", "pinatrace"
// DynamoRIO: "dynamorio", "drcov", "drrun"

// Instruction count timing — DBI adds overhead
// Execute known instruction sequence, compare execution time
```

---

## Code Integrity / Self-Hashing

```c
// CRC32 over .text section
uint32_t crc = compute_crc32(text_start, text_size);
if (crc != EXPECTED_CRC) exit(1);  // Code was modified (breakpoints, patches)

// MD5/SHA256 of function bodies
unsigned char hash[32];
SHA256(function_addr, function_size, hash);
if (memcmp(hash, expected_hash, 32) != 0) exit(1);
```

**Bypasses:**
1. **Hardware breakpoints** (don't modify code, DR0-DR3)
2. **Patch the comparison** to always succeed
3. **Hook the hash function** to return expected value
4. **Emulate** instead of debug (Unicorn/Qiling — no code modification)
5. **Snapshot + restore:** dump memory before and after, diff to find checks

**Self-checksumming in loops:**
```c
// Continuous integrity check in separate thread
void *watchdog(void *arg) {
    while (1) {
        if (compute_crc32(text_start, text_end - text_start) != saved_crc) {
            memset(flag_buffer, 0, flag_len);  // Destroy flag
            exit(1);
        }
        usleep(100000);
    }
}
```
**Bypass:** Kill the watchdog thread or patch its sleep to infinite.

---

## Anti-Disassembly Techniques

### Opaque Predicates

```asm
; Condition that always evaluates the same way but looks data-dependent
mov eax, [some_memory]
imul eax, eax          ; x^2
and eax, 1             ; x^2 mod 2 is always 0 for any x
jnz fake_branch        ; Never taken, but disassembler doesn't know
; real code here
```

**Identification:** Z3/SMT can prove branch is always/never taken.

### Junk Bytes / Overlapping Instructions

```asm
jmp real_code
db 0xE8           ; Looks like start of CALL to linear disassembler
real_code:
mov eax, 1        ; Real code — disassembler may misalign here
```

**Fix:** Switch to graph-mode disassembly (Ghidra/IDA handle this well). Manual: undefine and re-analyze from correct offset.

### Jump-in-the-Middle

```asm
; Jumps into the middle of a multi-byte instruction
eb 01          ; jmp +1 (skip next byte)
e8             ; fake CALL opcode — disassembler tries to decode as call
90             ; real: NOP (landed here from jmp)
```

### Function Chunking / Scattered Code

Functions split into non-contiguous chunks connected by unconditional jumps. Defeats linear function boundary detection.

**Tool:** IDA's "Append function tail" or Ghidra's "Create function" at each chunk.

### Control Flow Flattening (Advanced)

Beyond basic switch-case (see patterns.md): modern OLLVM variants use:
- **Bogus control flow:** Fake branches with opaque predicates
- **Instruction substitution:** `a + b` → `a - (-b)`, `a ^ b` → `(a | b) & ~(a & b)`
- **String encryption:** Strings decrypted at runtime, cleared after use

**Deobfuscation tools:**
- **D-810** (IDA plugin): Pattern-based deobfuscation, MBA simplification
- **GOOMBA** (Ghidra): Automated deobfuscation for OLLVM
- **Miasm**: Symbolic execution for deobfuscation
- **Arybo** / **SiMBA**: MBA expression simplification

```bash
# D-810: install in IDA plugins directory, Edit → Plugins → D-810
# Simplifies MBA expressions: (a | b) & ~(a & b) → a ^ b
# Removes opaque predicates via pattern matching
```

### Mixed Boolean-Arithmetic (MBA) Identification & Simplification

```python
# Common MBA patterns and their simplified forms:
# (x & y) + (x | y) == x + y
# (x ^ y) + 2*(x & y) == x + y
# (x | y) - (x & ~y) == y
# ~(~x & ~y) == x | y (De Morgan's)
# (x | y) & ~(x & y) == x ^ y

# SiMBA tool for automated simplification:
# pip install simba-simplifier
from simba import simplify_mba
expr = "(a | b) + (a & b) - (~a & b)"
print(simplify_mba(expr))  # → a
```

---

## Comprehensive Bypass Strategies

### Universal Bypass Checklist

1. **Identify all anti-analysis checks** — search for: `ptrace`, `IsDebuggerPresent`, `rdtsc`, `cpuid`, `NtQuery`, `GetTickCount`, `CheckRemoteDebuggerPresent`, `/proc/self`, `SIGTRAP`, `alarm`
2. **Static patching** — NOP/patch checks with pwntools or Ghidra before running
3. **LD_PRELOAD** (Linux) — hook libc functions returning fake values
4. **ScyllaHide** (Windows x64dbg) — patches PEB, hooks NT functions automatically
5. **Emulation** (Unicorn/Qiling) — no debugger artifacts to detect
6. **Kernel-level bypass** — modify `/proc/sys/kernel/yama/ptrace_scope`, use `prctl`

### Layered Anti-Debug (Real-World Pattern)

Many CTF challenges stack multiple checks:
```text
1. TLS callback → IsDebuggerPresent (before main)
2. main() → ptrace(TRACEME)
3. Watchdog thread → timing check + /proc scan
4. Code section → self-CRC32 integrity
5. Signal handler → real logic in SIGSEGV handler
```

**Approach:** Identify ALL checks before patching. Patch or hook each one systematically. Run under emulator if too many to patch individually.

### Quick Reference: Check to Bypass

| Anti-Debug Check | Platform | Bypass |
|---|---|---|
| `ptrace(TRACEME)` | Linux | `LD_PRELOAD`, patch to `ret 0`, `catch syscall` |
| `IsDebuggerPresent` | Windows | ScyllaHide, Frida hook, PEB patch |
| `NtQueryInformationProcess` | Windows | ScyllaHide, hook ntdll |
| `rdtsc` timing | Both | NOP rdtsc, Frida time hook, Pin |
| `/proc/self/status` | Linux | Mount namespace, hook fopen |
| `alarm(N)` | Linux | `handle SIGALRM ignore` in GDB |
| `SIGTRAP` handler | Linux | `handle SIGTRAP nostop pass` |
| TLS callback | Windows | Break on TLS in x64dbg, patch |
| DR register scan | Windows | Use software BPs, hook GetThreadContext |
| INT3 scan / CRC | Both | Hardware BPs, patch CRC comparison |
| Frida detection | Both | Early-load gadget, hook strstr |
| CPUID hypervisor | Both | Patch CPUID result, bare metal |
| Thread hiding | Windows | Hook NtSetInformationThread |



---

<!-- Source: languages-compiled.md -->

# CTF Reverse - Compiled Language Reversing (Go, Rust)

## Table of Contents
- [Go Binary Reversing](#go-binary-reversing)
  - [Recognition](#recognition)
  - [Symbol Recovery](#symbol-recovery)
  - [Go Memory Layout](#go-memory-layout)
  - [Goroutine and Concurrency Analysis](#goroutine-and-concurrency-analysis)
  - [Common Go Patterns in Decompilation](#common-go-patterns-in-decompilation)
  - [Go Binary Reversing Workflow](#go-binary-reversing-workflow)
- [Rust Binary Reversing](#rust-binary-reversing)
  - [Recognition](#recognition-1)
  - [Symbol Demangling](#symbol-demangling)
  - [Common Rust Patterns in Decompilation](#common-rust-patterns-in-decompilation)
  - [Rust-Specific Analysis Tools](#rust-specific-analysis-tools)
- [Swift Binary Reversing](#swift-binary-reversing)
- [Kotlin / JVM Binary Reversing](#kotlin--jvm-binary-reversing)
  - [JVM Bytecode (Android/Server)](#jvm-bytecode-androidserver)
  - [Kotlin/Native](#kotlinnative)
- [C++ Binary Reversing (Quick Reference)](#c-binary-reversing-quick-reference)
  - [vtable Reconstruction](#vtable-reconstruction)
  - [RTTI (Run-Time Type Information)](#rtti-run-time-type-information)
  - [Standard Library Patterns](#standard-library-patterns)

---

## Go Binary Reversing

Go binaries are increasingly common in CTF challenges due to Go's popularity for CLI tools, network services, and malware.

### Recognition

```bash
# Detect Go binary
file binary | grep -i "go"
strings binary | grep "go.buildid"
strings binary | grep "runtime.gopanic"

# Go version embedded in binary
strings binary | grep "^go1\."
```

**Key indicators:**
- Very large static binary (even "hello world" is ~2MB)
- Embedded `go.buildid` string
- `runtime.*` symbols (even in stripped binaries, some remain)
- `main.main` as entry point (not `main`)
- Strings like `GOROOT`, `GOPATH`, `/usr/local/go/src/`

### Symbol Recovery

Go embeds rich type and function information even in stripped binaries:

```bash
# GoReSym - recovers function names, types, interfaces from Go binaries
# https://github.com/mandiant/GoReSym
./GoReSym -d binary > symbols.json

# Parse output
python3 -c "
import json
with open('symbols.json') as f:
    data = json.load(f)
for fn in data.get('UserFunctions', []):
    print(f\"{fn['Start']:#x}  {fn['FullName']}\")
"
```

**Ghidra with golang-loader:**
```bash
# Install: Ghidra → Window → Script Manager → search "golang"
# Or use: https://github.com/getCUJO/ThreatFox/tree/main/ghidra-golang
# Recovers function names, string references, interface tables
```

**redress (Go binary analysis):**
```bash
# https://github.com/goretk/redress
redress -src binary         # Reconstruct source tree
redress -pkg binary         # List packages
redress -type binary        # List types and methods
redress -interface binary   # List interfaces
```

### Go Memory Layout

Understanding Go's data structures in decompilation:

```c
# String: {pointer, length} (16 bytes on 64-bit)
# NOT null-terminated! Length field is critical.
struct GoString {
    char *ptr;    // pointer to UTF-8 data
    int64 len;    // byte length
};

# Slice: {pointer, length, capacity} (24 bytes on 64-bit)
struct GoSlice {
    void *ptr;    // pointer to backing array
    int64 len;    // current length
    int64 cap;    // allocated capacity
};

# Interface: {type_descriptor, data_pointer} (16 bytes)
struct GoInterface {
    void *type;   // points to type metadata (itab for non-empty interface)
    void *data;   // points to actual value
};

# Map: pointer to runtime.hmap struct
# Channel: pointer to runtime.hchan struct
```

**In Ghidra/IDA:** When you see a function taking `(ptr, int64)` — it's likely a Go string. Three-field `(ptr, int64, int64)` is a slice.

### Goroutine and Concurrency Analysis

```bash
# Identify goroutine spawns in disassembly
strings binary | grep "runtime.newproc"
# newproc1 is the internal goroutine creation function

# In GDB with Go support:
gdb ./binary
(gdb) source /usr/local/go/src/runtime/runtime-gdb.py
(gdb) info goroutines          # List all goroutines
(gdb) goroutine 1 bt          # Backtrace for goroutine 1
```

**Channel operations in disassembly:**
- `runtime.chansend1` → `ch <- value`
- `runtime.chanrecv1` → `value = <-ch`
- `runtime.selectgo` → `select { case ... }`
- `runtime.closechan` → `close(ch)`

### Common Go Patterns in Decompilation

**Defer mechanism:**
- `runtime.deferproc` → registers deferred function
- `runtime.deferreturn` → executes deferred functions at function exit
- Deferred calls execute in LIFO order — relevant for cleanup/crypto key wiping

**Error handling (the `if err != nil` pattern):**
```text
# In disassembly, this appears as:
# call some_function        → returns (result, error) as two values
# test rax, rax             → check if error (second return value) is nil
# jne error_handler
```

**String concatenation:**
- `runtime.concatstrings` → `s1 + s2 + s3`
- `fmt.Sprintf` → formatted string building
- Look for format strings in `.rodata`: `"%s%d"`, `"%x"`

**Common stdlib patterns in CTF:**
```go
// Crypto operations → look for these in strings/imports:
// "crypto/aes", "crypto/cipher", "crypto/sha256", "encoding/hex", "encoding/base64"

// Network operations:
// "net/http", "net.Dial", "bufio.NewReader"

// File operations:
// "os.Open", "io.ReadAll", "os.ReadFile"
```

### Go Binary Reversing Workflow

```bash
1. file binary                          # Confirm Go, get arch
2. GoReSym -d binary > syms.json       # Recover symbols
3. strings binary | grep -i flag        # Quick win check
4. Load in Ghidra with golang-loader    # Apply recovered symbols
5. Find main.main                       # Entry point
6. Identify string comparisons          # GoString {ptr, len} pairs
7. Trace crypto operations              # crypto/* package usage
8. Check for embedded resources         # embed.FS in Go 1.16+
```

**Go embed.FS (Go 1.16+):** Binaries can embed files at compile time:
```bash
# Look for embedded file data
strings binary | grep "embed"
# Embedded files appear as raw data in the binary
# Search for known file signatures (PK for zip, PNG header, etc.)
```

**Key insight:** Go's runtime embeds extensive metadata even in stripped binaries. Use GoReSym before any manual analysis — it often recovers 90%+ of function names, making decompilation dramatically easier. Go strings are `{ptr, len}` tuples, not null-terminated — Ghidra's default string analysis will miss them without the golang-loader plugin.

**Detection:** Large static binary (2MB+ for simple programs), `go.buildid`, `runtime.gopanic`, source paths like `/home/user/go/src/`.

---

## Rust Binary Reversing

Rust binaries are common in modern CTFs, especially for crypto, systems, and security tooling challenges.

### Recognition

```bash
# Detect Rust binary
strings binary | grep -c "rust"
strings binary | grep "rustc"             # Compiler version
strings binary | grep "/rustc/"           # Source paths
strings binary | grep "core::panicking"   # Panic infrastructure
```

**Key indicators:**
- `core::panicking::panic` in strings
- Mangled symbols starting with `_ZN` (Itanium ABI) — e.g., `_ZN4main4main17h...`
- `.rustc` section in ELF
- References to `/rustc/<commit_hash>/library/`
- Large binary size (Rust statically links by default)

### Symbol Demangling

```bash
# Rust uses Itanium ABI mangling (same as C++)
# rustfilt demangles Rust-specific symbols
cargo install rustfilt
nm binary | rustfilt | grep "main"

# Or use c++filt (works for most Rust symbols)
nm binary | c++filt | grep "main"

# In Ghidra: Window → Script Manager → search "Demangler"
# Enable "DemangleAllScript" for automatic demangling
```

### Common Rust Patterns in Decompilation

**Option/Result enum:**
```text
# Option<T> in memory: {discriminant (0=None, 1=Some), value}
# Result<T, E>: {discriminant (0=Ok, 1=Err), union{ok_val, err_val}}

# In disassembly:
# cmp byte [rbp-0x10], 0    → check if None/Err
# je handle_none_case
```

**Vec<T> (same as Go slice):**
```c
struct RustVec {
    void *ptr;      // heap pointer
    uint64 cap;     // capacity
    uint64 len;     // length
};
```

**String / &str:**
```text
# String (owned): {ptr, capacity, length} — 24 bytes, heap-allocated
# &str (borrowed): {ptr, length} — 16 bytes, can point anywhere

# In decompilation, look for:
# alloc::string::String::from    → String creation
# core::str::from_utf8           → byte slice to str
```

**Iterator chains:**
```text
# .iter().map().filter().collect() compiles to loop fusion
# In disassembly: tight loop with inlined closures
# Look for: core::iter::adapters::map, filter, etc.
```

**Panic unwinding:**
```bash
# Panic strings reveal source locations and error messages
strings binary | grep "panicked at"
strings binary | grep "called .unwrap().. on"
# These often contain file paths, line numbers, and variable names
```

### Rust-Specific Analysis Tools

```bash
# cargo-bloat: analyze binary size by function
cargo install cargo-bloat
cargo bloat --release -n 50

# Ghidra Rust helper scripts
# https://github.com/AmateursCTF/ghidra-rust (community scripts for Rust RE)
```

**Key insight:** Rust panic messages are goldmines — they contain source file paths, line numbers, and descriptive error strings even in release builds. Always `strings binary | grep "panicked"` first. Rust's monomorphization means generic functions get duplicated per type — expect many similar-looking functions.

**Detection:** `core::panicking`, `.rustc` section, `/rustc/` paths, `_ZN` mangled symbols with Rust-style module paths.

---

## Swift Binary Reversing

See [platforms.md](platforms.md#swift-binary-reversing) for full Swift reversing guide including demangling, runtime structures, and Ghidra integration. Key quick reference:

```bash
# Detect Swift binary
strings binary | grep "swift"
otool -l binary | grep "swift"

# Demangle Swift symbols
swift demangle 's14MyApp0A8ClassC10checkInput6resultSbSS_tF'
# → MyApp.MyAppClass.checkInput(result: String) -> Bool

# Key runtime functions: swift_allocObject, swift_release, swift_once
# String: small (≤15 bytes inline) or large (heap pointer + length)
# Protocol witness tables = dynamic dispatch (like vtables)
```

**Detection:** `__swift5_*` sections in Mach-O, `swift_` runtime symbols, `s` prefix in mangled names.

---

## Kotlin / JVM Binary Reversing

Kotlin compiles to JVM bytecode or native (via Kotlin/Native). Common in Android and server-side CTF.

### JVM Bytecode (Android/Server)

```bash
# Detect Kotlin
strings classes.dex | grep "kotlin"
# Look for: kotlin.Metadata annotation, kotlin/jvm/internal/*

# Decompile
jadx classes.dex                     # Best for Kotlin bytecode
cfr classes.jar --kotlin             # CFR with Kotlin mode
fernflower classes.jar output/       # IntelliJ's decompiler

# Kotlin-specific patterns in decompiled output:
# - Companion objects: ClassName$Companion
# - Data classes: copy(), component1(), component2(), toString()
# - Coroutines: ContinuationImpl, invokeSuspend, state machine
# - Null checks: Intrinsics.checkNotNull() everywhere
# - When expression: compiled as tableswitch/lookupswitch
# - Sealed classes: instanceof checks in chain
```

**Kotlin coroutines in disassembly:**
```text
# Coroutines compile to state machines:
# invokeSuspend(result) {
#     switch (this.label) {
#         case 0: this.label = 1; return suspendFunction();
#         case 1: processResult(result); return Unit;
#     }
# }
# Each suspend point becomes a state in the switch.
# Follow the state machine to understand async flow.
```

### Kotlin/Native

```bash
# Kotlin/Native produces platform binaries (no JVM)
# Recognize by: konan, kotlin.native strings
strings binary | grep "konan"

# Much harder to reverse — no reflection metadata
# Uses LLVM backend, looks similar to C/C++ in disassembly
# Key functions: InitRuntime, DeinitRuntime, CreateStablePointer
# Memory management: automatic reference counting (not GC)
```

**Detection:** `kotlin.Metadata` annotations (JVM), `konan` strings (Native), `kotlin/` package paths.

---

## C++ Binary Reversing (Quick Reference)

While C++ RE is well-covered by general tools, these patterns are CTF-specific:

### vtable Reconstruction

```text
# Virtual function tables (vtables):
# First 8 bytes of object → pointer to vtable
# vtable entries: [typeinfo_ptr, destructor, method1, method2, ...]
# In Ghidra: Data → Create Pointer at vtable address

# Identify polymorphic dispatch:
# mov rax, [rdi]           # Load vtable from this pointer
# call [rax + 0x18]        # Call 4th virtual method (0x18/8 = 3rd after typeinfo+dtor)
```

### RTTI (Run-Time Type Information)

```bash
# If not stripped, RTTI reveals class hierarchy
strings binary | grep -E "^[0-9]+[A-Z]"   # Mangled type names
c++filt _ZTI7MyClass                        # → typeinfo for MyClass

# In Ghidra: search for vtable references, follow typeinfo pointer
# typeinfo struct: {vtable_for_typeinfo, name_string, base_class_ptr}
```

### Standard Library Patterns

```text
std::string (libstdc++):
  SSO (Small String Optimization): inline buffer for ≤15 chars
  Layout: {char* ptr, size_t size, union{size_t cap, char buf[16]}}

std::vector<T>:
  {T* begin, T* end, T* capacity_end}

std::map<K,V>:
  Red-black tree: each node has {left, right, parent, color, key, value}

std::unordered_map<K,V>:
  Hash table: {bucket_array, size, load_factor_max, ...}
```

---

## `.pyc` PEP-552 Magic-Header Forgery (source: pwn.college AoP 2025 day 9)

**Trigger:** loader validates the first 16 bytes of a `.pyc` (magic + timestamp + source-hash tag) but doesn't verify the bytecode body.
**Signals:** custom `importlib.abc.Loader` that checks `data[:16]`; no `hashlib` call on `data[16:]`.
**Mechanic:** Python 3.7+ PEP-552 pyc layout: `4B magic | 4B flags | 8B (timestamp+size OR hash)`. Prepend the expected header verbatim, append attacker bytecode, loader accepts. Trivial template:
```python
import importlib.util, marshal
magic = importlib.util.MAGIC_NUMBER
with open('out.pyc','wb') as f:
    f.write(magic + b'\x00\x00\x00\x00' + b'\x00'*8 + marshal.dumps(my_code))
```

## Go Interface/itab Restore via GoReSym (source: HTB University 2025 Starshard Reassembly)

**Trigger:** Go binary with interface-typed method calls (`itab` tables); standard `strings`/`objdump` yield little; Go runtime typelinks intact.
**Signals:** `runtime.itab` symbol present; `go.funcinfo.*` section; dispatch through `[itab+OFF]`.
**Mechanic:** run `GoReSym` or `go-symbol-restore` — recovers the typelinks table and resolves each `itab` to its concrete type + method set. Feed into Ghidra with type propagation to see virtual dispatch as plain calls. Pattern applies to any stripped Go 1.18+ binary.

## eBPF kprobe FSM Gated by Syscall Sequence (source: pwn.college AoP 2025 day 4)

**Trigger:** eBPF attached to a kprobe that mutates a `BPF_MAP_TYPE_HASH` based on syscall arg hashes; flag only releases when map reaches a specific state.
**Signals:** `bpftool prog list` non-standard entry; `bpftool prog dump xlated id N` shows state-machine transitions.
**Mechanic:** see `ctf-pwn/sandbox-escape.md` cross-ref for the same technique from the pwn angle. For RE: lift bytecode via angr's `bpf-ir` loader, symbolic-execute to find a sequence of `(syscall, arg)` tuples reaching accept state.



---

<!-- Source: languages.md -->

# CTF Reverse - Language & Platform-Specific Techniques

## Table of Contents
- [Python Bytecode Reversing (dis.dis output)](#python-bytecode-reversing-disdis-output)
  - [Common Pattern: XOR Validation with Split Indices](#common-pattern-xor-validation-with-split-indices)
  - [Bytecode Analysis Tips](#bytecode-analysis-tips)
- [Python Opcode Remapping](#python-opcode-remapping)
  - [Identification](#identification)
  - [Recovery](#recovery)
- [Pyarmor 8/9 Static Unpack (1shot)](#pyarmor-89-static-unpack-1shot)
- [DOS Stub Analysis](#dos-stub-analysis)
- [Unity IL2CPP Games](#unity-il2cpp-games)
- [HarmonyOS HAP/ABC Reverse (abc-decompiler)](#harmonyos-hapabc-reverse-abc-decompiler)
- [Brainfuck/Esolangs](#brainfuckesolangs)
- [UEFI Binary Analysis](#uefi-binary-analysis)
- [Transpilation to C](#transpilation-to-c)
- [Code Coverage Side-Channel Attack](#code-coverage-side-channel-attack)
- [Functional Language Reversing (OPAL)](#functional-language-reversing-opal)
- [Python Version-Specific Bytecode (VuwCTF 2025)](#python-version-specific-bytecode-vuwctf-2025)
- [Non-Bijective Substitution Cipher Reversing](#non-bijective-substitution-cipher-reversing)
- [Roblox Place File Analysis](#roblox-place-file-analysis)
- [Godot Game Asset Extraction](#godot-game-asset-extraction)
- [Rust serde_json Schema Recovery](#rust-serde_json-schema-recovery)
- [Android JNI RegisterNatives Obfuscation (HTB WonderSMS)](#android-jni-registernatives-obfuscation-htb-wondersms)
- [Verilog/Hardware Reverse Engineering (srdnlenCTF 2026)](#veriloghardware-reverse-engineering-srdnlenctf-2026)
- [Prefix-by-Prefix Hash Reversal (Nullcon 2026)](#prefix-by-prefix-hash-reversal-nullcon-2026)
- [Ruby/Perl Polyglot Constraint Satisfaction (BearCatCTF 2026)](#rubyperl-polyglot-constraint-satisfaction-bearcatctf-2026)
- [Electron App + Native Binary Reversing (RootAccess2026)](#electron-app--native-binary-reversing-rootaccess2026)
- [Node.js npm Package Runtime Introspection (RootAccess2026)](#nodejs-npm-package-runtime-introspection-rootaccess2026)

For Go and Rust binary reversing, see [languages-compiled.md](languages-compiled.md).

---

## Python Bytecode Reversing (dis.dis output)

### Common Pattern: XOR Validation with Split Indices

Challenge gives raw CPython bytecode (dis.dis disassembly). Common pattern:
1. Check flag length
2. XOR chars at even indices with key1, compare to list p1
3. XOR chars at odd indices with key2, compare to list p2

**Reversing:**
```python
# Given: p1, p2 (expected values), key1, key2 (XOR keys)
flag = [''] * flag_length
for i in range(len(p1)):
    flag[2*i] = chr(p1[i] ^ key1)      # Even indices
    flag[2*i+1] = chr(p2[i] ^ key2)    # Odd indices
print(''.join(flag))
```

### Bytecode Analysis Tips
- `LOAD_CONST` followed by `COMPARE_OP` reveals expected values
- `BINARY_XOR` identifies the transformation
- `BUILD_TUPLE`/`BUILD_LIST` with constants = expected output array
- Loop structure: `FOR_ITER` + `BINARY_SUBSCR` = iterating over flag chars
- `CALL_FUNCTION` on `ord` = character-to-int conversion

---

## Python Opcode Remapping

### Identification
Decompiler fails with opcode errors.

### Recovery
1. Find modified `opcode.pyc` in PyInstaller bundle
2. Compare with original Python opcodes
3. Build mapping: `{new_opcode: original_opcode}`
4. Patch target .pyc
5. Decompile normally

**Shortcut (Hack.lu CTF 2013):** If the challenge bundles its own modified Python interpreter (e.g., a custom `./py` binary), install `uncompyle2`/`uncompyle6` into that interpreter's environment and decompile using the challenge's own runtime. The modified interpreter understands its own opcode mapping, so standard decompilation tools work without manual opcode recovery.

---

## Pyarmor 8/9 Static Unpack (1shot)

- Tool: `Lil-House/Pyarmor-Static-Unpack-1shot`
- Use for Pyarmor 8.x/9.x armored scripts without executing sample code
- Quick signature check: payload typically starts with `PY` + six digits (Pyarmor 7 and earlier `PYARMOR` format is not supported)

Workflow:
1. Ensure target directory contains armored scripts and matching `pyarmor_runtime` library.
2. Run one-shot unpack to emit `.1shot.` outputs (disassembly + experimental decompile).
3. Treat disassembly as ground truth; verify decompiled source with bytecode when inconsistent.

```bash
python /path/to/oneshot/shot.py /path/to/scripts
```

Optional flags:
```bash
# Specify runtime explicitly
python /path/to/oneshot/shot.py /path/to/scripts -r /path/to/pyarmor_runtime.so

# Write outputs to another directory
python /path/to/oneshot/shot.py /path/to/scripts -o /path/to/output
```

Notes:
- `oneshot/pyarmor-1shot` executable must exist before running `shot.py`.
- PyInstaller bundles or archives should be unpacked first, then processed with 1shot.

---

## DOS Stub Analysis

PE files can hide code in DOS stub:
1. Check for large DOS stub in Ghidra/IDA
2. Run in DOSBox
3. Load in IDA as 16-bit DOS
4. Look for `int 16h` (keyboard input)

---

## Unity IL2CPP Games

- Use Il2CppDumper to dump symbols
- If Il2CppDumper fails, consider that `global-metadata.dat` may be encrypted; search strings/xrefs in the main binary and inspect the metadata loading path for custom decryption before dump.
- Look for `Start()` functions
- Key derivation: `key = SHA256(companyName + "\n" + productName)`
- Decrypt server responses with derived key

Please note most of that the executable file for the PC platform is GameAssembly.dll or *Assembly.dll, for the Android is libil2cpp.so.

---

## HarmonyOS HAP/ABC Reverse (abc-decompiler)

- Target files: `.hap` package and embedded `.abc` bytecode
- Tool: `https://github.com/ohos-decompiler/abc-decompiler`
- Download `jadx-dev-all.jar` from releases

Critical startup note:
- `java -jar` may enter GUI mode
- For CLI mode, always use:

```bash
java -cp "./jadx-dev-all.jar" jadx.cli.JadxCLI [options] <input>
```

Most common commands:
```bash
# Basic decompile to directory
java -cp "./jadx-dev-all.jar" jadx.cli.JadxCLI -d "out" ".abc"

# Decompile .abc (recommended for this scenario)
java -cp "./jadx-dev-all.jar" jadx.cli.JadxCLI -m simple -d "out_hap" "modules.abc"
```

Recommended parameters for this challenge:
- `-m simple`: reduce high-level reconstruction to avoid SSA/PHI-heavy failures
- `--log-level ERROR`: keep only critical errors
- Full recommended command:

```bash
java -cp "./jadx-dev-all.jar" jadx.cli.JadxCLI -m simple --log-level ERROR -d "out_abc_simple" "modules.abc"
```

Parameter quick reference:
- `-d` output directory
- `--help` help

Notes:
- `.hap` is a package: extract it first (zip), then locate and analyze `.abc`
- Quote paths containing spaces or non-ASCII characters
- Use a new output directory name per run to avoid stale results
- Errors do not always mean full failure; prioritize `out_xxx/sources/`
- If `auto` fails, switch to `-m simple` first

Standard workflow:
1. Run with `-m simple --log-level ERROR`
2. Inspect key business files in output (for example `pages/Index.java`)
3. If cleaner output is needed, retry with `-m auto` or `-m restructure`
4. If some methods still fail, keep the `simple` output and continue logic analysis via alternate paths

---

## Brainfuck/Esolangs

- Check if compiled with known tools (BF-it)
- Understand tape/memory model
- Static analysis of cell operations

---

## UEFI Binary Analysis

```bash
7z x firmware.bin -oextracted/
file extracted/* | grep "PE32+"
```

- Bootkit replaces boot loader
- Custom VM protects decryption
- Lift VM bytecode to C

---

## Transpilation to C

For heavily obfuscated code:
```python
for opcode, args in instructions:
    if opcode == 'XOR':
        print(f"r{args[0]} ^= r{args[1]};")
    elif opcode == 'ADD':
        print(f"r{args[0]} += r{args[1]};")
```

Compile with `-O3` for constant folding.

---

## Code Coverage Side-Channel Attack

**Pattern (Coverup, Nullcon 2026):** PHP challenge provides XDebug code coverage data alongside encrypted output.

**How it works:**
- PHP code uses `xdebug_start_code_coverage(XDEBUG_CC_UNUSED | XDEBUG_CC_DEAD_CODE | XDEBUG_CC_BRANCH_CHECK)`
- Encryption uses data-dependent branches: `if ($xored == chr(0)) ... if ($xored == chr(1)) ...`
- Coverage JSON reveals which branches were executed during encryption
- This leaks the set of XOR intermediate values that occurred

**Exploitation:**
```python
import json

# Load coverage data
with open('coverage.json') as f:
    cov = json.load(f)

# Extract executed XOR values from branch coverage
executed_xored = set()
for line_no, hit_count in cov['encrypt.php']['lines'].items():
    if hit_count > 0:
        # Map line numbers to the chr(N) value in the if-statement
        executed_xored.add(extract_value_from_line(line_no))

# For each position, filter candidates
for pos in range(len(ciphertext)):
    candidates = []
    for key_byte in range(256):
        xored = plaintext_byte ^ key_byte  # or reverse S-box lookup
        if xored in executed_xored:
            candidates.append(key_byte)
    # Combined with known plaintext prefix, this uniquely determines key
```

**Key insight:** Code coverage is a powerful oracle — it tells you which conditional paths were taken. Any encryption with data-dependent branching leaks information through coverage.

**Mitigation detection:** Look for branchless/constant-time crypto implementations that defeat this attack.

---

## Functional Language Reversing (OPAL)

**Pattern (Opalist, Nullcon 2026):** Binary compiled from OPAL (Optimized Applicative Language), a purely functional language.

**Recognition markers:**
- `.impl` (implementation) and `.sign` (signature) source files
- `IMPLEMENTATION` / `SIGNATURE` keywords
- Nested `IF..THEN..ELSE..FI` structures
- Functions named `f1`, `f2`, ... `fN` (numeric naming)
- Heavy use of `seq[nat]`, `string`, `denotation` types

**Reversing approach:**
1. Pure functions are mathematically invertible — reverse each step in the pipeline
2. Identify the transformation chain: `f_final(f_n(...f_2(f_1(input))...))`
3. For each function, build the inverse

**Aggregate brute-force for scramble functions:**
When a transformation accumulates state that depends on original (unknown) values:
```python
# Example: f8 adds cumulative offset based on parity of original bytes
# offset contribution per element depends on whether pre-scramble value is even/odd
# Total offset S = sum of contributions, but S mod 256 has only 256 possibilities

decoded = base64_decode(target)
for total_offset_S in range(256):
    candidate = [(b - total_offset_S) % 256 for b in decoded]
    # Verify: recompute S from candidate values
    recomputed_S = sum(contribution(i, candidate[i]) for i in range(len(candidate))) % 256
    if recomputed_S == total_offset_S:
        # Apply remaining inverse steps
        result = apply_inverse_substitution(candidate)
        if all(32 <= c < 127 for c in result):
            print(bytes(result))
```

**Key lesson:** When a scramble function has a chicken-and-egg dependency (result depends on original, which is unknown), brute-force the aggregate effect (often mod 256 = 256 possibilities) rather than all possible states (exponential).

---

## Python Version-Specific Bytecode (VuwCTF 2025)

**Pattern (A New Machine):** Challenge targets specific Python version (e.g., 3.14.0 alpha).

**Key requirement:** Compile that exact Python version to disassemble bytecode — alpha/beta versions have different opcodes than stable releases.

```bash
# Build specific Python version
wget https://www.python.org/ftp/python/3.14.0/Python-3.14.0a4.tar.xz
tar xf Python-3.14.0a4.tar.xz
cd Python-3.14.0a4 && ./configure && make -j$(nproc)
./python -c "import dis, marshal; dis.dis(marshal.loads(open('challenge.pyc','rb').read()[16:]))"
```

**Common validation:** Flag compared against tuple of squared ASCII values:
```python
# Reverse: flag[i] = sqrt(expected_tuple[i])
import math
flag = ''.join(chr(int(math.isqrt(v))) for v in expected_values)
```

---

## Non-Bijective Substitution Cipher Reversing

**Pattern (Coverup, Nullcon 2026):** S-box/substitution table has collisions (multiple inputs map to same output).

**Detection:**
```python
sbox = [...]  # substitution table
if len(set(sbox)) < len(sbox):
    print("Non-bijective! Collisions exist.")
```

**Building reverse lookup:**
```python
from collections import defaultdict
rev_sub = defaultdict(list)
for i, v in enumerate(sbox):
    rev_sub[v].append(i)
# rev_sub[output] = [list of possible inputs]
```

**Disambiguation strategies:**
1. Known plaintext format (e.g., `ENO{`, `flag{`) fixes key bytes at known positions
2. Side-channel data (code coverage, timing) eliminates impossible candidates
3. Printable ASCII constraint (32-126) reduces candidate space
4. Re-encrypt candidates and verify against known ciphertext

---

## Roblox Place File Analysis

**Pattern (MazeRunna, 0xFun 2026):** Roblox game with flag hidden in older version; latest version contains decoy.

**Version history via Asset Delivery API:**
```bash
# Extract placeId and universeId from game page HTML
# Query each version (requires .ROBLOSECURITY cookie):
curl -H "Cookie: .ROBLOSECURITY=..." \
  "https://assetdelivery.roblox.com/v2/assetId/{placeId}/version/1"
# Download location URL → place_v1.rbxlbin
```

**Binary format parsing:** `.rbxlbin` files contain chunks:
- **INST** — class buckets and referent IDs
- **PROP** — per-instance fields (including `Script.Source`)
- **PRNT** — parent-child relationships (object tree)

Decode chunk payloads, walk PROP entries for `Source` field, dump `Script.Source` / `LocalScript.Source` per version, then diff.

**Key lesson:** Always check version history. Latest version may contain decoy flag while real flag is in an older version. Diff script sources across versions.

---

## Godot Game Asset Extraction

**Pattern (Steal the Xmas):** Encrypted Godot .pck packages.

**Tools:**
- [gdsdecomp](https://github.com/GDRETools/gdsdecomp) - Extract Godot packages
- [KeyDot](https://github.com/Titoot/KeyDot) - Extract encryption key from Godot executables

**Workflow:**
1. Run KeyDot against game executable → extract encryption key
2. Input key into gdsdecomp
3. Extract and open project in Godot editor
4. Search scripts/resources for flag data

---

## Rust serde_json Schema Recovery

**Pattern (Curly Crab, PascalCTF 2026):** Rust binary reads JSON from stdin, deserializes via serde_json, prints success/failure emoji.

**Approach:**
1. Disassemble serde-generated `Visitor` implementations
2. Each visitor's `visit_map` / `visit_seq` reveals expected keys and types
3. Look for string literals in deserializer code (field names like `"pascal"`, `"CTF"`)
4. Reconstruct nested JSON schema from visitor call hierarchy
5. Identify value types from visitor method names: `visit_str` = string, `visit_u64` = number, `visit_bool` = boolean, `visit_seq` = array

```json
{"pascal":"CTF","CTF":2026,"crab":{"I_":true,"cr4bs":1337,"crabby":{"l0v3_":["rust"],"r3vv1ng_":42}}}
```

**Key insight:** Flag is the concatenation of JSON keys in schema order. Reading field names in order reveals the flag.

---

## Verilog/Hardware Reverse Engineering (srdnlenCTF 2026)

**Pattern (Rev Juice):** Verilog HDL source for a vending machine with hidden product unlocked by specific coin insertion and selection sequence.

**Approach:**
1. Analyze Verilog modules to understand state machine and history tracking
2. Identify hidden conditions (e.g., product 8 enabled only when `COINS_HISTORY` array has specific values at specific taps)
3. Build timing model for each action type (how many clock cycles each operation takes)
4. Work backward from required history values to construct the correct input sequence

**Timing model construction:**
```python
# Map each action to its cycle count (determined from Verilog state machines)
TIMING = {
    "insert_coin": 3,       # 3 cycles per coin insertion
    "select_success": 7,    # 7 cycles for successful product selection
    "select_fail": 5,       # 5 cycles for failed selection attempt
    "cancel_with_coins": 4, # 4 cycles for cancel when coins > 0
    "cancel_at_zero": 2,    # 2 cycles for cancel when coins = 0
}

# COINS_HISTORY is a shift register updated each cycle
# History tap requirements (from Verilog conditions):
# H[0]=1, H[7]=4, H[28]=H[33]=H[38]=6
# H[63]=H[73]=2, H[80]=9
# (H[19]+H[21]+H[56]+H[69]) mod 32 = 0
```

**Key insight:** Hardware challenges require understanding the exact timing model — each operation takes a specific number of clock cycles, and shift registers record history at fixed tap positions. Work backward from the required tap values to determine what action must have occurred at each cycle. The solution is often a specific sequence notation (e.g., `I9C_SP6_CNL_I2C_SP2_I6C_SP6_SP6_SP5_CNL_I4C_SP1`).

**Detection:** Look for `.v` or `.sv` (Verilog/SystemVerilog) files, `always @(posedge clk)` blocks, shift register patterns, and state machine `case` statements with hidden conditions gated on history values.

---

## Prefix-by-Prefix Hash Reversal (Nullcon 2026)

See [patterns-ctf-2.md](patterns-ctf-2.md#prefix-hash-brute-force-nullcon-2026) for the full technique. This section covers language-specific considerations.

**Language-specific notes:**
- Hash algorithm may be uncommon (MD2, custom) — don't need to identify it, just match outputs by running the binary
- Use `subprocess.run()` with `timeout=2` to handle binaries that hang on bad input
- For stripped binaries, check if `ltrace` reveals the hash function name (e.g., `MD2_Update`)

---

## Android JNI RegisterNatives Obfuscation (HTB WonderSMS)

**Pattern:** Android app loads native library with `System.loadLibrary()`, but uses `RegisterNatives` in `JNI_OnLoad` instead of standard JNI naming convention (`Java_com_pkg_Class_method`). This hides which C++ function handles each Java native method.

**Identification:**
```java
// In decompiled Java (jadx):
static { System.loadLibrary("audio"); }
private final native ProcessedMessage processMessage(SmsMessage msg);
```
Standard JNI would have a symbol `Java_com_rloura_wondersms_SmsReceiver_processMessage`. If that symbol is missing from the `.so`, `RegisterNatives` is being used.

**Finding the real handler in Ghidra:**
1. Locate `JNI_OnLoad` (exported symbol, always present)
2. Trace to `RegisterNatives(env, clazz, methods, count)` call
3. The `methods` array contains `{name, signature, fnPtr}` structs
4. Follow `fnPtr` to find the actual native function

```c
// JNI_OnLoad registers functions manually:
static JNINativeMethod methods[] = {
    {"processMessage", "(Landroid/telephony/SmsMessage;)LProcessedMessage;", (void*)real_handler}
};
(*env)->RegisterNatives(env, clazz, methods, 1);
```

**Architecture selection for analysis:**
```bash
# x86_64 gives best Ghidra decompilation (most similar to desktop code)
# Extract from APK:
unzip WonderSMS.apk -d extracted/
ls extracted/lib/x86_64/  # Prefer this over arm64-v8a for static analysis
```

**Key insight:** `RegisterNatives` is a deliberate obfuscation technique — it decouples Java method names from native symbol names, making it impossible to find handlers by string search alone. Always check `JNI_OnLoad` first when reversing Android native libraries with stripped symbols.

**Detection:** Native method declared in Java + no matching JNI symbol in `.so` + `JNI_OnLoad` present. The library is typically stripped (no debug symbols).

---

## Ruby/Perl Polyglot Constraint Satisfaction (BearCatCTF 2026)

**Pattern (Polly's Key):** A single file valid in both Ruby and Perl. Each language imposes different validation constraints on a 50-character key. Satisfy both simultaneously to decrypt the flag.

**Polyglot structure exploits:**
- Ruby: `=begin`...`=end` is a block comment
- Perl: `=begin`...`=cut` is POD (Plain Old Documentation), `=end` is ignored
- Different code runs in each language based on comment block boundaries

**Typical constraints:**
- **Ruby:** Character set must form a mathematical property (e.g., all 50 printable ASCII chars except `^` used exactly once, each satisfying `XOR(val, (val-16) % 257)` is a primitive root mod 257)
- **Perl:** Ordering constraint via insertion sort inversion count (hardcoded inversion table determines exact permutation)

**Solution approach:**
1. Find the valid character set (mathematical constraint from one language)
2. Use the ordering constraint (from other language) to determine exact arrangement
3. Compute key hash (e.g., MD5) and decrypt

```python
# Determine character ordering from inversion counts
def reconstruct_from_inversions(chars, inv_counts):
    result = []
    remaining = sorted(chars)
    for i in range(len(chars) - 1, -1, -1):
        # inv_counts[i] = number of elements to the left that are greater
        idx = inv_counts[i]
        result.insert(idx, remaining.pop(i))
    return result
```

**Key insight:** Polyglot files exploit language-specific comment/block syntax to run different code in each interpreter. The constraints from both languages intersect to uniquely determine the key. Identify which code runs in which language by testing the file with both interpreters and comparing behavior.

**Detection:** File that runs under multiple interpreters (`ruby file && perl file`). Challenge mentions "polyglot" or provides a file ending in `.rb` that also looks like Perl.

---

## Electron App + Native Binary Reversing (RootAccess2026)

**Pattern (Rootium Browser):** Electron desktop app bundles a native ELF/DLL binary for sensitive operations (vault, crypto, auth). The Electron layer is a wrapper; the real flag logic is in the native binary.

**Extraction workflow:**
1. **Unpack Electron ASAR archive:**
```bash
# Install ASAR tool
npm install -g @electron/asar

# Extract the app.asar archive
asar extract resources/app.asar app_extracted/
ls app_extracted/
```

2. **Locate native binary:** Search for ELF/DLL files called from JavaScript:
```bash
# Find native binaries
find app_extracted/ -name "*.node" -o -name "*.so" -o -name "*vault*" -o -name "*auth*"

# Check JS for child_process.spawn or ffi-napi calls
grep -r "spawn\|execFile\|ffi\|require.*native" app_extracted/
```

3. **Reverse the native binary** (XOR + rotation cipher example):
```python
def decrypt_password(encrypted_bytes, key):
    """Common pattern: XOR with constant + bit rotation + key XOR."""
    result = []
    for i, byte in enumerate(encrypted_bytes):
        decrypted = ((byte ^ 0x42) >> 3) ^ key[i % len(key)]
        result.append(chr(decrypted))
    return ''.join(result)

def decrypt_flag(encrypted_flag, password):
    """Flag uses password as key with position-dependent rotation."""
    result = []
    for i, byte in enumerate(encrypted_flag):
        key_byte = ord(password[i % len(password)])
        decrypted = ((byte ^ 0x7E) >> (i % 8)) ^ key_byte
        result.append(chr(decrypted))
    return ''.join(result)
```

**Key insight:** Electron apps are JavaScript wrapping native code. Extract with `asar`, then focus on the native binary. The JS layer often contains the password verification flow in plaintext, revealing what the native binary expects. Look for encrypted data in the `.data` or `.rodata` sections of the ELF.

**Detection:** `.asar` files in `resources/` directory, Electron framework files, `package.json` with electron dependency.

---

## Node.js npm Package Runtime Introspection (RootAccess2026)

**Pattern (RootAccess CLI):** Obfuscated npm package with RC4 encoding, control flow flattening, and flag split across multiple fragments. Static analysis is impractical — use runtime introspection instead.

**Dynamic analysis approach:**
```javascript
#!/usr/bin/env node

// 1. Load obfuscated modules
const cryptoMod = require('target-package/dist/lib/crypto.js');
const vaultMod = require('target-package/dist/lib/vault.js');

// 2. Enumerate all exported properties
for (const mod of [cryptoMod, vaultMod]) {
    for (const key of Object.keys(mod)) {
        const obj = mod[key];
        console.log(`Export: ${key}`);
        // List all methods including hidden ones
        const props = Object.getOwnPropertyNames(obj);
        const proto = Object.getOwnPropertyNames(obj.prototype || {});
        console.log('  Own:', props);
        console.log('  Proto:', proto);
    }
}

// 3. Extract flag fragments
const Engine = cryptoMod.CryptoEngine;
const total = Engine.getTotalFragments();
let flag = '';
for (let i = 1; i <= total; i++) {
    flag += Engine.getFragment(i);
}
console.log('Flag:', flag);

// 4. Check for hidden methods (common: __getFullFlag__, _debug, _raw)
const hidden = Object.getOwnPropertyNames(Engine)
    .filter(p => p.startsWith('__') || p.startsWith('_'));
console.log('Hidden methods:', hidden);
```

**Key insight:** Heavily obfuscated JavaScript (control flow flattening, RC4 string encoding, dead code) makes static analysis prohibitively slow. Runtime introspection via `Object.getOwnPropertyNames()` reveals all methods including hidden ones. The module's own decryption runs automatically when loaded — just call the decoded functions directly.

**Detection:** npm package with minified/obfuscated `dist/` directory, challenge says "reverse engineer the CLI tool", `package.json` with custom commands.



---

<!-- Source: patterns-ctf-2.md -->

# CTF Reverse - Competition-Specific Patterns (Part 2)

## Table of Contents
- [Multi-Layer Self-Decrypting Binary (DiceCTF 2026)](#multi-layer-self-decrypting-binary-dicectf-2026)
- [Embedded ZIP + XOR License Decryption (MetaCTF 2026)](#embedded-zip--xor-license-decryption-metactf-2026)
- [Stack String Deobfuscation from .rodata XOR Blob (Nullcon 2026)](#stack-string-deobfuscation-from-rodata-xor-blob-nullcon-2026)
- [Prefix Hash Brute-Force (Nullcon 2026)](#prefix-hash-brute-force-nullcon-2026)
- [CVP/LLL Lattice for Constrained Integer Validation (HTB ShadowLabyrinth)](#cvplll-lattice-for-constrained-integer-validation-htb-shadowlabyrinth)
- [Decision Tree Function Obfuscation (HTB WonderSMS)](#decision-tree-function-obfuscation-htb-wondersms)
- [GLSL Shader VM with Self-Modifying Code (ApoorvCTF 2026)](#glsl-shader-vm-with-self-modifying-code-apoorvctf-2026)
- [GF(2^8) Gaussian Elimination for Flag Recovery (ApoorvCTF 2026)](#gf28-gaussian-elimination-for-flag-recovery-apoorvctf-2026)
- [Z3 for Single-Line Python Boolean Circuit (BearCatCTF 2026)](#z3-for-single-line-python-boolean-circuit-bearcatctf-2026)
- [Sliding Window Popcount Differential Propagation (BearCatCTF 2026)](#sliding-window-popcount-differential-propagation-bearcatctf-2026)
- [Morse Code from Keyboard LEDs via ioctl (PlaidCTF 2013)](#morse-code-from-keyboard-leds-via-ioctl-plaidctf-2013)
- [Binary Repurposed as Keystream Oracle (DEF CON 33 Quals 2025)](#binary-repurposed-as-keystream-oracle-def-con-33-quals-2025)
- [Unicorn Host/Guest Memory Divergence — see ctf-pwn](#unicorn-hostguest-memory-divergence--see-ctf-pwn)

---

## Multi-Layer Self-Decrypting Binary (DiceCTF 2026)

**Pattern (another-onion):** Binary with N layers (e.g., 256), each reading 2 key bytes, deriving keystream via SHA-256 NI instructions, XOR-decrypting the next layer, then jumping to it. Must solve within a time limit (e.g., 30 minutes).

**Oracle for correct key:** Wrong key bytes produce garbage code. Correct key bytes produce code with exactly 2 `call read@plt` instructions (next layer's reads). Brute-force all 65536 candidates per layer using this oracle.

**JIT execution approach (fastest):**
```c
// Map binary's memory at original virtual addresses into solver process
// Compile solver at non-overlapping address: -Wl,-Ttext-segment=0x10000000
void *text = mmap((void*)0x400000, text_size, PROT_RWX, MAP_FIXED|MAP_PRIVATE, fd, 0);
void *bss = mmap((void*)bss_addr, bss_size, PROT_RW, MAP_FIXED|MAP_SHARED, shm_fd, 0);

// Patch read@plt to inject candidate bytes instead of reading stdin
// Patch tail jmp/call to next layer with ret/NOP to return from layer

// Fork-per-candidate: COW gives isolated memory without memcpy
for (int candidate = 0; candidate < 65536; candidate++) {
    pid_t pid = fork();
    if (pid == 0) {
        // Child: remap BSS as MAP_PRIVATE (COW from shared file)
        mmap(bss_addr, bss_size, PROT_RW, MAP_FIXED|MAP_PRIVATE, shm_fd, 0);
        inject_key(candidate >> 8, candidate & 0xff);
        ((void(*)())layer_addr)();  // Execute layer as function call
        // Check: does decrypted code contain exactly 2 call read@plt?
        if (count_read_calls(next_layer_addr) == 2) signal_found(candidate);
        _exit(0);
    }
}
```

**Performance tiers:**
| Approach | Speed | 256-layer estimate |
|----------|-------|--------------------|
| Python subprocess | ~2/s | days |
| Ptrace fork injection | ~119/s | 6+ hours |
| JIT + fork-per-candidate | ~1000/s | 140 min |
| JIT + shared BSS + 32 workers | ~3500/s | **~17 min** |

**Shared BSS optimization:** BSS (16MB+) stored in `/dev/shm` as `MAP_SHARED` in parent. Children remap as `MAP_PRIVATE` for COW. Reduces fork overhead from 16MB page-table setup to ~4KB.

**Key insight:** Multi-layer decryption challenges are fundamentally about building fast brute-force engines. JIT execution (mapping binary memory into solver, running code directly as function calls) is orders of magnitude faster than ptrace. Fork-based COW provides free memory isolation per candidate.

**Gotchas:**
- Real binary may use `call` (0xe8) instead of `jmp` (0xe9) for layer transitions — adjust tail patching
- BSS may extend beyond ELF MemSiz via kernel brk mapping — map extra space
- SHA-NI instructions work even when not advertised in `/proc/cpuinfo`

---

## Embedded ZIP + XOR License Decryption (MetaCTF 2026)

**Pattern (License To Rev):** Binary requires a license file as argument. Contains an embedded ZIP archive with the expected license, and an XOR-encrypted flag.

**Recognition:**
- `strings` reveals `EMBEDDED_ZIP` and `ENCRYPTED_MESSAGE` symbols
- Binary is not stripped — `nm` or `readelf -s` shows data symbols in `.rodata`
- `file` shows PIE executable, source file named `licensed.c`

**Analysis workflow:**
1. **Find data symbols:**
```bash
readelf -s binary | grep -E "EMBEDDED|ENCRYPTED|LICENSE"
# EMBEDDED_ZIP at offset 0x2220, 384 bytes
# ENCRYPTED_MESSAGE at offset 0x21e0, 35 bytes
```

2. **Extract embedded ZIP:**
```python
import struct
with open('binary', 'rb') as f:
    data = f.read()
# Find PK\x03\x04 magic in .rodata
zip_start = data.find(b'PK\x03\x04')
# Extract ZIP (size from symbol table or until next symbol)
open('embedded.zip', 'wb').write(data[zip_start:zip_start+384])
```

3. **Extract license from ZIP:**
```bash
unzip embedded.zip  # Contains license.txt
```

4. **XOR decrypt the flag:**
```python
license = open('license.txt', 'rb').read()
enc_msg = open('encrypted_msg.bin', 'rb').read()  # Extract from .rodata
flag = bytes(a ^ b for a, b in zip(enc_msg, license))
print(flag.decode())
```

**Key insight:** No need to run the binary or bypass the expiry date check. The embedded ZIP and encrypted message are both in `.rodata` — extract and XOR offline.

**Disassembly confirms:**
- `memcmp(user_license, decompressed_embedded_zip, size)` — license validation
- Date parsing with `sscanf("%d-%d-%d")` on `EXPIRY_DATE=` field
- XOR loop: `ENCRYPTED_MESSAGE[i] ^ license[i]` → `putc()` per byte

**Lesson:** When a binary has named symbols (`EMBEDDED_*`, `ENCRYPTED_*`), extract data directly from the binary without execution. XOR with known plaintext (the license) is trivially reversible.

---

## Stack String Deobfuscation from .rodata XOR Blob (Nullcon 2026)

**Pattern (stack_strings_1/2):** Binary mmaps a blob from `.rodata`, XOR-deobfuscates it, then uses the blob to validate input. Flag is recovered by reimplementing the verification loop.

**Recognition:**
- `mmap()` call followed by XOR loop over `.rodata` data
- Verification loop with running state (`eax`, `ebx`, `r9`) updated with constants like `0x9E3779B9`, `0x85EBCA6B`, `0xA97288ED`
- `rol32()` operations with position-dependent shifts
- Expected bytes stored in deobfuscated buffer

**Approach:**
1. Extract `.rodata` blob with pyelftools:
   ```python
   from elftools.elf.elffile import ELFFile
   with open(binary, "rb") as f:
       elf = ELFFile(f)
       ro = elf.get_section_by_name(".rodata")
       blob = ro.data()[offset:offset+size]
   ```
2. Recover embedded constants (length, magic values) by XOR with known keys from disassembly
3. Reimplement the byte-by-byte verification loop:
   - Each iteration: compute two hash-like values from running state
   - XOR them together and with expected byte to recover input byte
   - Update running state with constant additions

**Variant (stack_strings_2):** Adds position permutation + state dependency on previous character:
- Position permutation: byte `i` may go to position `pos[i]` in the output
- State dependency: `need = (expected - rol8(prev_char, 1)) & 0xFF`
- Must track `state` variable that updates to current character each iteration

**Key constants to look for:**
- `0x9E3779B9` (golden ratio fractional, common in hash functions)
- `0x85EBCA6B` (MurmurHash3 finalizer constant)
- `0xA97288ED` (related hash constant)
- `rol32()` with shift `i & 7`

---

## Prefix Hash Brute-Force (Nullcon 2026)

**Pattern (Hashinator):** Binary hashes every prefix of the input independently and outputs one digest per prefix. Given N output digests, the flag has N-1 characters.

**Attack:** Recover input one character at a time:
```python
for pos in range(1, len(target_hashes)):
    for ch in charset:
        candidate = known_prefix + ch + padding
        hashes = run_binary(candidate)
        if hashes[pos] == target_hashes[pos]:
            known_prefix += ch
            break
```

**Key insight:** If each prefix hash is independent (no chaining/HMAC), the problem decomposes into `N` x `|charset|` binary executions. This is the hash equivalent of byte-at-a-time block cipher attacks.

**Detection:** Binary outputs multiple hash lines. Changing last character only changes last hash. Different input lengths produce different numbers of output lines.

---

## CVP/LLL Lattice for Constrained Integer Validation (HTB ShadowLabyrinth)

**Pattern:** Binary validates flag via matrix multiplication where grouped input characters are multiplied by coefficient matrices and checked against expected 64-bit results. Standard algebra fails because solutions must be printable ASCII (32-126). Lattice-based CVP (Closest Vector Problem) with LLL reduction solves this efficiently.

**Identification:**
1. Binary groups input characters (e.g., 4 at a time)
2. Each group is multiplied by a coefficient matrix
3. Results compared against hardcoded 64-bit values
4. Need integer solutions in a constrained range (printable ASCII)

**SageMath CVP solver:**
```python
from sage.all import *

def solve_constrained_matrix(coefficients, targets, char_range=(32, 126)):
    """
    coefficients: list of coefficient rows (e.g., 4 values per group)
    targets: expected output values
    char_range: valid character range (printable ASCII)
    """
    n = len(coefficients[0])  # characters per group
    mid = (char_range[0] + char_range[1]) // 2

    # Build lattice: [coeff_matrix | I*scale]
    # The target vector includes adjusted targets
    M = matrix(ZZ, n + len(targets), n + len(targets))
    scale = 1000  # Weight to constrain character range

    for i, row in enumerate(coefficients):
        for j, c in enumerate(row):
            M[j, i] = c
        M[n + i, i] = 1  # padding

    for j in range(n):
        M[j, len(targets) + j] = scale

    target_vec = vector(ZZ, [t - sum(c * mid for c in row)
                              for row, t in zip(coefficients, targets)]
                        + [0] * n)

    # LLL + CVP
    L = M.LLL()
    closest = L * L.solve_left(target_vec)  # or use Babai
    solution = [closest[len(targets) + j] // scale + mid for j in range(n)]
    return bytes(solution)
```

**Two-phase validation pattern:**
1. **Phase 1 (matrix math):** Solve via CVP/LLL → recovers first N characters
2. First N characters become AES key → decrypt `file.bin` (XOR last 16 bytes + AES-256-CBC + zlib decompress)
3. **Phase 2 (custom VM):** Decrypted bytecode runs in custom VM, validates remaining characters via another linear system (mod 2^32)

**Modular linear system solving (Phase 2 — VM validation):**
```python
import numpy as np
from sympy import Matrix

# M * x = v (mod 2^32)
M_mod = Matrix(coefficients) % (2**32)
v_mod = Matrix(targets) % (2**32)
# Gaussian elimination in Z/(2^32)
solution = M_mod.solve(v_mod)  # Returns flag characters
```

**Key insight:** When a binary validates input through linear combinations with large coefficients and the solution must be in a small range (printable ASCII), this is a lattice problem in disguise. LLL reduction + CVP finds the nearest lattice point, recovering the constrained solution. Cross-reference: invoke `/ctf-crypto` for LLL/CVP fundamentals (advanced-math.md in ctf-crypto).

**Detection:** Binary performs matrix-like operations on grouped input, compares against 64-bit constants, and a brute-force search space is too large (e.g., 256^4 per group × 12 groups).

---

## Decision Tree Function Obfuscation (HTB WonderSMS)

**Pattern:** Binary routes input through ~200+ auto-generated functions, each computing a polynomial expression from input positions, comparing against a constant, and branching left/right. The tree makes static analysis impractical without scripted extraction.

**Identification:**
1. Large number of similar functions with random-looking names (e.g., `f315732804`)
2. Each function computes arithmetic on specific input positions
3. Functions call other tree functions or a final validation function
4. Decompiled code shows `if (expr cmp constant) call_left() else call_right()`

**Ghidra headless scripting for mass extraction:**
```python
# Extract comparison constants from all tree functions
# Run via: analyzeHeadless project/ tmp -import binary -postScript extract_tree.py
from ghidra.program.model.listing import *
from ghidra.program.model.symbol import *

fm = currentProgram.getFunctionManager()
results = []
for func in fm.getFunctions(True):
    name = func.getName()
    if name.startswith('f') and name[1:].isdigit():
        # Find CMP instruction and extract immediate constant
        inst_iter = currentProgram.getListing().getInstructions(func.getBody(), True)
        for inst in inst_iter:
            if inst.getMnemonicString() == 'CMP':
                operand = inst.getOpObjects(1)
                if operand:
                    results.append((name, int(operand[0].getValue())))
```

**Constraint propagation from known output format:**
1. Start from known output bytes (e.g., `http://HTB{...}`) → fix several input positions
2. Fixed positions cascade through arithmetic constraints → determine dependent positions
3. Tree root equation pins down remaining free variables
4. Recognize English words in partial flag to disambiguate multiple solutions

**Key insight:** Auto-generated decision trees look overwhelming but are repetitive by construction. Script the extraction (Ghidra, Binary Ninja, radare2) rather than reversing each function manually. The tree is just a dispatcher — the real logic is in the leaf function and its constraints.

**Detection:** Binary with hundreds of similarly-structured functions, 3-5 input position references per function, branching to two other functions or a common leaf.

---

## GLSL Shader VM with Self-Modifying Code (ApoorvCTF 2026)

**Pattern (Draw Me):** A WebGL2 fragment shader implements a Turing-complete VM on a 256x256 RGBA texture. The texture is both program memory and display output.

**Texture layout:**
- **Row 0:** Registers (pixel 0 = instruction pointer, pixels 1-32 = general purpose)
- **Rows 1-127:** Program memory (RGBA = opcode, arg1, arg2, arg3)
- **Rows 128-255:** VRAM (display output)

**Opcodes:** NOP(0), SET(1), ADD(2), SUB(3), XOR(4), JMP(5), JNZ(6), VRAM-write(7), STORE(8), LOAD(9). 16 steps per frame.

**Self-modifying code:** Phase 1 (decryption) uses STORE opcode to XOR-patch program memory that Phase 2 (drawing) then executes. The decryption overwrites SET instructions with correct pixel color values before the drawing code runs.

**Why GPU rendering fails:** The GPU runs all pixels in parallel per frame, but the shader tracks only ONE write target per pixel per frame. With multiple VRAM writes per frame, only the last survives — losing 75%+ of pixels. Similarly, STORE patches conflict during parallel decryption.

**Solve via sequential emulation:**
```python
from PIL import Image
import numpy as np

img = Image.open('program.png').convert('RGBA')
state = np.array(img, dtype=np.int32).copy()
regs = [0] * 33

# Phase 1: Trace decryption — apply all STORE patches sequentially
x, y = start_x, start_y
while True:
    r, g, b, a = state[y][x]
    opcode = int(r)
    if opcode == 1: regs[g] = b & 255           # SET
    elif opcode == 4: regs[g] = regs[b] ^ regs[a]  # XOR
    elif opcode == 8:                              # STORE — patches program memory
        tx, ty = regs[g], regs[b]
        state[ty][tx] = [regs[a], regs[a+1], regs[a+2], regs[a+3]]
    elif opcode == 5: break                        # JMP to drawing phase
    x += 1
    if x > 255: x, y = 0, y + 1

# Phase 2: Execute drawing code — all VRAM writes preserved
vram = np.zeros((128, 256), dtype=np.uint8)
# ... trace with opcode 7 writing to vram[ty][tx] = color
Image.fromarray(vram, mode='L').save('output.png')
```

**Key insight:** GLSL shaders are Turing-complete but GPU parallelism causes write conflicts. Self-modifying code (STORE patches) compounds the problem — patches from parallel executions overwrite each other. Sequential emulation in Python recovers the full output. The program.png file IS the bytecode.

**Detection:** WebGL/shader challenge with a PNG "program" file, challenge says "nothing renders" or output is garbled. Look for custom opcode tables in GLSL source.

---

## GF(2^8) Gaussian Elimination for Flag Recovery (ApoorvCTF 2026)

**Pattern (Forge):** Stripped binary performs Gaussian elimination over GF(2^8) (Galois Field with 256 elements, using the AES polynomial). A matrix and augmentation vector are embedded in `.rodata`. The solution vector is the flag.

**GF(2^8) arithmetic with AES polynomial (x^8+x^4+x^3+x+1 = 0x11b):**
```python
def gf_mul(a, b):
    """Multiply in GF(2^8) with AES reduction polynomial."""
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        hi = a & 0x80
        a = (a << 1) & 0xff
        if hi:
            a ^= 0x1b  # Reduction: x^8 = x^4+x^3+x+1
        b >>= 1
    return p

def gf_inv(a):
    """Brute-force multiplicative inverse (fine for 256 elements)."""
    if a == 0: return 0
    for x in range(1, 256):
        if gf_mul(a, x) == 1:
            return x
    return 0
```

**Solving the linear system:**
```python
# Extract N×N matrix + N-byte augmentation from binary .rodata
N = 56  # Flag length
# Build augmented matrix: N rows × (N+1) cols

for col in range(N):
    # Find non-zero pivot
    pivot = next((r for r in range(col, N) if aug[r][col] != 0), -1)
    if pivot != col:
        aug[col], aug[pivot] = aug[pivot], aug[col]
    # Scale pivot row by inverse
    inv = gf_inv(aug[col][col])
    aug[col] = [gf_mul(v, inv) for v in aug[col]]
    # Eliminate column in all other rows
    for row in range(N):
        if row == col: continue
        factor = aug[row][col]
        if factor == 0: continue
        aug[row] = [v ^ gf_mul(factor, aug[col][j]) for j, v in enumerate(aug[row])]

flag = bytes(aug[i][N] for i in range(N))
```

**Key insight:** GF(2^8) is NOT regular integer arithmetic — addition is XOR, multiplication uses polynomial reduction. The AES polynomial (0x11b) is the most common; look for the constant `0x1b` in disassembly. The binary may encrypt the result with AES-GCM afterward, but the raw solution vector (pre-encryption) is the flag.

**Detection:** Binary with a large matrix in `.rodata` (N² bytes), XOR-based row operations, constants `0x1b` or `0x11b`, and flag length matching sqrt of matrix size.

---

## Z3 for Single-Line Python Boolean Circuit (BearCatCTF 2026)

**Pattern (Captain Morgan):** Single-line Python (2000+ semicolons) validates flag via walrus operator chains decomposing input as a big-endian integer, with bitwise operations producing a boolean circuit.

**Identification:**
- Single-line Python with semicolons separating statements
- Walrus operator `:=` chains: `(x := expr)`
- Obfuscated XOR: `(x | i) & ~(x & i)` instead of `x ^ i`
- Input treated as a single large integer, decomposed via bit-shifting

**Z3 solution:**
```python
from z3 import *

n_bytes = 29  # Flag length
ari = BitVec('ari', n_bytes * 8)

# Parse semicolon-separated statements
# Model walrus chains as LShR(ari, shift_amount)
# Evaluate boolean expressions symbolically
# Final assertion: result_var == 0

s = Solver()
s.add(bfu == 0)  # Final validation variable
if s.check() == sat:
    m = s.model()
    val = m[ari].as_long()
    flag = val.to_bytes(n_bytes, 'big').decode('ascii')
```

**Key insight:** Single-line Python obfuscation creates a boolean circuit over input bits. The walrus operator chains are just variable assignments — split on semicolons and translate each to Z3 symbolically. Obfuscated XOR `(a | b) & ~(a & b)` is just `a ^ b`. Z3 solves these circuits in under a second. Look for `__builtins__` access or `ord()`/`chr()` calls to identify the input→integer conversion.

**Detection:** Single-line Python with 1000+ semicolons, walrus operators, bitwise operations, and a final comparison to 0 or True.

---

## Sliding Window Popcount Differential Propagation (BearCatCTF 2026)

**Pattern (Treasure Hunt 4):** Binary validates input via expected popcount (number of set bits) for each position of a 16-bit sliding window over the input bits.

**Differential propagation:**
When the window slides by 1 bit:
```text
popcount(window[i+1]) - popcount(window[i]) = bit[i+16] - bit[i]
```
So: `bit[i+16] = bit[i] + (data[i+1] - data[i])`

```python
expected = [...]  # 337 expected popcount values
total_bits = 337 + 15  # = 352

# Brute-force the initial 16-bit window (must have popcount = expected[0])
for start_val in range(0x10000):
    if bin(start_val).count('1') != expected[0]:
        continue

    bits = [0] * total_bits
    for j in range(16):
        bits[j] = (start_val >> (15 - j)) & 1

    valid = True
    for i in range(len(expected) - 1):
        new_bit = bits[i] + (expected[i + 1] - expected[i])
        if new_bit not in (0, 1):
            valid = False
            break
        bits[i + 16] = new_bit

    if valid:
        # Convert bits to bytes
        flag_bytes = bytes(int(''.join(map(str, bits[i:i+8])), 2)
                          for i in range(0, total_bits, 8))
        if b'BCCTF' in flag_bytes or flag_bytes[:5].isascii():
            print(flag_bytes.decode(errors='replace'))
            break
```

**Key insight:** Sliding window popcount differences create a recurrence relation: each new bit is determined by the bit 16 positions back plus the popcount delta. Only the first 16 bits are free (constrained by initial popcount). Brute-force the ~4000-8000 valid initial windows — for each, the entire bit sequence is deterministic. Runs in under a second.

**Detection:** Binary computing popcount/hamming weight on fixed-size windows. Expected value array with length ≈ input_bits - window_size + 1. Values in array are small integers (0 to window_size).

---

---

## Morse Code from Keyboard LEDs via ioctl (PlaidCTF 2013)

**Pattern:** Binary uses `ioctl(fd, KDSETLED, value)` to blink keyboard LEDs (Num/Caps/Scroll Lock). Timing patterns encode Morse code.

```bash
# Step 1: Bypass ptrace anti-debug
# Patch ptrace call at offset with NOP (0x90)
python3 -c "
data = open('binary','rb').read()
data = data[:0x72b] + b'\x90'*5 + data[:0x730]  # NOP the ptrace call
open('patched','wb').write(data)
"

# Step 2: Run under strace, capture ioctl calls
strace -e ioctl ./patched 2>&1 | grep KDSETLED > leds.txt

# Step 3: Decode timing patterns
# Short blink (250ms) = dit (.), long blink (750ms) = dah (-)
# Inter-character pause = 3x, inter-word pause = 7x
```

```python
# Parse strace output to extract Morse
import re
morse_map = {'.-':'A', '-...':'B', '-.-.':'C', '-..':'D', '.':'E',
             '..-.':'F', '--.':'G', '....':'H', '..':'I', '.---':'J',
             '-.-':'K', '.-..':'L', '--':'M', '-.':'N', '---':'O',
             '.--.':'P', '--.-':'Q', '.-.':'R', '...':'S', '-':'T',
             '..-':'U', '...-':'V', '.--':'W', '-..-':'X', '-.--':'Y',
             '--..':'Z', '-----':'0', '.----':'1'}
# Map LED on-durations to dots/dashes, group by pauses
```

**Key insight:** `KDSETLED` controls physical keyboard LEDs on Linux (`/dev/console`). The binary must run with console access. Use `strace -e ioctl` to capture all LED state changes without needing physical observation. Timing between calls determines dot vs dash.

---

See also: [patterns-ctf.md](patterns-ctf.md) for Part 1 (hidden emulator opcodes, SPN static extraction, image XOR smoothness, byte-at-a-time cipher, mathematical convergence bitmap, Windows PE XOR bitmap OCR, two-stage RC4+VM loaders, GBA ROM meet-in-the-middle, Sprague-Grundy game theory, kernel module maze solving, multi-threaded VM channels).

---

## Binary Repurposed as Keystream Oracle (DEF CON 33 Quals 2025)

**Pattern ("Dialects"):** Challenge ships a *modified* crypto primitive (e.g. tweaked SM3 / SM4 round constants) and asks you to break a ciphertext. The canonical move in 2025+ is **not** to reverse the primitive's math — it's to **patch the binary itself into a keystream-dumping oracle**:

1. Identify the core loop that produces round output / keystream bytes.
2. Patch in a small trampoline: write those bytes to stdout (or a file) before the next round consumes them.
3. Run the patched binary with attacker-chosen inputs.
4. Use the dumped keystream / intermediate state to solve the challenge algebraically (often just XOR).

**Why it beats reversing:**
- Saves hours of math on a non-standard primitive.
- The *binary author* already implemented the primitive correctly — reuse their work.
- Works even when the primitive is obfuscated / VM-wrapped, as long as you can locate the I/O boundary.

**Patch-in-place recipes:**
- `lief` / `radare2` / `patchelf` to inject a small `write(1, state_ptr, 64)` before `ret`.
- Or replace a `call encrypt` with `call hook; call encrypt` where `hook` dumps state to a memfd.

Also relevant: **protocol downgrade** pattern used in Dialects — upgrade an in-stream socket to TLS mid-session to evade "flag-share" detectors in remote judges. If the remote binary trusts the peer after the upgrade, you can exfil state over the upgraded channel.

Source: [blog.cloudlabs.ufscar.br/sec/defcon-quals-2025](https://blog.cloudlabs.ufscar.br/sec/defcon-quals-2025/).

---

## Unicorn Host/Guest Memory Divergence — see ctf-pwn

When a challenge uses the Unicorn engine as a sandbox, `uc_mem_read()` from the host controller does NOT trip guest memory hooks. Any primitive that turns a guest operation into a host read bypasses the sandbox. Full writeup: [ctf-pwn/advanced-exploits-2.md — Unicorn Emulator Host/Guest Hook Divergence](../ctf-pwn/advanced-exploits-2.md#unicorn-emulator-hostguest-hook-divergence-google-ctf-2025-unicornel-trustzone).

---

## `perf_event_open` Instruction-Count Side-Channel Byte Oracle (source: idekCTF 2025 constructor)

**Trigger:** local flag-check binary where correct prefix runs *longer* (more retired instructions) than incorrect; `perf stat -e instructions` available, or `perf_event_open` permission.
**Signals:** binary compares chars in a loop with an early-exit; distinct branches on match vs mismatch; no explicit timing protection.
**Mechanic:** run `perf stat -e instructions ./bin <candidate>` per character hypothesis; correct prefix yields a deterministic extra `N`-instruction cost per matched byte. Byte-by-byte oracle at the hardware-counter level — more stable than wall time.
Automation:
```bash
for c in {a..z} {A..Z} {0..9} '{' '_' '}'; do
  n=$(perf stat -e instructions -x, -- ./bin "${PREFIX}${c}" 2>&1 | tail -1 | cut -d',' -f1)
  echo "$c $n"
done | sort -k2 -n | tail
```

## VM Architecture Misidentification + Banned-Byte Synthesis (source: idekCTF 2025 Lazy VM)

**Trigger:** custom VM where the decompiler banner claims "register-based" but opcode dispatch actually goes through a single `pop/push` pair; additionally some opcode bytes are banned in the input bytecode file.
**Signals:** opcode handler functions each start with a stack pop and end with a push; dispatch table indexed by `*pc++`; challenge says "you cannot use bytes `0x61 0x66 0x67 0x6c`".
**Mechanic:** re-decompile with stack semantics (forget the "register" framing). For banned opcodes, synthesise them from allowed ones: `ADD K; SUB (K-target)` to produce the forbidden opcode byte at runtime; or use `XOR` pairs to construct any byte from a small allowed alphabet. Generic rule: if ISA claims are inconsistent with handler shape, trust the handler; any byte-ban constraint is solvable via arithmetic synthesis.



---

<!-- Source: patterns-ctf-3.md -->

# CTF Reverse — Patterns (2025-2026 era, continued)

Third-era patterns. Base patterns in [patterns-ctf.md](patterns-ctf.md); 2024-era additions in [patterns-ctf-2.md](patterns-ctf-2.md).

## Table of Contents
- [Genetic Algorithm over Opaque Scoring Function (source: PlaidCTF 2025 Prospectin')](#genetic-algorithm-over-opaque-scoring-function-source-plaidctf-2025-prospectin)

---

## Genetic Algorithm over Opaque Scoring Function (source: PlaidCTF 2025 Prospectin')

**Trigger:**
- ELF/PE where `main()` reads a small input (≤ 256 bytes), then feeds it through a long chain of `if (input[i] op const) score += kN; else score += kM;` style predicates — often dozens to hundreds of such checks.
- The binary prints success when `score >= THRESHOLD` (e.g. `0x119`, `0x5f3`); no obvious single-byte flag check, no hashing, just additive scoring.
- Ghidra decompilation shows a flat chain of arithmetic / bitwise / boolean checks with branch-free `score += w` updates that all depend on `input[i]`.

**Signals to grep:**
```
objdump -d bin | awk '/add\s+\$0x[0-9a-f]+,\s*%e[a-z]x/' | wc -l      # many score-bumping adds
grep -oE 'score\s*[+\-*]=\s*\w+' decompile.c | sort -u                 # diverse weights
# fitness-style control flow: single exit with   if (score >= X) win();
```

**Why not symbolic execution:** angr chokes on hundreds of branches; z3 solve time blows up because there's no feasible conjunction of constraints — the scoring is *additive*, not *equational*. You don't need all checks to pass, just enough to hit the threshold.

**Recipe:**

1. **Lift the scoring loop to a callable** — two options:
   - (a) Ghidra → decompile → paste C → `gcc -shared -fPIC` → `ctypes.CDLL`.
   - (b) `patchelf --add-needed` a tiny shim, or use Qiling/Unicorn to wrap only the `score()` function as a Python callable.
   - Cross-arch? Decompile aarch64 → paste into amd64 .so; the scoring body is pure arithmetic and ports 1-1.

2. **GA driver:**
```python
import random, ctypes
scorer = ctypes.CDLL("./score.so").score    # (const char*, size_t) -> int
POP, GENS, LEN, THR = 500, 2000, INPUT_LEN, 0x5f3

def fitness(b):
    buf = ctypes.create_string_buffer(b, LEN)
    return scorer(buf, LEN)

def mutate(b):
    i = random.randrange(LEN)
    return b[:i] + bytes([random.randrange(256)]) + b[i+1:]

def crossover(a, b):
    k = random.randrange(LEN)
    return a[:k] + b[k:]

pop = [bytes(random.randrange(256) for _ in range(LEN)) for _ in range(POP)]
for gen in range(GENS):
    pop.sort(key=fitness, reverse=True)
    if fitness(pop[0]) >= THR:
        print(pop[0].hex()); break
    elite = pop[:POP//10]
    pop = elite + [mutate(crossover(random.choice(elite), random.choice(elite)))
                   for _ in range(POP - len(elite))]
```

3. **Tuning knobs that matter:**
   - Tournament selection > elitism if the fitness landscape is rugged.
   - Byte-wise mutation rate 1-3% optimal; too high destroys converged structure, too low stalls.
   - When charset is restricted (hex digits, printable ASCII), constrain `random.randrange(...)` accordingly — a 5-10× speedup.
   - If the scorer has independent per-byte contributions, **replace GA with hill-climbing**: vary one byte at a time, keep if score doesn't decrease. Often 100× faster than GA and provably optimal for separable scoring.

4. **Detecting separability (skip GA):**
   - Run the scorer with input `b"A"*N`, then flip byte `i` through 0..255. If the per-byte optimum is independent of other bytes, the scoring is **separable** — solve each byte independently.
   - Build a `256 × N` table `best[i][v]` = score contribution of byte `i = v`; pick argmax per column.

**Generalizes to:** license validators, "submit 32-byte key to unlock"-style crackmes with weighted scoring, ML-style classifier wrappers, puzzle games with score-based win conditions. First separability-probe, then hill-climb, then GA as fallback.



---

<!-- Source: patterns-ctf.md -->

# CTF Reverse - Competition-Specific Patterns (Part 1)

## Table of Contents
- [Hidden Emulator Opcodes + LD_PRELOAD Key Extraction (0xFun 2026)](#hidden-emulator-opcodes--ld_preload-key-extraction-0xfun-2026)
- [Spectre-RSB SPN Cipher — Static Parameter Extraction (0xFun 2026)](#spectre-rsb-spn-cipher--static-parameter-extraction-0xfun-2026)
- [Image XOR Mask Recovery via Smoothness (VuwCTF 2025)](#image-xor-mask-recovery-via-smoothness-vuwctf-2025)
- [Shellcode in Data Section via mmap RWX (VuwCTF 2025)](#shellcode-in-data-section-via-mmap-rwx-vuwctf-2025)
- [Recursive execve Subtraction (VuwCTF 2025)](#recursive-execve-subtraction-vuwctf-2025)
- [Byte-at-a-Time Block Cipher Attack (UTCTF 2024)](#byte-at-a-time-block-cipher-attack-utctf-2024)
- [Mathematical Convergence Bitmap (EHAX 2026)](#mathematical-convergence-bitmap-ehax-2026)
- [Windows PE XOR Bitmap Extraction + OCR (srdnlenCTF 2026)](#windows-pe-xor-bitmap-extraction--ocr-srdnlenctf-2026)
- [Two-Stage Loader: RC4 Gate + VM Constraints (srdnlenCTF 2026)](#two-stage-loader-rc4-gate--vm-constraints-srdnlenctf-2026)
- [GBA ROM VM Hash Inversion via Meet-in-the-Middle (srdnlenCTF 2026)](#gba-rom-vm-hash-inversion-via-meet-in-the-middle-srdnlenctf-2026)
- [Sprague-Grundy Game Theory Binary (DiceCTF 2026)](#sprague-grundy-game-theory-binary-dicectf-2026)
- [Kernel Module Maze Solving (DiceCTF 2026)](#kernel-module-maze-solving-dicectf-2026)
- [Multi-Threaded VM with Channel Synchronization (DiceCTF 2026)](#multi-threaded-vm-with-channel-synchronization-dicectf-2026)
- [Backdoored Shared Library Detection via String Diffing (Hack.lu CTF 2012)](#backdoored-shared-library-detection-via-string-diffing-hacklu-ctf-2012)

---

## Hidden Emulator Opcodes + LD_PRELOAD Key Extraction (0xFun 2026)

**Pattern (CHIP-8):** Non-standard opcode `FxFF` triggers hidden `superChipRendrer()` → AES-256-CBC decryption. Key derived from binary constants.

**Technique:**
1. Check all instruction dispatch branches for non-standard opcodes
2. Hidden opcode may trigger crypto functions (OpenSSL)
3. Use `LD_PRELOAD` hook on `EVP_DecryptInit_ex` to capture AES key at runtime:

```c
#include <openssl/evp.h>
int EVP_DecryptInit_ex(EVP_CIPHER_CTX *ctx, const EVP_CIPHER *type,
                       ENGINE *impl, const unsigned char *key,
                       const unsigned char *iv) {
    // Log key
    for (int i = 0; i < 32; i++) printf("%02x", key[i]);
    printf("\n");
    // Call original
    return ((typeof(EVP_DecryptInit_ex)*)dlsym(RTLD_NEXT, "EVP_DecryptInit_ex"))
           (ctx, type, impl, key, iv);
}
```

```bash
gcc -shared -fPIC -ldl -lssl hook.c -o hook.so
LD_PRELOAD=./hook.so ./emulator rom.ch8
```

---

## Spectre-RSB SPN Cipher — Static Parameter Extraction (0xFun 2026)

**Pattern:** Binary uses cache side channels to implement S-boxes, but ALL cipher parameters (round keys, S-box tables, permutation) are in the binary's data section.

**Key insight:** Don't try to run on special hardware. Extract parameters statically:
- 8 S-boxes × 8 output bits, 256 entries each
- Values `0x340` = bit 1, `0x100` = bit 0
- 64-byte permutation table, 8 round keys

```python
# Extract from binary data section
import struct
sbox = [[0]*256 for _ in range(8)]
for i in range(8):
    for j in range(256):
        val = struct.unpack('<I', data[sbox_offset + (i*256+j)*4 : ...])[0]
        sbox[i][j] = 1 if val == 0x340 else 0
```

**Lesson:** Side-channel implementations embed lookup tables in memory. Extract statically.

---

## Image XOR Mask Recovery via Smoothness (VuwCTF 2025)

**Pattern (Trianglification):** Image divided into triangle regions, each XOR-encrypted with `key = (mask * x - y) & 0xFF` where mask is unknown (0-255).

**Recovery:** Natural images have smooth gradients. Brute-force mask (256 values per region), score by neighbor pixel differences:

```python
import numpy as np
from PIL import Image

img = np.array(Image.open('encrypted.png'))

def score_smoothness(region_pixels, mask, positions):
    decrypted = []
    for (x, y), pixel in zip(positions, region_pixels):
        key = (mask * x - y) & 0xFF
        decrypted.append(pixel ^ key)
    # Score: sum of absolute differences between adjacent pixels
    return -sum(abs(decrypted[i] - decrypted[i+1]) for i in range(len(decrypted)-1))

for region in regions:
    best_mask = max(range(256), key=lambda m: score_smoothness(region, m, positions))
```

**Search space:** 256 candidates × N regions = trivial. Smoothness is a reliable scoring metric for natural images.

---

## Shellcode in Data Section via mmap RWX (VuwCTF 2025)

**Pattern (Missing Function):** Binary relocates data to RWX memory (mmap with PROT_READ|PROT_WRITE|PROT_EXEC) and jumps to it.

**Detection:** Look for `mmap` with PROT_EXEC flag. Embedded shellcode often uses XOR with rotating key.

**Analysis:** Extract data section, apply XOR key (try 3-byte rotating), disassemble result.

---

## Recursive execve Subtraction (VuwCTF 2025)

**Pattern (String Inspector):** Binary recursively calls itself via `execve`, subtracting constants each time.

**Solution:** Find base case and work backward. Often a mathematical relationship like `N * M + remainder`.

---

## Byte-at-a-Time Block Cipher Attack (UTCTF 2024)

**Pattern (PES-128):** First output byte depends only on first input byte (no diffusion).

**Attack:** For each position, try all 256 byte values, compare output byte with target ciphertext. One match per byte = full plaintext recovery without knowing the key.

**Detection:** Change one input byte → only corresponding output byte changes. This means zero cross-byte diffusion = trivially breakable.

---

## Mathematical Convergence Bitmap (EHAX 2026)

**Pattern (Compute It):** Binary classifies complex-plane coordinates by Newton's method convergence. The classification results, arranged as a grid, spell out the flag in ASCII art.

**Recognition:**
- Input file with coordinate pairs (x, y)
- Binary iterates a mathematical function (e.g., z^3 - 1 = 0) and outputs pass/fail
- Grid dimensions hinted by point count (e.g., 2600 = 130×20)
- 5-pixel-high ASCII art font common in CTFs

**Newton's method for z^3 - 1:**
```python
def newton_converges_to_one(px, py, max_iter=50, target_count=12):
    """Returns True if Newton's method converges to z=1 in exactly target_count steps."""
    x, y = px, py
    count = 0
    for _ in range(max_iter):
        f_real = x**3 - 3*x*y**2 - 1.0
        f_imag = 3*x**2*y - y**3
        J_rr = 3.0 * (x**2 - y**2)
        J_ri = 6.0 * x * y
        det = J_rr**2 + J_ri**2
        if det < 1e-9:
            break
        x -= (f_real * J_rr + f_imag * J_ri) / det
        y -= (f_imag * J_rr - f_real * J_ri) / det
        count += 1
        if abs(x - 1.0) < 1e-6 and abs(y) < 1e-6:
            break
    return count == target_count

# Read coordinates and render bitmap
points = [(float(x), float(y)) for x, y in ...]
bits = [1 if newton_converges_to_one(px, py) else 0 for px, py in points]
WIDTH = 130  # 2600 / 20 rows
for r in range(len(bits) // WIDTH):
    print(''.join('#' if bits[r*WIDTH+c] else '.' for c in range(WIDTH)))
```

**Key insight:** The binary is a mathematical classifier, not a flag checker. The flag is in the visual pattern of classifications, not in the binary's output. Reverse-engineer the math, apply to all coordinates, and visualize as bitmap.

---

## Windows PE XOR Bitmap Extraction + OCR (srdnlenCTF 2026)

**Pattern (Artistic Warmup):** Binary renders input text, compares rendered bitmap against expected pixel data stored XOR'd with constant in `.rdata`. No need to compute — extract expected pixels directly.

**Attack:**
1. Reverse the core check function to identify rendering and comparison logic
2. Find the expected pixel blob in `.rdata` (look for large data block referenced near comparison)
3. XOR with constant (e.g., 0xAA) to recover expected rendered DIB
4. Save as image and OCR to recover flag text

```python
import numpy as np
from PIL import Image

with open("binary.exe", "rb") as f:
    data = f.read()

# Extract from .rdata section (offsets from reversing)
blob_offset = 0xC3620  # .rdata offset to XOR'd blob
blob_size = 0x15F90     # 450 * 50 * 4 (BGRA)
blob = np.frombuffer(data[blob_offset:blob_offset + blob_size], dtype=np.uint8)
expected = blob ^ 0xAA  # XOR with constant key

# Reshape as BGRA image (dimensions from reversing)
img = expected.reshape(50, 450, 4)
channel = img[:, :, 0]  # Take one channel (grayscale text)
Image.fromarray(channel, "L").save("target.png")

# OCR with charset whitelist
import subprocess
result = subprocess.run(
    ["tesseract", "target.png", "stdout", "-c",
     "tessedit_char_whitelist=abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789{}_"],
    capture_output=True, text=True)
print(result.stdout)
```

**Key insight:** When a binary renders text and compares pixels, the expected pixel data is the flag rendered as an image. Extract it directly from the binary data section without needing to understand the rendering logic. OCR with charset whitelist improves accuracy for CTF flag characters.

---

## Two-Stage Loader: RC4 Gate + VM Constraints (srdnlenCTF 2026)

**Pattern (Cornflake v3.5):** Two-stage malware loader — stage 1 uses RC4 username gate, stage 2 downloaded from C2 contains VM-based password validation.

**Stage 1 — RC4 username recovery:**
```python
def rc4(key, data):
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) & 0xFF
        s[i], s[j] = s[j], s[i]
    i = j = 0
    out = bytearray()
    for b in data:
        i = (i + 1) & 0xFF
        j = (j + s[i]) & 0xFF
        s[i], s[j] = s[j], s[i]
        out.append(b ^ s[(s[i] + s[j]) & 0xFF])
    return bytes(out)

# Key from binary strings, ciphertext from stored hex
username = rc4(b"s3cr3t_k3y_v1", bytes.fromhex("46f5289437bc009c17817e997ae82bfbd065545d"))
```

**Stage 2 — VM constraint extraction:**
1. Download stage 2 from C2 endpoint (e.g., `/updates/check.php`)
2. Reverse VM bytecode interpreter (typically 15-20 opcodes)
3. Extract linear equality constraints over flag characters
4. Solve constraint system (Z3 or manual)

**Key insight:** Multi-stage loaders often use simple crypto (RC4) for the first gate and more complex validation (custom VM) for the second. The VM memory may be uninitialized (all zeros), drastically simplifying constraint extraction since memory-dependent operations become constants.

---

## GBA ROM VM Hash Inversion via Meet-in-the-Middle (srdnlenCTF 2026)

**Pattern (Dante's Trial):** Game Boy Advance ROM implements a custom VM. Hash function uses FNV-1a variant with uninitialized memory (stays all zeros). Meet-in-the-middle attack splits the search space.

**Hash function structure:**
```python
# FNV-1a variant with XOR/multiply
P = 0x100000001b3        # FNV prime
CUP = 0x9e3779b185ebca87  # Golden ratio constant
MASK64 = (1 << 64) - 1

def fmix64(h):
    """Finalization mixer."""
    h ^= h >> 33; h = (h * 0xff51afd7ed558ccd) & MASK64
    h ^= h >> 33; h = (h * 0xc4ceb9fe1a85ec53) & MASK64
    h ^= h >> 33
    return h

def hash_input(chars, seed_lo=0x84222325, seed_hi=0xcbf29ce4):
    hlo, hhi, ptr = seed_lo, seed_hi, 0
    for c in chars:
        # tri_mix(c, mem[ptr]) — mem is always 0
        delta = ((ord(c) * CUP) ^ (0 * P)) & MASK64
        hlo = ((hlo ^ (delta & 0xFFFFFFFF)) * (P & 0xFFFFFFFF)) & 0xFFFFFFFF
        hhi = ((hhi ^ (delta >> 32)) * (P >> 32)) & 0xFFFFFFFF
        ptr = (ptr + 1) & 0xFF
    combined = ((hhi << 32) | (hlo ^ ptr)) & MASK64
    return fmix64((combined * P) & MASK64)
```

**Meet-in-the-middle attack:**
```python
import string

TARGET = 0x73f3ebcbd9b4cd93
LENGTH = 6
SPLIT = 3
charset = [c for c in string.printable if 32 <= ord(c) < 127]

# Forward pass: enumerate first 3 characters from seed state
forward = {}
for c1 in charset:
    for c2 in charset:
        for c3 in charset:
            state = hash_forward(seed, [c1, c2, c3])
            forward[state] = c1 + c2 + c3

# Backward pass: invert fmix64 and final multiply, enumerate last 3 chars
inv_target = invert_fmix64(TARGET)
for c4 in charset:
    for c5 in charset:
        for c6 in charset:
            state = hash_backward(inv_target, [c4, c5, c6])
            if state in forward:
                print(f"Found: {forward[state]}{c4}{c5}{c6}")
```

**Key insight:** Meet-in-the-middle reduces search from `95^6 ≈ 7.4×10^11` to `2×95^3 ≈ 1.7×10^6` — a factor of ~430,000x speedup. Critical when the hash function is invertible from the output side (i.e., `fmix64` and the final multiply can be undone). Also: uninitialized VM memory that stays zero simplifies the hash function by removing a variable.

---

## Sprague-Grundy Game Theory Binary (DiceCTF 2026)

**Pattern (Bedtime):** Stripped Rust binary plays N rounds of bounded Nim. Each round has piles and max-move parameter k. Binary uses a PRNG for moves when in a losing position; user must respond optimally so the PRNG eventually generates an invalid move (returns 1). Sum of return values must equal a target.

**Game theory identification:**
- Bounded Nim: remove 1 to k items from any pile per turn
- **Grundy value** per pile: `pile_value % (k+1)`
- **XOR** of all Grundy values: non-zero = winning (N-position), zero = losing (P-position)
- N-positions: computer wins automatically (returns 0)
- P-positions: computer uses PRNG, may make invalid move (returns 1)

**PRNG state tracking through user feedback:**
```python
MASK64 = (1 << 64) - 1

def prng_step(state, pile_count, k):
    """Computer's PRNG move. Returns (pile_idx, amount, new_state)."""
    r12 = state[2] ^ 0x28027f28b04ccfa7
    rax = (state[1] + r12) & MASK64
    s0_new = ROL64((state[0] ** 2 + rax) & MASK64, 32)
    r12_upd = (r12 + rax) & MASK64
    s0_final = ROL64((s0_new ** 2 + r12_upd) & MASK64, 32)

    pile_idx = rax % pile_count
    amount = (r12_upd % k) + 1
    return pile_idx, amount, [s0_final, r12_upd, state[2]]

# Critical: state[2] updated ONLY by user moves (XOR of pile_idx, amount, new_value)
# PRNG moves do NOT affect state[2] — creates feedback loop
```

**Solving approach:**
1. Dump game data from GDB (all entries with pile values and parameters)
2. Classify: count P-positions (return 1) vs N-positions (return 0)
3. Simulate each P-position: PRNG moves → user responds optimally → track state[2]
4. Encode user moves as input format (4-digit decimal pairs, reversed order)

**Key insight:** When a game binary's PRNG state depends on user input, you must simulate the full feedback loop — not just solve the game theory. Use GDB hardware watchpoints to discover which state variables are affected by user vs computer moves.

---

## Kernel Module Maze Solving (DiceCTF 2026)

**Pattern (Explorer):** Rust kernel module implements a 3D maze via `/dev/challenge` ioctls. Navigate the maze, avoid decoy exits (status=2), find the real exit (status=1), read the flag.

**Ioctl enumeration:**
| Command | Description |
|---------|-------------|
| `0x80046481-83` | Get maze dimensions (3 axes, 8-16 each) |
| `0x80046485` | Get status: 0=playing, 1=WIN, 2=decoy |
| `0x80046486` | Get wall bitfield (6 directions) |
| `0x80406487` | Get flag (64 bytes, only when status=1) |
| `0x40046488` | Move in direction (0-5) |
| `0x6489` | Reset position |

**DFS solver with decoy avoidance:**
```c
// Minimal static binary using raw syscalls (no libc) for small upload size
// gcc -nostdlib -static -Os -fno-builtin -o solve solve.c -Wl,--gc-sections && strip solve

int visited[16][16][16];
int bad[16][16][16];   // decoy positions across resets

void dfs(int fd, int x, int y, int z) {
    if (visited[x][y][z] || bad[x][y][z]) return;
    visited[x][y][z] = 1;

    int status = ioctl_get_status(fd);
    if (status == 1) { read_flag(fd); exit(0); }
    if (status == 2) { bad[x][y][z] = 1; return; }  // decoy — mark bad

    int walls = ioctl_get_walls(fd);
    int dx[] = {1,-1,0,0,0,0}, dy[] = {0,0,1,-1,0,0}, dz[] = {0,0,0,0,1,-1};
    int opp[] = {2,3,0,1,5,4};  // opposite directions for backtracking

    for (int dir = 0; dir < 6; dir++) {
        if (!(walls & (1 << dir))) continue;  // wall present
        ioctl_move(fd, dir);
        dfs(fd, x+dx[dir], y+dy[dir], z+dz[dir]);
        ioctl_move(fd, opp[dir]);  // backtrack
    }
}
// After decoy hit: reset via ioctl 0x6489, clear visited, re-run DFS
```

**Remote deployment:** Upload binary via base64 chunks over netcat shell, decode, execute.

**Key insight:** For kernel module challenges, injecting test binaries into initramfs and probing ioctls dynamically is faster than static RE of stripped kernel modules. Keep solver binary minimal (raw syscalls, no libc) for fast upload.

---

## Multi-Threaded VM with Channel Synchronization (DiceCTF 2026)

**Pattern (locked-in):** Custom stack-based VM runs 16 concurrent threads verifying a 30-char flag. Threads communicate via futex-based channels. Pipeline: input → XOR scramble → transformation → base-4 state machine → final check.

**Analysis approach:**
1. **Identify thread roles** by tracing channel read/write patterns in GDB
2. **Extract constants** (XOR scramble values, lookup tables) via breakpoints on specific opcodes
3. **Watch for inverted logic:** validity check returns 0 for valid, non-zero for blocked (opposite of intuition)
4. **Detect futex quirks:** `unlock_pi` on unowned mutex returns EPERM=1, which can change all computations

**BFS state space search for constrained state machines:**
```python
from collections import deque

def solve_flag(scramble_vals, lookup_table, initial_state, target_state):
    """BFS through state machine to find valid flag bytes."""
    flag = [None] * 30
    # Known prefix/suffix from flag format
    flag[0:5] = list(b'dice{')
    flag[29] = ord('}')

    # For each unknown position, try all printable ASCII
    states = {initial_state}
    for pos in range(28, 4, -1):  # processed in reverse
        next_states = {}
        for state in states:
            for ch in range(32, 127):
                transformed = transform(ch, scramble_vals[pos])
                digits = to_base4(transformed)
                new_state = apply_digits(state, digits, lookup_table)
                if new_state is not None:  # valid path exists
                    next_states.setdefault(new_state, []).append((state, ch))
        states = set(next_states.keys())

    # Trace back from target_state to recover flag
```

**Key insight:** Multi-threaded VMs require tracing data flow across thread boundaries. Channel-based communication creates a pipeline — identify each thread's role (input, transform, validate, output) by watching which channels it reads/writes. Constants that affect computation may come from unexpected sources (futex return values, thread IDs).

---

## Backdoored Shared Library Detection via String Diffing (Hack.lu CTF 2012)

**Pattern (Zombie Lockbox):** A setuid binary uses `strcmp` for password validation. The expected password is visible via `strings` and works under GDB (which drops suid), but fails when run normally. The binary links against a non-standard libc that patches function behavior based on suid status.

**Detection steps:**
1. Check for non-standard library paths with `ldd`:
```bash
ldd ./binary
# Suspicious: libc.so.6 => /lib/libc/libc.so.6  (non-standard path)
# Normal:    libc.so.6 => /lib32/libc.so.6
```

2. Diff strings between the suspicious and system libc:
```bash
strings /lib/libc/libc.so.6 > suspicious_strings
strings /lib32/libc-2.15.so > normal_strings
diff suspicious_strings normal_strings
```

3. Disassemble the patched function (e.g., `puts`) to find injected code:
```bash
gdb /lib/libc/libc.so.6
(gdb) disas puts
# Look for unexpected calls or branches
# Injected code may check suid status (getuid/geteuid syscalls)
# and swap the expected password at runtime
```

**Key insight:** When a binary behaves differently under GDB vs. normal execution, check `ldd` for non-standard library paths. Suid binaries drop privileges under debuggers, so a backdoored libc can detect this via `getuid`/`geteuid` syscalls and change program behavior accordingly. The `strings | diff` approach quickly reveals injected data without full disassembly.

---

See also: [patterns-ctf-2.md](patterns-ctf-2.md) for Part 2 (multi-layer self-decrypting binary, embedded ZIP+XOR license, stack string deobfuscation, prefix hash brute-force, CVP/LLL lattice, decision tree obfuscation, GLSL shader VM, GF(2^8) Gaussian elimination, Z3 boolean circuit, sliding window popcount).



---

<!-- Source: patterns.md -->

# CTF Reverse - Patterns & Techniques

## Table of Contents
- [Custom VM Reversing](#custom-vm-reversing)
  - [Analysis Steps](#analysis-steps)
  - [Common VM Patterns](#common-vm-patterns)
  - [RVA-Based Opcode Dispatching](#rva-based-opcode-dispatching)
  - [State Machine VMs (90K+ states)](#state-machine-vms-90k-states)
- [Anti-Debugging Techniques](#anti-debugging-techniques)
  - [Common Checks](#common-checks)
  - [Bypass Technique](#bypass-technique)
  - [LD_PRELOAD Hook](#ld_preload-hook)
  - [pwntools Binary Patching (Crypto-Cat)](#pwntools-binary-patching-crypto-cat)
- [Nanomites](#nanomites)
  - [Linux (Signal-Based)](#linux-signal-based)
  - [Windows (Debug Events)](#windows-debug-events)
  - [Analysis](#analysis)
- [Self-Modifying Code](#self-modifying-code)
  - [Pattern: XOR Decryption](#pattern-xor-decryption)
- [Known-Plaintext XOR (Flag Prefix)](#known-plaintext-xor-flag-prefix)
  - [Variant: XOR with Position Index](#variant-xor-with-position-index)
- [Mixed-Mode (x86-64 / x86) Stagers](#mixed-mode-x86-64--x86-stagers)
- [LLVM Obfuscation (Control Flow Flattening)](#llvm-obfuscation-control-flow-flattening)
  - [Pattern](#pattern)
  - [De-obfuscation](#de-obfuscation)
- [S-Box / Keystream Generation](#s-box--keystream-generation)
  - [Fisher-Yates Shuffle (Xorshift32)](#fisher-yates-shuffle-xorshift32)
  - [Xorshift64* Keystream](#xorshift64-keystream)
  - [Identifying Patterns](#identifying-patterns)
- [SECCOMP/BPF Filter Analysis](#seccompbpf-filter-analysis)
  - [BPF Analysis](#bpf-analysis)
- [Exception Handler Obfuscation](#exception-handler-obfuscation)
  - [RtlInstallFunctionTableCallback](#rtlinstallfunctiontablecallback)
  - [Vectored Exception Handlers (VEH)](#vectored-exception-handlers-veh)
- [Memory Dump Analysis](#memory-dump-analysis)
  - [When Binary Dumps Memory](#when-binary-dumps-memory)
  - [Known Plaintext Attack](#known-plaintext-attack)
- [Byte-Wise Uniform Transforms](#byte-wise-uniform-transforms)
- [x86-64 Gotchas](#x86-64-gotchas)
  - [Sign Extension](#sign-extension)
  - [Loop Boundary State Updates](#loop-boundary-state-updates)
- [Custom Mangle Function Reversing](#custom-mangle-function-reversing)
- [Position-Based Transformation Reversing](#position-based-transformation-reversing)
- [Hex-Encoded String Comparison](#hex-encoded-string-comparison)
- [Signal-Based Binary Exploration](#signal-based-binary-exploration)
- [Malware Anti-Analysis Bypass via Patching](#malware-anti-analysis-bypass-via-patching)
- [Multi-Stage Shellcode Loaders](#multi-stage-shellcode-loaders)
- [Timing Side-Channel Attack](#timing-side-channel-attack)
- [Multi-Thread Anti-Debug with Decoy + Signal Handler MBA (ApoorvCTF 2026)](#multi-thread-anti-debug-with-decoy--signal-handler-mba-apoorvctf-2026)

---

## Custom VM Reversing

### Analysis Steps
1. Identify VM structure: registers, memory, instruction pointer
2. Reverse `executeIns`/`runvm` function for opcode meanings
3. Write a disassembler to parse bytecode
4. Decompile disassembly to understand algorithm

### Common VM Patterns
```c
switch (opcode) {
    case 1: *R[op1] *= op2; break;      // MUL
    case 2: *R[op1] -= op2; break;      // SUB
    case 3: *R[op1] = ~*R[op1]; break;  // NOT
    case 4: *R[op1] ^= mem[op2]; break; // XOR
    case 5: *R[op1] = *R[op2]; break;   // MOV
    case 7: if (R0) IP += op1; break;   // JNZ
    case 8: putc(R0); break;            // PRINT
    case 10: R0 = getc(); break;        // INPUT
}
```

### RVA-Based Opcode Dispatching
- Opcodes are RVAs pointing to handler functions
- Handler performs operation, reads next RVA, jumps
- Map all handlers by following RVA chain

### State Machine VMs (90K+ states)
```java
// BFS for valid path
var agenda = new ArrayDeque<State>();
agenda.add(new State(0, ""));
while (!agenda.isEmpty()) {
    var current = agenda.remove();
    if (current.path.length() == TARGET_LENGTH) {
        println(current.path);
        continue;
    }
    for (var transition : machine.get(current.state).entrySet()) {
        agenda.add(new State(transition.getValue(),
                            current.path + (char)transition.getKey()));
    }
}
```

---

## Anti-Debugging Techniques

### Common Checks
- `IsDebuggerPresent()` (Windows)
- `ptrace(PTRACE_TRACEME)` (Linux)
- `/proc/self/status` TracerPid
- Timing checks (`rdtsc`, `time()`)
- Registry checks (Windows)

### Bypass Technique
1. Identify `test` instructions after debug checks
2. Set breakpoint at the `test`
3. Modify register to bypass conditional

```bash
# In radare2
db 0x401234          # Break at test
dc                   # Run
dr eax=0             # Clear flag
dc                   # Continue
```

### LD_PRELOAD Hook
```c
#define _GNU_SOURCE
#include <dlfcn.h>
#include <sys/ptrace.h>

long int ptrace(enum __ptrace_request req, ...) {
    long int (*orig)(enum __ptrace_request, pid_t, void*, void*);
    orig = dlsym(RTLD_NEXT, "ptrace");
    // Log or modify behavior
    return orig(req, pid, addr, data);
}
```

Compile: `gcc -shared -fPIC -ldl hook.c -o hook.so`
Run: `LD_PRELOAD=./hook.so ./binary`

### pwntools Binary Patching (Crypto-Cat)
Patch out anti-debug calls directly using pwntools — replaces function with `ret` instruction:
```python
from pwn import *

elf = ELF('./challenge', checksec=False)
elf.asm(elf.symbols.ptrace, 'ret')   # Replace ptrace() with immediate return
elf.save('patched')                   # Save patched binary
```

Other common patches:
```python
elf.asm(addr, 'nop')                  # NOP out an instruction
elf.asm(addr, 'xor eax, eax; ret')    # Return 0 (bypass checks)
elf.asm(addr, 'mov eax, 1; ret')      # Return 1 (force success)
```

---

## Nanomites

### Linux (Signal-Based)
- `SIGTRAP` (`int 3`) → Custom operation
- `SIGILL` (`ud2`) → Custom operation
- `SIGFPE` (`idiv 0`) → Custom operation
- `SIGSEGV` (null deref) → Custom operation

### Windows (Debug Events)
- `EXCEPTION_DEBUG_EVENT` → Main handler
- Parent modifies child via `PTRACE_POKETEXT`
- Magic markers: `0x1337BABE`, `0xDEADC0DE`

### Analysis
1. Check for `fork()` + `ptrace(PTRACE_TRACEME)`
2. Find `WaitForDebugEvent` loop
3. Map EAX values to operations
4. Log operations to reconstruct algorithm

---

## Self-Modifying Code

### Pattern: XOR Decryption
```asm
lea     rax, next_block
mov     dl, [rcx]        ; Input char
xor_loop:
    xor     [rax+rbx], dl
    inc     rbx
    cmp     rbx, BLOCK_SIZE
    jnz     xor_loop
jmp     rax              ; Execute decrypted
```

**Solution:** Known opcode at block start reveals XOR key (flag char).

---

## Known-Plaintext XOR (Flag Prefix)

**Pattern:** Encrypted bytes given; flag format known (e.g., `0xL4ugh{`).

**Approach:**
1. Assume repeating XOR key.
2. Use known prefix (and any hint phrase) to recover key bytes.
3. Try small key lengths and validate printable output.

```python
enc = bytes.fromhex("...")  # ciphertext
known = b"0xL4ugh{say_yes_to_me"
for klen in range(2, 33):
    key = bytearray(klen)
    ok = True
    for i, b in enumerate(known):
        if i >= len(enc):
            break
        ki = i % klen
        v = enc[i] ^ b
        if key[ki] != 0 and key[ki] != v:
            ok = False
            break
        key[ki] = v
    if not ok:
        continue
    pt = bytes(enc[i] ^ key[i % klen] for i in range(len(enc)))
    if all(32 <= c < 127 for c in pt):
        print(klen, key, pt)
```

**Note:** Challenge hints often appear verbatim in the flag body (e.g., "say_yes_to_me").

### Variant: XOR with Position Index
**Pattern:** `cipher[i] = plain[i] ^ key[i % k] ^ i` (or `^ (i & 0xff)`).

**Symptoms:**
- Repeating-key XOR almost fits known prefix but breaks at later positions
- XOR with known prefix yields a "key" that changes by +1 per index

**Fix:** Remove index first, then recover key with known prefix.
```python
enc = bytes.fromhex("...")
known = b"0xL4ugh{say_yes_to_me"
for klen in range(2, 33):
    key = bytearray(klen)
    ok = True
    for i, b in enumerate(known):
        if i >= len(enc):
            break
        ki = i % klen
        v = (enc[i] ^ i) ^ b  # strip index XOR
        if key[ki] != 0 and key[ki] != v:
            ok = False
            break
        key[ki] = v
    if not ok:
        continue
    pt = bytes((enc[i] ^ i) ^ key[i % klen] for i in range(len(enc)))
    if all(32 <= c < 127 for c in pt):
        print(klen, key, pt)
```

---

## Mixed-Mode (x86-64 / x86) Stagers

**Pattern:** 64-bit ELF jumps into a 32-bit blob via far return (`retf`/`retfq`), often after anti-debug.

**Identification:**
- Bytes `0xCB` (retf) or `0xCA` (retf imm16), sometimes preceded by `0x48` (retfq)
- 32-bit disasm shows SSE ops (`psubb`, `pxor`, `paddb`) in a tight loop
- Computed jumps into the 32-bit region

**Gotchas:**
- `retf` pops **6 bytes**: 4-byte EIP + 2-byte CS (not 8)
- 32-bit blob may rely on inherited **XMM state** and **EFLAGS**
- Missing XMM/flags transfer when switching emulators yields wrong output

**Bypass/Emulation Tips:**
1. Create a UC_MODE_32 emulator, copy memory + GPRs, **EFLAGS**, and **XMM regs**
2. Run 32-bit block, then copy memory + regs back to 64-bit
3. If anti-debug uses `fork/ptrace` + patching, emulate parent to log POKEs and apply them in child

---

## LLVM Obfuscation (Control Flow Flattening)

### Pattern
```c
while (1) {
    if (i == 0xA57D3848) { /* block */ }
    if (i != 0xA5AA2438) break;
    i = 0x39ABA8E6;  // Next state
}
```

### De-obfuscation
1. GDB script to break at `je` instructions
2. Log state variable values
3. Map state transitions
4. Reconstruct true control flow

---

## S-Box / Keystream Generation

### Fisher-Yates Shuffle (Xorshift32)
```python
def gen_sbox():
    sbox = list(range(256))
    state = SEED
    for i in range(255, -1, -1):
        state = ((state << 13) ^ state) & 0xffffffff
        state = ((state >> 17) ^ state) & 0xffffffff
        state = ((state << 5) ^ state) & 0xffffffff
        j = state % (i + 1) if i > 0 else 0
        sbox[i], sbox[j] = sbox[j], sbox[i]
    return sbox
```

### Xorshift64* Keystream
```python
def gen_keystream():
    ks = []
    state = SEED_64
    mul = 0x2545f4914f6cdd1d
    for _ in range(256):
        state ^= (state >> 12)
        state ^= (state << 25)
        state ^= (state >> 27)
        state = (state * mul) & 0xffffffffffffffff
        ks.append((state >> 56) & 0xff)
    return ks
```

### Identifying Patterns
- Xorshift32: shifts 13, 17, 5 (no multiplication constant)
- Xorshift64*: shifts 12, 25, 27, then multiply by `0x2545f4914f6cdd1d`
- Other common constant: `0x9e3779b97f4a7c15` (golden ratio)

---

## SECCOMP/BPF Filter Analysis

```bash
seccomp-tools dump ./binary
```

### BPF Analysis
- `A = sys_number` followed by comparisons
- `mem[N] = A`, `A = mem[N]` for memory ops
- Map to constraint equations, solve with z3

```python
from z3 import *
flag = [BitVec(f'c{i}', 32) for i in range(14)]
s = Solver()
s.add(flag[0] >= 0x20, flag[0] < 0x7f)
# Add constraints from filter
if s.check() == sat:
    m = s.model()
    print(''.join(chr(m[c].as_long()) for c in flag))
```

---

## Exception Handler Obfuscation

### RtlInstallFunctionTableCallback
- Dynamic exception handler registration
- Handler installs new handler, modifies code
- Use x64dbg with exception handler breaks

### Vectored Exception Handlers (VEH)
- `AddVectoredExceptionHandler` installs handler
- Handler decrypts code at exception address
- Step through, dump decrypted code

---

## Memory Dump Analysis

### When Binary Dumps Memory
- Check for `/proc/self/maps` reads
- Check for `/proc/self/mem` reads
- Heap data often appended to dump

### Known Plaintext Attack
```python
prologue = bytes([0xf3, 0x0f, 0x1e, 0xfa, 0x55, 0x48, 0x89, 0xe5])
encrypted = data[func_offset:func_offset+8]
partial_key = bytes(a ^ b for a, b in zip(encrypted, prologue))
```

---

## Byte-Wise Uniform Transforms

**Pattern:** Output buffer depends on each input byte independently (no cross-byte coupling).

**Detection:**
- Change one input position → only one output position changes
- Fill input with a single byte → output buffer becomes constant

**Solve:**
1. For each byte value 0..255, run the program with that byte repeated
2. Record output byte → build mapping and inverse mapping
3. Apply inverse mapping to static target bytes to recover the flag

---

## x86-64 Gotchas

### Sign Extension
```python
esi = 0xffffffc7  # NOT -57

# For XOR: low byte only
esi_xor = esi & 0xff  # 0xc7

# For addition: full 32-bit with overflow
r12 = (r13 + esi) & 0xffffffff
```

### Loop Boundary State Updates
Assembly often splits state updates across loop boundaries:
```asm
    jmp loop_middle        ; First iteration in middle!

loop_top:                   ; State for iterations 2+
    mov  r13, sbox[a & 0xf]
    ; Uses OLD 'a', not new!

loop_middle:
    ; Main computation
    inc  a
    jne  loop_top
```

---

## Custom Mangle Function Reversing

**Pattern (Flag Appraisal):** Binary mangles input 2 bytes at a time with intermediate state, compares to static target.

**Approach:**
1. Extract static target bytes from `.rodata` section
2. Understand mangle: processes pairs with running state value
3. Write inverse function (process in reverse, undo each operation)
4. Feed target bytes through inverse → recovers flag

---

## Position-Based Transformation Reversing

**Pattern (PascalCTF 2026):** Binary transforms input by adding/subtracting position index.

**Reversing:**
```python
expected = [...]  # Extract from .rodata
flag = ''
for i, b in enumerate(expected):
    if i % 2 == 0:
        flag += chr(b - i)   # Even: input = output - i
    else:
        flag += chr(b + i)   # Odd: input = output + i
```

---

## Hex-Encoded String Comparison

**Pattern (Spider's Curse):** Input converted to hex, compared against hex constant.

**Quick solve:** Extract hex constant from strings/Ghidra, decode:
```bash
echo "4d65746143..." | xxd -r -p
```

---

## Signal-Based Binary Exploration

**Pattern (Signal Signal Little Star):** Binary uses UNIX signals as a binary tree navigation mechanism.

**Identification:**
- Multiple `sigaction()` calls with `SA_SIGINFO`
- `sigaltstack()` setup (alternate signal stack)
- Handler decodes embedded payload, installs next pair of signals
- Two types: Node (installs children) vs Leaf (prints message + exits)

**Solving approach:**
1. Hook `sigaction` via `LD_PRELOAD` to log signal installations
2. DFS through the binary tree by sending signals
3. At each stage, observe which 2 signals are installed
4. Send one, check if program exits (leaf) or installs 2 more (node)
5. If wrong leaf, backtrack and try sibling

```c
// LD_PRELOAD interposer to log sigaction calls
int sigaction(int signum, const struct sigaction *act, ...) {
    if (act && (act->sa_flags & SA_SIGINFO))
        log("SET %d SA_SIGINFO=1\n", signum);
    return real_sigaction(signum, act, oldact);
}
```

---

## Malware Anti-Analysis Bypass via Patching

**Pattern (Carrot):** Malware with multiple environment checks before executing payload.

**Common checks to patch:**
| Check | Technique | Patch |
|-------|-----------|-------|
| `ptrace(PTRACE_TRACEME)` | Anti-debug | Change `cmp -1` to `cmp 0` |
| `sleep(150)` | Anti-sandbox timing | Change sleep value to 1 |
| `/proc/cpuinfo` "hypervisor" | Anti-VM | Flip `JNZ` to `JZ` |
| "VMware"/"VirtualBox" strings | Anti-VM | Flip `JNZ` to `JZ` |
| `getpwuid` username check | Environment | Flip comparison |
| `LD_PRELOAD` check | Anti-hook | Skip check |
| Fan count / hardware check | Anti-VM | Flip `JLE` to `JGE` |
| Hostname check | Environment | Flip `JNZ` to `JZ` |

**Ghidra patching workflow:**
1. Find check function, identify the conditional jump
2. Click on instruction → `Ctrl+Shift+G` → modify opcode
3. For `JNZ` (0x75) → `JZ` (0x74), or vice versa
4. For immediate values: change operand bytes directly
5. Export: press `O` → choose "Original File" format
6. `chmod +x` the patched binary

**Server-side validation bypass:**
- If patched binary sends system info to remote server, patch the data too
- Modify string addresses in data-gathering functions
- Change format strings to embed correct values directly

---

## Multi-Stage Shellcode Loaders

**Pattern (I Heard You Liked Loaders):** Nested shellcode with XOR decode loops and anti-debug.

**Debugging workflow:**
1. Break at `call rax` in launcher, step into shellcode
2. Bypass ptrace anti-debug: step to syscall, `set $rax=0`
3. Step through XOR decode loop (or break on `int3` if hidden)
4. Repeat for each stage until final payload

**Flag extraction from `mov` instructions:**
```python
# Final stage loads flag 4 bytes at a time via mov ebx, value
# Extract little-endian 4-byte chunks
values = [0x6174654d, 0x7b465443, ...]  # From disassembly
flag = b''.join(v.to_bytes(4, 'little') for v in values)
```

---

## Timing Side-Channel Attack

**Pattern (Clock Out):** Validation time varies per correct character (longer sleep on match).

**Exploitation:**
```python
import time
from pwn import *

flag = ""
for pos in range(flag_length):
    best_char, best_time = '', 0
    for c in string.printable:
        io = remote(host, port)
        start = time.time()
        io.sendline((flag + c).ljust(total_len, 'X'))
        io.recvall()
        elapsed = time.time() - start
        if elapsed > best_time:
            best_time = elapsed
            best_char = c
        io.close()
    flag += best_char
```

---

## Multi-Thread Anti-Debug with Decoy + Signal Handler MBA (ApoorvCTF 2026)

**Pattern (A Golden Experience Requiem):** Multi-threaded binary with layered anti-analysis: Thread 1 performs decoy operations (fake AES + deliberate crash via `ud2`), Thread 2 does the real flag computation in a SIGSEGV signal handler using Mixed Boolean Arithmetic (MBA), Thread 3 erases memory to prevent post-mortem analysis.

**Thread layout:**
| Thread | Purpose | Trap |
|--------|---------|------|
| Thread 1 | Decoy: AES-looking operations → `ud2` crash | Analysts waste time reversing fake crypto |
| Thread 2 | Real flag: SIGSEGV handler with MBA transforms | Hidden in signal handler, not main code path |
| Thread 3 | Memory eraser: zeros out flag data after computation | Prevents memory dumping |
| Main | rdtsc-based anti-debug timing check | Penalizes debugger-attached execution |

**Solving approach — pure Python emulation of MBA logic:**
```python
# MBA helpers (extracted from assembly)
def mba_add(a, b): return (a + b) & 0xff
def mba_xor(a, b): return (a ^ b) & 0xff

def mba_transform(i):
    """Position-dependent transform from signal handler."""
    val = (i * 7 + 0x3f) & 0xff
    rotated = ((i << 3) | (i >> 5)) & 0xff
    return mba_xor(val, rotated)

# S-box (SHA-256 initial hash values repurposed)
SBOX = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
        0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]

def sbox_lookup(i):
    idx = i & 7
    shift = ((i >> 3) & 3) * 8
    return (SBOX[idx] >> shift) & 0xff

# Two interleaved rodata arrays (even indices → array1, odd → array2)
rodata1 = bytes.fromhex("39407691b717c97879013adf3a2adea11c2b04e0")
rodata2 = bytes.fromhex("bb19b025e37eaa786c4116e7aeea00c9c623940d")

flag = []
for i in range(40):  # flag length
    t = mba_transform(i)
    s = sbox_lookup(i)
    mem = rodata1[i // 2] if i % 2 == 0 else rodata2[i // 2]
    flag.append(chr(t ^ s ^ mem))

print(''.join(flag))
```

**Key insight:** The real flag logic is in the signal handler (SIGSEGV/SIGILL), not the main thread. Thread 1's AES-like code and `ud2` crash are intentional misdirection. The `rdtsc` timing check detects debuggers and corrupts output. Bypass by extracting the MBA logic from assembly and reimplementing in Python — never run the binary under a debugger.

**Detection indicators:**
- Multiple `pthread_create` calls with different handler functions
- `signal(SIGSEGV, handler)` or `sigaction` setup
- `ud2` instruction (deliberate illegal instruction)
- `rdtsc` instructions for timing checks
- SHA-256 constants (0x6a09e667...) used as lookup tables, not for hashing



---

<!-- Source: platforms.md -->

# CTF Reverse - Platform-Specific Reversing

macOS/iOS, embedded/IoT firmware, kernel driver, automotive, and game engine reverse engineering.

## Table of Contents
- [macOS / iOS Reversing](#macos--ios-reversing)
  - [Mach-O Binary Format](#mach-o-binary-format)
  - [Code Signing & Entitlements](#code-signing--entitlements)
  - [Objective-C Runtime RE](#objective-c-runtime-re)
  - [Swift Binary Reversing](#swift-binary-reversing)
  - [iOS App Analysis](#ios-app-analysis)
  - [dyld / Dynamic Linking](#dyld--dynamic-linking)
- [Embedded / IoT Firmware RE](#embedded--iot-firmware-re)
  - [Firmware Extraction](#firmware-extraction)
  - [Firmware Unpacking](#firmware-unpacking)
  - [Architecture-Specific Notes](#architecture-specific-notes)
  - [RTOS Analysis](#rtos-analysis)
- [Kernel Driver Reversing](#kernel-driver-reversing)
  - [Linux Kernel Modules](#linux-kernel-modules)
  - [eBPF Programs](#ebpf-programs)
  - [Windows Kernel Drivers](#windows-kernel-drivers)
- [Game Engine Reversing](#game-engine-reversing)
  - [Unreal Engine](#unreal-engine)
  - [Unity (Beyond IL2CPP)](#unity-beyond-il2cpp)
  - [Anti-Cheat Analysis](#anti-cheat-analysis)
  - [Lua-Scripted Games](#lua-scripted-games)
- [Automotive / CAN Bus RE](#automotive--can-bus-re)
- [RISC-V (Advanced)](#risc-v-advanced)
  - [Custom Extensions](#custom-extensions)
  - [Privileged Modes](#privileged-modes)
  - [RISC-V Debugging](#risc-v-debugging)

---

## macOS / iOS Reversing

### Mach-O Binary Format

```bash
# File identification
file binary                    # "Mach-O 64-bit executable arm64" or "x86_64"
otool -l binary               # Load commands (segments, dylibs, entry point)
otool -L binary               # Linked dynamic libraries

# Universal (fat) binaries — multiple architectures in one file
lipo -info universal_binary    # List architectures
lipo universal_binary -thin arm64 -output binary_arm64  # Extract one arch

# Segments and sections
otool -l binary | grep -A5 "segment\|section"
# Key segments: __TEXT (code), __DATA (globals), __LINKEDIT (symbols)
# Key sections: __text (instructions), __cstring (C strings), __objc_methname
```

**Key Mach-O concepts:**
- Load commands drive the dynamic linker (`dyld`)
- `LC_MAIN` → entry point (replaces `LC_UNIXTHREAD`)
- `LC_LOAD_DYLIB` → shared library dependencies
- `LC_CODE_SIGNATURE` → code signing blob
- `__DATA_CONST.__got` → Global Offset Table
- `__DATA.__la_symbol_ptr` → Lazy symbol pointers (like PLT)

### Code Signing & Entitlements

```bash
# Check code signature
codesign -dvvv binary
codesign --verify binary

# Extract entitlements (capability permissions)
codesign -d --entitlements - binary
# Key entitlements: com.apple.security.app-sandbox, com.apple.security.network.client

# Remove code signature (for patching)
codesign --remove-signature binary

# Re-sign (ad-hoc, for testing)
codesign -f -s - binary
```

**CTF relevance:** Patched binaries need re-signing to run on macOS. Ad-hoc signing (`-s -`) works for local testing.

### Objective-C Runtime RE

```bash
# Dump Objective-C class info
class-dump binary > classes.h
# Shows: @interface, @protocol, method signatures with types

# Runtime inspection with lldb
(lldb) expression -l objc -O -- [NSClassFromString(@"ClassName") new]
(lldb) expression -l objc -O -- [[ClassName alloc] init]

# Method swizzling detection (anti-tamper)
# Look for: method_exchangeImplementations, class_replaceMethod
```

**Objective-C in disassembly:**
```text
# objc_msgSend(receiver, selector, ...) is THE dispatch mechanism
# RDI = self (receiver), RSI = selector (char* method name)

# In Ghidra/IDA, look for:
objc_msgSend(obj, "checkPassword:", input)
# Selector strings are in __objc_methname section
# Cross-reference selectors to find implementations
```

**class-dump alternatives:**
- `dsdump` — faster, supports Swift + Objective-C
- `otool -oV binary` — dump Objective-C segments
- Ghidra: Enable "Objective-C" analyzer in Analysis Options

### Swift Binary Reversing

```bash
# Detect Swift
strings binary | grep "swift"
otool -l binary | grep "swift"   # __swift5_* sections

# Swift demangling
swift demangle 's14MyApp0A8ClassC10checkInput6resultSbSS_tF'
# → MyApp.MyAppClass.checkInput(result: String) -> Bool

# xcrun swift-demangle < mangled_names.txt
```

**Swift in disassembly:**
```text
# Swift uses value witness tables (VWT) for type operations
# Protocol witness tables (PWT) for dynamic dispatch (like vtables)

# Key runtime functions to watch:
swift_allocObject          → heap allocation
swift_release             → reference count decrement
swift_bridgeObjectRetain  → bridged (ObjC ↔ Swift) retain
swift_once                → lazy initialization (like dispatch_once)

# String layout:
# Small strings (≤15 bytes): inline in 16-byte buffer, tagged pointer
# Large strings: heap-allocated, pointer + length + flags

# Array<T>: pointer to ContiguousArrayStorage (header + elements)
# Dictionary<K,V>: hash table with open addressing
```

**Ghidra for Swift:** Enable "Swift" language module. Swift metadata sections (`__swift5_types`, `__swift5_proto`) contain type descriptors that Ghidra can parse.

### iOS App Analysis

```bash
# Extract IPA (iOS app package)
unzip app.ipa -d extracted/
ls extracted/Payload/*.app/

# Check if encrypted (App Store encryption / FairPlay DRM)
otool -l extracted/Payload/*.app/binary | grep -A4 "LC_ENCRYPTION_INFO"
# cryptid = 1 means encrypted, 0 means decrypted

# Decrypt with frida-ios-dump (requires jailbroken device)
# Or use Clutch / bfdecrypt on device
frida-ios-dump -H jailbroken_ip -p 22 "App Name"

# Analyze decrypted binary
class-dump decrypted_binary > headers.h
```

**Jailbreak detection and bypass:**
```javascript
// Common jailbreak checks:
// 1. Check for Cydia/Sileo
// 2. Check /private/var/lib/apt
// 3. fork() succeeds (sandboxed apps can't fork)
// 4. Open /etc/apt, /bin/sh with write
// 5. Check for substrate/substitute libraries

// Frida bypass:
var paths = ["/Applications/Cydia.app", "/bin/sh", "/etc/apt",
             "/private/var/lib/apt", "/usr/bin/ssh"];
Interceptor.attach(Module.findExportByName(null, "access"), {
    onEnter(args) {
        this.path = Memory.readUtf8String(args[0]);
    },
    onLeave(retval) {
        if (paths.some(p => this.path && this.path.includes(p))) {
            retval.replace(-1);  // File not found
        }
    }
});
```

### dyld / Dynamic Linking

```bash
# DYLD environment variables (for analysis, blocked in hardened runtime)
DYLD_PRINT_LIBRARIES=1 ./binary       # Print loaded dylibs
DYLD_INSERT_LIBRARIES=hook.dylib ./binary  # Inject dylib (like LD_PRELOAD)
# Note: SIP (System Integrity Protection) blocks this for system binaries

# Inspect dyld shared cache (contains all system frameworks)
dyld_shared_cache_util -list /System/Cryptexes/OS/System/Library/dyld/dyld_shared_cache_arm64e
```

---

## Embedded / IoT Firmware RE

### Firmware Extraction

```bash
# binwalk — firmware analysis and extraction
binwalk firmware.bin                        # Identify embedded filesystems, compressed data
binwalk -e firmware.bin                     # Extract all identified components
binwalk -Me firmware.bin                    # Recursive extraction (matryoshka)
binwalk --dd='.*' firmware.bin              # Extract everything raw

# Manual extraction by signature
strings firmware.bin | head -50             # Look for version strings, filesystem markers
hexdump -C firmware.bin | grep "hsqs"       # SquashFS magic
hexdump -C firmware.bin | grep "UBI#"       # UBI magic
```

**Hardware extraction methods (physical access):**
```text
UART:  Serial console — often gives root shell or bootloader access
       Tools: USB-UART adapter, baudrate detection (usually 115200)
       Identify: 4 pins (GND, TX, RX, VCC), use multimeter

JTAG:  Direct CPU debug — read/write flash, halt CPU, set breakpoints
       Tools: OpenOCD, J-Link, Bus Pirate
       Identify: 10/14/20-pin header, use JTAGulator for auto-detection

SPI Flash: Direct chip read — dump entire firmware
           Tools: flashrom, CH341A programmer
           Identify: 8-pin SOIC chip (Winbond, Macronix, etc.)

eMMC:  Embedded MMC — common in routers, phones
       Tools: eMMC reader, direct solder to test pads
```

### Firmware Unpacking

```bash
# SquashFS (most common in routers)
unsquashfs -d output/ squashfs-root.sqfs
# If custom compression: try different compressors (-comp xz|lzma|lzo|gzip)

# JFFS2
jefferson -d output/ jffs2.img

# UBI/UBIFS
ubireader_extract_images firmware.ubi
ubireader_extract_files ubifs.img

# CPIO (initramfs)
cpio -idv < initramfs.cpio

# Device tree blob
dtc -I dtb -O dts -o output.dts device_tree.dtb

# Kernel extraction
binwalk -e firmware.bin
# Look for: zImage, uImage, vmlinux
# Extract vmlinux from compressed: vmlinux-to-elf tool
```

### Architecture-Specific Notes

**ARM (most common in IoT):**
```bash
# Cross-toolchain
apt install gcc-arm-linux-gnueabihf gdb-multiarch

# QEMU emulation
qemu-arm -L /usr/arm-linux-gnueabihf/ ./arm_binary
qemu-arm -g 1234 ./arm_binary    # Start GDB server on port 1234
gdb-multiarch -ex 'target remote :1234' ./arm_binary

# ARM vs Thumb: ARM instructions are 4 bytes, Thumb are 2 bytes
# LSB of function pointer indicates mode: 0=ARM, 1=Thumb
# Ghidra: Right-click → Processor Options → ARM/Thumb mode
```

**MIPS (routers, embedded):**
```bash
# Big-endian vs little-endian — check ELF header or file command
file binary    # "MIPS, MIPS32 rel2 (MIPS-II), big-endian" or "little-endian"

# Emulation
qemu-mips -L /usr/mips-linux-gnu/ ./mips_binary         # Big-endian
qemu-mipsel -L /usr/mipsel-linux-gnu/ ./mipsel_binary   # Little-endian

# Key MIPS patterns:
# Branch delay slots — instruction AFTER branch always executes
# $gp (global pointer) — used for PIC, points to .got
# lui + addiu pair — loads 32-bit constant (upper 16 + lower 16)
```

**RISC-V:** See main [tools.md](tools.md#risc-v-binary-analysis-ehax-2026) for Capstone disassembly and [RISC-V Advanced](#risc-v-advanced) below.

### RTOS Analysis

```text
FreeRTOS:
  - Tasks (like threads): xTaskCreate → function pointer + stack
  - Strings: "IDLE", "Tmr Svc", task names
  - xQueueSend/xQueueReceive → inter-task communication
  - Look for vTaskDelay() for timing, xSemaphoreTake() for sync

Zephyr:
  - k_thread_create → kernel thread creation
  - k_msgq_put/k_msgq_get → message queues
  - CONFIG_* symbols reveal kernel configuration

Bare metal (no OS):
  - Interrupt vector table at address 0x0 or 0x08000000 (STM32)
  - main loop pattern: while(1) { read_input(); process(); output(); }
  - Peripheral registers at memory-mapped addresses (check datasheet)
```

---

## Kernel Driver Reversing

### Linux Kernel Modules

```bash
# Identify kernel module
file module.ko                      # "ELF 64-bit LSB relocatable"
modinfo module.ko                   # Module info (description, author, license)

# List module symbols
nm module.ko | grep -v " U "       # Exported symbols

# Strings for quick recon
strings module.ko | grep -i "flag\|secret\|ioctl\|device"

# Find ioctl handler
# Key pattern: .unlocked_ioctl = my_ioctl_handler in file_operations struct
# In Ghidra: find struct with function pointers, identify by position

# Load in Ghidra
# Language: x86:LE:64:default
# Base address: doesn't matter for .ko (relocatable)
# Look for init_module / cleanup_module entry points
```

**Common kernel module CTF patterns:**
```c
// Device creation (creates /dev/challenge)
alloc_chrdev_region(&dev, 0, 1, "challenge");
cdev_init(&cdev, &fops);

// ioctl handler (main interface)
long my_ioctl(struct file *f, unsigned int cmd, unsigned long arg) {
    switch (cmd) {
        case CUSTOM_CMD_1: /* operation */ break;
        case CUSTOM_CMD_2: /* operation */ break;
    }
}

// copy_from_user / copy_to_user — data transfer with userspace
copy_from_user(kernel_buf, (void __user *)arg, size);
copy_to_user((void __user *)arg, kernel_buf, size);
```

**Debugging kernel modules:**
```bash
# QEMU + GDB for kernel debugging
qemu-system-x86_64 -kernel bzImage -initrd initrd.cpio -s -S \
  -append "console=ttyS0 nokaslr" -nographic

# In another terminal
gdb vmlinux
(gdb) target remote :1234
(gdb) lx-symbols           # Load module symbols (requires scripts)
(gdb) add-symbol-file module.ko 0x<loaded_address>
```

### eBPF Programs

```bash
# Dump eBPF programs from running system
bpftool prog list
bpftool prog dump xlated id <N>    # Disassemble
bpftool prog dump jited id <N>     # JIT'd machine code

# eBPF bytecode analysis
# eBPF has 11 registers (r0-r10), 64-bit
# r0 = return value, r1-r5 = arguments, r10 = frame pointer
# Instructions are 8 bytes each

# Disassemble .o file containing eBPF
llvm-objdump -d ebpf_prog.o

# Key eBPF patterns:
# bpf_map_lookup_elem → read from map
# bpf_map_update_elem → write to map
# bpf_probe_read → read kernel memory
# bpf_trace_printk → debug output
```

### Windows Kernel Drivers

```bash
# .sys files are PE format — load in IDA/Ghidra as normal PE
# Entry point: DriverEntry(PDRIVER_OBJECT, PUNICODE_STRING)

# Key patterns:
# IoCreateDevice → creates device object
# IRP_MJ_DEVICE_CONTROL → ioctl handler
# MmMapIoSpace → memory-mapped I/O
# ObReferenceObjectByHandle → get kernel object from handle
# ZwCreateFile/ZwReadFile → kernel-mode file operations
```

---

## Game Engine Reversing

### Unreal Engine

```bash
# Pak file extraction
# UnrealPakTool or quickbms with unreal_tournament_4.bms
unrealpak.exe extract GameName.pak -output extracted/

# UE4/UE5 asset formats:
# .uasset — serialized UObject (meshes, textures, blueprints)
# .umap — level/map data
# .ushaderbytecode — compiled shader
# FModel (https://fmodel.app/) — GUI asset viewer/extractor
```

**Blueprint reversing:**
```text
Blueprints compile to bytecode in .uasset files.
- UAssetGUI / FModel to browse Blueprint assets
- Kismet bytecode → visual scripting logic
- Look for: K2_SetTimer, DoOnce, Branch, Custom Events
- Flag logic often in Blueprint event graphs, not C++
```

**UE4/UE5 C++ reversing:**
```bash
# Key engine classes:
# UObject → base class for everything
# AActor → entities in the world
# UGameInstance → game state
# APlayerController → player input handling

# Reflection system — UCLASS(), UPROPERTY(), UFUNCTION() macros
# Generates metadata accessible at runtime
# In Ghidra: look for UClass::StaticClass() calls → type identification

# String handling: FString (UTF-16), FName (hashed identifier), FText (localized)
# In memory: FString = {TCHAR* Data, int32 ArrayNum, int32 ArrayMax}
```

### Unity (Beyond IL2CPP)

See [languages.md](languages.md#unity-il2cpp-games) for IL2CPP basics.

**Mono-based Unity (not IL2CPP):**
```bash
# Managed assemblies in Data/Managed/ directory
# Assembly-CSharp.dll contains game logic
dnspy Assembly-CSharp.dll       # Full decompilation + debugging
ilspy Assembly-CSharp.dll       # Decompilation only

# Common Unity patterns:
# MonoBehaviour.Start() → initialization
# MonoBehaviour.Update() → per-frame logic
# PlayerPrefs.GetString("key") → stored data
# SceneManager.LoadScene("level") → scene transitions
```

**Unity asset extraction:**
```bash
# AssetStudio — extract textures, models, audio, scripts
# AssetRipper — comprehensive Unity asset extraction
# UABE (Unity Asset Bundle Extractor) — low-level asset editing

# Search for flags in:
# - Text assets (.txt, .json)
# - TextMesh / UI Text components
# - Shader source code
# - ScriptableObject assets
# - PlayerPrefs save files
```

### Anti-Cheat Analysis

```text
For CTF challenges involving game anti-cheat:

EasyAntiCheat (EAC):
- Kernel driver (EasyAntiCheat_EOS.sys)
- User-mode module injected into game
- Integrity checks on game memory
- Bypass: kernel-level memory R/W (for research only)

BattlEye:
- BEService.exe → BEClient.dll injected
- Communication via encrypted channel
- Screenshot capture, process scanning
- Module: BEClient2.dll

Valve Anti-Cheat (VAC):
- User-mode only (no kernel driver)
- Module hashing, memory scanning
- Network-based detection (server-side)
- Delayed bans (not immediate)

CTF approach:
1. Identify which anti-cheat (strings, loaded modules)
2. For CTF: usually need to bypass specific check, not full anti-cheat
3. Memory patching: find game state in memory, modify values
4. Save file manipulation: often easier than runtime cheating
```

### Lua-Scripted Games

```bash
# Many games embed Lua for scripting
# Look for: lua51.dll, luajit.dll, .lua files in assets

# Luac bytecode decompilation
luadec bytecode.luac > decompiled.lua      # Lua 5.1-5.3
unluac bytecode.luac > decompiled.lua      # Alternative

# LuaJIT bytecode
luajit -bl bytecode.lua                     # Disassemble
# ljd (LuaJIT decompiler): python3 ljd bytecode.lua

# Embedded Lua: strings binary | grep "lua_\|luaL_\|LUA_"
# Hook lua_pcall to intercept script execution
```

---

## Automotive / CAN Bus RE

```bash
# CAN bus interface setup
sudo ip link set can0 type can bitrate 500000
sudo ip link set up can0

# Capture CAN traffic
candump can0                               # Live capture
candump -l can0                            # Log to file
cansniffer can0                            # Filter/highlight changes

# Replay CAN messages
canplayer -I logfile.log can0
cansend can0 7DF#0201000000000000          # Send single frame (OBD-II request)

# UDS (Unified Diagnostic Services) — common in automotive CTF
# Service 0x27: Security Access (seed-key authentication)
# Service 0x2E: Write Data By Identifier
# Service 0x31: Routine Control

# Decode CAN frames
# ID: 11-bit or 29-bit identifier
# DLC: Data Length Code (0-8 bytes)
# Data: up to 8 bytes payload
```

**CTF automotive patterns:**
- Seed-key bypass: Reverse the key derivation algorithm from ECU firmware
- CAN message replay: Capture legitimate command, replay to unlock feature
- Firmware extraction from ECU via UDS/KWP2000

---

## RISC-V (Advanced)

Beyond basic disassembly (see [tools.md](tools.md#risc-v-binary-analysis-ehax-2026)):

### Custom Extensions

```text
Bitmanip extensions (Zbb, Zbc, Zbs):
  clz, ctz, cpop         → count leading/trailing zeros, popcount
  orc.b, rev8            → byte-level bit manipulation
  andn, orn, xnor        → negated logic operations
  clmul, clmulh, clmulr  → carry-less multiplication (crypto)
  bset, bclr, binv, bext → single-bit operations

Crypto extensions (Zk*):
  aes32esi, aes32dsmi     → AES round operations
  sha256sig0, sha512sum0  → SHA hash acceleration
  sm3p0, sm4ed            → Chinese crypto standards
```

### Privileged Modes

```text
Machine mode (M):  Highest privilege, firmware/bootloader
Supervisor mode (S): OS kernel
User mode (U):      Applications

CSR registers to watch:
  mstatus/sstatus    → privilege level, interrupt enable
  mtvec/stvec       → trap handler address
  mepc/sepc         → exception return address
  mcause/scause     → trap cause
  satp              → page table root (virtual memory)
```

### RISC-V Debugging

```bash
# OpenOCD + GDB for hardware debugging
openocd -f interface/jlink.cfg -f target/riscv.cfg

# GDB for RISC-V
riscv64-unknown-elf-gdb binary
(gdb) target remote :3333

# QEMU with GDB server
qemu-riscv64 -g 1234 -L /usr/riscv64-linux-gnu/ ./binary
riscv64-linux-gnu-gdb -ex 'target remote :1234' ./binary
```



---

<!-- Source: quickref.md -->

# ctf-reverse — Quick Reference

Inline code snippets and quick-reference tables. Loaded on demand from `SKILL.md`. All detailed techniques live in the category-specific support files listed in `SKILL.md#additional-resources`.


## Problem-Solving Workflow

1. **Start with strings extraction** - many easy challenges have plaintext flags
2. **Try ltrace/strace** - dynamic analysis often reveals flags without reversing
3. **Try Frida hooking** - hook strcmp/memcmp to capture expected values without reversing
4. **Try angr** - symbolic execution solves many flag-checkers automatically
5. **Try Qiling** - emulate foreign-arch binaries or bypass heavy anti-debug without artifacts
6. **Map control flow** before modifying execution
7. **Automate manual processes** via scripting (r2pipe, Frida, angr, Python)
8. **Validate assumptions** by comparing decompiler outputs (dogbolt.org for side-by-side)

## Quick Wins (Try First!)

```bash
# Plaintext flag extraction
strings binary | grep -E "flag\{|CTF\{|pico"
strings binary | grep -iE "flag|secret|password"
rabin2 -z binary | grep -i "flag"

# Dynamic analysis - often captures flag directly
ltrace ./binary
strace -f -s 500 ./binary

# Hex dump search
xxd binary | grep -i flag

# Run with test inputs
./binary AAAA
echo "test" | ./binary
```

## Initial Analysis

```bash
file binary           # Type, architecture
checksec --file=binary # Security features (for pwn)
chmod +x binary       # Make executable
```

## Memory Dumping Strategy

**Key insight:** Let the program compute the answer, then dump it. Break at final comparison (`b *main+OFFSET`), enter any input of correct length, then `x/s $rsi` to dump computed flag.

## Decoy Flag Detection

**Pattern:** Multiple fake targets before real check.

**Identification:**
1. Look for multiple comparison targets in sequence
2. Check for different success messages
3. Trace which comparison is checked LAST

**Solution:** Set breakpoint at FINAL comparison, not earlier ones.

## GDB PIE Debugging

PIE binaries randomize base address. Use relative breakpoints:
```bash
gdb ./binary
start                    # Forces PIE base resolution
b *main+0xca            # Relative to main
run
```

## Comparison Direction (Critical!)

**Two patterns:**
1. `transform(flag) == stored_target` - Reverse the transform
2. `transform(stored_target) == flag` - Flag IS the transformed data!

**Pattern 2 solution:** Don't reverse - just apply transform to stored target.

## Common Encryption Patterns

- XOR with single byte - try all 256 values
- XOR with known plaintext (`flag{`, `CTF{`)
- RC4 with hardcoded key
- Custom permutation + XOR
- XOR with position index (`^ i` or `^ (i & 0xff)`) layered with a repeating key

## Quick Tool Reference

```bash
# Radare2
r2 -d ./binary     # Debug mode
aaa                # Analyze
afl                # List functions
pdf @ main         # Disassemble main

# Ghidra (headless)
analyzeHeadless project/ tmp -import binary -postScript script.py

# IDA
ida64 binary       # Open in IDA64
```

## Binary Types

### Python .pyc
Disassemble with `marshal.load()` + `dis.dis()`. Header: 8 bytes (2.x), 12 (3.0-3.6), 16 (3.7+). See [languages.md](languages.md#python-bytecode-reversing-disdis-output).

### WASM
```bash
wasm2c checker.wasm -o checker.c
gcc -O3 checker.c wasm-rt-impl.c -o checker

# WASM patching (game challenges):
wasm2wat main.wasm -o main.wat    # Binary → text
# Edit WAT: flip comparisons, change constants
wat2wasm main.wat -o patched.wasm # Text → binary
```

**WASM game patching (Tac Tic Toe, Pragyan 2026):** If proof generation is independent of move quality, patch minimax (flip `i64.lt_s` → `i64.gt_s`, change bestScore sign) to make AI play badly while proofs remain valid. Invoke `/ctf-misc` for full game patching patterns (games-and-vms).

### Android APK
`apktool d app.apk -o decoded/` for resources; `jadx app.apk` for Java decompilation. Check `decoded/res/values/strings.xml` for flags. See [tools.md](tools.md#android-apk).

### Flutter APK (Dart AOT)
If `lib/arm64-v8a/libapp.so` + `libflutter.so` present, use [Blutter](https://github.com/worawit/blutter): `python3 blutter.py path/to/app/lib/arm64-v8a out_dir`. Outputs reconstructed Dart symbols + Frida script. See [tools.md](tools.md#flutter-apk-blutter).

### .NET
- dnSpy - debugging + decompilation
- ILSpy - decompiler

### Packed (UPX)
```bash
upx -d packed -o unpacked
```
If unpacking fails, inspect UPX metadata first: verify UPX section names, header fields, and version markers are intact. If metadata looks tampered or uncertain, review UPX source on GitHub to identify likely modification points. 

### Tauri Packed Desktop Apps
Tauri embeds Brotli-compressed frontend assets in the executable. Find `index.html` xrefs to locate asset index table, dump blobs, Brotli decompress. Reference: `tauri-codegen/src/embedded_assets.rs`.

## Anti-Debugging Bypass

Common checks:
- `IsDebuggerPresent()` / PEB.BeingDebugged / NtQueryInformationProcess (Windows)
- `ptrace(PTRACE_TRACEME)` / `/proc/self/status` TracerPid (Linux)
- TLS callbacks (run before main — check PE TLS Directory)
- Timing checks (`rdtsc`, `clock_gettime`, `GetTickCount`)
- Hardware breakpoint detection (DR0-DR3 via GetThreadContext)
- INT3 scanning / code self-hashing (CRC over .text section)
- Signal-based: SIGTRAP handler, SIGALRM timeout, SIGSEGV for real logic
- Frida/DBI detection: `/proc/self/maps` scan, port 27042, inline hook checks

Bypass: Set breakpoint at check, modify register to bypass conditional.
pwntools patch: `elf.asm(elf.symbols.ptrace, 'ret')` to replace function with immediate return. See [patterns.md](patterns.md#pwntools-binary-patching-crypto-cat).

For comprehensive anti-analysis techniques and bypasses (30+ methods with code), see [anti-analysis.md](anti-analysis.md).

## S-Box / Keystream Patterns

**Xorshift32:** Shifts 13, 17, 5
**Xorshift64:** Shifts 12, 25, 27
**Magic constants:** `0x2545f4914f6cdd1d`, `0x9e3779b97f4a7c15`

## Custom VM Analysis

1. Identify structure: registers, memory, IP
2. Reverse `executeIns` for opcode meanings
3. Write disassembler mapping opcodes to mnemonics
4. Often easier to bruteforce than fully reverse
5. Look for the bytecode file loaded via command-line arg

See [patterns.md](patterns.md#custom-vm-reversing) for VM workflow, opcode tables, and state machine BFS.

## Python Bytecode Reversing

XOR flag checkers with interleaved even/odd tables are common. See [languages.md](languages.md#python-bytecode-reversing-disdis-output) for bytecode analysis tips and reversing patterns.

## Signal-Based Binary Exploration

Binary uses UNIX signals as binary tree navigation; hook `sigaction` via `LD_PRELOAD`, DFS by sending signals. See [patterns.md](patterns.md#signal-based-binary-exploration).

## Malware Anti-Analysis Bypass via Patching

Flip `JNZ`/`JZ` (0x75/0x74), change sleep values, patch environment checks in Ghidra (`Ctrl+Shift+G`). See [patterns.md](patterns.md#malware-anti-analysis-bypass-via-patching).

## Expected Values Tables

**Locating:**
```bash
objdump -s -j .rodata binary | less
# Look near comparison instructions
# Size matches flag length
```

## x86-64 Gotchas

Sign extension and 32-bit truncation pitfalls. See [patterns.md](patterns.md#x86-64-gotchas) for details and code examples.

## Iterative Solver Pattern

Try each byte (0-255) per position, match against expected output. **Uniform transform shortcut:** if one input byte only changes one output byte, build 0..255 mapping then invert. See [patterns.md](patterns.md) for full implementation.

## Unicorn Emulation (Complex State)

`from unicorn import *` -- map segments, set up stack, hook to trace. **Mixed-mode pitfall:** 64-bit stub jumping to 32-bit via `retf` requires switching to UC_MODE_32 and copying GPRs + EFLAGS + XMM regs. See [tools.md](tools.md#unicorn-emulation).

## Multi-Stage Shellcode Loaders

Nested shellcode with XOR decode loops; break at `call rax`, bypass ptrace with `set $rax=0`, extract flag from `mov` instructions. See [patterns.md](patterns.md#multi-stage-shellcode-loaders).

## Timing Side-Channel Attack

Validation time varies per correct character; measure elapsed time per candidate to recover flag byte-by-byte. See [patterns.md](patterns.md#timing-side-channel-attack).

## Godot Game Asset Extraction

Use KeyDot to extract encryption key from executable, then gdsdecomp to extract .pck package. See [languages.md](languages.md#godot-game-asset-extraction).

## Roblox Place File Analysis

Query Asset Delivery API for version history; parse `.rbxlbin` chunks (INST/PROP/PRNT) to diff script sources across versions. See [languages.md](languages.md#roblox-place-file-analysis).

## Unstripped Binary Information Leaks

**Pattern (Bad Opsec):** Debug info and file paths leak author identity.

**Quick checks:**
```bash
strings binary | grep "/home/"    # Home directory paths
strings binary | grep "/Users/"   # macOS paths
file binary                       # Check if stripped
readelf -S binary | grep debug    # Debug sections present?
```

## Custom Mangle Function Reversing

Binary mangles input 2 bytes at a time with running state; extract target from `.rodata`, write inverse function. See [patterns.md](patterns.md#custom-mangle-function-reversing).

## Rust serde_json Schema Recovery

Disassemble serde `Visitor` implementations to recover expected JSON schema; field names in order reveal flag. See [languages.md](languages.md#rust-serde_json-schema-recovery).

## Position-Based Transformation Reversing

Binary adds/subtracts position index; reverse by undoing per-index offset. See [patterns.md](patterns.md#position-based-transformation-reversing).

## Hex-Encoded String Comparison

Input converted to hex, compared against constant. Decode with `xxd -r -p`. See [patterns.md](patterns.md#hex-encoded-string-comparison).

## Embedded ZIP + XOR License Decryption

Binary with named symbols (`EMBEDDED_ZIP`, `ENCRYPTED_MESSAGE`) in `.rodata` → extract ZIP containing license, XOR encrypted message with license bytes to recover flag. No execution needed. See [patterns-ctf-2.md](patterns-ctf-2.md#embedded-zip--xor-license-decryption-metactf-2026).

## Stack String Deobfuscation (.rodata XOR Blob)

Binary mmaps `.rodata` blob, XOR-deobfuscates, uses it to validate input. Reimplement verification loop with pyelftools to extract blob. Look for `0x9E3779B9`, `0x85EBCA6B` constants and `rol32()`. See [patterns-ctf-2.md](patterns-ctf-2.md#stack-string-deobfuscation-from-rodata-xor-blob-nullcon-2026).

## Prefix Hash Brute-Force

Binary hashes every prefix independently. Recover one character at a time by matching prefix hashes. See [patterns-ctf-2.md](patterns-ctf-2.md#prefix-hash-brute-force-nullcon-2026).

## Mathematical Convergence Bitmap

**Pattern:** Binary classifies coordinate pairs by Newton's method convergence (e.g., z^3-1=0). Grid of pass/fail results renders ASCII art flag. Key: the binary is a classifier, not a checker — reverse the math and visualize. See [patterns-ctf.md](patterns-ctf.md#mathematical-convergence-bitmap-ehax-2026).

## RISC-V Binary Analysis

Statically linked, stripped RISC-V ELF. Use Capstone with `CS_MODE_RISCVC | CS_MODE_RISCV64` for mixed compressed instructions. Emulate with `qemu-riscv64`. Watch for fake flags and XOR decryption with incremental keys. See [tools.md](tools.md#risc-v-binary-analysis-ehax-2026).

## Sprague-Grundy Game Theory Binary

Game binary plays bounded Nim with PRNG for losing-position moves. Identify game framework (Grundy values = pile % (k+1), XOR determines position), track PRNG state evolution through user input feedback. See [patterns-ctf.md](patterns-ctf.md#sprague-grundy-game-theory-binary-dicectf-2026).

## Kernel Module Maze Solving

Rust kernel module implements maze via device ioctls. Enumerate commands dynamically, build DFS solver with decoy avoidance, deploy as minimal static binary (raw syscalls, no libc). See [patterns-ctf.md](patterns-ctf.md#kernel-module-maze-solving-dicectf-2026).

## Multi-Threaded VM with Channels

Custom VM with 16+ threads communicating via futex channels. Trace data flow across thread boundaries, extract constants from GDB, watch for inverted validity logic, solve via BFS state space search. See [patterns-ctf.md](patterns-ctf.md#multi-threaded-vm-with-channel-synchronization-dicectf-2026).

## CVP/LLL Lattice for Constrained Integer Validation (HTB ShadowLabyrinth)

Binary validates flag via matrix multiplication with 64-bit coefficients; solutions must be printable ASCII. Use LLL reduction + CVP in SageMath to find nearest lattice point in the constrained range. Two-phase pattern: Phase 1 recovers AES key, Phase 2 decrypts custom VM bytecode with another linear system (mod 2^32). See [patterns-ctf-2.md](patterns-ctf-2.md#cvplll-lattice-for-constrained-integer-validation-htb-shadowlabyrinth).

## Decision Tree Function Obfuscation (HTB WonderSMS)

~200+ auto-generated functions routing input through polynomial comparisons. Script extraction via Ghidra headless rather than reversing each function manually. Constraint propagation from known output format cascades through arithmetic constraints. See [patterns-ctf-2.md](patterns-ctf-2.md#decision-tree-function-obfuscation-htb-wondersms).

## Android JNI RegisterNatives Obfuscation (HTB WonderSMS)

`RegisterNatives` in `JNI_OnLoad` hides which C++ function handles each Java native method (no standard `Java_com_pkg_Class_method` symbol). Find the real handler by tracing `JNI_OnLoad` → `RegisterNatives` → `fnPtr`. Use x86_64 `.so` from APK for best Ghidra decompilation. See [languages.md](languages.md#android-jni-registernatives-obfuscation-htb-wondersms).

## Multi-Layer Self-Decrypting Binary

N-layer binary where each layer decrypts the next using user-provided key bytes + SHA-NI. Use oracle (correct key → valid code with expected pattern). JIT execution with fork-per-candidate COW isolation for speed. See [patterns-ctf-2.md](patterns-ctf-2.md#multi-layer-self-decrypting-binary-dicectf-2026).

## GLSL Shader VM with Self-Modifying Code

**Pattern:** WebGL2 fragment shader implements Turing-complete VM on a 256x256 RGBA texture (program memory + VRAM). Self-modifying code (STORE opcode) patches drawing instructions. GPU parallelism causes write conflicts — emulate sequentially in Python to recover full output. See [patterns-ctf-2.md](patterns-ctf-2.md#glsl-shader-vm-with-self-modifying-code-apoorvctf-2026).

## GF(2^8) Gaussian Elimination for Flag Recovery

**Pattern:** Binary performs Gaussian elimination over GF(2^8) with the AES polynomial (0x11b). Matrix + augmentation vector in `.rodata`; solution vector is the flag. Look for constant `0x1b` in disassembly. Addition is XOR, multiplication uses polynomial reduction. See [patterns-ctf-2.md](patterns-ctf-2.md#gf28-gaussian-elimination-for-flag-recovery-apoorvctf-2026).

## Z3 for Single-Line Python Boolean Circuit

**Pattern:** Single-line Python (2000+ semicolons) with walrus operator chains validates flag as big-endian integer via boolean circuit. Obfuscated XOR `(a | b) & ~(a & b)`. Split on semicolons, translate to Z3 symbolically, solve in under a second. See [patterns-ctf-2.md](patterns-ctf-2.md#z3-for-single-line-python-boolean-circuit-bearcatctf-2026).

## Sliding Window Popcount Differential Propagation

**Pattern:** Binary validates input via expected popcount for each position of a 16-bit sliding window. Popcount differences create a recurrence: `bit[i+16] = bit[i] + (data[i+1] - data[i])`. Brute-force ~4000-8000 valid initial 16-bit windows; each determines the entire bit sequence. See [patterns-ctf-2.md](patterns-ctf-2.md#sliding-window-popcount-differential-propagation-bearcatctf-2026).

## Ruby/Perl Polyglot Constraint Satisfaction

**Pattern:** Single file valid in both Ruby and Perl, each imposing different constraints on a key. Exploits `=begin`/`=end` (Ruby block comment) vs `=begin`/`=cut` (Perl POD) to run different code per interpreter. Intersect constraints from both languages to recover the unique key. See [languages.md](languages.md#rubyperl-polyglot-constraint-satisfaction-bearcatctf-2026).

## Verilog/Hardware RE

**Pattern:** Verilog HDL source for state machines with hidden conditions gated on shift register history. Analyze `always @(posedge clk)` blocks and `case` statements to find correct input sequences. See [languages.md](languages.md#veriloghardware-reverse-engineering-srdnlenctf-2026).

## Backdoored Shared Library Detection

Binary works in GDB but fails when run normally (suid)? Check `ldd` for non-standard libc paths, then `strings | diff` the suspicious vs. system library to find injected code/passwords. See [patterns-ctf.md](patterns-ctf.md#backdoored-shared-library-detection-via-string-diffing-hacklu-ctf-2012).

## Go Binary Reversing

Large static binary with `go.buildid`? Use GoReSym to recover function names (works even on stripped binaries). Go strings are `{ptr, len}` pairs — not null-terminated. Look for `main.main`, `runtime.gopanic`, channel ops (`runtime.chansend1`/`chanrecv1`). Use Ghidra golang-loader plugin for best results. See [languages-compiled.md](languages-compiled.md#go-binary-reversing).

## Rust Binary Reversing

Binary with `core::panicking` strings and `_ZN` mangled symbols? Use `rustfilt` for demangling. Panic messages contain source paths and line numbers — `strings binary | grep "panicked"` is the fastest approach. Option/Result enums use discriminant byte (0=None/Err, 1=Some/Ok). See [languages-compiled.md](languages-compiled.md#rust-binary-reversing).

## Frida Dynamic Instrumentation

Hook runtime functions without modifying binary. `frida -f ./binary -l hook.js` to spawn with instrumentation. Hook `strcmp`/`memcmp` to capture expected values, bypass anti-debug by replacing `ptrace` return value, scan memory for flag patterns, replace validation functions. See [tools-dynamic.md](tools-dynamic.md#frida-dynamic-instrumentation).

## angr Symbolic Execution

Automatic path exploration to find inputs satisfying constraints. Load binary with `angr.Project`, set find/avoid addresses, call `simgr.explore()`. Constrain input to printable ASCII and known prefix for faster solving. Hook expensive functions (crypto, I/O) to prevent path explosion. See [tools-dynamic.md](tools-dynamic.md#angr-symbolic-execution).

## Qiling Emulation

Cross-platform binary emulation with OS-level support (syscalls, filesystem). Emulate Linux/Windows/ARM/MIPS binaries on any host. No debugger artifacts — bypasses all anti-debug by default. Hook syscalls and addresses with Python API. See [tools-dynamic.md](tools-dynamic.md#qiling-framework-cross-platform-emulation).

## VMProtect / Themida Analysis

VMProtect virtualizes code into custom bytecode. Identify VM entry (pushad-like), find handler table (large indirect jump), trace handlers dynamically. For CTF, focus on tracing operations on input rather than full devirtualization. Themida: dump at OEP with ScyllaHide + Scylla. See [tools-advanced.md](tools-advanced.md#vmprotect-analysis).

## Binary Diffing

BinDiff and Diaphora compare two binaries to highlight changes. Essential when challenge provides patched/original versions. Export from IDA/Ghidra, diff to find vulnerability or hidden functionality. See [tools-advanced.md](tools-advanced.md#binary-diffing).

## Advanced GDB (pwndbg, rr)

pwndbg: `context`, `vmmap`, `search -s "flag{"`, `telescope $rsp`. GEF alternative. Reverse debugging with `rr record`/`rr replay` — step backward through execution. Python scripting for brute-force and automated tracing. See [tools-advanced.md](tools-advanced.md#advanced-gdb-techniques).

## macOS / iOS Reversing

Mach-O binaries: `otool -l` for load commands, `class-dump` for Objective-C headers. Swift: `swift demangle` for symbols. iOS apps: decrypt FairPlay DRM with frida-ios-dump, bypass jailbreak detection with Frida hooks. Re-sign patched binaries with `codesign -f -s -`. See [platforms.md](platforms.md#macos--ios-reversing).

## Embedded / IoT Firmware RE

`binwalk -Me firmware.bin` for recursive extraction. Hardware: UART/JTAG/SPI flash for firmware dumps. Filesystems: SquashFS (`unsquashfs`), JFFS2, UBI. Emulate with QEMU: `qemu-arm -L /usr/arm-linux-gnueabihf/ ./binary`. See [platforms.md](platforms.md#embedded--iot-firmware-re).

## Kernel Driver Reversing

Linux `.ko`: find ioctl handler via `file_operations` struct, trace `copy_from_user`/`copy_to_user`. Debug with QEMU+GDB (`-s -S`). eBPF: `bpftool prog dump xlated`. Windows `.sys`: find `DriverEntry` → `IoCreateDevice` → IRP handlers. See [platforms.md](platforms.md#kernel-driver-reversing).

## Game Engine Reversing

Unreal: extract .pak with UnrealPakTool, reverse Blueprint bytecode with FModel. Unity Mono: decompile Assembly-CSharp.dll with dnSpy. Anti-cheat (EAC, BattlEye, VAC): identify system, bypass specific check. Lua games: `luadec`/`unluac` for bytecode. See [platforms.md](platforms.md#game-engine-reversing).

## Swift / Kotlin Binary Reversing

Swift: `swift demangle` symbols, protocol witness tables for dispatch, `__swift5_*` sections. Kotlin/JVM: coroutines compile to state machines in `invokeSuspend`, `jadx` with Kotlin mode for best decompilation. Kotlin/Native: LLVM backend, looks like C++ in disassembly. See [languages-compiled.md](languages-compiled.md#swift-binary-reversing).



---

<!-- Source: tools-advanced-2.md -->

# CTF Reverse — Advanced Tooling (2025-2026 era)

Heavy-weight tooling patterns from 2025-2026 elite CTFs. Base tooling (angr, Ghidra, IDA scripting, Unicorn standalone) lives in [tools-advanced.md](tools-advanced.md); dynamic-only tools (Frida, Qiling) in [tools-dynamic.md](tools-dynamic.md).

## Table of Contents
- [Massive PE (GB-scale) with Per-Layer VirtualProtect-Gated Self-Decryption — Unicorn + angr Hybrid (source: DEFCON 2025 Quals nfuncs1)](#massive-pe-gb-scale-with-per-layer-virtualprotect-gated-self-decryption--unicorn--angr-hybrid-source-defcon-2025-quals-nfuncs1)

---

## Massive PE (GB-scale) with Per-Layer VirtualProtect-Gated Self-Decryption — Unicorn + angr Hybrid (source: DEFCON 2025 Quals nfuncs1)

**Trigger:**
- A Windows PE binary ≥ 500 MB (often 3 GB+) where loading in IDA or Ghidra exhausts RAM.
- Each "layer" calls `VirtualProtect(addr, size, PAGE_EXECUTE_READWRITE, &old)` followed by an inline decryption loop (`xor`/`add`/`rol` with a per-layer key derived from earlier inputs), then `call rax`/`jmp rax` into the freshly-decrypted chunk.
- Many `read()` calls that validate each input byte against a lookup table or equality compare, then conditionally fall through to the next layer.

**Signals to grep:**
```
strings -a bin.exe | grep -iE 'VirtualProtect|NtProtectVirtualMemory'
objdump -d --start-address=... | grep -c '\s(xor|ror|rol)\s'   # many small crypto loops
pefile: count of sections with SizeOfRawData > 10 MB
```

**Why you cannot just angr it:** a symbolic engine running through `VirtualProtect` and self-modified code explodes on path count; a pure Unicorn emulator has no SMT to solve the per-byte input constraints.

**Hybrid approach (works in ≤ 1 h on 16 cores):**

1. **Unicorn-only warm-up** — emulate from entry with a fake `ReadFile`/`read` hook that feeds placeholder bytes. Record every `VirtualProtect` call (addr, size, prot) and every `call`/`jmp rax` that follows. This builds a **layer graph** without interpreting crypto semantically — each layer is a (decrypt-fn, entry-addr, key-source) tuple.

2. **Per-layer angr solve** — for each layer from Unicorn's graph:
   - Load only the decrypted bytes Unicorn observed (dump the code page right after the `VirtualProtect` with `RWX`).
   - Build a `CFGEmulated` rooted at `entry-addr`, stopping at the next `VirtualProtect` call (use a `state.inspect` breakpoint on `VirtualProtect` address).
   - Add constraints from input-byte lookup table checks (angr's `SimState.solver.add(buf[i] == const)` after matching the comparator pattern).
   - `state.solver.eval(input, cast_to=bytes)` → canonical input for that layer.

3. **Hook orchestration in Unicorn** — once layers 1..k are solved:
   ```python
   def hook_read(uc, buf_addr, count, user_data):
       uc.mem_write(buf_addr, LAYER_INPUTS[user_data["layer_idx"]])
       user_data["layer_idx"] += 1
       return count
   def hook_puts(uc, *_):          # skip diagnostic prints, they slow us 5×
       uc.reg_write(UC_X86_REG_RIP, uc.reg_read(UC_X86_REG_RIP) + uc.mem_read(RIP, 5))
   ```
   Let the binary cascade through all decrypted layers end-to-end; the final layer prints the flag.

4. **Performance fences:**
   - Do **NOT** disassemble inside hooks (Capstone/iced_x86 inside a per-instruction hook costs ~40× — measured on DEFCON 2025 nfuncs1 at 3 h without this fix).
   - Use `UC_HOOK_BLOCK`, not `UC_HOOK_CODE`, unless you need single-step.
   - Dump memory pages to disk between layers; don't hold 3 GB in Python.

**Template:**
```python
import unicorn, angr
uc = unicorn.Uc(UC_ARCH_X86, UC_MODE_64)
uc.mem_map(BASE, SIZE)
uc.mem_write(BASE, open(BIN, "rb").read())
LAYERS = []

def vp_hook(uc, addr, sz, user_data):
    # capture (addr, sz, code_bytes) right before exec
    LAYERS.append((addr, sz, uc.mem_read(addr, sz)))
uc.hook_add(UC_HOOK_CODE, vp_hook, begin=VP_ADDR, end=VP_ADDR+1)
uc.emu_start(ENTRY, STOP, timeout=3*60*10**6)

for addr, sz, code in LAYERS:
    proj = angr.Project.angr.load_shellcode(code, "amd64", load_address=addr)
    st = proj.factory.blank_state(addr=addr)
    buf = st.solver.BVS("buf", 8*INPUT_SZ)
    st.memory.store(INPUT_BUF, buf)
    sm = proj.factory.simulation_manager(st)
    sm.explore(find=SUCCESS_ADDR, avoid=FAIL_ADDR)
    LAYER_INPUT = sm.found[0].solver.eval(buf, cast_to=bytes)
```

**Generalizes to:** any multi-stage unpacker (VMProtect 3+, Themida, custom game protections) where each stage exposes a small `read()` oracle that gates progression. The key insight is *Unicorn to navigate, angr to solve per-stage constraints, never both at once.*



---

<!-- Source: tools-advanced.md -->

# CTF Reverse - Advanced Tools & Deobfuscation

Advanced tooling for commercial packers/protectors, binary diffing, deobfuscation frameworks, emulation, and symbolic execution beyond angr.

## Table of Contents
- [VMProtect Analysis](#vmprotect-analysis)
  - [Recognition](#recognition)
  - [Approach](#approach)
  - [Tools](#tools)
  - [CTF Strategy](#ctf-strategy)
- [Themida / WinLicense Analysis](#themida--winlicense-analysis)
  - [Recognition](#recognition-1)
  - [Approach for CTF](#approach-for-ctf)
- [Binary Diffing](#binary-diffing)
  - [BinDiff](#bindiff)
  - [Diaphora](#diaphora)
- [Deobfuscation Frameworks](#deobfuscation-frameworks)
  - [D-810 (IDA)](#d-810-ida)
  - [GOOMBA (Ghidra)](#goomba-ghidra)
  - [Miasm](#miasm)
- [Qiling Framework (Emulation)](#qiling-framework-emulation)
- [Triton (Dynamic Symbolic Execution)](#triton-dynamic-symbolic-execution)
- [Manticore (Symbolic Execution)](#manticore-symbolic-execution)
- [Rizin / Cutter](#rizin--cutter)
- [RetDec (Retargetable Decompiler)](#retdec-retargetable-decompiler)
- [Advanced GDB Techniques](#advanced-gdb-techniques)
  - [Python Scripting](#python-scripting)
  - [Brute-Force with GDB Script](#brute-force-with-gdb-script)
  - [Conditional Breakpoints](#conditional-breakpoints)
  - [Watchpoints](#watchpoints)
  - [Reverse Debugging (rr)](#reverse-debugging-rr)
  - [GDB Dashboard / GEF / pwndbg](#gdb-dashboard--gef--pwndbg)
- [Advanced Ghidra Scripting](#advanced-ghidra-scripting)
- [Patching Strategies](#patching-strategies)
  - [Binary Ninja Patching (Python API)](#binary-ninja-patching-python-api)
  - [LIEF (Library for Instrumenting Executable Formats)](#lief-library-for-instrumenting-executable-formats)

---

## VMProtect Analysis

VMProtect virtualizes x86/x64 code into custom bytecode interpreted by a generated VM. One of the most challenging protectors in CTF.

### Recognition

```bash
# VMProtect signatures
strings binary | grep -i "vmp\|vmprotect"
# PE sections: .vmp0, .vmp1 (VMProtect adds its own sections)
readelf -S binary | grep ".vmp"
# Large binary with entropy > 7.5 in certain sections
```

**Key indicators:**
- `push` / `pop` heavy prologues (VM entry pushes all registers to stack)
- Large switch-case dispatcher (the VM handler loop)
- Anti-debug checks embedded in VM handlers
- Mutation engine: same opcode has different handlers per build

### Approach

```text
1. Identify VM entry points — look for pushad/pushaq-like sequences
2. Find the handler table — large indirect jump (jmp [reg + offset])
3. Trace handler execution — each handler ends with jump to next
4. Identify handlers:
   - vAdd, vSub, vMul, vXor, vNot (arithmetic)
   - vPush, vPop (stack operations)
   - vLoad, vStore (memory access)
   - vJmp, vJcc (control flow)
   - vRet (VM exit — restores real registers)
5. Build disassembler for VM bytecode
6. Simplify / deobfuscate the lifted IL
```

### Tools

- **VMPAttack** (IDA plugin): Automatically identifies VM handlers
- **NoVmp**: Devirtualization via VTIL (open-source)
- **VMProtect devirtualizer scripts**: Community IDA/Binary Ninja scripts
- **Approach for CTF:** Often easier to trace specific operations (crypto, comparisons) than fully devirtualize

### CTF Strategy

```python
# Trace VM execution dynamically to extract operations on flag
# Hook VM handler dispatch to log opcode + operands

import frida

script = """
var vm_dispatch = ptr('0x...');  // Address of handler table jump
Interceptor.attach(vm_dispatch, {
    onEnter(args) {
        // Log handler index and stack state
        var handler_idx = this.context.rax;  // or whichever register
        console.log('Handler:', handler_idx, 'RSP:', this.context.rsp);
    }
});
"""
```

**Key insight:** Full devirtualization is rarely needed for CTF. Focus on tracing what operations are performed on your input. Hook comparison/crypto functions called from within the VM.

---

## Themida / WinLicense Analysis

Similar to VMProtect but with additional anti-debug layers.

### Recognition
- Sections: `.themida`, `.winlice`
- Extremely heavy anti-debug (kernel-level checks, driver installation)
- Code mutation + virtualization + packing combined

### Approach for CTF
1. **Dump unpacked code:** Let it run, dump process memory after unpacking
2. **Bypass anti-debug:** ScyllaHide in x64dbg with Themida-specific preset
3. **Fix imports:** Use Scylla plugin for IAT reconstruction
4. **Focus on dumped code:** Once unpacked, analyze as normal binary

```bash
# x64dbg workflow for Themida:
1. Load binary
2. Enable ScyllaHide → Profile: Themida
3. Run to OEP (Original Entry Point) — may need several attempts
4. Dump with Scylla: OEP → IAT Autosearch → Get Imports → Dump
5. Fix dump: Scylla → Fix Dump
6. Analyze fixed dump in Ghidra/IDA
```

---

## Binary Diffing

Critical for patch analysis, 1-day exploit development, and CTF challenges that provide two versions of a binary.

### BinDiff

```bash
# Export from IDA/Ghidra first, then diff
# IDA: File → BinExport → Export as BinExport2
# Ghidra: Use BinExport plugin

# Command line diffing
bindiff primary.BinExport secondary.BinExport
# Opens in BinDiff GUI — shows matched/unmatched functions
```

**Key metrics:**
- Similarity score (0.0-1.0) per function pair
- Changed instructions highlighted
- Unmatched functions = new/removed code

### Diaphora

Free, open-source alternative to BinDiff, runs as IDA plugin.

```bash
# In IDA:
# File → Script file → diaphora.py
# Export first binary, then open second and diff

# Ghidra version: diaphora_ghidra.py
```

**Useful for CTF:** When challenge provides "patched" and "original" binaries, diff reveals the vulnerability or hidden functionality.

---

## Deobfuscation Frameworks

### D-810 (IDA)

Pattern-based deobfuscation plugin for IDA Pro. Excellent for OLLVM-obfuscated binaries.

```text
Capabilities:
- MBA simplification: (a ^ b) + 2*(a & b) → a + b
- Dead code elimination
- Opaque predicate removal
- Constant folding
- Control flow unflattening (partial)

Installation: Copy to IDA plugins directory
Usage: Edit → Plugins → D-810 → Select rules → Apply
```

### GOOMBA (Ghidra)

```text
GOOMBA (Ghidra-based Obfuscated Object Matching and Bytes Analysis):
- Integrates with Ghidra's P-Code
- Simplifies MBA expressions
- Pattern matching for known obfuscation

Installation: Copy .jar to Ghidra extensions
Usage: Code Browser → Analysis → GOOMBA
```

### Miasm

Powerful reverse engineering framework with symbolic execution and IR lifting.

```python
from miasm.analysis.binary import Container
from miasm.analysis.machine import Machine
from miasm.expression.expression import *

# Load binary and lift to Miasm IR
cont = Container.from_stream(open("binary", "rb"))
machine = Machine(cont.arch)
mdis = machine.dis_engine(cont.bin_stream, loc_db=cont.loc_db)

# Disassemble function
asmcfg = mdis.dis_multiblock(entry_addr)

# Lift to IR
lifter = machine.lifter_model_call(loc_db=cont.loc_db)
ircfg = lifter.new_ircfg_from_asmcfg(asmcfg)

# Symbolic execution
from miasm.ir.symbexec import SymbolicExecutionEngine
sb = SymbolicExecutionEngine(lifter)
# Execute symbolically, then simplify expressions
```

**Use case:** Deobfuscate expression trees, simplify complex arithmetic, trace data flow through obfuscated code.

---

## Qiling Framework (Emulation)

Cross-platform emulation framework built on Unicorn, with OS-level support (syscalls, filesystem, registry).

```python
from qiling import Qiling
from qiling.const import QL_VERBOSE

# Emulate Linux ELF
ql = Qiling(["./binary"], "rootfs/x8664_linux",
            verbose=QL_VERBOSE.DEBUG)

# Hook specific address
@ql.hook_address
def hook_check(ql, address, size):
    if address == 0x401234:
        ql.arch.regs.rax = 0  # Bypass check
        ql.log.info("Anti-debug bypassed")

# Hook syscall
@ql.hook_syscall(name="ptrace")
def hook_ptrace(ql, request, pid, addr, data):
    return 0  # Always succeed

# Hook API (Windows)
@ql.set_api("IsDebuggerPresent", target=ql.os.user_defined_api)
def hook_isdebug(ql, address, params):
    return 0

ql.run()
```

**Advantages over Unicorn:**
- OS emulation (file I/O, network, registry)
- Multi-platform (Linux, Windows, macOS, Android, UEFI)
- Built-in debugger interface
- Rootfs for library loading

**CTF use cases:**
- Emulate binaries for foreign architectures (ARM, MIPS, RISC-V)
- Bypass all anti-debug at once (no debugger artifacts)
- Fuzz embedded/IoT firmware without hardware
- Trace execution without code modification

---

## Triton (Dynamic Symbolic Execution)

Pin-based dynamic binary analysis framework with symbolic execution, taint analysis, and AST simplification.

```python
from triton import *

ctx = TritonContext(ARCH.X86_64)

# Load binary sections
with open("binary", "rb") as f:
    binary = f.read()
ctx.setConcreteMemoryAreaValue(0x400000, binary)

# Symbolize input
for i in range(32):
    ctx.symbolizeMemory(MemoryAccess(INPUT_ADDR + i, CPUSIZE.BYTE), f"input_{i}")

# Emulate instructions
pc = ENTRY_POINT
while pc:
    inst = Instruction(pc, ctx.getConcreteMemoryAreaValue(pc, 16))
    ctx.processing(inst)

    # At comparison point, extract path constraint
    if pc == CMP_ADDR:
        ast = ctx.getPathConstraintsAst()
        model = ctx.getModel(ast)
        for k, v in sorted(model.items()):
            print(f"input[{k}] = {chr(v.getValue())}", end="")
        break

    pc = ctx.getConcreteRegisterValue(ctx.registers.rip)
```

**Triton vs angr:**
| Feature | Triton | angr |
|---|---|---|
| Execution | Concrete + symbolic (DSE) | Fully symbolic |
| Speed | Faster (concrete-driven) | Slower (explores all paths) |
| Path explosion | Less prone (follows one path) | Major issue |
| API | C++ / Python | Python |
| Best for | Single-path deobfuscation, taint tracking | Multi-path exploration |

**Key use:** Triton excels at deobfuscation — run the program concretely, but track symbolic state, then simplify the collected constraints.

---

## Manticore (Symbolic Execution)

Trail of Bits' symbolic execution tool. Similar to angr but with native EVM (Ethereum) support.

```python
from manticore.native import Manticore

m = Manticore("./binary")

# Hook success/failure
@m.hook(0x401234)
def success(state):
    buf = state.solve_one_n_batched(state.input_symbols, 32)
    print("Flag:", bytes(buf))
    m.kill()

@m.hook(0x401256)
def fail(state):
    state.abandon()

m.run()
```

**Best for:** EVM/smart contract analysis, simpler Linux binaries. angr is generally more mature for complex RE tasks.

---

## Rizin / Cutter

Rizin is the maintained fork of radare2. Cutter is its Qt-based GUI.

```bash
# Rizin CLI (r2-compatible commands)
rizin -d ./binary
> aaa                    # Analyze all
> afl                    # List functions
> pdf @ main             # Print disassembly
> VV                     # Visual graph mode

# Cutter GUI
cutter binary           # Open in GUI with decompiler
```

**Cutter advantages:**
- Built-in Ghidra decompiler (via r2ghidra plugin)
- Graph view, hex editor, debug panel in one GUI
- Integrated Python/JavaScript scripting console
- Free and open source

---

## RetDec (Retargetable Decompiler)

LLVM-based decompiler supporting many architectures. Free and open-source.

```bash
# Install
pip install retdec-decompiler
# Or use web: https://retdec.com/decompilation/

# CLI
retdec-decompiler binary
# Outputs: binary.c (decompiled C), binary.dsm (disassembly)

# Specific function
retdec-decompiler --select-ranges 0x401000-0x401100 binary
```

**Strengths:** Multi-arch support (x86, ARM, MIPS, PowerPC, PIC32), free, produces compilable C. Good for architectures not well-supported by Ghidra.

---

## Advanced GDB Techniques

### Python Scripting

```python
# ~/.gdbinit or source from GDB
import gdb

class TraceCompare(gdb.Breakpoint):
    """Log all comparison operations."""
    def __init__(self, addr):
        super().__init__(f"*{addr}", gdb.BP_BREAKPOINT)

    def stop(self):
        frame = gdb.selected_frame()
        rdi = int(frame.read_register("rdi"))
        rsi = int(frame.read_register("rsi"))
        rdx = int(frame.read_register("rdx"))
        # Read compared buffers
        inferior = gdb.selected_inferior()
        buf1 = inferior.read_memory(rdi, rdx).tobytes()
        buf2 = inferior.read_memory(rsi, rdx).tobytes()
        print(f"memcmp({buf1!r}, {buf2!r}, {rdx})")
        return False  # Don't stop, just log

# Usage in GDB:
# (gdb) source trace_cmp.py
# (gdb) python TraceCompare(0x401234)
```

### Brute-Force with GDB Script

```python
# Byte-by-byte brute force via GDB Python API
import gdb, string

def bruteforce_flag(check_addr, success_addr, fail_addr, flag_len):
    flag = []
    for pos in range(flag_len):
        for ch in string.printable:
            candidate = ''.join(flag) + ch + 'A' * (flag_len - pos - 1)
            gdb.execute('start', to_string=True)
            gdb.execute(f'b *{check_addr}', to_string=True)
            # Write candidate to stdin pipe
            # ... (setup input)
            gdb.execute('continue', to_string=True)
            rip = int(gdb.parse_and_eval('$rip'))
            if rip == success_addr:
                flag.append(ch)
                break
        gdb.execute('delete breakpoints', to_string=True)
    return ''.join(flag)
```

### Conditional Breakpoints

```bash
# Break only when register has specific value
(gdb) b *0x401234 if $rax == 0x41
(gdb) b *0x401234 if *(char*)$rdi == 'f'

# Break on Nth hit
(gdb) b *0x401234
(gdb) ignore 1 99    # Skip first 99 hits, break on 100th

# Log without stopping
(gdb) b *0x401234
(gdb) commands
> silent
> printf "rax=%lx rdi=%lx\n", $rax, $rdi
> continue
> end
```

### Watchpoints

```bash
# Hardware watchpoint — break when memory changes
(gdb) watch *(int*)0x601050        # Break on write to address
(gdb) rwatch *(int*)0x601050       # Break on read
(gdb) awatch *(int*)0x601050       # Break on read or write

# Watch a variable by name (needs debug symbols)
(gdb) watch flag_buffer[0]

# Conditional watchpoint
(gdb) watch *(int*)0x601050 if *(int*)0x601050 == 0x42
```

### Reverse Debugging (rr)

```bash
# Record execution
rr record ./binary
# Replay with reverse execution support
rr replay

# In rr replay (GDB commands plus):
(gdb) reverse-continue     # Run backward to previous breakpoint
(gdb) reverse-stepi        # Step backward one instruction
(gdb) reverse-next         # Reverse next
(gdb) when                 # Show current event number

# Set checkpoint and return to it
(gdb) checkpoint
(gdb) restart 1           # Return to checkpoint 1
```

**Key use:** When you step past the critical moment, reverse back instead of restarting. Invaluable for anti-debug that corrupts state.

### GDB Dashboard / GEF / pwndbg

```bash
# pwndbg (most popular for CTF)
# https://github.com/pwndbg/pwndbg
git clone https://github.com/pwndbg/pwndbg && cd pwndbg && ./setup.sh

# Key pwndbg commands:
pwndbg> context           # Show registers, stack, code, backtrace
pwndbg> vmmap             # Memory map (like /proc/self/maps)
pwndbg> search -s "flag{" # Search memory for string
pwndbg> telescope $rsp 20 # Smart stack dump
pwndbg> cyclic 200        # Generate De Bruijn pattern
pwndbg> hexdump $rdi 64   # Pretty hex dump
pwndbg> got               # Show GOT entries
pwndbg> plt               # Show PLT entries

# GEF (alternative)
# https://github.com/hugsy/gef
bash -c "$(curl -fsSL https://gef.blah.cat/sh)"

# Key GEF commands:
gef> xinfo $rdi           # Detailed info about address
gef> checksec             # Binary security features
gef> heap chunks          # Heap chunk listing
gef> pattern create 100   # De Bruijn pattern
```

---

## Advanced Ghidra Scripting

```python
# Ghidra Python (Jython) — run via Script Manager or headless

# Batch rename functions matching a pattern
from ghidra.program.model.symbol import SourceType
fm = currentProgram.getFunctionManager()
for func in fm.getFunctions(True):
    if func.getName().startswith("FUN_"):
        # Check if function contains specific instruction pattern
        body = func.getBody()
        inst_iter = currentProgram.getListing().getInstructions(body, True)
        for inst in inst_iter:
            if inst.getMnemonicString() == "CPUID":
                func.setName("anti_vm_check_" + hex(func.getEntryPoint().getOffset()),
                            SourceType.USER_DEFINED)
                break

# Extract all XOR constants from a function
def extract_xor_constants(func):
    """Find all XOR operations and their immediate operands."""
    constants = []
    body = func.getBody()
    inst_iter = currentProgram.getListing().getInstructions(body, True)
    for inst in inst_iter:
        if inst.getMnemonicString() == "XOR":
            for i in range(inst.getNumOperands()):
                op = inst.getOpObjects(i)
                if op and hasattr(op[0], 'getValue'):
                    constants.append(int(op[0].getValue()))
    return constants

# Bulk decompile and search for pattern
from ghidra.app.decompiler import DecompInterface
decomp = DecompInterface()
decomp.openProgram(currentProgram)

for func in fm.getFunctions(True):
    result = decomp.decompileFunction(func, 30, monitor)
    if result.depiledFunction():
        code = result.getDecompiledFunction().getC()
        if "strcmp" in code or "memcmp" in code:
            print(f"Comparison in {func.getName()} at {func.getEntryPoint()}")
```

---

## Patching Strategies

### Binary Ninja Patching (Python API)

```python
import binaryninja as bn

bv = bn.open_view("binary")

# NOP out instruction
bv.write(0x401234, b"\x90" * 5)  # 5-byte NOP

# Patch conditional jump (JNZ → JZ)
bv.write(0x401234, b"\x74")  # 0x75 (JNZ) → 0x74 (JZ)

# Insert always-true (mov eax, 1; ret)
bv.write(0x401234, b"\xb8\x01\x00\x00\x00\xc3")

bv.save("patched")
```

### LIEF (Library for Instrumenting Executable Formats)

```python
import lief

# Parse and modify ELF/PE/Mach-O
binary = lief.parse("binary")

# Add a new section
section = lief.ELF.Section(".patch")
section.content = list(b"\xcc" * 0x100)
section.type = lief.ELF.SECTION_TYPES.PROGBITS
section.flags = lief.ELF.SECTION_FLAGS.EXECINSTR | lief.ELF.SECTION_FLAGS.ALLOC
binary.add(section)

# Modify entry point
binary.header.entrypoint = 0x401000

# Hook imported function
binary.patch_pltgot("strcmp", 0x401000)

binary.write("patched")
```

**LIEF advantages:** Cross-format (ELF, PE, Mach-O), Python API, can add sections/segments, modify headers, patch imports.

---

## TTF GSUB Ligature Steganography (source: TFC CTF 2025 font-leagues)

**Trigger:** challenge ships a TTF/OTF; typing specific pairs in an editor renders a different glyph; correct flag collapses to `O` (or another marker glyph).
**Signals:** abnormally dense GSUB table in `ttx` output; glyph names like `hex_a`, `hex_b`, `hex_c`; ligature chains > 10 steps.
**Mechanic:** dump GSUB via `ttx -t GSUB file.ttf`. Ligature subtables define (glyph-A, glyph-B) → glyph-X replacements. Reverse the DAG: leaves you need to reach the marker glyph → input-byte pairs. Map `one/zero` glyph names back to bits or `ascii_XX` → characters. Automation:
```python
from fontTools.ttLib import TTFont
f = TTFont("x.ttf")
gsub = f["GSUB"].table
# iterate substitutions, build networkx DiGraph, reverse BFS from marker glyph
```

## AVX2 Lane-Wise Z3 Lifting (source: pwn.college AoP 2025 day 12)

**Trigger:** RE target uses `vpaddb` / `vpsubb` / `vpblendvb` / `vpshufb` in a tight loop operating on the input.
**Signals:** `ymm*` registers, vp* opcodes with imm8 shuffle masks, loop bound = input length.
**Mechanic:** lift each vector op into 32 (or 16) parallel BitVec8 operations over Z3. Treat each vp* as lane-parallel; `vpshufb ymm0, ymm1, ymm2` → per-lane `BitVec(ymm1[ymm2[i] & 0xf])`. Solver inverts the transformation in seconds. Don't try to re-express as scalar — stay in lanes.
Template:
```python
from z3 import *
inp = [BitVec(f"b{i}", 8) for i in range(32)]
# model each vp* directly on inp list
s = Solver(); s.add(final == expected); s.check()
```



---

<!-- Source: tools-dynamic.md -->

# CTF Reverse - Dynamic Analysis Tools

## Table of Contents
- [Frida (Dynamic Instrumentation)](#frida-dynamic-instrumentation)
  - [Installation](#installation)
  - [Basic Function Hooking](#basic-function-hooking)
  - [Anti-Debug Bypass](#anti-debug-bypass)
  - [Memory Scanning and Patching](#memory-scanning-and-patching)
  - [Function Replacement](#function-replacement)
  - [Tracing and Stalker](#tracing-and-stalker)
  - [r2frida (Radare2 + Frida Integration)](#r2frida-radare2--frida-integration)
  - [Frida for Android/iOS](#frida-for-androidios)
- [angr (Symbolic Execution)](#angr-symbolic-execution)
  - [Installation](#installation-1)
  - [Basic Path Exploration](#basic-path-exploration)
  - [Symbolic Input with Constraints](#symbolic-input-with-constraints)
  - [Hook Functions to Simplify Analysis](#hook-functions-to-simplify-analysis)
  - [Exploring from Specific Address](#exploring-from-specific-address)
  - [Common Patterns and Tips](#common-patterns-and-tips)
  - [Dealing with Path Explosion](#dealing-with-path-explosion)
  - [angr CFG Recovery](#angr-cfg-recovery)
- [lldb (LLVM Debugger)](#lldb-llvm-debugger)
  - [Basic Commands](#basic-commands)
  - [Scripting (Python)](#scripting-python)
- [x64dbg (Windows Debugger)](#x64dbg-windows-debugger)
  - [Key Features](#key-features)
  - [Scripting](#scripting)
  - [Common CTF Workflow](#common-ctf-workflow)
- [Qiling Framework (Cross-Platform Emulation)](#qiling-framework-cross-platform-emulation)
  - [Installation](#installation-2)
  - [Basic Usage](#basic-usage)
  - [Anti-Debug Bypass via Emulation](#anti-debug-bypass-via-emulation)
  - [Input Fuzzing with Qiling](#input-fuzzing-with-qiling)
- [Triton (Dynamic Symbolic Execution)](#triton-dynamic-symbolic-execution)
- [Intel Pin Instruction-Counting Side Channel (Hackover CTF 2015)](#intel-pin-instruction-counting-side-channel-hackover-ctf-2015)

---

## Frida (Dynamic Instrumentation)

Frida injects JavaScript into running processes for real-time hooking, tracing, and modification. Essential for anti-debug bypass, runtime inspection, and mobile RE.

### Installation

```bash
pip install frida-tools frida
# Verify
frida --version
```

### Basic Function Hooking

```javascript
// hook.js — intercept a function and log arguments/return value
Interceptor.attach(Module.findExportByName(null, "strcmp"), {
    onEnter: function(args) {
        this.arg0 = Memory.readUtf8String(args[0]);
        this.arg1 = Memory.readUtf8String(args[1]);
        console.log(`strcmp("${this.arg0}", "${this.arg1}")`);
    },
    onLeave: function(retval) {
        console.log(`  → ${retval}`);
    }
});
```

```bash
# Attach to running process
frida -p $(pidof binary) -l hook.js

# Spawn and instrument from start
frida -f ./binary -l hook.js --no-pause

# One-liner: hook strcmp and dump comparisons
frida -f ./binary --no-pause -e '
Interceptor.attach(Module.findExportByName(null, "strcmp"), {
    onEnter(args) {
        console.log("strcmp:", Memory.readUtf8String(args[0]), Memory.readUtf8String(args[1]));
    }
});
'
```

### Anti-Debug Bypass

```javascript
// Bypass ptrace(PTRACE_TRACEME) — returns 0 (success) without calling
Interceptor.attach(Module.findExportByName(null, "ptrace"), {
    onEnter: function(args) {
        this.request = args[0].toInt32();
    },
    onLeave: function(retval) {
        if (this.request === 0) { // PTRACE_TRACEME
            retval.replace(ptr(0));
            console.log("[*] ptrace(TRACEME) bypassed");
        }
    }
});

// Bypass IsDebuggerPresent (Windows)
var isDbg = Module.findExportByName("kernel32.dll", "IsDebuggerPresent");
Interceptor.attach(isDbg, {
    onLeave: function(retval) {
        retval.replace(ptr(0));
    }
});

// Bypass timing checks — hook clock_gettime to return constant
Interceptor.attach(Module.findExportByName(null, "clock_gettime"), {
    onLeave: function(retval) {
        // Force constant timestamp to defeat timing checks
        var ts = this.context.rsi || this.context.x1; // x86 or ARM
        Memory.writeU64(ts, 0);        // tv_sec
        Memory.writeU64(ts.add(8), 0); // tv_nsec
    }
});
```

### Memory Scanning and Patching

```javascript
// Scan for flag pattern in memory
Process.enumerateRanges('r--').forEach(function(range) {
    Memory.scan(range.base, range.size, "66 6c 61 67 7b", { // "flag{"
        onMatch: function(address, size) {
            console.log("[FLAG] Found at:", address, Memory.readUtf8String(address, 64));
        },
        onComplete: function() {}
    });
});

// Patch instruction (NOP out a check)
var addr = Module.findBaseAddress("binary").add(0x1234);
Memory.patchCode(addr, 2, function(code) {
    var writer = new X86Writer(code, { pc: addr });
    writer.putNop();
    writer.putNop();
    writer.flush();
});
```

### Function Replacement

```javascript
// Replace a validation function to always return true
var checkFlag = Module.findExportByName(null, "check_flag");
Interceptor.replace(checkFlag, new NativeCallback(function(input) {
    console.log("[*] check_flag called with:", Memory.readUtf8String(input));
    return 1; // always valid
}, 'int', ['pointer']));
```

### Tracing and Stalker

```javascript
// Trace all calls in a function (Stalker — instruction-level tracing)
var targetAddr = Module.findExportByName(null, "main");
Stalker.follow(Process.getCurrentThreadId(), {
    transform: function(iterator) {
        var instruction;
        while ((instruction = iterator.next()) !== null) {
            if (instruction.mnemonic === "call") {
                iterator.putCallout(function(context) {
                    console.log("CALL at", context.pc, "→", ptr(context.pc).readPointer());
                });
            }
            iterator.keep();
        }
    }
});
```

### r2frida (Radare2 + Frida Integration)

```bash
# Attach radare2 to process via Frida
r2 frida://spawn/./binary

# r2frida commands
\ii                    # List imports
\il                    # List loaded modules
\dt strcmp             # Trace strcmp calls
\dc                    # Continue execution
\dm                    # List memory maps
```

### Frida for Android/iOS

```bash
# Android (requires rooted device or Frida server)
adb push frida-server /data/local/tmp/
adb shell "chmod 755 /data/local/tmp/frida-server && /data/local/tmp/frida-server &"

# Hook Android Java methods
frida -U -f com.example.app -l hook_android.js --no-pause
```

```javascript
// hook_android.js — hook Java method
Java.perform(function() {
    var MainActivity = Java.use("com.example.app.MainActivity");
    MainActivity.checkPassword.implementation = function(input) {
        console.log("[*] checkPassword called with:", input);
        var result = this.checkPassword(input);
        console.log("[*] Result:", result);
        return result;
    };
});
```

**Key insight:** Frida excels where static analysis fails — obfuscated code, packed binaries, and runtime-generated data. Hook comparison functions (`strcmp`, `memcmp`, custom validators) to extract expected values without reversing the algorithm. Use `Interceptor.attach` for observation, `Interceptor.replace` for modification.

**When to use:** Anti-debugging bypass, extracting runtime-computed keys, hooking crypto functions to dump plaintext, mobile app analysis, packed binary inspection.

---

## angr (Symbolic Execution)

angr automatically explores program paths to find inputs satisfying constraints. Solves many flag-checking binaries in minutes that take hours manually.

### Installation

```bash
pip install angr
```

### Basic Path Exploration

```python
import angr
import claripy

# Load binary
proj = angr.Project('./binary', auto_load_libs=False)

# Find address of "Correct!" print, avoid "Wrong!" print
# Get these from disassembly (objdump -d or Ghidra)
FIND_ADDR = 0x401234    # Address of success path
AVOID_ADDR = 0x401256   # Address of failure path

# Create simulation manager and explore
simgr = proj.factory.simgr()
simgr.explore(find=FIND_ADDR, avoid=AVOID_ADDR)

if simgr.found:
    found = simgr.found[0]
    # Get stdin that reaches the target
    print("Flag:", found.posix.dumps(0))  # fd 0 = stdin
```

### Symbolic Input with Constraints

```python
import angr
import claripy

proj = angr.Project('./binary', auto_load_libs=False)

# Create symbolic input (e.g., 32-byte flag)
flag_len = 32
flag_chars = [claripy.BVS(f'flag_{i}', 8) for i in range(flag_len)]
flag = claripy.Concat(*flag_chars + [claripy.BVV(b'\n')])

# Constrain to printable ASCII
state = proj.factory.entry_state(stdin=flag)
for c in flag_chars:
    state.solver.add(c >= 0x20)
    state.solver.add(c <= 0x7e)

# Constrain known prefix: "flag{"
state.solver.add(flag_chars[0] == ord('f'))
state.solver.add(flag_chars[1] == ord('l'))
state.solver.add(flag_chars[2] == ord('a'))
state.solver.add(flag_chars[3] == ord('g'))
state.solver.add(flag_chars[4] == ord('{'))
state.solver.add(flag_chars[flag_len-1] == ord('}'))

simgr = proj.factory.simgr(state)
simgr.explore(find=0x401234, avoid=0x401256)

if simgr.found:
    found = simgr.found[0]
    result = found.solver.eval(flag, cast_to=bytes)
    print("Flag:", result.decode())
```

### Hook Functions to Simplify Analysis

```python
import angr

proj = angr.Project('./binary', auto_load_libs=False)

# Hook printf to avoid path explosion in I/O
@proj.hook(0x401100, length=5)  # Address of call to printf
def skip_printf(state):
    pass  # Do nothing, just skip

# Hook sleep/anti-debug functions
@proj.hook(0x401050, length=5)  # Address of call to sleep
def skip_sleep(state):
    pass

# Replace a function with a summary
class AlwaysSucceed(angr.SimProcedure):
    def run(self):
        return 1

proj.hook_symbol('check_license', AlwaysSucceed())
```

### Exploring from Specific Address

```python
# Start from middle of function (skip initialization)
state = proj.factory.blank_state(addr=0x401200)

# Set up registers/memory manually
state.regs.rdi = 0x600000  # Pointer to input buffer
state.memory.store(0x600000, b"AAAA" + b"\x00" * 28)

simgr = proj.factory.simgr(state)
simgr.explore(find=0x401300, avoid=0x401350)
```

### Common Patterns and Tips

```python
# Pattern 1: argv-based input
state = proj.factory.entry_state(args=['./binary', flag_sym])

# Pattern 2: Multiple find/avoid addresses
simgr.explore(
    find=[0x401234, 0x401300],     # Any success path
    avoid=[0x401256, 0x401400]     # All failure paths
)

# Pattern 3: Find by output string (no address needed)
def is_successful(state):
    stdout = state.posix.dumps(1)  # fd 1 = stdout
    return b"Correct" in stdout

def should_avoid(state):
    stdout = state.posix.dumps(1)
    return b"Wrong" in stdout

simgr.explore(find=is_successful, avoid=should_avoid)

# Pattern 4: Timeout protection
simgr.explore(find=0x401234, avoid=0x401256, num_find=1)
# Or use exploration techniques:
simgr.use_technique(angr.exploration_techniques.DFS())  # Depth-first
simgr.use_technique(angr.exploration_techniques.LengthLimiter(max_length=500))
```

### Dealing with Path Explosion

```python
# Use DFS instead of BFS (default) for flag checkers
simgr.use_technique(angr.exploration_techniques.DFS())

# Limit symbolic memory operations
state.options.add(angr.options.ZERO_FILL_UNCONSTRAINED_MEMORY)
state.options.add(angr.options.ZERO_FILL_UNCONSTRAINED_REGISTERS)

# Hook expensive functions (crypto, hashing) to avoid explosion
import hashlib
class SHA256Hook(angr.SimProcedure):
    def run(self, data, length, output):
        # Concretize input and compute hash
        concrete_data = self.state.solver.eval(
            self.state.memory.load(data, self.state.solver.eval(length)),
            cast_to=bytes
        )
        h = hashlib.sha256(concrete_data).digest()
        self.state.memory.store(output, h)

proj.hook_symbol('SHA256', SHA256Hook())
```

### angr CFG Recovery

```python
# Control flow graph for understanding structure
cfg = proj.analyses.CFGFast()
print(f"Functions found: {len(cfg.functions)}")

# Find main
for addr, func in cfg.functions.items():
    if func.name == 'main':
        print(f"main at {addr:#x}")
        break

# Cross-references
node = cfg.model.get_any_node(0x401234)
print("Predecessors:", [hex(p.addr) for p in cfg.model.get_predecessors(node)])
```

**Key insight:** angr works best on flag-checker binaries with clear success/failure paths. For complex binaries, hook expensive functions (crypto, I/O) and use DFS exploration. Start with the simplest approach (just find/avoid addresses) before adding constraints. If angr is slow, constrain input to printable ASCII and add known prefix.

**When to use:** Flag validators with branching logic, maze/path-finding binaries, constraint-heavy checks, automated binary analysis. Less effective for: heavy crypto, floating-point math, complex heap operations.

---

## lldb (LLVM Debugger)

Primary debugger for macOS/iOS. Also works on Linux. Preferred for Swift/Objective-C and Apple platform binaries.

### Basic Commands

```bash
lldb ./binary
(lldb) run                          # Run program
(lldb) b main                       # Breakpoint on main
(lldb) b 0x401234                   # Breakpoint at address
(lldb) breakpoint set -r "check.*"  # Regex breakpoint
(lldb) c                            # Continue
(lldb) si                           # Step instruction
(lldb) ni                           # Next instruction
(lldb) register read                # Show all registers
(lldb) register write rax 0         # Modify register
(lldb) memory read 0x401000 -c 32   # Read 32 bytes
(lldb) x/s $rsi                     # Examine string (GDB-style)
(lldb) dis -n main                  # Disassemble function
(lldb) image list                   # Loaded modules + base addresses
```

### Scripting (Python)

```python
# lldb Python scripting
import lldb

def hook_strcmp(debugger, command, result, internal_dict):
    target = debugger.GetSelectedTarget()
    process = target.GetProcess()
    thread = process.GetSelectedThread()
    frame = thread.GetSelectedFrame()
    arg0 = frame.FindRegister("rdi").GetValueAsUnsigned()
    arg1 = frame.FindRegister("rsi").GetValueAsUnsigned()
    s0 = process.ReadCStringFromMemory(arg0, 256, lldb.SBError())
    s1 = process.ReadCStringFromMemory(arg1, 256, lldb.SBError())
    print(f'strcmp("{s0}", "{s1}")')

# Register in lldb: command script add -f script.hook_strcmp hook_strcmp
```

**Key insight:** Use lldb for macOS binaries (Mach-O), iOS apps, and when GDB isn't available. `image list` gives ASLR slide for PIE binaries. Scripting API is more structured than GDB's.

---

## x64dbg (Windows Debugger)

Open-source Windows debugger with modern UI. Alternative to OllyDbg/WinDbg for Windows RE challenges.

### Key Features

```bash
# Launch
x64dbg.exe binary.exe         # 64-bit
x32dbg.exe binary.exe         # 32-bit

# Essential shortcuts
F2      → Toggle breakpoint
F7      → Step into
F8      → Step over
F9      → Run
Ctrl+G  → Go to address
Ctrl+F  → Find pattern in memory
```

### Scripting

```bash
# x64dbg command line
bp 0x401234                    # Breakpoint
SetBPX 0x401234, 0, "log {s:utf8@[esp+4]}"  # Log string arg on hit
run                            # Continue
StepOver                       # Step over
```

### Common CTF Workflow

1. Set breakpoint on `GetWindowTextA`/`MessageBoxA` for GUI crackers
2. Trace back from success/failure message
3. Use **Scylla** plugin for IAT reconstruction on packed binaries
4. **Snowman** decompiler plugin for quick pseudo-C

**Key insight:** x64dbg has built-in pattern scanning, hardware breakpoints, and conditional logging. For Windows CTF binaries, it's often faster than IDA/Ghidra for dynamic analysis. Use the **xAnalyzer** plugin for automatic function argument annotation.

---

## Qiling Framework (Cross-Platform Emulation)

Qiling emulates binaries with OS-level support (syscalls, filesystem, registry). Built on Unicorn but adds the OS layer that Unicorn lacks.

### Installation

```bash
pip install qiling
# Download rootfs for target OS:
git clone https://github.com/qilingframework/rootfs
```

### Basic Usage

```python
from qiling import Qiling
from qiling.const import QL_VERBOSE

# Linux ELF emulation
ql = Qiling(["./binary", "arg1"], "rootfs/x8664_linux",
            verbose=QL_VERBOSE.DEFAULT)
ql.run()

# Windows PE emulation (no Windows needed!)
ql = Qiling(["rootfs/x86_windows/bin/binary.exe"], "rootfs/x86_windows")
ql.run()

# ARM/MIPS emulation (IoT firmware)
ql = Qiling(["rootfs/arm_linux/bin/binary"], "rootfs/arm_linux")
ql.run()
```

### Anti-Debug Bypass via Emulation

```python
from qiling import Qiling

ql = Qiling(["./binary"], "rootfs/x8664_linux")

# Hook ptrace syscall — return 0 (success)
def hook_ptrace(ql, ptrace_request, pid, addr, data):
    ql.log.info("ptrace bypassed")
    return 0

ql.os.set_syscall("ptrace", hook_ptrace)

# Hook specific address (e.g., anti-VM check)
def skip_check(ql):
    ql.arch.regs.rax = 0  # Force success
    ql.log.info(f"Skipped check at {ql.arch.regs.rip:#x}")

ql.hook_address(skip_check, 0x401234)

ql.run()
```

### Input Fuzzing with Qiling

```python
# Emulate binary with different inputs to find flag
import string
from qiling import Qiling

def test_input(candidate):
    ql = Qiling(["./binary"], "rootfs/x8664_linux",
                verbose=QL_VERBOSE.DISABLED, stdin=candidate.encode())
    ql.run()
    return ql.os.stdout.read()

for ch in string.printable:
    output = test_input("flag{" + ch)
    if b"Correct" in output:
        print(f"Found: {ch}")
```

**Advantages over GDB/Frida:**
- No debugger artifacts (bypasses all anti-debug by default)
- Cross-platform without hardware (ARM, MIPS, RISC-V on x86 host)
- Scriptable with Python (faster iteration than GDB)
- Snapshot/restore for brute-forcing

**When to use:** Foreign architecture binaries, IoT firmware, heavy anti-debug, automated testing of many inputs.

---

## Triton (Dynamic Symbolic Execution)

See [tools-advanced.md](tools-advanced.md#triton-dynamic-symbolic-execution) for full Triton reference. Quick usage:

```python
from triton import *

ctx = TritonContext(ARCH.X86_64)

# Symbolize input buffer
for i in range(32):
    ctx.symbolizeMemory(MemoryAccess(0x600000 + i, CPUSIZE.BYTE), f"flag_{i}")

# Process instructions and collect constraints
# At comparison point, solve for flag
model = ctx.getModel(ctx.getPathConstraintsAst())
flag = ''.join(chr(v.getValue()) for _, v in sorted(model.items()))
```

**Best for:** Single-path symbolic execution, deobfuscation, taint analysis. Faster than angr for linear code paths.

---

## Intel Pin Instruction-Counting Side Channel (Hackover CTF 2015)

**Pattern:** Brute-force input character-by-character against a binary using Intel Pin's `inscount0` tool. Each correct character causes deeper execution (more instructions) in the comparison logic.

```python
import string
from subprocess import Popen, PIPE

pin = './pin'
tool = './source/tools/ManualExamples/obj-ia32/inscount0.so'
binary = './target'

key = ''
while True:
    best_count, best_char = 0, ''
    for c in string.printable:
        cmd = [pin, '-injection', 'child', '-t', tool, '--', binary]
        p = Popen(cmd, stdout=PIPE, stdin=PIPE, stderr=PIPE)
        p.communicate((key + c + '\n').encode())
        with open('inscount.out') as f:
            count = int(f.read().split()[-1])
        if count > best_count:
            best_count, best_char = count, c
    key += best_char
    print(f"Found: {key}")
```

**Key insight:** Movfuscated binaries (compiled with `movfuscator`) expand every instruction into sequences of `mov` operations, making static analysis impractical. However, character-by-character comparison still creates measurable instruction count differences. Pin's `inscount0.so` counts total executed instructions — the correct character at each position causes ~1000+ more instructions (proceeding further in the comparison). Also works for obfuscated binaries with sequential input checks.



---

<!-- Source: tools.md -->

# CTF Reverse - Tools Reference

## Table of Contents
- [GDB](#gdb)
  - [Basic Commands](#basic-commands)
  - [PIE Binary Debugging](#pie-binary-debugging)
  - [One-liner Automation](#one-liner-automation)
  - [Memory Examination](#memory-examination)
- [Radare2](#radare2)
  - [Basic Session](#basic-session)
  - [r2pipe Automation](#r2pipe-automation)
- [Ghidra](#ghidra)
  - [Headless Analysis](#headless-analysis)
  - [Emulator for Decryption](#emulator-for-decryption)
  - [MCP Commands](#mcp-commands)
- [Unicorn Emulation](#unicorn-emulation)
  - [Basic Setup](#basic-setup)
  - [Mixed-Mode (64 to 32) Switch](#mixed-mode-64-to-32-switch)
  - [Register Tracing Hook](#register-tracing-hook)
  - [Track Register Changes](#track-register-changes)
- [Python Bytecode](#python-bytecode)
  - [Disassembly](#disassembly)
  - [Extract Constants](#extract-constants)
  - [Pyarmor Static Unpack (1shot)](#pyarmor-static-unpack-1shot)
- [WASM Analysis](#wasm-analysis)
  - [Decompile to C](#decompile-to-c)
  - [Common Patterns](#common-patterns)
- [Android APK](#android-apk)
  - [Extraction](#extraction)
  - [Key Locations](#key-locations)
  - [Search](#search)
  - [Flutter APK (Blutter)](#flutter-apk-blutter)
  - [HarmonyOS HAP/ABC (abc-decompiler)](#harmonyos-hapabc-abc-decompiler)
- [.NET Analysis](#net-analysis)
  - [Tools](#tools)
  - [Two-Stage XOR + AES-CBC Decode Pattern (Codegate 2013)](#two-stage-xor--aes-cbc-decode-pattern-codegate-2013)
  - [NativeAOT](#nativeaot)
- [Packed Binaries](#packed-binaries)
  - [UPX](#upx)
  - [Custom Packers](#custom-packers)
  - [PyInstaller](#pyinstaller)
- [LLVM IR](#llvm-ir)
  - [Convert to Assembly](#convert-to-assembly)
- [RISC-V Binary Analysis (EHAX 2026)](#risc-v-binary-analysis-ehax-2026)
- [Binary Ninja](#binary-ninja)
- [Decompiler Comparison with dogbolt.org](#decompiler-comparison-with-dogboltorg)
- [Useful Commands](#useful-commands)

For dynamic instrumentation tools (Frida, angr, lldb, x64dbg), see [tools-dynamic.md](tools-dynamic.md).

---

## GDB

### Basic Commands
```bash
gdb ./binary
run                      # Run program
start                    # Run to main
b *0x401234              # Breakpoint at address
b *main+0x100            # Relative breakpoint
c                        # Continue
si                       # Step instruction
ni                       # Next instruction (skip calls)
x/s $rsi                 # Examine string
x/20x $rsp               # Examine stack
info registers           # Show registers
set $eax=0               # Modify register
```

### PIE Binary Debugging
```bash
gdb ./binary
start                    # Forces PIE base resolution
b *main+0xca            # Relative to main
b *main+0x198
run
```

### One-liner Automation
```bash
gdb -ex 'start' -ex 'b *main+0x198' -ex 'run' ./binary
```

### Memory Examination
```bash
x/s $rsi                 # String at RSI
x/38c $rsi               # 38 characters
x/20x $rsp               # 20 hex words from stack
x/10i $rip               # 10 instructions from RIP
```

---

## Radare2

### Basic Session
```bash
r2 -d ./binary           # Open in debug mode
aaa                      # Analyze all
afl                      # List functions
pdf @ main               # Disassemble main
db 0x401234              # Set breakpoint
dc                       # Continue
ood                      # Restart debugging
dr                       # Show registers
dr eax=0                 # Modify register
```

### r2pipe Automation
```python
import r2pipe
r2 = r2pipe.open('./binary', flags=['-d'])
r2.cmd('aaa')
r2.cmd('db 0x401234')

for char in range(256):
    r2.cmd('ood')        # Restart
    r2.cmd(f'dr eax={char}')
    output = r2.cmd('dc')
    if 'correct' in output:
        print(f"Found: {chr(char)}")
```

---

## Ghidra

### Headless Analysis
```bash
analyzeHeadless /path/to/project tmp -import binary -postScript script.py
```

### Emulator for Decryption
```java
EmulatorHelper emu = new EmulatorHelper(currentProgram);
emu.writeRegister("RSP", 0x2fff0000);
emu.writeRegister("RBP", 0x2fff0000);

// Write encrypted data
emu.writeMemory(dataAddress, encryptedBytes);

// Set function arguments
emu.writeRegister("RDI", arg1);

// Run until return
emu.setBreakpoint(returnAddress);
emu.run(functionEntryAddress);

// Read result
byte[] decrypted = emu.readMemory(outputAddress, length);
```

### MCP Commands
- Recon: `list_functions`, `list_imports`, `list_strings`
- Analysis: `decompile_function`, `get_xrefs_to`
- Annotation: `rename_function`, `rename_variable`

---

## Unicorn Emulation

### Basic Setup
```python
from unicorn import *
from unicorn.x86_const import *

mu = Uc(UC_ARCH_X86, UC_MODE_64)

# Map code segment
mu.mem_map(0x400000, 0x10000)
mu.mem_write(0x400000, code_bytes)

# Map stack
mu.mem_map(0x7fff0000, 0x10000)
mu.reg_write(UC_X86_REG_RSP, 0x7fff0000 + 0xff00)

# Run
mu.emu_start(start_addr, end_addr)
```

### Mixed-Mode (64 to 32) Switch
```python
# When a 64-bit stub jumps into 32-bit code via retf/retfq:
# - retf pops 4-byte EIP + 2-byte CS (6 bytes)
# - retfq pops 8-byte RIP + 8-byte CS (16 bytes)

uc32 = Uc(UC_ARCH_X86, UC_MODE_32)
# Copy memory regions, then GPRs
reg_map = {
    UC_X86_REG_EAX: UC_X86_REG_RAX,
    UC_X86_REG_EBX: UC_X86_REG_RBX,
    UC_X86_REG_ECX: UC_X86_REG_RCX,
    UC_X86_REG_EDX: UC_X86_REG_RDX,
    UC_X86_REG_ESI: UC_X86_REG_RSI,
    UC_X86_REG_EDI: UC_X86_REG_RDI,
    UC_X86_REG_EBP: UC_X86_REG_RBP,
}
for e, r in reg_map.items():
    uc32.reg_write(e, mu.reg_read(r) & 0xffffffff)  # mu = 64-bit emulator from above
uc32.reg_write(UC_X86_REG_EFLAGS, mu.reg_read(UC_X86_REG_RFLAGS) & 0xffffffff)

# SSE-heavy blobs need XMM registers copied
for xr in [UC_X86_REG_XMM0, UC_X86_REG_XMM1, UC_X86_REG_XMM2, UC_X86_REG_XMM3,
           UC_X86_REG_XMM4, UC_X86_REG_XMM5, UC_X86_REG_XMM6, UC_X86_REG_XMM7]:
    uc32.reg_write(xr, mu.reg_read(xr))

# Run 32-bit, then copy regs/memory back to 64-bit
```

**Tip:** set `UC_IGNORE_REG_BREAK=1` to silence warnings on unimplemented regs.

### Register Tracing Hook
```python
def hook_code(uc, address, size, user_data):
    if address == TARGET_ADDR:
        rsi = uc.reg_read(UC_X86_REG_RSI)
        print(f"0x{address:x}: rsi=0x{rsi:016x}")

mu.hook_add(UC_HOOK_CODE, hook_code)
```

### Track Register Changes
```python
prev_rsi = [None]
def hook_rsi_changes(uc, address, size, user_data):
    rsi = uc.reg_read(UC_X86_REG_RSI)
    if rsi != prev_rsi[0]:
        print(f"0x{address:x}: RSI changed to 0x{rsi:016x}")
        prev_rsi[0] = rsi

mu.hook_add(UC_HOOK_CODE, hook_rsi_changes)
```

---

## Python Bytecode

### Disassembly
```python
import marshal, dis

with open('file.pyc', 'rb') as f:
    f.read(16)  # Skip header (varies by Python version)
    code = marshal.load(f)
    dis.dis(code)
```

### Extract Constants
```python
for ins in dis.get_instructions(code):
    if ins.opname == 'LOAD_CONST':
        print(ins.argval)
```

### Pyarmor Static Unpack (1shot)

Repository: `https://github.com/Lil-House/Pyarmor-Static-Unpack-1shot`

```bash
# Basic usage (recursive processing)
python /path/to/oneshot/shot.py /path/to/scripts

# Specify pyarmor runtime library explicitly
python /path/to/oneshot/shot.py /path/to/scripts -r /path/to/pyarmor_runtime.so

# Save outputs to another directory
python /path/to/oneshot/shot.py /path/to/scripts -o /path/to/output
```

Notes:
- `oneshot/pyarmor-1shot` must exist before running `shot.py`.
- Supported focus: Pyarmor 8.x-9.x (`PY` + six digits header style).
- Pyarmor 7 and earlier (`PYARMOR` header) are out of scope.
- Disassembly output is generally reliable; decompiled source is experimental.

---

## WASM Analysis

### Decompile to C
```bash
wasm2c checker.wasm -o checker.c
gcc -O3 checker.c wasm-rt-impl.c -o checker
```

### Common Patterns
- `w2c_memory` - Linear memory array
- `wasm_rt_trap(N)` - Runtime errors
- Function exports: `flagChecker`, `validate`

---

## Android APK

### Extraction
```bash
apktool d app.apk -o decoded/   # Best - decodes XML
jadx app.apk                     # Decompile to Java
unzip app.apk -d extracted/      # Simple extraction
```

### Key Locations
- `res/values/strings.xml` - String resources
- `AndroidManifest.xml` - App metadata
- `classes.dex` - Dalvik bytecode
- `assets/`, `res/raw/` - Resources

### Search
```bash
grep -r "flag\|CTF" decoded/
strings decoded/classes*.dex | grep -i flag
```

### Flutter APK (Blutter)

```bash
# Run Blutter on arm64 build
python3 blutter.py path/to/app/lib/arm64-v8a out_dir
```

### HarmonyOS HAP/ABC (abc-decompiler)

Repository: `https://github.com/ohos-decompiler/abc-decompiler`

```bash
# Extract .hap first to obtain .abc files
unzip app.hap -d hap_extracted/
```

Critical startup mode:
```bash
# Use CLI entrypoint (avoid java -jar GUI mode)
java -cp "./jadx-dev-all.jar" jadx.cli.JadxCLI [options] <input>
```

```bash
# Basic decompile
java -cp "./jadx-dev-all.jar" jadx.cli.JadxCLI -d "out" ".abc"

# Recommended for .abc
java -cp "./jadx-dev-all.jar" jadx.cli.JadxCLI -m simple --log-level ERROR -d "out_abc_simple" ".abc"
```

Notes:
- Start with `-m simple --log-level ERROR`.
- If `auto` fails, retry with `-m simple` first.
- Errors do not always mean total failure; check `out_xxx/sources/`.
- Use a fresh output directory per run.

---

## .NET Analysis

### Tools
- **dnSpy** - Debugging + decompilation (best)
- **ILSpy** - Decompiler
- **dotPeek** - JetBrains decompiler

### NativeAOT
- Look for `System.Private.CoreLib` strings
- Type metadata present but restructured
- Search for length-prefixed UTF-16 patterns

### Two-Stage XOR + AES-CBC Decode Pattern (Codegate 2013)

**Pattern:** .NET binary stores an encrypted byte array that undergoes XOR decoding followed by AES-256-CBC decryption. The same key value serves as both the AES key and IV.

**Steps:**
1. Extract hardcoded byte array and key string from binary (dnSpy/ILSpy)
2. XOR each byte (may be multi-pass, e.g., `0x25` then `0x58`, equivalent to single `0x7D`)
3. Base64-decode the XOR result
4. AES-256-CBC decrypt with `RijndaelManaged` using the extracted key as both Key and IV

```python
from Crypto.Cipher import AES
from base64 import b64decode

# Step 1: XOR decode
data = bytearray(encrypted_bytes)
for i in range(len(data)):
    data[i] ^= 0x7D  # Combined XOR key (0x25 ^ 0x58)

# Step 2: Base64 decode
ct = b64decode(bytes(data))

# Step 3: AES-256-CBC decrypt (same value for key and IV)
key = b"9e2ea73295c7201c5ccd044477228527"  # Padded to 32 bytes
cipher = AES.new(key, AES.MODE_CBC, iv=key)
plaintext = cipher.decrypt(ct)
```

**Key insight:** When `RijndaelManaged` appears in .NET decompilation, check if Key and IV are set to the same value — this is a common CTF pattern. The XOR stage often serves as a simple obfuscation layer before the real crypto.

---

## Packed Binaries

### UPX
```bash
upx -d packed -o unpacked
strings binary | grep UPX     # Check for UPX signature
```

### Custom Packers
1. Set breakpoint after unpacking stub
2. Dump memory
3. Fix PE/ELF headers

### PyInstaller
```bash
python pyinstxtractor.py binary.exe
# Look in: binary.exe_extracted/
```

---

## LLVM IR

### Convert to Assembly
```bash
llc task.ll --x86-asm-syntax=intel
gcc -c task.s -o file.o
```

---

## RISC-V Binary Analysis (EHAX 2026)

**Pattern (iguessbro):** Statically linked, stripped RISC-V ELF binary. Can't run natively on x86.

**Disassembly with Capstone:**
```python
from capstone import *

with open('binary', 'rb') as f:
    code = f.read()

# RISC-V 64-bit with compressed instruction support
md = Cs(CS_ARCH_RISCV, CS_MODE_RISCVC | CS_MODE_RISCV64)
md.detail = True

# Disassemble from entry point (check ELF header for e_entry)
TEXT_OFFSET = 0x10000  # typical for static RISC-V
for insn in md.disasm(code[TEXT_OFFSET:], TEXT_OFFSET):
    print(f"0x{insn.address:x}:\t{insn.mnemonic}\t{insn.op_str}")
```

**Common RISC-V patterns:**
- `li a0, N` → load immediate (argument setup)
- `mv a0, s0` → register move
- `call offset` → function call (auipc + jalr pair)
- `beq/bne a0, zero, label` → conditional branch
- `sd/ld` → 64-bit store/load
- `addiw` → 32-bit add (W-suffix = word operations)

**Key differences from x86:**
- No flags register — comparisons are inline with branch instructions
- Arguments in a0-a7 (not rdi/rsi/rdx)
- Return value in a0
- Saved registers s0-s11 (callee-saved)
- Compressed instructions (2 bytes) mixed with standard (4 bytes) — use `CS_MODE_RISCVC`

**Anti-RE tricks in RISC-V:**
- Fake flags as string constants (check for `"n0t_th3_r34l"` patterns)
- Timing anti-brute-force (rdtime instruction)
- XOR decryption with incremental key: `decrypted[i] = enc[i] ^ (key & 0xFF) ^ 0xA5; key += 7`

**Emulation:** `qemu-riscv64 -L /usr/riscv64-linux-gnu/ ./binary` (needs cross-toolchain sysroot)

---

## Binary Ninja

Interactive disassembler/decompiler with rapid community growth.

**Decompilation outputs:** High-Level Intermediate Language (HLIL), pseudo-C, pseudo-Rust, pseudo-Python.

```bash
# Open binary
binaryninja binary
```

```python
# Headless analysis (Python API)
import binaryninja
bv = binaryninja.open_view("binary")
for func in bv.functions:
    print(func.name, hex(func.start))
    print(func.hlil)  # High-Level IL
```

**Community plugins:** Available via Plugin Manager (Ctrl+Shift+P → "Plugin Manager").

**Free version:** https://binary.ninja/free/ (cloud-based, limited features).

**Advantages over Ghidra:** Faster startup, cleaner IL representations, better Python API for scripting.

---

## Decompiler Comparison with dogbolt.org

**dogbolt.org** runs multiple decompilers simultaneously on the same binary and shows results side-by-side.

**Supported decompilers:** Hex-Rays (IDA), Ghidra, Binary Ninja, angr, RetDec, Snowman, dewolf, Reko, Relyze.

**When to use:**
- Decompiler output is confusing — compare with alternatives for clarity
- One decompiler mishandles a construct — another may get it right
- Quick triage without installing every tool locally
- Validate decompiler correctness by cross-referencing outputs

```bash
# Upload via web interface: https://dogbolt.org/
# Or use the API:
curl -F "file=@binary" https://dogbolt.org/api/binaries/
```

**Key insight:** Different decompilers excel at different constructs. When one produces unreadable output, another often generates clearer pseudocode. Cross-referencing catches decompiler bugs.

---

## Useful Commands

```bash
# File info
file binary
checksec --file=binary
rabin2 -I binary

# String extraction
strings binary | grep -iE "flag|secret"
rabin2 -z binary

# Sections
readelf -S binary
objdump -h binary

# Symbols
nm binary
readelf -s binary

# Disassembly
objdump -d binary
objdump -M intel -d binary
```
