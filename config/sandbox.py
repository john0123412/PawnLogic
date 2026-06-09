"""config/sandbox.py - sandbox languages, Docker images, and browser config."""
from .paths import PAWNLOGIC_HOME

SANDBOX_LANGS = {
    "python":     {"ext": ".py",   "cmd": None,           "compile": None},
    "c":          {"ext": ".c",    "cmd": None,           "compile": "gcc -O0 -g {src} -o {bin} -lm 2>&1"},
    "cpp":        {"ext": ".cpp",  "cmd": None,           "compile": "g++ -O0 -g -std=c++17 {src} -o {bin} 2>&1"},
    "javascript": {"ext": ".js",   "cmd": "node {src}",   "compile": None},
    "js":         {"ext": ".js",   "cmd": "node {src}",   "compile": None},
    "bash":       {"ext": ".sh",   "cmd": "bash {src}",   "compile": None},
    "rust":       {"ext": ".rs",   "cmd": None,           "compile": "rustc {src} -o {bin} 2>&1"},
    "go":         {"ext": ".go",   "cmd": "go run {src}", "compile": None},
    "java":       {"ext": ".java", "cmd": None,           "compile": "javac {src} 2>&1"},
}

DOCKER_IMAGES = {
    "pwndocker":  "skysider/pwndocker",
    "ubuntu18":   "ubuntu:18.04",
    "ubuntu22":   "ubuntu:22.04",
    "kali":       "kalilinux/kali-rolling",
    "python":     "python:3.12-slim",
    "gcc":        "gcc:latest",
}

BROWSER_CONFIG = {
    "timeout":        30,
    "screenshot_dir": str(PAWNLOGIC_HOME / "workspace" / "screenshots"),
    "stealthy":       True,
    "solve_cf":       True,
}

USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 Version/17.4 Safari/605.1.15",
]
