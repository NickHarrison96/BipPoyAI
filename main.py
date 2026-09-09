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
import textwrap
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QFrame, QScrollArea, QSplitter, QGroupBox,
    QFormLayout, QComboBox, QSlider, QSpinBox, QDoubleSpinBox, QSizePolicy,
    QMessageBox, QStackedWidget,
)
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QSize
from PySide6.QtGui import QFont, QTextCursor, QKeyEvent, QIcon, QFontMetrics

from styles import get_main_stylesheet, get_status_pill_style, COLORS
from backend import OllamaBackend, derive_model_tag


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

    def update_content(self, content: str):
        """Update the displayed content (used during streaming)."""
        if self.role == "user":
            self.content_label.setText(content.replace("\n", "<br>"))
        else:
            self.content_label.setText(md_to_html(content))


# ─── Settings Panel ──────────────────────────────────────────────────────────

class SettingsPanel(QFrame):
    """Sidebar panel with hardware/model configuration controls."""

    def __init__(self, backend: OllamaBackend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.setObjectName("settingsPanel")
        self.setFixedWidth(320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Title
        title = QLabel("⚙  Settings")
        title.setObjectName("titleLabel")
        title.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {COLORS['text_primary']};")
        layout.addWidget(title)

        # ── Inference Settings ──
        inf_group = QGroupBox("Inference")
        inf_layout = QFormLayout(inf_group)
        inf_layout.setSpacing(10)
        inf_layout.setContentsMargins(12, 20, 12, 12)

        # Context Size
        self.ctx_combo = QComboBox()
        self.ctx_combo.addItems(["8192", "16384", "32768", "65536"])
        self.ctx_combo.setCurrentText(str(backend.num_ctx))
        inf_layout.addRow("Context Size:", self.ctx_combo)

        # Temperature
        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 2.0)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setDecimals(2)
        self.temp_spin.setValue(backend.temperature)
        inf_layout.addRow("Temperature:", self.temp_spin)

        # Max Tokens
        self.max_tokens_combo = QComboBox()
        self.max_tokens_combo.addItems(["2048", "4096", "8192", "16384"])
        self.max_tokens_combo.setCurrentText(str(backend.max_tokens))
        inf_layout.addRow("Max Tokens:", self.max_tokens_combo)

        layout.addWidget(inf_group)

        # ── Hardware Settings ──
        hw_group = QGroupBox("Hardware (Modelfile)")
        hw_layout = QFormLayout(hw_group)
        hw_layout.setSpacing(10)
        hw_layout.setContentsMargins(12, 20, 12, 12)

        # GPU Layers
        self.gpu_spin = QSpinBox()
        self.gpu_spin.setRange(0, 99)
        self.gpu_spin.setValue(99)
        self.gpu_spin.setToolTip("99 = full GPU offload. 0 = CPU only.")
        hw_layout.addRow("GPU Layers:", self.gpu_spin)

        # CPU Threads
        cpu_count = os.cpu_count() or 8
        self.cpu_spin = QSpinBox()
        self.cpu_spin.setRange(1, cpu_count)
        self.cpu_spin.setValue(max(1, cpu_count - 2))
        hw_layout.addRow("CPU Threads:", self.cpu_spin)

        # Batch Size
        self.batch_combo = QComboBox()
        self.batch_combo.addItems(["256", "512", "1024"])
        self.batch_combo.setCurrentText("512")
        hw_layout.addRow("Batch Size:", self.batch_combo)

        layout.addWidget(hw_group)

        # ── Actions ──
        # Apply to running session
        apply_btn = QPushButton("Apply Settings")
        apply_btn.setObjectName("secondaryButton")
        apply_btn.setToolTip("Apply inference settings to the current session")
        apply_btn.clicked.connect(self._apply_settings)
        layout.addWidget(apply_btn)

        # Save & Rebuild Modelfile + config.yaml
        save_btn = QPushButton("Save && Rebuild Configs")
        save_btn.setToolTip(
            "Regenerate Modelfile and config.yaml with current settings.\n"
            "You'll need to re-create the Ollama model for hardware changes to take effect."
        )
        save_btn.clicked.connect(self._save_and_rebuild)
        layout.addWidget(save_btn)

        layout.addStretch()

        # ── Model Info ──
        info_label = QLabel(f"Model: {backend.get_model_tag()}")
        info_label.setObjectName("mutedLabel")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # Load saved hardware settings from existing Modelfile
        self._load_from_modelfile()

    def _load_from_modelfile(self):
        """Read current hardware values from the existing Modelfile."""
        modelfile_path = Path(self.backend.working_dir) / "Modelfile"
        if not modelfile_path.exists():
            return
        try:
            content = modelfile_path.read_text(encoding="utf-8")

            ctx_m = re.search(r'PARAMETER\s+num_ctx\s+(\d+)', content)
            if ctx_m:
                val = ctx_m.group(1)
                idx = self.ctx_combo.findText(val)
                if idx >= 0:
                    self.ctx_combo.setCurrentIndex(idx)

            gpu_m = re.search(r'PARAMETER\s+num_gpu\s+(\d+)', content)
            if gpu_m:
                self.gpu_spin.setValue(int(gpu_m.group(1)))

            cpu_m = re.search(r'PARAMETER\s+num_thread\s+(\d+)', content)
            if cpu_m:
                self.cpu_spin.setValue(int(cpu_m.group(1)))

            batch_m = re.search(r'PARAMETER\s+num_batch\s+(\d+)', content)
            if batch_m:
                val = batch_m.group(1)
                idx = self.batch_combo.findText(val)
                if idx >= 0:
                    self.batch_combo.setCurrentIndex(idx)

            temp_m = re.search(r'PARAMETER\s+temperature\s+([\d.]+)', content)
            if temp_m:
                self.temp_spin.setValue(float(temp_m.group(1)))

        except Exception:
            pass

    def _apply_settings(self):
        """Push current UI values into the backend for the running session."""
        self.backend.update_settings(
            temperature=self.temp_spin.value(),
            num_ctx=int(self.ctx_combo.currentText()),
            max_tokens=int(self.max_tokens_combo.currentText()),
        )

    def _save_and_rebuild(self):
        """Regenerate Modelfile and config.yaml from current UI values."""
        working_dir = Path(self.backend.working_dir)
        model_tag = self.backend.get_model_tag()

        # Find GGUF file
        gguf_files = list(working_dir.glob("*.gguf"))
        if not gguf_files:
            QMessageBox.warning(self, "Error", "No .gguf file found in the model directory.")
            return
        selected_gguf = gguf_files[0].name

        context_size = int(self.ctx_combo.currentText())
        gpu_layers = self.gpu_spin.value()
        cpu_threads = self.cpu_spin.value()
        batch_size = int(self.batch_combo.currentText())
        temperature = self.temp_spin.value()

        # ── Write Modelfile ──
        modelfile_content = textwrap.dedent(f"""\
            FROM ./{selected_gguf}

            # Hardware, RAM, and VRAM resource allocation
            PARAMETER num_ctx {context_size}
            PARAMETER num_gpu {gpu_layers}
            PARAMETER num_thread {cpu_threads}
            PARAMETER num_batch {batch_size}
            PARAMETER temperature {temperature}

            SYSTEM \"\"\"
            You are a helpful, knowledgeable AI assistant. Answer clearly and concisely.
            \"\"\"
        """)

        modelfile_path = working_dir / "Modelfile"
        modelfile_path.write_text(modelfile_content, encoding="utf-8")

        # ── Write config.yaml ──
        config_content = textwrap.dedent(f"""\
            model_list:
              - model_name: {model_tag}
                litellm_params:
                  model: ollama_chat/{model_tag}
                  api_base: http://127.0.0.1:11434
                  num_ctx: {context_size}
                  max_tokens: {int(self.max_tokens_combo.currentText())}
              - model_name: "*"
                litellm_params:
                  model: ollama_chat/{model_tag}
                  api_base: http://127.0.0.1:11434
                  num_ctx: {context_size}
                  max_tokens: {int(self.max_tokens_combo.currentText())}

            litellm_settings:
              drop_params: true
              ignore_invalid_params: true
              modify_params: true
              force_timeout: 600
              json_logs: false
        """)

        config_path = working_dir / "config.yaml"
        config_path.write_text(config_content, encoding="utf-8")

        # Apply to running session too
        self._apply_settings()

        QMessageBox.information(
            self,
            "Saved",
            "Modelfile and config.yaml have been rebuilt.\n\n"
            "If you changed hardware settings (GPU layers, threads, batch),\n"
            "you'll need to click 'Install Model' in the status bar to\n"
            "re-create the Ollama model with the new settings."
        )


# ─── Main Window ─────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    """The main Qwythos AI chat window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Qwythos AI")
        self.setMinimumSize(900, 650)
        self.resize(1100, 750)

        # Backend
        self.backend = OllamaBackend(working_dir=SCRIPT_DIR)

        # Streaming state
        self._streaming_bubble: MessageBubble | None = None
        self._streaming_text = ""

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

        # Input area
        input_area = self._build_input_area()
        chat_layout.addWidget(input_area)

        # Status bar
        status_bar = self._build_status_bar()
        chat_layout.addWidget(status_bar)

        main_layout.addWidget(chat_container, 1)

        # ── Settings Panel (right sidebar) ──
        self.settings_panel = SettingsPanel(self.backend)
        self.settings_panel.setVisible(False)  # hidden by default
        main_layout.addWidget(self.settings_panel)

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

        # Clear chat button
        clear_btn = QPushButton("🗑  Clear")
        clear_btn.setObjectName("secondaryButton")
        clear_btn.setFixedHeight(32)
        clear_btn.clicked.connect(self._clear_chat)
        layout.addWidget(clear_btn)

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
        self.stop_btn.setVisible(False)
        btn_layout.addWidget(self.stop_btn)

        layout.addWidget(btn_container)

        return container

    def _build_status_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("statusBar")
        bar.setFixedHeight(32)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(16)

        # Ollama status
        ollama_label = QLabel("Ollama")
        ollama_label.setStyleSheet(
            f"font-size: 11px; color: {COLORS['text_muted']}; background: transparent;"
        )
        layout.addWidget(ollama_label)

        self.ollama_pill = QLabel("checking…")
        self.ollama_pill.setObjectName("statusPill")
        self.ollama_pill.setStyleSheet(get_status_pill_style("loading"))
        layout.addWidget(self.ollama_pill)

        # LiteLLM status
        litellm_label = QLabel("LiteLLM")
        litellm_label.setStyleSheet(
            f"font-size: 11px; color: {COLORS['text_muted']}; background: transparent;"
        )
        layout.addWidget(litellm_label)

        self.litellm_pill = QLabel("checking…")
        self.litellm_pill.setObjectName("statusPill")
        self.litellm_pill.setStyleSheet(get_status_pill_style("loading"))
        layout.addWidget(self.litellm_pill)

        # Model status
        model_label = QLabel("Model")
        model_label.setStyleSheet(
            f"font-size: 11px; color: {COLORS['text_muted']}; background: transparent;"
        )
        layout.addWidget(model_label)

        self.model_pill = QLabel("checking…")
        self.model_pill.setObjectName("statusPill")
        self.model_pill.setStyleSheet(get_status_pill_style("loading"))
        layout.addWidget(self.model_pill)

        layout.addStretch()

        # Generation stats
        self.stats_label = QLabel("")
        self.stats_label.setStyleSheet(
            f"font-size: 11px; color: {COLORS['text_muted']}; background: transparent;"
        )
        layout.addWidget(self.stats_label)

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

        icon = QLabel("✦")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(f"font-size: 48px; color: {COLORS['accent']}; background: transparent;")
        wlayout.addWidget(icon)

        title = QLabel("Welcome to Qwythos AI")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            f"font-size: 22px; font-weight: 700; color: {COLORS['text_primary']};"
            f" background: transparent;"
        )
        wlayout.addWidget(title)

        desc = QLabel(
            "Your local AI assistant running entirely on this computer.\n"
            "No internet required • Complete privacy • Unlimited usage"
        )
        desc.setAlignment(Qt.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-size: 14px; color: {COLORS['text_secondary']}; background: transparent;"
            f" line-height: 1.5;"
        )
        wlayout.addWidget(desc)

        hint = QLabel("Type a message below to get started →")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(
            f"font-size: 13px; color: {COLORS['text_muted']}; background: transparent;"
            f" padding-top: 8px;"
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
        if status == "live":
            self.ollama_pill.setText("live")
            self.ollama_pill.setStyleSheet(get_status_pill_style("live"))
        else:
            self.ollama_pill.setText("offline")
            self.ollama_pill.setStyleSheet(get_status_pill_style("offline"))
        self._update_banner()

    def _on_litellm_status(self, status: str):
        self._litellm_live = (status == "live")
        if status == "live":
            self.litellm_pill.setText("live")
            self.litellm_pill.setStyleSheet(get_status_pill_style("live"))
        else:
            self.litellm_pill.setText("offline")
            self.litellm_pill.setStyleSheet(get_status_pill_style("offline"))
        self._update_banner()

    def _on_model_status(self, status: str):
        self._model_ready = (status == "ready")
        if status == "ready":
            self.model_pill.setText("ready")
            self.model_pill.setStyleSheet(get_status_pill_style("live"))
        elif status == "not_found":
            self.model_pill.setText("not found")
            self.model_pill.setStyleSheet(get_status_pill_style("offline"))
        else:
            self.model_pill.setText("unknown")
            self.model_pill.setStyleSheet(get_status_pill_style("loading"))
        self._update_banner()

    def _update_banner(self):
        """Show/hide the status banner based on service states."""
        # Disconnect any previous banner button connections cleanly
        if self._banner_connected:
            try:
                self.banner_action_btn.clicked.disconnect()
            except (RuntimeError, TypeError):
                pass
            self._banner_connected = False

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
        elif not self._litellm_live:
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

        # Toggle buttons
        self.send_btn.setVisible(False)
        self.stop_btn.setVisible(True)
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

        # Final render
        if self._streaming_bubble:
            self._streaming_bubble.update_content(full_response)

        self._streaming_bubble = None
        self._streaming_text = ""

        # Restore buttons
        self.send_btn.setVisible(True)
        self.stop_btn.setVisible(False)
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

        self.send_btn.setVisible(True)
        self.stop_btn.setVisible(False)
        self.chat_input.setEnabled(True)
        self.chat_input.setFocus()

    def _on_stats_update(self, stats: dict):
        """Update the generation speed indicator."""
        tps = stats.get("tokens_per_sec", 0)
        total = stats.get("total_tokens", 0)
        self.stats_label.setText(f"{tps} tok/s  •  {total} tokens")

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
        self.stats_label.setText("")

        # Re-add welcome
        self._add_welcome_message()

    def _toggle_settings(self):
        """Show/hide the settings panel."""
        visible = self.settings_panel.isVisible()
        self.settings_panel.setVisible(not visible)

    def _scroll_to_bottom(self):
        """Scroll the chat view to the bottom."""
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
