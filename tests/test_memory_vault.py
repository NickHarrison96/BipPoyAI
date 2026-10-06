"""
Regression checks for the memory vault.

Pure-data module, so these need no Qt and no running services — they exercise
the injection rules directly. Run: python tests/test_memory_vault.py
"""

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import memory_vault as mv


class Failure(Exception):
    pass


def check(cond, label):
    if cond:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}")
        raise Failure(label)


def with_clean_vault(fn):
    """Run fn() against a throwaway vault directory."""
    original = mv.MEMORY_DIR
    tmp = Path(tempfile.mkdtemp()) / "memory"
    mv.MEMORY_DIR = tmp
    try:
        return fn(tmp)
    finally:
        mv.MEMORY_DIR = original
        shutil.rmtree(tmp.parent, ignore_errors=True)


def test_empty_vault_is_a_noop():
    print("empty vault leaves the persona alone")
    with_clean_vault(lambda _d: None)
    check(mv.compose_system_prompt("You are Cayde.") == "You are Cayde.",
          "persona returned unchanged")
    check(mv.compose_system_prompt("") == "", "empty persona stays empty")
    check(mv.build_block() == "", "no block built")


def test_disabled_vault_is_a_noop():
    print("disabled vault leaves the persona alone")
    with_clean_vault(lambda d: mv.write_entry("a", "note"))
    check(mv.compose_system_prompt("P", enabled=False) == "P",
          "disabled vault not injected")


def test_vault_is_appended():
    print("vault composes onto the persona")
    def body(d):
        mv.write_entry("hw", "RTX 2070 SUPER")
        out = mv.compose_system_prompt("You are Cayde.")
        check(out.startswith("You are Cayde."), "persona preserved")
        check("RTX 2070 SUPER" in out, "entry present")
        check(out.index("You are") < out.index("# Memory"), "persona first")
    with_clean_vault(body)


def test_vault_only():
    print("vault works with no persona")
    def body(d):
        mv.write_entry("hw", "8GB VRAM")
        out = mv.compose_system_prompt("")
        check(out.startswith("# Memory"), "block stands alone")
        check("You are" not in out, "no empty persona line")
    with_clean_vault(body)


def test_strip_is_idempotent():
    """Apply cannot stack copies — the persona box round-trips this value."""
    print("repeated composition does not stack blocks")
    def body(d):
        mv.write_entry("prefs", "be terse")
        persona = "You are Cayde."
        s = persona
        for _ in range(5):
            s = mv.compose_system_prompt(s)
        check(s.count("# Memory") == 1, "exactly one block after 5 rounds")
        check(mv.strip_vault(s) == persona, "strips back to the persona")
    with_clean_vault(body)


def test_block_file_lifecycle():
    print("CLI block file is written and cleaned up")
    def body(d):
        check(mv.write_block_file(mv.build_block()) is None,
              "empty vault writes no file")
        mv.write_entry("x", "hello")
        path = mv.write_block_file(mv.build_block())
        check(path and path.exists(), "file written when populated")
        check("hello" in path.read_text(encoding="utf-8"), "content correct")
        mv.delete_entry("x")
        check(mv.write_block_file(mv.build_block()) is None,
              "no file once emptied")
        check(not Path(mv.BLOCK_FILE).exists(), "stale file removed")
    with_clean_vault(body)


def test_entries_are_whole_not_sliced():
    """Over budget must drop an entry, never hand over half of one."""
    print("over-budget entries are dropped whole")
    def body(d):
        # Sentinels at both ends: a sliced entry shows up as start-without-end.
        mv.write_entry("a", "AAAA" + "x" * 400 + "ZZZZ")
        mv.write_entry("b", "BBBB" + "y" * 400 + "WWWW")
        for cap in range(200, 1400, 25):
            block = mv.build_block(max_chars=cap)
            check(len(block) <= cap, f"within {cap}-char cap")
            for tag in ("AAAA", "ZZZZ"):
                if tag in block:
                    other = "ZZZZ" if tag == "AAAA" else "AAAA"
                    check(other in block,
                          f"entry 'a' whole (both sentinels) at {cap}")
                    break
    with_clean_vault(body)


def test_cap_is_never_exceeded():
    print("cap holds at every size")
    def body(d):
        for i in range(6):
            mv.write_entry(f"e{i}", chr(97 + i) * 300)
        for cap in (150, 200, 300, 500, 800, 1200, 2500, 10000):
            block = mv.build_block(max_chars=cap)
            check(len(block) <= cap, f"within {cap}-char cap")
    with_clean_vault(body)


def test_oversized_entry_yields_nothing():
    print("a single entry bigger than the cap yields no block")
    def body(d):
        mv.write_entry("huge", "z" * 5000)
        check(mv.build_block(max_chars=500) == "", "no partial block")
    with_clean_vault(body)


def test_dropped_entries_are_disclosed():
    print("omissions are stated in the block")
    def body(d):
        mv.write_entry("small", "s" * 20)
        mv.write_entry("big1", "b" * 400)
        mv.write_entry("big2", "c" * 400)
        block = mv.build_block(max_chars=500)
        check("not included" in block, "omission disclosed")
    with_clean_vault(body)


def test_crud_roundtrip():
    print("entry CRUD round-trips")
    def body(d):
        check(mv.write_entry("hw", "8GB") is not None, "write returns a path")
        check(mv.read_entry("hw").strip() == "8GB", "read matches")
        mv.append_entry("hw", "CUDA 12")
        check("CUDA 12" in mv.read_entry("hw"), "append keeps prior text")
        names = [e["name"] for e in mv.list_entries()]
        check(names == sorted(names, key=str.lower), "entries sorted by name")
        check(mv.delete_entry("hw"), "delete succeeds")
        check(mv.delete_entry("hw") is False, "delete of missing is False")
    with_clean_vault(body)


def test_filename_sanitisation():
    print("entry names are sanitised")
    def body(d):
        mv.write_entry("../../etc/passwd", "x")
        check(mv.read_entry("../../etc/passwd").strip() == "x",
              "traversal neutralised, still readable")
        check(not (d.parent.parent / "etc" / "passwd.md").exists(),
              "nothing written outside the vault")
    with_clean_vault(body)


def test_blank_entries_ignored():
    print("blank entries do not produce empty sections")
    def body(d):
        mv.write_entry("empty", "   \n  ")
        mv.write_entry("real", "content")
        block = mv.build_block()
        check("## empty" not in block, "blank entry skipped")
        check("## real" in block, "real entry kept")
    with_clean_vault(body)


TESTS = [
    test_empty_vault_is_a_noop,
    test_disabled_vault_is_a_noop,
    test_vault_is_appended,
    test_vault_only,
    test_strip_is_idempotent,
    test_block_file_lifecycle,
    test_entries_are_whole_not_sliced,
    test_cap_is_never_exceeded,
    test_oversized_entry_yields_nothing,
    test_dropped_entries_are_disclosed,
    test_crud_roundtrip,
    test_filename_sanitisation,
    test_blank_entries_ignored,
]


def main():
    failed = 0
    for fn in TESTS:
        try:
            fn()
        except Failure:
            failed += 1
            print()
    print()
    if failed:
        print(f"{failed} test(s) FAILED")
        return 1
    print(f"all {len(TESTS)} memory vault tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())