"""
Chat history persistence — pure data layer.

Stores conversations as JSON files in ~/.qwythos/history/. Two kinds:
  - Named sessions:  <name>.json     (user-saved via Save button / Ctrl+S)
  - Auto-save:       auto_save.json  (rolling backup, updated on every generation)

No GUI or Qt imports here — safe to call from worker threads and the TUI.
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

HISTORY_DIR = Path.home() / ".qwythos" / "history"


def _ensure_dir() -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def _sanitize(name: str) -> str:
    """Strip characters that are unsafe in filenames."""
    return "".join(c if c.isalnum() or c in "-_ ." else "_" for c in name).strip() or "session"


# ─── Auto-save (rolling backup) ───────────────────────────────────────────────

def auto_save(messages: List[Dict[str, str]]) -> None:
    """Overwrite the rolling auto-save file with the current conversation."""
    _ensure_dir()
    data = {"saved_at": time.time(), "messages": messages}
    try:
        (HISTORY_DIR / "auto_save.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass  # never crash the GUI because history couldn't be written


def load_auto_save() -> List[Dict[str, str]]:
    """Return the auto-saved conversation, or [] if none / corrupt."""
    return load_session(HISTORY_DIR / "auto_save.json")


# ─── Named sessions ───────────────────────────────────────────────────────────

def save_session(messages: List[Dict[str, str]], name: Optional[str] = None) -> Path:
    """
    Save a conversation as a named session file and return its path.
    If name is omitted, a timestamp is used.
    """
    _ensure_dir()
    if not name:
        name = time.strftime("%Y-%m-%d_%H-%M-%S")
    path = HISTORY_DIR / f"{_sanitize(name)}.json"
    data = {"saved_at": time.time(), "messages": messages}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_session(path) -> List[Dict[str, str]]:
    """Load messages from a session file. Returns [] if missing or corrupt."""
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    messages = data.get("messages", [])
    return messages if isinstance(messages, list) else []


def list_sessions() -> List[Dict]:
    """
    Return metadata for every saved session (newest first).
    Each entry: {path, name, saved_at, message_count}
    """
    _ensure_dir()
    sessions = []
    for f in HISTORY_DIR.glob("*.json"):
        if f.name == "auto_save.json":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        sessions.append({
            "path": str(f),
            "name": f.stem,
            "saved_at": data.get("saved_at", 0),
            "message_count": len(data.get("messages", [])),
        })
    sessions.sort(key=lambda s: s["saved_at"], reverse=True)
    return sessions


def delete_session(path) -> bool:
    """Delete a session file. Returns True on success."""
    try:
        Path(path).unlink()
        return True
    except OSError:
        return False
