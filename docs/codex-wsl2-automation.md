# Bounded Codex Automation On WSL2

`tools/codex_goal_run.sh` runs one non-interactive `codex exec` goal from a
clean feature branch. It refuses `main`, detached HEAD, dirty worktrees, and
artifact paths outside ignored `.codex_goals/` or `.agent-work/` roots.

```bash
tools/codex_goal_run.sh \
  --goal "Run targeted tests, implement the approved task, and stop before push" \
  --branch feature/example \
  --max-wall-seconds 3600
```

Each run has a unique directory containing `manifest.json`, `heartbeat.log`,
and `codex.log`. The manifest records the branch, commit, timestamps, process
status, capability gates, and a hash of the goal. It never stores environment
values or the goal text.

Paid smoke requires both `--real-api` and a positive `--max-api-calls`. Package
installation and remote Git operations remain disabled unless `--install-deps`
or `--allow-remote` is supplied. These flags grant capability to the agent; the
repository trust and release rules still apply.

On interruption or timeout, the runner sends an interrupt to the Codex process
group, waits for the bounded timeout cleanup, then kills remaining children.
To recover, inspect the manifest and log, confirm no process referenced by the
run is alive, remove a stale `.run-lock` only after that check, restore a clean
worktree, and start a new run. Delete old run directories after retaining any
review evidence required by the maintainer.
