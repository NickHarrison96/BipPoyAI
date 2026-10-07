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
import re
import shutil
from pathlib import Path
from typing import Dict, Mapping, Optional

PROJECT_ROOT = Path(__file__).resolve().parent
STATE_DIR = PROJECT_ROOT / ".state"
EXTERNAL_FILE = STATE_DIR / "external_paths.json"
ROLE_MODELS_FILE = STATE_DIR / "role_models.json"

ROLE_NAMES = ("default", "reasoning", "coding", "vision", "multimodal")
ACTIVE_ONLY_ROLES = ("default", "reasoning")
VISION_ROLES = ("vision", "multimodal")
MAX_ROLE_TAG_LENGTH = 160

_ROLE_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*(:[A-Za-z0-9][A-Za-z0-9._-]*)?$")


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


def validate_role(role) -> str:
    if not isinstance(role, str) or role not in ROLE_NAMES:
        raise ValueError(f"Unknown role {role!r}; expected one of {', '.join(ROLE_NAMES)}.")
    return role


def validate_role_tag(tag) -> str:
    if not isinstance(tag, str):
        raise ValueError("Role tag must be a string.")
    value = tag.strip()
    if not value:
        raise ValueError("Role tag is empty.")
    if len(value) > MAX_ROLE_TAG_LENGTH:
        raise ValueError(f"Role tag is longer than {MAX_ROLE_TAG_LENGTH} characters.")
    if "*" in value or "\\" in value or ".." in value:
        raise ValueError(f"Role tag {value!r} is not an exact Ollama tag.")
    if re.match(r"^[A-Za-z]:", value) or value.lower().endswith(".gguf"):
        raise ValueError(f"Role tag {value!r} looks like a file path, not an Ollama tag.")
    if not _ROLE_TAG_RE.match(value):
        raise ValueError(f"Role tag {value!r} is not a valid Ollama tag.")
    return value


def _clean_role_mapping(mapping: Mapping) -> Dict[str, str]:
    cleaned: Dict[str, str] = {}
    for role, tag in mapping.items():
        validate_role(role)
        if tag is None or (isinstance(tag, str) and not tag.strip()):
            continue
        cleaned[role] = validate_role_tag(tag)
    return cleaned


def normalize_tag(tag: str) -> str:
    value = tag.strip().lower()
    return value[:-len(":latest")] if value.endswith(":latest") else value


def conflicting_roles(mapping: Mapping[str, str]) -> Dict[str, str]:
    conflicts: Dict[str, str] = {}
    default = mapping.get("default")
    reasoning = mapping.get("reasoning")
    if default and reasoning and normalize_tag(default) != normalize_tag(reasoning):
        msg = "'default' and 'reasoning' must name the same (active) model tag."
        conflicts["default"] = msg
        conflicts["reasoning"] = msg
    text_tags = {normalize_tag(mapping[r]) for r in ACTIVE_ONLY_ROLES + ("coding",) if mapping.get(r)}
    for role in VISION_ROLES:
        tag = mapping.get(role)
        if tag and normalize_tag(tag) in text_tags:
            conflicts[role] = f"'{role}' must name a distinct vision model, not '{tag}'."
    return conflicts


def role_mapping_issues(mapping: Mapping[str, str]) -> list:
    return sorted(set(conflicting_roles(mapping).values()))


def role_tags() -> Dict[str, str]:
    data = _load_json(ROLE_MODELS_FILE)
    out: Dict[str, str] = {}
    for role in ROLE_NAMES:
        tag = data.get(role)
        if not tag:
            continue
        try:
            out[role] = validate_role_tag(tag)
        except ValueError:
            continue
    for role in conflicting_roles(out):
        out.pop(role, None)
    return out


def save_role_tags(mapping: Mapping[str, Optional[str]]) -> Dict[str, str]:
    cleaned = _clean_role_mapping(mapping)
    issues = role_mapping_issues(cleaned)
    if issues:
        raise ValueError("Refusing to save role models:\n" + "\n".join(issues))
    ROLE_MODELS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ROLE_MODELS_FILE.write_text(json.dumps(cleaned, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return dict(cleaned)


def set_role_tag(role: str, tag: Optional[str]) -> Dict[str, str]:
    validate_role(role)
    current: Dict[str, Optional[str]] = dict(role_tags())
    current[role] = tag
    return save_role_tags(current)


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
