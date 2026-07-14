"""Startup primitives independent from the interactive CLI facade."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
import sys
import urllib.request


def default_pawnlogic_home() -> Path:
    raw = os.environ.get("PAWNLOGIC_HOME")
    if raw:
        return Path(raw).expanduser()
    try:
        home = Path.home()
    except Exception:
        home = Path(os.environ.get("TMPDIR") or "/tmp")
    return (home / ".pawnlogic").expanduser()


def manual_load_env(path: Path) -> None:
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)
    except Exception as exc:
        print(f"\033[93m  Warning: failed to read {path}: {exc}\033[0m", file=sys.stderr)


def install_proxy() -> str | None:
    http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not http_proxy and not https_proxy:
        return None
    proxies: dict[str, str] = {}
    if http_proxy:
        proxies["http"] = http_proxy
    if https_proxy:
        proxies["https"] = https_proxy
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies))
    urllib.request.install_opener(opener)
    return https_proxy or http_proxy


def ensure_runtime_dir_writable(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".write_test"
    try:
        probe.write_text("ok", encoding="utf-8")
    finally:
        probe.unlink(missing_ok=True)


def has_any_api_key(providers: Mapping[str, Mapping[str, object]]) -> bool:
    from config.providers import init_providers

    init_providers()
    return any(
        os.getenv(str(provider["api_key_env"]), "")
        not in ("", "YOUR_API_KEY_HERE")
        for provider in providers.values()
        if provider.get("api_key_env")
    )


__all__ = [
    "default_pawnlogic_home",
    "ensure_runtime_dir_writable",
    "has_any_api_key",
    "install_proxy",
    "manual_load_env",
]
