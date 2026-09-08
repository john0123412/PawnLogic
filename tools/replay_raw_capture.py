"""Dump raw PTY bytes to a file for byte-level forensics of content loss."""
import os, pexpect, time

cols, rows = 80, 30
out = open("/tmp/replay_raw.txt", "w")  # noqa: SIM115 - closed at finally
child = pexpect.spawn(
    "venv/bin/python", ["-m", "pawnlogic", "--model", "bai:glm-5.3-flash"],
    env=os.environ.copy(), encoding="utf-8", timeout=120, dimensions=(rows, cols),
)
child.logfile_read = out
try:
    child.expect(["Resume session", "You >", "You>"], timeout=30)
    if "Resume" in child.after:
        child.sendline("")
        child.expect(["You >", "You>"], timeout=20)
    child.sendline("Count slowly from 1 to 20, one number per line, nothing else.")
    time.sleep(60)
    child.sendline("/q")
    try:
        child.expect(pexpect.EOF, timeout=20)
    except pexpect.TIMEOUT:
        child.terminate(force=True)
except Exception as e:
    print("err:", e)
finally:
    try:
        if child.isalive():
            child.terminate(force=True)
    except Exception:
        pass
out.close()
print("captured", os.path.getsize("/tmp/replay_raw.txt"), "bytes")
