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

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QFrame, QScrollArea, QGroupBox, QLineEdit,
    QFormLayout, QComboBox, QSpinBox, QDoubleSpinBox, QSizePolicy,
    QMessageBox,
)
from PySide6.QtCore import Qt, QTimer, QSize, QEvent
from PySide6.QtGui import QFont, QTextCursor, QKeyEvent

from styles import get_main_stylesheet, COLORS
from backend import OllamaBackend, derive_model_tag
from widgets import (
    CrackedBackdrop, ScanlineOverlay, LEDDot, HardwareStrip,
    BarMeter, MascotGlyph,
)
from configs import ModelConfig, load_full, write_all
from hardware import detect as detect_hardware


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
        self.setFixedWidth(340)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # Title
        title = QLabel("⚙  Settings")
        title.setStyleSheet(f"font-size: 17px; font-weight: 700; color: {COLORS['text_primary']};")
        layout.addWidget(title)

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

        layout.addWidget(conn_group)

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

        save_btn = QPushButton("💾  Save && Rebuild Configs")
        save_btn.setToolTip(
            "Regenerate Modelfile and config.yaml with current settings.\n"
            "You'll need to re-create the Ollama model for hardware changes to take effect."
        )
        save_btn.clicked.connect(self._save_and_rebuild)
        layout.addWidget(save_btn)

        layout.addStretch()

        # ── Model Info ──
        self.info_label = QLabel(f"Model: {backend.get_model_tag()}")
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet(f"font-size: 11px; color: {COLORS['text_muted']};")
        layout.addWidget(self.info_label)

        # Load saved settings from disk
        self._load_from_configs()

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

            self.temp_spin.setValue(cfg.temperature)

            idx = self.engine_combo.findText(cfg.engine_mode)
            if idx >= 0:
                self.engine_combo.setCurrentIndex(idx)

            self.litellm_url_edit.setText(cfg.litellm_url)
            self.litellm_key_edit.setText(cfg.litellm_api_key)
            self.ollama_url_edit.setText(cfg.ollama_base_url)
        except Exception:
            pass

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
        )

    def _save_and_rebuild(self):
        """Regenerate Modelfile and config.yaml using the configs module."""
        working_dir = Path(self.backend.working_dir)

        # Find GGUF file
        gguf_files = list(working_dir.glob("*.gguf"))
        if not gguf_files:
            QMessageBox.warning(self, "Error", "No .gguf file found in the model directory.")
            return

        cfg = ModelConfig(
            selected_gguf=gguf_files[0].name,
            model_tag=self.backend.get_model_tag(),
            engine_mode=self.engine_combo.currentText(),
            context_size=int(self.ctx_combo.currentText()),
            gpu_layers=self.gpu_spin.value(),
            cpu_threads=self.cpu_spin.value(),
            batch_size=int(self.batch_combo.currentText()),
            temperature=self.temp_spin.value(),
            max_tokens=int(self.max_tokens_combo.currentText()),
            litellm_url=self.litellm_url_edit.text() or "http://127.0.0.1:4000",
            litellm_api_key=self.litellm_key_edit.text() or "",
            ollama_base_url=self.ollama_url_edit.text() or "http://127.0.0.1:11434",
        )

        try:
            write_all(cfg, working_dir)
        except ValueError as e:
            QMessageBox.critical(self, "Save Failed", str(e))
            return

        # Apply inference settings to the running session too
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

        # Raise overlays so they sit above all child widgets
        self._backdrop.raise_()
        self._backdrop.lower()   # actually push it to the very back
        self._scanlines.raise_() # scanlines float above backdrop but below content

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
        pwr = "green" if self._ollama_live else "red"
        io  = "green" if self._litellm_live else "off"
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
