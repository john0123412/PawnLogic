"""conftest.py — pytest root configuration for PawnLogic."""
import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parent)
if ROOT in sys.path:
    sys.path.remove(ROOT)
sys.path.insert(0, ROOT)

# Pre-import the real local `config` package so it wins the module cache
# before any test file that mocks sys.modules["config"] runs.
import importlib
for key in list(sys.modules):
    if key == "config" or key.startswith("config."):
        f = getattr(sys.modules[key], "__file__", "") or ""
        if ROOT not in f:
            del sys.modules[key]
import config  # noqa: E402,F401 — force-cache the real package
