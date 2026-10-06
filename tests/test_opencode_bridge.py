"""
Non-destructiveness tests for the OpenCode config bridge.

opencode_bridge writes a file in the user's home directory
(~/.config/opencode/opencode.json), which on this machine already holds a real
$schema and an MCP_DOCKER entry. Losing that is the whole failure mode this file
exists to rule out, so the emphasis is on "what did it NOT touch" rather than on
the happy path.

Every test runs inside with_isolated_config(), which repoints CONFIG_DIR and
CONFIG_FILE at a throwaway temp directory and asserts, after the fact, that the
real ones still hold their original bytes. Nothing here reads or writes the real
config except that final assertion, which is read-only.

The /v1 section is the other half. provider_block() once wrote a bare
"http://127.0.0.1:4000" as baseURL; @ai-sdk/anthropic appends "/messages" to it,
LiteLLM serves "/v1/messages" and 404s "/messages", so every OpenCode request
would have failed at runtime with no visible cause. with_api_version() is the
fix, and the tests assert it from BOTH ends: the helper's own behaviour, and
the URL that actually reaches the written file.

Run: python tests/test_opencode_bridge.py
"""

import io
import json
import shutil
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import opencode_bridge as ob  # noqa: E402

REAL_CONFIG = Path.home() / ".config" / "opencode" / "opencode.json"

# Written into the throwaway config dir as the "user's" existing config. The
# em-dash and the nested MCP command list are the parts a careless rewrite
# flattens or drops, so they are the parts worth asserting on.
USER_CONFIG = {
    "$schema": "https://opencode.ai/config.json",
    "provider": {
        "myprovider": {
            "npm": "@ai-sdk/openai-compatible",
            "name": "Something The User Set Up",
            "options": {"baseURL": "https://example.invalid/v1"},
            "models": {"some-model": {"name": "Some Model"}},
        }
    },
    "mcp": {
        "MCP_DOCKER": {
            "type": "local",
            "command": ["docker", "mcp", "gateway", "run",
                        "--profile", "dev_workflow"],
            "enabled": True,
        }
    },
    "theme": "opencode",
}

CONFIG_YAML = """model_list:
  - model_name: test-tag-under-test
    litellm_params:
      model: ollama_chat/test-tag-under-test
      api_base: http://127.0.0.1:11434
      num_ctx: 16384
      max_tokens: 4096

litellm_settings:
  drop_params: true
"""


class Failure(Exception):
    pass


def check(cond, label):
    if cond:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}")
        raise Failure(label)


def exits(fn, *args, **kwargs):
    """Call fn expecting SystemExit; returns the message it exited with."""
    try:
        fn(*args, **kwargs)
    except SystemExit as exc:
        return str(exc)
    return None


def captured(fn, *args, **kwargs):
    """Call fn with stdout captured; returns (return_value, stdout)."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        value = fn(*args, **kwargs)
    return value, buf.getvalue()


def with_isolated_config(fn):
    """Run fn(work_dir, config_file) against a temp config + temp project dir."""
    tmp = Path(tempfile.mkdtemp())
    real_dir, real_file = ob.CONFIG_DIR, ob.CONFIG_FILE
    try:
        work = tmp / "project"
        cfg_dir = tmp / "home" / ".config" / "opencode"
        work.mkdir()
        cfg_dir.mkdir(parents=True)
        (work / "config.yaml").write_text(CONFIG_YAML, encoding="utf-8")

        ob.CONFIG_DIR = cfg_dir
        ob.CONFIG_FILE = cfg_dir / "opencode.json"
        # Belt and braces: prove the patch took, so no test can silently write
        # to the real file because an assignment above was misspelled. Silent on
        # success — it is a guard rail, not a test result.
        if not str(ob.CONFIG_FILE).startswith(str(tmp)):
            raise Failure("config paths were not repointed into the temp tree")
        return fn(work, ob.CONFIG_FILE)
    finally:
        ob.CONFIG_DIR, ob.CONFIG_FILE = real_dir, real_file
        shutil.rmtree(tmp, ignore_errors=True)


def seed_user_config(path: Path, doc=None):
    path.write_text(json.dumps(doc if doc is not None else USER_CONFIG,
                               indent=2) + "\n", encoding="utf-8")


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_with_api_version_appends_the_prefix(work, path):
    """The bug: a bare port produced a baseURL the proxy does not serve."""
    print("with_api_version puts the /v1 prefix on a bare port")
    got = ob.with_api_version("http://127.0.0.1:4000")
    check(got == "http://127.0.0.1:4000/v1", f"bare port suffixed (got {got})")
    check(f"{got}/messages" == "http://127.0.0.1:4000/v1/messages",
          "the request @ai-sdk/anthropic will build is the route LiteLLM serves")


def test_with_api_version_tolerates_a_trailing_slash(work, path):
    print("a trailing slash does not turn into //v1")
    got = ob.with_api_version("http://127.0.0.1:4000/")
    check(got == "http://127.0.0.1:4000/v1", f"normalised to the same root (got {got})")
    check("//v1" not in got, f"no doubled separator (got {got})")


def test_with_api_version_is_idempotent(work, path):
    """Re-running the bridge must not grow the URL on every launch."""
    print("an already-versioned URL is left alone")
    once = ob.with_api_version("http://127.0.0.1:4000/v1")
    twice = ob.with_api_version(once)
    check(once == "http://127.0.0.1:4000/v1", f"already versioned is stable (got {once})")
    check(twice == once, f"applying it again changes nothing (got {twice})")
    check(ob.with_api_version("http://127.0.0.1:4000/v1/") == once,
          "a slash after /v1 still normalises back to /v1")
    check(ob.with_api_version("http://127.0.0.1:4000/v1").count("/v1") == 1,
          "not double-suffixed")


def test_with_api_version_empty_input_does_not_crash(work, path):
    """build_config falls back to a default, but a direct caller may pass nothing."""
    print("empty or missing input returns something instead of raising")
    for value in ("", None):
        got = ob.with_api_version(value)
        check(isinstance(got, str), f"{value!r} returns a string (got {got!r})")
        check(got == "", f"{value!r} yields the empty string (got {got!r})")
    check(ob.with_api_version("///") == "", "a slash-only URL collapses to empty")


def test_provider_block_shape(work, path):
    print("provider block is the shape OpenCode expects")
    block = ob.provider_block("some-tag", "http://127.0.0.1:4000",
                              context=32768, output=8192,
                              api_key="sk-test")
    check(block["npm"] == "@ai-sdk/anthropic", "anthropic npm package")
    check(block["options"]["baseURL"] == "http://127.0.0.1:4000/v1",
          "baseURL comes from config, carrying the /v1 prefix the SDK needs")
    check(bool(block["options"]["apiKey"]), "apiKey present")
    check(list(block["models"]) == ["some-tag"],
          f"exactly one model, keyed by tag (got {list(block['models'])})")
    check(block["models"]["some-tag"]["limit"] == {"context": 32768,
                                                   "output": 8192},
          "limit block carries both sizes")


def test_provider_block_calls_the_helper(work, path):
    """
    The assertion that actually protects the bug.

    with_api_version() can be perfectly correct while provider_block() never calls
    it, and the failure is invisible until runtime: @ai-sdk/anthropic appends
    `/messages`, LiteLLM 404s the unversioned path, and the connection looks fine.
    So assert on the CALLER's output, not just the helper's.
    """
    print("provider_block hands the SDK a URL LiteLLM actually serves")
    block = ob.provider_block("some-tag", "http://127.0.0.1:4000")
    base = block["options"]["baseURL"]
    check(base.endswith("/v1"), f"baseURL ends in /v1 (got {base})")
    check(base != "http://127.0.0.1:4000",
          "baseURL is not the bare port that 404s")
    check(f"{base}/messages".endswith("/v1/messages"),
          f"the SDK's resulting path is the one that exists (got {base}/messages)")

    already = ob.provider_block("some-tag", "http://127.0.0.1:4000/v1")
    check(already["options"]["baseURL"] == base,
          "an already-versioned input gives the same block, not /v1/v1")


def test_build_config_carries_the_api_root(work, path):
    print("build_config hands the URL straight through from config.yaml")
    doc = ob.build_config(work)
    base = doc["provider"][ob.PROVIDER_ID]["options"]["baseURL"]
    check(base.endswith("/v1"), f"merged block ends in /v1 (got {base})")
    check(base == "http://127.0.0.1:4000/v1",
          f"the bare port from config.yaml was versioned (got {base})")


def test_written_file_carries_the_api_root(work, path):
    """End-to-end: what OpenCode would actually read off disk."""
    print("the URL on disk is one LiteLLM answers")
    seed_user_config(path)
    ob.write_config(work)
    base = read(path)["provider"][ob.PROVIDER_ID]["options"]["baseURL"]
    check(base.endswith("/v1"), f"written baseURL ends in /v1 (got {base})")
    check("/v1/messages" in f"{base}/messages", "SDK path would reach the route")
    check("//v1" not in base, f"no doubled separator on disk (got {base})")


def test_provider_block_sizes_follow_config(work, path):
    print("window sizes are read from config.yaml, not pinned in the module")
    doc = ob.build_config(work)
    limit = doc["provider"][ob.PROVIDER_ID]["models"]["test-tag-under-test"]["limit"]
    check(limit["context"] == 16384, f"context read from config.yaml ({limit})")
    check(limit["output"] == 4096, f"output read from config.yaml ({limit})")


def test_build_config_preserves_user_content(work, path):
    print("an existing user config survives a merge untouched")
    seed_user_config(path)
    doc = ob.build_config(work)
    check(doc["$schema"] == USER_CONFIG["$schema"], "$schema kept")
    check("myprovider" in doc["provider"], "unrelated provider kept")
    check(doc["provider"]["myprovider"] == USER_CONFIG["provider"]["myprovider"],
          "unrelated provider byte-for-byte identical")
    check(doc["mcp"] == USER_CONFIG["mcp"], "mcp block kept intact")
    check(doc["theme"] == "opencode", "unrelated top-level key kept")
    check(ob.PROVIDER_ID in doc["provider"], "our provider added")
    check(path.read_text(encoding="utf-8") ==
          json.dumps(USER_CONFIG, indent=2) + "\n",
          "build_config did not write to disk")


def test_build_config_refuses_malformed_json(work, path):
    print("a config it cannot parse is refused, not overwritten")
    broken = '{"$schema": "https://opencode.ai/config.json", "mcp": {'
    path.write_text(broken, encoding="utf-8")
    msg = exits(ob.build_config, work)
    check(msg is not None, "SystemExit on malformed JSON")
    check("will not overwrite" in msg, "refusal explains itself")
    check(path.read_text(encoding="utf-8") == broken, "file left as it was")


def test_build_config_refuses_non_object_document(work, path):
    print("a JSON array is not a config")
    path.write_text('["not", "a", "config"]', encoding="utf-8")
    msg = exits(ob.build_config, work)
    check(msg is not None, "SystemExit on a non-object document")
    check("not a JSON object" in msg, "reason names the shape")


def test_build_config_refuses_non_object_provider(work, path):
    print("an existing non-object 'provider' is refused")
    for junk in ('"a string"', "[1, 2, 3]", "null"):
        seed_user_config(path, {"provider": junk})
        msg = exits(ob.build_config, work)
        check(msg is not None, f"SystemExit on provider={junk}")
        check("non-object 'provider'" in msg, f"reason names the key ({junk})")
        check(path.read_text(encoding="utf-8") == json.dumps(
            {"provider": junk}, indent=2) + "\n",
            f"file untouched ({junk})")


def test_undecodable_bytes_are_refused(work, path):
    """cp1252 bytes are corruption, not syntax — still must not be clobbered."""
    print("a config that is not even UTF-8 is refused")
    path.write_bytes(b'{"theme": "caf\xe9"}')
    msg = exits(ob.build_config, work)
    check(msg is not None, "SystemExit on undecodable bytes")
    check("will not overwrite" in msg, "refusal explains itself")
    check(path.read_bytes() == b'{"theme": "caf\xe9"}', "bytes left as they were")


def test_bom_is_tolerated(work, path):
    print("a Windows BOM is an editor artefact, not a reason to refuse")
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(USER_CONFIG).encode("utf-8"))
    doc = ob.build_config(work)
    check(doc["mcp"] == USER_CONFIG["mcp"], "BOM'd config read correctly")
    check(ob.PROVIDER_ID in doc["provider"], "merge proceeds past the BOM")


def test_write_config_creates_backup(work, path):
    print("the previous config is kept before it is overwritten")
    seed_user_config(path)
    original = path.read_text(encoding="utf-8")
    returned = ob.write_config(work)
    check(returned == path, "write_config returns the path it wrote")

    backup = ob.backup_path()
    check(backup.exists(), f"backup exists at {backup.name}")
    check(backup != path, "backup is a different file")
    check(backup.read_text(encoding="utf-8") == original,
          "backup holds the ORIGINAL content")
    check(backup.suffix == ob.BACKUP_SUFFIX,
          f"backup named from BACKUP_SUFFIX ({backup.name})")
    doc = read(path)
    check(doc["mcp"] == USER_CONFIG["mcp"], "live file still has the mcp block")
    check(ob.PROVIDER_ID in doc["provider"], "live file has our provider")


def test_backup_path_is_the_one_announced(work, path):
    """main() printed path.with_suffix() + suffix before, which was never written."""
    print("the backup path main() prints is the path that exists")
    seed_user_config(path)
    _, out = captured(ob.main, [])
    check(str(ob.backup_path()) in out, "printed path matches backup_path()")
    check(str(ob.backup_path()) in out and ob.backup_path().exists(),
          "printed path exists on disk")


def test_write_config_creates_missing_dir(work, path):
    print("a fresh machine with no ~/.config/opencode works")
    shutil.rmtree(path.parent)
    check(not path.parent.exists(), "config directory is gone")
    returned = ob.write_config(work)
    check(returned.exists(), f"config written at {returned.name}")
    check(not ob.backup_path().exists(), "no backup when there was nothing to copy")
    check(ob.PROVIDER_ID in read(path)["provider"], "provider present")


def test_write_config_is_idempotent(work, path):
    print("running it twice changes nothing the second time")
    seed_user_config(path)
    ob.write_config(work)
    first = path.read_text(encoding="utf-8")
    first_size = path.stat().st_size
    ob.write_config(work)
    second = path.read_text(encoding="utf-8")
    check(first == second, "byte-identical after a second write")
    check(path.stat().st_size == first_size, "file did not grow")
    doc = read(path)
    check(len(doc["provider"]) == 2, f"no duplicate provider keys ({len(doc['provider'])})")
    check(len(doc["provider"][ob.PROVIDER_ID]["models"]) == 1, "still one model")
    check(second.count(f'"{ob.PROVIDER_ID}":') == 1,
          "provider key written exactly once")


def test_switching_models_does_not_accumulate(work, path):
    print("a different tag replaces the old one instead of piling up")
    seed_user_config(path)
    ob.write_config(work)
    first_models = list(read(path)["provider"][ob.PROVIDER_ID]["models"])

    (work / "config.yaml").write_text(
        CONFIG_YAML.replace("test-tag-under-test", "second-tag"),
        encoding="utf-8")
    ob.write_config(work)

    models = list(read(path)["provider"][ob.PROVIDER_ID]["models"])
    check(models == ["second-tag"], f"only the new tag remains ({models})")
    check(first_models != models, "the old tag is gone")
    doc = read(path)
    check(doc["mcp"] == USER_CONFIG["mcp"], "user content still intact after switch")
    check("myprovider" in doc["provider"], "user provider still intact after switch")


def test_tag_comes_from_config_yaml(work, path):
    print("the model tag is read, not hardcoded")
    doc = ob.build_config(work)
    check("test-tag-under-test" in doc["provider"][ob.PROVIDER_ID]["models"],
          "tag from config.yaml reaches the provider block")

    source = Path(ob.__file__).read_text(encoding="utf-8")
    for baked in ("qwythos", "heretic", "Qwythos"):
        check(baked not in source, f"no '{baked}' literal baked into the module")


def test_launch_reports_missing_binary(work, path):
    print("a missing opencode is reported, not a silent success")
    real_which = shutil.which
    ob.shutil.which = lambda name: None
    try:
        code, out = captured(ob.launch, work)
    finally:
        ob.shutil.which = real_which
    check(code == 1, f"nonzero exit code ({code})")
    check("not in your PATH" in out, "reason stated on stdout")


def test_launch_cmdline_quotes_spaces(work, path):
    print("an extra arg containing a space survives the cmd round trip")
    line = ob._cmdline(["opencode", "-m", "cayde/tag", "--session", "my chat"])
    check('"my chat"' in line, f"spaced arg quoted ({line})")
    check(line.count('"') == 2, "exactly one quoted run")


def test_main_rejects_the_dead_model_flag(work, path):
    print("--model is gone rather than parsed and ignored")
    help_out = io.StringIO()
    with redirect_stdout(help_out):
        code = exits(ob.main, ["--help"])
    check(code == "0", f"--help exits zero ({code})")
    check("--model" not in help_out.getvalue(), "help does not advertise --model")

    err = io.StringIO()
    with redirect_stderr(err):
        code = exits(ob.main, ["--model", "some-other-tag"])
    check(code == "2", f"--model is a usage error, exit 2 ({code})")
    check("unrecognized arguments" in err.getvalue(),
          "argparse says the flag does not exist")
    check(not path.exists(), "a rejected flag writes nothing")


def test_print_writes_nothing(work, path):
    print("--print shows the config without touching it")
    seed_user_config(path)
    before = path.read_text(encoding="utf-8")
    code, out = captured(ob.main, ["--print"])
    check(code == 0, f"exits zero ({code})")
    check('"npm": "@ai-sdk/anthropic"' in out, "provider block shown")
    check(path.read_text(encoding="utf-8") == before, "file untouched by --print")
    check(not ob.backup_path().exists(), "no backup taken by --print")


TESTS = [
    test_with_api_version_appends_the_prefix,
    test_with_api_version_tolerates_a_trailing_slash,
    test_with_api_version_is_idempotent,
    test_with_api_version_empty_input_does_not_crash,
    test_provider_block_shape,
    test_provider_block_calls_the_helper,
    test_build_config_carries_the_api_root,
    test_written_file_carries_the_api_root,
    test_provider_block_sizes_follow_config,
    test_build_config_preserves_user_content,
    test_build_config_refuses_malformed_json,
    test_build_config_refuses_non_object_document,
    test_build_config_refuses_non_object_provider,
    test_undecodable_bytes_are_refused,
    test_bom_is_tolerated,
    test_write_config_creates_backup,
    test_backup_path_is_the_one_announced,
    test_write_config_creates_missing_dir,
    test_write_config_is_idempotent,
    test_switching_models_does_not_accumulate,
    test_tag_comes_from_config_yaml,
    test_launch_reports_missing_binary,
    test_launch_cmdline_quotes_spaces,
    test_main_rejects_the_dead_model_flag,
    test_print_writes_nothing,
]


def real_config_fingerprint():
    """(exists, size, bytes) of the user's actual config, or None if absent."""
    if not REAL_CONFIG.exists():
        return None
    return (True, REAL_CONFIG.stat().st_size, REAL_CONFIG.read_bytes())


def main():
    before = real_config_fingerprint()
    if before:
        print(f"real config guarded: {REAL_CONFIG} ({before[1]} bytes)\n")
    else:
        print(f"real config absent, nothing to guard: {REAL_CONFIG}\n")

    failed = 0
    for fn in TESTS:
        try:
            with_isolated_config(fn)
        except Failure:
            failed += 1
            print()
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {fn.__name__}: {type(exc).__name__}: {exc}")
            print()

    after = real_config_fingerprint()
    print()
    if before != after:
        print(f"  FAIL  real config changed: {before} -> {after}")
        failed += 1
    elif before:
        print(f"  PASS  real config untouched ({after[1]} bytes, identical)")

    print()
    if failed:
        print(f"{failed} test(s) FAILED")
        return 1
    print(f"all {len(TESTS)} opencode bridge tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
