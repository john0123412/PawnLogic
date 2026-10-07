"""Airlock lifecycle helpers.

Shared by `tools/docker_sandbox.py`; lifecycle code lives here so the
sandbox module stays within its architecture budget. The compatibility
guard below belongs to the offline attach/restore contract documented in
docs/plans/container-boundary-followups.md §3.
"""


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
