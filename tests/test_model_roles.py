"""
Role registry and config.yaml alias routing.

No Ollama, no network, no real .state/: registry files are redirected into a
temporary directory. Run: python tests/test_model_roles.py
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import configs
import model_registry as mr

ACTIVE = "deepseek-r1-primary"
CODER = "qwen2.5-coder:7b"
VISION = "llava:7b"


class Failure(Exception):
    pass


def check(cond, label):
    if cond:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}")
        raise Failure(label)


def raises(fn, *args):
    try:
        fn(*args)
    except ValueError:
        return True
    return False


class Sandbox:
    def __enter__(self):
        self.real_state = mr.ROLE_MODELS_FILE
        self.real_external = mr.EXTERNAL_FILE
        self.real_snapshot = self.real_state.read_bytes() if self.real_state.exists() else None
        self.tmp = Path(tempfile.mkdtemp())
        mr.ROLE_MODELS_FILE = self.tmp / ".state" / "role_models.json"
        mr.EXTERNAL_FILE = self.tmp / ".state" / "external_paths.json"
        (self.tmp / "Models").mkdir()
        (self.tmp / "Models" / f"{ACTIVE}.gguf").write_bytes(b"GGUF")
        return self

    def __exit__(self, *exc):
        mr.ROLE_MODELS_FILE = self.real_state
        mr.EXTERNAL_FILE = self.real_external
        after = self.real_state.read_bytes() if self.real_state.exists() else None
        shutil.rmtree(self.tmp, ignore_errors=True)
        if after != self.real_snapshot:
            raise Failure("real .state/role_models.json was modified")
        return False

    def cfg(self, **kw):
        base = dict(
            selected_gguf=f"Models/{ACTIVE}.gguf",
            model_tag=ACTIVE,
            engine_mode="litellm_chat",
            context_size=32768,
            max_tokens=8192,
            litellm_url="http://127.0.0.1:4000",
            litellm_api_key="sk-test",
            ollama_base_url="http://127.0.0.1:11434",
        )
        base.update(kw)
        return configs.ModelConfig(**base)


def entry_names(text):
    return [name for name, _ in configs._config_entries(text)]


def test_tag_validation():
    print("role tags must be exact Ollama tags")
    for good in ("qwythos-heretic", CODER, "hf.co/user/repo:Q4_K_M", "  llava:7b  "):
        check(not raises(mr.validate_role_tag, good), f"accepts {good!r}")
    check(mr.validate_role_tag("  llava:7b ") == "llava:7b", "only whitespace is stripped")
    for bad in ("*", '"*"', "", "   ", "G:/Models/x.gguf", "G:\\Models\\x", "C:x",
                "/abs/model", "a..b", "model.gguf", "a b", ":latest", "x:", "x::y", 5, None):
        check(raises(mr.validate_role_tag, bad), f"rejects {bad!r}")
    check(raises(mr.validate_role, "chat"), "rejects unknown role")
    check(raises(mr.validate_role, "*"), "rejects wildcard role")


def test_save_and_load():
    print("registry persists only whitelisted roles to the redirected file")
    with Sandbox() as sb:
        check(mr.role_tags() == {}, "empty registry by default")
        stored = mr.save_role_tags({"default": ACTIVE, "reasoning": ACTIVE, "coding": CODER,
                                    "vision": None, "multimodal": ""})
        check(stored == {"default": ACTIVE, "reasoning": ACTIVE, "coding": CODER}, "None/empty unset roles")
        check(mr.ROLE_MODELS_FILE.exists() and str(sb.tmp) in str(mr.ROLE_MODELS_FILE), "written in temp dir")
        check(mr.role_tags() == stored, "round trip")
        before = mr.ROLE_MODELS_FILE.read_bytes()
        check(raises(mr.save_role_tags, {"chat": CODER}), "unknown role rejected")
        check(raises(mr.save_role_tags, {"coding": "*"}), "wildcard rejected")
        check(raises(mr.save_role_tags, {"vision": "G:/Models/v.gguf"}), "absolute path rejected")
        check(raises(mr.save_role_tags, {"coding": CODER, "vision": CODER}), "vision == coding rejected")
        check(raises(mr.save_role_tags, {"default": ACTIVE, "multimodal": ACTIVE}), "multimodal == default rejected")
        check(raises(mr.save_role_tags, {"default": ACTIVE, "reasoning": CODER}), "default != reasoning rejected")
        check(mr.ROLE_MODELS_FILE.read_bytes() == before, "failed saves write nothing")
        mr.set_role_tag("vision", VISION)
        check(mr.role_tags().get("vision") == VISION, "set_role_tag adds one role")
        mr.set_role_tag("vision", None)
        check("vision" not in mr.role_tags(), "set_role_tag clears one role")
        check(raises(mr.set_role_tag, "vision", CODER), "set_role_tag enforces conflicts")


def test_hand_edited_file_is_filtered():
    print("hand-edited registry entries fail closed")
    with Sandbox():
        mr.ROLE_MODELS_FILE.parent.mkdir(parents=True, exist_ok=True)
        mr.ROLE_MODELS_FILE.write_text(json.dumps({
            "default": ACTIVE, "coding": "*", "vision": ACTIVE, "multimodal": "C:/m.gguf",
            "chat": "x", "reasoning": ACTIVE,
        }), encoding="utf-8")
        check(mr.role_tags() == {"default": ACTIVE, "reasoning": ACTIVE}, "invalid and unknown entries dropped")
        mr.ROLE_MODELS_FILE.write_text(json.dumps({"coding": CODER, "vision": CODER}), encoding="utf-8")
        check(mr.role_tags() == {"coding": CODER}, "vision aliasing the coder is dropped")
        mr.ROLE_MODELS_FILE.write_text("not json", encoding="utf-8")
        check(mr.role_tags() == {}, "corrupt file reads as empty")


def test_single_model_output_unchanged():
    print("no roles -> same single-entry config as before")
    with Sandbox() as sb:
        text = configs.render_config_yaml(sb.cfg(), role_map={})
        expected = (
            "model_list:\n"
            f"  - model_name: {ACTIVE}\n"
            "    litellm_params:\n"
            f"      model: ollama_chat/{ACTIVE}\n"
            "      api_base: http://127.0.0.1:11434\n"
            "      num_ctx: 32768\n"
            "      max_tokens: 8192\n"
            "      extra_body:\n"
            "        think: false\n"
            "\n"
            "litellm_settings:\n"
            "  drop_params: true\n"
            "  ignore_invalid_params: true\n"
            "  modify_params: true\n"
            "  force_timeout: 600\n"
            "  json_logs: false\n"
        )
        check(text == expected, "byte-identical to the legacy template")


def test_offline_only_active_aliases():
    print("offline: only aliases that target the active tag are emitted")
    with Sandbox() as sb:
        roles = {"default": ACTIVE, "reasoning": ACTIVE, "coding": CODER, "vision": VISION}
        mr.save_role_tags(roles)
        configs.write_all(sb.cfg(), sb.tmp, registered_tags=set())
        text = (sb.tmp / "config.yaml").read_text(encoding="utf-8")
        check(entry_names(text) == [ACTIVE, "default", "reasoning"], "active first, then default/reasoning")
        check("*" not in text, "no wildcard")
        check(CODER not in text and VISION not in text, "unverifiable targets omitted")
        check(mr.role_tags() == roles, "stored mappings preserved while offline")
        _, issues = configs.resolve_role_aliases(sb.cfg(), registered_tags=set())
        check(any("coding" in i and "unavailable" in i for i in issues), "skip reason reported")


def test_online_routing():
    print("online: installed coder/vision tags are routed exactly")
    with Sandbox() as sb:
        roles = {"default": ACTIVE, "reasoning": ACTIVE, "coding": CODER, "vision": VISION, "multimodal": VISION}
        installed = {ACTIVE, CODER, VISION}
        text = configs.render_config_yaml(sb.cfg(), roles, installed)
        check(entry_names(text) == [ACTIVE, "default", "reasoning", "coding", "vision", "multimodal"], "all roles routed, active first")
        (sb.tmp / "config.yaml").write_text(text, encoding="utf-8")
        aliases = configs.load_role_aliases(sb.tmp / "config.yaml")
        check(aliases == {"default": ACTIVE, "reasoning": ACTIVE, "coding": CODER,
                          "vision": VISION, "multimodal": VISION}, "alias targets are exact tags")
        check(text.count("api_base: http://127.0.0.1:11434") == 6, "every alias uses the same backend")

        text = configs.render_config_yaml(sb.cfg(), roles, {ACTIVE, CODER})
        check("vision" not in entry_names(text) and "multimodal" not in entry_names(text), "absent vision weights -> no vision alias")
        check(VISION not in text, "no phantom vision target")


def test_default_never_reroutes():
    print("default/reasoning never route away from the active model")
    with Sandbox() as sb:
        roles = {"default": CODER, "reasoning": CODER}
        text = configs.render_config_yaml(sb.cfg(), roles, {ACTIVE, CODER})
        check(entry_names(text) == [ACTIVE], "mismatched default/reasoning omitted")
        _, issues = configs.resolve_role_aliases(sb.cfg(), roles, {ACTIVE, CODER})
        check(any("active model" in i for i in issues), "reason reported")
        text = configs.render_config_yaml(sb.cfg(model_tag=CODER, selected_gguf=None), roles, {ACTIVE, CODER})
        check(entry_names(text) == [CODER, "default", "reasoning"], "routes once that model is active")
        text = configs.render_config_yaml(sb.cfg(), {"default": f"{ACTIVE}:latest"}, set())
        check(f"model: ollama_chat/{ACTIVE}\n" in text.split("model_name: default")[1], "':latest' treated as the active tag")


def test_conflicts():
    print("aliases cannot collide with the active tag, installed tags or each other")
    with Sandbox() as sb:
        text = configs.render_config_yaml(sb.cfg(model_tag="coding"), {"coding": CODER}, {"coding", CODER})
        check(entry_names(text) == ["coding"], "alias equal to active tag skipped")
        check(text.count("model_name: coding") == 1, "no duplicate model_name")
        text = configs.render_config_yaml(sb.cfg(), {"vision": VISION}, {ACTIVE, VISION, "vision"})
        check(entry_names(text) == [ACTIVE], "alias shadowing an installed model skipped")
        text = configs.render_config_yaml(sb.cfg(), {"coding": CODER, "vision": CODER}, {ACTIVE, CODER})
        check(entry_names(text) == [ACTIVE, "coding"], "explicit conflicting vision skipped")
        text = configs.render_config_yaml(sb.cfg(), {"vision": ACTIVE}, {ACTIVE})
        check(entry_names(text) == [ACTIVE], "active text model never aliased as vision")
        text = configs.render_config_yaml(sb.cfg(), {"*": CODER, "coding": "*"}, {ACTIVE, CODER})
        check(entry_names(text) == [ACTIVE] and "*" not in text, "wildcards in role_map ignored")
        check(raises(configs.render_config_yaml, sb.cfg(model_tag="*"), {}), "wildcard active tag refused")


def test_alias_context_caps():
    print("alias context is conservative and output never exceeds context")
    with Sandbox() as sb:
        roles = {"default": ACTIVE, "coding": CODER}
        text = configs.render_config_yaml(sb.cfg(), roles, {ACTIVE, CODER})
        blocks = dict(configs._config_entries(text))
        check("num_ctx: 32768" in blocks[ACTIVE], "active keeps its context")
        for role in ("default", "coding"):
            check("num_ctx: 8192" in blocks[role] and "max_tokens: 8192" in blocks[role], f"{role} capped at 8192")
        text = configs.render_config_yaml(sb.cfg(context_size=4096, max_tokens=8192), roles, {ACTIVE, CODER})
        blocks = dict(configs._config_entries(text))
        for name in (ACTIVE, "default", "coding"):
            check("num_ctx: 4096" in blocks[name] and "max_tokens: 4096" in blocks[name], f"{name} output <= context 4096")
        text = configs.render_config_yaml(sb.cfg(thinking=True), roles, {ACTIVE, CODER})
        blocks = dict(configs._config_entries(text))
        check("think: true" in blocks["default"] and "think: false" in blocks["coding"], "think only on active-target aliases")


def test_engine_prefix():
    print("aliases follow the engine prefix")
    with Sandbox() as sb:
        text = configs.render_config_yaml(sb.cfg(engine_mode="litellm_standard"), {"coding": CODER}, {ACTIVE, CODER})
        check(f"model: ollama/{CODER}" in text and "ollama_chat/" not in text, "ollama/ prefix used")


def test_load_full_keeps_active():
    print("load_full reads the active entry, never an alias")
    with Sandbox() as sb:
        roles = {"default": ACTIVE, "reasoning": ACTIVE, "coding": CODER}
        configs.write_all(sb.cfg(context_size=16384, max_tokens=4096), sb.tmp, {ACTIVE, CODER}, roles)
        loaded = configs.load_full(sb.tmp)
        check(loaded.model_tag == ACTIVE, "active tag")
        check(loaded.context_size == 16384 and loaded.max_tokens == 4096, "active sizing, not alias sizing")
        check(loaded.engine_mode == "litellm_chat", "engine mode")
        legacy = (
            "model_list:\n"
            "  - model_name: coding\n    litellm_params:\n      model: ollama/x\n      api_base: http://a\n      num_ctx: 8192\n"
            f"  - model_name: {ACTIVE}\n    litellm_params:\n      model: ollama_chat/{ACTIVE}\n      api_base: http://b\n      num_ctx: 20000\n"
            "\nlitellm_settings:\n  drop_params: true\n"
        )
        (sb.tmp / "config.yaml").write_text(legacy, encoding="utf-8")
        y = configs.load_config_yaml(sb.tmp / "config.yaml")
        check(y["model_tag"] == ACTIVE and y["context_size"] == 20000 and y["ollama_url"] == "http://b",
              "alias listed first is not mistaken for active")
        (sb.tmp / "config.yaml").write_text(legacy.replace("model_name: coding", 'model_name: "*"'), encoding="utf-8")
        check(configs.load_config_yaml(sb.tmp / "config.yaml")["model_tag"] == ACTIVE, "wildcard entry skipped")
        role_named = configs.render_config_yaml(sb.cfg(model_tag="coding"), role_map={})
        (sb.tmp / "config.yaml").write_text(role_named, encoding="utf-8")
        check(configs.load_config_yaml(sb.tmp / "config.yaml")["model_tag"] == "coding",
              "a real model tagged coding still loads as active")


def test_registered_tags_are_exact():
    print("installed tags must match size exactly, except implicit :latest")
    with Sandbox() as sb:
        text = configs.render_config_yaml(sb.cfg(), {"coding": CODER}, {ACTIVE, "qwen2.5-coder"})
        check(CODER not in text, "base name cannot stand in for an installed :7b variant")
        text = configs.render_config_yaml(sb.cfg(), {"coding": CODER}, {ACTIVE, "qwen2.5-coder:14b"})
        check(CODER not in text, "different explicit tag is not accepted")
        text = configs.render_config_yaml(sb.cfg(), {"coding": CODER}, {ACTIVE, CODER})
        check(f"model: ollama_chat/{CODER}" in text, "exact installed tag is accepted")


def test_no_hardcoded_drive_paths():
    print("tracked registry/config code has no machine drive paths")
    root = Path(__file__).resolve().parent.parent
    for name in ("model_registry.py", "configs.py"):
        src = (root / name).read_text(encoding="utf-8")
        check("G:\\" not in src and "G:/" not in src, f"{name} has no G: path")


def main():
    tests = [
        test_tag_validation,
        test_save_and_load,
        test_hand_edited_file_is_filtered,
        test_single_model_output_unchanged,
        test_offline_only_active_aliases,
        test_online_routing,
        test_default_never_reroutes,
        test_conflicts,
        test_alias_context_caps,
        test_engine_prefix,
        test_load_full_keeps_active,
        test_registered_tags_are_exact,
        test_no_hardcoded_drive_paths,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Failure:
            failed += 1
        except Exception as exc:
            failed += 1
            print(f"  ERROR {t.__name__}: {type(exc).__name__}: {exc}")
    print()
    print(f"{len(tests) - failed}/{len(tests)} test groups passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
