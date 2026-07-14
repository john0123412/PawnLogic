"""Pure Docker execution-plan validation, separate from Docker SDK calls."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import re


LANGUAGE_COMMANDS: dict[str, tuple[str, str, str]] = {
    "python": (".py", "python3 /code/main.py", "python"),
    "c": (".c", "gcc -O0 -g /code/main.c -o /code/main -lm && /code/main", "gcc"),
    "cpp": (".cpp", "g++ -O0 -g -std=c++17 /code/main.cpp -o /code/main && /code/main", "gcc"),
    "bash": (".sh", "bash /code/main.sh", "ubuntu22"),
    "javascript": (".js", "node /code/main.js", "ubuntu22"),
    "rust": (".rs", "rustc /code/main.rs -o /code/main && /code/main", "ubuntu22"),
    "go": (".go", "cd /code && go run main.go", "ubuntu22"),
    "java": (".java", "cd /code && javac Main.java && java -cp . Main", "ubuntu22"),
}
PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?(?:[<>=!~]=?[A-Za-z0-9_.+-]+)?$")


@dataclass(frozen=True, slots=True)
class DockerExecutionPlan:
    language: str
    extension: str
    command: str
    image: str
    network: str
    timeout_seconds: int


def build_docker_execution_plan(
    args: Mapping[str, object],
    *,
    resolve_image: Callable[[str], str],
    network_error: Callable[[Mapping[str, object], str], str | None],
    command_error: Callable[[str], str | None],
) -> tuple[DockerExecutionPlan | None, str | None]:
    code = str(args.get("code", ""))
    if not code:
        return None, "ERROR: code parameter is required"
    unsafe = command_error(code)
    if unsafe:
        return None, unsafe
    language = str(args.get("language", "python")).lower().strip()
    if language not in LANGUAGE_COMMANDS:
        return None, (
            f"ERROR: unsupported language '{language}'. Supported: "
            + ", ".join(LANGUAGE_COMMANDS)
        )
    network = str(args.get("network", "none") or "none").strip().lower()
    unsafe = network_error(args, network)
    if unsafe:
        return None, unsafe
    extension, command, default_image = LANGUAGE_COMMANDS[language]
    raw_image = str(args.get("image", "")) or default_image
    install_deps = str(args.get("install_deps", "")).strip()
    if language == "python" and install_deps:
        packages = install_deps.split()
        invalid = [package for package in packages if not PACKAGE_NAME_RE.fullmatch(package)]
        if invalid:
            return None, "ERROR: invalid Python package name(s): " + ", ".join(invalid)
        command = f"pip install {' '.join(packages)} -q && {command}"
    return DockerExecutionPlan(
        language=language,
        extension=extension,
        command=command,
        image=resolve_image(raw_image),
        network=network,
        timeout_seconds=int(str(args.get("timeout", 30))),
    ), None


__all__ = ["DockerExecutionPlan", "build_docker_execution_plan"]
