"""Snapshot the emulated screen after every erase-J burst to find exactly
which handoff wipes delivered content on a long streamed turn."""
import os, pexpect, pyte, re, time

cols, rows = 80, 30
screen = pyte.HistoryScreen(cols, rows, history=5000)
stream = pyte.Stream(screen)
snapshots = []
counter = [0]

class Feeder:
    def write(self, data):
        stream.feed(data)
        counter[0] += data.count("\x1b[J")
        if counter[0] >= len(snapshots) * 3 and counter[0] > 0:
            # snapshot every 3 erase-J events
            lines = ["".join(r).rstrip() for r in screen.display]
            hist = ["".join(str(c.data if hasattr(c, "data") else c) for c in buf)
                    for buf in screen.history.top]
            snapshots.append({
                "eraseJ": counter[0],
                "screen": lines,
                "history_tail": hist[-40:],
            })

child = pexpect.spawn(
    "venv/bin/python", ["-m", "pawnlogic", "--model", "bai:glm-5.3-flash"],
    env=os.environ.copy(), encoding="utf-8", timeout=120, dimensions=(rows, cols),
)
child.logfile_read = Feeder()
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

# find when each number disappears from (screen + history) union
def visible(snap):
    blob = "\n".join(snap["screen"]) + "\n" + "\n".join(snap["history_tail"])
    return blob

first_seen, last_seen = {}, {}
for idx, snap in enumerate(snapshots):
    blob = visible(snap)
    for n in range(1, 21):
        if re.search(rf"(?<!\d){n}(?!\d)", blob):
            last_seen[n] = idx
            first_seen.setdefault(n, idx)
print("snapshots:", len(snapshots))
for n in range(1, 21):
    f, l = first_seen.get(n), last_seen.get(n)
    status = "MISSING" if f is None else f"seen {f}..{l}"
    print(f"{n:2d}: {status}")
# dump the snapshot where 6 last appears and the next one
if 6 in last_seen:
    i = last_seen[6]
    print(f"--- snapshot {i} (6 still visible) screen ---")
    for l in snapshots[i]["screen"]:
        if l.strip(): print(repr(l[:70]))
    if i + 1 < len(snapshots):
        print(f"--- snapshot {i+1} (6 gone?) screen ---")
        for l in snapshots[i+1]["screen"]:
            if l.strip(): print(repr(l[:70]))
import pickle
with open("/tmp/replay_snaps.pkl", "wb") as fh:
    pickle.dump(snapshots, fh)
