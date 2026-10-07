# Host egress stage-one implementation and verification

Stage one prepares and verifies the administrator-managed filter. Stage two
permits operational use only after the complete ADR 0014 backend matrix has
passed and the owner accepts the report. No service autostart, broad sudo,
container capabilities, backend migration or existing-container termination
is part of stage one. The current repository contains a generator and a
read-only preflight, **not an installed or approved privileged executor**.

## Read-only prerequisite report

From the repository, run:

```bash
python tools/host_egress_preflight.py --out .agent-work/notes/host-egress-readiness.json
```

The CLI checks the local Unix-socket daemon, required binaries and root or
noninteractive sudo availability. Exit 1 means prerequisites are missing; it
never prompts for a password. Commands have bounded waits and do not apply
firewall rules. All 13 matrix rows begin as `not_run`, and
`activation_ready` remains false even when prerequisites are available.
The `sudo -n true` probe establishes only permission to run that no-op; it
does not establish permission for a future helper or firewall command.
Do not install this developer CLI as a sudoers entry point.

If conntrack is missing and the owner has authorized package installation,
an administrator can run this in the host's local terminal:

```bash
sudo apt-get install --no-install-recommends conntrack
```

Enter administrator credentials only in that terminal, never in chat, test
reports or repository files. Package installation alone does not provide this
session with permission to mutate firewall rules. Do not grant NOPASSWD to
iptables, a shell, a repository script, or the current generator as a shortcut.

## Privileged executor contract before installation

The proposed fixed entry point is `/usr/local/sbin/pawnlogic-egress-helper`.
Installation and its sudoers grant are deferred until this executable exists,
passes independent review and the administrator reviews its exact digest.

- The executable, its imported code, interpreter and all parent directories
  must be root-owned and unwritable by the invoking account. Do not import
  Python modules from a writable checkout or honor user Python search paths.
- A root-owned policy store fixes numeric destination snapshots, ports,
  maximum duration, full container ID and managed network ID. A caller selects
  only an approved operation ID and fixed lifecycle action. Caller JSON,
  stdin, file paths, arbitrary command arguments and environment declarations
  cannot create or widen policy. Labels alone are not identity proof.
- The helper rechecks Docker identity, source addresses and network membership
  against the root-owned manifest. Unknown state, extra attachments, backend
  changes or IP reuse deny admission. No privileged daemon state is inferred
  from a model's description of a container.
- Execution uses fixed absolute binaries and argument vectors, never a shell
  evaluating the generator's human-readable strings. A root-owned operation
  lock and monotonic duration prevent competing activations or extensions.
- State-only allowance is REPLY-only. INPUT, same-bridge, embedded DNS, hairpin
  and both address families require proven hooks or explicit fail-closed
  refusal. A valid interface name does not prove any path is covered.
- On failure/expiry keep blocking rules until the owned fixture is stopped or
  otherwise proven isolated. Only then revoke flows, remove this operation's
  artifacts and verify cleanup. Save/restore cannot clobber concurrent Docker
  or owner changes. Unconfirmed containment is an error, never success.

Only this reviewed fixed executable can eventually receive an exact, narrow
sudoers entry. Root-owned policy authorization remains separate from permission
to invoke it. The earlier hypothetical NOPASSWD line is not an installation
instruction for the current review package.

## Real backend acceptance

Run each ADR 0014 row with explicitly owned disposable fixtures and record
the kernel/backend versions, tested executable digest, actual commands,
positive/negative receipts and cleanup verification. Isolated network namespace
checks are useful preliminary tests, but do not prove the actual Docker hooks.
Mocks, generated command strings, CLI availability and authorization itself
are not kernel results. No row may be silently skipped or labelled passed.

Keep published test ports bound to loopback if that row requires them. Do not
restart the host Docker daemon, touch unrelated containers or remove owner
rules to simulate faults. A destructive restart test needs its own isolated
daemon fixture or a separately approved maintenance window. Any unsupported
or untested row blocks operational activation. Only after backend acceptance
run one bounded real IQuest workflow and then present the stage-two report.

## Current handoff

Stage-one authorization can be recorded independently of execution capability.
If the current session lacks administrator credentials, finish reviewable
repository work and preserve a blocked prerequisite report; do not retry
password guesses, read credentials or use Docker membership to obtain host
root. Resume installation/kernel acceptance through the reviewed administrator
entry point when access is available. Terminal visual checks remain owner
observations; passing a source or locally built binary probe cannot mark them
as complete.
