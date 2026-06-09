"""config/phases.py - MoE dynamic tool-pruning route table."""

AGENT_PHASES: dict[str, list[str]] = {
    "RECON": [
        "pwn_env", "list_dir", "find_files", "read_file", "inspect_binary",
        "pwn_timed_debug",
        "search_skills",
        "check_service",
    ],
    "VULN_DEV": [
        "pwn_cyclic", "pwn_disasm", "pwn_rop", "pwn_libc", "pwn_one_gadget", "run_shell",
        "pwn_timed_debug",
    ],
    "EXPLOIT": [
        "write_file", "patch_file", "run_code", "pwn_debug", "pwn_timed_debug",
        "run_interactive", "run_shell",
        "run_code_docker", "pwn_container",
        "tool_install_package",
        "docker_prune_resources",
    ],
    "GENERAL": [
        "read_file", "write_file", "patch_file", "run_shell", "web_search", "fetch_url",
        "pwn_timed_debug",
        "run_code_docker", "pwn_container",
        "tool_install_package",
        "docker_prune_resources",
        "bump_skill",
        "search_skills",
        "check_service",
    ],
    "WEB_PEN": [
        "web_fetch", "web_click", "web_screenshot", "web_select", "web_type", "web_navigate",
        "web_search", "fetch_url",
        "read_file", "write_file",
        "run_shell",
        "bump_skill",
        "search_skills",
        "check_service",
    ],
}
