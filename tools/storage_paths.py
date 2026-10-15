"""Shared companion selection; import has no account or directory writes."""
from functools import lru_cache
from pathlib import Path
import importlib.util
import os
import sys

SOURCE = Path(__file__).resolve().parents[1]
TOOL = "qq-history-recovery"

@lru_cache(maxsize=None)
def _guard(name):
    path = SOURCE / "guards" / "tools" / (name + ".py")
    if not path.is_file():
        raise RuntimeError("Guard checkout incomplete; restore the pinned submodule")
    spec = importlib.util.spec_from_file_location("_" + TOOL.replace("-", "_") + "_" + name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

def config_root():
    stem = TOOL.upper().replace("-", "_")
    selected = os.environ.get(stem + "_CONFIG") or os.environ.get(stem + "_CONFIG_DIR")
    if selected:
        candidate = Path(selected).expanduser()
        if not candidate.is_absolute():
            raise ValueError("Configuration override must be an absolute directory")
        root = candidate.resolve()
    else:
        root = _guard("datadir").resolve_companion_root(TOOL)
        root = Path(root).resolve() if root else SOURCE.with_name(TOOL + "-config")
    if root == SOURCE or root.is_relative_to(SOURCE):
        raise ValueError("Configuration cannot be inside the tool source repository")
    return root

def writable_config_root():
    root = config_root()
    if not root.is_dir():
        raise RuntimeError("Private companion missing; restore its Git checkout before writing")
    return root
