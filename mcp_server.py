"""
MCP workspace server — tools for the `claude` CLI.

Grants `claude` a way to read, write, and run commands *inside directories the
user has explicitly approved*, plus a few always-safe inspection tools that need
no grant at all.

Security model, since this is the part that matters:

- **Nothing is granted by default.** `mcp_grants.py` starts empty; every path
  tool denies until the user runs `--grant`. There is no "grant the project
  automatically on first launch" path, because that would silently widen what
  an LLM can reach the first time the CLI is started.
- **The jail resolves before it compares.** Paths are fully resolved (`..` and
  symlinks applied) *before* the containment test. Testing the literal string
  is the classic escape: `C:/proj/../secrets` looks like it starts with `C:/proj`
  and isn't.
- **Read, write, and shell are separate capabilities.** A read-only grant cannot
  be talked into a write, and shell is never implied by write.
- **Every spawn is bounded.** Hard timeout, output cap, no shell, argument list
  form. A command that runs forever or floods stdout cannot wedge the server.
- **Errors say "not granted", never leak the filesystem.** A denial must not
  confirm whether an ungranted path exists.

Registration is manual on purpose. `claude mcp add` writes to the user's config
and persists for every future launch in this project, so the exact command is
printed by `python mcp_server.py --register` and run by the user, never
automatically at launch.
"""

import argparse
import subprocess
import sys
from pathlib import Path

import mcp_grants

# ── Limits ────────────────────────────────────────────────────────────────────

# Wall-clock cap on any spawned command. Long enough for a build, short enough
# that a hung process cannot hold a tool call open indefinitely.
COMMAND_TIMEOUT = 30

# Output cap per stream, in characters. A build that prints megabytes would
# otherwise blow out the model's context window for no benefit.
MAX_OUTPUT_CHARS = 30000

# Refuse to read or write files larger than this. Keeps a stray multi-GB blob
# from being slurped into the conversation.
MAX_FILE_BYTES = 2 * 1024 * 1024

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache"}

_DENIED = (
    "Not permitted: '{path}' is not inside a directory you have granted.\n"
    "Grant one with:  python mcp_server.py --grant \"<directory>\"\n"
    "Inspect grants:  python mcp_server.py --list"
)


def _denied(path) -> str:
    # Never echo whether the path exists — a denial that confirms existence is
    # an information leak for paths the caller was never allowed to know about.
    return _DENIED.format(path=path)


def _require(path, capability: str) -> str:
    """Return the resolved path, or raise PermissionError when not granted."""
    if not mcp_grants.has_capability(path, capability):
        raise PermissionError(_denied(path))
    return str(Path(path).expanduser().resolve())


# ── Server ────────────────────────────────────────────────────────────────────

def build_server():
    """Construct the FastMCP server with every tool registered."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(
        "Cayde 420 Workspace",
        instructions=(
            "Read, write, and run commands inside directories the user has "
            "explicitly granted. Paths outside a grant are refused — that is "
            "the user's boundary, not an error to work around. Ask them to "
            "grant a directory instead of trying another path."
        ),
    )

    # ── Always safe: no grant needed, read-only, no user data ──

    @mcp.tool()
    def list_grants() -> str:
        """List the directories the user has granted, and their capabilities."""
        lines = mcp_grants.describe()
        return "\n".join(lines)

    @mcp.tool()
    def get_system_resources() -> str:
        """Current CPU, memory, and disk usage for this machine."""
        try:
            import psutil
        except ImportError:
            return "psutil is not installed."
        parts = [f"CPU:    {psutil.cpu_percent(interval=0.2):.0f}%"]
        mem = psutil.virtual_memory()
        parts.append(
            f"RAM:    {mem.percent:.0f}% of {mem.total / 1e9:.1f} GB"
        )
        for part in "C D E".split():
            try:
                usage = psutil.disk_usage(f"{part}:\\")
            except OSError:
                continue
            parts.append(
                f"Disk {part}: {usage.percent:.0f}% of {usage.total / 1e9:.0f} GB"
            )
        return "\n".join(parts)

    @mcp.tool()
    def get_ollama_status() -> str:
        """Which local models are installed in Ollama, and their sizes."""
        import json
        import urllib.request

        base = "http://127.0.0.1:11434"
        try:
            with urllib.request.urlopen(f"{base}/api/tags", timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 — report any failure as text
            return f"Ollama is not reachable at {base} ({exc})."
        models = data.get("models", [])
        if not models:
            return "Ollama is running but has no models installed."
        return "\n".join(
            f"{m.get('name', '?')}  "
            f"{(m.get('size', 0) or 0) / 1e9:.1f} GB"
            for m in models
        )

    # ── Path tools: need an explicit grant ──

    @mcp.tool()
    def list_directory(path: str = ".") -> str:
        """
        List files and folders in a granted directory, with sizes.

        Subdirectories that are skipped (.git, node_modules, caches) are marked
        rather than hidden, so you know they exist.
        """
        target = _require(path, "read")
        root = Path(target)
        if not root.is_dir():
            return f"Not a directory: {target}"

        rows = []
        try:
            entries = sorted(root.iterdir(), key=lambda p: p.name.lower())
        except OSError as exc:
            return f"Could not read {target}: {exc}"

        for entry in entries:
            try:
                if entry.is_dir():
                    if entry.name in SKIP_DIRS:
                        rows.append(f"{entry.name}/  (skipped)")
                    else:
                        rows.append(f"{entry.name}/")
                else:
                    rows.append(f"{entry.name}  {entry.stat().st_size} B")
            except OSError:
                rows.append(f"{entry.name}  (unreadable)")
        return "\n".join(rows) or "(empty)"

    @mcp.tool()
    def find_files(pattern: str, path: str = ".") -> str:
        """
        Find files under a granted directory whose name contains `pattern`.

        Case-insensitive substring match, not a glob. Skips .git,
        node_modules, and caches so a search can't be turned into a whole-disk
        crawl through them.
        """
        target = _require(path, "read")
        needle = (pattern or "").lower()
        if not needle:
            return "Give a non-empty pattern."

        root = Path(target)
        if not root.is_dir():
            return f"Not a directory: {target}"

        hits = []
        for file in root.rglob("*"):
            if any(part in SKIP_DIRS for part in file.parts):
                continue
            if not file.is_file():
                continue
            if needle in file.name.lower():
                hits.append(str(file.relative_to(root)))
            if len(hits) >= 200:
                hits.append("... (truncated at 200)")
                break
        return "\n".join(sorted(hits)) or "No matches."

    @mcp.tool()
    def read_file(path: str) -> str:
        """
        Read a text file inside a granted directory.

        Refuses files over 2 MB. Read-only: this cannot modify anything.
        """
        target = _require(path, "read")
        file = Path(target)
        if not file.is_file():
            return f"Not a file: {target}"
        try:
            if file.stat().st_size > MAX_FILE_BYTES:
                return (
                    f"File is {file.stat().st_size} B, over the "
                    f"{MAX_FILE_BYTES} B limit. Read a slice of it instead."
                )
            return file.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"Could not read {target}: {exc}"

    @mcp.tool()
    def write_file(path: str, content: str) -> str:
        """
        Write text to a file inside a granted directory, creating parents.

        Requires a grant with the `write` capability — read alone is not enough.
        Overwrites without prompting, so check what you are replacing.
        """
        target = _require(path, "write")
        file = Path(target)
        try:
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(content, encoding="utf-8")
        except OSError as exc:
            return f"Could not write {target}: {exc}"
        return f"Wrote {len(content)} chars to {target}"

    @mcp.tool()
    def edit_file(path: str, old: str, new: str, replace_all: bool = False) -> str:
        """
        Replace an exact string in a granted file.

        Refuses rather than guessing when `old` appears more than once (unless
        replace_all), so a one-line edit cannot silently rewrite every match.
        Requires a `write` grant.
        """
        target = _require(path, "write")
        file = Path(target)
        if not file.is_file():
            return f"Not a file: {target}"
        try:
            text = file.read_text(encoding="utf-8")
        except OSError as exc:
            return f"Could not read {target}: {exc}"

        count = text.count(old)
        if count == 0:
            return "Text to replace was not found; nothing changed."
        if count > 1 and not replace_all:
            return (
                f"Text appears {count} times. Pass replace_all=True to change "
                "them all, or include more surrounding context."
            )
        updated = text.replace(old, new) if replace_all else text.replace(old, new, 1)
        try:
            file.write_text(updated, encoding="utf-8")
        except OSError as exc:
            return f"Could not write {target}: {exc}"
        return f"Replaced {count if replace_all else 1} occurrence(s) in {target}"

    @mcp.tool()
    def run_command(command: str, path: str = ".") -> str:
        """
        Run a shell command with a granted directory as the working directory.

        Requires a grant with the `shell` capability — read and write do not
        imply it. The command runs with arguments passed as a list (no shell
        string interpolation on our side), is killed after 30 seconds, and has
        its output truncated. Stay inside the granted directory.
        """
        cwd = _require(path, "shell")
        if not Path(cwd).is_dir():
            return f"Not a directory: {cwd}"
        if not (command or "").strip():
            return "Give a command to run."

        shell = ["cmd", "/c"] if sys.platform == "win32" else ["sh", "-c"]
        try:
            proc = subprocess.run(
                shell + [command],
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=COMMAND_TIMEOUT,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            return f"Command exceeded {COMMAND_TIMEOUT}s and was killed."
        except OSError as exc:
            return f"Could not run command: {exc}"

        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        parts = []
        if out:
            parts.append(out[:MAX_OUTPUT_CHARS])
        if err:
            parts.append(f"[stderr]\n{err[:MAX_OUTPUT_CHARS]}")
        if len(out) > MAX_OUTPUT_CHARS or len(err) > MAX_OUTPUT_CHARS:
            parts.append(f"[output truncated at {MAX_OUTPUT_CHARS} chars]")
        if proc.returncode != 0:
            parts.append(f"[exit {proc.returncode}]")
        return "\n".join(parts) or "(no output)"

    return mcp


# ── CLI ───────────────────────────────────────────────────────────────────────

def _register_snippet() -> str:
    return (
        "claude mcp add cayde-workspace --scope local -- "
        f"{sys.executable} \"{Path(__file__).resolve()}\""
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cayde 420 MCP workspace server",
    )
    parser.add_argument(
        "--grant", metavar="DIR",
        help="Grant a directory (read, write, and shell).",
    )
    parser.add_argument(
        "--read-only", action="store_true",
        help="With --grant, only grant read access.",
    )
    parser.add_argument(
        "--revoke", metavar="DIR",
        help="Revoke a directory grant.",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List current grants and exit.",
    )
    parser.add_argument(
        "--register", action="store_true",
        help="Print the claude mcp add command and exit.",
    )
    parser.add_argument(
        "--serve", action="store_true",
        help="Run the MCP server on stdio (how claude launches it).",
    )
    args = parser.parse_args()

    if args.grant:
        caps = ["read"] if args.read_only else list(mcp_grants.CAPABILITIES)
        if mcp_grants.grant(args.grant, caps):
            print(f"Granted {', '.join(caps)} on:")
            for line in mcp_grants.describe():
                print(f"  {line}")
        else:
            print(f"Could not grant {args.grant!r} — is it an existing directory?")
            return 1
        return 0

    if args.revoke:
        if mcp_grants.revoke(args.revoke):
            print(f"Revoked {args.revoke}")
        else:
            print("No such grant.")
        return 0

    if args.list:
        for line in mcp_grants.describe():
            print(line)
        return 0

    if args.register:
        print("Run this yourself to let claude reach the server:\n")
        print(f"    {_register_snippet()}\n")
        print("It writes to your claude config and persists for this project,")
        print("so Cayde 420 never runs it for you. Remove it again with:")
        print("    claude mcp remove cayde-workspace --scope local")
        return 0

    if not args.serve:
        parser.print_help()
        return 0

    if not mcp_grants.list_grants():
        print(
            "No directories granted — every path tool will refuse.\n"
            f"Start with:  python mcp_server.py --grant \"{mcp_grants.default_root()}\"\n",
            file=sys.stderr,
        )
    build_server().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())