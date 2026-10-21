"""Carga los scripts de `scripts/` (no son un paquete) para poder probarlos."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


def load_script(name: str) -> ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registrado antes de ejecutarlo: las dataclasses lo buscan en sys.modules.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
