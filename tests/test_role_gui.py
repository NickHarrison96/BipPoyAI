import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QPushButton

import configs
import main as gui
import memory_vault
import model_registry as mr
import settings

ACTIVE = "deepseek-r1-primary"
CODER = "qwen2.5-coder:7b"
VISION = "llava:7b"


class Failure(Exception):
    pass


def check(condition, label):
    if not condition:
        raise Failure(label)


class FakeBackend(QObject):
    model_list_updated = Signal(list)

    def __init__(self, working_dir):
        super().__init__()
        self.working_dir = str(working_dir)
        self.num_ctx = 32768
        self.max_tokens = 16384
        self.temperature = 0.2
        self.litellm_base_url = "http://127.0.0.1:4000"

    def get_model_tag(self):
        return ACTIVE

    def get_system_prompt(self):
        return ""

    def set_memory_enabled(self, enabled):
        pass

    def get_urls(self):
        return {
            "litellm_base_url": self.litellm_base_url,
            "litellm_api_key": "sk-test",
            "ollama_base_url": "http://127.0.0.1:11434",
        }


def config(root):
    return configs.ModelConfig(
        selected_gguf=f"Models/{ACTIVE}.gguf",
        model_tag=ACTIVE,
        context_size=32768,
        max_tokens=16384,
        litellm_url="http://127.0.0.1:4000",
        litellm_api_key="sk-test",
        ollama_base_url="http://127.0.0.1:11434",
    )


def routes(root):
    text = (root / "config.yaml").read_text(encoding="utf-8")
    return dict(configs._config_entries(text)), configs.load_role_aliases(root / "config.yaml"), text


def save_button(panel):
    buttons = [button for button in panel.findChildren(QPushButton)
               if button.text() == "Save Model Routes"]
    check(len(buttons) == 1, "one Save Model Routes button exists")
    return buttons[0]


@contextmanager
def sandbox(saved=None):
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "Models").mkdir()
        (root / "Models" / f"{ACTIVE}.gguf").write_bytes(b"GGUF")
        with patch.object(mr, "ROLE_MODELS_FILE", root / ".state" / "role_models.json"), \
             patch.object(mr, "EXTERNAL_FILE", root / ".state" / "external_paths.json"), \
             patch.object(settings, "SETTINGS_FILE", root / ".state" / "settings.json"), \
             patch.object(memory_vault, "MEMORY_DIR", root / ".state" / "memory"), \
             patch.object(gui.SettingsPanel, "_sync_service_status"), \
             patch.object(gui.QMessageBox, "warning") as warning:
            if saved is not None:
                mr.save_role_tags(saved)
            configs.write_all(config(root), root, registered_tags=set(), role_map={})
            backend = FakeBackend(root)
            panel = gui.SettingsPanel(backend)
            panel._service_status_timer.stop()
            try:
                yield app, root, backend, panel, warning
            finally:
                panel.close()
                panel.deleteLater()
                app.processEvents()


def test_save_installed_exact_routes_and_context_cap():
    with sandbox() as (app, root, backend, panel, warning):
        backend.model_list_updated.emit([ACTIVE, CODER, "qwen2.5-coder:14b"])
        app.processEvents()
        check(panel.role_combos["default"].findData(ACTIVE) >= 0, "active tag is selectable")
        check(panel.role_combos["coding"].findData(CODER) >= 0, "exact coder tag is selectable")
        panel.role_combos["default"].setCurrentIndex(panel.role_combos["default"].findData(ACTIVE))
        panel.role_combos["coding"].setCurrentIndex(panel.role_combos["coding"].findData(CODER))
        save_button(panel).click()
        entries, aliases, text = routes(root)
        check(not warning.called, "valid routes save without warning")
        check(mr.role_tags() == {"default": ACTIVE, "reasoning": ACTIVE, "coding": CODER},
              "saved registry contains only selected exact tags and paired active roles")
        check(list(entries) == [ACTIVE, "default", "reasoning", "coding"], "config emits only active and selected aliases")
        check(aliases == {"default": ACTIVE, "reasoning": ACTIVE, "coding": CODER},
              "aliases target the exact installed tags")
        check("model: ollama_chat/qwen2.5-coder:14b" not in text, "other coder size is not routed")
        check("num_ctx: 32768" in entries[ACTIVE] and "max_tokens: 16384" in entries[ACTIVE],
              "active model keeps its context and output budget")
        for role in aliases:
            check("num_ctx: 8192" in entries[role] and "max_tokens: 8192" in entries[role],
                  f"{role} is capped at 8k")
        check("*" not in text, "no wildcard is generated")


def test_offline_skips_coding_and_online_update_restores_it():
    saved = {"default": ACTIVE, "reasoning": ACTIVE, "coding": CODER}
    with sandbox(saved) as (app, root, backend, panel, warning):
        configs.write_all(config(root), root, registered_tags=set())
        entries, aliases, text = routes(root)
        check(list(entries) == [ACTIVE, "default", "reasoning"], "offline config skips coder")
        check(aliases == {"default": ACTIVE, "reasoning": ACTIVE}, "offline routes only active roles")
        check(mr.role_tags() == saved, "offline does not discard saved coder")
        check("*" not in text, "offline config has no wildcard")
        with patch.object(gui, "write_all", wraps=configs.write_all) as writer:
            backend.model_list_updated.emit([ACTIVE, CODER])
            app.processEvents()
            check(writer.call_count == 1, "online model list rewrites stale routes with write_all")
        entries, aliases, text = routes(root)
        check(list(entries) == [ACTIVE, "default", "reasoning", "coding"], "online update re-adds coder")
        check(aliases["coding"] == CODER, "restored coder target is exact")
        check("num_ctx: 8192" in entries["coding"] and "max_tokens: 8192" in entries["coding"],
              "restored coder retains 8k cap")
        check(mr.role_tags() == saved and not warning.called, "reconciliation preserves saved registry")
        check("*" not in text, "online config has no wildcard")


def test_absent_vision_is_not_offered_or_routed():
    with sandbox() as (app, root, backend, panel, warning):
        backend.model_list_updated.emit([ACTIVE, CODER])
        app.processEvents()
        for role in ("vision", "multimodal"):
            combo = panel.role_combos[role]
            check(not combo.isEditable() and combo.findData(VISION) == -1,
                  f"{role} cannot select absent vision tag")
            check(combo.currentData() == "", f"{role} remains unassigned")
        save_button(panel).click()
        entries, aliases, text = routes(root)
        check(not warning.called, "saving without vision succeeds")
        check("vision" not in entries and "multimodal" not in entries,
              "absent vision aliases are not emitted")
        check(VISION not in text and "*" not in text, "no phantom vision route or wildcard")
        check(aliases == {} and mr.role_tags() == {}, "no unselected roles are persisted")


def test_uninstalled_saved_target_is_rejected():
    saved = {"default": ACTIVE, "reasoning": ACTIVE, "vision": VISION}
    with sandbox(saved) as (app, root, backend, panel, warning):
        backend.model_list_updated.emit([ACTIVE, CODER])
        app.processEvents()
        combo = panel.role_combos["vision"]
        check(combo.currentData() == VISION and "not installed" in combo.currentText(),
              "previously assigned missing model is marked unavailable")
        before = (root / "config.yaml").read_bytes()
        save_button(panel).click()
        check(warning.call_count == 1 and VISION in warning.call_args.args[2],
              "save warns about the uninstalled target")
        check(mr.role_tags() == saved, "rejected save leaves registry unchanged")
        check((root / "config.yaml").read_bytes() == before, "rejected save leaves config unchanged")
        check("*" not in before.decode("utf-8"), "rejected route never adds wildcard")


TESTS = [
    test_save_installed_exact_routes_and_context_cap,
    test_offline_skips_coding_and_online_update_restores_it,
    test_absent_vision_is_not_offered_or_routed,
    test_uninstalled_saved_target_is_rejected,
]


def main():
    failed = 0
    for test in TESTS:
        try:
            test()
        except Exception as exc:
            failed += 1
            print(f"  FAIL  {test.__name__}: {type(exc).__name__}: {exc}")
        else:
            print(f"  PASS  {test.__name__}")
    print(f"{len(TESTS) - failed}/{len(TESTS)} role GUI tests passed")
    return int(failed != 0)


if __name__ == "__main__":
    sys.exit(main())
