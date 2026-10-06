"""
Directory grants for the MCP workspace server — pure data layer.

The MCP server can read, write, and run shell commands, but only inside
directories the user has explicitly granted by hand. Nothing is granted by
default, and there is no wildcard: a grant for `C:/proj` does not extend to
`C:/proj/../secrets` or to a symlink pointing out of the tree.

This is deliberately a separate module from mcp_server.py so the GUI, the TUI,
and the server can all read and edit grants without importing the MCP SDK.

Grants live in `.state/mcp_grants.json` alongside the other per-PC state, so a
fresh clone has none and the server refuses everything until the user opts in.
"""

import json
import os
from pathlib import Path
from typing import List

import settings

GRANTS_FILE = settings.SETTINGS_DIR / "mcp_grants.json"

# Capabilities that can be granted per directory. Kept explicit rather than
# boolean flags so an unknown key in the JSON is ignored instead of silently
# enabling something the user never asked for.
CAPABILITIES = ("read", "write", "shell")

DEFAULTS = {"grants": []}


def _load() -> dict:
    try:
        raw = json.loads(GRANTS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return dict(DEFAULTS)
    entries = raw.get("grants")
    if not isinstance(entries, list):
        return dict(DEFAULTS)
    cleaned = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        if not isinstance(path, str) or not path.strip():
            continue
        caps = item.get("capabilities")
        # An entry with no capabilities is a grant to nothing. Drop it rather
        # than defaulting to a full grant.
        if not isinstance(caps, list):
            continue
        valid = sorted({c for c in caps if c in CAPABILITIES})
        if not valid:
            continue
        cleaned.append({"path": path.strip(), "capabilities": valid})
    return {"grants": cleaned}


def _save(data: dict) -> bool:
    try:
        settings.SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        GRANTS_FILE.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except OSError:
        return False
    return True


def list_grants() -> List[dict]:
    """Return every grant: {path, capabilities}. Absolute paths."""
    return _load()["grants"]


def grant(path: str, capabilities=None) -> bool:
    """
    Grant capabilities on a directory. Idempotent; merges into an existing
    grant rather than replacing it.

    The path is stored absolute and resolved, so a grant cannot later be
    re-pointed at a different directory by moving the process cwd.
    """
    caps = sorted(set(capabilities or CAPABILITIES) & set(CAPABILITIES))
    if not caps:
        return False
    try:
        resolved = str(Path(path).expanduser().resolve())
    except (OSError, RuntimeError):
        return False
    if not Path(resolved).is_dir():
        return False

    data = _load()
    for entry in data["grants"]:
        if entry["path"] == resolved:
            merged = sorted(set(entry["capabilities"]) | set(caps))
            if merged == entry["capabilities"]:
                return True
            entry["capabilities"] = merged
            return _save(data)
    data["grants"].append({"path": resolved, "capabilities": caps})
    return _save(data)


def revoke(path: str) -> bool:
    """Remove the grant for a directory. True when something was removed."""
    try:
        target = str(Path(path).expanduser().resolve())
    except (OSError, RuntimeError):
        return False
    data = _load()
    before = len(data["grants"])
    data["grants"] = [g for g in data["grants"] if g["path"] != target]
    if len(data["grants"]) == before:
        return False
    return _save(data)


def granted_roots() -> List[str]:
    """Absolute paths of every granted directory, longest first.

    Longest-first matters when one grant nests inside another: the caller walks
    this list and must match the most specific root, or a parent grant would
    shadow a more restrictive nested one.
    """
    roots = [g["path"] for g in _load()["grants"]]
    return sorted(roots, key=len, reverse=True)


def resolve_grant(target) -> tuple:
    """
    Find the grant covering `target` and return (root, capabilities).

    `target` is fully resolved first, so `..` segments and symlinks are applied
    before the containment test. Comparing the unresolved path instead is what
    makes naive jails escapeable.

    Returns (None, []) when nothing covers it — the caller must deny.
    """
    try:
        real = Path(target).expanduser().resolve()
    except (OSError, RuntimeError):
        return None, []

    for entry in _load()["grants"]:
        root = Path(entry["path"])
        try:
            if real == root or root in real.parents:
                return entry["path"], entry["capabilities"]
        except (OSError, ValueError):
            # Different drives on Windows can raise here; treat as no match.
            continue
    return None, []


def has_capability(target, capability: str) -> bool:
    """True when `target` sits inside a grant that includes `capability`."""
    if capability not in CAPABILITIES:
        return False
    _root, caps = resolve_grant(target)
    return capability in caps


def describe() -> List[str]:
    """Human-readable grant summary for the CLI."""
    grants = list_grants()
    if not grants:
        return ["No directories granted. Every tool call will be denied."]
    return [
        f"{g['path']}  [{', '.join(g['capabilities'])}]"
        for g in grants
    ]


def default_root() -> str:
    """The project directory, offered as the obvious thing to grant."""
    return os.path.dirname(os.path.abspath(__file__))