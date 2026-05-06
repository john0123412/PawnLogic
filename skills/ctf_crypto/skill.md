---
name: ctf-crypto
description: Cryptography CTF attacks: RSA, AES, ECC, PRNG, hash length-extension, padding oracles, lattice/LWE/CVP, HNP, Coppersmith, Pollard, Wiener, ZKP/Circom/halo2, post-quantum KEM. Dispatch on prime shape, oracle type, or scheme artefact.
license: MIT
compatibility: Requires filesystem-based agent (Claude Code or similar) with bash, Python 3, and internet access for tool installation.
allowed-tools: Bash Read Write Edit Glob Grep Task WebFetch WebSearch
metadata:
  user-invocable: "false"
---

# CTF Cryptography

Quick reference for crypto CTF challenges. Each technique has a one-liner here; see supporting files for full details with code.

## Additional Resources

- [classic-ciphers.md](classic-ciphers.md) — Vigenere/Kasiski, XOR variants, OTP reuse, homophonic
- [modern-ciphers.md](modern-ciphers.md) — AES/CBC/GCM, padding oracle, Bleichenbacher, LFSR, length extension
- [modern-ciphers-2.md](modern-ciphers-2.md) — 2024-26: S-box collision, AES-GCM derived, Ascon diff, linear MAC, FFT Shamir
- [rsa-attacks.md](rsa-attacks.md) — small e/d, common mod, Wiener, Hastad, Fermat, Coppersmith, polynomial-prime
- [rsa-attacks-2.md](rsa-attacks-2.md) — 2025-26: TLS blinder-squaring + Coppersmith partial-`d`
- [rsa-attacks-oracle.md](rsa-attacks-oracle.md) — Manger's OAEP, padding/timing/blinding oracles
- [ecc-attacks.md](ecc-attacks.md) — invalid curve, Smart's, Pohlig-Hellman, ECDSA nonce, genus-1 variety
- [zkp-and-advanced.md](zkp-and-advanced.md) — Groth16/PLONK/halo2/Noir ZK, Z3, SSS, LogUp/ProtoStar
- [prng.md](prng.md) — MT19937, LCG, V8 XorShift128+, time-seed, ChaCha20 key recovery
- [prng-2.md](prng-2.md) — 2024-26: GF(2) matrix, middle-square, logistic, Legendre bit oracle
- [historical.md](historical.md) — Lorenz SZ40, book cipher
- [advanced-math.md](advanced-math.md) — CVP/Babai, LLL, Coppersmith, HNP, Pohlig-Hellman, Quaternion RSA
- [advanced-math-2.md](advanced-math-2.md) — 2024-26: LWE, clock group, CSIDH trace, Joux, GEA LFSR, Hill off-by-one
- [exotic-crypto.md](exotic-crypto.md) — braid-group DH, tropical, ePrint scheme killers, CSIDH sign-leak, PQ (Kyber/UOV)
---

## Pattern Recognition Index

Map **observable signals** (not challenge names) to the right technique. Scan this first.

| Signal in challenge | Technique → file |
|---|---|
| `pow(m, e, n) == m` for some `m` ∉ {0,1,n-1}; timing outlier on one input | RSA fixed-point factoring → rsa-attacks.md |
| Close primes (`|p - q|` small), or partial-known prime | Fermat / Coppersmith structured primes → rsa-attacks.md |
| Small `d` (Wiener bound), or small `e` + small `m` | Wiener / cube-root → rsa-attacks.md |
| Same `m` under same `e` to several `n_i` | Hastad broadcast / CRT → rsa-attacks.md |
| PKCS#1 v1.5 error side-channel on an RSA decrypt endpoint | Bleichenbacher / Manger → rsa-attacks-oracle.md, modern-ciphers.md |
| Two faulted RSA signatures, TLS renegotiation between them | Blinder `A` → `A²` bit recovery → rsa-attacks-oracle.md |
| Many linear eqs mod q with bounded error (ECDSA partial nonce, truncated LCG, HNP) | CVP/Babai (rkm0959 template) → advanced-math.md |
| Power/EM traces with uniform *length* but shape clustering | Waveform-morphology analysis (sliding min/max/mean) → advanced-math-2.md |
| CSIDH / isogeny + small secret vector + AES oracle | Brute force 419-element shared-secret space → advanced-math-2.md |
| Padding-oracle endpoint on CBC | Byte-by-byte CBC padding oracle → modern-ciphers.md |
| ECDSA with partial-nonce leak / same nonce reused | Pohlig-Hellman / nonce lattice → ecc-attacks.md, advanced-math.md |
| MT19937 outputs visible (624 words) | State recovery via Python `randcrack` or GF(2) matrix → prng.md |
| Boolean predicate + "find x such that f(x)=1" + N small | Qiskit Grover `k = π/4√(N/M)` → ctf-misc/ai-ml.md |
| Model weights file + accuracy-gate grader | Federated label-flip poisoning → ctf-misc/ai-ml.md |
| Two parsers for same URL/path/HTML (different libs in deps) | Parser differential → ctf-web/auth-and-access.md |
| halo2 circuit: `advice_values[…]` fill without RNG, ≥ N proofs same secret | Blinding-omission Lagrange recovery → zkp-and-advanced.md |
| LogUp/ProtoStar-style lookup over `F_p` with `p ≤ 2^32` | Characteristic-repetition bypass → zkp-and-advanced.md |
| Noir/Circom `sha256_var(buf, len)` with trailing buf unconstrained | Trailing-byte under-constraint → zkp-and-advanced.md |
| Obfuscated projective embedding, degree-2 coord relations, group order = small·large | Genus-1 variety → Weierstrass + BSGS/MOV/NFS → ecc-attacks.md |
| Jacobian `Point` class without `is_on_curve` check | Invalid-curve small-order pts → ecc-attacks.md |
| Scheme quoting ePrint, "homomorphism learning" / "entropic operator" | Linear-algebra scheme-killer → exotic-crypto.md |
| CSIDH/group-action KEM exposing `group_action(e, ±1)` | Sign-leak oracle → exotic-crypto.md |
| Distinguishable "invalid padding" vs "invalid message" on OAEP endpoint | Manger's attack → rsa-attacks-oracle.md |
| Modulus hex shows repeated-block structure (u·2^k + u·v + w) | Polynomial factorisation of n → rsa-attacks.md |
| Shamir t-of-n with x_i^t = 1 (roots of unity) | FFT collapse recovery → modern-ciphers-2.md |
| AES with `Nr=1` literal or one-round helper | Linear inversion from one PT/CT pair → modern-ciphers-2.md |
| Hill/classical cipher mod = printable-ASCII range (94) | Try N-1 and N-2 → advanced-math-2.md |
| Dual hash suffix constraint MD5 + SHA1 (3-byte) | Joux multicollision cascade → advanced-math-2.md |
| GEA-1/GEA-2 LFSR with known keystream prefix | Rank-deficient key MITM → advanced-math-2.md |
| Bit oracle on `(s_i / p)` Legendre symbol | Z3/lattice over GF(p) state → prng-2.md |
| Falcon-512/1024 ref-impl signing with `double`-based FPU math + many signature samples | FP subnormal / rounding leakage → exotic-crypto.md#falcon |
| ML-DSA / Dilithium signatures with hints `h` (ω-bounded) or filtered `z` | Hint-leak lattice primal attack → exotic-crypto.md#ml-dsa |
| SPHINCS+ / SLH-DSA signing where FORS idx can repeat (non-atomic counter) | Tree-reuse forgery → exotic-crypto.md#slh-dsa |
| CSIDH / CTIDH KEM accepts attacker-supplied Montgomery `A` with no twist check | Invalid-curve Pohlig-Hellman → exotic-crypto.md#invalid-curve-pq |
| Custom KDF iterated N times before encrypt, entropy-shrinking op inside; PCAP has hundreds of packets | Null-key fixed-point: try `key=0` first → modern-ciphers-2.md |
| AES ref-impl in Python with `m[-8]`/`m[-4]` negative indices + accepts `len > 16` | Extended-block linear byte relation → modern-ciphers-2.md |
| Merkle tree leaves = `bcrypt(fixed_salt, user_payload)` with variable-length payload | 72-byte truncation collision → modern-ciphers-2.md |
| TLS server with RSA signing + OOB-byte primitive corrupting `d`; two renegotiations per session | Blinder squaring + Coppersmith partial-`d` → rsa-attacks-2.md |

For each row the point is: **if you see the signal, go to the file — you never need to know the challenge's name.**

---

For inline code/cheatsheet quick references (grep patterns, one-liners, common payloads), see [quickref.md](quickref.md). The `Pattern Recognition Index` above is the dispatch table — always consult it first; load `quickref.md` only if you need a concrete snippet after dispatch.



---

<!-- Source: advanced-math-2.md -->

# CTF Crypto - Advanced Math (2024-2026)

Modern lattice / Coppersmith / algebraic attacks from 2024-2026. For the classical toolbox (isogenies, Pohlig-Hellman, LLL, Quaternion RSA, CVP/HNP template), see [advanced-math.md](advanced-math.md).

## Table of Contents
- [Coppersmith's Method (Structured Primes, LACTF 2026)](#coppersmiths-method-structured-primes-lactf-2026)
- [Clock Group (x^2+y^2=1 mod p) DLP (LACTF 2026)](#clock-group-x2y21-mod-p-dlp-lactf-2026)
- [Non-Permutation S-box Collision Attack (Nullcon 2026)](#non-permutation-s-box-collision-attack-nullcon-2026)
- [Polynomial CRT in GF(2)[x] (Nullcon 2026)](#polynomial-crt-in-gf2x-nullcon-2026)
- [Manger's RSA Padding Oracle Attack (Nullcon 2026)](#mangers-rsa-padding-oracle-attack-nullcon-2026)
- [LWE Lattice Attack via CVP (EHAX 2026)](#lwe-lattice-attack-via-cvp-ehax-2026)
- [Affine Cipher over Non-Prime Modulus (Nullcon 2026)](#affine-cipher-over-non-prime-modulus-nullcon-2026)
- [CSIDH Isogeny Power-Trace Side-Channel (404CTF 2024 "Sea Side Channel")](#csidh-isogeny-power-trace-side-channel-404ctf-2024-sea-side-channel)
- [Hill-Cipher / Classical Modulus Off-by-One (Midnightflag 2025)](#hill-cipher--classical-modulus-off-by-one-source-midnightflag-2025)
- [MD5 + SHA1 Dual-Suffix Joux Multicollision Cascade (FCSC 2025 Fun With Hash)](#md5--sha1-dual-suffix-joux-multicollision-cascade-source-fcsc-2025-fun-with-hash)
- [GEA-1 / GEA-2 LFSR Rank-Deficient Key Recovery (FCSC 2025 Make GEA Great Again)](#gea-1--gea-2-lfsr-rank-deficient-key-recovery-source-fcsc-2025-make-gea-great-again)
- [`dream_multiply` Digit-Concatenation Diophantine (SekaiCTF 2025 I Dream of Genni)](#dream_multiply-digit-concatenation-diophantine-source-sekaictf-2025-i-dream-of-genni)

---

## Coppersmith's Method (Structured Primes, LACTF 2026)

**Pattern (six-seven-again):** p = base + 10^k · x where base is fully known, x is small.

**Condition:** x < N^{1/e} for degree-e polynomial (≈ N^0.25 for linear).

**Attack:**
```python
# p = base + 10^k * x, so x ≡ -base * (10^k)^{-1} (mod p)
# Since p | N, construct polynomial with root x mod N
R.<x> = PolynomialRing(Zmod(N))
inv_10k = inverse_mod(10^k, N)
f = x + (base * inv_10k) % N  # Must be monic!
roots = f.small_roots(X=2^70, beta=0.5)
if roots:
    x_val = int(roots[0])
    p = base + 10^k * x_val
    q = N // p
```

**Key details:**
- Polynomial MUST be monic (leading coefficient 1)
- `beta=0.5` means we're looking for a factor ≥ N^0.5
- `X` parameter is upper bound on root size
- Works for any "partially known prime" pattern

## Clock Group (x^2+y^2=1 mod p) DLP (LACTF 2026)

**Pattern (the-clock):** Diffie-Hellman on the unit circle group.

**Group structure:**
```python
# Group law: (x1,y1) * (x2,y2) = (x1*y2 + y1*x2, y1*y2 - x1*x2)
# Identity: (0, 1)
# Inverse of (x, y): (-x, y)
# Group order: p + 1 (NOT p - 1!)

def clock_mul(P, Q, p):
    x1, y1 = P
    x2, y2 = Q
    return ((x1*y2 + y1*x2) % p, (y1*y2 - x1*x2) % p)

def clock_pow(P, n, p):
    result = (0, 1)  # identity
    base = P
    while n > 0:
        if n & 1:
            result = clock_mul(result, base, p)
        base = clock_mul(base, base, p)
        n >>= 1
    return result
```

**Recovering hidden prime p:**
```python
# Given points on the curve, p divides (x^2 + y^2 - 1)
from math import gcd
vals = [x**2 + y**2 - 1 for x, y in known_points]
p = reduce(gcd, vals)
# May need to remove small factors
```

**Pohlig-Hellman when p+1 is smooth:**
```python
order = p + 1
factors = factor(order)
# Standard Pohlig-Hellman in the clock group
# Solve d in each prime-power subgroup, CRT combine
```

**CRITICAL:** The order is p+1, isomorphic to norm-1 elements of GF(p²)*. This is different from multiplicative group (order p-1) and elliptic curves (order ≈ p).

## Non-Permutation S-box Collision Attack (Nullcon 2026)

**Detection:** Check if S-box is a permutation:
```python
sbox = [...]  # 256 entries
if len(set(sbox)) < 256:
    from collections import Counter
    counts = Counter(sbox)
    for val, cnt in counts.items():
        if cnt > 1:
            colliders = [i for i in range(256) if sbox[i] == val]
            delta = colliders[0] ^ colliders[1]
            print(f"S[{hex(colliders[0])}] = S[{hex(colliders[1])}] = {hex(val)}, delta = {hex(delta)}")
```

**Attack:** For each key byte position k (0-15):
1. Try all 256 values v: encrypt two plaintexts differing by `delta` at position k
2. When `ct1 == ct2`: S-box input at position k was in the collision set `{c0, c1}`
3. Deduce: `key[k] = v ^ round_const` OR `key[k] = v ^ round_const ^ delta`
4. 2-way ambiguity per byte -> 2^16 = 65,536 candidates, brute-force locally

**Total oracle queries:** 16 x 256 + 1 = 4,097 (reference ciphertext + probes).

**Key lessons:**
- SAT/SMT solvers time out on 15+ rounds of symbolic AES even with simplified S-box
- Integral/square attacks fail because non-permutation S-box breaks balance property
- Always check S-box for non-permutation FIRST before attempting complex cryptanalysis

---

## Polynomial CRT in GF(2)[x] (Nullcon 2026)

**Pattern:** Server gives `r = flag mod f` where `f` is a random polynomial over GF(2).

**Attack:** Chinese Remainder Theorem in polynomial ring GF(2)[x]:
1. Collect ~20 pairs `(r_i, f_i)` from server (each `f_i` is ~32-bit random polynomial)
2. Filter for coprime pairs using polynomial GCD
3. Apply CRT to combine: `flag = r_i (mod f_i)` for all i
4. With ~13-20 coprime 32-bit moduli (>= 400 bits combined), flag is unique

```python
def poly_crt(remainders, moduli):
    """CRT in GF(2)[x]: combine (r_i, f_i) pairs."""
    result, mod = remainders[0], moduli[0]
    for i in range(1, len(remainders)):
        g, s, t = poly_xgcd(mod, moduli[i])
        combined_mod = poly_mul(mod, moduli[i])
        result = poly_add(poly_mul(poly_mul(remainders[i], s), mod),
                         poly_mul(poly_mul(result, t), moduli[i]))
        result = poly_mod(result, combined_mod)
        mod = combined_mod
    return result, mod
```

---

## Manger's RSA Padding Oracle Attack (Nullcon 2026)

**Setup:**
- Key `k < 2^64` (small), RSA modulus `n` is large (1337+ bits)
- Oracle: "invalid padding" = `decrypt < threshold`, "error" = `decrypt >= threshold`
- No modular wrap-around because `k << n`

**Attack (simplified Manger's):**
```python
# Phase 1: Find f1 where k * f1 >= threshold
f1 = 1
while oracle(encrypt(f1)) == "below":  # multiply ciphertext by f1^e mod n
    f1 *= 2
# f1/2 < threshold/k <= f1, so k is in [threshold/f1, threshold/(f1/2)]

# Phase 2: Binary search for exact key
lo, hi = 0, threshold
while lo < hi:
    mid = (lo + hi) // 2
    f_test = ceil(threshold, mid + 1)  # f such that k*f >= threshold iff k > mid
    if oracle(encrypt(f_test)) == "above":
        hi = mid
    else:
        lo = mid + 1
key = lo  # ~64 queries for 64-bit key
```

**Total queries:** ~128 (64 for phase 1 + 64 for phase 2).

---

## LWE Lattice Attack via CVP (EHAX 2026)

**Pattern (Dream Labyrinth):** Multi-layer challenge ending with Learning With Errors (LWE) recovery. Secret vector `s` in {-1, 0, 1}^n, public matrix A, ciphertext `b = A*s + e (mod q)`.

**LWE solving with fpylll (CVP/Babai):**
```python
from fpylll import IntegerMatrix, LLL, CVP
import numpy as np

q = 3329  # Common LWE modulus (Kyber uses this)
n = 256   # Secret dimension
m = 512   # Number of samples

# A is m×n matrix, b is m-vector, all mod q
# Construct lattice basis for CVP approach
# Lattice: rows of [q*I_m | 0] on top, [A^T | I_n] below
# Target: b

def solve_lwe_cvp(A, b, q, n, m):
    # Build lattice basis (m+n) × (m+n)
    dim = m + n
    B = IntegerMatrix(dim, dim)

    # Top m rows: q*I_m (ensures solutions mod q)
    for i in range(m):
        B[i, i] = q

    # Bottom n rows: A columns + identity
    for j in range(n):
        for i in range(m):
            B[m + j, i] = int(A[i][j])
        B[m + j, m + j] = 1

    # LLL reduce the basis
    LLL.reduction(B)

    # Target vector: (b | 0...0)
    target = [int(b[i]) for i in range(m)] + [0] * n

    # CVP via Babai's nearest plane
    closest = CVP.babai(B, target)

    # Extract secret from last n components
    s_candidate = [closest[m + j] for j in range(n)]

    # Project to ternary {-1, 0, 1}
    s = []
    for val in s_candidate:
        val_mod = val % q
        if val_mod == 0:
            s.append(0)
        elif val_mod == 1:
            s.append(1)
        elif val_mod == q - 1:
            s.append(-1)
        else:
            # Try closest ternary value
            s.append(min([-1, 0, 1], key=lambda t: abs((val_mod - t) % q)))
    return s

s = solve_lwe_cvp(A, b, q, n, m)
```

**CRITICAL: Endianness gotcha.** Server may describe data as "big-endian" but actually use little-endian (or vice versa). If CVP produces garbage, try swapping byte order of the secret interpretation:
```python
# If server says big-endian but actually uses little-endian:
s_bytes_le = bytes([(v % 256) for v in s])  # little-endian
s_bytes_be = s_bytes_le[::-1]               # big-endian
# Try both interpretations for key derivation
```

**Key derivation after LWE recovery (common pattern):**
```python
import hashlib
from Cryptodome.Cipher import AES

s_bytes = bytes([(v % 256) for v in s])

# Recover session nonce: XOR wrapped_nonce with hash of secret
session_nonce = bytes(a ^ b for a, b in
    zip(wrapped_nonce, hashlib.sha256(s_bytes).digest()[:16]))

# Derive AES key from secret + nonce
aes_key = hashlib.sha256(s_bytes + session_nonce).digest()

# Decrypt AES-GCM
cipher = AES.new(aes_key, AES.MODE_GCM, nonce=aes_nonce)
plaintext = cipher.decrypt_and_verify(ciphertext, tag)
```

**Layer patterns in multi-stage crypto challenges:**
- **Layer 1 (Geometry):** Reconstruct point positions from noisy distance measurements. Use least-squares or trilateration with multiple models. Compute convex hull of recovered points.
- **Layer 2 (Subspace):** Find hidden low-dimensional subspace in high-dimensional data. Self-dot products of candidate vectors identify correct answers (smallest self-dot products = closest to subspace).
- **Layer 3 (LWE):** Recover secret vector from lattice problem. Use CVP with fpylll, project result to expected domain (ternary, binary, etc.).

**References:** EHAX CTF 2026 "Dream Labyrinth". Related: Kyber/CRYSTALS lattice cryptography.

---

## Affine Cipher over Non-Prime Modulus (Nullcon 2026)

**Pattern:** `c = A @ p + b (mod m)` where A is nxn matrix, m may not be prime (e.g., 65).

**Chosen-plaintext attack:**
1. Send n+1 crafted inputs to get n+1 ciphertext blocks
2. Difference attack: `c_i - c_0 = A @ (p_i - p_0) (mod m)`
3. Build difference matrices D (plaintext) and E (ciphertext)
4. Solve: `A = E @ D^{-1} (mod m)` using Gauss-Jordan with GCD invertibility checks
5. Recover: `b = c_0 - A @ p_0 (mod m)`

**CRT approach for composite modulus (preferred):**
```python
def crt2(r1, m1, r2, m2):
    """CRT: x = r1 (mod m1) and x = r2 (mod m2)"""
    m1_inv = pow(m1, m2 - 2, m2)  # Fermat's little theorem
    t = ((r2 - r1) * m1_inv) % m2
    return (r1 + m1 * t) % (m1 * m2)

def gauss_elim(A, b, mod):
    """Gaussian elimination over Z/modZ. A=matrix, b=vector, returns solution x."""
    n = len(b)
    M = [list(A[i]) + [b[i]] for i in range(n)]  # augmented matrix
    for col in range(n):
        pivot = next((r for r in range(col, n) if M[r][col] % mod), None)
        if pivot is None: continue
        M[col], M[pivot] = M[pivot], M[col]
        inv = pow(M[col][col], -1, mod)
        M[col] = [x * inv % mod for x in M[col]]
        for r in range(n):
            if r != col and M[r][col] % mod:
                f = M[r][col]
                M[r] = [(M[r][j] - f * M[col][j]) % mod for j in range(n + 1)]
    return [M[i][n] % mod for i in range(n)]

# For m=65=5x13: Gaussian elimination in GF(5) and GF(13) separately
A5, b5 = A % 5, rhs % 5
A13, b13 = A % 13, rhs % 13
x5 = gauss_elim(A5, b5, mod=5)
x13 = gauss_elim(A13, b13, mod=13)
x = [crt2(x5[i], 5, x13[i], 13) for i in range(len(x5))]
```

---

## CSIDH Isogeny Power-Trace Side-Channel (404CTF 2024 "Sea Side Channel")

**Target:** CSIDH (Commutative Supersingular Isogeny Diffie-Hellman) — post-quantum key exchange where secret is a small integer vector `e = (e_1, ..., e_n)` with each `e_i` in a small range (e.g. `[-5, 5]`).

**Practical trick 1 — brute force the shared secret space:**
CSIDH's shared-secret keyspace is frequently tiny (≤ 419 distinct values for the 404CTF instance). Iterate all candidates, validate each against a known-plaintext AES oracle (if the shared secret feeds KDF → AES-GCM, ≤ 419 trial decryptions suffice). No isogeny computation needed.

**Practical trick 2 — Velu isogeny degree leaks via loop count:**
For each prime `l_i`, the Velu formula applies `l_i` point operations. Degree-3/5/7 isogenies produce distinctly sized power traces:
- degree 3 (`l=3`) → ~1940 frames
- degree 5 → ~3700 frames
- degree 7 → ~5440 frames

Count frames per isogeny step → directly read off `|e_i|` (sign decided later).

**Practical trick 3 — bypass constant-time padding via waveform shape:**
A "constant time" implementation pads each step to 7 operations so the *duration* no longer leaks `l_i`. Bypass it by looking at the **morphology** of the trace (shape of `P+1/4` pattern), not its length. Groups the 7-op step into A/B/C signatures:
```python
import numpy as np
# sliding min/max/mean over 100-sample window to denoise
def shape_features(trace, w=100):
    k = np.lib.stride_tricks.sliding_window_view(trace, w)
    return np.stack([k.min(-1), k.max(-1), k.mean(-1)], axis=-1)

# Cluster feature sequences by visual pattern (A/B/C) — each cluster maps to one l_i
```
Then pattern-match each step against reference A/B/C waveforms.

**Key lesson for CTFs:** when a crypto chall gives you power/EM/timing traces, first try duration analysis (loop counts). If that's padded, escalate to **waveform shape** — padding doesn't fix shape.

Source: [mathishammel.com/blog/writeup-404ctf-seaside](https://mathishammel.com/blog/writeup-404ctf-seaside).

---

## Hill-Cipher / Classical Modulus Off-by-One (source: Midnightflag 2025)

**Trigger:** Hill cipher (or any classical encoding) where the alphabet is printable-ASCII range 33–126 (94 chars) but the code uses modulus 94 — while the actual keyspace requires 93 (or vice versa).
**Signals:** challenge script with `mod = 94` on printable ASCII; small key-permutation space (≤ 6 orderings).
**Mechanic:** brute-force the key-permutation space AND sweep modulus ∈ {N−2, N−1, N}. Correct modulus gives readable plaintext; off-by-one gives garbled output. Pattern: any classical cipher using a printable-ASCII-sized modulus → try N−1 and N−2.

## MD5 + SHA1 Dual-Suffix Joux Multicollision Cascade (source: FCSC 2025 Fun With Hash)

**Trigger:** server requires `md5(p)` and `sha1(p)` to both end with a fixed 3-byte suffix (e.g. `FC 5C 25`); payload must also embed a time-limited `sha256(ts)`.
**Signals:** dual-hash suffix constraint, Merkle-Damgård hashes only (no BLAKE/KangarooTwelve), short handshake time.
**Mechanic:** Joux multicollision on MD5 — find `k = 24` pairs of colliding blocks → `2^24` MD5-equivalent payloads at cost `24·2^64 / 2^32 = 2^56` work (trivial with dedicated differential tool). Constrain blocks so the 3-byte MD5 suffix already holds, then enumerate the `2^24` free payloads until one also matches the SHA1 3-byte suffix. `P ≈ 2^24 · 2^−24 ≈ 63 %` success. Tool: hashclash (Marc Stevens) with custom target bytes.

## GEA-1 / GEA-2 LFSR Rank-Deficient Key Recovery (source: FCSC 2025 Make GEA Great Again)

**Trigger:** GPRS cipher GEA-1 or GEA-2; three/four LFSRs with weak key-setup (intentional rank deficiency in init reducing effective keyspace to ~40 bits); known plaintext prefix.
**Signals:** keystream length multiple of 8 bits; challenge explicitly references GEA/GPRS; short session key (64 bits).
**Mechanic:** use Beierle et al. (2021) — recover GEA-1 session key via 40-bit meet-in-the-middle on the rank-deficient register initialization. For GEA-2, use the algebraic attack (linearisation over `F_2`). Generic takeaway: any LFSR-based telephony cipher (GEA, A5/1, A5/2) → check for register-init "coincidence".

## `dream_multiply` Digit-Concatenation Diophantine (source: SekaiCTF 2025 I Dream of Genni)

**Trigger:** custom binary op `f(x,y) = int(str(x) + str(y))` or digit-shifting variant; service asks for `(x, y)` satisfying both `f(x, y) == T` and `x * y == T'`.
**Signals:** user-provided constraint involving `str(x) + str(y)`, `str(x).lstrip('0')`, or base-10 digit concatenation.
**Mechanic:** branch-and-prune over digit positions. `f(x, y)` = `x · 10^len(y) + y`, so the constraint becomes `x · 10^k + y = T` with `y < 10^k`. For each candidate `k ∈ [1, 10]`, solve `y = T − x · 10^k`, check `x · y == T'` → small search space. Z3 or plain backtracking in a few seconds.



---

<!-- Source: advanced-math.md -->

# CTF Crypto - Advanced Mathematical Attacks

## Table of Contents
- [Elliptic Curve Isogenies](#elliptic-curve-isogenies)
- [Pohlig-Hellman Attack (Weak ECC)](#pohlig-hellman-attack-weak-ecc)
- [LLL Algorithm for Approximate GCD](#lll-algorithm-for-approximate-gcd)
- [Coppersmith's Method (Close Private Keys)](#coppersmiths-method-close-private-keys)
- [Quaternion RSA](#quaternion-rsa)
- [Polynomial Arithmetic in GF(2)[x]](#polynomial-arithmetic-in-gf2x)
- [RSA Signing Bug](#rsa-signing-bug)
- [CVP for Biased-Nonce ECDSA / Truncated LCG / HNP](#cvp-for-biased-nonce-ecdsa--truncated-lcg--hnp)

For 2024-2026 era techniques (LACTF / Nullcon / EHAX / 404CTF / FCSC / SekaiCTF / Midnightflag), see [advanced-math-2.md](advanced-math-2.md).

---

## Elliptic Curve Isogenies

Isogeny-based crypto challenges are often **graph traversal problems in disguise**:

**Key concepts:**
- j-invariant uniquely identifies curve isomorphism class
- Curves connected by isogenies form a graph (often tree-like)
- Degree-2 isogenies: each node has ~3 neighbors (2 children + 1 parent)

**Modular polynomial approach:**
- Connected j-invariants j₁, j₂ satisfy Φ₂(j₁, j₂) = 0
- Find neighbors by computing roots of Φ₂(j, Y) in the finite field
- Much faster than computing actual isogenies

**Pathfinding in isogeny graphs:**
```python
# Height estimation via random walks to leaves
def estimate_height(j, neighbors_func, trials=100):
    min_depth = float('inf')
    for _ in range(trials):
        depth, curr = 0, j
        while True:
            nbrs = neighbors_func(curr)
            if len(nbrs) <= 1:  # leaf node
                break
            curr = random.choice(nbrs)
            depth += 1
        min_depth = min(min_depth, depth)
    return min_depth

# Find path between two nodes via LCA
def find_path(start, end):
    # Ascend from both nodes tracking heights
    # Find least common ancestor
    # Concatenate: path_up(start) + reversed(path_up(end))
```

**Complex multiplication (CM) curves:**
- Discriminant D = f² · D_K where D_K is fundamental discriminant
- Conductor f determines tree depth
- Look for special discriminants: -163, -67, -43, etc. (class number 1)

## Pohlig-Hellman Attack (Weak ECC)

For elliptic curves with smooth order (many small prime factors):

```python
from sage.all import *

# Factor curve order
E = EllipticCurve(GF(p), [a, b])
n = E.order()
factors = factor(n)

# Solve DLP in each small subgroup
partial_logs = []
for (prime, exp) in factors:
    # Compute subgroup generator
    cofactor = n // (prime ** exp)
    G_sub = cofactor * G
    P_sub = cofactor * P  # Target point

    # Solve small DLP
    d_sub = discrete_log(P_sub, G_sub, ord=prime**exp)
    partial_logs.append((d_sub, prime**exp))

# Combine with CRT
from sympy.ntheory.modular import crt
moduli = [m for (_, m) in partial_logs]
residues = [r for (r, _) in partial_logs]
private_key, _ = crt(moduli, residues)
```

## LLL Algorithm for Approximate GCD

**Pattern (Grinch's Cryptological Defense):** Server gives hints `h_i = f * p_i + n_i` where f is the flag, p_i are small primes, n_i is small noise.

**Lattice construction:**
```python
from sage.all import *

# Collect 3 hints from server
# h_i = f * p_i + n_i (noise is small)
# Construct lattice where short vector reveals primes

M = matrix(ZZ, [
    [1, 0, 0, h1],
    [0, 1, 0, h2],
    [0, 0, 1, h3],
    [0, 0, 0, -1]  # Scaling factor
])

reduced = M.LLL()
# Short vector contains p1, p2, p3
# Recover f = (h1 - n1) / p1
```

## Coppersmith's Method (Close Private Keys)

**Pattern (Duality of Key):** Two RSA key pairs with d1 ≈ d2 (small difference).

**Attack:**
```python
# From e1*d1 ≡ 1 mod φ and e2*d2 ≡ 1 mod φ:
# d2 - d1 ≡ (e1*e2)^(-1) * (e1 - e2) mod p

# Construct polynomial f(x) = (r - x) mod p where x = d2-d1
# Use Coppersmith small_roots() to find x

R.<x> = PolynomialRing(Zmod(N))
r = inverse_mod(e1*e2, N) * (e1 - e2) % N
f = r - x
roots = f.small_roots(X=2^128, beta=0.5)  # Adjust bounds
# x = d2 - d1, recover p from gcd(f(x), N)
```

## Quaternion RSA

**Pattern:** RSA encryption using Hamilton quaternion algebra over Z/nZ. The plaintext is embedded into quaternion components that are linear combinations of m, p, q, then the quaternion matrix is raised to power e mod n.

**Key structure:**
```python
# Quaternion q = a0 + a1*i + a2*j + a3*k
# Components are linear in m, p, q:
a0 = m
a1 = m + α1*p + β1*q  # e.g., m + 3p + 7q
a2 = m + α2*p + β2*q  # e.g., m + 11p + 13q
a3 = m + α3*p + β3*q  # e.g., m + 17p + 19q

# 4x4 matrix representation:
# Row 0: [a0, -a1, -a2, -a3]
# Row 1: [a1,  a0, -a3,  a2]
# Row 2: [a2,  a3,  a0, -a1]
# Row 3: [a3, -a2,  a1,  a0]

# Ciphertext = first row of matrix^e mod n
```

**Critical property:** For quaternion `q = s + v` (scalar + vector), `q^k = s_k + t_k*v` — the vector part stays **proportional** under exponentiation. This means the ratios of imaginary components are preserved:

`c1 : c2 : c3 = a1 : a2 : a3 (mod n)`

**Factoring n (the attack):**

```python
import math

# Extract quaternion components from ciphertext row [ct0, ct1, ct2, ct3]
# Row 0 = [c0, -c1, -c2, -c3], so negate last 3:
c0, c1, c2, c3 = ct[0], (-ct[1]) % n, (-ct[2]) % n, (-ct[3]) % n

# From ratio preservation: c1*a2 = c2*a1 (mod n), c1*a3 = c3*a1 (mod n)
# Substituting a_i = m + αi*p + βi*q and eliminating m between two equations:
# Result: A*p + B*q ≡ 0 (mod n=pq) => q|A, p|B

# For components a1=m+α1p+β1q, a2=m+α2p+β2q, a3=m+α3p+β3q:
# Eliminate m from (c1*a2=c2*a1) and (c1*a3=c3*a1):
A = (-(α1*c1 - α2*c2)*(c1-c3) + (α1*c1 - α3*c3)*(c1-c2)) % n
B = (-(β1*c1 - β2*c2)*(c1-c3) + (β1*c1 - β3*c3)*(c1-c2)) % n

# More concretely for coefficients [3,7], [11,13], [17,19]:
A = (-(11*c1-3*c2)*(c1-c3) + (17*c1-3*c3)*(c1-c2)) % n
B = (-(13*c1-7*c2)*(c1-c3) + (19*c1-7*c3)*(c1-c2)) % n

q_factor = math.gcd(A, n)  # gives q
p_factor = math.gcd(B, n)  # gives p
```

**Decryption after factoring:**

Over F_p, the quaternion algebra H_p ≅ M_2(F_p) (Wedderburn theorem), so the quaternion's multiplicative order divides p²-1. Decrypt using:

```python
# Group order for quaternions over F_p divides p²-1
d_p = pow(e, -1, p**2 - 1)
d_q = pow(e, -1, q**2 - 1)

# Decrypt mod p and mod q separately, then CRT
enc_mod_p = [[x % p for x in row] for row in enc_matrix]
enc_mod_q = [[x % q for x in row] for row in enc_matrix]
dec_p = matrix_pow(enc_mod_p, d_p, p)
dec_q = matrix_pow(enc_mod_q, d_q, q)

# CRT combine: dec_matrix[0][0] = m (the flag)
m = CRT(dec_p[0][0], dec_q[0][0], p, q)
flag = long_to_bytes(m)
```

**Why it works:** The "reduced dimension" is that 4D quaternion exponentiation reduces to a 2D recurrence (scalar + magnitude of vector), and the direction of the vector part is invariant. This leaks the ratio a1:a2:a3 directly from the ciphertext, enabling factorization.

**References:** SECCON CTF 2023 "RSA 4.0", 0xL4ugh CTF "Reduced Dimension"

---

## Polynomial Arithmetic in GF(2)[x]

**Key operations for CTF crypto:**
```python
def poly_add(a, b):
    """Addition in GF(2)[x] = XOR of coefficient integers."""
    return a ^ b

def poly_mul(a, b):
    """Carry-less multiplication in GF(2)[x]."""
    result = 0
    while b:
        if b & 1:
            result ^= a
        a <<= 1
        b >>= 1
    return result

def poly_divmod(a, b):
    """Division with remainder in GF(2)[x]."""
    if b == 0:
        raise ZeroDivisionError
    deg_a, deg_b = a.bit_length() - 1, b.bit_length() - 1
    q = 0
    while deg_a >= deg_b and a:
        shift = deg_a - deg_b
        q ^= (1 << shift)
        a ^= (b << shift)
        deg_a = a.bit_length() - 1
    return q, a  # quotient, remainder
```

**Applications:** CRT in GF(2)[x] for recovering secrets from polynomial remainders, Reed-Solomon-like error correction.

---

## RSA Signing Bug

**Vulnerability:** Using wrong exponent for signing
- Correct: `sign = m^d mod n` (private exponent)
- Bug: `sign = m^e mod n` (public exponent)

**Exploitation:**
```python
# If signature is m^e mod n, we can "encrypt" to verify
# and compute e-th root to forge signatures
from sympy import integer_nthroot

# For small e (e.g., 3), take e-th root if m^e < n
forged_sig, exact = integer_nthroot(message, e)
if exact:
    print(f"Forged signature: {forged_sig}")
```

---

## CVP for Biased-Nonce ECDSA / Truncated LCG / HNP

**Pattern (Hidden Number Problem):** You have many equations of the form `k_i ≡ a_i * x + b_i (mod q)` where `k_i` is an unknown nonce **with some high or low bits known or biased**. Goal: recover the secret `x`.

Applies to:
- ECDSA with partial-nonce leak (top/bottom bits known from side-channel)
- Truncated LCG (seen low/mid bits of state, each state relates linearly to seed)
- DSA with constant nonce prefix

**Lattice construction (Babai's nearest plane via fpylll):**
```python
from fpylll import IntegerMatrix, CVP, LLL

# N equations: k_i = a_i * x + b_i (mod q), where |k_i| <= K (bias bound)
# Build basis B and target t so that CVP(B, t) recovers x

n = len(a_list)
B = IntegerMatrix(n + 2, n + 2)
for i in range(n):
    B[i, i] = q
B[n, n] = 1
B[n + 1, n + 1] = K                 # bound term (so short vector reveals x)
for i in range(n):
    B[n, i] = a_list[i]
    B[n + 1, i] = b_list[i]

B = LLL.reduction(B)
target = tuple([0] * n + [0, K])    # we want the "centered" combination
closest = CVP.babai(B, target)
# Read x from the reduced basis — typically closest[-2] or a small post-processing step
```

**Canonical reference:** [rkm0959/Inequality_Solving_with_CVP](https://github.com/rkm0959/Inequality_Solving_with_CVP) — this repo is the go-to template; it reframes biased-nonce ECDSA, truncated LCG, and bounded HNP into a single inequality-solving CVP problem.

**Spot the pattern:** any challenge with many linear equations mod q + bounded error → CVP via lattice. Don't try to Gaussian-eliminate; the "error" is what makes LLL/Babai necessary.

---




---

<!-- Source: classic-ciphers.md -->

# CTF Crypto - Classic Ciphers

## Table of Contents
- [Vigenere Cipher](#vigenere-cipher)
- [Atbash Cipher](#atbash-cipher)
- [Substitution Cipher with Rotating Wheel](#substitution-cipher-with-rotating-wheel)
- [Kasiski Examination for Key Length](#kasiski-examination-for-key-length)
- [XOR Variants](#xor-variants)
  - [Multi-Byte XOR Key Recovery via Frequency Analysis](#multi-byte-xor-key-recovery-via-frequency-analysis)
  - [Cascade XOR (First-Byte Brute Force)](#cascade-xor-first-byte-brute-force)
  - [XOR with Rotation: Power-of-2 Bit Isolation (Pragyan 2026)](#xor-with-rotation-power-of-2-bit-isolation-pragyan-2026)
  - [Weak XOR Verification Brute Force (Pragyan 2026)](#weak-xor-verification-brute-force-pragyan-2026)
- [Deterministic OTP with Load-Balanced Backends (Pragyan 2026)](#deterministic-otp-with-load-balanced-backends-pragyan-2026)
- [OTP Key Reuse / Many-Time Pad XOR (BYPASS CTF 2025)](#otp-key-reuse--many-time-pad-xor-bypass-ctf-2025)
- [Book Cipher](#book-cipher)
- [Variable-Length Homophonic Substitution (ASIS CTF Finals 2013)](#variable-length-homophonic-substitution-asis-ctf-finals-2013)

---

## Vigenere Cipher

**Known Plaintext Attack (most common in CTFs):**
```python
def vigenere_decrypt(ciphertext, key):
    result = []
    key_index = 0
    for c in ciphertext:
        if c.isalpha():
            shift = ord(key[key_index % len(key)].upper()) - ord('A')
            base = ord('A') if c.isupper() else ord('a')
            result.append(chr((ord(c) - base - shift) % 26 + base))
            key_index += 1
        else:
            result.append(c)
    return ''.join(result)

def derive_key(ciphertext, plaintext):
    """Derive key from known plaintext (e.g., flag format CCOI26{)"""
    key = []
    for c, p in zip(ciphertext, plaintext):
        if c.isalpha() and p.isalpha():
            c_val = ord(c.upper()) - ord('A')
            p_val = ord(p.upper()) - ord('A')
            key.append(chr((c_val - p_val) % 26 + ord('A')))
    return ''.join(key)
```

### Kasiski Examination for Key Length

When no known plaintext is available, determine the Vigenere key length using Kasiski examination: find repeated sequences in the ciphertext and compute the GCD of their distances.

```python
from math import gcd
from functools import reduce
from collections import Counter

def kasiski_examination(ciphertext, min_seq=3):
    """Find repeating sequences and compute likely key lengths."""
    ct = ''.join(c.upper() for c in ciphertext if c.isalpha())
    distances = []

    # Find repeated trigrams and their distances
    for seq_len in range(min_seq, 6):
        seen = {}
        for i in range(len(ct) - seq_len):
            seq = ct[i:i+seq_len]
            if seq in seen:
                for prev_pos in seen[seq]:
                    distances.append(i - prev_pos)
                seen[seq].append(i)
            else:
                seen[seq] = [i]

    # Key length is likely the GCD of distances
    if distances:
        key_len = reduce(gcd, distances)
        print(f"Likely key length: {key_len}")
        print(f"All distances: {sorted(set(distances))}")
        return key_len
    return None

def frequency_attack(ciphertext, key_length):
    """Break Vigenere by frequency analysis on each key-position group."""
    ct = [c.upper() for c in ciphertext if c.isalpha()]
    english_freq = [0.082,0.015,0.028,0.043,0.127,0.022,0.020,0.061,0.070,
                   0.002,0.008,0.040,0.024,0.067,0.075,0.019,0.001,0.060,
                   0.063,0.091,0.028,0.010,0.023,0.002,0.020,0.001]
    key = []

    for i in range(key_length):
        group = [ct[j] for j in range(i, len(ct), key_length)]
        # Try each shift, score by English letter frequency
        best_shift, best_score = 0, -1
        for shift in range(26):
            decrypted = [chr((ord(c) - ord('A') - shift) % 26 + ord('A')) for c in group]
            freq = Counter(decrypted)
            score = sum(freq.get(chr(j+65), 0) / len(group) * english_freq[j]
                       for j in range(26))
            if score > best_score:
                best_score = score
                best_shift = shift
        key.append(chr(best_shift + ord('A')))

    return ''.join(key)
```

**Key insight:** Repeated sequences in Vigenere ciphertext occur at distances that are multiples of the key length. The GCD of all such distances reveals the key length, after which each position becomes a simple Caesar cipher solvable by frequency analysis.

**When standard keys don't work:**
1. Key may not repeat - could be as long as message
2. Key derived from challenge theme (character names, phrases)
3. Key may have "padding" - repeated letters (IICCHHAA instead of ICHA)
4. Try guessing plaintext words from theme, derive full key

---

## Atbash Cipher

Simple substitution: A<->Z, B<->Y, C<->X, etc.

```python
def atbash(text):
    return ''.join(
        chr(ord('Z') - (ord(c.upper()) - ord('A'))) if c.isalpha() else c
        for c in text
    )
```

**Identification:** Challenge name hints ("Abashed" = Atbash), preserves spaces/punctuation, 1-to-1 substitution.

---

## Substitution Cipher with Rotating Wheel

**Pattern (Wheel of Mystery):** Physical cipher wheel with inner/outer alphabets.

**Automated solver:** Use [quipqiup.com](https://quipqiup.com/) for general substitution ciphers — it uses word pattern matching and language entropy to solve without knowing the key.

**Brute force all rotations:**
```python
outer = "ABCDEFGHIJKLMNOPQRSTUVWXYZ{}"
inner = "QNFUVWLEZYXPTKMR}ABJICOSDHG{"  # Given

for rotation in range(len(outer)):
    rotated = inner[rotation:] + inner[:rotation]
    mapping = {outer[i]: rotated[i] for i in range(len(outer))}
    decrypted = ''.join(mapping.get(c, c) for c in ciphertext)
    if decrypted.startswith("METACTF{"):
        print(decrypted)
```

---

## XOR Variants

### Multi-Byte XOR Key Recovery via Frequency Analysis

**Pattern:** Ciphertext XOR'd with a repeating multi-byte key. Key length unknown.

**Step 1 — Determine key length:** Try each candidate length, split ciphertext into groups by position modulo key length, score each group's byte frequency against English text (space = 0x20 is the most common byte).

**Step 2 — Recover each key byte:** For each position, brute-force all 256 byte values and select the one producing the most English-like decrypted text.

```python
from collections import Counter

def score_english(data):
    """Score how English-like a byte sequence is."""
    freq = Counter(data)
    # Space is the most common character in English text
    return freq.get(ord(' '), 0) + sum(freq.get(c, 0) for c in range(ord('a'), ord('z')+1))

def find_key_length(ciphertext, max_len=40):
    """Test key lengths by scoring single-byte XOR on each column."""
    best_len, best_score = 1, 0
    for kl in range(1, max_len + 1):
        total = 0
        for col in range(kl):
            group = ciphertext[col::kl]
            best_col_score = max(
                score_english(bytes(b ^ k for b in group))
                for k in range(256)
            )
            total += best_col_score
        if total > best_score:
            best_score = total
            best_len = kl
    return best_len

def recover_key(ciphertext, key_length):
    """Recover each key byte via frequency analysis."""
    key = []
    for col in range(key_length):
        group = ciphertext[col::key_length]
        best_k = max(range(256), key=lambda k: score_english(bytes(b ^ k for b in group)))
        key.append(best_k)
    return bytes(key)

ct = open('encrypted.bin', 'rb').read()
kl = find_key_length(ct)
key = recover_key(ct, kl)
print(f"Key ({kl} bytes): {key}")
print(bytes(c ^ key[i % len(key)] for i, c in enumerate(ct)))
```

**Key insight:** Multi-byte repeating XOR splits into `key_length` independent single-byte XOR problems. English text frequency (especially space = 0x20) reliably identifies correct key bytes. Works best with ciphertext longer than ~100 bytes.

### Cascade XOR (First-Byte Brute Force)

**Pattern (Shifty XOR):** Each byte XORed with previous ciphertext byte.

```python
# c[i] = p[i] ^ c[i-1] (or similar cascade)
# Brute force first byte, rest follows deterministically
for first_byte in range(256):
    flag = [first_byte]
    for i in range(1, len(ct)):
        flag.append(ct[i] ^ flag[i-1])
    if all(32 <= b < 127 for b in flag):
        print(bytes(flag))
```

### XOR with Rotation: Power-of-2 Bit Isolation (Pragyan 2026)

**Pattern (R0tnoT13):** Given `S XOR ROTR(S, k)` for multiple rotation offsets k, recover S.

**Key insight:** When ALL rotation offsets are powers of 2 (2, 4, 8, 16, 32, 64), even-indexed and odd-indexed bits NEVER mix across any frame. This reduces N-bit recovery to just 2 bits of brute force.

**Algorithm:**
1. Express every bit of S in terms of two unknowns (s_0 for even bits, s_1 for odd bits) using the k=2 frame
2. Only 4 candidate states -> try all, verify against all frames
3. XOR valid state with ciphertext -> plaintext

### Weak XOR Verification Brute Force (Pragyan 2026)

**Pattern (Dor4_Null5):** Verification XORs all comparison bytes into a single byte instead of checking each individually.

**Vulnerability:** Any fixed response has 1/256 probability of passing. With enough interaction budget (e.g., 4919 attempts), brute-force succeeds with ~256 expected attempts.

```python
for attempt in range(3000):
    r.sendlineafter(b"prompt: ", b"00" * 8)  # Fixed zero response
    result = r.recvline()
    if b"successful" in result:
        break
```

---

## Deterministic OTP with Load-Balanced Backends (Pragyan 2026)

**Pattern (DumCows):** Service encrypts data with deterministic keystream that resets per connection. Multiple backends with different keystreams behind a load balancer.

**Attack:**
1. Send known plaintext (e.g., 18 bytes of 'A'), XOR with ciphertext -> recover keystream
2. XOR keystream with target ciphertext -> decrypt secret
3. **Backend matching:** Must connect to same backend for keystream to match. Retry connections until patterns align.

```python
def recover_keystream(known, ciphertext):
    return bytes(k ^ c for k, c in zip(known, ciphertext))

def decrypt(keystream, target_ct):
    return bytes(k ^ c for k, c in zip(keystream, target_ct))
```

**Key insight:** When encryption is deterministic per connection with no nonce/IV, known-plaintext attack is trivial. The challenge is matching backends.

---

## OTP Key Reuse / Many-Time Pad XOR (BYPASS CTF 2025)

**Pattern (Once More Unto the Same Wind):** Two ciphertexts encrypted with the same OTP key. Known plaintext for one message enables recovery of the other.

**XOR property:** `C1 XOR C2 = P1 XOR P2` (key cancels). When one plaintext (P1) is known, recover the other: `P2 = C1 XOR C2 XOR P1`.

```python
from pwn import xor

c1 = bytes.fromhex("7713283f5e9979...")
c2 = bytes.fromhex("740b393f4c8b67...")

# If one plaintext is known (or guessable, e.g., padded 'A' chars)
known_plaintext = b"A" * len(c1)
flag = xor(xor(c1, c2), known_plaintext)
print(flag)
```

**When plaintext is unknown — crib dragging:**
```python
def crib_drag(c1, c2, crib, max_pos=None):
    """Slide known word across XOR of two ciphertexts."""
    xored = xor(c1[:min(len(c1), len(c2))], c2[:min(len(c1), len(c2))])
    for pos in range(len(xored) - len(crib)):
        candidate = xor(xored[pos:pos+len(crib)], crib)
        if all(32 <= b < 127 for b in candidate):
            print(f"pos {pos}: {candidate}")
```

**Key insight:** OTP (One-Time Pad) XOR encryption is only secure when the key is truly one-time. Reusing the key on two messages leaks `P1 XOR P2` — exploit with known plaintext or crib dragging.

---

## Book Cipher

**Pattern (Booking Key, Nullcon 2026):** Book cipher with "steps forward" encoding. Brute-force starting position with charset filtering reduces ~56k candidates to 3-4.

See [historical.md](historical.md) for full implementation.

---

## Variable-Length Homophonic Substitution (ASIS CTF Finals 2013)

**Pattern (Rookie Agent):** Ciphertext uses alphanumeric characters grouped in blocks of 5. Single-character frequency analysis shows non-uniform distribution. N-gram analysis reveals repeated multi-character groups mapping to single plaintext characters, with different plaintext characters encoded by groups of different lengths (1-4 characters).

**Analysis workflow:**

1. Collapse whitespace and compute n-gram frequencies (1 through 6):
```python
from collections import Counter

ct = "6di16ovhtmnzslsxqcjo8fkdmtyrbn..."  # cleaned ciphertext
for n in range(1, 7):
    ngrams = [ct[i:i+n] for i in range(len(ct)-n+1)]
    freq = Counter(ngrams).most_common(20)
    print(f"{n}-grams: {freq[:10]}")
```

2. Identify constant-frequency groups — if `8f`, `fk`, and `kd` each appear exactly 36 times, check whether `8fkd` also appears 36 times. If so, it is a single substitution unit:
```python
# Iteratively replace most-frequent fixed groups with single symbols
substitutions = {
    '8fkd': 'E', '4bg9': 'I', 'lsxq': 'A', 'fmrk': 'B',
    '9gle': 'C', 'mtyr': 'D', 'cjo': 'F', 'htm': 'G',
    # ... continue for all identified groups
}
reduced = ct
for pattern, symbol in sorted(substitutions.items(), key=lambda x: -len(x[0])):
    reduced = reduced.replace(pattern, symbol)
```

3. The reduced text is now a monoalphabetic substitution — solve with [quipqiup.com](https://quipqiup.com/) or statistical analysis on English.

4. When some characters remain ambiguous after decryption, brute-force permutations against a known hash of the flag:
```python
from itertools import permutations
from hashlib import sha256

partial_flag = '3c6a1c371b381c943065864b95ae5546'
ambiguous_chars = '12456789x'  # chars with uncertain mapping
known_hash = '9f2a579716af14400c9ba1de8682ca52c17b3ed4235ea17ac12ae78ca24876ef'

for p in permutations(ambiguous_chars):
    mapping = dict(zip(ambiguous_chars, p))
    candidate = ''.join(mapping.get(c, c) for c in partial_flag)
    if sha256(('ASIS_' + candidate).encode()).hexdigest() == known_hash:
        print(f"Flag: ASIS_{candidate}")
        break
```

**Key insight:** Variable-length homophonic substitution hides letter frequencies by mapping common plaintext letters to longer codegroups. The attack reverses this: find n-grams that always appear as a unit (identical frequency for all sub-n-grams), replace them with single symbols, then solve the resulting monoalphabetic substitution. When the flag format provides a hash for verification, brute-force remaining ambiguous character permutations offline.



---

<!-- Source: ecc-attacks.md -->

# CTF Crypto - Elliptic Curve Attacks

## Table of Contents
- [Small Subgroup Attacks](#small-subgroup-attacks)
- [Invalid Curve Attacks](#invalid-curve-attacks)
- [Singular Curves](#singular-curves)
- [Smart's Attack (Anomalous Curves)](#smarts-attack-anomalous-curves)
- [ECC Fault Injection](#ecc-fault-injection)
- [Clock Group DLP via Pohlig-Hellman (LACTF 2026)](#clock-group-dlp-via-pohlig-hellman-lactf-2026)
- [ECDSA Nonce Reuse (BearCatCTF 2026)](#ecdsa-nonce-reuse-bearcatctf-2026)
- [Ed25519 Torsion Side Channel (BearCatCTF 2026)](#ed25519-torsion-side-channel-bearcatctf-2026)

---

## Small Subgroup Attacks

- Check curve order for small factors
- Pohlig-Hellman: solve DLP in small subgroups, combine with CRT

```python
# SageMath ECC basics
E = EllipticCurve(GF(p), [a, b])
G = E.gens()[0]  # generator
order = E.order()
```

---

## Invalid Curve Attacks

If point validation is missing, send points on weaker curves. Craft points with small-order subgroups to leak secret key bits.

---

## Singular Curves

If discriminant delta = 0, curve is singular. DLP becomes easy (maps to additive/multiplicative group).

---

## Smart's Attack (Anomalous Curves)

**When to use:** Curve order equals field characteristic p (anomalous curve). Solves ECDLP in O(1) via p-adic lifting.

**Detection:** `E.order() == p` — always check this first!

**SageMath (automatic):**
```python
E = EllipticCurve(GF(p), [a, b])
G = E(Gx, Gy)
Q = E(Qx, Qy)
# Sage's discrete_log handles anomalous curves automatically
secret = G.discrete_log(Q)
```

**Manual p-adic lift (when Sage's auto method fails):**
```python
def smart_attack(p, a, b, G, Q):
    E = EllipticCurve(GF(p), [a, b])
    Qp = pAdicField(p, 2)  # p-adic field with precision 2
    Ep = EllipticCurve(Qp, [a, b])

    # Lift points to p-adics
    Gp = Ep.lift_x(ZZ(G[0]), all=True)  # try both lifts
    Qp_point = Ep.lift_x(ZZ(Q[0]), all=True)

    for gp in Gp:
        for qp in Qp_point:
            try:
                # Multiply by p to get points in kernel of reduction
                pG = p * gp
                pQ = p * qp
                # Extract p-adic logarithm
                x_G = ZZ(pG[0] / pG[1]) / p  # or pG.xy()
                x_Q = ZZ(pQ[0] / pQ[1]) / p
                secret = ZZ(x_Q / x_G) % p
                if E(G) * secret == E(Q):
                    return secret
            except (ZeroDivisionError, ValueError):
                continue
    return None
```

**Multi-layer decryption after key recovery:** Challenge may wrap flag in AES-CBC + DES-CBC or similar — just busywork once the ECC key is recovered. Derive keys with SHA-256 of shared secret.

---

## ECC Fault Injection

**Pattern (Faulty Curves):** Bit flip during ECC computation reveals private key bits.

**Attack:** Compare correct vs faulty ciphertext, recover key bit-by-bit:
```python
# For each key bit position:
# If fault at bit i changes output -> key bit i affects computation
# Binary distinguisher: faulty_output == correct_output -> bit is 0
```

---

## Clock Group DLP via Pohlig-Hellman (LACTF 2026)

**Pattern (the-clock):** Diffie-Hellman on unit circle group: x^2 + y^2 = 1 (mod p).

**Key facts:**
- Group law: (x1,y1) * (x2,y2) = (x1*y2 + y1*x2, y1*y2 - x1*x2)
- **Group order = p + 1** (not p - 1!)
- Isomorphic to GF(p^2)* elements of norm 1

**Group operations:**
```python
def clock_mul(P, Q, p):
    x1, y1 = P
    x2, y2 = Q
    return ((x1*y2 + y1*x2) % p, (y1*y2 - x1*x2) % p)

def clock_pow(P, n, p):
    result = (0, 1)  # identity
    base = P
    while n > 0:
        if n & 1:
            result = clock_mul(result, base, p)
        base = clock_mul(base, base, p)
        n >>= 1
    return result
```

**Recovering hidden prime p:**
```python
# Given points on the curve, p divides (x^2 + y^2 - 1)
from math import gcd
vals = [x**2 + y**2 - 1 for x, y in known_points]
p = reduce(gcd, vals)
# May need to remove small factors
```

**Attack when p+1 is smooth:**
```python
# 1. Recover p from points: gcd(x^2 + y^2 - 1) across known points
# 2. Factor p+1 into small primes
# 3. Pohlig-Hellman: solve DLP in each small subgroup, CRT combine
# 4. Compute shared secret, derive AES key (e.g., via MD5)
```

**Identification:** Challenge mentions "clock", "circle", or gives points satisfying x^2+y^2=1. Always check if p+1 (not p-1) is smooth.

---

## Ed25519 Torsion Side Channel (BearCatCTF 2026)

**Pattern (Curvy Wurvy):** Ed25519 signing oracle derives per-user keys as `user_key = MASTER_KEY * uid mod l` (where `l` is the Ed25519 subgroup order). Goal: recover `MASTER_KEY` from oracle queries.

**The attack exploits Ed25519's cofactor h=8:**
- Full curve order = `8*l`, but scalars are reduced mod `l`
- When `MASTER_KEY * 2^t` wraps around `l`, multiplication produces a torsion component visible as y-coordinate change

**Key extraction via binary decomposition:**
```python
# Query sign(uid=3, 2^t) for t = 0..255
# S_t = (MASTER_KEY * 2^t mod l) * P3
# Check: does doubling S_t match S_{t+1}?

bits = []
for t in range(255):
    S_t = query_sign(3, 2**t)
    S_t1 = query_sign(3, 2**(t+1))
    doubled = point_double(S_t)
    # Wrap occurred if doubled.y != S_{t+1}.y (torsion shift)
    bits.append(0 if doubled.y == S_t1.y else 1)

# Reconstruct: MASTER_KEY ≈ l * (0.bit0 bit1 bit2 ...)_binary
# Try all 8 torsion corrections for exact value
```

**Key insight:** Ed25519's cofactor creates an observable side channel: when scalar multiplication wraps around the subgroup order `l`, the result shifts by a torsion element (one of 8 points). By querying powers of 2 and checking y-coordinate consistency, each bit of the secret scalar is leaked. Libraries like `ecpy` that reduce mod `l` are vulnerable to this when used in multi-user key derivation schemes.

**Detection:** Ed25519 signing oracle with user-controlled UID or multiplier. Key derivation formula `key = master * uid mod l`.

---

## ECDSA Nonce Reuse (BearCatCTF 2026)

**Pattern (Chatroom):** ECDSA signatures on secp256k1 with constant nonce `k`. When two signatures share the same `r` value, the nonce and private key are recoverable.

**Recovery:**
```python
from hashlib import sha256

# Two signatures (r, s1) and (r, s2) with same r → same nonce k
h1 = int(sha256(msg1).hexdigest(), 16)
h2 = int(sha256(msg2).hexdigest(), 16)
n = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141  # secp256k1 order

k = ((h1 - h2) * pow(s1 - s2, -1, n)) % n
d = ((s1 * k - h1) * pow(r, -1, n)) % n  # private key
```

**Key insight:** Same `r` value across multiple ECDSA signatures means the nonce `k` was reused. This is the same class of bug that compromised the PlayStation 3 signing key. Always check for repeated `r` values in signature datasets.

**Detection:** Multiple ECDSA signatures with identical `r` component. Challenge mentions "nonce", "deterministic signing", or provides a signing oracle.

---

## Obfuscated Genus-1 Variety → Weierstrass + Hybrid BSGS/MOV/NFS (source: hxp 39C3 AlcoholicVariety)

**Trigger:** DLP-style challenge on a 10-coordinate projective embedding with degree-2 relations between pairs; group order factors into a small (~31-bit) prime and a medium (~63-bit) prime.
**Signals:** `.sage` challenge with coordinates `(x0..x9)` and constraint polynomials of total degree 2; group order with two clean prime factors of disparate size.
**Mechanic:** interpolate low-degree polynomials between coord pairs — variety is genus 1 in disguise; convert to Weierstrass form in Magma (`jInvariant`, `EllipticCurveFromjInvariant`). Split ECDLP via CRT: BSGS on the small factor, MOV (Weil pairing to `GF(p)`) + cado-nfs NFS on the large. Recovers the scalar that 10-dim coords hide.
Source: [affine.group/writeup/2024-12-hxp-AlcoholicVariety](http://affine.group/writeup/2024-12-hxp-AlcoholicVariety).

## Invalid-Point on py_ecc / Jacobian `Point` Without Curve Check (source: SekaiCTF 2025 Law and Order)

**Trigger:** homemade elliptic-curve class (py_ecc-style) with `add`/`double` in Jacobian coordinates but no on-curve check on inputs.
**Signals:** `class Point: def __add__(self, other): ...` with only field arithmetic, no `self.curve.is_on_curve(self)` assertion before use; `SECP`/`ED25519`-like constants.
**Mechanic:** submit points from a different curve whose order has small factors; Pohlig-Hellman on the small-order subgroup leaks the secret modulo `ℓ`. Aggregate via CRT. Works because Jacobian add/double only checks algebraic relations, not curve membership.



---

<!-- Source: exotic-crypto.md -->

# CTF Crypto - Exotic Algebraic Structures

## Table of Contents
- [Braid Group DH — Alexander Polynomial Multiplicativity (DiceCTF 2026)](#braid-group-dh--alexander-polynomial-multiplicativity-dicectf-2026)
- [Monotone Function Inversion with Partial Output](#monotone-function-inversion-with-partial-output)
- [Tropical Semiring Residuation Attack (BearCatCTF 2026)](#tropical-semiring-residuation-attack-bearcatctf-2026)

---

## Braid Group DH — Alexander Polynomial Multiplicativity (DiceCTF 2026)

**Pattern (Plane or Exchange):** Diffie-Hellman key exchange built over mathematical braids. Public keys are derived by connecting a private braid to public info, then scrambled with Reidemeister-like moves. Shared secret = `sha256(normalize(calculate(connect(my_priv, their_pub))))`. The `calculate()` function computes the Alexander polynomial of the braid.

**Protocol structure:**
```python
import sympy as sp
import hashlib

t = sp.Symbol('t')

def compose(p1, p2):
    return [p1[p2[i]] for i in range(len(p1))]

def inverse(p):
    inv = [0] * len(p)
    for i, j in enumerate(p):
        inv[j] = i
    return inv

def connect(g1, g2):
    """Concatenate two braids with a swap at the junction."""
    x1, o1 = g1
    x2, o2 = g2
    l = len(x1)
    new_x = list(x1) + [v + l for v in x2]
    new_o = list(o1) + [v + l for v in o2]
    # Swap at junction
    new_x[l-1], new_x[l] = new_x[l], new_x[l-1]
    return (new_x, new_o)

def sweep(ap):
    """Compute winding number matrix from arc presentation."""
    l = len(ap)
    current_row = [0] * l
    matrix = []
    for pair in ap:
        c1, c2 = sorted(pair)
        diff = pair[1] - pair[0]
        s = 1 if diff > 0 else (-1 if diff < 0 else 0)
        for c in range(c1, c2):
            current_row[c] += s
        matrix.append(list(current_row))
    return matrix

def mine(point):
    x, o = point
    return sweep([*zip(x, o)])

def calculate(point):
    """Compute Alexander polynomial from braid."""
    mat = sp.Matrix([[t**(-x) for x in y] for y in mine(point)])
    return mat.det(method='bareiss') * (1 - t)**(1 - len(point[0]))

def normalize(calculation):
    """Convert Laurent polynomial to standard form."""
    poly = sp.expand(sp.simplify(calculation))
    all_exp = [term.as_coeff_exponent(t)[1] for term in poly.as_ordered_terms()]
    min_exp = min(all_exp)
    poly = sp.expand(sp.simplify(poly * t**(-min_exp)))
    if poly.coeff(t, 0) < 0:
        poly *= -1
    return poly

# Key exchange:
# alice_pub = scramble(connect(pub_info, alice_priv), 1000)
# bob_pub = scramble(connect(pub_info, bob_priv), 1000)
# shared = sha256(str(normalize(calculate(connect(alice_priv, bob_pub)))))
```

**The fatal vulnerability — Alexander polynomial multiplicativity:**

The Alexander polynomial satisfies `Δ(β₁·β₂) = Δ(β₁) × Δ(β₂)` under braid concatenation. This makes the scheme abelian:

```python
# Eve computes shared secret from public values only:
calc_pub = normalize(calculate(pub_info))
calc_alice = normalize(calculate(alice_pub))
calc_bob = normalize(calculate(bob_pub))

# Recover Alice's private polynomial
calc_alice_priv = sp.cancel(calc_alice / calc_pub)  # exact division

# Shared secret = calc(alice_priv) * calc(bob_pub) = calc(bob_priv) * calc(alice_pub)
shared_poly = normalize(sp.expand(calc_alice_priv * calc_bob))
shared_hex = hashlib.sha256(str(shared_poly).encode()).hexdigest()

# Decrypt XOR stream cipher
key = bytes.fromhex(shared_hex)
while len(key) < len(ciphertext):
    key += hashlib.sha256(key).digest()
plaintext = bytes(a ^ b for a, b in zip(ciphertext, key))
```

**Computational trick for large matrices:**

Direct sympy Bareiss on rational-function matrices (e.g., 30×30 with entries `t^(-w)`) is extremely slow. Clear denominators first:

```python
# Winding numbers range from w_min to w_max (e.g., -1 to 5)
# Multiply all entries by t^w_max to get polynomial matrix
k = max(abs(w) for row in winding_matrix for w in row)
n = len(winding_matrix)

# Original: M[i][j] = t^(-w[i][j])
# Scaled:   M'[i][j] = t^(k - w[i][j])  (all non-negative powers)
mat_poly = sp.Matrix([[t**(k - w) for w in row] for row in winding_matrix])
det_scaled = mat_poly.det(method='bareiss')  # Much faster!

# Recover true determinant: det(M) = det(M') / t^(k*n)
det_true = sp.cancel(det_scaled / t**(k * n))
# Then: (1-t)^(n-1) divides det_true (topological property)
result = sp.cancel(det_true * (1 - t)**(1 - n))
```

**Validation — palindromic property:**
All valid Alexander polynomials are palindromic (coefficients read the same forwards and backwards). Use this as a sanity check on intermediate results:
```python
def is_palindromic(poly, var=t):
    coeffs = sp.Poly(poly, var).all_coeffs()
    return coeffs == coeffs[::-1]
```

**When to recognize:** Challenge mentions braids, knots, permutation pairs, winding numbers, Reidemeister moves, or "topological key exchange." The key mathematical insight is that the Alexander polynomial — while a powerful knot/braid invariant — is multiplicative, making it fundamentally unsuitable as a one-way function for Diffie-Hellman.

**Key lessons:**
- **Diffie-Hellman requires non-abelian hardness.** If the invariant used for the shared secret is multiplicative/commutative under the group operation, Eve can compute it from public values.
- **Scrambling (Reidemeister moves) doesn't help** — the Alexander polynomial is an invariant, so scrambled braids produce the same polynomial.
- **Large symbolic determinants** need the denominator-clearing trick: multiply by `t^k` to get polynomials, compute det, divide back.

**References:** DiceCTF 2026 "Plane or Exchange"

---

## Monotone Function Inversion with Partial Output

**Pattern:** A flag is converted to a real number, pushed through an invertible/monotone function (e.g., iterated map, spiral), then some output digits are masked/erased. Recover the masked digits to invert and get the flag.

**Identification:**
- Output is a high-precision decimal number with some digits replaced by `?`
- The transformation is smooth/monotone (invertible via root-finding)
- Flag format constrains the input to a narrow range
- Challenge hints like "brute won't cut it" or "binary search"

**Key insight:** For a monotone function `f`, knowing the flag format (e.g., `0xL4ugh{...}`) constrains the output to a tiny interval. Many "unknown" output digits are actually **fixed** across all valid inputs and can be determined immediately.

**Attack: Hierarchical Digit Recovery**

1. **Determine fixed digits:** Compute `f(flag_min)` and `f(flag_max)` for all valid flags. Digits that are identical in both outputs are fixed regardless of flag content.

2. **Sequential refinement:** Determine remaining unknown digits one at a time (largest contribution first). For each candidate value (0-9), invert `f` and check if the result is a valid flag (ASCII, correct format).

3. **Validation:** The correct digit produces readable ASCII text; wrong digits produce garbage bytes in the flag.

```python
import mpmath

# Match SageMath's RealField(N) precision exactly:
# RealField(256) = 256-bit MPFR mantissa
mpmath.mp.prec = 256  # BINARY precision (not decimal!)
# For decimal: mpmath.mp.dps = N sets decimal places

phi = (mpmath.mpf(1) + mpmath.sqrt(mpmath.mpf(5))) / 2

def forward(x0):
    """The challenge's transformation (e.g., iterated spiral)."""
    x = x0
    for i in range(iterations):
        r = mpmath.mpf(i) / mpmath.mpf(iterations)
        x = r * mpmath.sqrt(x*x + 1) + (1 - r) * (x + phi)
    return x

def invert(y_target, x_guess):
    """Invert via root-finding (Newton's method)."""
    def f(x0):
        return forward(x0) - y_target
    return mpmath.findroot(f, x_guess, tol=mpmath.mpf(10)**(-200))

# Hierarchical search: determine unknown digits sequentially
masked = "?7086013?3756162?51694057..."
unknown_positions = [0, 8, 16, 25, 33, ...]

# Step 1: Fix digits that are constant across all valid flags
# (compute forward for min/max valid flag, compare)

# Step 2: For each remaining unknown (largest positional weight first):
for pos in remaining_unknowns:
    for digit in range(10):
        # Set this digit, others to middle value (5)
        output_val = construct_number(known_digits | {pos: digit})
        x_inv = invert(output_val, x_guess=0.335)
        flag_int = int(x_inv * mpmath.power(10, flag_digits))
        flag_bytes = flag_int.to_bytes(30, 'big')

        # Check: starts with prefix? Ends with suffix? All ASCII?
        if is_valid_flag(flag_bytes):
            known_digits[pos] = digit
            break
```

**Why it works:** Each unknown digit affects a different decimal scale in the output number. The largest unknown (earliest position) shifts the inverted value by the most, determining several bytes of the flag. Fixing it and moving to the next unknown reveals more bytes. Total work: `10 * num_unknowns` inversions (linear, not exponential).

**Precision matching:** SageMath's `RealField(N)` uses MPFR with N-bit mantissa. In mpmath, set `mp.prec = N` (NOT `mp.dps`). The last few output digits are precision-sensitive and will only match with the correct binary precision.

**Derivative analysis:** For the spiral-type map `x → r*sqrt(x²+1) + (1-r)*(x+φ)`, the per-step derivative is `r*x/sqrt(x²+1) + (1-r) ≈ 1`, so the total derivative stays near 1 across all 81 iterations. This means precision is preserved through inversion — 67 known output digits give ~67 digits of input precision.

**References:** 0xL4ugh CTF "SpiralFloats"

---

## Tropical Semiring Residuation Attack (BearCatCTF 2026)

**Pattern (Tropped):** Diffie-Hellman key exchange using tropical matrices (min-plus algebra). Per-character shared secret XOR'd with encrypted flag.

**Tropical algebra:**
- Addition = `min(a, b)`
- Multiplication = `a + b`
- Matrix multiply: `(A*B)[i,j] = min_k(A[i,k] + B[k,j])`

**Tropical residuation recovers shared secret from public data:**
```python
def tropical_residuate(M, Mb, aM, n):
    """Recover shared secret from public matrices.
    M = public matrix, Mb = M*b (Bob's public), aM = a*M (Alice's public)
    """
    # Right residual: b*[j] = max_i(Mb[i] - M[i][j])
    b_star = [max(Mb[i] - M[i][j] for i in range(n)) for j in range(n)]
    # Shared secret: aMb = min_j(aM[j] + b*[j])
    aMb = min(aM[j] + b_star[j] for j in range(n))
    return aMb

# Decrypt per-character: key = aMb % 32; plaintext = key ^ ciphertext
for i, enc_char in enumerate(encrypted):
    key = shared_secret % 32
    plaintext_char = chr(key ^ ord(enc_char))
```

**Key insight:** Tropical DH is broken because the min-plus semiring lacks cancellation — given `M` and `M*b`, the "residual" `b*` can be computed directly via `max(Mb[i] - M[i][j])`. Unlike standard DH where recovering `b` from `g^b` is hard, tropical residuation recovers enough of `b`'s effect to compute the shared secret. This makes tropical matrix DH insecure for any matrix size.

**Detection:** Challenge mentions "tropical", "min-plus", "exotic algebra", or defines custom matrix multiplication using `min` and `+`.

---

## ePrint-Scheme-Killer Linear-Algebra (source: hxp 39C3 Linear-algebra-vs-ePrint)

**Trigger:** challenge quotes an obscure ePrint paper (2019/717, 2024/792, 2025/007 …) introducing "homomorphism learning", "entropic operator", or "Stickel variation"; scheme advertises post-DLP security.
**Signals:** references to `homomorphism_learning.pdf`, bilinear "mixing" functions, claimed reduction to a non-standard assumption.
**Mechanic:** construct an auxiliary homomorphism `π` with `ker(π) ∩ ker(ψ) = {0}`; solve a linear system over the generators to recover the message without ever doing DLP. For bilinear-mix schemes: exploit separability,
`mix((a,b),(u,v)) = mix((a,b),(c,d)) · mix((1,1),(u,v)) / mix((1,1),(c,d))`
which collapses the DH assumption. Generic recipe: always verify that the scheme genuinely needs its stated hard problem — linear-algebra often bypasses it.

## CSIDH / Group-Action KEM Sign-Leak Oracle (source: SekaiCTF 2025 Alter Ego)

**Trigger:** isogeny-based KEM exposing `group_action(e, x)` for attacker-controlled `x ∈ {±1}`; exponent vector `e ∈ ℤ^n`.
**Signals:** CSIDH/CSURF code, `ideal_to_isogeny`, exponent vector stored plainly.
**Mechanic:** feeding `-1` reduces primes in `e`'s factorisation depending on the sign of each coordinate. Observe which primes disappear ⇒ infer sign bits of `e` one by one ⇒ find the negative counterpart that still validates. Key recovery in `O(n)` oracle calls.

## FCSC 2025 Post-Quantum: Kzber (Kyber) + UOV "Vinegar" (source: hackropole.fr)

**Trigger:** challenge files with Kyber parameters (`n=256`, `q=3329`, module rank 2/3/4) or UOV oil/vinegar split; filenames `pk`, `sk`, `ct`.
**Signals:** `polyvec.h5`/`ciphertext.bin` + README citing NIST PQC round; or vinegar variables with explicit rank.
**Mechanic:** Kyber path — decapsulation-failure oracle (Ravi et al.) or implicit-rejection timing. UOV path — rank analysis / MinRank over the central map; typically reduces recovery cost to `O(q^r)` with small `r`. Run Magma `MinRank` or Sage `HFE` helper.
Source: [hackropole.fr/fr/fcsc2025/](https://hackropole.fr/fr/fcsc2025/).

## Falcon Floating-Point Leakage on Sign Verification (source: 2025-era PQ CTFs, CCS 2024 Falcon papers)

**Trigger:** Falcon-512 / Falcon-1024 signing or signature verification reachable; reference implementation uses `double` / `fpu` math; verifier bounds use `sqrt(norm2) < β`.
**Signals:** `falcon-ref.c` compiled with `-lm`; signature pairs `(r, s)` emitted with varying `r`; check code calls `vrfy_norm2` or manipulates `int64_t` from `double`.
**Mechanic:** the Falcon fast FP Gaussian sampler leaks via FP-rounding subnormals. Collect ~10^5 signatures; recover the signing key's secret lattice basis via `f, g, F, G` relations + Howgrave-Graham/learning-with-rounding CVP. Alternate path: if the verifier casts `double → int64_t` without explicit bound, mount an "off-by-eps" forgery where `norm2 = β²` boundary flips due to FP rounding — craft a signature whose FP norm is just under β but integer norm is over. Library: `pqs` + Sage prototype in CRYSTALS tools repo.

## ML-DSA (Dilithium) Hint-Leak via Public-Key Compression (source: 2026 PQC challenges)

**Trigger:** signature scheme is ML-DSA (NIST FIPS 204) or legacy Dilithium; challenge provides "hints" `h` alongside `(c, z)` triples.
**Signals:** `h` has Hamming weight ≤ ω (80 for DILITHIUM2); parameters `(q, d, γ1, γ2)` match ML-DSA; a filter reveals `z` components bounded by `γ1 − β`.
**Mechanic:** each hint bit reveals one parity of `HighBits(⟨a_i, y⟩ + c·s1)`. With enough signatures, build a lattice `B = [A | qI]` augmented by hint constraints; short-vector recovery via BKZ-40 exposes `s1`, then `s2` follows. For constrained-hint variants (force all hints to 0), the scheme collapses to an LWE instance with biased noise — solved by lattice + primal attack with effective dimension `n - ω`.

## SLH-DSA (SPHINCS+) Signature-Stealing via Tree Reuse (source: 2026 PQC challenges)

**Trigger:** SPHINCS+ or ML-DSA-derived stateful-ish signing with a bug that reuses the same FORS (Forest Of Random Subsets) instance twice.
**Signals:** server stores a counter that can be replayed (file-based, not atomic); two signatures derivable from the same `(pk, idx)` with different messages.
**Mechanic:** one-time-signatures in FORS guarantee security ONLY under single-use. If idx repeats, pair `(msg_1, sig_1)` and `(msg_2, sig_2)` together reveal enough tree leaves to forge a third signature on a chosen message. Equivalent HORS-then-WOTS attack exists in WOTS+ — signing two messages whose hashes share a prefix leaks chained WOTS nodes. Counter-grep: any filesystem-backed signer without atomic counter rename + `fsync` is vulnerable.

## Invalid-Curve Attacks on Post-Quantum KEM Implementations (CSIDH / CTIDH)

**Trigger:** isogeny-based KEM (CSIDH-512, CTIDH, SeaSign) with public key on attacker-supplied curve parameters.
**Signals:** API accepts Montgomery `A`-coefficient directly; no twist-check; `class_group_action(A, k)` returns deterministically.
**Mechanic:** send a CSIDH key on a twist / Fp-rational subgroup of smooth order. Deterministic action reveals `k mod ℓ_i` for each tiny prime `ℓ_i` via Pohlig-Hellman on the subgroup. Over ~200 queries, CRT-combine to full `k`. Defense: constant-time twist check (`A² - 4` square/non-square test) before every action.



---

<!-- Source: historical.md -->

# CTF Crypto - Historical Ciphers

## Table of Contents
- [Lorenz SZ40/42 (Tunny) Cipher](#lorenz-sz4042-tunny-cipher)
- [Book Cipher Brute Force (Nullcon 2026)](#book-cipher-brute-force-nullcon-2026)

---

## Lorenz SZ40/42 (Tunny) Cipher

The Lorenz cipher uses 12 wheels to encrypt 5-bit ITA2/Baudot characters. With known plaintext, a structured attack recovers all wheel settings.

**Machine structure:**
- 5 χ (chi) wheels: periods 41, 31, 29, 26, 23 — advance every step
- 5 Ψ (psi) wheels: periods 43, 47, 51, 53, 59 — advance only when μ37=1
- μ61 wheel: period 61 — advances every step, controls μ37 stepping
- μ37 wheel: period 37 — advances only when μ61=1, controls Ψ stepping

**Encryption:** `ciphertext[i] = plaintext[i] XOR chi[i] XOR psi[i]` (per 5-bit character)

**CRITICAL: The delta (Δ) approach is the fundamental technique:**

```python
# Step 1: Get keystream from known plaintext
key_stream = [pt[i] ^ ct[i] for i in range(N)]

# Step 2: Compute delta keystream (THE key insight)
delta_k = [key_stream[i] ^ key_stream[i+1] for i in range(N-1)]
# delta_k = delta_chi XOR delta_psi
# Since psi only moves ~25% of the time, delta_k BIASES toward delta_chi

# Step 3: Recover delta_chi via majority vote at each wheel position
# Assume wheels start at position 1
for bit in range(5):
    P = chi_periods[bit]  # [41, 31, 29, 26, 23]
    delta_chi = []
    for phase in range(P):
        # Collect all delta_k values at this wheel phase
        vals = [delta_k_bit[i] for i in range(phase, len(delta_k_bit), P)]
        delta_chi.append(1 if sum(vals) > len(vals)/2 else 0)

# Step 4: Integrate delta_chi to get chi (2 candidates per wheel, start 0 or 1)
chi = [start]  # start = 0 or 1
for i in range(P-1):
    chi.append(chi[-1] ^ delta_chi[i])
# Circular consistency: chi[0] ^ chi[-1] should equal delta_chi[P-1]

# Step 5: Subtract chi from keystream to get psi contribution
# Identify when psi steps: delta_psi = delta_k XOR delta_chi
# When ALL 5 bits of delta_psi are 0 → μ37 was off (psi didn't step)
# (Statistically very rare for all 5 cams to not change when stepping)

# Step 6: From stepping pattern, determine μ61 (period 61)
# μ61[pos] = 1 when we see psi resume stepping after being stopped

# Step 7: Cross-reference to get μ37 (period 37)
# μ37 position advances only when μ61=1

# Step 8: Determine psi wheels from delta_psi values when stepping occurs
# Look for repeating patterns with periods 43, 47, 51, 53, 59

# Step 9: Brute force remaining ambiguity
# Total candidates: 2^5 (chi) × 2^5 (psi) × 61×37 (μ positions) = 2,313,472
# Trivially brutable - decrypt and check if known plaintext matches
```

**Common mistakes to avoid:**
- Do NOT assume psi is "period 2" or just alternating — it has real wheels with periods 43-59
- Do NOT spend time on statistical period-finding for the motor — just use the structured Δ approach
- Do NOT try LFSR analysis on the step sequence — the stepping is from mechanical wheels, not LFSRs
- The "step rate" (~35%) is a consequence of μ37 being on ~50% and μ61 on ~50% = ~25% psi stepping
- Always assume standard wheel periods unless evidence says otherwise
- Total brute force space is tiny (<3M) — don't over-optimize

**ITA2/Baudot encoding (5-bit):**
```python
# Standard ITA2 mapping used in Lorenz challenges
char_to_code = {
    'A': 24, 'B': 19, 'C': 14, 'D': 18, 'E': 16, 'F': 22, 'G': 11,
    'H': 5,  'I': 12, 'J': 26, 'K': 30, 'L': 9,  'M': 7,  'N': 6,
    'O': 3,  'P': 13, 'Q': 29, 'R': 10, 'S': 20, 'T': 1,  'U': 28,
    'V': 15, 'W': 25, 'X': 23, 'Y': 21, 'Z': 17,
    '9': 4,  '5': 27, '8': 31, '3': 8,  '4': 2,  '/': 0,
}
# Code 27 = FIGS shift, Code 31 = LTRS shift
```

---

## Book Cipher Brute Force (Nullcon 2026)

**Pattern (Booking Key):** Book cipher encodes password as list of "steps forward" in reference text.

**Key insight:** Charset constraint drastically reduces candidate starting positions:
```python
def decode_book_cipher(cipher_distances, book_text, valid_chars):
    """Brute-force starting position; filter by charset."""
    candidates = []
    for start_key in range(len(book_text)):
        pos = start_key
        password = []
        valid = True
        for dist in cipher_distances:
            pos = (pos + dist) % len(book_text)
            ch = book_text[pos]
            if ch not in valid_chars:
                valid = False
                break
            password.append(ch)
        if valid:
            candidates.append((start_key, ''.join(password)))
    return candidates  # Typically 3-4 candidates out of ~56k positions
```



---

<!-- Source: modern-ciphers-2.md -->

# CTF Crypto - Modern Ciphers (2024-2026)

Modern AEAD / MAC / S-box / differential attacks from 2024-2026. For the canonical toolbox (CBC padding oracle, Bleichenbacher, LFSR, length extension), see [modern-ciphers.md](modern-ciphers.md).

## Table of Contents
- [Non-Permutation S-box Collision Attack (Nullcon 2026)](#non-permutation-s-box-collision-attack)
- [LCG Partial Output Recovery (0xFun 2026)](#lcg-partial-output-recovery-0xfun-2026)
- [Affine Cipher over Composite Modulus (Nullcon 2026)](#affine-cipher-over-composite-modulus-nullcon-2026)
- [AES-GCM with Derived Keys (EHAX 2026)](#aes-gcm-with-derived-keys-ehax-2026)
- [Ascon-like Reduced-Round Differential Cryptanalysis (srdnlenCTF 2026)](#ascon-like-reduced-round-differential-cryptanalysis-srdnlenctf-2026)
- [Custom Linear MAC Forgery (Nullcon 2026)](#custom-linear-mac-forgery-nullcon-2026)
- [Shamir t-of-n with Roots-of-Unity Evaluation Points → FFT Recovery (SekaiCTF 2025 ssss)](#shamir-t-of-n-with-roots-of-unity-evaluation-points--fft-recovery-source-sekaictf-2025-ssss)
- [Single-Round AES Linear Inversion (HTB University 2025 Disguised)](#single-round-aes-linear-inversion-source-htb-university-2025-disguised)

---

## Non-Permutation S-box Collision Attack

**Pattern (Tetraes, Nullcon 2026):** Custom AES-like cipher with S-box collisions.

**Detection:** `len(set(sbox)) < 256` means collisions exist. Find collision pairs and their XOR delta.

**Attack:** For each key byte, try 256 plaintexts differing by delta. When `ct1 == ct2`, S-box input was in collision set. 2-way ambiguity per byte, 2^16 brute-force. Total: 4,097 oracle queries.

See [advanced-math.md](advanced-math.md) for full S-box collision analysis code.

---

## LCG Partial Output Recovery (0xFun 2026)

**Known parameters:** If LCG (Linear Congruential Generator) constants (M, A, C) are known and output is `state mod N`, iterate by N through modulus to find state:
```python
# output = state % N, state = (A * prev + C) % M
for candidate in range(output, M, N):
    # Check if candidate is consistent with next output
    next_state = (A * candidate + C) % M
    if next_state % N == next_output:
        print(f"State: {candidate}")
```

**Upper bits only (e.g., upper 32 of 64):** Brute-force lower 32 bits:
```python
for low in range(2**32):
    state = (observed_upper << 32) | low
    next_state = (A * state + C) % M
    if (next_state >> 32) == next_observed_upper:
        print(f"Full state: {state}")
```

---

## Affine Cipher over Composite Modulus (Nullcon 2026)

Affine encryption `c = A*x + b (mod M)` with composite M: split into prime factor fields, invert independently, CRT recombine. See [advanced-math.md](advanced-math.md#affine-cipher-over-non-prime-modulus-nullcon-2026) for full chosen-plaintext key recovery and implementation.

---

## AES-GCM with Derived Keys (EHAX 2026)

**Pattern:** Final decryption step after recovering a secret (e.g., from LWE, key exchange). Session nonce and AES key derived via SHA-256 hashing of the recovered secret.

```python
import hashlib
from Cryptodome.Cipher import AES

# Common key derivation chain:
# 1. Recover secret bytes (s_bytes) from crypto challenge
# 2. Unwrap session nonce: nonce = wrapped_nonce XOR SHA256(s_bytes)[:nonce_len]
# 3. Derive AES key: key = SHA256(s_bytes + session_nonce)
# 4. Decrypt AES-GCM

def decrypt_with_derived_key(s_bytes, wrapped_nonce, ciphertext, aes_nonce, tag, nonce_len=16):
    secret_hash = hashlib.sha256(s_bytes).digest()
    session_nonce = bytes(a ^ b for a, b in zip(wrapped_nonce, secret_hash[:nonce_len]))
    aes_key = hashlib.sha256(s_bytes + session_nonce).digest()
    cipher = AES.new(aes_key, AES.MODE_GCM, nonce=aes_nonce)
    return cipher.decrypt_and_verify(ciphertext, tag)
```

**Key insight:** When AES-GCM authentication fails (`ValueError: MAC check failed`), the derived key is wrong — usually means the upstream secret recovery was incorrect or endianness is swapped.

---

## Ascon-like Reduced-Round Differential Cryptanalysis (srdnlenCTF 2026)

**Pattern (Lightweight):** 4-round Ascon-like permutation with reduced diffusion. Key-dependent biases in output-bit differentials allow key recovery via chosen input differences.

**Attack:**
1. Reproduce the permutation exactly (critical: post-S-box x4 assignment order matters)
2. Invert the linear layer of x0 using a precomputed 64×64 GF(2) inverse matrix
3. For each bit position i, query with `diff = (1<<i, 1<<i)` across multiple samples
4. Measure empirical biases at output bits `j1 = (i+1) mod 64` and `j2 = (i+14) mod 64`
5. Classify key bits `(k0[i], k1[i])` via centroid-based clustering with sign-pattern mask
6. Verify candidate key in-session; refine low-margin bits with additional samples

**GF(2) linear layer inversion:**
```python
def build_inverse(shifts=(19, 28)):
    """Construct GF(2) inverse matrix for Ascon-like linear layer: x ^= rot(x,19) ^ rot(x,28)."""
    # Build 64x64 matrix over GF(2)
    M = [[0]*64 for _ in range(64)]
    for out_bit in range(64):
        M[out_bit][out_bit] = 1
        for shift in shifts:
            M[out_bit][(out_bit + shift) % 64] ^= 1
    # Gaussian elimination to find inverse
    aug = [row + [1 if i == j else 0 for j in range(64)] for i, row in enumerate(M)]
    for col in range(64):
        pivot = next(r for r in range(col, 64) if aug[r][col])
        aug[col], aug[pivot] = aug[pivot], aug[col]
        for r in range(64):
            if r != col and aug[r][col]:
                aug[r] = [a ^ b for a, b in zip(aug[r], aug[col])]
    return [row[64:] for row in aug]
```

**Centroid clustering for key classification:**
```python
# For each bit position, measure bias at two output positions
# 4 possible (k0[i], k1[i]) pairs → 4 centroid patterns
# Uses sign-pattern mask CMASK=0x73 to account for bit-position-dependent behavior
# Classify by minimum Euclidean distance in 2D bias space
CMASK = 0x73
for i in range(64):
    bias_j1, bias_j2 = measure_biases(i, samples)
    mask_bit = (CMASK >> (i % 8)) & 1
    centroids = centroid_table[mask_bit]  # Precomputed per-position centroids
    k0_bit, k1_bit = min(range(4), key=lambda c: euclidean_dist(
        (bias_j1, bias_j2), centroids[c]))
```

**Key insight:** Reduced-round lightweight ciphers (Ascon, GIFT, etc.) have exploitable biases when the number of rounds is insufficient for full diffusion. The linear layer's inverse can be computed algebraically, and differential biases measured across chosen-plaintext queries reveal individual key bits. This is practical even with noisy measurements if you collect enough samples.

---

## Custom Linear MAC Forgery (Nullcon 2026)

**Pattern (Pasty):** Server signs paste IDs with a custom SHA-256-based construction. The signature is linear in three 8-byte secret blocks derived from the key.

**Structure:** For each 8-byte output block `i`:
- `selector = SHA256(id)[i*8] % 3` → chooses which secret block to use
- `out[i] = hash_block[i] XOR secret[selector] XOR chain[i-1]`

**Recovery:** Create ~10 pastes to collect `(id, sig)` pairs. Each pair reveals `secret[selector]` for 4 selectors. With ~4-5 pairs, all 3 secret blocks are recovered. Then forge for target ID.

**Key insight:** Linearity in custom crypto constructions (XOR-based signing) makes them trivially forgeable. Always check if the MAC has the property: knowing the secret components lets you compute valid signatures for arbitrary inputs.

---

## Shamir t-of-n with Roots-of-Unity Evaluation Points → FFT Recovery (source: SekaiCTF 2025 ssss)

**Trigger:** Shamir secret-sharing where the chosen evaluation points are `t`-th roots of unity `ω^i` in `F_p` for `ω` of order `t`.
**Signals:** only `t` shares are issued (not `t+1`); evaluation points obey `x_i^t = 1`.
**Mechanic:** DFT property collapses the polynomial sum — `Σ_{i=0}^{t-1} P(ω^i) · ω^{-i·k} = t · (a_k + a_{k+t})` mod `p`. So `t` evaluations suffice to reconstruct (modulo the wrap-around). When `deg(P) < 2t`, this is exact; apply inverse FFT to get all coefficients and read the secret `P(0) = a_0`.

## Single-Round AES Linear Inversion (source: HTB University 2025 Disguised)

**Trigger:** custom AES with `Nr = 1` (or a homemade `aes_one_round(p, k)` primitive); known plaintext/ciphertext pair.
**Signals:** `Nr = 1` literal in code, or only one `AddRoundKey → SubBytes → ShiftRows → MixColumns → AddRoundKey` chain.
**Mechanic:** with a single round, the transformation is invertible from one PT/CT pair — invert `MixColumns` (linear), apply inverse `ShiftRows`, invert `SubBytes` via the S-box LUT, XOR against PT to get `K0`; key schedule recovers `K1`. Any "simplified AES" should be checked this way before attempting LC/DC.

## KDF Iteration Decay to Null Key (source: 404CTF 2025 Dérive dans l'espace)

**Trigger:** custom key-derivation function called `N` times where state shrinks each round (hash truncation, repeated XOR-fold, `k = h(k)[:len(k)-1]`); AES/ChaCha packets from a PCAP, >90% decrypt identically with `key = b"\x00" * keylen`.
**Signals:** KDF loop body visibly reduces entropy (e.g. `key = sha256(key)[:16] & mask` with zeroing mask, or `key ^= key >> 1; key &= key - 1`); PCAP has hundreds of short UDP packets all with same IV layout; `decrypt(pkt, b"\x00"*16) == plausible_plaintext` for any sample.
**Mechanic:** after enough rounds, the KDF's fixed point is `0`. Attackers do **not** need to break the KDF — just try the zero key on every packet. PNG magic (`89 50 4e 47 0d 0a 1a 0a`) or `\x1f\x8b` gzip magic in the plaintext is the giveaway.
```python
# Fast scan: decrypt every packet with the null key, look for magic bytes
from Crypto.Cipher import AES
MAGICS = [b"\x89PNG", b"\x1f\x8b", b"PK\x03\x04", b"RIFF", b"%PDF"]
for pkt in packets:
    ct, iv = pkt[:-16], pkt[-16:]
    pt = AES.new(b"\x00"*16, AES.MODE_CBC, iv).decrypt(ct)
    if any(m in pt for m in MAGICS):
        carve(pt)          # reassemble file from consecutive hits
```
**Why it fires anywhere:** every "homemade ratcheting key" primitive is vulnerable if the ratchet isn't bijective over a full-entropy state. Always try `key = 0` on the suspected ciphertexts before reversing the KDF.

## Extended-Block AES via Python Negative Indexing (source: Google CTF 2025 Underhanded)

**Trigger:** "underhanded" AES reference in Python where `shift_rows` and `mix_columns` iterate with hardcoded indices like `m[-8]`, `m[-4]`, `m[-1]` instead of `m[i + row*4]`; cipher accepts messages longer than 16 bytes without chaining.
**Signals:** grep the source for `[-` inside `shift_rows`/`mix_columns`; absence of an explicit `assert len(block) == 16`; the function returns `len(pt)` bytes of ciphertext in one shot.
**Mechanic:** Python's `m[-8]` wraps to `len(m)-8`. For a 32+ byte input, the "second column" of the state is actually a byte from a later column in the previous round's output, producing a **linear relation** between distant ciphertext bytes that only involves round-key bytes:
```
c[8] ⊕ c[n-8] = k10[8] ⊕ k10[r]          # after the last AddRoundKey
```
Each long-message encryption leaks one such relation per overflowed index. With 4-6 oracle queries on carefully sized inputs, you recover the last round key `K10`; then run key schedule backwards. A 24-bit + 16-bit meet-in-the-middle on the first 6 rounds finishes the key in ~5 min.
**Writeup principle:** whenever a crypto primitive is "extended" to variable length in an ad-hoc way, check for negative indices, integer wraparound in pointer arithmetic, or unsigned/signed confusion in block counters. These are the 3 classical underhanded crypto mistakes.

## bcrypt 72-Byte Truncation → Merkle-Leaf Collision (source: Google CTF 2025 Merkurated)

**Trigger:** Merkle tree (deposit / proof-of-reserves / airdrop) where leaves are `bcrypt(salt_fixed, user_value || aux_data)`; `len(user_value || aux_data)` can exceed 72 bytes.
**Signals:** `bcrypt.hashpw` or `py_bcrypt` in code on a user-controlled field; fixed salt (constant or deterministic from tree root); variable-length `value` field; proof verification re-hashes the leaf with `bcrypt` and checks tree path.
**Mechanic:** bcrypt silently truncates input to 72 bytes. Build two leaves `A = pad72 || "VALUE=10**9"` and `B = pad72 || "VALUE=10**18"` where the first 72 bytes are identical — they hash to the **same** bcrypt output. Commit tree with leaf `A` (small value, passes balance checks), later present the proof with leaf `B` claiming the large value.
```python
# Collision generator — find a 64-char suffix whose first 72 bytes match a target leaf
target = bcrypt.hashpw(desired_small_leaf, SALT)
for _ in range(2**14):
    candidate = prefix_72B + random_suffix()      # suffix ignored by bcrypt
    if bcrypt.hashpw(candidate, SALT) == target:  # always true modulo the first 72B
        submit_proof(candidate, claimed_value=HUGE)
```
**Generalizes to:** any hash with input-length cap (bcrypt 72, classic DES `crypt` 8, MySQL `OLD_PASSWORD` 8, LANMAN 14) used in an authentication or Merkle context where the trailing bytes carry semantic weight.



---

<!-- Source: modern-ciphers.md -->

# CTF Crypto - Modern Cipher Attacks

## Table of Contents
- [AES-CFB-8 Static IV State Forging](#aes-cfb-8-static-iv-state-forging)
- [ECB Pattern Leakage on Images](#ecb-pattern-leakage-on-images)
- [Padding Oracle Attack](#padding-oracle-attack)
- [CBC-MAC vs OFB-MAC Vulnerability](#cbc-mac-vs-ofb-mac-vulnerability)
- [Weak Hash Functions / GF(2) Gaussian Elimination](#weak-hash-functions--gf2-gaussian-elimination)
- [CBC Padding Oracle Attack](#cbc-padding-oracle-attack)
- [Bleichenbacher / PKCS#1 v1.5 RSA Padding Oracle](#bleichenbacher--pkcs1-v15-rsa-padding-oracle)
- [Birthday Attack / Meet-in-the-Middle](#birthday-attack--meet-in-the-middle)
- [LFSR Stream Cipher Attacks](#lfsr-stream-cipher-attacks)
  - [Berlekamp-Massey Algorithm](#berlekamp-massey-algorithm)
  - [Correlation Attack](#correlation-attack)
  - [Known-Plaintext on LFSR Keystream](#known-plaintext-on-lfsr-keystream)
  - [Galois vs Fibonacci LFSR](#galois-vs-fibonacci-lfsr)
  - [Common LFSR Lengths and Polynomials](#common-lfsr-lengths-and-polynomials)
- [CRC32 Collision-Based Signature Forgery (iCTF 2013)](#crc32-collision-based-signature-forgery-ictf-2013)
- [Blum-Goldwasser Bit-Extension Oracle (PlaidCTF 2013)](#blum-goldwasser-bit-extension-oracle-plaidctf-2013)
- [Hash Length Extension Attack (PlaidCTF 2014)](#hash-length-extension-attack-plaidctf-2014)
- [Compression Oracle / CRIME-Style Attack (BCTF 2015)](#compression-oracle--crime-style-attack-bctf-2015)
- [RC4 Second-Byte Bias Distinguisher (Hackover CTF 2015)](#rc4-second-byte-bias-distinguisher-hackover-ctf-2015)

For 2024-2026 era techniques (S-box collision, AES-GCM, Ascon differential, linear MAC, FFT Shamir), see [modern-ciphers-2.md](modern-ciphers-2.md).

---

## AES-CFB-8 Static IV State Forging

**Pattern (Cleverly Forging Breaks):** AES-CFB with 8-bit feedback and reused IV allows state reconstruction.

**Key insight:** After encrypting 16 known bytes, the AES internal shift register state is fully determined by those ciphertext bytes. Forge new ciphertexts by continuing encryption from known state.

---

## ECB Pattern Leakage on Images

**Pattern (Electronic Christmas Book):** AES-ECB on BMP/image data preserves visual patterns.

**Exploitation:** Identical plaintext blocks produce identical ciphertext blocks, revealing image structure even when encrypted. Rearrange or identify patterns visually.

---

## Padding Oracle Attack

**Pattern (The Seer):** Server reveals whether decrypted padding is valid.

**Byte-by-byte decryption:**
```python
def decrypt_byte(block, prev_block, position, oracle, known):
    """known = bytearray(16) tracking recovered intermediate bytes for this block."""
    for guess in range(256):
        modified = bytearray(prev_block)
        # Set known bytes to produce valid padding
        pad_value = 16 - position
        for j in range(position + 1, 16):
            modified[j] = known[j] ^ pad_value
        modified[position] = guess
        if oracle(bytes(modified) + block):
            return guess ^ pad_value
```

---

## CBC-MAC vs OFB-MAC Vulnerability

OFB mode creates a keystream that can be XORed for signature forgery.

**Attack:** If you have signature for known plaintext P1, forge for P2:
```text
new_sig = known_sig XOR block2_of_P1 XOR block2_of_P2
```

**Important:** Don't forget PKCS#7 padding in calculations! Small bruteforce space? Just try all combinations (e.g., 100 for 2 unknown digits).

---

## Weak Hash Functions / GF(2) Gaussian Elimination

Linear permutations (only XOR, rotations) are algebraically attackable. Build transformation matrix and solve over GF(2).

```python
import numpy as np

def solve_gf2(A, b):
    """Solve Ax = b over GF(2)."""
    m, n = A.shape
    Aug = np.hstack([A, b.reshape(-1, 1)]) % 2
    pivot_cols, row = [], 0
    for col in range(n):
        pivot = next((r for r in range(row, m) if Aug[r, col]), None)
        if pivot is None: continue
        Aug[[row, pivot]] = Aug[[pivot, row]]
        for r in range(m):
            if r != row and Aug[r, col]: Aug[r] = (Aug[r] + Aug[row]) % 2
        pivot_cols.append((row, col)); row += 1
    if any(Aug[r, -1] for r in range(row, m)): return None
    x = np.zeros(n, dtype=np.uint8)
    for r, c in reversed(pivot_cols):
        x[c] = Aug[r, -1] ^ sum(Aug[r, c2] * x[c2] for c2 in range(c+1, n)) % 2
    return x
```

---

## CBC Padding Oracle Attack

**Pattern:** Server reveals whether CBC-mode ciphertext has valid PKCS#7 padding (via error messages, timing, or status codes). Decrypt any ciphertext block-by-block without the key.

```python
from pwn import *

def padding_oracle(iv, ct):
    """Returns True if server accepts padding."""
    resp = requests.post(URL, data={'iv': iv.hex(), 'ct': ct.hex()})
    return 'padding' not in resp.text.lower()  # or check status code

def decrypt_block(prev_block, target_block):
    """Decrypt one 16-byte block using padding oracle."""
    intermediate = bytearray(16)
    plaintext = bytearray(16)

    for byte_pos in range(15, -1, -1):
        pad_val = 16 - byte_pos
        # Set already-known bytes to produce correct padding
        crafted = bytearray(16)
        for k in range(byte_pos + 1, 16):
            crafted[k] = intermediate[k] ^ pad_val

        for guess in range(256):
            crafted[byte_pos] = guess
            if padding_oracle(bytes(crafted), target_block):
                intermediate[byte_pos] = guess ^ pad_val
                plaintext[byte_pos] = intermediate[byte_pos] ^ prev_block[byte_pos]
                break

    return bytes(plaintext)
```

**Tools:**
```bash
# PadBuster — automated padding oracle exploitation
padbuster http://target/decrypt.php ENCRYPTED_B64 16 \
  -encoding 0 -error "Invalid padding"

# Python: pip install padding-oracle
from padding_oracle import PaddingOracle
oracle = PaddingOracle(block_size=16, oracle_fn=check_padding)
plaintext = oracle.decrypt(ciphertext, iv=iv)
```

**Key insight:** The oracle only needs to distinguish "valid padding" from "invalid padding." This can be a different HTTP status code, error message, response time, or even whether the application processes the request further. A single bit of information per query is sufficient. Decryption requires at most 256 x 16 = 4096 queries per block.

**Detection:** CBC mode encryption + any distinguishable behavior difference on padding errors. Common in cookie encryption, token systems, and encrypted API parameters.

---

## Bleichenbacher / PKCS#1 v1.5 RSA Padding Oracle

**Pattern:** RSA encryption with PKCS#1 v1.5 padding where the server reveals whether decrypted plaintext has valid `0x00 0x02` prefix. Adaptive chosen-ciphertext attack recovers the plaintext.

```python
import gmpy2

def bleichenbacher_oracle(c, n, e):
    """Returns True if RSA decryption has valid PKCS#1 v1.5 padding (0x00 0x02 prefix)."""
    resp = send_to_server(c)
    return resp.status_code != 400  # Server returns 400 on bad padding

def bleichenbacher_attack(c0, n, e, oracle, k):
    """
    c0: target ciphertext (integer)
    k: byte length of modulus (e.g., 256 for RSA-2048)
    """
    B = pow(2, 8 * (k - 2))

    # Step 1: Start with s1 = ceil(n / 3B)
    s = (n + 3 * B - 1) // (3 * B)

    # Step 2: Search for s where oracle(c0 * s^e mod n) is True
    while True:
        c_prime = (c0 * pow(s, e, n)) % n
        if oracle(c_prime, n, e):
            break
        s += 1

    # Step 3: Narrow interval [a, b] using s values
    # Repeat: find new s, narrow interval, until a == b
    # When interval collapses, plaintext = a * modinv(s, n) % n
    # (Full implementation requires interval tracking — use existing tools)
```

**Tools:**
```bash
# ROBOT attack scanner (modern Bleichenbacher variant)
python3 robot-detect.py -H target.com

# TLS-Attacker framework
java -jar TLS-Attacker.jar -connect target:443 -workflow_type BLEICHENBACHER
```

**Key insight:** The attack is adaptive — each oracle response narrows the range of possible plaintexts. Typically requires ~10,000 oracle queries for RSA-2048. The ROBOT attack (Return Of Bleichenbacher's Oracle Threat) showed this affects modern TLS implementations through subtle timing differences. Any server that distinguishes "bad padding" from "bad content" is vulnerable.

---

## Birthday Attack / Meet-in-the-Middle

**Pattern:** Find collisions in hash functions or MACs using the birthday paradox. With an n-bit hash, expect a collision after ~2^(n/2) random inputs.

```python
import hashlib, os

def birthday_collision(hash_fn, output_bits, prefix=b''):
    """Find two inputs with the same truncated hash."""
    target_bytes = output_bits // 8
    seen = {}

    while True:
        msg = prefix + os.urandom(16)
        h = hash_fn(msg).digest()[:target_bytes]
        if h in seen:
            return seen[h], msg  # Collision found!
        seen[h] = msg

# Example: find collision on first 4 bytes of SHA-256 (~65536 attempts)
msg1, msg2 = birthday_collision(hashlib.sha256, 32)
```

**Meet-in-the-Middle (2DES, double encryption):**
```python
def meet_in_the_middle(encrypt_fn, decrypt_fn, plaintext, ciphertext, keyspace):
    """Break double encryption E(k2, E(k1, pt)) = ct."""
    # Forward: encrypt plaintext with all possible k1
    forward = {}
    for k1 in keyspace:
        intermediate = encrypt_fn(k1, plaintext)
        forward[intermediate] = k1

    # Backward: decrypt ciphertext with all possible k2
    for k2 in keyspace:
        intermediate = decrypt_fn(k2, ciphertext)
        if intermediate in forward:
            return forward[intermediate], k2  # Found k1, k2!
```

**Key insight:** Birthday attack: n-bit hash needs ~2^(n/2) queries for 50% collision probability. 32-bit hash -> ~65K, 64-bit -> ~4 billion. Meet-in-the-middle reduces double encryption from O(2^(2k)) to O(2^k) time + O(2^k) space — this is why 2DES provides only 1 extra bit of security over DES.

---

## LFSR Stream Cipher Attacks

Linear Feedback Shift Registers generate keystreams from an initial state and feedback polynomial. Common in CTF crypto challenges and lightweight/custom ciphers.

**Detection:** Look for bit-level operations (XOR, shift, AND with tap mask), short repeating keystreams, or challenge descriptions mentioning "stream cipher", "LFSR", "shift register", or "linear recurrence".

### Berlekamp-Massey Algorithm

**Pattern:** Given a portion of known keystream (from known plaintext XOR), recover the minimal LFSR that generates it. Once you have the feedback polynomial and state, predict all future (and past) output.

**Key insight:** Berlekamp-Massey finds the shortest LFSR producing a given sequence in O(n^2). If you have 2L consecutive keystream bits (where L is the LFSR length), you can fully recover the LFSR.

```python
from sage.all import *

# Known keystream bits (from known plaintext XOR ciphertext)
keystream = [1, 0, 1, 1, 0, 0, 1, 0, 1, 1, 1, 0, 0, 1]

# Berlekamp-Massey in SageMath
F = GF(2)
seq = [F(b) for b in keystream]
R = berlekamp_massey(seq)  # Returns the feedback polynomial
print(f"LFSR polynomial: {R}")
print(f"LFSR length: {R.degree()}")

# Recover initial state from first L bits
L = R.degree()
state = keystream[:L]

# Generate future keystream
def lfsr_next(state, taps):
    """taps = list of tap positions from polynomial"""
    new_bit = 0
    for t in taps:
        new_bit ^= state[t]
    return state[1:] + [new_bit]
```

### Correlation Attack

**Pattern:** Combined LFSR generator (multiple LFSRs combined through a nonlinear function). If the combining function has correlation bias toward one LFSR's output, attack that LFSR independently.

**Key insight:** If `P(output = LFSR_i output) > 0.5`, brute-force LFSR_i's initial state (2^L candidates for length-L LFSR) and check correlation with known keystream. Much faster than brute-forcing the full combined state.

```python
# Correlation attack on a single biased LFSR
def correlation_attack(keystream_bits, lfsr_length, taps, threshold=0.6):
    """Try all 2^L initial states, keep those with high correlation"""
    best_corr, best_state = 0, None
    for seed in range(2**lfsr_length):
        state = [(seed >> i) & 1 for i in range(lfsr_length)]
        matches = 0
        s = state[:]
        for i, bit in enumerate(keystream_bits):
            if s[0] == bit:
                matches += 1
            s = lfsr_next(s, taps)
        corr = matches / len(keystream_bits)
        if corr > best_corr:
            best_corr, best_state = corr, seed
    return best_state, best_corr
```

### Known-Plaintext on LFSR Keystream

**Pattern:** XOR known plaintext with ciphertext to get keystream. With >=2L keystream bits, solve the linear system directly.

```python
import numpy as np

# Given 2L keystream bits, solve for L-bit state + L feedback taps
# Keystream relation: k[i+L] = c[0]*k[i] + c[1]*k[i+1] + ... + c[L-1]*k[i+L-1] (mod 2)
def solve_lfsr(keystream, L):
    """Solve for LFSR feedback from 2L keystream bits over GF(2)"""
    # Build matrix: each row is [k[i], k[i+1], ..., k[i+L-1]] = k[i+L]
    A = []
    b = []
    for i in range(L):
        A.append(keystream[i:i+L])
        b.append(keystream[i+L])
    # Solve over GF(2) using SageMath
    from sage.all import matrix, vector, GF
    M = matrix(GF(2), A)
    v = vector(GF(2), b)
    coeffs = M.solve_right(v)
    return list(coeffs)
```

### Galois vs Fibonacci LFSR

Two equivalent representations — same keystream, different wiring:
- **Fibonacci:** feedback from multiple taps XOR'd into last position (most common in CTFs)
- **Galois:** feedback distributed across the register (faster in hardware)

Conversion: Galois polynomial is the reciprocal of Fibonacci polynomial. Most CTF tools assume Fibonacci form.

### Common LFSR Lengths and Polynomials

| Bits | Common primitive polynomial | Period |
|------|---------------------------|--------|
| 16 | x^16 + x^14 + x^13 + x^11 + 1 | 65535 |
| 32 | x^32 + x^22 + x^2 + x + 1 | 2^32 - 1 |
| 64 | x^64 + x^4 + x^3 + x + 1 | 2^64 - 1 |

**Maximal-length LFSR:** Primitive polynomial -> period = 2^L - 1 (visits all nonzero states).

---

## CRC32 Collision-Based Signature Forgery (iCTF 2013)

**Pattern:** CRC32 is linear — appending 4 carefully chosen bytes to any message produces a target CRC32 value, enabling signature forgery without knowing the secret key.

**Key insight:** `CRC32(msg || secret)` is not a secure MAC. Given any signed response `(msg, sig)`, compute 4 suffix bytes that force `CRC32(forged_msg || suffix || secret) == target_sig`. The linearity of CRC32 means the suffix computation is deterministic and instant.

```python
import struct, binascii

def crc32_forge(data, target_crc):
    """Append 4 bytes to data so CRC32(data + suffix) == target_crc"""
    current = binascii.crc32(data) & 0xFFFFFFFF
    # CRC32 polynomial table lookup to find suffix bytes
    # that transform current CRC into target_crc
    suffix = b''
    crc = target_crc ^ 0xFFFFFFFF
    for _ in range(4):
        byte = (crc & 0xFF)
        crc = (crc >> 8)
        suffix = bytes([byte]) + suffix
    return data + suffix  # Simplified — full implementation requires polynomial division
```

**When to use:** Any protocol using CRC32 as a message authentication code (MAC). CRC32 is a checksum, not a cryptographic hash — it provides no integrity guarantees against adversarial modification.

---

## Blum-Goldwasser Bit-Extension Oracle (PlaidCTF 2013)

**Pattern:** Exploit a decryption oracle for Blum-Goldwasser-style encryption by extending ciphertext length by one bit per query to leak plaintext via parity.

**Key insight:** Extend ciphertext by one bit (L+1), shift ciphertext left (`c << 1`), and submit a modified `y` value. The oracle reveals the LSB (parity) of each decrypted chunk. The squaring sequence `y = pow(y, 2, N)` can be manipulated to produce valid extended ciphertexts the server hasn't seen.

```python
# Iterative plaintext recovery via bit-extension
for i in range(msg_length):
    extended_c = original_c << 1        # Shift ciphertext left by 1
    new_y = pow(original_y, 2, N)       # Advance squaring sequence
    response = oracle(extended_c, new_y, msg_length + 1)
    leaked_bit = response & 1           # LSB reveals one plaintext bit
    plaintext_bits.append(leaked_bit)
    original_y = new_y
```

**When to use:** Blum-Goldwasser or BBS-based (Blum Blum Shub) encryption with a decryption oracle that accepts variable-length ciphertexts. The parity leak accumulates one bit per query.

---

## Hash Length Extension Attack (PlaidCTF 2014)

**Pattern:** Server computes `hash(SECRET || user_data)` using MD5, SHA-1, or SHA-256 (Merkle-Damgard constructions). Given a valid hash and the original data, extend it with arbitrary appended data and compute a valid hash — without knowing the secret.

```bash
# Using HashPump (install: apt install hashpump)
hashpump --keylength 8 \
  --signature 'ef16c2bffbcf0b7567217f292f9c2a9a50885e01e002fa34db34c0bb916ed5c3' \
  --data 'original_data' \
  --additional ';admin=true'
# Outputs: new_signature and new_data (with padding bytes)
```

```python
# Python: hashpumpy
import hashpumpy
new_hash, new_data = hashpumpy.hashpump(
    original_hash, original_data, append_data, secret_length
)
```

**Key insight:** Merkle-Damgard hashes (MD5, SHA-1, SHA-256) process data in blocks, and the hash output IS the internal state. Given `H(secret || msg)`, you can compute `H(secret || msg || padding || extension)` without knowing `secret` — just initialize the hash state from the known output and continue hashing. Only HMAC (`H(K XOR opad || H(K XOR ipad || msg))`) is immune. If the secret length is unknown, try lengths 1-32.

---

## Compression Oracle / CRIME-Style Attack (BCTF 2015)

**Pattern:** Server compresses plaintext (LZW, zlib, etc.) before encrypting. By observing ciphertext length changes with chosen plaintexts, leak the unknown plaintext character-by-character.

```python
import base64

def oracle(plaintext):
    """Send chosen plaintext, get ciphertext length."""
    resp = send_to_server(plaintext)
    return len(base64.b64decode(resp))

# Baseline: empty input
base_len = oracle("")

# Recover secret byte-by-byte
known = ""
for pos in range(secret_length):
    for c in string.printable:
        candidate = known + c
        length = oracle(candidate)
        if length <= base_len + len(known):  # Compressed = match
            known += c
            break
```

**Key insight:** Compression algorithms (LZW, DEFLATE, zlib) replace repeated sequences with back-references. If `SALT + user_input` is compressed before encryption, sending input that matches part of the salt produces shorter ciphertext (the match compresses). This is the same class as CRIME (TLS), BREACH (HTTP), and HEIST attacks. The oracle is ciphertext length.

---

## RC4 Second-Byte Bias Distinguisher (Hackover CTF 2015)

**Pattern:** Distinguish RC4 output from true random data by exploiting RC4's second-byte bias. The second output byte of RC4 is biased toward `0x00` with probability 1/128 (vs expected 1/256).

```python
count_zero = 0
for sample in all_samples:
    if sample[1] == 0x00:  # second byte
        count_zero += 1

# Expected: random = N/256, RC4 = N/128 (2x more zeros)
if count_zero > threshold:
    print("RC4")
else:
    print("Random")
```

**Key insight:** RC4's key scheduling creates a well-known bias where `P(second_byte == 0) = 1/128` instead of `1/256`. With ~2048 samples, RC4 produces ~16 zero second-bytes vs ~8 for random. Other RC4 biases: bytes 3-255 show weaker biases; long-term biases exist at every 256th position.

---




---

<!-- Source: prng-2.md -->

# CTF Crypto - PRNG (2024-2026)

Modern PRNG attacks from 2024-2026. For classical MT19937, LCG, ChaCha20, V8 XorShift128+, see [prng.md](prng.md).

## Table of Contents
- [GF(2) Matrix PRNG Seed Recovery (0xFun 2026)](#gf2-matrix-prng-seed-recovery-0xfun-2026)
- [Middle-Square PRNG Brute Force (UTCTF 2024)](#middle-square-prng-brute-force-utctf-2024)
- [Deterministic RNG from Flag Bytes + Hill Climbing (VuwCTF 2025)](#deterministic-rng-from-flag-bytes--hill-climbing-vuwctf-2025)
- [Byte-by-Byte Oracle with Random Mode Matching (VuwCTF 2025)](#byte-by-byte-oracle-with-random-mode-matching-vuwctf-2025)
- [RSA Key Reuse / Replay (UTCTF 2024)](#rsa-key-reuse--replay-utctf-2024)
- [Logistic Map / Chaotic PRNG Seed Recovery (BYPASS CTF 2025)](#logistic-map--chaotic-prng-seed-recovery-bypass-ctf-2025)
- [Legendre-Symbol Bit Oracle → GF(p) State Recovery (HTB University 2025 One Trick Pony)](#legendre-symbol-bit-oracle--gfp-state-recovery-source-htb-university-2025-one-trick-pony)

---

## GF(2) Matrix PRNG Seed Recovery (0xFun 2026)

**Pattern (BitStorm):** PRNG using only XOR, shifts, and rotations is linear over GF(2).

**Key insight:** Express entire PRNG as matrix multiplication: `output_bits = M * seed_bits (mod 2)`. With enough outputs, Gaussian elimination recovers the seed.

```python
import numpy as np

def build_prng_matrix(prng_func, seed_bits=2048, output_bits=2048):
    """Build GF(2) matrix by running PRNG on unit vectors."""
    M = np.zeros((output_bits, seed_bits), dtype=np.uint8)
    for i in range(seed_bits):
        # Set bit i of seed
        seed = 1 << (seed_bits - 1 - i)
        output = prng_func(seed)
        for j in range(output_bits):
            M[j, i] = (output >> (output_bits - 1 - j)) & 1
    return M

# Given output, solve: M * seed = output (mod 2)
# Use GF(2) Gaussian elimination (see modern-ciphers.md solve_gf2)
seed = solve_gf2(M, output_bits_array)
```

**Identification:** Any PRNG using only `^`, `<<`, `>>`, bitwise rotate. DON'T try iterative state recovery — go straight to the matrix.

---

## Middle-Square PRNG Brute Force (UTCTF 2024)

**Pattern (numbers go brrr):** Middle-square method with small seed space.

```python
# PRNG: seed = int(str(seed * seed).zfill(12)[3:9])  — 6-digit seed
# Seed source: int(time.time() * 1000) % (10**6) — only 1M possibilities
# AES key: 8 rounds of PRNG, each produces seed % 2^16 as 2-byte fragment

def middle_square_keygen(seed):
    key = b''
    for _ in range(8):
        seed = int(str(seed * seed).zfill(12)[3:9])
        key += (seed % (2**16)).to_bytes(2, 'big')
    return key

# Brute-force: encrypt known plaintext, compare
for seed in range(10**6):
    key = middle_square_keygen(seed)
    if try_decrypt(ciphertext, key):
        print(f"Seed: {seed}")
        break
```

**Even with time-limited interactions:** 1 known-plaintext pair suffices for offline brute force.

---

## Deterministic RNG from Flag Bytes + Hill Climbing (VuwCTF 2025)

**Pattern (Totally Random Art):** Flag bytes seed Python `random.Random()`. First N bytes of flag are known format, remaining bytes produce deterministic output.

**Attack:** When PRNG seed is known/derivable from flag format, hill-climb unknown characters:
```python
import random

def render(flag_bytes):
    rng = random.Random()
    rng.seed(flag_bytes)
    grid = [[0]*10 for _ in range(5)]
    for b in flag_bytes:
        steps, stroke = divmod(b, 16)
        x, y = 0, 0
        for _ in range(steps):
            dx, dy = rng.choice([(0,1),(0,-1),(1,0),(-1,0)])
            x = (x + dx) % 10
            y = (y + dy) % 5
        grid[y][x] = (grid[y][x] + stroke) % 16
    return grid

# Hill climb: try each byte value, keep the one that maximizes grid match
target = parse_target_art()
flag = list(b'VuwCTF{')
for pos in range(7, 17):
    best_score, best_char = -1, 0
    for c in range(32, 127):
        candidate = bytes(flag + [c])
        score = sum(1 for y in range(5) for x in range(10)
                    if render(candidate)[y][x] == target[y][x])
        if score > best_score:
            best_score, best_char = score, c
    flag.append(best_char)
```

---

## Byte-by-Byte Oracle with Random Mode Matching (VuwCTF 2025)

**Pattern (Unorthodox IV):** Server encrypts with one of N random modes/IVs per encryption. Can submit own plaintexts.

**Attack strategy:**
1. Connect, get encrypted flag
2. Probe with known prefix to check if connection can "reach" the flag's mode (same mode = same ciphertext prefix). ~50 probes, if no match, reconnect.
3. Once reachable, test candidate characters. Mode match AND next byte match = correct char. Mode match but byte mismatch = eliminate candidate permanently.
4. Elimination persists across reconnections.

**Key insight:** Probe for mode reachability first to avoid wasting attempts. Elimination-based search is more efficient than confirmation-based when modes are randomized.

---

## RSA Key Reuse / Replay (UTCTF 2024)

**Pattern (simple signature):** RSA keys reused across rounds with alternating inputs.

**Attack:** Submit previously captured encrypted output back to the server. If keys are static across interactions, replay attacks are trivial. Always check if crypto keys change between rounds.

---

## Logistic Map / Chaotic PRNG Seed Recovery (BYPASS CTF 2025)

**Pattern (Chaotic Trust):** Stream cipher using the logistic map `x_{n+1} = r * x * (1 - x)` as PRNG. Keystream generated by packing iterated float values.

**Key insight:** Logistic map with `r ≈ 4.0` is chaotic but deterministic — recovering the seed (initial x value) enables full keystream reconstruction. Seed is usually a decimal between 0 and 1, such as 0.123456789.

```python
import struct

def logistic_map(x, r=3.99):
    return r * x * (1 - x)

def decrypt_logistic(cipher_hex, seed):
    cipher = bytes.fromhex(cipher_hex)
    x = seed
    stream = b""

    while len(stream) < len(cipher):
        x = logistic_map(x)
        # Pack float as bytes for keystream (check endianness)
        stream += struct.pack("<f", x)[-2:]  # or full 4 bytes

    stream = stream[:len(cipher)]
    return bytes(a ^ b for a, b in zip(cipher, stream))

# Brute-force seed precision
for precision in range(6, 12):
    for base in [123456, 234567, 314159, 271828]:
        seed = base / (10 ** precision)
        result = decrypt_logistic(cipher_hex, seed)
        if b"FLAG" in result or b"CTF" in result:
            print(f"Seed: {seed}, Flag: {result}")
```

**Variations:**
- **r parameter:** Usually `r = 3.99` or `r = 4.0` (full chaos regime)
- **Packing:** `struct.pack("<f", x)` (4 bytes), `struct.pack("<d", x)` (8 bytes), or `[-2:]` for 2-byte fragments
- **Seed range:** Often a recognizable decimal like `0.123456789` or derived from challenge hints

**Identification:** Challenge mentions "chaos", "logistic", "butterfly effect", or provides `r` parameter. Look for source code containing `x = r * x * (1 - x)` iteration.

---

## Legendre-Symbol Bit Oracle → GF(p) State Recovery (source: HTB University 2025 One Trick Pony)

**Trigger:** oracle outputs a single bit per query derived from `(x_i / p)` (Legendre symbol) where `x_i` is the internal PRNG state and `p` is a public prime; state evolves via a linear recurrence (LCG, simple LFSR-mod-p).
**Signals:** `jacobi_symbol(s, p)` in source; ~1 bit per query; prime `p` printed publicly.
**Mechanic:** each bit is a QR/NQR constraint over `GF(p)`. Collect few-hundred samples, translate to a CNF via `x_i` quadratic residuosity, solve with Z3 BitVec or lattice reduction (if recurrence is LCG-shaped: CVP on `a x + b = y` with Legendre constraint). Recovers seed in seconds. Pattern: any bit-oracle cipher whose single output is a squareness test over a known modulus is linearly solvable.



---

<!-- Source: prng.md -->

# CTF Crypto - PRNG & Key Recovery

## Table of Contents
- [Mersenne Twister (MT19937) State Recovery](#mersenne-twister-mt19937-state-recovery)
- [MT State Recovery from random.random() Floats via GF(2) Matrix (PHD CTF Quals 2012)](#mt-state-recovery-from-randomrandom-floats-via-gf2-matrix-phd-ctf-quals-2012)
- [Time-Based Seed Attacks](#time-based-seed-attacks)
- [C srand/rand Synchronization via Python ctypes](#c-srandrand-synchronization-via-python-ctypes)
- [Layered Encryption Recovery](#layered-encryption-recovery)
- [LCG Parameter Recovery Attack](#lcg-parameter-recovery-attack)
- [ChaCha20 Key Recovery](#chacha20-key-recovery)
- [V8 XorShift128+ State Recovery (Math.random Prediction)](#v8-xorshift128-state-recovery-mathrandom-prediction)
- [Password Cracking Strategy](#password-cracking-strategy)

For 2024-2026 era techniques (GF(2) matrix, middle-square, logistic map, Legendre bit oracle), see [prng-2.md](prng-2.md).

---

## Mersenne Twister (MT19937) State Recovery

Python's `random` module uses Mersenne Twister. If you can observe outputs, you can recover the state and predict future values.

**Key properties:**
- 624 × 32-bit internal state
- Each output is tempered from state
- After 624 outputs, state is twisted (regenerated)

**Basic untemper (reverse single output):**
```python
def untemper(y):
    y ^= y >> 18
    y ^= (y << 15) & 0xefc60000
    for _ in range(7):
        y ^= (y << 7) & 0x9d2c5680
    y ^= y >> 11
    y ^= y >> 22
    return y

# Given 624 consecutive outputs, recover state
state = [untemper(output) for output in outputs]
```

**Python's randrange(maxsize) on 64-bit:**
- `maxsize = 2^63 - 1`, so `getrandbits(63)` is used
- Each 63-bit output uses 2 MT outputs: `(mt1 << 31) | (mt2 >> 1)`
- One bit lost per output → need symbolic solving

**Symbolic approach with z3:**
```python
from z3 import *

def symbolic_temper(y):
    y = y ^ (LShR(y, 11))
    y = y ^ ((y << 7) & 0x9d2c5680)
    y = y ^ ((y << 15) & 0xefc60000)
    y = y ^ (LShR(y, 18))
    return y

# Create symbolic MT state
mt = [BitVec(f'mt_{i}', 32) for i in range(624)]
solver = Solver()

# For each observed 63-bit output
for i, out63 in enumerate(outputs):
    if 2*i + 1 >= 624: break
    y1 = symbolic_temper(mt[2*i])
    y2 = symbolic_temper(mt[2*i + 1])
    combined = Concat(Extract(31, 0, y1), Extract(31, 1, y2))
    solver.add(combined == out63)

if solver.check() == sat:
    state = [solver.model()[mt[i]].as_long() for i in range(624)]
```

**Applications:**
- MIME boundary prediction (email libraries)
- Session token prediction
- CAPTCHA bypass (predictable codes)
- Game RNG exploitation

## MT State Recovery from random.random() Floats via GF(2) Matrix (PHD CTF Quals 2012)

**Pattern:** Server exposes `random.random()` float outputs (e.g., via an API endpoint). Standard MT untemper requires 624 × 32-bit integer outputs, but `random.random()` produces 53-bit floats — truncating each to 8 usable bits per observation. A precomputed GF(2) magic matrix maps observed byte values back to the 624-word MT state.

**Key insight:** `random.random()` returns `(a*2^27+b)/2^53` where `a` = 27 bits from one MT output and `b` = 26 bits from the next. Truncating `int(float * 256)` yields only 8 bits per float, so 3360+ observations are needed (vs. 624 for integer outputs). The `not_random` library precomputes the GF(2) relationship between observed bits and state bits.

```python
import random, gzip, hashlib

# Load precomputed GF(2) magic matrix (from github.com/fx5/not_random)
f = gzip.GzipFile("magic_data", "r")
magic = eval(f.read())
f.close()

def rebuild_from_floats(floats):
    """Convert float observations to byte values, then recover MT state."""
    vals = [int(f * 256) for f in floats]  # truncate to 8-bit
    return rebuild_random(vals)

def rebuild_random(vals):
    """Recover MT19937 state from 3360+ byte observations using GF(2) matrix."""
    def getbit(bit):
        assert bit >= 0
        return (vals[bit // 8] >> (7 - bit % 8)) & 1
    state = []
    for i in range(624):
        val = 0
        data = magic[i % 2]
        for bit in data:
            val <<= 1
            for b in bit:
                val ^= getbit(b + (i // 2) * 8 - 8)
        state.append(val)
    state.append(0)
    ran = random.Random()
    ran.setstate((3, tuple(state), None))
    # Advance past consumed outputs
    for i in range(len(vals) - 3201 + 394):
        ran.randint(0, 255)
    return ran

# Collect 3360+ random.random() floats from the target
floats = [...]  # observed values from server API

# Recover state and predict future outputs
my_random = rebuild_from_floats(floats[:3360])

# Verify predictions match remaining observations
for observed, predicted in zip(floats[3360:], [my_random.random() for _ in range(40)]):
    assert '%.16f' % observed == '%.16f' % predicted

# Forge password reset token (same hash the server computes)
token = hashlib.md5(('%.16f' % my_random.random()).encode()).hexdigest()
reset_url = f'http://target/reset/{user_id}-{token}/'
```

**Attack flow (password reset token prediction):**
1. Request 3360+ random float values from an API endpoint that exposes them (e.g., `/?count=3360`)
2. Simultaneously trigger a password reset (the reset token is `md5(random.random())`)
3. Recover the MT state from the observed floats
4. Predict the `random.random()` call used for the reset token
5. Construct the reset URL with the predicted token

**When to use:** Server uses Python's `random.random()` for security-sensitive tokens (session IDs, password resets, CSRF tokens) and also exposes random values through another endpoint. The `not_random` library handles the bit-level math — focus on collecting enough float observations and synchronizing timing with the target operation.

---

## Time-Based Seed Attacks

When encryption uses time-based PRNG seed:
```python
seed = f"{username}_{timestamp}_{random_bits}"
```

**Attack approach:**
1. **Username:** Extract from metadata, email headers, challenge context
2. **Timestamp:** Get from file metadata (ZIP, exiftool)
3. **Random bits:** Check for hardcoded seed in binary, or bruteforce if small range

**Timestamp extraction:**
```bash
# Set timezone to match target
TZ=Pacific/Galapagos exiftool file.enc
# Look for File Modification Date/Time
```

**Bruteforce milliseconds:**
```python
from datetime import datetime
import random

for ms in range(1000):
    ts = f"2021-02-09!07:23:54.{ms:03d}"
    seed = f"{username}_{ts}_{rdata}"
    rng = random.Random()
    rng.seed(seed)
    key = bytes(rng.getrandbits(8) for _ in range(32))
    if try_decrypt(ciphertext, key):
        print(f"Found seed: {seed}")
        break
```

## C srand/rand Synchronization via Python ctypes

**Pattern:** Binary seeds C's PRNG with `srand(time(NULL))` at startup and uses `rand()` for encryption keys, random challenges, or XOR masks. Python's `random` module uses Mersenne Twister (different algorithm), so calling `random.seed(t)` produces wrong outputs. Use `ctypes` to load the same libc and call C's `srand()`/`rand()` directly.

**Basic synchronization (L3akCTF 2024, MireaCTF):**
```python
from ctypes import CDLL
from time import time

# Load the SAME libc used by the target binary
libc = CDLL('./libc.so.6')  # or CDLL('libc.so.6') for system libc

# Seed at the same second as the binary starts
libc.srand(int(time()))

# Generate the same sequence as the binary's rand() calls
for i in range(16):
    value = libc.rand() & 0xff  # match binary's truncation (e.g., & 0xff for byte)
    print(value)
```

**Decrypting XOR-encrypted data (L3akCTF 2024 chonccfile):**
```python
from ctypes import CDLL
from time import time
from pwn import u32, p32

libc_imp = CDLL('./libc.so.6')
libc_imp.srand(int(time()))

# Binary XORs each 4-byte block with rand() output
encrypted_data = b'...'  # read from heap/memory
result = b''
for i in range(0, len(encrypted_data), 4):
    block = u32(encrypted_data[i:i+4])
    libc_imp.rand()       # skip delay-related rand() call if binary does extra calls
    key = libc_imp.rand()
    block ^= key
    result += p32(block)
```

**Timing considerations:**
- `time(NULL)` has 1-second granularity — start the exploit within the same second as the binary
- Remote targets may have startup delay — try offsets of `+1` or `+2` seconds
- Account for any `rand()` calls between `srand()` and the target usage (e.g., random delays)
- Not 100% reliable on first try — retry with adjacent seeds if needed

**Key insight:** Python's `random` and C's `rand()` are completely different PRNGs. When a C binary uses `srand(time(NULL))`, the only way to reproduce the sequence from Python is `ctypes.CDLL` calling the same libc's `srand`/`rand`. Load the challenge's provided `libc.so.6` for exact compatibility. This works for any C PRNG output prediction — XOR keys, random challenges, token generation, or encrypted heap data.

**Alternative — custom shared library (MireaCTF):**
```c
// random_lib.c — compile with: gcc -shared -o random_lib.so random_lib.c
#include <stdlib.h>
void setseed(int seed) { srand(seed); }
int generate() { return rand() & 0xff; }
```
```python
from ctypes import CDLL
lib = CDLL('./random_lib.so')
lib.setseed(int(time()) + 1)  # +1 for remote delay
numbers = [lib.generate() for _ in range(16)]
```

---

## Layered Encryption Recovery

When binary uses multiple encryption layers:
1. Identify encryption order (e.g., Serpent → TEA)
2. Find seed derivation (e.g., sum of flag chars)
3. Keys often derived from `srand()` sequence
4. Bruteforce seed range (sum of printable ASCII is limited)

## LCG Parameter Recovery Attack

Linear Congruential Generators are weak PRNGs. Given consecutive outputs, recover parameters:

**LCG formula:** `x_{n+1} = (a * x_n + c) mod m`

**Recovery from output sequence (SageMath):**
```python
# Given sequence: [s0, s1, s2, s3, ...]
# crypto-attacks library: github.com/jvdsn/crypto-attacks
from attacks.lcg import parameter_recovery

sequence = [
    72967016216206426977511399018380411256993151454761051136963936354667101207529,
    49670218548812619526153633222605091541916798863041459174610474909967699929824,
    # ... more outputs
]

m, a, c = parameter_recovery.attack(sequence)
print(f"Modulus m: {m}")
print(f"Multiplier a: {a}")
print(f"Increment c: {c}")
```

**Weak RSA from LCG primes:**
- If RSA primes are generated from LCG, recover LCG params first
- Use known plaintext XOR ciphertext to extract LCG outputs
- Regenerate same prime sequence to factor N

```python
# Recover XOR key (which is LCG output)
def recover_lcg_output(plaintext, ciphertext, timestamp):
    pt_bytes = plaintext.encode('utf-8').ljust(32, b'\0')
    ct_int = int.from_bytes(bytes.fromhex(ciphertext), 'big')
    return timestamp ^ int.from_bytes(pt_bytes, 'big') ^ ct_int

# After recovering LCG params, generate RSA primes
lcg = LCG(a, c, m, seed)
primes = []
while len(primes) < 8:
    candidate = lcg.next()
    if is_prime(candidate) and candidate.bit_length() == 256:
        primes.append(candidate)

n = prod(primes)
phi = prod(p - 1 for p in primes)
d = pow(65537, -1, phi)
```

## ChaCha20 Key Recovery

When ChaCha20 key is derived from recoverable data:

```python
from Crypto.Cipher import ChaCha20

# If key derived from predictable source (timestamp, PID, etc.)
for candidate_key in generate_candidates():
    cipher = ChaCha20.new(key=candidate_key, nonce=nonce)
    plaintext = cipher.decrypt(ciphertext)
    if is_valid(plaintext):  # Check for expected format
        print(f"Key found: {candidate_key.hex()}")
        break
```

**Ghidra emulator for key extraction:**
When key is computed by complex function, emulate it rather than reimplementing.

## V8 XorShift128+ State Recovery (Math.random Prediction)

**Pattern:** Web challenge uses `Math.floor(CONST * Math.random())` to generate tokens, codes, or game values. V8's `Math.random()` uses XorShift128+ (xs128p) PRNG. Given consecutive floored outputs, recover the internal state (state0, state1) with Z3, then predict future values.

**V8 internals:**
1. xs128p produces 64-bit state; V8 uses `state0 >> 12 | 0x3FF0000000000000` to create a double in [1.0, 2.0), then subtracts 1.0
2. `Math.random()` reads from a **64-value LIFO cache**. When the cache is empty, `RefillCache()` generates 64 new values. Values are consumed in reverse order from the cache
3. Only `state0` is used for the output (not `state1`)

**xs128p algorithm:**
```python
def xs128p(state0, state1):
    s1 = state0 & 0xFFFFFFFFFFFFFFFF
    s0 = state1 & 0xFFFFFFFFFFFFFFFF
    s1 ^= (s1 << 23) & 0xFFFFFFFFFFFFFFFF
    s1 ^= (s1 >> 17) & 0xFFFFFFFFFFFFFFFF
    s1 ^= s0 & 0xFFFFFFFFFFFFFFFF
    s1 ^= (s0 >> 26) & 0xFFFFFFFFFFFFFFFF
    state0 = state1 & 0xFFFFFFFFFFFFFFFF
    state1 = s1 & 0xFFFFFFFFFFFFFFFF
    return state0, state1, state0  # output is new state0
```

**Z3 solver for `Math.floor(CONST * Math.random())`:**
```python
from z3 import *
from decimal import Decimal
import struct

def to_double(value):
    double_bits = (value >> 12) | 0x3FF0000000000000
    return struct.unpack('d', struct.pack('<Q', double_bits))[0] - 1

def from_double(dbl):
    return struct.unpack('<Q', struct.pack('d', dbl + 1))[0] & 0x7FFFFFFFFFFFFFFF

def sym_xs128p(s0, s1):
    s1_ = s0
    s0_ = s1
    s1_ ^= (s1_ << 23)
    s1_ ^= LShR(s1_, 17)
    s1_ ^= s0_
    s1_ ^= LShR(s0_, 26)
    return s1, s1_  # new state0, state1

def solve_v8_random(observed_values, multiple):
    """Recover xs128p state from consecutive Math.floor(multiple * Math.random()) outputs.
    observed_values must be in REVERSE order (oldest first after tac)."""
    ostate0, ostate1 = BitVecs('ostate0 ostate1', 64)
    sym_s0, sym_s1 = ostate0, ostate1
    slvr = SolverFor("QF_BV")

    for val in observed_values:
        sym_s0, sym_s1 = sym_xs128p(sym_s0, sym_s1)
        calc = LShR(sym_s0, 12)  # V8's ToDouble mantissa bits
        # Constrain: floor(multiple * to_double(state0)) == val
        lower = from_double(Decimal(val) / Decimal(multiple))
        upper = from_double(Decimal(val + 1) / Decimal(multiple))
        lower_m = lower & 0x000FFFFFFFFFFFFF
        upper_m = upper & 0x000FFFFFFFFFFFFF
        upper_e = (upper >> 52) & 0x7FF
        slvr.add(And(lower_m <= calc, Or(upper_m >= calc, upper_e == 1024)))

    if slvr.check() == sat:
        m = slvr.model()
        return m[ostate0].as_long(), m[ostate1].as_long()
    return None, None

# Predict next values after state recovery
def predict_next(state0, state1, multiple, count):
    results = []
    for _ in range(count):
        state0, state1, output = xs128p(state0, state1)
        import math
        results.append(math.floor(multiple * to_double(output)))
    return results
```

**Usage (tool: d0nutptr/v8_rand_buster):**
```bash
# Collect observed values, reverse them (LIFO cache order), pipe to solver
cat observed_codes.txt | tac | python3 xs128p.py --multiple 100000

# Generate predictions from recovered state
python3 xs128p.py --multiple 100000 --gen <state0>,<state1>,<count>
```

**Key insight:** The LIFO cache means observed values are in reverse generation order — reverse them with `tac` before solving. The Z3 `QF_BV` (quantifier-free bitvector) theory efficiently handles the bitwise operations. Typically 5-10 consecutive outputs suffice for a unique solution.

**Common pitfalls:**
- Forgetting to reverse the observation order (cache is LIFO)
- Multiple browser tabs or web workers may have separate PRNG states
- Cache boundary (every 64 calls) can introduce discontinuities if observations span a refill

**When to use:** Web challenge where JavaScript generates predictable-looking random values (tokens, verification codes, game rolls) using `Math.random()`. Look for patterns like `Math.floor(N * Math.random())` or `Math.random().toString(36).substr(2)` in client-side or server-side Node.js code.

---

## Password Cracking Strategy

**Attack order for unknown passwords:**
1. Common wordlists: `rockyou.txt`, `10k-common.txt`
2. Theme-based wordlist (usernames, challenge keywords)
3. Rules attack: wordlist + `best66.rule`, `dive.rule`
4. Hybrid: `word + ?d?d?d?d` (word + 4 digits)
5. Brute force: start at 4 chars, increase

**SHA256 with hex salt (VuwCTF 2025, Delicious Cooking):** Format `hash$hex_salt`. Salt must be hex-decoded before `SHA256(password + salt_bytes)`. Password often derivable from security questions (e.g., "fav movie + PIN" = "ratatouille0000"-"ratatouille9999").

**CTF password patterns:**
```text
base_password + year     → actnowonclimatechange2026
username + digits        → nemo123, admin2026
theme + numbers          → flag2026, ctf2025
leet speak               → p@ssw0rd, s3cr3t
```

**Hashcat modes reference:**
```bash
# Common modes
-m 0      # MD5
-m 1000   # NTLM
-m 5600   # NTLMv2
-m 13600  # WinZip AES
-m 13000  # RAR5
-m 11600  # 7-Zip

# Attack modes
-a 0      # Dictionary
-a 3      # Brute force mask
-a 6      # Hybrid (word + mask)
-a 7      # Hybrid (mask + word)
```

**When password relates to another in challenge:**
- Try variations: `password + year`, `password + 123`
- Try reversed: `drowssap`
- Try with common suffixes: `!`, `@`, `#`, `1`, `123`
- If SMB/FTP password known, ZIP password often related

---




---

<!-- Source: quickref.md -->

# ctf-crypto — Quick Reference

Inline code snippets and quick-reference tables. Loaded on demand from `SKILL.md`. All detailed techniques live in the category-specific support files listed in `SKILL.md#additional-resources`.

## Classic Ciphers

- **Caesar:** Frequency analysis or brute force 26 keys
- **Vigenere:** Known plaintext attack with flag format prefix; derive key from `(ct - pt) mod 26`. Kasiski examination for unknown key length (GCD of repeated sequence distances)
- **Atbash:** A<->Z substitution; look for "Abashed" hints in challenge name
- **Substitution wheel:** Brute force all rotations of inner/outer alphabet mapping
- **Multi-byte XOR:** Split ciphertext by key position, frequency-analyze each column independently; score by English letter frequency (space = 0x20)
- **Cascade XOR:** Brute force first byte (256 attempts), rest follows deterministically
- **XOR rotation (power-of-2):** Even/odd bits never mix; only 4 candidate states
- **Weak XOR verification:** Single-byte XOR check has 1/256 pass rate; brute force with enough budget
- **Deterministic OTP:** Known-plaintext XOR to recover keystream; match load-balanced backends
- **OTP key reuse (many-time pad):** `C1 XOR C2 XOR known_P = unknown_P`; crib dragging when no plaintext known
- **Homophonic (variable-length):** Multi-character ciphertext groups map to single plaintext chars. Find n-grams with identical sub-n-gram frequencies, replace with symbols, solve as monoalphabetic. See [classic-ciphers.md](classic-ciphers.md#variable-length-homophonic-substitution-asis-ctf-finals-2013).

See [classic-ciphers.md](classic-ciphers.md) for full code examples.

## Modern Cipher Attacks

- **AES-ECB:** Block shuffling, byte-at-a-time oracle; image ECB preserves visual patterns
- **AES-CBC:** Bit flipping to change plaintext; padding oracle for decryption without key
- **AES-CFB-8:** Static IV with 8-bit feedback allows state reconstruction after 16 known bytes
- **CBC-MAC/OFB-MAC:** XOR keystream for signature forgery: `new_sig = old_sig XOR block_diff`
- **S-box collisions:** Non-permutation S-box (`len(set(sbox)) < 256`) enables 4,097-query key recovery
- **GF(2) elimination:** Linear hash functions (XOR + rotations) solved via Gaussian elimination over GF(2)
- **Padding oracle:** Byte-by-byte decryption by modifying previous block and testing padding validity
- **LFSR stream ciphers:** Berlekamp-Massey recovers feedback polynomial from 2L keystream bits; correlation attack breaks combined generators with biased combining functions

See [modern-ciphers.md](modern-ciphers.md) for full code examples.

## RSA Attacks

- **Small e with small message:** Take eth root
- **Common modulus:** Extended GCD attack
- **Wiener's attack:** Small d
- **Fermat factorization:** p and q close together
- **Pollard's p-1:** Smooth p-1
- **Hastad's broadcast:** Same message, multiple e=3 encryptions
- **Consecutive primes:** q = next_prime(p); find first prime below sqrt(N)
- **Multi-prime:** Factor N with sympy; compute phi from all factors
- **Restricted-digit primes:** Digit-by-digit factoring from LSB with modular pruning
- **Coppersmith structured primes:** Partially known prime; `f.small_roots()` in SageMath
- **Manger oracle (simplified):** Phase 1 doubling + phase 2 binary search; ~128 queries for 64-bit key
- **Manger on RSA-OAEP (timing):** Python `or` short-circuit skips expensive PBKDF2 when Y != 0, creating fast/slow timing oracle. Full 3-step attack (~1024 iterations for 1024-bit RSA). Calibrate timing bounds with known-fast/known-slow samples.
- **Polynomial hash (trivial root):** `g(0) = 0` for polynomial hash; craft suffix for `msg = 0 (mod P)`, signature = 0
- **Polynomial CRT in GF(2)[x]:** Collect ~20 remainders `r = flag mod f`, filter coprime, CRT combine
- **Affine over composite modulus:** CRT in each prime factor field; Gauss-Jordan per prime
- **RSA p=q validation bypass:** Set `p=q` so server computes wrong `phi=(p-1)^2` instead of `p*(p-1)`; test decryption fails, leaking ciphertext
- **RSA cube root CRT (gcd(e,phi)>1):** When all primes ≡ 1 mod e, compute eth roots per-prime via `nthroot_mod`, enumerate CRT combinations (3^k feasible for small k)
- **Factoring from phi(n) multiple:** Any multiple of `phi(n)` (e.g., `e*d-1`) enables factoring via Miller-Rabin square root technique; succeeds with prob ≥ 1/2 per attempt

See [rsa-attacks.md](rsa-attacks.md) and [advanced-math.md](advanced-math.md) for full code examples.

## Elliptic Curve Attacks

- **Small subgroup:** Check curve order for small factors; Pohlig-Hellman + CRT
- **Invalid curve:** Send points on weaker curves if validation missing
- **Singular curves:** Discriminant = 0; DLP maps to additive/multiplicative group
- **Smart's attack:** Anomalous curves (order = p); p-adic lift solves DLP in O(1)
- **Fault injection:** Compare correct vs faulty output; recover key bit-by-bit
- **Clock group (x^2+y^2=1):** Order = p+1 (not p-1!); Pohlig-Hellman when p+1 is smooth
- **Isogenies:** Graph traversal via modular polynomials; pathfinding via LCA
- **ECDSA nonce reuse:** Same `r` in two signatures leaks nonce `k` and private key `d` via modular arithmetic. Check for repeated `r` values
- **Braid group DH:** Alexander polynomial is multiplicative under braid concatenation — Eve computes shared secret from public keys. See [exotic-crypto.md](exotic-crypto.md#braid-group-dh--alexander-polynomial-multiplicativity-dicectf-2026)
- **Ed25519 torsion side channel:** Cofactor h=8 leaks secret scalar bits when key derivation uses `key = master * uid mod l`; query powers of 2, check y-coordinate consistency
- **Tropical semiring residuation:** Tropical (min-plus) DH is broken — residual `b* = max(Mb[i] - M[i][j])` recovers shared secret directly from public matrices

See [ecc-attacks.md](ecc-attacks.md), [advanced-math.md](advanced-math.md), and [exotic-crypto.md](exotic-crypto.md) for full code examples.

## Lattice / LWE Attacks

- **LWE via CVP (Babai):** Construct lattice from `[q*I | 0; A^T | I]`, use fpylll CVP.babai to find closest vector, project to ternary {-1,0,1}. Watch for endianness mismatches between server description and actual encoding.
- **LLL for approximate GCD:** Short vector in lattice reveals hidden factors
- **Multi-layer challenges:** Geometry → subspace recovery → LWE → AES-GCM decryption chain

See [advanced-math.md](advanced-math.md) for full LWE solving code and multi-layer patterns.

## ZKP & Constraint Solving

- **ZKP cheating:** For impossible problems (3-coloring K4), find hash collisions or predict PRNG salts
- **Graph 3-coloring:** `nx.coloring.greedy_color(G, strategy='saturation_largest_first')`
- **Z3 solver:** BitVec for bit-level, Int for arbitrary precision; BPF/SECCOMP filter solving
- **Garbled circuits (free XOR):** XOR three truth table entries to recover global delta
- **Bigram substitution:** OR-Tools CP-SAT with automaton constraint for known plaintext structure
- **Trigram decomposition:** Positions mod n form independent monoalphabetic ciphers
- **Shamir SSS (deterministic coefficients):** One share + seeded RNG = univariate equation in secret
- **Race condition (TOCTOU):** Synchronized concurrent requests bypass `counter < N` checks
- **Groth16 broken setup (delta==gamma):** Trivially forge: A=alpha, B=beta, C=-vk_x. Always check verifier constants first
- **Groth16 proof replay:** Unconstrained nullifier + no tracking = infinite replays from setup tx
- **DV-SNARG forgery:** With verifier oracle access, learn secret v values from unconstrained pairs, forge via CRS entry cancellation

See [zkp-and-advanced.md](zkp-and-advanced.md) for full code examples and solver patterns.

## Modern Cipher Attacks (Additional)

- **Affine over composite modulus:** `c = A*x+b (mod M)`, M composite (e.g., 65=5*13). Chosen-plaintext recovery via one-hot vectors, CRT inversion per prime factor. See [modern-ciphers.md](modern-ciphers.md#affine-cipher-over-composite-modulus-nullcon-2026).
- **Custom linear MAC forgery:** XOR-based signature linear in secret blocks. Recover secrets from ~5 known pairs, forge for target. See [modern-ciphers.md](modern-ciphers.md#custom-linear-mac-forgery-nullcon-2026).
- **Manger oracle (RSA threshold):** RSA multiplicative + binary search on `m*s < 2^128`. ~128 queries to recover AES key.

## CBC Padding Oracle Attack

Server reveals valid/invalid padding → decrypt any CBC ciphertext without key. ~4096 queries per 16-byte block. Use PadBuster or `padding-oracle` Python library. See [modern-ciphers.md](modern-ciphers.md#cbc-padding-oracle-attack).

## Bleichenbacher RSA Padding Oracle (ROBOT)

RSA PKCS#1 v1.5 padding validation oracle → adaptive chosen-ciphertext plaintext recovery. ~10K queries for RSA-2048. Affects TLS implementations via timing. See [modern-ciphers.md](modern-ciphers.md#bleichenbacher--pkcs1-v15-rsa-padding-oracle).

## Birthday Attack / Meet-in-the-Middle

n-bit hash collision in ~2^(n/2) attempts. Meet-in-the-middle breaks double encryption in O(2^k) instead of O(2^(2k)). See [modern-ciphers.md](modern-ciphers.md#birthday-attack--meet-in-the-middle).

## CRC32 Collision-Based Signature Forgery (iCTF 2013)

CRC32 is linear — append 4 chosen bytes to force any target CRC32, forging `CRC32(msg || secret)` signatures without the secret. See [modern-ciphers.md](modern-ciphers.md#crc32-collision-based-signature-forgery-ictf-2013).

## Blum-Goldwasser Bit-Extension Oracle (PlaidCTF 2013)

Extend ciphertext by one bit per oracle query to leak plaintext via parity. Manipulate BBS squaring sequence to produce valid extended ciphertexts. See [modern-ciphers.md](modern-ciphers.md#blum-goldwasser-bit-extension-oracle-plaidctf-2013).

## Hash Length Extension Attack

Exploits Merkle-Damgard hashes (`hash(SECRET || user_data)`) — append arbitrary data and compute valid hash without knowing the secret. Use `hashpump` or `hashpumpy`. See [modern-ciphers.md](modern-ciphers.md#hash-length-extension-attack-plaidctf-2014).

## Compression Oracle (CRIME-Style)

Compression before encryption leaks plaintext via ciphertext length changes. Send chosen plaintexts; matching n-grams compress shorter. Same class as CRIME/BREACH. See [modern-ciphers.md](modern-ciphers.md#compression-oracle--crime-style-attack-bctf-2015).

## RC4 Second-Byte Bias

RC4's second output byte is biased toward `0x00` (probability 1/128 vs 1/256). Distinguishes RC4 from random with ~2048 samples. See [modern-ciphers.md](modern-ciphers.md#rc4-second-byte-bias-distinguisher-hackover-ctf-2015).

## RSA Multiplicative Homomorphism Signature Forgery

Unpadded RSA: `S(a) * S(b) mod n = S(a*b) mod n`. If oracle blacklists target message, sign its factors and multiply. See [rsa-attacks.md](rsa-attacks.md#rsa-signature-forgery-via-multiplicative-homomorphism-mma-ctf-2015).

## Common Patterns

- **RSA basics:** `phi = (p-1)*(q-1)`, `d = inverse(e, phi)`, `m = pow(c, d, n)`. See [rsa-attacks.md](rsa-attacks.md) for full examples.
- **XOR:** `from pwn import xor; xor(ct, key)`. See [classic-ciphers.md](classic-ciphers.md) for XOR variants.

## C srand/rand Prediction via ctypes (L3akCTF 2024, MireaCTF)

**Pattern:** Binary uses `srand(time(NULL))` + `rand()` for keys/XOR masks. Python's `random` module uses a different PRNG. Use `ctypes.CDLL('./libc.so.6')` to call C's `srand(int(time()))` and `rand()` directly, reproducing the exact sequence. See [prng.md](prng.md#c-srandrand-synchronization-via-python-ctypes) for XOR decryption examples and timing tips.

## V8 XorShift128+ (Math.random) State Recovery

**Pattern:** V8 JavaScript engine uses xs128p PRNG for `Math.random()`. Given 5-10 consecutive outputs of `Math.floor(CONST * Math.random())`, recover internal state (state0, state1) with Z3 QF_BV solver and predict future values. Values must be reversed (LIFO cache). Tool: `d0nutptr/v8_rand_buster`. See [prng.md](prng.md#v8-xorshift128-state-recovery-mathrandom-prediction).

## MT State Recovery from Float Outputs (PHD CTF Quals 2012)

**Pattern:** Server exposes `random.random()` floats. Standard untemper needs 624 × 32-bit integers, but floats yield only ~8 usable bits each. A precomputed GF(2) magic matrix (`not_random` library) recovers the full MT state from 3360+ float observations. Use to predict password reset tokens, session IDs, or CSRF tokens derived from `random.random()`. See [prng.md](prng.md#mt-state-recovery-from-randomrandom-floats-via-gf2-matrix-phd-ctf-quals-2012).

## Chaotic PRNG (Logistic Map)

- **Logistic map:** `x = r * x * (1 - x)`, `r ≈ 3.99-4.0`; seed recovery by brute-forcing high-precision decimals
- **Keystream:** `struct.pack("<f", x)` per iteration; XOR with ciphertext

See [prng.md](prng.md#logistic-map--chaotic-prng-seed-recovery-bypass-ctf-2025) for full code.

## Useful Tools

- **Python:** `pip install pycryptodome z3-solver sympy gmpy2`
- **SageMath:** `sage -python script.py` (required for ECC, Coppersmith, lattice attacks)
- **RsaCtfTool:** `python RsaCtfTool.py -n <n> -e <e> --uncipher <c>` — automated RSA attack suite (tries Wiener, Hastad, Fermat, Pollard, and many more)
- **quipqiup.com:** Automated substitution cipher solver (frequency + word pattern analysis)




---

<!-- Source: rsa-attacks-2.md -->

# CTF Crypto — RSA Attacks (2025-2026 era)

RSA attacks from elite 2025-2026 CTFs. Base techniques (Wiener, Fermat, Hastad, Coppersmith structured primes, small-`d`, common-modulus, fixed-point) live in [rsa-attacks.md](rsa-attacks.md); oracle-style attacks (Bleichenbacher, Manger, blinding) in [rsa-attacks-oracle.md](rsa-attacks-oracle.md).

## Table of Contents
- [TLS RSA Bit-Flipped `d` via OOB-byte + Blinding Neutralization + Coppersmith Partial-`d` (source: PlaidCTF 2025 Tales from the Crypt)](#tls-rsa-bit-flipped-d-via-oob-byte--blinding-neutralization--coppersmith-partial-d-source-plaidctf-2025-tales-from-the-crypt)

---

## TLS RSA Bit-Flipped `d` via OOB-byte + Blinding Neutralization + Coppersmith Partial-`d` (source: PlaidCTF 2025 Tales from the Crypt)

**Trigger:**
- TLS 1.2 server using RSA-PKCS#1 v1.5 signatures (ServerKeyExchange or CertificateVerify) with RSA **blinding** enabled in the signing routine (`s = (r^e · m)^d · r^{-1} mod N` where `r = rand()`).
- An out-of-band channel (`MSG_OOB`, `send(..., MSG_OOB)`, or a side-channel like Rowhammer / laser injection) lets the attacker flip a small number of bits inside the private exponent `d` stored in server memory; the faulty `d_f = d XOR (rand3bits << 3*k)`.
- Same TCP session supports **renegotiation** — two handshakes sharing internal state (so the blinder's RNG state advances deterministically between them).

**Signals to grep:**
```
recv(sock, buf, 1, MSG_OOB)    # ← OOB-byte primitive corrupts a key byte
RSA_blinding_on                # ← the blinder is enabled
SSL_renegotiate / SSL_do_handshake twice on same BIO
Server sends ServerKeyExchange signed with long-term RSA
```

**Mechanic (3 phases):**

### Phase 1 — Neutralize the blinder via paired renegotiations

Because `r` advances deterministically (e.g. LCG inside OpenSSL's `BN_BLINDING`), two successive signatures `s1`, `s2` on messages `m1`, `m2` (whose blinders are linked: typically `r_2 = r_1^{-1}` after one "update" step, or `r_2 = 2·r_1` with some implementations) satisfy:

```
s1 = m1^{d_f} · r1^{-1}          # blinded by r1
s2 = m2^{d_f} · r2^{-1}          # blinded by r2 = f(r1)
```

If the relationship between `r1` and `r2` is known (e.g. `r2 = r1²`, or `r2 = 2·r1`), pick `m2 = m1²` so the blinders cancel:

```
s = s1² / s2  ≡  (m1^{2 d_f} · r1^{-2}) / (m1^{2 d_f} · r1^{-2})  ≡  m^{d_f} mod N
```

You now have a **pure** `m^{d_f} mod N` observation — no blinder left.

### Phase 2 — Recover partial `d` bit-by-bit from the fault

Each faulted signing event flips 3-8 bits of `d` at an attacker-chosen byte offset `k`. Since `(m^{d_f})^e ≠ m mod N` when bits are flipped, factor the difference:

```
m^{d_f} · m^{-d}  ≡  m^{d_f - d}  ≡  m^{Δd}  mod N
```

Compute `m^{Δd}` by knowing one valid signature (unfaulted) of the same `m` — gives you the shifted `Δd` pattern. Brute-force the 3-bit flip choice per byte position (≤ 8 candidates per byte) by checking `m^d_candidate · s^{-1} ≡ 1`. Accumulate byte-position fault observations until you have the **lower 768 bits** of `d`.

### Phase 3 — Coppersmith to finish

With `d_0 = d mod 2^768` recovered, use the classical Boneh-Durfee / Coppersmith partial-`d` attack (works when you have `≥ n/4` low bits of `d` for a balanced `n`-bit `N`):

```
e · d ≡ 1 mod lcm(p-1, q-1)
→ e·d_0 - 1 ≡ 0 mod (p-1) / 2   (approximately)
→ quadratic poly in p over Z, reducible by Coppersmith when d_0 length ≥ N/4
```

SageMath driver:
```python
# partial d recovery — Coppersmith small roots of f(p) over Z/N
PR.<x> = PolynomialRing(Zmod(N))
# e·d0 − 1 ≡ k·(p-1)(q-1)/2 for some k ≤ e;
# iterate candidate k, build f(x) = x² − (N − e*d0/k + 1)·x + N  (approx), find roots
for k in range(1, e+1):
    s_plus_q = isqrt( (N - e*d0//k + 1)**2 - 4*N )
    # then p + q = (e·d0/k + 1 + N)/…  — solve quadratic over Z
    roots = (x**2 - (N - e*d0//k + 1)*x + N).small_roots(X=2^384, beta=0.5)
    if roots:
        p = ZZ(roots[0]); q = N // p
        break
```

Recovered `p`, `q` → load into Wireshark's **RSA key log** (`.pem` from `p`,`q`,`e`) to decrypt the captured TLS application records and read the flag.

**Why this fires anywhere:** every blinding scheme must randomize BOTH `r` independently between signatures; deterministic linking + any fault primitive on `d` collapses to this attack. Check `BN_BLINDING_update`, custom Java `BigInteger` blinders, and any "improved fault countermeasure" that reuses RNG seeds.

**Companion reads:**
- [rsa-attacks-oracle.md](rsa-attacks-oracle.md) — Manger / Bleichenbacher oracles that complement blinding faults.
- [advanced-math.md](advanced-math.md) — Coppersmith & Boneh-Durfee general templates.



---

<!-- Source: rsa-attacks-oracle.md -->

# CTF Crypto - RSA Oracle Attacks

Padding/OAEP/blinding/LSB oracle attacks on RSA. For factoring attacks (Wiener, Fermat, Pollard, common-modulus, Coppersmith), see [rsa-attacks.md](rsa-attacks.md).

## Table of Contents
- [Manger's RSA Padding Oracle Attack (Nullcon 2026)](#mangers-rsa-padding-oracle-attack-nullcon-2026)
- [Manger's Attack on RSA-OAEP via Timing Oracle (HTB Early Bird)](#mangers-attack-on-rsa-oaep-via-timing-oracle-htb-early-bird)
- [RSA Blinding Defeat via TLS Renegeration (PlaidCTF 2025)](#rsa-blinding-defeat-via-tls-renegeration-plaidctf-2025)
- [Manger's Attack — RSA-OAEP First-Byte Padding Oracle (HTB Business 2025 Early Bird)](#mangers-attack--rsa-oaep-first-byte-padding-oracle-source-htb-business-2025-early-bird)

---

## Manger's RSA Padding Oracle Attack (Nullcon 2026)

**Pattern (TLS, Nullcon 2026):** RSA-encrypted key with threshold oracle. Phase 1: double f until `k*f >= threshold`. Phase 2: binary search. ~128 total queries for 64-bit key.

See [advanced-math.md](advanced-math.md) for full implementation.

---

## Manger's Attack on RSA-OAEP via Timing Oracle (HTB Early Bird)

**Pattern:** Flask app implements RSA-OAEP with custom hash (PBKDF2, 2M iterations). Python's short-circuit `or` evaluation creates a timing oracle: if the first byte Y != 0, PBKDF2 is never called (~0.6s). If Y == 0, PBKDF2 runs (~2s).

**Vulnerable code pattern:**
```python
if Y != 0 or not self.H_verify(self.L, DB[:self.hLen]) or self.os2ip(PS) != 0:
    return {"ok": False, "error": "decryption error"}
```

**Oracle mapping:** Fast response → Y != 0 (decrypted message >= B). Slow response → Y == 0 (decrypted message < B = 2^(8*(k-1))).

**Calibration for network reliability:**
```python
def calibrate(n, e, k):
    B = pow(2, 8 * (k - 1))
    slow_times, fast_times = [], []
    for i in range(5):
        # Known-slow: encrypt values < B
        enc = pow(B - 1 - i*100, e, n).to_bytes(k, 'big')
        slow_times.append(measure(enc))
        # Known-fast: encrypt values > B
        enc = pow(B + 1 + i*100, e, n).to_bytes(k, 'big')
        fast_times.append(measure(enc))
    FAST_UPPER = max(fast_times) * 1.5
    SLOW_LOWER = min(slow_times) * 0.9
```

**Oracle with retry for ambiguous results:**
```python
def padding_oracle(c_int):
    while True:
        total = measure_response_time(c_int)
        if SLOW_LOWER < total < SLOW_UPPER:
            return True   # Y == 0 (below B)
        elif total < FAST_UPPER:
            return False  # Y != 0 (above B)
        # Ambiguous: retry
```

**Full 3-step Manger's attack (~1024 iterations for 1024-bit RSA):**
```python
# Step 1: Find f1 where f1 * m >= B
f1 = 2
while oracle((pow(f1, e, n) * c) % n):
    f1 *= 2

# Step 2: Find f2 where n <= f2 * m < n + B
f2 = (n + B) // B * f1 // 2
while not oracle((pow(f2, e, n) * c) % n):
    f2 += f1 // 2

# Step 3: Binary search narrowing m to exact value
mmin, mmax = ceil_div(n, f2), floor_div(n + B, f2)
while mmin < mmax:
    f = floor_div(2 * B, mmax - mmin)
    i = floor_div(f * mmin, n)
    f3 = ceil_div(i * n, mmin)
    if oracle((pow(f3, e, n) * c) % n):
        mmax = floor_div(i * n + B, f3)
    else:
        mmin = ceil_div(i * n + B, f3)
m = mmin
```

**Post-recovery OAEP decode:**
```python
from Crypto.Signature.pss import MGF1
maskedSeed = EM[1:hLen+1]
maskedDB = EM[hLen+1:]
seed = bytes(a ^ b for a, b in zip(maskedSeed, MGF1(maskedDB, hLen, HF)))
DB = bytes(a ^ b for a, b in zip(maskedDB, MGF1(seed, k - hLen - 1, HF)))
# DB[:hLen] should match lHash; rest is 0x00...0x01 || message
```

**Key insight:** Python's `or` short-circuits left-to-right. When expensive operations (PBKDF2, bcrypt, argon2) appear in chained conditions, the first condition becomes a timing oracle. RFC 8017 explicitly warns implementations must not let attackers distinguish error conditions — timing differences violate this.

**Detection:** RSA-OAEP with custom hash or slow KDF. Flask/Python backend. `/verify-token` or similar decryption endpoint returning generic errors. Timing differences between responses.

---

## RSA Blinding Defeat via TLS Renegeration (PlaidCTF 2025)

**Pattern ("Tales from the Crypt"):** OpenSSL RSA-CRT fault-attack mitigation uses blinding: per-session, signature is computed as `S = blind * (m * blind^(-e))^d mod n`, where `blind = A` is a fresh random. Bug: on **TLS renegotiation**, the implementation updates the blinder as `A -> A^2` instead of regenerating. Two faulted signatures under *related* blinders let you eliminate `A` algebraically and recover the corrupted bit of `d`.

**Core math:** If session 1 uses blinder `A` and leaks a faulty signature `S1 = m^(d + eps1) * A (mod n)`, and session 2 (after reneg) uses `A^2` leaking `S2 = m^(d + eps2) * A^2 (mod n)`, then:
```
S1^2 / S2 = m^(2*eps1 - eps2) (mod n)
```
The unknown blinder cancels. Comparing the resulting value against expected bit-flip deltas recovers `d` bit-by-bit.

**Why it's a new class:** not a pure math attack and not a pure implementation bug — a **protocol-crypto crossover**. The weakness lives in the TLS state-machine assumption that a renegotiated session is independent.

**Exploitation checklist:**
1. Inject a fault (e.g. Rowhammer, clock glitch, or server already leaks faulty signatures) during sign.
2. Force TLS renegotiation before grabbing a second signature.
3. Compute `S1^2 * S2^(-1) mod n` — the blinder cancels.
4. Iterate bit-by-bit: each bit of `d` gives two possible eps values; one matches, the other doesn't.

**Takeaway for CTFs:** when you see RSA + TLS renegotiation + "weird" signatures, assume blinder is related across sessions and look for `S1^2 / S2` style algebraic cancellation.

Source: [jsur.in/posts/2025-04-07-plaid-ctf-2025-tales-from-the-crypt](https://jsur.in/posts/2025-04-07-plaid-ctf-2025-tales-from-the-crypt/).

---

## Manger's Attack — RSA-OAEP First-Byte Padding Oracle (source: HTB Business 2025 Early Bird)

**Trigger:** OAEP-decrypting service whose response distinguishes `m ≥ B` vs `m < B` (where `B = 2^(8·(k-1))`), typically via "invalid padding" vs "invalid message" error differentiation.
**Signals:** `RSAES-OAEP` / `OAEP` in code, two distinguishable error branches, ability to submit ciphertexts adaptively.
**Mechanic:** binary search via multiplicative blinding `c' = c · s^e mod n`. Each oracle query halves the interval. Recovers `m` in ~`log2(n)` queries — ~2048 for 2048-bit RSA. Reference: Manger "A chosen ciphertext attack on RSA optimal asymmetric encryption padding" (2001).
Template:
```python
def manger(c, e, n, oracle, k):
    B = 1 << (8*(k-1))
    # f1 step
    f1 = 2
    while oracle(pow(f1, e, n) * c % n): f1 *= 2
    ...
```



---

<!-- Source: rsa-attacks.md -->

# CTF Crypto - RSA Attacks

## Table of Contents
- [Small Public Exponent (Cube Root)](#small-public-exponent-cube-root)
- [Common Modulus Attack](#common-modulus-attack)
- [Wiener's Attack (Small Private Exponent)](#wieners-attack-small-private-exponent)
- [Pollard's p-1 Factorization](#pollards-p-1-factorization)
- [Hastad's Broadcast Attack](#hastads-broadcast-attack)
- [RSA with Consecutive Primes (Fermat Factorization)](#rsa-with-consecutive-primes-fermat-factorization)
- [Multi-Prime RSA](#multi-prime-rsa)
- [RSA with Restricted-Digit Primes (LACTF 2026)](#rsa-with-restricted-digit-primes-lactf-2026)
- [Coppersmith for Structured RSA Primes (LACTF 2026)](#coppersmith-for-structured-rsa-primes-lactf-2026)
- [Polynomial Hash with Trivial Root (Pragyan 2026)](#polynomial-hash-with-trivial-root-pragyan-2026)
- [Polynomial CRT in GF(2)[x] (Nullcon 2026)](#polynomial-crt-in-gf2x-nullcon-2026)
- [Affine Cipher over Non-Prime Modulus (Nullcon 2026)](#affine-cipher-over-non-prime-modulus-nullcon-2026)
- [RSA p=q Validation Bypass (BearCatCTF 2026)](#rsa-pq-validation-bypass-bearcatctf-2026)
- [RSA Cube Root CRT when gcd(e, phi) > 1 (BearCatCTF 2026)](#rsa-cube-root-crt-when-gcde-phi--1-bearcatctf-2026)
- [Factoring n from Multiple of phi(n) (BearCatCTF 2026)](#factoring-n-from-multiple-of-phin-bearcatctf-2026)
- [RSA Signature Forgery via Multiplicative Homomorphism (MMA CTF 2015)](#rsa-signature-forgery-via-multiplicative-homomorphism-mma-ctf-2015)
- [RSA Fixed-Point Factoring (404CTF "Un point c'est tout")](#rsa-fixed-point-factoring-404ctf-un-point-cest-tout)
- [Structured-Prime Polynomial Factorisation (HTB Business 2025 Got Ransomed)](#structured-prime-polynomial-factorisation-source-htb-business-2025-got-ransomed)

For padding/OAEP/blinding/LSB oracle attacks on RSA, see [rsa-attacks-oracle.md](rsa-attacks-oracle.md).

---

## Small Public Exponent (Cube Root)

**Pattern:** Small `e` (typically 3) with small message. When `m^e < n`, the ciphertext is just `m^e` without modular reduction — take the integer eth root.

```python
import gmpy2

def small_e_attack(c, e):
    """Recover plaintext when m^e < n (no modular wrap)."""
    m, exact = gmpy2.iroot(c, e)
    if exact:
        return int(m)
    return None

# Usage
m = small_e_attack(c, e=3)
print(bytes.fromhex(hex(m)[2:]))
```

**When it fails:** If `m^e > n` (message padded or large), the modular reduction destroys the simple root. In that case, try Hastad's broadcast attack or Coppersmith's short-pad attack.

---

## Common Modulus Attack

**Pattern:** Same message encrypted with same `n` but two different public exponents `e1`, `e2` where `gcd(e1, e2) = 1`. Recover plaintext without factoring `n`.

```python
from math import gcd

def common_modulus_attack(c1, c2, e1, e2, n):
    """Recover plaintext from two encryptions with same n, coprime e1/e2."""
    # Extended GCD: find a, b such that a*e1 + b*e2 = 1
    def extended_gcd(a, b):
        if a == 0: return b, 0, 1
        g, x, y = extended_gcd(b % a, a)
        return g, y - (b // a) * x, x

    g, a, b = extended_gcd(e1, e2)
    assert g == 1, "e1 and e2 must be coprime"

    # m = c1^a * c2^b mod n
    # Handle negative exponent by using modular inverse
    if a < 0:
        c1 = pow(c1, -1, n)
        a = -a
    if b < 0:
        c2 = pow(c2, -1, n)
        b = -b
    m = (pow(c1, a, n) * pow(c2, b, n)) % n
    return m
```

**Key insight:** Two encryptions of the same message under the same modulus but different exponents leak the plaintext via Bezout's identity. No factoring required.

---

## Wiener's Attack (Small Private Exponent)

**Pattern:** Private exponent `d` is small (d < N^0.25). The continued fraction expansion of `e/n` reveals `d`.

```python
def wiener_attack(e, n):
    """Recover d when d < N^0.25 using continued fraction expansion of e/n."""
    def continued_fraction(num, den):
        cf = []
        while den:
            q, r = divmod(num, den)
            cf.append(q)
            num, den = den, r
        return cf

    def convergents(cf):
        convs = []
        h0, h1 = 0, 1
        k0, k1 = 1, 0
        for a in cf:
            h0, h1 = h1, a * h1 + h0
            k0, k1 = k1, a * k1 + k0
            convs.append((h1, k1))
        return convs

    cf = continued_fraction(e, n)
    for k, d in convergents(cf):
        if k == 0:
            continue
        # Check if d is valid: phi = (e*d - 1) / k must be integer
        if (e * d - 1) % k != 0:
            continue
        phi = (e * d - 1) // k
        # phi = (p-1)(q-1) = n - p - q + 1, so p+q = n - phi + 1
        s = n - phi + 1
        # p and q are roots of x^2 - s*x + n = 0
        discriminant = s * s - 4 * n
        if discriminant < 0:
            continue
        from math import isqrt
        t = isqrt(discriminant)
        if t * t == discriminant:
            return d
    return None

# Usage
d = wiener_attack(e, n)
m = pow(c, d, n)
```

**When to use:** Very large `e` (close to `n`) often indicates small `d`. Also try `owiener` Python package: `pip install owiener`.

---

## Pollard's p-1 Factorization

**Pattern:** One prime factor `p` has a smooth `p-1` (all prime factors of `p-1` are small). Compute `a^(B!) mod n`; GCD with `n` reveals `p`.

```python
from math import gcd

def pollard_p1(n, B=100000):
    """Factor n when p-1 is B-smooth for some prime factor p."""
    a = 2
    for j in range(2, B + 1):
        a = pow(a, j, n)
        d = gcd(a - 1, n)
        if 1 < d < n:
            return d, n // d
    return None

# Usage
result = pollard_p1(n)
if result:
    p, q = result
```

**Key insight:** By Fermat's little theorem, if `p-1` divides `B!`, then `a^(B!) ≡ 1 (mod p)`, so `gcd(a^(B!) - 1, n)` gives `p`. Increase `B` for larger smooth bounds. CTF primes generated with `getStrongPrime()` or similar are resistant.

---

## Hastad's Broadcast Attack

**Pattern:** Same plaintext `m` encrypted with `e` different public keys (all with exponent `e`, typically `e=3`). Use CRT to reconstruct `m^e`, then take the eth root.

```python
from functools import reduce

def hastad_broadcast(ciphertexts, moduli, e):
    """Recover m from e encryptions with the same exponent e."""
    assert len(ciphertexts) >= e and len(moduli) >= e

    # Chinese Remainder Theorem
    def crt(remainders, moduli):
        N = reduce(lambda a, b: a * b, moduli)
        result = 0
        for r, m in zip(remainders, moduli):
            Ni = N // m
            Mi = pow(Ni, -1, m)
            result += r * Ni * Mi
        return result % N

    # CRT gives m^e (mod N1*N2*...*Ne)
    # Since m < each Ni, m^e < N1*N2*...*Ne, so no modular reduction occurred
    me = crt(ciphertexts[:e], moduli[:e])

    import gmpy2
    m, exact = gmpy2.iroot(me, e)
    if exact:
        return int(m)
    return None

# Usage (e=3, three encryptions)
m = hastad_broadcast([c1, c2, c3], [n1, n2, n3], e=3)
print(bytes.fromhex(hex(m)[2:]))
```

**Key insight:** CRT reconstructs `m^e` exactly (no modular reduction) because `m < min(n_i)` and therefore `m^e < n_1 * n_2 * ... * n_e`. Taking the integer eth root recovers `m`.

---

## RSA with Consecutive Primes (Fermat Factorization)

**Pattern (Loopy Primes):** q = next_prime(p), making p ~ q ~ sqrt(N). Also known as Fermat factorization — works whenever `|p - q|` is small.

**Factorization:** Find first prime below sqrt(N):
```python
from sympy import nextprime, prevprime, isqrt

root = isqrt(n)
p = prevprime(root + 1)
while n % p != 0:
    p = prevprime(p)
q = n // p
```

**Multi-layer variant:** 1024 nested RSA encryptions, each with consecutive primes of increasing bit size. Decrypt in reverse order.

---

## Multi-Prime RSA

When N is product of many small primes (not just p*q):
```python
# Factor N (easier when many primes)
from sympy import factorint
factors = factorint(n)  # Returns {p1: e1, p2: e2, ...}

# Compute phi using all factors
phi = 1
for p, e in factors.items():
    phi *= (p - 1) * (p ** (e - 1))

d = pow(e, -1, phi)
plaintext = pow(ciphertext, d, n)
```

---

## RSA with Restricted-Digit Primes (LACTF 2026)

**Pattern (six-seven):** RSA primes p, q composed only of digits {6, 7}, ending in 7.

**Digit-by-digit factoring from LSB:**
```python
# At each step k, we know p mod 10^k -> compute q mod 10^k = n * p^{-1} mod 10^k
# Prune: only keep candidates where digit k of both p and q is in {6, 7}
candidates = [(6,), (7,)]  # p ends in 6 or 7
for k in range(1, num_digits):
    new_candidates = []
    for p_digits in candidates:
        for d in [6, 7]:
            p_val = sum(p_digits[i] * 10**i for i in range(len(p_digits))) + d * 10**k
            q_val = (n * pow(p_val, -1, 10**(k+1))) % 10**(k+1)
            q_digit_k = (q_val // 10**k) % 10
            if q_digit_k in {6, 7}:
                new_candidates.append(p_digits + (d,))
    candidates = new_candidates
```

**General lesson:** When prime digits are restricted to a small set, digit-by-digit recovery from LSB with modular arithmetic prunes exponentially. Works for any restricted character set.

---

## Coppersmith for Structured RSA Primes (LACTF 2026)

**Pattern (six-seven-again):** p = base + 10^k * x where base is fully known and x is small (x < N^0.25).

**Attack via SageMath:**
```python
# Construct f(x) such that f(x_secret) = 0 (mod p) and thus (mod N)
# p = base + 10^k * x -> x + base * (10^k)^{-1} = 0 (mod p)
R.<x> = PolynomialRing(Zmod(N))
f = x + (base * inverse_mod(10**k, N)) % N
roots = f.small_roots(X=2**70, beta=0.5)  # x < N^0.25
```

**When to use:** Whenever part of a prime is known and the unknown part is small enough for Coppersmith bounds (< N^{1/e} for degree-e polynomial, approximately N^0.25 for linear).

---


## Polynomial Hash with Trivial Root (Pragyan 2026)

**Pattern (!!Cand1esaNdCrypt0!!):** RSA signature scheme using polynomial hash `g(x,a,b) = x(x^2 + ax + b) mod P`.

**Vulnerability:** `g(0) = 0` for all parameters `a,b`. RSA signature of 0 is always 0 (`0^d mod n = 0`).

**Exploitation:** Craft message suffix so `bytes_to_long(prefix || suffix) = 0 (mod P)`:
```python
P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF61  # 128-bit prime
# Compute required suffix value mod P
req = (-prefix_val * pow(256, suffix_len, P)) % P
# Brute-force partial bytes until all printable ASCII
while True:
    high = os.urandom(32).translate(printable_table)
    low_val = (req - int.from_bytes(high, 'big') * shift) % P
    low = low_val.to_bytes(16, 'big')
    if all(32 <= b <= 126 for b in low):
        suffix = high + low
        break
# Signature is simply 0
```

**General lesson:** Always check if hash function has trivial inputs (0, 1, -1). Factoring the polynomial often reveals these.

---

## Polynomial CRT in GF(2)[x] (Nullcon 2026)

**Pattern (Going in Circles, Nullcon 2026):** `r = flag mod f` where f is random GF(2) polynomial. Collect ~20 pairs, filter coprime, CRT combine.

See [advanced-math.md](advanced-math.md) for GF(2)[x] polynomial arithmetic and CRT implementation.

---

## Affine Cipher over Non-Prime Modulus (Nullcon 2026)

**Pattern (Matrixfun, Nullcon 2026):** `c = A @ p + b (mod m)` with composite m. Chosen-plaintext difference attack. For composite modulus, solve via CRT in each prime factor field separately.

See [advanced-math.md](advanced-math.md) for CRT approach and Gauss-Jordan implementation.

---

## RSA p=q Validation Bypass (BearCatCTF 2026)

**Pattern (Pickme):** Server validates user-submitted RSA key (checks `n`, `e`, `d`, `p*q=n`, `e*d ≡ 1 mod phi`), encrypts the flag, then tries test decryption. If decryption fails, leaks ciphertext in error message.

**Exploit:** Set `p = q`. The server computes `phi = (p-1)*(q-1) = (p-1)^2` (incorrect — real totient of `p^2` is `p*(p-1)`). All validation checks pass, but decryption with the wrong `d` fails, leaking the ciphertext.

```python
from Crypto.Util.number import getPrime, inverse

p = getPrime(512)
q = p  # p = q!
n = p * q  # = p^2
e = 65537
wrong_phi = (p - 1) * (q - 1)  # = (p-1)^2
d = inverse(e, wrong_phi)  # passes server validation

# Server encrypts flag with our key, test decryption fails → leaks ciphertext c
# Decrypt with correct totient:
real_phi = p * (p - 1)
real_d = inverse(e, real_phi)
flag = pow(c, real_d, n)
```

**Key insight:** `phi(p^2) = p*(p-1)`, NOT `(p-1)^2`. When a server validates RSA parameters but uses `(p-1)*(q-1)` without checking `p != q`, setting `p=q` creates a working key that the server will miscompute the private exponent for, causing decryption failure and error-path data leakage.

---

## RSA Cube Root CRT when gcd(e, phi) > 1 (BearCatCTF 2026)

**Pattern (Kidd's Crypto):** RSA with `e=3`, modulus composed of many small primes all ≡ 1 (mod 3). Since each `p-1` is divisible by 3, `gcd(e, phi(n)) = 3^k` and the standard modular inverse `d = e^-1 mod phi` doesn't exist.

**Solution:** Compute cube roots per-prime via CRT:
```python
from sympy.ntheory.residues import nthroot_mod
from sympy.ntheory.modular import crt

primes = [p1, p2, ..., p13]  # All ≡ 1 mod 3

# For each prime, find all 3 cube roots of c mod p
roots_per_prime = []
for p in primes:
    roots = nthroot_mod(c % p, 3, p, all_roots=True)
    roots_per_prime.append(roots)

# Try all 3^13 = 1,594,323 combinations
from itertools import product
for combo in product(*roots_per_prime):
    result, mod = crt(primes, list(combo))
    try:
        text = long_to_bytes(result).decode('ascii')
        if text.isprintable():
            print(f"Flag: {text}")
            break
    except:
        continue
```

**Key insight:** When `gcd(e, phi(n)) > 1`, standard RSA decryption fails. Factor `n`, compute eth roots modulo each prime separately (each prime ≡ 1 mod e gives `e` roots), then enumerate all CRT combinations. Feasible when the number of primes is small (3^13 ≈ 1.6M combinations).

---

## Factoring n from Multiple of phi(n) (BearCatCTF 2026)

**Pattern (Twisted Pair):** Given RSA `n` and a leaked pair `(re, rd)` where `re * rd ≡ 1 (mod k*phi(n))`. The value `re*rd - 1` is a multiple of `phi(n)`, enabling probabilistic factoring.

```python
import random
from math import gcd

def factor_from_phi_multiple(n, phi_multiple):
    """Factor n given any multiple of phi(n) using Miller-Rabin variant."""
    # Write phi_multiple = 2^s * d where d is odd
    s, d = 0, phi_multiple
    while d % 2 == 0:
        s += 1
        d //= 2

    for _ in range(100):  # 100 attempts
        a = random.randrange(2, n - 1)
        x = pow(a, d, n)
        if x == 1 or x == n - 1:
            continue
        for _ in range(s - 1):
            prev = x
            x = pow(x, 2, n)
            if x == n - 1:
                break
            if x == 1:
                # prev is non-trivial square root of 1
                p = gcd(prev - 1, n)
                if 1 < p < n:
                    return p, n // p
        # Check final
        if x != n - 1:
            p = gcd(x - 1, n)
            if 1 < p < n:
                return p, n // p
    return None

phi_mult = re * rd - 1
p, q = factor_from_phi_multiple(n, phi_mult)
```

**Key insight:** Any multiple of `phi(n)` — not just `phi(n)` itself — enables factoring via the Miller-Rabin square root technique. If a server leaks `e*d` for any key pair, or if `re*rd - 1` is given, compute `gcd(a^(m/2) - 1, n)` for random `a` values. Succeeds with probability ≥ 1/2 per attempt.

---

## RSA Signature Forgery via Multiplicative Homomorphism (MMA CTF 2015)

**Pattern:** Signing oracle refuses to sign the target message `m` but will sign other values. Unpadded RSA is multiplicatively homomorphic: `S(a) * S(b) mod n == S(a * b) mod n`.

```python
# Factor target message and sign each factor separately
divisor = 2
assert target_msg % divisor == 0
sig_a = sign_oracle(target_msg // divisor)
sig_b = sign_oracle(divisor)
forged_sig = (sig_a * sig_b) % n
```

**Key insight:** Textbook RSA signatures are homomorphic: `m^d mod n` preserves multiplication. If the oracle blacklists `m` but signs its factors, multiply the partial signatures. To find a suitable factorization, try small divisors (2, 3, ...) until `m / divisor` also passes the blacklist check. This is why PKCS#1 padding is essential — padded messages cannot be factored into other valid padded messages.

---

## RSA Fixed-Point Factoring (404CTF "Un point c'est tout")

**Pattern:** Oracle leaks a **fixed point** of the RSA permutation — a value `F` where `F^e ≡ F (mod n)`. In practice: timing side-channel (encryption/decryption is unusually fast on `F` because `F^e = F` reduces without work) or behaviour difference.

**Why it factors n:** Fixed points of `x -> x^e mod n` correspond (via CRT) to combinations of fixed points of `x^e mod p` and `x^e mod q`. Non-trivial ones (i.e. `F ≠ 0, 1, n-1`) leak factorisation:

```python
from math import gcd

# Given a fixed point F such that pow(F, e, n) == F and F not in {0, 1, n-1}
p_candidate = gcd(F, n)          # or gcd(F-1, n), gcd(F+1, n)
if 1 < p_candidate < n:
    p = p_candidate
    q = n // p
```

Try `gcd(F, n)`, `gcd(F-1, n)`, `gcd(F+1, n)` — one of them yields a prime factor.

**How to spot fixed points:**
- Timing outlier on an input (encryption/decryption "too fast").
- Idempotent behaviour: `E(E(x)) == E(x)`.
- Challenge gives you a small pool of possible messages and asks you to submit one — test each for `pow(m, e, n) == m`.

**Countermeasure:** proper padding (OAEP) destroys the algebraic structure — never sign/encrypt raw group elements.

Source: [eshard.com/posts/404ctf-un-point](https://eshard.com/posts/404ctf-un-point).

---

## Structured-Prime Polynomial Factorisation (source: HTB Business 2025 Got Ransomed)

**Trigger:** modulus printed in hex reveals a visible periodic structure; primes of form `u·2^1024 + u·v + w` with small `u, v, w`.
**Signals:** hex dump of `n` shows large blocks of zeros followed by small coefficients; README hints at "custom key-gen".
**Mechanic:** write `n = a·x² + b·x + c` with `x = 2^1024`; read `a, b, c` directly from the hex dump. Factor the polynomial in SymPy (`sympy.factor_list`) to recover `p, q`. Generalises to any `n` built via a low-degree polynomial with small integer coefficients.
Source: [synacktiv.com/en/publications/htb-business-ctf-write-ups](https://www.synacktiv.com/en/publications/htb-business-ctf-write-ups).



---

<!-- Source: zkp-and-advanced.md -->

# CTF Crypto - ZKP, Solvers & Advanced Techniques

## Table of Contents
- [ZKP Attacks](#zkp-attacks)
- [Graph 3-Coloring](#graph-3-coloring)
- [Z3 SMT Solver Guide](#z3-smt-solver-guide)
- [Garbled Circuits: Free XOR Delta Recovery (LACTF 2026)](#garbled-circuits-free-xor-delta-recovery-lactf-2026)
- [Bigram/Trigram Substitution -> Constraint Solving (LACTF 2026)](#bigramtrigram-substitution---constraint-solving-lactf-2026)
- [Shamir Secret Sharing with Deterministic Coefficients (LACTF 2026)](#shamir-secret-sharing-with-deterministic-coefficients-lactf-2026)
- [Race Condition in Crypto-Protected Endpoints (LACTF 2026)](#race-condition-in-crypto-protected-endpoints-lactf-2026)
- [Garbled Circuits: AES Key Recovery via Metadata Leakage (srdnlenCTF 2026)](#garbled-circuits-aes-key-recovery-via-metadata-leakage-srdnlenctf-2026)
- [Post-Quantum Signature Fault Injection: MAYO (srdnlenCTF 2026)](#post-quantum-signature-fault-injection-mayo-srdnlenctf-2026)
- [Lattice-Based Threshold Signature Attack: FROST (srdnlenCTF 2026)](#lattice-based-threshold-signature-attack-frost-srdnlenctf-2026)
- [Groth16 Broken Trusted Setup — delta == gamma (DiceCTF 2026)](#groth16-broken-trusted-setup--delta--gamma-dicectf-2026)
- [Groth16 Proof Replay — Unconstrained Nullifier (DiceCTF 2026)](#groth16-proof-replay--unconstrained-nullifier-dicectf-2026)
- [DV-SNARG Forgery via Verifier Oracle (DiceCTF 2026)](#dv-snarg-forgery-via-verifier-oracle-dicectf-2026)
- [KZG Pairing Oracle for Permutation Recovery (UNbreakable 2026)](#kzg-pairing-oracle-for-permutation-recovery-unbreakable-2026)

---

## ZKP Attacks

- Look for information leakage in proofs
- If proving IMPOSSIBLE problem (e.g., 3-coloring K4), you must cheat
- Find hash collisions to commit to one value but reveal another
- PRNG state recovery: salts generated from seeded PRNG can be predicted
- Small domain brute force: if you know `commit(i) = sha256(salt(i), color(i))` and have salt, brute all colors

---

## Graph 3-Coloring

```python
import networkx as nx
nx.coloring.greedy_color(G, strategy='saturation_largest_first')
```

---

## Z3 SMT Solver Guide

Z3 solves constraint satisfaction - useful when crypto reduces to finding values satisfying conditions.

**Basic usage:**
```python
from z3 import *

# Boolean variables (for bit-level problems)
bits = [Bool(f'b{i}') for i in range(64)]

# Integer/bitvector variables
x = BitVec('x', 32)  # 32-bit bitvector
y = Int('y')         # arbitrary precision int

solver = Solver()
solver.add(x ^ 0xdeadbeef == 0x12345678)
solver.add(y > 100, y < 200)

if solver.check() == sat:
    model = solver.model()
    print(model.eval(x))
```

**BPF/SECCOMP filter solving:**

When challenges use BPF bytecode for flag validation (e.g., custom syscall handlers):

```python
from z3 import *

# Model flag as array of 4-byte chunks (how BPF sees it)
flag = [BitVec(f'f{i}', 32) for i in range(14)]
s = Solver()

# Constraint: printable ASCII
for f in flag:
    for byte in range(4):
        b = (f >> (byte * 8)) & 0xff
        s.add(b >= 0x20, b < 0x7f)

# Extract constraints from BPF dump (seccomp-tools dump ./binary)
mem = [BitVec(f'm{i}', 32) for i in range(16)]

# Example BPF constraint reconstruction
s.add(mem[0] == flag[0])
s.add(mem[1] == mem[0] ^ flag[1])
s.add(mem[4] == mem[0] + mem[1] + mem[2] + mem[3])
s.add(mem[8] == 4127179254)  # From BPF if statement

if s.check() == sat:
    m = s.model()
    flag_bytes = b''
    for f in flag:
        val = m[f].as_long()
        flag_bytes += val.to_bytes(4, 'little')
    print(flag_bytes.decode())
```

**Converting bits to flag:**
```python
from Crypto.Util.number import long_to_bytes

if solver.check() == sat:
    model = solver.model()
    flag_bits = ''.join('1' if model.eval(b) else '0' for b in bits)
    print(long_to_bytes(int(flag_bits, 2)))
```

**When to use Z3:**
- Type system constraints (OCaml GADTs, Haskell types)
- Custom hash/cipher with algebraic structure
- Equation systems over finite fields
- Boolean satisfiability encoded in challenge
- Constraint propagation puzzles

---

## Garbled Circuits: Free XOR Delta Recovery (LACTF 2026)

**Pattern (sisyphus):** Yao's garbled circuit with free XOR optimization. Circuit designed so normal evaluation only reaches one wire label, but the other is needed.

**Free XOR property:** Wire labels satisfy `W_0 XOR W_1 = delta` for global secret delta.

**Attack:** XOR three of four encrypted truth table entries to cancel AES terms:
```python
# Encrypted rows: E_i = AES(key_a_i XOR key_b_i, G_out_f(a,b))
# XOR of three rows where AES inputs differ by delta causes cancellation
# Reveals delta directly, then compute: W_1 = W_0 XOR delta
```

**General lesson:** In garbled circuits, if you can obtain any two labels for the same wire, you recover delta and can compute all labels.

---

## Bigram/Trigram Substitution -> Constraint Solving (LACTF 2026)

**Pattern (lazy-bigrams):** Bigram substitution cipher where plaintext has known structure (NATO phonetic alphabet).

**OR-Tools CP-SAT approach:**
1. Model substitution as injective mapping (IntVar per bigram)
2. Add crib constraints from known flag prefix
3. Add **regular language constraint** (automaton) for valid NATO word sequences
4. Solver finds unique solution

**Pattern (not-so-lazy-trigrams):** "Trigram substitution" that decomposes into three independent monoalphabetic ciphers on positions mod 3.

**Decomposition insight:** If cipher uses `shuffle[pos % n][char]`, each residue class `pos = k (mod n)` is an independent monoalphabetic substitution. Solve each separately with frequency analysis or known-plaintext.

---

## Shamir Secret Sharing with Deterministic Coefficients (LACTF 2026)

**Pattern (spreading-secrets):** Coefficients `a_1...a_9` are deterministic functions of secret s (via RNG seeded with s). One share (x_0, y_0) is revealed.

**Vulnerability:** Given one share, the equation `y_0 = s + g(s)*x_0 + g^2(s)*x_0^2 + ... + g^9(s)*x_0^9` is **univariate** in s.

**Root-finding via Frobenius:**
```python
# In GF(p), find roots of h(s) via gcd with x^p - x
# h(s) = s + g(s)*x_0 + ... + g^9(s)*x_0^9 - y_0
# Compute x^p mod h(x) via binary exponentiation with polynomial reduction
# gcd(x^p - x, h(x)) = product of (x - root_i) for all roots
R.<x> = PolynomialRing(GF(p))
h = construct_polynomial(x0, y0)
xp = pow(x, p, h)  # Fast modular exponentiation
g = gcd(xp - x, h)  # Extract linear factors
roots = [-g[0]/g[1]] if g.degree() == 1 else g.roots()
```

**General lesson:** If ALL Shamir coefficients are derived from the secret, a single share creates a univariate equation. This completely breaks the (k,n) threshold scheme.

---

## Race Condition in Crypto-Protected Endpoints (LACTF 2026)

**Pattern (misdirection):** Endpoint has TOCTOU vulnerability: `if counter < 4` check happens before increment, allowing concurrent requests to all pass the check.

**Exploitation:**
1. **Cache-bust signatures:** Modify each request slightly (e.g., prepend zeros to nonce) so server can't use cached verification results
2. **Synchronize requests:** Use multiprocessing with barrier to send ~80 simultaneous requests
3. All pass `counter < 4` check before any increments -> counter jumps past limit

```python
from multiprocessing import Process, Barrier
barrier = Barrier(80)

def make_request(barrier, modified_sig):
    barrier.wait()  # Synchronize all processes
    requests.post(url, json={"sig": modified_sig})

# Launch 80 processes with unique signature modifications
processes = [Process(target=make_request, args=(barrier, modify_sig(i))) for i in range(80)]
```

**Key insight:** TOCTOU in `check-then-act` patterns. Look for read-modify-write without atomicity/locking.

---

## Garbled Circuits: AES Key Recovery via Metadata Leakage (srdnlenCTF 2026)

**Pattern (FHAES):** Service evaluates AES via garbled circuits with a fixed per-connection key. Exploit garbling metadata rather than AES cryptanalysis.

**Attack:**
1. Construct a custom circuit with one attacker-controlled AND gate that leaks the global Free-XOR offset delta
2. Use delta to locally evaluate the key-schedule section (first 1360 AND gates) as the evaluator
3. For each of the first 16 key-schedule S-box calls, brute-force the input byte by re-garbling the S-box chunk and comparing observed AND tables
4. Reconstruct key words from S-box outputs and recover the full 128-bit key through algebraic manipulation of the AES-128 schedule recurrence

```python
def garble_and(A, B, D, and_idx):
    """Reproduce garbling with proper parity handling."""
    r = B & 1
    alpha = A & 1
    beta = B & 1
    # Computes gate0, gate1, z output via hash-based approach
    return gate0, gate1, z

def evaluator_and(A, B, gate0, gate1, and_idx):
    """Evaluate AND gate using hash-based approach."""
    hashA = h_wire(A, and_idx)
    hashB = h_wire(B, and_idx)
    L = hashA if (A & 1) == 0 else (hashA ^ gate0)
    R = hashB if (B & 1) == 0 else (hashB ^ gate1)
    return L ^ R ^ (A * (B & 1))
```

**Key insight:** Garbled circuits that use free XOR optimization with fixed keys across sessions leak key material through the AND gate truth tables. Each S-box has a small enough input space (256 values) to brute-force when you know delta. This extends the LACTF technique from "recovering delta" to "recovering the entire AES key."

---

## Post-Quantum Signature Fault Injection: MAYO (srdnlenCTF 2026)

**Pattern (Faulty Mayo):** One-byte fault injection window in `mayo_sign_signature` before final `s = v + O*x` construction. Controlled bit flips across 64 signature queries recover the secret matrix O row by row.

**Attack:**
1. Reverse binary to map fault offsets to `mayo_sign_signature` instructions
2. For each of 64 rows of secret matrix O, use faulted signatures to extract linear equations over GF(16)
3. Solve 17-variable linear systems over GF(16) for each row using Gaussian elimination
4. Rebuild equivalent signer using recovered O and public seed from compressed public key
5. Forge valid signature for challenge message

**GF(16) Gaussian elimination:**
```python
# Precompute multiplication and inverse tables for GF(16)
# GF(16) = GF(2)[x] / (x^4 + x + 1), elements 0-15
INV = [0] * 16  # multiplicative inverses
MUL = [[0]*16 for _ in range(16)]  # multiplication table

def solve_linear_gf16(equations, nvars=17):
    """Gaussian elimination over GF(16)."""
    A = [x[:] + [y] for x, y in equations]
    m, row = len(A), 0
    for col in range(nvars):
        piv = next((r for r in range(row, m) if A[r][col] != 0), None)
        if piv is None: continue
        A[row], A[piv] = A[piv], A[row]
        invp = INV[A[row][col]]
        A[row] = [MUL[invp][v] for v in A[row]]
        for r in range(m):
            if r != row and A[r][col] != 0:
                f = A[r][col]
                A[r] = [A[r][c] ^ MUL[f][A[row][c]] for c in range(nvars + 1)]
        row += 1
    return [A[i][nvars] for i in range(nvars)]
```

**Key insight:** Post-quantum signature schemes like MAYO can be broken with fault injection if you can cause controlled bit flips during signing. Each fault creates a linear equation over GF(16), and 17+ equations per row suffice to recover the secret. This is analogous to DFA on classical schemes but over extension fields.

---

## Lattice-Based Threshold Signature Attack: FROST (srdnlenCTF 2026)

**Pattern (Threshold):** Preprocessing queue capacity allows collecting many signatures. Fixed challenge construction enables solving 1D noisy linear equations per coefficient.

**Attack:**
1. Exploit queue-depth cap (≤8 active) rather than total-usage cap by alternating menu options
2. Force fixed challenge `c` by choosing commitment `w₀` each query to zero aggregate commitment before high-bit extraction
3. With fixed `c`, each coefficient becomes: `z = λ·u + noise (mod q)`
4. Select multiple signer subsets to obtain different Lagrange coefficient scales (small/mid/huge) for each target signer
5. Solve via interval intersection and maximum-likelihood selection
6. Recover 7 signer shares; combine with own share; reconstruct master secret via Lagrange interpolation

**Interval intersection algorithm:**
```python
from math import ceil, floor

def intersect_intervals(intervals, lam, z, q, B):
    """Refine candidate intervals using one (λ, z) observation with noise bound B."""
    out = []
    for lo, hi in intervals:
        if lam > 0:
            kmin = ceil((lam * lo - z - B) / q)
            kmax = floor((lam * hi - z + B) / q)
            for k in range(kmin, kmax + 1):
                a = (z + q * k - B) / lam
                b = (z + q * k + B) / lam
                lo2, hi2 = max(lo, a), min(hi, b)
                if lo2 <= hi2:
                    out.append((lo2, hi2))
    # Merge overlapping intervals
    out.sort()
    merged = [out[0]] if out else []
    for lo, hi in out[1:]:
        if lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged
```

**Key insight:** Threshold signature schemes can leak individual shares when the challenge value is controlled. By querying with different signer subsets, you get different Lagrange coefficient scales for the same unknown share, allowing iterative interval refinement. With enough observations, the interval converges to a unique value.

---

## Groth16 Broken Trusted Setup — delta == gamma (DiceCTF 2026)

**Pattern (Housing Crisis):** Groth16 verifier has `vk_delta_2 == vk_gamma_2`, which breaks soundness entirely. Proofs are trivially forgeable.

**Forgery:**
```python
from py_ecc.bn128 import G1, G2, multiply, add, neg, pairing
from py_ecc.bn128 import curve_order as q

# When delta == gamma, the pairing equation simplifies:
# e(A, B) = e(alpha, beta) * e(vk_x + C, gamma)
# Set A = vk_alpha1, B = vk_beta2, then:
# e(alpha, beta) * e(vk_x + C, gamma) = e(alpha, beta)
# → e(vk_x + C, gamma) = 1 → C = -vk_x (point negation)

forged_A = vk_alpha1   # alpha point from verification key
forged_B = vk_beta2    # beta point from verification key
forged_C = neg(vk_x)   # negate the public input accumulator

# This proof verifies for ANY public inputs
```

**Detection:** Compare `vk_delta_2` and `vk_gamma_2` in the verifier contract. If equal, the entire Groth16 scheme collapses — any statement can be "proven."

**When to check:** Always inspect Groth16 verification key constants before attempting complex attacks. A broken trusted setup makes everything else unnecessary.

---

## Groth16 Proof Replay — Unconstrained Nullifier (DiceCTF 2026)

**Pattern (Housing Crisis):** DAO governance never tracks used `proposalNullifierHash` values, and the circuit leaves the nullifier unconstrained. A valid proof from the setup transaction can be replayed infinitely.

**Attack:**
1. Find the DAO contract's deployment/setup transaction
2. Extract constructor arguments containing valid Groth16 proof
3. Replay the same proof for every proposal — it always verifies
4. Use proposals to control DAO actions (betting, market creation, resolution)

**Key insight:** ZK circuits that leave inputs unconstrained and systems that don't track nullifiers are vulnerable to replay. Always check: does the verifier contract track proof nullifiers? Does the circuit actually constrain all declared public inputs?

---

## DV-SNARG Forgery via Verifier Oracle (DiceCTF 2026)

**Pattern (Dot):** DV-SNARG (Designated Verifier Succinct Non-interactive ARGument) for an adder circuit. Must produce 20 valid proofs for **wrong** answers.

**Key insight:** DV-SNARGs explicitly lose soundness when the prover has oracle access to the verifier (ePrint 2024/1138). The verifier's secret randomness can be extracted through query patterns.

**DPP (Dot Product Proof) structure:**
```text
q[i] = v[i] + b*(tensor[i] - constraint[i])
where b = fixed constant (e.g., 162817)
      v[i] = random in [-256, 256]
      constraint weights r = random in [-2^40, 2^40]
```

**Forgery via CRS entry cancellation:**
For a wrong answer, only the output constraint (wire N) is violated. Find two CRS entries whose constraint contributions cancel:

1. Wire N is touched by gate G AND the output constraint
2. `pair(input1, input2)` of gate G is touched ONLY by gate G
3. Adding `CRS[wire_N]` and subtracting `CRS[pair]` to the wrong proof cancels `b*r_G` terms
4. The remaining deficit `b*r_output` also cancels
5. Adjust `delta = -v[N] + 2*b*v[input1]*v[input2]` via `delta*G` on h2

**Learning secret v values via oracle:**
```python
# At streak=0, submitting correct answer is "safe" — doesn't reset streak
# Use oracle to learn |v[i]| from unconstrained diagonal pairs:

for guess in range(257):  # v[i] in [-256, 256], |v[i]| in [0, 256]
    # Set pair(i,i) coefficient to guess^2
    # If guess == |v[i]|, specific oracle response differs
    response = oracle_query(guess)
    if response == "hit":
        abs_v_i = guess
        break

# Learn signs from off-diagonal unconstrained pairs (1 query each)
# Learn product sign: v[a]*v[b] sign from pair(a,b)
```

**Performance:** ~364 oracle queries for Phase 1 (~97s), ~300s for 20 forged proofs ≈ 400s total.

**Key insight:** When attacking DV-SNARGs with oracle access, the strategy is: (1) learn a small number of secret values from the verifier's randomness, (2) use algebraic cancellation between CRS entries to forge proofs. Unconstrained pair indices expose pure tensor products of the secret vector.

---

## KZG Pairing Oracle for Permutation Recovery (UNbreakable 2026)

**Pattern (toxicwaste):** KZG commitment scheme publishes shuffled points `{alpha^i * G1}` for i=0..n. The shuffle hides which point corresponds to which exponent. Recover the exponent ordering using bilinear pairings as an oracle, then extract the toxic waste `alpha`.

**Distortion map technique:** On supersingular pairing-friendly curves, a distortion map `psi((x,y)) = (zeta*x, y)` (where `zeta^3 = 1`) enables additive exponent comparisons:

```python
from sage.all import *

# For points P_i = alpha^a_i * G1 and P_j = alpha^a_j * G1:
# e(P_i, psi(P_j)) = e(G1, psi(G1))^(alpha^(a_i + a_j))
# If e(P_i, psi(P_j)) == e(P_k, psi(G1)), then a_i + a_j == a_k

# Step 1: Identify G1 (alpha^0) — the only point where e(P, psi(P)) == e(G1, psi(G1))
g1 = None
base_pairing = None
for P in shuffled_points:
    val = P.weil_pairing(psi(P), order)
    if base_pairing is None:
        base_pairing = val
        g1 = P
    elif val == base_pairing:
        g1 = P
        break

# Step 2: Walk the chain — find alpha*G1 via e(P_?, psi(G1)) comparisons
# Then alpha^2*G1 via e(alpha*G1, psi(alpha*G1)) == e(alpha^2*G1, psi(G1))
# Continue until full ordering recovered

# Step 3: With ordered points, solve A(x) = 0 over GF(q) to get alpha
# Step 4: Forge KZG opening proofs using recovered alpha
```

**Key insight:** Bilinear pairings reveal additive relationships between exponents without solving discrete log. The pairing `e(P_i, psi(P_j))` depends on `alpha^(a_i + a_j)`, so comparing against known pairing values identifies which shuffled point has which exponent. This turns a cryptographic shuffle into a solvable ordering problem.

---

## halo2 Blinding-Omission → Witness Recovery via Lagrange (source: ZK Hack V)

**Trigger:** halo2 circuit where `advice_values[unusable_rows_start..]` is filled with a constant (`Fr::ONE`, `Fr::ZERO`) instead of `Fr::random(&mut rng)`; multiple proofs on same secret with different nonces.
**Signals:** grep for `advice_values` fill loop that does not call an RNG; test vectors contain ≥ N proofs sharing a witness.
**Mechanic:** without blinding, advice polynomials leak their evaluation at the Fiat-Shamir challenge `x`. Collect ≥ N proofs (each gives 3 eval points), Lagrange-interpolate the advice polynomial, then evaluate at `ω²` to read the secret witness. Template: build a Vandermonde matrix from `(x_i, advice_i)` tuples, solve for coefficients in `Fr`.

## LogUp / ProtoStar Lookup with Small-Prime Field (source: ZK Hack V)

**Trigger:** LogUp/ProtoStar-style lookup argument over a prime field of characteristic ≤ 2³², e.g. `F_p^6` with `p = 70937`; check of the form `Σ h_i = Σ g_i` combined with multiplicity vector `m`.
**Signals:** prime constant that fits in `u16`/`u32`; `multiplicity` vector in the witness; additive (not multiplicative) aggregation in the lookup.
**Mechanic:** insert the illegal witness `w*` exactly `p` times into the advice column. Because aggregation is additive mod `p`, the sum collapses to 0 and the range-check constraint passes. Multiplicity vector `m` can remain all-zeros. Generalises: any lookup argument where the illegal contribution can be multiplied to `p·k` is bypassable in a small-characteristic field.

## Noir `sha256_var(buf, len)` Trailing-Byte Under-Constraint (source: ZK Hack V)

**Trigger:** Noir (or any arithmetic-circuit DSL) using `std::hash::sha256_var(buf, len)` where `buf.len() > len`; subsequent in-circuit checks read the full `buf`, not `buf[..len]`.
**Signals:** the circuit declares a fixed-size array but hashes a variable prefix; whitelist / substring / membership check reads trailing bytes.
**Mechanic:** place a legitimate preimage in the first `len` bytes (hash check passes) and append an attacker-chosen payload to the tail (membership check now matches target). Two checks satisfy simultaneously → impersonation. Fix: constrain `buf[len..] == 0` as an additional chip.
