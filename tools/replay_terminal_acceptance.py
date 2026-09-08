"""Full-CLI replay harness: drives the real pawn binary under a PTY,
records (1) raw PTY bytes, (2) pyte-emulated final screen, and reports
duplicate/fragment analysis for the 1-50 counting acceptance gate."""
import os, pexpect, pyte, re, sys, time

cols, rows = 80, 30
screen = pyte.HistoryScreen(cols, rows, history=5000)
stream = pyte.Stream(screen)

class Feeder:
    def write(self, data): stream.feed(data)
    def flush(self): pass

child = pexpect.spawn(
    "venv/bin/python", ["-m", "pawnlogic", "--model", "bai:glm-5.3-flash"],
    env=os.environ.copy(), encoding="utf-8", timeout=120, dimensions=(rows, cols),
)
child.logfile_read = Feeder()
raw_all = []
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
except Exception:
    pass
finally:
    try:
        if child.isalive():
            child.terminate(force=True)
    except Exception:
        pass

lines = ["".join(r) for r in screen.display]
hist = ["".join(str(c.data if hasattr(c, "data") else c) for c in buf) for buf in screen.history.top]
# analysis: numbers 1..20 visible, each exactly once, no "Thinking" fragments
full = "\n".join(lines + hist)
report = []
for n in range(1, 21):
    cnt = len(re.findall(rf"(?<!\d){n}(?!\d)", full))
    report.append((n, cnt))
thinking = full.count("Thinking")
frag = sum(1 for l in lines if re.match(r"^\s*[|/\\-]\s*Thinking", l))
bad = [(n, c) for n, c in report if c != 1]
print("numbers not exactly-once:", bad if bad else "none")
print("Thinking fragments on final screen:", thinking, "(spinner lines:", frag, ")")
print("VERDICT:", "PASS" if not bad and thinking == 0 else "FAIL")
