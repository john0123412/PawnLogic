"""Tool schemas for the Docker tool family.

Declared separately from tools/docker_sandbox.py: the schema block is pure
declarative data and dominates the module's size, so it lives apart from the
runtime code. Keep this file, the plan validator (tools/docker_plan.py), and
the network gate in tools/docker_sandbox.py in agreement when touching
network modes (AGENT.md "Docker network modes are a closed set").
"""

from tools.docker_plan import SUPPORTED_NETWORK_MODES

DOCKER_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "run_code_docker",
            "description": (
                "Run code inside a disposable Docker container.\n"
                "Use for Pwn exploit testing, multi-libc environment checks, isolated sandbox execution, and authorized CTF plaintext HTTP clients; for CTF HTTP use bridge with explicit allow_network, without host mode or credential mounts.\n"
                "Defaults to no network (network=none) to prevent CTF flag leakage.\n"
                "Resource limits: 512 MB memory, 0.5 CPU, 256 PIDs.\n"
                "One-shot hardening: read-only root filesystem (relaxed only when install_deps must write site-packages), tmpfs /tmp and /run, all Linux capabilities dropped, and a user matching the host UID:GID when available (non-root only for a nonzero host UID; dependency installs retain the image user).\n"
                "Supported languages: python / c / cpp / bash / javascript / rust / go / java.\n"
                "Returns clear setup guidance when Docker is unavailable."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "language": {
                        "type": "string",
                        "description": "Programming language (default python).",
                    },
                    "code": {
                        "type": "string",
                        "description": "Source code to execute.",
                    },
                    "image": {
                        "type": "string",
                        "description": (
                            "Execution image. Use 'python' for pure Python logic and 'pwndocker' for Pwn analysis. "
                            "When omitted, an image is selected from the language. "
                            "Available aliases: pwndocker / ubuntu18 / ubuntu22 / kali / python / gcc."
                        ),
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Execution timeout seconds (default 30).",
                    },
                    "mount_files": {
                        "type": "object",
                        "description": "File mounts {host path: container path}.",
                    },
                    "network": {
                        "type": "string",
                        "enum": list(SUPPORTED_NETWORK_MODES),
                        "description": (
                            "Network mode: none (default no network) / bridge / host. "
                            "bridge/host requires allow_network=true or an environment policy override. "
                            "The operator may declare scope metadata via "
                            "PAWNLOGIC_DOCKER_EGRESS_ALLOW (hosts-file mappings only; no destination filtering). "
                            "Container-sharing modes (container:<id>) and unknown modes are rejected."
                        ),
                    },
                    "container_user": {
                        "type": "string",
                        "description": (
                            "Run the container as this user (name or uid[:gid]). Default: a user "
                            "matching the host uid:gid; 'root' explicitly selects root when "
                            "explicitly required."
                        ),
                    },
                    "allow_network": {
                        "type": "boolean",
                        "description": "Explicitly allow bridge/host Docker network mode (default false).",
                    },
                    "allow_auto_pull": {
                        "type": "boolean",
                        "description": "Explicitly allow automatic docker pull when an image is missing (default false).",
                    },
                    "allow_host_read_mount": {
                        "type": "boolean",
                        "description": "Explicitly allow read-only mounts outside the workspace for trusted challenge files.",
                    },
                    "stdin": {
                        "type": "string",
                        "description": "Standard input passed to the program.",
                    },
                    "install_deps": {
                        "type": "string",
                        "description": "Space-separated pip package names for Python only.",
                    },
                },
                "required": ["language", "code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pwn_container",
            "description": (
                "Persistent container management tool for long-running CTF target environments.\n"
                "Actions:\n"
                "  create  - create and start a persistent container\n"
                "  exec    - run a command inside a running container\n"
                "  destroy - stop and destroy a container\n"
                "  list    - list active persistent containers\n"
                "Use for multi-step Pwn debugging and exploit verification."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "exec", "destroy", "list"],
                        "description": "Operation type.",
                    },
                    "name": {
                        "type": "string",
                        "description": "Container name identifier.",
                    },
                    "image": {
                        "type": "string",
                        "description": "Docker image for create only (default pwndocker).",
                    },
                    "command": {
                        "type": "string",
                        "description": "Command to execute for exec.",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Command timeout seconds for exec (default 30).",
                    },
                    "network": {
                        "type": "string",
                        "enum": list(SUPPORTED_NETWORK_MODES),
                        "description": (
                            "Network mode for create (default none). "
                            "bridge/host requires allow_network=true or an environment policy override. "
                            "The operator may declare scope metadata via "
                            "PAWNLOGIC_DOCKER_EGRESS_ALLOW (hosts-file mappings only; no destination filtering). "
                            "Container-sharing modes (container:<id>) and unknown modes are rejected."
                        ),
                    },
                    "container_user": {
                        "type": "string",
                        "description": (
                            "Run the persistent container as this user (name or uid[:gid]) on create; "
                            "default is the image default user."
                        ),
                    },
                    "allow_network": {
                        "type": "boolean",
                        "description": "Explicitly allow create to use bridge/host Docker network mode (default false).",
                    },
                    "allow_auto_pull": {
                        "type": "boolean",
                        "description": "Explicitly allow automatic docker pull when an image is missing (default false).",
                    },
                    "allow_host_read_mount": {
                        "type": "boolean",
                        "description": "Explicitly allow read-only mounts outside the workspace for trusted challenge files.",
                    },
                },
                "required": ["action"],
            },
        },
    },
    # P4.2: tool_install_package schema.
    {
        "type": "function",
        "function": {
            "name": "tool_install_package",
            "description": (
                "Airlock package installation tool.\n"
                "Installs apt/pip packages in a persistent container. Only connections made by this Airlock operation are disconnected; an existing bridge attachment stays unchanged.\n"
                "Failed temporary disconnect revokes tool access and kills/removes the container; daemon cleanup failure explicitly requires manual cleanup.\n"
                "Configured egress declarations are validated, but existing hosts-file mappings are unchanged and destinations are not filtered.\n"
                "Package names are strictly regex-validated to prevent command injection.\n"
                "Temporarily granting bridge egress requires explicit authorization: pass allow_network=true or set PAWNLOGIC_DOCKER_ALLOW_NETWORK=true.\n"
                "Works only for containers created through pwn_container create."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "container_name": {
                        "type": "string",
                        "description": "Target persistent container name (the name passed to pwn_container create).",
                    },
                    "pkg_manager": {
                        "type": "string",
                        "enum": ["apt", "pip"],
                        "description": "Package manager: apt or pip.",
                    },
                    "packages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Package names to install; each package may contain only [a-zA-Z0-9_\\-\\.]+.",
                    },
                    "allow_network": {
                        "type": "boolean",
                        "description": "Explicitly authorize the temporary bridge egress used for installation.",
                    },
                },
                "required": ["container_name", "pkg_manager", "packages"],
            },
        },
    },
    # P4.3: docker_prune_resources schema.
    {
        "type": "function",
        "function": {
            "name": "docker_prune_resources",
            "description": (
                "Docker resource cleanup tool.\n"
                "Removes all stopped containers and dangling images, returning reclaimed disk space in MB.\n"
                "Use after CTF tasks or when disk space is low."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]
