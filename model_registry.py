"""
Machine-local model bookkeeping that is deliberately not committed.

Everything lives under the gitignored `.state/` directory next to the tracked
configs:

  .state/external_paths.json   filename -> absolute path of a GGUF that sits
                               OUTSIDE the project (on another drive). Keeps the
                               tracked configs portable: they store the bare
                               filename, this file remembers where the bytes are
                               on this machine.

  .state/models.json           filename -> the Ollama tag and inference/hardware
                               fields tuned for that model. Switching models
                               restores its own tag/context/temperature/etc.
                               instead of reusing the previous model's values.

Neither file is part of the repo. Everything else — the model definition and
the proxy routing — stays in the project directory and is owned by configs.py.
"""

import json
from pathlib import Path
from typing import Dict

PROJECT_ROOT = Path(__file__).resolve().parent
MODELS_DIR = PROJECT_ROOT / "Models"
STATE_DIR = PROJECT_ROOT / ".state"
EXTERNAL_FILE = STATE_DIR / "external_paths.json"
SETTINGS_FILE = STATE_DIR / "models.json"

# Clean defaults used when a model has no saved settings yet. Mirrors
# configs.ModelConfig so a freshly-added model does not inherit the previous
# model's tuning. `tag` is None to mean "derive from the filename".
DEFAULT_MODEL_SETTINGS = {
    "tag": None,
    "context_size": 32768,
    "max_tokens": 8192,
    "temperature": 0.2,
    "gpu_layers": 99,
    "cpu_threads": 6,
    "batch_size": 512,
    "top_p": None,
    "top_k": None,
    "repeat_penalty": None,
    "thinking": False,
    "system_prompt": "",
}


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


# ─── Per-model settings ───────────────────────────────────────────────────────

def model_settings(filename: str) -> Dict[str, object]:
    """Saved tuning for a GGUF filename (empty if never configured).

    Keyed by filename, not tag: the weights are the stable identity. The tag is
    itself a setting, so a model installed under a custom tag (e.g. `qwythos-heretic`
    for `Qwen3.5-9B-Heretic-patched2.gguf`) keeps it when you switch back.
    """
    data = _load_json(SETTINGS_FILE)
    entry = data.get(filename)
    return entry if isinstance(entry, dict) else {}


def remember_model_settings(filename: str, settings: Dict[str, object]) -> None:
    """Persist the tuned fields for a GGUF filename."""
    data = _load_json(SETTINGS_FILE)
    data[filename] = settings
    _save_json(SETTINGS_FILE, data)


def default_settings() -> Dict[str, object]:
    """A copy of the clean defaults (mutating the returned dict is safe)."""
    return dict(DEFAULT_MODEL_SETTINGS)
