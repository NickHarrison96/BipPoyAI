"""
Machine-local model bookkeeping that is deliberately not committed.

Two kinds of state are tracked:

  .state/external_paths.json   filename -> absolute path of a GGUF that sits
                               OUTSIDE the project (on another drive). Keeps the
                               configs portable: they store the bare filename,
                               this file remembers where the bytes are on this
                               machine.

  Models/<stem>/               a folder per model, holding that model's own
                               Modelfile + config.yaml. Selecting a .gguf swaps
                               these into the active root files; a model with no
                               folder yet gets one created. Because the folder
                               lives under Models/, it is machine-local and never
                               committed.

The root Modelfile / config.yaml are the *active* files Ollama and LiteLLM read;
the per-model folders are the source they are swapped from.
"""

import json
import shutil
from pathlib import Path
from typing import Dict

PROJECT_ROOT = Path(__file__).resolve().parent
STATE_DIR = PROJECT_ROOT / ".state"
EXTERNAL_FILE = STATE_DIR / "external_paths.json"


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_json(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        pass


# ─── External weight locations ────────────────────────────────────────────────

def external_paths() -> Dict[str, str]:
    """Map of filename -> absolute path for weights that live outside Models/."""
    return _load_json(EXTERNAL_FILE)


def remember_external(filename: str, abs_path: str) -> None:
    """Record where an out-of-project GGUF lives on this machine."""
    data = _load_json(EXTERNAL_FILE)
    data[filename] = abs_path
    _save_json(EXTERNAL_FILE, data)


def forget_external(filename: str) -> None:
    data = _load_json(EXTERNAL_FILE)
    if filename in data:
        del data[filename]
        _save_json(EXTERNAL_FILE, data)


def is_in_project(path: Path) -> bool:
    """True when `path` is inside the project directory (so Models/ applies)."""
    try:
        path.resolve().relative_to(PROJECT_ROOT.resolve())
        return True
    except ValueError:
        return False


def resolve(selected_gguf: str, working_dir=None) -> Path:
    """Resolve a `selected_gguf` reference to the absolute path it points at.

    References take three forms:
      - absolute path            -> used as-is (legacy / direct)
      - "Models/<file>.gguf"     -> project Models/ directory
      - "<file>.gguf" (bare)     -> project Models/ first, then the external map
    """
    p = Path(selected_gguf)
    if p.is_absolute():
        return p
    base = Path(working_dir) if working_dir else PROJECT_ROOT
    if len(p.parts) > 1:
        return (base / p).resolve()
    local = base / "Models" / p.name
    if local.exists():
        return local
    ext = external_paths().get(p.name)
    if ext:
        ext_path = Path(ext)
        if ext_path.exists():
            return ext_path
    return local


def canonicalize(selected_gguf: str) -> str:
    """Normalise a GGUF reference to its portable form.

    An absolute path that points inside the project becomes "Models/<file>";
    one recorded in the external map becomes the bare "<file>". Anything that is
    not recognised is returned unchanged, so a legacy absolute path still works.
    """
    p = Path(selected_gguf)
    if not p.is_absolute():
        return selected_gguf
    try:
        rel = p.resolve().relative_to(PROJECT_ROOT.resolve())
        return rel.as_posix()
    except ValueError:
        pass
    name = p.name
    ext = external_paths().get(name)
    if ext and Path(ext) == p:
        return name
    return p.as_posix()


# ─── Per-model config folders ─────────────────────────────────────────────────

def model_folder(stem: str, working_dir=None) -> Path:
    """The folder inside Models/ that holds a model's own config.yaml + Modelfile."""
    base = Path(working_dir) if working_dir else PROJECT_ROOT
    return base / "Models" / stem


def _model_files(stem: str, working_dir=None):
    folder = model_folder(stem, working_dir)
    return folder / "Modelfile", folder / "config.yaml"


def has_model_config(stem: str, working_dir=None) -> bool:
    """True when the model already has its own Modelfile + config.yaml."""
    mf, cy = _model_files(stem, working_dir)
    return mf.exists() and cy.exists()


def activate_model(stem: str, working_dir=None) -> None:
    """Swap a model's stored Modelfile + config.yaml into the active root files."""
    mf, cy = _model_files(stem, working_dir)
    wd = Path(working_dir) if working_dir else PROJECT_ROOT
    shutil.copyfile(mf, wd / "Modelfile")
    shutil.copyfile(cy, wd / "config.yaml")


def store_model(stem: str, working_dir=None) -> None:
    """Copy the active root Modelfile + config.yaml into the model's folder."""
    folder = model_folder(stem, working_dir)
    folder.mkdir(parents=True, exist_ok=True)
    wd = Path(working_dir) if working_dir else PROJECT_ROOT
    shutil.copyfile(wd / "Modelfile", folder / "Modelfile")
    shutil.copyfile(wd / "config.yaml", folder / "config.yaml")
