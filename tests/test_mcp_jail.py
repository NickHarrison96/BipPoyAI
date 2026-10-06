"""
Jail tests for the MCP workspace server.

These matter more than the happy path: every one of them is an escape that a
prompt injection would reach for. No MCP transport is involved — the tools are
called directly against a temporary grants file, so the tests never touch the
real one.

Run: python tests/test_mcp_jail.py
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mcp_grants  # noqa: E402


class Failure(Exception):
    pass


def check(cond, label):
    if cond:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}")
        raise Failure(label)


def denied(fn, *args, **kwargs):
    """Call a tool expecting PermissionError; True when it refused."""
    try:
        fn(*args, **kwargs)
    except PermissionError:
        return True
    return False


def tools_of(server):
    """{name: callable} for every tool the server registered."""
    return {name: tool.fn for name, tool in server._tool_manager._tools.items()}


def call(tools, name, **kwargs):
    return tools[name](**kwargs)


def with_sandbox(fn):
    """Run fn(root, outside, tools) against a temp tree and temp grants file."""
    tmp = Path(tempfile.mkdtemp())
    original = mcp_grants.GRANTS_FILE
    try:
        root = tmp / "project"
        outside = tmp / "secrets"
        root.mkdir()
        outside.mkdir()
        (root / "a.txt").write_text("hello", encoding="utf-8")
        (outside / "key.txt").write_text("TOPSECRET", encoding="utf-8")

        mcp_grants.GRANTS_FILE = tmp / "grants.json"
        import mcp_server
        fn(root, outside, tools_of(mcp_server.build_server()))
    finally:
        mcp_grants.GRANTS_FILE = original
        shutil.rmtree(tmp, ignore_errors=True)


def test_denies_by_default(root, outside, tools):
    print("nothing granted means nothing works")
    check(denied(tools["read_file"], str(root / "a.txt")),
          "read denied with no grants")
    check(denied(tools["write_file"], str(root / "new.txt"), "x"),
          "write denied with no grants")
    check(denied(tools["run_command"], "echo hi", str(root)),
          "shell denied with no grants")
    check(denied(tools["list_directory"], str(root)),
          "listing denied with no grants")


def test_outside_grant(root, outside, tools):
    print("an ungranted sibling stays off limits")
    mcp_grants.grant(str(root), ["read", "write", "shell"])
    check(call(tools, "read_file", path=str(root / "a.txt")) == "hello",
          "granted file reads")
    check(denied(tools["read_file"], str(outside / "key.txt")),
          "sibling read denied")
    check(denied(tools["write_file"], str(outside / "pwn.txt"), "x"),
          "sibling write denied")
    check(denied(tools["run_command"], "echo hi", str(outside)),
          "sibling shell denied")


def test_traversal(root, outside, tools):
    print(".. traversal cannot climb out of a grant")
    mcp_grants.grant(str(root), ["read", "write", "shell"])
    check(denied(tools["read_file"], str(root / ".." / "secrets" / "key.txt")),
          "read via .. denied")
    check(denied(tools["write_file"],
                 str(root / ".." / "secrets" / "key.txt"), "pwn"),
          "write via .. denied")
    check(denied(tools["run_command"], "echo hi", str(root / "..")),
          "shell cwd via .. denied")
    nested = str(root / "a.txt" / ".." / ".." / "secrets" / "key.txt")
    check(denied(tools["read_file"], nested), "deep .. nesting denied")


def test_symlink_escape(root, outside, tools):
    print("a symlink out of the grant is refused")
    mcp_grants.grant(str(root), ["read"])
    link = root / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        print("  SKIP  symlinks unavailable here")
        return
    check(denied(tools["read_file"], str(link / "key.txt")),
          "read through symlink denied")
    check(denied(tools["list_directory"], str(link)),
          "listing through symlink denied")


def test_capabilities_are_separate(root, outside, tools):
    print("read does not imply write, write does not imply shell")
    mcp_grants.grant(str(root), ["read"])
    check(not denied(tools["read_file"], str(root / "a.txt")), "read works")
    check(denied(tools["write_file"], str(root / "new.txt"), "x"),
          "write refused on a read-only grant")
    check(denied(tools["run_command"], "echo hi", str(root)),
          "shell refused on a read-only grant")

    mcp_grants.revoke(str(root))
    mcp_grants.grant(str(root), ["read", "write"])
    check(not denied(tools["write_file"], str(root / "new.txt"), "x"),
          "write works on a write grant")
    check(denied(tools["run_command"], "echo hi", str(root)),
          "shell still refused without the shell capability")


def test_grants_are_revokable(root, outside, tools):
    print("revoking takes effect immediately")
    mcp_grants.grant(str(root), ["read", "write", "shell"])
    check(not denied(tools["read_file"], str(root / "a.txt")), "granted first")
    mcp_grants.revoke(str(root))
    check(denied(tools["read_file"], str(root / "a.txt")),
          "denied right after revoke")


def test_denial_does_not_leak(root, outside, tools):
    print("a denial does not confirm what is out there")
    mcp_grants.grant(str(root), ["read"])
    try:
        tools["read_file"](str(outside / "key.txt"))
    except PermissionError as exc:
        msg = str(exc).lower()
        check("topsecret" not in msg, "no file contents leaked")
        # It may echo the path the caller supplied — they already know that.
        # What it must not do is reveal existence or invite a retry elsewhere.
        check("not found" not in msg and "does not exist" not in msg,
              "does not claim the path is missing")
        check("permissionerror" not in msg, "no raw exception class leaked")
    else:
        check(False, "expected a denial")


def test_inspection_tools_need_no_grant(root, outside, tools):
    print("safe inspection tools work with no grants")
    mcp_grants.GRANTS_FILE.write_text(json.dumps({"grants": []}), encoding="utf-8")
    out = call(tools, "get_system_resources")
    check("CPU" in out and "RAM" in out, "system resources reported")
    out = call(tools, "list_grants")
    check("No directories granted" in out, "empty grant list reported")
    out = call(tools, "get_ollama_status")
    check(isinstance(out, str) and out.strip() != "",
          "ollama status returns text either way")


def test_command_is_bounded(root, outside, tools):
    print("a hung command is killed rather than wedging the server")
    mcp_grants.grant(str(root), ["shell"])
    out = call(tools, "run_command",
               command="ping -n 60 127.0.0.1", path=str(root))
    check("exceeded" in out.lower() or "timed out" in out.lower(),
          f"timeout reported: {out[:60]!r}")


def test_output_is_truncated(root, outside, tools):
    print("flooding stdout cannot blow out the context window")
    import mcp_server
    mcp_grants.grant(str(root), ["shell"])
    # Write the flooder to a file first: a nested-quote command line is mangled
    # by `cmd /c` before python ever sees it, which would test nothing.
    flooder = root / "flood.py"
    flooder.write_text("print('x' * 500000)", encoding="utf-8")
    out = call(tools, "run_command", command="python flood.py", path=str(root))
    check(len(out) <= mcp_server.MAX_OUTPUT_CHARS + 200,
          f"output capped at {len(out)} chars")
    check("truncated" in out, "truncation disclosed")


def test_edit_refuses_ambiguous_match(root, outside, tools):
    print("an ambiguous edit is refused rather than guessed")
    mcp_grants.grant(str(root), ["write"])
    target = root / "dup.txt"
    target.write_text("x\nx\n", encoding="utf-8")
    out = call(tools, "edit_file", path=str(target), old="x", new="y")
    check("2 times" in out, "ambiguity reported")
    check(target.read_text(encoding="utf-8") == "x\nx\n", "file untouched")
    out = call(tools, "edit_file", path=str(target), old="x", new="y",
               replace_all=True)
    check("Replaced 2" in out, "explicit replace_all proceeds")
    check(target.read_text(encoding="utf-8") == "y\ny\n", "file updated")


def test_write_creates_parents(root, outside, tools):
    print("writing into a new subdirectory works inside the grant")
    mcp_grants.grant(str(root), ["write"])
    target = root / "deep" / "nested" / "out.txt"
    out = call(tools, "write_file", path=str(target), content="made")
    check("Wrote" in out, "write reported")
    check(target.read_text(encoding="utf-8") == "made", "content landed")


def test_grants_file_not_writable(root, outside, tools):
    print("the grants file cannot be rewritten from inside a grant")
    mcp_grants.grant(str(root), ["write"])
    evil = outside / "grants.json"
    payload = json.dumps(
        {"grants": [{"path": str(outside), "capabilities": ["shell"]}]}
    )
    out = call(tools, "write_file", path=str(evil), content=payload) \
        if not denied(tools["write_file"], str(evil), payload) else ""
    check("Wrote" not in out, "write refused outside the grant")
    check(not evil.exists(), "no grants file created outside the jail")


def test_grants_store_ignores_junk(root, outside, tools):
    print("a hand-edited grants file cannot smuggle in a capability")
    mcp_grants.GRANTS_FILE.write_text(json.dumps({
        "grants": [
            {"path": str(root), "capabilities": ["shell", "sudo", "root"]},
            {"path": str(outside), "capabilities": "shell"},
            {"capabilities": ["shell"]},
            "not even a dict",
        ]
    }), encoding="utf-8")
    entries = mcp_grants.list_grants()
    check(len(entries) == 1, f"only the valid entry kept (got {len(entries)})")
    check("shell" in entries[0]["capabilities"], "known capability kept")
    check("sudo" not in entries[0]["capabilities"], "unknown capability dropped")
    check(mcp_grants.has_capability(str(root), "shell"),
          "shell works after a junk-laden edit")


TESTS = [
    test_denies_by_default,
    test_outside_grant,
    test_traversal,
    test_symlink_escape,
    test_capabilities_are_separate,
    test_grants_are_revokable,
    test_denial_does_not_leak,
    test_inspection_tools_need_no_grant,
    test_command_is_bounded,
    test_output_is_truncated,
    test_edit_refuses_ambiguous_match,
    test_write_creates_parents,
    test_grants_file_not_writable,
    test_grants_store_ignores_junk,
]


def main():
    failed = 0
    for fn in TESTS:
        try:
            with_sandbox(fn)
        except Failure:
            failed += 1
            print()
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {fn.__name__}: {type(exc).__name__}: {exc}")
            print()
    print()
    if failed:
        print(f"{failed} test(s) FAILED")
        return 1
    print(f"all {len(TESTS)} jail tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())