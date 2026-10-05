"""
User-level application settings — pure data layer.

Reads and writes ~/.qwythos/settings.json. This file holds everything that is
about *this install* rather than about the model: connection endpoints and
credentials. Modelfile and config.yaml stay owned by configs.py.

No GUI or Qt imports here — safe to call from worker threads and the TUI.
"""

import json
from pathlib import Path

SETTINGS_DIR = Path.home() / ".qwythos"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"

DEFAULTS = {
    "ollama_base_url": "http://127.0.0.1:11434",
    "litellm_base_url": "http://127.0.0.1:4000",
    "litellm_api_key": "sk-ant-api03-local-mock-key-for-ollama-bypass-000000000000000000",
    "auto_start_litellm": "false",
    # When true, child processes (LiteLLM proxy) start without a console window.
    # Handy once the stack is known-good; you lose the live log on failure.
    "launch_silent": "false",
}


def is_true(value) -> bool:
    """Interpret a settings string as a boolean.

    Settings are persisted as strings because save() only accepts non-empty
    strings, so every boolean flag round-trips as "true"/"false".
    """
    return str(value).strip().lower() == "true"


def to_flag(value: bool) -> str:
    """Render a boolean for storage via save()."""
    return "true" if value else "false"


def load() -> dict:
    """Return the full settings dict, with DEFAULTS filling any gaps."""
    merged = dict(DEFAULTS)
    try:
        on_disk = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return merged
    except (OSError, json.JSONDecodeError):
        return merged

    if isinstance(on_disk, dict):
        for key, default in DEFAULTS.items():
            value = on_disk.get(key)
            if isinstance(value, str) and value.strip():
                merged[key] = value.strip()
            else:
                merged[key] = default
    return merged


def save(updates: dict) -> dict:
    """Merge non-empty string values into settings.json and return the result."""
    merged = load()
    for key in DEFAULTS:
        value = updates.get(key)
        if isinstance(value, str) and value.strip():
            merged[key] = value.strip()

    try:
        SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(
            json.dumps(merged, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass
    return merged
