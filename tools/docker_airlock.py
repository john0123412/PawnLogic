"""Airlock lifecycle helpers.

Shared by `tools/docker_sandbox.py`; lifecycle code lives here so the
sandbox module stays within its architecture budget. Three contracts live
here, documented in docs/plans/container-boundary-followups.md:

- §3 compatibility guard: offline (none/unattached) containers are rejected
  before any Airlock attach or install.
- §2 operation deadline: attach, the apt/pip exec and the owned-network
  cleanup all run under one monotonic deadline enforced by an independent
  watchdog thread. The installer call and the disconnect are bounded waits,
  so a stuck Docker SDK request cannot outwait containment. Operations for
  the same container are serialized and every watchdog callback is bound to
  an operation generation, so a late timer cannot kill its successor. Expiry
  revokes the tool handle, terminates the container (forced removal
  fallback) and removes the owned bridge attachment; unresolved cleanup is
  reported as a containment failure, never success.
"""

import threading

from utils.ansi import c, GREEN

AIRLOCK_TIMEOUT_DEFAULT = 120
AIRLOCK_TIMEOUT_MIN = 1
AIRLOCK_TIMEOUT_MAX = 300
SERIAL_WAIT_SECONDS = 15.0
CONTAINMENT_JOIN_SECONDS = 10.0


def validate_airlock_timeout(raw) -> tuple[int | None, str | None]:
    """
    Validate the Airlock operation deadline. Booleans, non-integers and
    out-of-range values are rejected so callers can refuse them before any
    daemon interaction.
    """
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None, (
            f"ERROR: timeout_seconds must be an integer between "
            f"{AIRLOCK_TIMEOUT_MIN} and {AIRLOCK_TIMEOUT_MAX} seconds "
            f"(default {AIRLOCK_TIMEOUT_DEFAULT})"
        )
    if not AIRLOCK_TIMEOUT_MIN <= raw <= AIRLOCK_TIMEOUT_MAX:
        return None, (
            f"ERROR: timeout_seconds must be an integer between "
            f"{AIRLOCK_TIMEOUT_MIN} and {AIRLOCK_TIMEOUT_MAX} seconds "
            f"(default {AIRLOCK_TIMEOUT_DEFAULT})"
        )
    return raw, None


class AirlockOperation:
    """One serialized Airlock run; watchdog callbacks bind to its generation."""

    def __init__(self, container_name: str, generation: int, timeout_seconds: int):
        self.container_name = container_name
        self.generation = generation
        self.timeout_seconds = timeout_seconds
        self.expired = False
        self.finished = False
        self.settled = False
        self.execution_claimed = False
        self.containment: str | None = None


_state_guard = threading.Lock()
_serial_locks: dict[str, threading.Lock] = {}
_generations: dict[str, int] = {}


def begin_airlock_operation(container_name: str, timeout_seconds: int) -> AirlockOperation | str:
    """
    Serialize operations per container (bounded wait) and atomically
    invalidate previous watchdog callbacks by advancing the generation.
    Returns the operation, or a rejection string when another operation is
    still running for the container.
    """
    with _state_guard:
        serial = _serial_locks.setdefault(container_name, threading.Lock())
    if not serial.acquire(timeout=SERIAL_WAIT_SECONDS):
        return (
            f"SECURITY BLOCK: another Airlock operation is already running for "
            f"container '{container_name}'; install denied"
        )
    with _state_guard:
        generation = _generations.get(container_name, 0) + 1
        _generations[container_name] = generation
        return AirlockOperation(container_name, generation, timeout_seconds)


def claim_airlock_execution(op: AirlockOperation) -> bool:
    """Admit one installer atomically against expiry and generation changes.

    This is the local admission point, not atomic cancellation of a remote
    Docker request. Never hold the state lock while calling the daemon.
    """
    with _state_guard:
        if any((op.expired, op.finished, op.settled, op.execution_claimed)):
            return False
        if _generations.get(op.container_name) != op.generation:
            return False
        op.execution_claimed = True
        return True


def settle_airlock_operation(op: AirlockOperation, watchdog: threading.Timer | None) -> tuple[bool, str | None]:
    """
    Main-thread completion of an operation. Atomically marks the operation
    finished so a late or running watchdog callback becomes a no-op, cancels
    the timer, and on expiry waits (bounded) for the watchdog's containment
    report. Returns (expired, containment report or None). Idempotent; a
    missing watchdog (start failure) still releases the serial slot.
    """
    if watchdog is not None:
        watchdog.cancel()
    with _state_guard:
        if op.settled:
            return op.expired, op.containment
        op.settled = True
        expired = op.expired
        if not expired:
            op.finished = True
        serial = _serial_locks.get(op.container_name)
    if expired:
        # Only a started watchdog can set expired, so join is safe here.
        watchdog.join(CONTAINMENT_JOIN_SECONDS)
        containment = op.containment or (
            "termination could not be confirmed before the wait window closed; "
            "treat the container as live and clean it up manually"
        )
    else:
        containment = None
    if serial is not None:
        serial.release()
    return expired, containment


def start_deadline_watchdog(
    op: AirlockOperation, container, revoke_handle, owned_disconnect
) -> threading.Timer:
    """Start the independent watchdog thread for the operation deadline."""
    timer = threading.Timer(
        op.timeout_seconds,
        _deadline_fired,
        args=(op, container, revoke_handle, owned_disconnect),
    )
    timer.daemon = True
    timer.start()
    return timer


def _deadline_fired(op: AirlockOperation, container, revoke_handle, owned_disconnect) -> None:
    """Watchdog callback: atomically claim expiry, then contain."""
    with _state_guard:
        if op.finished or op.expired:
            return
        if _generations.get(op.container_name) != op.generation:
            return  # stale timer for a superseded operation
        op.expired = True
    op.containment = _expire_containment(op, container, revoke_handle, owned_disconnect)


def _expire_containment(
    op: AirlockOperation, container, revoke_handle, owned_disconnect
) -> str:
    """Revoke the handle, terminate the container, remove the owned attachment."""
    revoke_handle()
    parts = ["tool access revoked", _terminate(container)]
    if owned_disconnect is not None:
        with _state_guard:
            # A finished operation never reaches containment (the callback
            # checks finished first), so only a successor's generation bump
            # can make this pass stale.
            superseded = _generations.get(op.container_name) != op.generation
        if superseded:
            # A successor operation owns the container now; its teardown must
            # not be torn down by this stale containment pass.
            parts.append("superseded before owned attachment removal; disconnect skipped")
        else:
            try:
                owned_disconnect()
                parts.append("owned bridge attachment removed")
            except Exception as disc_err:
                parts.append(f"owned bridge attachment could not be removed: {disc_err}")
    return "; ".join(parts)


def _terminate(container) -> str:
    """Kill the container, falling back to forced removal. Never raises."""
    try:
        container.kill()
        return "container terminated"
    except Exception:
        try:
            container.remove(force=True)
            return "container forcibly removed"
        except Exception as cleanup_err:
            return (
                "container may still be running; manual Docker cleanup "
                f"required: {cleanup_err}"
            )


def contain_after_leak(revoke_handle, container) -> str:
    """
    Containment for a failed owned disconnect: revoke tool access, then
    kill the container with a forced-removal fallback. The kill/remove runs
    in a bounded worker so a hung daemon call cannot outwait the deadline
    window or hold the per-container lease; containment that cannot be
    confirmed within the window is reported as unresolved, never as clean.
    The returned text matches the historical disconnect-failure report.
    """
    revoke_handle()
    done = threading.Event()
    box: dict = {}

    def _terminate():
        try:
            container.kill()
            box["result"] = "container killed; tool access revoked"
        except Exception:
            try:
                container.remove(force=True)
                box["result"] = "container removed; tool access revoked"
            except Exception as cleanup_err:
                box["result"] = (
                    "container may still be running; tool access revoked; manual "
                    f"Docker cleanup required: {cleanup_err}"
                )
        finally:
            done.set()

    threading.Thread(target=_terminate, daemon=True).start()
    if not done.wait(CONTAINMENT_JOIN_SECONDS):
        return (
            "containment could not be confirmed before the wait window closed; "
            "tool access revoked; the container may still be running and needs "
            "manual cleanup"
        )
    return box["result"]


def _deadline_report(op: AirlockOperation, container_name: str, containment) -> str:
    return (
        f"SECURITY BLOCK: Airlock install exceeded its {op.timeout_seconds}s "
        f"deadline for container '{container_name}'; {containment}"
    )


def finish_airlock_run(
    op: AirlockOperation,
    watchdog,
    result: str,
    *,
    container,
    container_name: str,
    owned_disconnect,
    revoke_handle,
) -> str:
    """
    Single completion path for an Airlock operation. The deadline, the
    watchdog and the per-container lease cover the whole lifecycle:

    1. already expired → settle and report the watchdog's containment;
    2. otherwise disconnect the owned attachment first — bounded wait, with
       the watchdog still armed and the lease still held; a stalled or
       failing disconnect is a leak and gets the same kill/force-remove
       containment;
    3. only then settle (cancel watchdog, release the lease) so a successor
       operation cannot start while network cleanup is still in flight.
    """
    with _state_guard:
        expired = op.expired
    if expired:
        _, containment = settle_airlock_operation(op, watchdog)
        return _deadline_report(op, container_name, containment)

    if owned_disconnect is not None:
        done = threading.Event()
        box: dict = {}

        def _disconnect():
            try:
                owned_disconnect()
            except Exception as exc:
                box["error"] = exc
            finally:
                done.set()

        threading.Thread(target=_disconnect, daemon=True).start()
        if not done.wait(CONTAINMENT_JOIN_SECONDS):
            containment = contain_after_leak(revoke_handle, container)
            settle_airlock_operation(op, watchdog)
            return (
                f"SECURITY BLOCK: Airlock owned disconnect did not complete "
                f"within {CONTAINMENT_JOIN_SECONDS:.0f}s for container "
                f"'{container_name}'; {containment}"
            )
        if "error" in box:
            containment = contain_after_leak(revoke_handle, container)
            settle_airlock_operation(op, watchdog)
            return (
                f"SECURITY BLOCK: Airlock network disconnect failed: "
                f"{box['error']}; {containment}"
            )
        print(c(GREEN, f"  [Airlock] container '{container_name}' forcibly disconnected from network"))

    expired, containment = settle_airlock_operation(op, watchdog)
    if expired:
        # The deadline fired while the disconnect was being finalized.
        return _deadline_report(op, container_name, containment)
    return result


def offline_attach_rejection(container, container_name: str) -> str | None:
    """
    Compatibility guard before an Airlock bridge attach: the Docker daemon
    rejects attaching containers created in private network modes to bridge
    afterward, so the container's actual membership is refreshed and verified
    before any mutation. Offline containers and unknown state are rejected;
    a container that already sits on a real network returns None.
    """
    try:
        container.reload()
    except Exception as exc:
        return (
            f"SECURITY BLOCK: cannot verify network state of container "
            f"'{container_name}' ({type(exc).__name__}: {exc}); Airlock install "
            f"denied and the container was left unchanged"
        )
    attrs = container.attrs if isinstance(container.attrs, dict) else {}
    settings = attrs.get("NetworkSettings")
    settings = settings if isinstance(settings, dict) else {}
    networks = settings.get("Networks")
    if not isinstance(networks, dict):
        return (
            f"SECURITY BLOCK: cannot determine network membership of container "
            f"'{container_name}'; Airlock install denied and the container was "
            f"left unchanged"
        )
    attached = [
        name
        for name, net in networks.items()
        if name != "none" and isinstance(net, dict) and net.get("NetworkID")
    ]
    if attached:
        return None
    return (
        f"SECURITY BLOCK: Airlock install not supported for container "
        f"'{container_name}': it is offline (network mode none or unattached) and "
        f"the Docker daemon rejects attaching such containers to bridge afterward. "
        f"The container was left unchanged; to install packages, create it with "
        f"explicitly authorized bridge networking at creation time"
    )
