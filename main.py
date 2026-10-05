"""
Qwythos AI — Standalone Local Chat Interface

A polished PySide6 desktop GUI for chatting with the Qwythos-9B model
running locally through Ollama + LiteLLM proxy.

Usage:
    python main.py
    (or double-click launch.bat)
"""

import sys
import os
import re
from pathlib import Path

if sys.version_info < (3, 11):
    print("ERROR: Python 3.11 or newer is required.")
    print(f"You are running Python {sys.version.split()[0]}.")
    print("Download the latest version from https://python.org")
    input("Press Enter to exit...")
    sys.exit(1)

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QFrame, QScrollArea, QGroupBox, QLineEdit,
    QFormLayout, QComboBox, QSpinBox, QDoubleSpinBox,
QMessageBox, QFileDialog, QCheckBox, QSystemTrayIcon, QMenu,
      QSizePolicy,
  )
from PySide6.QtCore import Qt, QTimer, QSize, Signal
from PySide6.QtGui import QKeyEvent, QShortcut, QKeySequence, QIcon, QPixmap, QPainter, QColor, QPen, QAction

from styles import get_main_stylesheet, COLORS
from backend import OllamaBackend
from widgets import (
    CrackedBackdrop, ScanlineOverlay, LEDDot, HardwareStrip,
    BarMeter, MascotGlyph,
)
from configs import ModelConfig, load_full, write_all
from hardware import detect as detect_hardware
import history


# ─── Resolve working directory (always relative to this script) ───────────────

SCRIPT_DIR = str(Path(__file__).parent.resolve())


# ─── Utility: simple markdown → HTML for assistant messages ───────────────────

def md_to_html(text: str) -> str:
    """
    Lightweight markdown-to-HTML for chat display.
    Handles: code blocks, inline code, bold, italic, bullet lists, newlines.
    """
    html = text

    # Fenced code blocks ```lang\n...\n```
    def _code_block(m):
        lang = m.group(1) or ""
        code = m.group(2).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return (
            f'<div style="background:rgba(0,0,0,0.35); border:1px solid rgba(100,100,180,0.2);'
            f' border-radius:8px; padding:10px 14px; margin:8px 0; font-family:Consolas,monospace;'
            f' font-size:12px; white-space:pre-wrap; color:#c9d1d9;">'
            f'{code}</div>'
        )
    html = re.sub(r'```(\w*)\n(.*?)```', _code_block, html, flags=re.DOTALL)

    # Inline code `...`
    html = re.sub(
        r'`([^`]+)`',
        r'<code style="background:rgba(0,0,0,0.3); padding:2px 6px; border-radius:4px;'
        r' font-family:Consolas,monospace; font-size:12px; color:#c9d1d9;">\1</code>',
        html,
    )

    # Bold **...**
    html = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', html)

    # Italic *...*
    html = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', html)

    # Bullet lists (lines starting with - or *)
    def _bullet_line(m):
        return f'<div style="padding-left:16px;">• {m.group(1)}</div>'
    html = re.sub(r'^[\-\*]\s+(.+)$', _bullet_line, html, flags=re.MULTILINE)

    # Numbered lists
    def _num_line(m):
        return f'<div style="padding-left:16px;">{m.group(1)}. {m.group(2)}</div>'
    html = re.sub(r'^(\d+)\.\s+(.+)$', _num_line, html, flags=re.MULTILINE)

    # Line breaks (but not inside code blocks which already have pre-wrap)
    html = html.replace("\n", "<br>")

    return html


def estimate_tokens(text: str) -> int:
    """Rough token count (~4 chars/token, standard heuristic for English)."""
    if not text or not text.strip():
        return 0
    return max(1, (len(text) + 3) // 4)


# ─── Custom chat input (Enter to send, Shift+Enter for newline) ──────────────

class ChatInput(QTextEdit):
    """Custom text input that sends on Enter, newlines on Shift+Enter."""

    def __init__(self, send_callback, parent=None):
        super().__init__(parent)
        self.send_callback = send_callback
        self.setObjectName("chatInput")
        self.setPlaceholderText("Type a message…")
        self.setAcceptRichText(False)
        self.setFixedHeight(80)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                # Shift+Enter → newline
                super().keyPressEvent(event)
            else:
                # Enter → send
                self.send_callback()
        else:
            super().keyPressEvent(event)


# ─── Message Bubble Widget ───────────────────────────────────────────────────

class MessageBubble(QFrame):
    """A single chat message rendered as a styled bubble."""

    def __init__(self, role: str, content: str, parent=None):
        super().__init__(parent)
        self.role = role
        self._raw_content = content
        self.setObjectName("messageBubble")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Role label
        role_label = QLabel("You" if role == "user" else "Qwythos")
        role_label.setObjectName("mutedLabel")
        role_label.setStyleSheet(
            f"font-size: 11px; font-weight: 600; color: {COLORS['text_muted']}; "
            f"padding: 0px 4px; background: transparent;"
        )

        # Content label
        self.content_label = QLabel()
        self.content_label.setWordWrap(True)
        self.content_label.setTextFormat(Qt.RichText)
        self.content_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        self.content_label.setStyleSheet(
            f"font-size: 14px; line-height: 1.5; padding: 0px; background: transparent;"
            f" color: {COLORS['text_primary']};"
        )

        if role == "user":
            self.content_label.setText(content.replace("\n", "<br>"))
            self.setStyleSheet(
                f"background-color: {COLORS['user_bubble']};"
                f" border: 1px solid {COLORS['user_bubble_border']};"
                f" border-radius: 14px; border-top-right-radius: 4px;"
                f" padding: 12px 16px; margin: 4px 0px 4px 80px;"
            )
            role_label.setAlignment(Qt.AlignRight)
        else:
            self.content_label.setText(md_to_html(content))
            self.setStyleSheet(
                f"background-color: {COLORS['assistant_bubble']};"
                f" border: 1px solid {COLORS['assistant_bubble_border']};"
                f" border-radius: 14px; border-top-left-radius: 4px;"
                f" padding: 12px 16px; margin: 4px 80px 4px 0px;"
            )
            role_label.setAlignment(Qt.AlignLeft)

        layout.addWidget(role_label)
        layout.addWidget(self.content_label)

        # ── Footer: token count + copy button (assistant only) ──
        footer = QHBoxLayout()
        footer.setSpacing(8)

        self.token_label = QLabel()
        self.token_label.setStyleSheet(
            f"font-size: 10px; color: {COLORS['text_muted']}; background: transparent;"
        )
        footer.addWidget(self.token_label)

        if role == "assistant":
            self.copy_btn = QPushButton("📋 Copy")
            self.copy_btn.setFixedHeight(22)
            self.copy_btn.setStyleSheet(
                f"font-size: 10px; padding: 2px 8px; border-radius: 4px;"
                f" background: transparent; border: 1px solid {COLORS['divider']};"
                f" color: {COLORS['text_muted']};"
            )
            self.copy_btn.setCursor(Qt.PointingHandCursor)
            self.copy_btn.clicked.connect(self._copy_content)
            footer.addWidget(self.copy_btn)

        footer.addStretch()
        layout.addLayout(footer)

        # Set initial token count
        self._update_token_count(content)

    def _update_token_count(self, content: str):
        n = estimate_tokens(content)
        self.token_label.setText(f"~{n} token{'s' if n != 1 else ''}")

    def _copy_content(self):
        """Copy the raw message content to the system clipboard."""
        QApplication.clipboard().setText(self._raw_content)
        self.copy_btn.setText("✓ Copied")
        QTimer.singleShot(1500, lambda: self.copy_btn.setText("📋 Copy"))

    def update_content(self, content: str):
        """Update the displayed content (used during streaming)."""
        self._raw_content = content
        if self.role == "user":
            self.content_label.setText(content.replace("\n", "<br>"))
        else:
            self.content_label.setText(md_to_html(content))
        self._update_token_count(content)


# ─── Settings Panel ──────────────────────────────────────────────────────────

class SettingsPanel(QFrame):
    """Sidebar panel with hardware/model configuration controls.

    Width adapts to the window instead of being pinned: a fixed width meant the
    form rows could not fit their labels and fields, so values were clipped and
    the panel was only readable when maximised.
    """

    # Emitted when the user asks to re-create the Ollama model after a rebuild.
    # MainWindow owns that flow (status banner + ModelManager), so the panel asks.
    model_rebuild_requested = Signal()

    # Emitted when the panel's own Launch Claude CLI button is pressed.
    launch_claude_requested = Signal()

    def __init__(self, backend: OllamaBackend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.setObjectName("settingsPanel")
        # Growable within limits so the form always has room for its labels.
        self.setMinimumWidth(360)
        self.setMaximumWidth(520)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # Title
        title = QLabel("⚙  Settings")
        title.setStyleSheet(f"font-size: 17px; font-weight: 700; color: {COLORS['text_primary']};")
        layout.addWidget(title)

        # ── Model & Persona ──
        session_group = QGroupBox("Model & Persona")
        session_layout = QFormLayout(session_group)
        session_layout.setSpacing(8)
        session_layout.setContentsMargins(12, 20, 12, 12)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.addItem(backend.get_model_tag())
        self.model_combo.currentTextChanged.connect(self._on_model_changed)
        session_layout.addRow("Active Model:", self.model_combo)

        # Multi-GGUF selector — repo-local files listed, plus a browser for
        # models that live on another drive (the common case).
        self.gguf_combo = QComboBox()
        self.gguf_combo.setEditable(True)
        self.gguf_combo.setInsertPolicy(QComboBox.NoInsert)
        self.gguf_combo.currentTextChanged.connect(self._on_gguf_changed)

        browse_btn = QPushButton("Browse…")
        browse_btn.setObjectName("secondaryButton")
        browse_btn.setFixedWidth(90)
        browse_btn.clicked.connect(self._browse_for_gguf)

        gguf_row = QWidget()
        gguf_row.setObjectName("settingsPanel")
        gguf_row_layout = QHBoxLayout(gguf_row)
        gguf_row_layout.setContentsMargins(0, 0, 0, 0)
        gguf_row_layout.addWidget(self.gguf_combo, 1)
        gguf_row_layout.addWidget(browse_btn, 0)
        session_layout.addRow("GGUF File:", gguf_row)
        self._refresh_gguf_list()

        self.system_prompt_edit = QTextEdit()
        self.system_prompt_edit.setFixedHeight(70)
        self.system_prompt_edit.setPlaceholderText("Custom system prompt instructions...")
        self.system_prompt_edit.setText(backend.get_system_prompt())
        session_layout.addRow("System Prompt:", self.system_prompt_edit)

        layout.addWidget(session_group)

        # Connect live model list updates from Ollama backend
        self.backend.model_list_updated.connect(self._on_model_list_updated)

        # ── Inference Settings ──
        inf_group = QGroupBox("Inference")
        inf_layout = QFormLayout(inf_group)
        inf_layout.setSpacing(8)
        inf_layout.setContentsMargins(12, 20, 12, 12)

        self.ctx_combo = QComboBox()
        self.ctx_combo.addItems(["8192", "16384", "32768", "65536"])
        self.ctx_combo.setCurrentText(str(backend.num_ctx))
        inf_layout.addRow("Context Size:", self.ctx_combo)

        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 2.0)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setDecimals(2)
        self.temp_spin.setValue(backend.temperature)
        inf_layout.addRow("Temperature:", self.temp_spin)

        self.max_tokens_combo = QComboBox()
        self.max_tokens_combo.addItems(["2048", "4096", "8192", "16384"])
        self.max_tokens_combo.setCurrentText(str(backend.max_tokens))
        inf_layout.addRow("Max Tokens:", self.max_tokens_combo)

        layout.addWidget(inf_group)

        # ── Hardware Settings ──
        hw_group = QGroupBox("Hardware (Modelfile)")
        hw_layout = QFormLayout(hw_group)
        hw_layout.setSpacing(8)
        hw_layout.setContentsMargins(12, 20, 12, 12)

        self.gpu_spin = QSpinBox()
        self.gpu_spin.setRange(0, 99)
        self.gpu_spin.setValue(99)
        self.gpu_spin.setToolTip("99 = full GPU offload. 0 = CPU only.")
        hw_layout.addRow("GPU Layers:", self.gpu_spin)

        cpu_count = os.cpu_count() or 8
        self.cpu_spin = QSpinBox()
        self.cpu_spin.setRange(1, cpu_count)
        self.cpu_spin.setValue(max(1, cpu_count - 2))
        hw_layout.addRow("CPU Threads:", self.cpu_spin)

        self.batch_combo = QComboBox()
        self.batch_combo.addItems(["256", "512", "1024"])
        self.batch_combo.setCurrentText("512")
        hw_layout.addRow("Batch Size:", self.batch_combo)

        self.top_p_spin = QDoubleSpinBox()
        self.top_p_spin.setRange(0.0, 1.0)
        self.top_p_spin.setSingleStep(0.05)
        self.top_p_spin.setDecimals(2)
        self.top_p_spin.setSpecialValueText("model default")
        self.top_p_spin.setValue(0.0)
        self.top_p_spin.setToolTip("Nucleus sampling cutoff. 0 = use the model's own default.")
        hw_layout.addRow("Top P:", self.top_p_spin)

        self.top_k_spin = QSpinBox()
        self.top_k_spin.setRange(0, 200)
        self.top_k_spin.setSpecialValueText("model default")
        self.top_k_spin.setValue(0)
        self.top_k_spin.setToolTip("Top-K sampling limit. 0 = use the model's own default.")
        hw_layout.addRow("Top K:", self.top_k_spin)

        self.repeat_penalty_spin = QDoubleSpinBox()
        self.repeat_penalty_spin.setRange(0.5, 3.0)
        self.repeat_penalty_spin.setSingleStep(0.05)
        self.repeat_penalty_spin.setDecimals(2)
        self.repeat_penalty_spin.setValue(1.0)
        self.repeat_penalty_spin.setToolTip("Penalty for repeating tokens. 1.0 = use the model's own default.")
        hw_layout.addRow("Repeat Penalty:", self.repeat_penalty_spin)

        # Persona baked into the model at create time. Separate from the chat
        # System Prompt field above, which only affects the running session.
        self.model_persona_edit = QTextEdit()
        self.model_persona_edit.setFixedHeight(64)
        self.model_persona_edit.setPlaceholderText(
            "Leave empty to keep the model's own default persona."
        )
        self.model_persona_edit.setToolTip(
            "Baked into the Ollama model as SYSTEM when you rebuild.\n"
            "Leave empty to let the model keep whatever persona it shipped with."
        )
        hw_layout.addRow("Model Persona:", self.model_persona_edit)

        layout.addWidget(hw_group)

        # ── Connection Settings ──
        conn_group = QGroupBox("Connection")
        conn_layout = QFormLayout(conn_group)
        conn_layout.setSpacing(8)
        conn_layout.setContentsMargins(12, 20, 12, 12)

        self.engine_combo = QComboBox()
        self.engine_combo.addItems(["litellm_chat", "litellm_standard", "direct"])
        self.engine_combo.setToolTip(
            "litellm_chat: recommended — LiteLLM proxy, chat endpoint\n"
            "litellm_standard: LiteLLM proxy, standard endpoint\n"
            "direct: talk to Ollama directly on port 11434"
        )
        conn_layout.addRow("Engine Mode:", self.engine_combo)

        self.litellm_url_edit = QLineEdit()
        self.litellm_url_edit.setPlaceholderText("http://127.0.0.1:4000")
        conn_layout.addRow("LiteLLM URL:", self.litellm_url_edit)

        self.litellm_key_edit = QLineEdit()
        self.litellm_key_edit.setPlaceholderText("API key")
        conn_layout.addRow("LiteLLM Key:", self.litellm_key_edit)

        self.ollama_url_edit = QLineEdit()
        self.ollama_url_edit.setPlaceholderText("http://127.0.0.1:11434")
        conn_layout.addRow("Ollama URL:", self.ollama_url_edit)

        self.auto_litellm_check = QCheckBox("Auto-start LiteLLM on launch")
        self.auto_litellm_check.setToolTip("Automatically start the LiteLLM proxy when the app opens")
        conn_layout.addRow("", self.auto_litellm_check)

        layout.addWidget(conn_group)

        # ── Claude CLI ──
        claude_group = QGroupBox("Claude CLI")
        claude_layout = QFormLayout(claude_group)
        claude_layout.setSpacing(8)
        claude_layout.setContentsMargins(12, 20, 12, 12)

        self.claude_model_edit = QLineEdit()
        self.claude_model_edit.setPlaceholderText("qwythos-heretic")
        self.claude_model_edit.setToolTip(
            "Model name Claude Code requests via ANTHROPIC_MODEL.\n"
            "Claude Code rejects unknown names in --model, so this is set by\n"
            "environment variable instead. LiteLLM's \"*\" wildcard routes any name."
        )
        claude_layout.addRow("Claude Model:", self.claude_model_edit)

        self.thinking_check = QCheckBox("Enable model thinking")
        self.thinking_check.setToolTip(
            "Off (recommended): the model answers directly.\n"
            "On: the model emits a reasoning block first and can spend the whole\n"
            "output budget on it, leaving no text in the response."
        )
        claude_layout.addRow("", self.thinking_check)

        self.silent_launch_check = QCheckBox("Launch services silently")
        self.silent_launch_check.setToolTip(
            "Hide the LiteLLM console window when starting the proxy.\n"
            "Turn off if you want to watch its log while troubleshooting."
        )
        claude_layout.addRow("", self.silent_launch_check)

        claude_btn = QPushButton("⚡  Launch Claude CLI")
        claude_btn.setObjectName("secondaryButton")
        claude_btn.clicked.connect(self.launch_claude_requested.emit)
        claude_layout.addRow("", claude_btn)

        layout.addWidget(claude_group)

        # ── Actions ──
        auto_btn = QPushButton("🔍  Auto-detect Hardware")
        auto_btn.setToolTip("Probe CPU/RAM/GPU and fill in recommended settings")
        auto_btn.clicked.connect(self._auto_detect)
        layout.addWidget(auto_btn)

        apply_btn = QPushButton("Apply Settings")
        apply_btn.setObjectName("secondaryButton")
        apply_btn.setToolTip("Apply inference settings to the current session")
        apply_btn.clicked.connect(self._apply_settings)
        layout.addWidget(apply_btn)

        save_btn = QPushButton("💾  Save & Rebuild Configs")
        save_btn.setToolTip(
            "Regenerate Modelfile and config.yaml with current settings.\n"
            "You'll need to re-create the Ollama model for hardware changes to take effect."
        )
        save_btn.clicked.connect(self._save_and_rebuild)
        layout.addWidget(save_btn)

        # Unsaved-changes marker. Every control that feeds a ModelConfig reports
        # edits here so it is obvious when on-disk configs are stale.
        self.dirty_label = QLabel("")
        self.dirty_label.setObjectName("dangerButton")
        self.dirty_label.setAlignment(Qt.AlignCenter)
        self.dirty_label.setVisible(False)
        layout.addWidget(self.dirty_label)

        self._form_widgets = []
        self._baseline = {}
        # Tags Ollama currently has, so the coherence check can tell a
        # deliberate rename from drift onto a model that does not exist.
        self._registered_tags: set = set()

        layout.addStretch()

        # ── Model Info ──
        self.info_label = QLabel(f"Model: {backend.get_model_tag()}")
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet(f"font-size: 11px; color: {COLORS['text_muted']};")
        layout.addWidget(self.info_label)

        # Load saved settings from disk
        self._load_from_configs()

        # Start watching for edits only once the widgets hold their loaded
        # values, otherwise every field reads as a pending change on startup.
        self._watch_for_changes()
        self._reset_dirty()

    def _refresh_gguf_list(self):
        """Populate the GGUF selector with Models/ files, then re-select whatever
        the config already points at (which may be an absolute path elsewhere)."""
        working_dir = Path(self.backend.working_dir)
        models_dir = working_dir / "Models"
        ggufs = sorted(f.name for f in models_dir.glob("*.gguf")) if models_dir.exists() else []
        current_cfg = load_full(working_dir)

        self.gguf_combo.blockSignals(True)
        self.gguf_combo.clear()
        self.gguf_combo.addItems(ggufs)
        current = current_cfg.selected_gguf
        if current:
            # Keep the configured selection visible even when the file is not in
            # Models/ - otherwise it looks like nothing is selected.
            if current not in ggufs:
                self.gguf_combo.addItem(current)
            self.gguf_combo.setCurrentText(current)
        elif not ggufs:
            self.gguf_combo.addItem("(no .gguf found - click Browse.)")
            self.gguf_combo.setCurrentIndex(0)
        self.gguf_combo.blockSignals(False)

    def _browse_for_gguf(self):
        """Pick a GGUF from anywhere on disk (models often live on another drive)."""
        working_dir = Path(self.backend.working_dir)
        start_dir = working_dir
        current = load_full(working_dir).selected_gguf
        if current:
            candidate = Path(current)
            if candidate.is_absolute() and candidate.parent.is_dir():
                start_dir = candidate.parent

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select GGUF model file",
            str(start_dir),
            "GGUF models (*.gguf);;All files (*)",
        )
        if not path:
            return

        self.gguf_combo.blockSignals(True)
        self.gguf_combo.addItem(path)
        self.gguf_combo.setCurrentText(path)
        self.gguf_combo.blockSignals(False)
        self._on_gguf_changed(path)

    def _on_gguf_changed(self, filename: str):
        """Switch to a different GGUF: derive tag, rebuild configs, hot-swap backend."""
        if not filename or filename.startswith("("):
            return
        working_dir = Path(self.backend.working_dir)

        from configs import derive_model_tag
        new_tag = derive_model_tag(filename)

        cfg = load_full(working_dir)
        cfg = cfg.with_updates(selected_gguf=filename, model_tag=new_tag)
        try:
            write_all(cfg, working_dir, self._registered_tags)
        except ValueError as e:
            QMessageBox.warning(self, "Switch Failed", str(e))
            return

        self.backend.set_model_tag(new_tag)
        self.model_combo.setCurrentText(new_tag)
        self.info_label.setText(f"Model: {new_tag}")

    def _on_model_list_updated(self, models: list):
        """Update model switcher dropdown when Ollama reports installed models."""
        self._registered_tags = set(models)
        if not models:
            return
        current = self.model_combo.currentText().strip()
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for m in models:
            self.model_combo.addItem(m)
        if current and self.model_combo.findText(current) < 0:
            self.model_combo.addItem(current)
        self.model_combo.setCurrentText(current or self.backend.get_model_tag())
        self.model_combo.blockSignals(False)

    def _on_model_changed(self, tag: str):
        """Handle model tag selection change."""
        tag = tag.strip()
        if tag:
            self.backend.set_model_tag(tag)
            self.info_label.setText(f"Model: {tag}")

    def _load_from_configs(self):
        """Read current settings from Modelfile + config.yaml via configs module."""
        try:
            cfg = load_full(Path(self.backend.working_dir))

            val = str(cfg.context_size)
            idx = self.ctx_combo.findText(val)
            if idx >= 0:
                self.ctx_combo.setCurrentIndex(idx)

            self.gpu_spin.setValue(cfg.gpu_layers)
            self.cpu_spin.setValue(cfg.cpu_threads)

            val = str(cfg.batch_size)
            idx = self.batch_combo.findText(val)
            if idx >= 0:
                self.batch_combo.setCurrentIndex(idx)

            # Seed from disk like every other field, otherwise Apply/Save would
            # overwrite config.yaml's max_tokens with this combo's stale default.
            val = str(cfg.max_tokens)
            idx = self.max_tokens_combo.findText(val)
            if idx >= 0:
                self.max_tokens_combo.setCurrentIndex(idx)

            self.temp_spin.setValue(cfg.temperature)

            # Sampling params are Optional on the model: 0 means "not set".
            self.top_p_spin.setValue(cfg.top_p or 0.0)
            self.top_k_spin.setValue(cfg.top_k or 0)
            self.repeat_penalty_spin.setValue(cfg.repeat_penalty or 1.0)
            self.model_persona_edit.setPlainText(cfg.system_prompt)

            idx = self.engine_combo.findText(cfg.engine_mode)
            if idx >= 0:
                self.engine_combo.setCurrentIndex(idx)

            if cfg.model_tag:
                self.model_combo.setCurrentText(cfg.model_tag)
                self.info_label.setText(f"Model: {cfg.model_tag}")

            # Thinking is owned by config.yaml (extra_body.think).
            self.thinking_check.setChecked(bool(cfg.thinking))

            self.system_prompt_edit.setText(self.backend.get_system_prompt())

            # Connection endpoints live in settings.json, not Modelfile/config.yaml
            conn = self.backend.get_urls()
            self.litellm_url_edit.setText(conn["litellm_base_url"])
            self.litellm_key_edit.setText(conn["litellm_api_key"])
            self.ollama_url_edit.setText(conn["ollama_base_url"])

            import settings as app_settings
            loaded = app_settings.load()
            self.auto_litellm_check.setChecked(
                app_settings.is_true(loaded.get("auto_start_litellm"))
            )
            self.silent_launch_check.setChecked(
                app_settings.is_true(loaded.get("launch_silent"))
            )
            # Default the Claude model field to the configured tag so the common
            # case needs no typing.
            if not self.claude_model_edit.text():
                self.claude_model_edit.setText(self.backend.get_model_tag())
        except Exception as e:
            print(f"[SettingsPanel] Failed to load configs: {e}")

    def _auto_detect(self):
        """Probe hardware and fill in recommended settings."""
        try:
            hw = detect_hardware()
            r = hw.recommendations

            val = str(r.context_size)
            idx = self.ctx_combo.findText(val)
            if idx >= 0:
                self.ctx_combo.setCurrentIndex(idx)

            self.gpu_spin.setValue(r.gpu_layers)
            self.cpu_spin.setValue(r.cpu_threads)

            val = str(r.batch_size)
            idx = self.batch_combo.findText(val)
            if idx >= 0:
                self.batch_combo.setCurrentIndex(idx)

            idx = self.engine_combo.findText(r.engine_mode)
            if idx >= 0:
                self.engine_combo.setCurrentIndex(idx)

            gpu_info = f" — {hw.gpu.name} ({hw.gpu.total_vram_gb:.1f} GB VRAM)" if hw.gpu else ""
            QMessageBox.information(
                self,
                "Hardware Detected",
                f"CPU: {hw.cpu_cores} cores\n"
                f"RAM: {hw.ram_gb:.1f} GB\n"
                f"GPU{gpu_info}\n\n"
                f"Recommended settings applied!"
            )
        except Exception as e:
            QMessageBox.warning(self, "Detection Failed", str(e))

    def _apply_settings(self):
        """Push current UI values into the backend for the running session."""
        self.backend.update_settings(
            temperature=self.temp_spin.value(),
            num_ctx=int(self.ctx_combo.currentText()),
            max_tokens=int(self.max_tokens_combo.currentText()),
            engine_mode=self.engine_combo.currentText(),
        )
        tag = self.model_combo.currentText().strip()
        if tag:
            self.backend.set_model_tag(tag)
        self.backend.set_system_prompt(self.system_prompt_edit.toPlainText().strip())
        self.info_label.setText(f"Model: {self.backend.get_model_tag()}")

        # Endpoints hot-swap immediately — no restart required
        self.backend.update_urls(
            ollama_base_url=self.ollama_url_edit.text(),
            litellm_base_url=self.litellm_url_edit.text(),
            litellm_api_key=self.litellm_key_edit.text(),
        )

        # Persist auto-start + silent-launch preferences
        import settings as app_settings
        app_settings.save({
            "auto_start_litellm": app_settings.to_flag(self.auto_litellm_check.isChecked()),
            "launch_silent": app_settings.to_flag(self.silent_launch_check.isChecked()),
        })

    def _watch_for_changes(self):
        """Mark the panel dirty when any control that feeds a ModelConfig changes."""
        # findChildren takes a single type per call, so gather from each.
        seen = []
        for cls in (QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit):
            for w in self.findChildren(cls):
                if w not in seen:
                    seen.append(w)

        for w in seen:
            if w is self.gguf_combo:
                continue  # its own handler already rebuilds configs on change
            self._form_widgets.append(w)
            for sig in ("currentTextChanged", "valueChanged", "textChanged", "toggled"):
                if hasattr(w, sig):
                    getattr(w, sig).connect(self._mark_dirty)
                    break
        # The GGUF combo triggers a rebuild on change, but still counts as a
        # pending edit the user should see flagged.
        self.gguf_combo.currentTextChanged.connect(self._mark_dirty)

    def _form_values(self) -> dict:
        """Snapshot of every tracked control's current value."""
        vals = {}
        for w in self._form_widgets:
            name = f"{type(w).__name__}@{w.objectName() or id(w)}"
            if isinstance(w, (QComboBox,)):
                vals[name] = ("combo", w.currentText())
            elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
                vals[name] = ("num", w.value())
            elif isinstance(w, QLineEdit):
                vals[name] = ("text", w.text())
        vals["gguf"] = ("combo", self.gguf_combo.currentText())
        return vals

    def _mark_dirty(self, *_args):
        self._refresh_dirty()

    def _reset_dirty(self):
        self._baseline = self._form_values()
        self._refresh_dirty()

    def _refresh_dirty(self):
        try:
            current = self._form_values()
        except RuntimeError:
            return  # widget torn down
        changed = current != self._baseline
        self.dirty_label.setText("[!]  Unsaved changes" if changed else "")
        self.dirty_label.setVisible(changed)

    def _save_and_rebuild(self):
        """Regenerate Modelfile and config.yaml using the configs module."""
        working_dir = Path(self.backend.working_dir)

        model_tag = self.model_combo.currentText().strip() or self.backend.get_model_tag()

        # The selected GGUF may be repo-local or an absolute path chosen via
        # Browse (models usually live on another drive), so validate it rather
        # than requiring a .gguf in the project directory.
        chosen_gguf = self.gguf_combo.currentText().strip()
        if not chosen_gguf or chosen_gguf.startswith("("):
            chosen_gguf = load_full(working_dir).selected_gguf or ""

        if not chosen_gguf:
            QMessageBox.warning(
                self, "No model selected",
                "No GGUF model is selected.\n\n"
                "Click Browse… to choose a .gguf file, which may live outside "
                "this project folder."
            )
            return

        gguf_path = Path(chosen_gguf)
        if not gguf_path.is_absolute():
            gguf_path = working_dir / gguf_path
        if not gguf_path.exists():
            QMessageBox.warning(
                self, "Model file not found",
                f"Cannot find the selected model file:\n\n{gguf_path}\n\n"
                "It may have been moved or renamed. Click Browse… to reselect it."
            )
            return

        cfg = ModelConfig(
            selected_gguf=chosen_gguf,
            model_tag=model_tag,
            engine_mode=self.engine_combo.currentText(),
            context_size=int(self.ctx_combo.currentText()),
            gpu_layers=self.gpu_spin.value(),
            cpu_threads=self.cpu_spin.value(),
            batch_size=int(self.batch_combo.currentText()),
            temperature=self.temp_spin.value(),
            max_tokens=int(self.max_tokens_combo.currentText()),
            thinking=self.thinking_check.isChecked(),
            top_p=(self.top_p_spin.value() or None),
            top_k=(self.top_k_spin.value() or None),
            repeat_penalty=(
                self.repeat_penalty_spin.value() if self.repeat_penalty_spin.value() != 1.0 else None
            ),
            system_prompt=self.model_persona_edit.toPlainText().strip(),
            litellm_url=self.litellm_url_edit.text() or "http://127.0.0.1:4000",
            litellm_api_key=self.litellm_key_edit.text() or "",
            ollama_base_url=self.ollama_url_edit.text() or "http://127.0.0.1:11434",
        )

        try:
            write_all(cfg, working_dir, self._registered_tags)
        except ValueError as e:
            QMessageBox.critical(self, "Save Failed", str(e))
            return

        # Point the session at the tag we just wrote before creating it, so the
        # rebuild targets the selected model rather than whatever the dropdown
        # happened to be showing.
        self.backend.set_model_tag(cfg.model_tag)
        self.model_combo.setCurrentText(cfg.model_tag)
        self.info_label.setText(f"Model: {cfg.model_tag}")

        # Apply inference settings to the running session too
        self._apply_settings()
        self._reset_dirty()

        # Previously this only rewrote the two files and left the old model
        # serving. Actually re-create it so hardware changes take effect.
        rebuild = QMessageBox.question(
            self,
            "Rebuild model now?",
            f"Configs written for model '{cfg.model_tag}'.\n\n"
            "Re-create it in Ollama now?\n\n"
            "(Hardware settings such as GPU layers and context are baked into\n"
            "the model at create time, so this is needed for them to apply.)",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if rebuild == QMessageBox.Yes:
            self.model_rebuild_requested.emit()


# ─── Main Window ─────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    """The main Qwythos AI chat window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Qwythos AI")
        self.setMinimumSize(960, 680)
        self.resize(1140, 780)

        # Backend
        self.backend = OllamaBackend(working_dir=SCRIPT_DIR)

        # Pip-Boy visual layers (sit behind all content)
        self._backdrop = CrackedBackdrop(self, seed=42, density=18)
        self._backdrop.resize(self.size())
        self._scanlines = ScanlineOverlay(self, spacing=3, alpha=20)
        self._scanlines.resize(self.size())

        # Streaming state
        self._streaming_bubble: MessageBubble | None = None
        self._streaming_text = ""

        # Auto-scroll: follow output only while the user is at the bottom
        self._auto_scroll = True

        # ── Central Widget ──
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Chat Area (left/center) ──
        chat_container = QWidget()
        chat_layout = QVBoxLayout(chat_container)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(0)

        # Header bar
        header = self._build_header()
        chat_layout.addWidget(header)

        # Status banner (shown when services are offline)
        self.status_banner = QFrame()
        self.status_banner.setObjectName("statusBanner")
        self.status_banner.setStyleSheet(
            f"background-color: rgba(245, 158, 11, 0.12);"
            f" border-bottom: 1px solid rgba(245, 158, 11, 0.25);"
            f" padding: 8px 16px;"
        )
        banner_layout = QHBoxLayout(self.status_banner)
        banner_layout.setContentsMargins(16, 8, 16, 8)

        self.banner_label = QLabel("")
        self.banner_label.setStyleSheet(f"color: {COLORS['warning']}; font-size: 13px;")
        banner_layout.addWidget(self.banner_label, 1)

        self.banner_action_btn = QPushButton("Fix")
        self.banner_action_btn.setObjectName("secondaryButton")
        self.banner_action_btn.setFixedWidth(130)
        self.banner_action_btn.setVisible(False)
        banner_layout.addWidget(self.banner_action_btn)

        self.status_banner.setVisible(False)
        chat_layout.addWidget(self.status_banner)

        # Message scroll area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.messages_container = QWidget()
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.setContentsMargins(24, 16, 24, 16)
        self.messages_layout.setSpacing(12)
        self.messages_layout.setAlignment(Qt.AlignTop)

        # Welcome message
        self._add_welcome_message()

        self.scroll_area.setWidget(self.messages_container)
        chat_layout.addWidget(self.scroll_area, 1)

        # Track user scroll position for auto-scroll behavior
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)

        # Input area
        input_area = self._build_input_area()
        chat_layout.addWidget(input_area)

        # Status bar
        status_bar = self._build_status_bar()
        chat_layout.addWidget(status_bar)

        main_layout.addWidget(chat_container, 1)

        # ── Settings Panel (right sidebar) ──
        # Wrapped in a scroll area: the panel has grown past the window height
        # and without this the lower groups overflow and their labels collide.
        self.settings_panel = SettingsPanel(self.backend)
        self.settings_panel.model_rebuild_requested.connect(self._install_model)
        self.settings_panel.launch_claude_requested.connect(self._launch_claude_cli)

        self.settings_scroll = QScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.settings_scroll.setFrameShape(QFrame.NoFrame)
        self.settings_scroll.setWidget(self.settings_panel)
        self.settings_scroll.setVisible(False)  # hidden by default
        main_layout.addWidget(self.settings_scroll)

        # Push backdrop to the very back, scanlines float above it but below content
        self._backdrop.lower()
        self._scanlines.raise_()

        # ── Connect backend signals ──
        self.backend.ollama_status_changed.connect(self._on_ollama_status)
        self.backend.litellm_status_changed.connect(self._on_litellm_status)
        self.backend.model_status_changed.connect(self._on_model_status)

        # Track statuses
        self._ollama_live = False
        self._litellm_live = False
        self._model_ready = False
        self._banner_connected = False

        # Apply stylesheet
        self.setStyleSheet(get_main_stylesheet())

        # ── Keyboard shortcuts ──
        QShortcut(QKeySequence("Ctrl+L"), self, self._clear_chat)
        QShortcut(QKeySequence("Ctrl+N"), self, self._clear_chat)
        QShortcut(QKeySequence("Ctrl+S"), self, self._save_conversation)

        # ── Auto-start LiteLLM on launch (if enabled) ──
        QTimer.singleShot(1500, self._maybe_autostart_litellm)

        # ── System tray ──
        self._setup_tray()

    def _make_tray_icon(self) -> QIcon:
        """Generate a simple amber-on-green Pip-Boy tray icon at runtime."""
        pm = QPixmap(64, 64)
        pm.fill(QColor("#16241c"))
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        # outer ring
        p.setPen(QPen(QColor("#c9a961"), 4))
        p.drawEllipse(6, 6, 52, 52)
        # inner dot
        p.setBrush(QColor("#ffd98a"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(22, 22, 20, 20)
        p.end()
        return QIcon(pm)

    def _setup_tray(self):
        """Create the system tray icon with Show/Hide and Quit actions."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = None
            return

        self._tray = QSystemTrayIcon(self._make_tray_icon(), self)
        self._tray.setToolTip("Qwythos AI")

        menu = QMenu()
        show_action = QAction("Show / Hide", self)
        show_action.triggered.connect(self._toggle_visibility)
        menu.addAction(show_action)
        menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._quit_app)
        menu.addAction(quit_action)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self._toggle_visibility()

    def _toggle_visibility(self):
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def _quit_app(self):
        """Terminate managed child processes, then exit (spec Step 5)."""
        try:
            self.backend.shutdown()
        except Exception:
            pass
        QApplication.quit()

    def closeEvent(self, event):
        """Minimize to tray instead of closing (unless tray is unavailable)."""
        if self._tray and self._tray.isVisible():
            event.ignore()
            self.hide()
            self._tray.showMessage(
                "Qwythos AI", "Still running in the system tray.",
                QSystemTrayIcon.Information, 2000,
            )
        else:
            try:
                self.backend.shutdown()
            except Exception:
                pass
            event.accept()

    def resizeEvent(self, event):
        """Keep backdrop and scanlines full-window on resize."""
        super().resizeEvent(event)
        self._backdrop.resize(self.size())
        self._scanlines.resize(self.size())

    # ── Build UI Components ───────────────────────────────────────────────────

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("glassPanel")
        header.setStyleSheet(
            f"background-color: {COLORS['glass']};"
            f" border: none;"
            f" border-bottom: 1px solid {COLORS['divider']};"
            f" border-radius: 0px;"
        )
        header.setFixedHeight(60)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 0, 16, 0)

        # Logo / Title
        title = QLabel("✦  Qwythos AI")
        title.setStyleSheet(
            f"font-size: 20px; font-weight: 700; color: {COLORS['text_primary']};"
            f" background: transparent;"
        )
        layout.addWidget(title)

        subtitle = QLabel("Local AI  •  Powered by Ollama + LiteLLM")
        subtitle.setObjectName("subtitleLabel")
        subtitle.setStyleSheet(
            f"font-size: 12px; color: {COLORS['text_muted']}; background: transparent;"
            f" padding-left: 12px;"
        )
        layout.addWidget(subtitle)

        layout.addStretch()

        # Load session button
        load_btn = QPushButton("📂  Load")
        load_btn.setObjectName("secondaryButton")
        load_btn.setFixedHeight(32)
        load_btn.setToolTip("Load a previously saved conversation")
        load_btn.clicked.connect(self._load_session)
        layout.addWidget(load_btn)

        # Save session button
        save_btn = QPushButton("💾  Save")
        save_btn.setObjectName("secondaryButton")
        save_btn.setFixedHeight(32)
        save_btn.setToolTip("Save the current conversation (Ctrl+S exports to file)")
        save_btn.clicked.connect(self._save_session)
        layout.addWidget(save_btn)

        # Clear chat button
        clear_btn = QPushButton("🗑  Clear")
        clear_btn.setObjectName("secondaryButton")
        clear_btn.setFixedHeight(32)
        clear_btn.clicked.connect(self._clear_chat)
        layout.addWidget(clear_btn)

        # Claude CLI launcher
        claude_btn = QPushButton("⚡  Claude CLI")
        claude_btn.setObjectName("secondaryButton")
        claude_btn.setFixedHeight(32)
        claude_btn.setToolTip("Launch the Claude CLI in a new terminal, routed through LiteLLM → Ollama")
        claude_btn.clicked.connect(self._launch_claude_cli)
        layout.addWidget(claude_btn)

        # Settings toggle
        self.settings_btn = QPushButton("⚙  Settings")
        self.settings_btn.setObjectName("secondaryButton")
        self.settings_btn.setFixedHeight(32)
        self.settings_btn.clicked.connect(self._toggle_settings)
        layout.addWidget(self.settings_btn)

        return header

    def _build_input_area(self) -> QFrame:
        container = QFrame()
        container.setStyleSheet(
            f"background-color: {COLORS['glass']};"
            f" border-top: 1px solid {COLORS['divider']};"
            f" border-radius: 0px;"
        )

        layout = QHBoxLayout(container)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(12)

        # Chat input
        self.chat_input = ChatInput(self._send_message)
        layout.addWidget(self.chat_input, 1)

        # Button stack (Send / Stop)
        btn_container = QWidget()
        btn_layout = QVBoxLayout(btn_container)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(6)

        self.send_btn = QPushButton("Send  ➤")
        self.send_btn.setObjectName("sendButton")
        self.send_btn.setFixedSize(100, 36)
        self.send_btn.clicked.connect(self._send_message)
        btn_layout.addWidget(self.send_btn)

        self.stop_btn = QPushButton("■  Stop")
        self.stop_btn.setObjectName("stopButton")
        self.stop_btn.setFixedSize(100, 36)
        self.stop_btn.clicked.connect(self._stop_generation)
        self.stop_btn.setEnabled(False)  # always visible, disabled when idle
        btn_layout.addWidget(self.stop_btn)

        layout.addWidget(btn_container)

        return container

    def _build_status_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("statusBar")
        bar.setFixedHeight(36)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(10)

        def _status_pair(label_text: str) -> tuple:
            """Return (LED, caption_label) side-by-side."""
            led = LEDDot("off", diameter=9)
            cap = QLabel(label_text)
            cap.setStyleSheet(
                f"font-size: 10px; color: {COLORS['text_muted']};"
                f" background: transparent; letter-spacing: 1px;"
            )
            return led, cap

        # Ollama
        self.ollama_led, ol_cap = _status_pair("OLLAMA")
        layout.addWidget(self.ollama_led)
        layout.addWidget(ol_cap)

        # LiteLLM
        self.litellm_led, ll_cap = _status_pair("LITELLM")
        layout.addWidget(self.litellm_led)
        layout.addWidget(ll_cap)

        # Model
        self.model_led, ml_cap = _status_pair("MODEL")
        layout.addWidget(self.model_led)
        layout.addWidget(ml_cap)

        layout.addStretch()

        # Token-rate bar meter
        self.bar_meter = BarMeter(segments=14)
        layout.addWidget(self.bar_meter)

        # Hardware strip (decorative instrument cluster)
        self.hw_strip = HardwareStrip()
        layout.addWidget(self.hw_strip)

        return bar

    # ── Welcome / Empty State ─────────────────────────────────────────────────

    def _add_welcome_message(self):
        welcome = QFrame()
        welcome.setObjectName("welcomeCard")
        welcome.setStyleSheet(
            f"background-color: {COLORS['glass']};"
            f" border: 1px solid {COLORS['glass_border']};"
            f" border-radius: 16px;"
            f" padding: 32px;"
        )

        wlayout = QVBoxLayout(welcome)
        wlayout.setAlignment(Qt.AlignCenter)
        wlayout.setSpacing(12)

        # Mascot glyph (original line-art from widgets.py)
        mascot = MascotGlyph(size=96)
        wlayout.addWidget(mascot, alignment=Qt.AlignHCenter)

        title = QLabel("Welcome to Qwythos AI")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            f"font-size: 22px; font-weight: 700; color: {COLORS['text_primary']};"
            f" background: transparent;"
        )
        wlayout.addWidget(title)

        desc = QLabel(
            "Your local AI assistant running entirely on this computer.\n"
            "No internet required  •  Complete privacy  •  Unlimited usage"
        )
        desc.setAlignment(Qt.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-size: 14px; color: {COLORS['text_secondary']}; background: transparent;"
        )
        wlayout.addWidget(desc)

        hint = QLabel("Type a message below to get started →")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(
            f"font-size: 12px; color: {COLORS['text_muted']}; background: transparent;"
            f" padding-top: 8px; letter-spacing: 1px;"
        )
        wlayout.addWidget(hint)

        self.welcome_widget = welcome
        self.messages_layout.addWidget(welcome)

    def _remove_welcome(self):
        """Remove the welcome card once the first message is sent."""
        if hasattr(self, 'welcome_widget') and self.welcome_widget:
            self.welcome_widget.setParent(None)
            self.welcome_widget.deleteLater()
            self.welcome_widget = None

    # ── Status Signal Handlers ────────────────────────────────────────────────

    def _on_ollama_status(self, status: str):
        self._ollama_live = (status == "live")
        self.ollama_led.set_state("green" if status == "live" else "red")
        self._sync_hw_strip()
        self._update_banner()

    def _on_litellm_status(self, status: str):
        self._litellm_live = (status == "live")
        self.litellm_led.set_state("green" if status == "live" else "amber")
        self._sync_hw_strip()
        self._update_banner()

    def _on_model_status(self, status: str):
        self._model_ready = (status == "ready")
        if status == "ready":
            self.model_led.set_state("green")
        elif status == "not_found":
            self.model_led.set_state("red")
        else:
            self.model_led.set_state("amber")
        self._sync_hw_strip()
        self._update_banner()

    def _sync_hw_strip(self):
        """Drive the decorative PWR / I/O / GPU LEDs on the hardware strip."""
        is_direct = self.backend.get_engine_mode() == "direct"
        pwr = "green" if self._ollama_live else "red"
        io  = "green" if (self._litellm_live or (is_direct and self._ollama_live)) else "off"
        gpu = "green" if self._model_ready else ("amber" if self._ollama_live else "off")
        self.hw_strip.set_lamps(pwr, io, gpu)
        if self._model_ready:
            self.hw_strip.set_plate("RDY")
        elif self._ollama_live:
            self.hw_strip.set_plate("INIT")
        else:
            self.hw_strip.set_plate("OFF")

    def _update_banner(self):
        """Show/hide the status banner based on service states."""
        # Disconnect any previous banner button connections cleanly
        if self._banner_connected:
            try:
                self.banner_action_btn.clicked.disconnect()
            except (RuntimeError, TypeError):
                pass
            self._banner_connected = False

        is_direct = self.backend.get_engine_mode() == "direct"

        if not self._ollama_live:
            self.banner_label.setText(
                "⚠  Ollama is not running. Start Ollama to use the model."
            )
            self.banner_action_btn.setVisible(False)
            self.status_banner.setVisible(True)
            self.send_btn.setEnabled(False)
        elif not self._model_ready:
            self.banner_label.setText(
                f"⚠  Model '{self.backend.get_model_tag()}' not found in Ollama."
            )
            self.banner_action_btn.setText("Install Model")
            self.banner_action_btn.setVisible(True)
            self.banner_action_btn.clicked.connect(self._install_model)
            self._banner_connected = True
            self.status_banner.setVisible(True)
            self.send_btn.setEnabled(False)
        elif not is_direct and not self._litellm_live:
            self.banner_label.setText(
                "⚠  LiteLLM proxy is offline. The model needs LiteLLM to route requests."
            )
            self.banner_action_btn.setText("Start LiteLLM")
            self.banner_action_btn.setVisible(True)
            self.banner_action_btn.clicked.connect(self._start_litellm)
            self._banner_connected = True
            self.status_banner.setVisible(True)
            self.send_btn.setEnabled(False)
        else:
            self.status_banner.setVisible(False)
            self.send_btn.setEnabled(True)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _maybe_autostart_litellm(self):
        """Start LiteLLM automatically on launch if the user enabled it."""
        import settings as app_settings
        if app_settings.load().get("auto_start_litellm", "false") != "true":
            return
        if self._litellm_live:
            return
        if self.backend.get_engine_mode() == "direct":
            return  # direct mode doesn't need LiteLLM

        self._start_litellm()

    def _launch_claude_cli(self):
        """Spawn the Claude CLI in a new console, spoofed to route through LiteLLM → Ollama."""
        import shutil as _shutil
        if not _shutil.which("claude"):
            QMessageBox.warning(
                self, "Claude CLI Not Found",
                "The 'claude' command is not in your PATH.\n\n"
                "Install Claude Code with:\n"
                "    npm install -g @anthropic-ai/claude-code"
            )
            return

        if self.backend.get_engine_mode() != "direct" and not self._litellm_live:
            QMessageBox.warning(
                self, "LiteLLM Offline",
                "Claude CLI needs LiteLLM to route requests.\n"
                "Start LiteLLM first (click 'Fix' in the status banner)."
            )
            return

        import subprocess as _subprocess
        # Prefer the panel's Claude Model field so it can be overridden without
        # editing the config; fall back to the active model tag.
        claude_model = ""
        panel = getattr(self, "settings_panel", None)
        if panel is not None:
            claude_model = panel.claude_model_edit.text().strip()
        if not claude_model:
            claude_model = self.backend.get_model_tag()

        env = os.environ.copy()
        env["ANTHROPIC_BASE_URL"] = self.backend.litellm_base_url
        env["ANTHROPIC_AUTH_TOKEN"] = "sk-litellm-local"
        env["ANTHROPIC_API_KEY"] = ""
        env["CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS"] = "1"
        env["ANTHROPIC_MODEL"] = claude_model
        try:
            # No --model flag: Claude Code validates model names against its own
            # known list and stalls on local Ollama tags. ANTHROPIC_MODEL above
            # selects the model, and LiteLLM's "*" wildcard routes it.
            if os.name == "nt":
                _subprocess.Popen(
                    ["cmd", "/c", "start", "cmd", "/k", "claude"],
                    env=env, cwd=SCRIPT_DIR,
                )
            else:
                _subprocess.Popen(
                    ["x-terminal-emulator", "-e", "claude"],
                    env=env, cwd=SCRIPT_DIR,
                )
        except OSError as e:
            QMessageBox.critical(self, "Launch Failed", str(e))

    def _install_model(self):
        """Create the model in Ollama from the Modelfile."""
        self.banner_action_btn.setEnabled(False)
        self.banner_action_btn.setText("Installing…")

        manager = self.backend.create_model()
        manager.progress_update.connect(
            lambda msg: self.banner_label.setText(f"⏳  {msg}")
        )
        manager.finished_ok.connect(self._on_model_installed)
        manager.finished_error.connect(self._on_model_install_error)
        manager.start()

    def _on_model_installed(self):
        self.banner_action_btn.setEnabled(True)
        self.banner_action_btn.setText("Install Model")
        self.backend.check_status()  # re-poll

    def _on_model_install_error(self, error: str):
        self.banner_action_btn.setEnabled(True)
        self.banner_action_btn.setText("Retry Install")
        QMessageBox.critical(self, "Model Install Failed", error)

    def _start_litellm(self):
        """Start the LiteLLM proxy."""
        self.banner_action_btn.setEnabled(False)
        self.banner_action_btn.setText("Starting…")

        starter = self.backend.start_litellm()
        starter.progress_update.connect(
            lambda msg: self.banner_label.setText(f"⏳  {msg}")
        )
        starter.started_ok.connect(self._on_litellm_started)
        starter.started_error.connect(self._on_litellm_start_error)
        starter.start()

    def _on_litellm_started(self):
        self.banner_action_btn.setEnabled(True)
        self.banner_action_btn.setText("Start LiteLLM")
        self.backend.check_status()

    def _on_litellm_start_error(self, error: str):
        self.banner_action_btn.setEnabled(True)
        self.banner_action_btn.setText("Retry")
        QMessageBox.critical(self, "LiteLLM Start Failed", error)

    def _send_message(self):
        """Send the current input as a user message."""
        text = self.chat_input.toPlainText().strip()
        if not text:
            return

        if self.backend.is_generating():
            return

        # Remove welcome card
        self._remove_welcome()

        # Clear input
        self.chat_input.clear()

        # Add user bubble
        user_bubble = MessageBubble("user", text)
        self.messages_layout.addWidget(user_bubble)

        # Create assistant bubble for streaming
        self._streaming_text = ""
        self._streaming_bubble = MessageBubble("assistant", "")
        self._streaming_bubble.content_label.setText(
            f'<span style="color: {COLORS["text_muted"]};">Thinking…</span>'
        )
        self.messages_layout.addWidget(self._streaming_bubble)

        # Scroll to bottom
        QTimer.singleShot(50, self._scroll_to_bottom)

        # Toggle buttons — Stop always visible, just enable/disable
        self.send_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.chat_input.setEnabled(False)

        # Start generation
        worker = self.backend.send_message(text)
        worker.token_received.connect(self._on_token)
        worker.generation_complete.connect(self._on_generation_complete)
        worker.error_occurred.connect(self._on_generation_error)
        worker.stats_update.connect(self._on_stats_update)
        worker.start()

    def _on_token(self, token: str):
        """Handle a single streaming token."""
        if self._streaming_bubble:
            self._streaming_text += token
            self._streaming_bubble.update_content(self._streaming_text)
            self._scroll_to_bottom()

    def _on_generation_complete(self, full_response: str):
        """Handle generation completion."""
        self.backend.finalize_response(full_response)

        # Auto-save the conversation (rolling backup)
        history.auto_save(self.backend.conversation)

        # Final render
        if self._streaming_bubble:
            self._streaming_bubble.update_content(full_response)

        self._streaming_bubble = None
        self._streaming_text = ""

        # Restore buttons
        self.send_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.chat_input.setEnabled(True)
        self.chat_input.setFocus()

        self._scroll_to_bottom()

    def _on_generation_error(self, error: str):
        """Handle generation error."""
        if self._streaming_bubble:
            self._streaming_bubble.update_content(
                f"⚠ **Error:** {error}"
            )
            self._streaming_bubble.setStyleSheet(
                f"background-color: rgba(239, 68, 68, 0.1);"
                f" border: 1px solid rgba(239, 68, 68, 0.3);"
                f" border-radius: 14px; border-top-left-radius: 4px;"
                f" padding: 12px 16px; margin: 4px 80px 4px 0px;"
            )

        self._streaming_bubble = None
        self._streaming_text = ""

        self.send_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.chat_input.setEnabled(True)
        self.chat_input.setFocus()

    def _on_stats_update(self, stats: dict):
        """Update the generation speed indicator."""
        tps = stats.get("tokens_per_sec", 0)
        # Drive the bar meter: scale 0–30 tok/s → 0.0–1.0
        self.bar_meter.set_level(min(tps / 30.0, 1.0))
        self.hw_strip.set_plate(f"{int(tps):3d}T")

    def _stop_generation(self):
        """Stop the current generation."""
        self.backend.stop_generation()

    def _clear_chat(self):
        """Clear all messages and reset conversation."""
        # Remove all message bubbles
        while self.messages_layout.count():
            item = self.messages_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        self.backend.clear_conversation()
        self._streaming_bubble = None
        self._streaming_text = ""
        self.bar_meter.set_level(0.0)
        self.hw_strip.set_plate("OFF")

        # Re-add welcome
        self._add_welcome_message()

    def _toggle_settings(self):
        """Show/hide the settings panel."""
        visible = self.settings_scroll.isVisible()
        self.settings_scroll.setVisible(not visible)

    def _on_scroll_changed(self, value: int):
        """Re-enable auto-scroll when the user returns to the bottom."""
        sb = self.scroll_area.verticalScrollBar()
        if value >= sb.maximum() - 40:
            self._auto_scroll = True
        else:
            self._auto_scroll = False

    def _save_conversation(self):
        """Export the current conversation to a Markdown file."""
        if not self.backend.conversation:
            QMessageBox.information(self, "Nothing to Save", "The conversation is empty.")
            return

        default_name = Path.home() / "qwythos_conversation.md"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Conversation", str(default_name),
            "Markdown (*.md);;Text Files (*.txt);;All Files (*)",
        )
        if not path:
            return

        lines = ["# Qwythos AI Conversation", ""]
        for msg in self.backend.conversation:
            role = "**You**" if msg["role"] == "user" else "**Qwythos**"
            lines.append(role)
            lines.append("")
            lines.append(msg["content"])
            lines.append("")

        try:
            Path(path).write_text("\n".join(lines), encoding="utf-8")
            QMessageBox.information(self, "Saved", f"Conversation saved to:\n{path}")
        except OSError as e:
            QMessageBox.critical(self, "Save Failed", str(e))

    def _save_session(self):
        """Save the current conversation as a named history session."""
        if not self.backend.conversation:
            QMessageBox.information(self, "Nothing to Save", "The conversation is empty.")
            return
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, "Save Session", "Session name (blank = timestamp):"
        )
        if not ok:
            return
        try:
            path = history.save_session(self.backend.conversation, name.strip() or None)
            QMessageBox.information(self, "Saved", f"Session saved to:\n{path}")
        except OSError as e:
            QMessageBox.critical(self, "Save Failed", str(e))

    def _load_session(self):
        """Pick a saved session and restore it into the chat."""
        sessions = history.list_sessions()
        if not sessions:
            auto = history.load_auto_save()
            if auto:
                reply = QMessageBox.question(
                    self, "Restore Session",
                    "No named sessions found. Restore the auto-saved conversation?",
                )
                if reply == QMessageBox.Yes:
                    self._restore_conversation(auto)
                return
            QMessageBox.information(self, "No Sessions", "No saved sessions found.")
            return

        items = [f"{s['name']}  ({s['message_count']} msgs)" for s in sessions]
        item, ok = QInputDialog.getItem(self, "Load Session", "Session:", items, 0, False)
        if ok and item:
            idx = items.index(item)
            messages = history.load_session(sessions[idx]["path"])
            if messages:
                self._restore_conversation(messages)

    def _restore_conversation(self, messages: list):
        """Replace the current chat with messages loaded from history."""
        while self.messages_layout.count():
            item = self.messages_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        self._remove_welcome()
        self.backend.conversation = list(messages)

        for msg in messages:
            if msg.get("role") == "system":
                continue
            bubble = MessageBubble(msg.get("role", "assistant"), msg.get("content", ""))
            self.messages_layout.addWidget(bubble)

        self._streaming_bubble = None
        self._streaming_text = ""
        QTimer.singleShot(50, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        """Scroll the chat view to the bottom (only if auto-scroll is on)."""
        if not self._auto_scroll:
            return
        sb = self.scroll_area.verticalScrollBar()
        sb.setValue(sb.maximum())


# ─── Entry Point ──────────────────────────────────────────────────────────────

def main():
    # High DPI support
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # consistent cross-platform base

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
