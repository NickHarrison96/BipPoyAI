"""
Pip-Boy inspired theme — amber/gold readout on weathered dark green.

Design rules:
  - Monospace everywhere.
  - Amber is the ink; green is the paper. Never the reverse.
  - Panels are rounded and outlined in warm gold, lit from within.
  - Green/amber/red LEDs carry status. Nothing else is allowed to be red.
  - Texture, glow, and knobs are painted in widgets.py — QSS can't do them.
"""

# ─── Palette ──────────────────────────────────────────────────────────────────

COLORS = {
    # Ground — desaturated field green, warm-shifted
    "bg":            "#16241c",
    "bg_deep":       "#0f1a14",
    "bg_raised":     "#1c2e24",
    "bg_panel":      "#1a2b21",
    "bg_inset":      "#111c16",
    "bg_hover":      "#24382c",

    # Warm light bleeding through the cracks
    "ember":         "#c76a3a",
    "ember_dim":     "#5c3520",

    # Amber ramp — the readout
    "a_dim":         "#6b5a34",
    "a_muted":       "#9a834a",
    "a_mid":         "#c9a961",
    "a_bright":      "#e8c07a",
    "a_hot":         "#ffd98a",

    # Status LEDs
    "led_green":     "#6eff7a",
    "led_green_dim": "#1f4a26",
    "led_amber":     "#ffb642",
    "led_amber_dim": "#5c3f14",
    "led_red":       "#ff5f56",
    "led_red_dim":   "#4a1a18",

    # Structure
    "border":        "#3d5240",
    "border_warm":   "#7a6238",
    "border_hot":    "#c9a961",

    # ── Back-compat aliases (older main.py referenced these) ──
    "glass":                    "#1a2b21",
    "glass_border":             "#7a6238",
    "divider":                  "#3d5240",
    "text_primary":             "#e8c07a",
    "text_secondary":           "#c9a961",
    "text_muted":               "#9a834a",
    "accent":                   "#ffd98a",
    "success":                  "#6eff7a",
    "warning":                  "#ffb642",
    "error":                    "#ff5f56",
    "user_bubble":              "#111c16",
    "user_bubble_border":       "#7a6238",
    "assistant_bubble":         "#1a2b21",
    "assistant_bubble_border":  "#3d5240",
}

MONO = '"Cascadia Mono", "JetBrains Mono", "Consolas", "DejaVu Sans Mono", monospace'


def get_main_stylesheet() -> str:
    C = COLORS
    return f"""
    /* ── GLOBAL ────────────────────────────────────────────────── */
    QWidget {{
        background-color: transparent;
        color: {C["a_mid"]};
        font-family: {MONO};
        font-size: 13px;
    }}

    QMainWindow {{ background-color: {C["bg"]}; }}

    QToolTip {{
        background-color: {C["bg_deep"]};
        color: {C["a_bright"]};
        border: 1px solid {C["border_warm"]};
        border-radius: 4px;
        padding: 6px 9px;
        font-family: {MONO};
        font-size: 12px;
    }}

    /* ── STRUCTURAL FRAMES ─────────────────────────────────────── */
    QFrame#headerBar {{
        background-color: rgba(15, 26, 20, 0.72);
        border: none;
        border-bottom: 1px solid {C["border_warm"]};
    }}

    QFrame#statusStrip {{
        background-color: rgba(10, 18, 14, 0.88);
        border: none;
        border-top: 1px solid {C["border_warm"]};
    }}

    QFrame#inputDock {{
        background-color: rgba(15, 26, 20, 0.72);
        border: none;
        border-top: 1px solid {C["border_warm"]};
    }}

    QFrame#alertBar {{
        background-color: rgba(92, 63, 20, 0.55);
        border: none;
        border-bottom: 1px solid {C["led_amber"]};
    }}

    /* Rounded readout panel — the signature element */
    QFrame#panel {{
        background-color: rgba(26, 43, 33, 0.82);
        border: 1px solid {C["border_hot"]};
        border-radius: 10px;
    }}

    QFrame#panelInset {{
        background-color: rgba(17, 28, 22, 0.85);
        border: 1px solid {C["border"]};
        border-radius: 8px;
    }}

    /* ── SCROLL ────────────────────────────────────────────────── */
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}

    QScrollBar:vertical {{
        background: rgba(17, 28, 22, 0.6);
        width: 12px;
        margin: 0;
        border-left: 1px solid {C["border"]};
    }}
    QScrollBar::handle:vertical {{
        background: {C["a_dim"]};
        min-height: 28px;
        border-radius: 3px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {C["a_muted"]}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

    QScrollBar:horizontal {{
        background: rgba(17, 28, 22, 0.6);
        height: 12px;
        border-top: 1px solid {C["border"]};
    }}
    QScrollBar::handle:horizontal {{
        background: {C["a_dim"]}; min-width: 28px; border-radius: 3px; margin: 2px;
    }}
    QScrollBar::handle:horizontal:hover {{ background: {C["a_muted"]}; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

    /* ── BUTTONS ───────────────────────────────────────────────── */
    QPushButton {{
        background-color: rgba(26, 43, 33, 0.6);
        color: {C["a_mid"]};
        border: 1px solid {C["border_warm"]};
        border-radius: 6px;
        padding: 7px 15px;
        font-family: {MONO};
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 1px;
    }}
    QPushButton:hover {{
        background-color: {C["bg_hover"]};
        color: {C["a_hot"]};
        border-color: {C["border_hot"]};
    }}
    QPushButton:pressed {{
        background-color: {C["a_dim"]};
        color: {C["a_hot"]};
    }}
    QPushButton:disabled {{
        color: {C["a_dim"]};
        border-color: {C["border"]};
        background-color: transparent;
    }}

    QPushButton#primaryButton {{
        background-color: rgba(201, 169, 97, 0.18);
        color: {C["a_hot"]};
        border: 1px solid {C["border_hot"]};
    }}
    QPushButton#primaryButton:hover {{
        background-color: rgba(232, 192, 122, 0.32);
        color: #fff0c4;
    }}
    QPushButton#primaryButton:disabled {{
        background-color: transparent;
        color: {C["a_dim"]};
        border-color: {C["border"]};
    }}

    QPushButton#dangerButton {{
        color: {C["led_red"]};
        border: 1px solid {C["led_red_dim"]};
        background-color: rgba(74, 26, 24, 0.35);
    }}
    QPushButton#dangerButton:hover {{
        background-color: rgba(255, 95, 86, 0.22);
        border-color: {C["led_red"]};
    }}

    QPushButton#ghostButton {{
        background-color: transparent;
        border: 1px solid transparent;
        color: {C["a_muted"]};
        padding: 6px 10px;
    }}
    QPushButton#ghostButton:hover {{
        color: {C["a_hot"]};
        border-color: {C["border_warm"]};
        background-color: rgba(36, 56, 44, 0.6);
    }}

    QPushButton#tabButton {{
        background-color: transparent;
        border: none;
        border-bottom: 2px solid transparent;
        border-radius: 0px;
        color: {C["a_muted"]};
        padding: 8px 16px;
    }}
    QPushButton#tabButton:hover {{ color: {C["a_bright"]}; }}
    QPushButton#tabButton:checked {{
        color: {C["a_hot"]};
        border-bottom: 2px solid {C["a_hot"]};
    }}

    /* ── INPUTS ────────────────────────────────────────────────── */
    QTextEdit#chatInput {{
        background-color: rgba(17, 28, 22, 0.9);
        border: 1px solid {C["border_warm"]};
        border-radius: 8px;
        padding: 10px 13px;
        color: {C["a_bright"]};
        font-family: {MONO};
        font-size: 13px;
        selection-background-color: {C["a_muted"]};
        selection-color: {C["bg_deep"]};
    }}
    QTextEdit#chatInput:focus {{ border-color: {C["border_hot"]}; }}

    QLineEdit {{
        background-color: rgba(17, 28, 22, 0.9);
        border: 1px solid {C["border"]};
        border-radius: 5px;
        padding: 6px 9px;
        color: {C["a_bright"]};
        font-family: {MONO};
        font-size: 12px;
        selection-background-color: {C["a_muted"]};
        selection-color: {C["bg_deep"]};
    }}
    QLineEdit:focus {{ border-color: {C["border_hot"]}; }}
    QLineEdit:disabled {{ color: {C["a_dim"]}; }}

    /* ── COMBO / SPIN ──────────────────────────────────────────── */
    QComboBox {{
        background-color: rgba(17, 28, 22, 0.9);
        border: 1px solid {C["border"]};
        border-radius: 5px;
        padding: 6px 9px;
        color: {C["a_bright"]};
        font-family: {MONO};
        font-size: 12px;
    }}
    QComboBox:hover {{ border-color: {C["border_warm"]}; }}
    QComboBox:focus {{ border-color: {C["border_hot"]}; }}
    QComboBox::drop-down {{
        border: none;
        border-left: 1px solid {C["border"]};
        width: 18px;
    }}
    QComboBox::down-arrow {{
        image: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid {C["a_muted"]};
        margin-right: 6px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {C["bg_deep"]};
        border: 1px solid {C["border_hot"]};
        border-radius: 5px;
        color: {C["a_mid"]};
        selection-background-color: rgba(201, 169, 97, 0.25);
        selection-color: {C["a_hot"]};
        outline: none;
        padding: 3px;
    }}

    QSpinBox, QDoubleSpinBox {{
        background-color: rgba(17, 28, 22, 0.9);
        border: 1px solid {C["border"]};
        border-radius: 5px;
        padding: 6px 9px;
        color: {C["a_bright"]};
        font-family: {MONO};
        font-size: 12px;
    }}
    QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {C["border_hot"]}; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button,
    QSpinBox::down-button, QDoubleSpinBox::down-button {{
        background: transparent;
        border: none;
        border-left: 1px solid {C["border"]};
        width: 14px;
    }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
        image: none;
        border-left: 3px solid transparent;
        border-right: 3px solid transparent;
        border-bottom: 4px solid {C["a_muted"]};
    }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
        image: none;
        border-left: 3px solid transparent;
        border-right: 3px solid transparent;
        border-top: 4px solid {C["a_muted"]};
    }}

    /* ── LABELS ────────────────────────────────────────────────── */
    QLabel {{ background: transparent; color: {C["a_mid"]}; }}

    QLabel#brandLabel {{
        color: {C["a_hot"]};
        font-size: 19px;
        font-weight: 700;
        letter-spacing: 1px;
    }}
    QLabel#brandSub {{
        color: {C["a_dim"]};
        font-size: 11px;
        letter-spacing: 1px;
    }}
    QLabel#sectionRule {{
        color: {C["a_muted"]};
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 2px;
        padding: 2px 0px;
    }}
    QLabel#fieldLabel {{
        color: {C["a_muted"]};
        font-size: 12px;
    }}
    QLabel#hintLabel {{
        color: {C["a_dim"]};
        font-size: 11px;
    }}
    QLabel#alertText {{
        color: {C["led_amber"]};
        font-size: 12px;
        background: transparent;
    }}
    QLabel#welcomeTitle {{
        color: {C["a_hot"]};
        font-size: 21px;
        font-weight: 700;
        letter-spacing: 1px;
    }}
    QLabel#welcomeBody {{
        color: {C["a_mid"]};
        font-size: 13px;
    }}
    QLabel#statusCaption {{
        color: {C["a_dim"]};
        font-size: 11px;
        letter-spacing: 1px;
    }}

    /* ── GROUPBOX ──────────────────────────────────────────────── */
    QGroupBox {{
        background-color: rgba(17, 28, 22, 0.45);
        border: 1px solid {C["border"]};
        border-radius: 8px;
        margin-top: 11px;
        padding: 20px 13px 13px 13px;
        font-family: {MONO};
        font-size: 11px;
        font-weight: 700;
        color: {C["a_muted"]};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 11px;
        padding: 0 7px;
        background-color: {C["bg_raised"]};
        color: {C["a_bright"]};
        letter-spacing: 2px;
    }}

    /* ── MISC ──────────────────────────────────────────────────── */
    QSplitter::handle {{ background-color: {C["border"]}; width: 1px; }}

    QMessageBox {{ background-color: {C["bg_raised"]}; }}
    QMessageBox QLabel {{ color: {C["a_mid"]}; font-family: {MONO}; }}
    """


# ─── Status pill ──────────────────────────────────────────────────────────────

def get_status_pill_style(status: str) -> str:
    """Rounded status tag paired with an LEDDot. live | loading | offline."""
    C = COLORS
    base = (
        f"font-family: {MONO}; font-size: 11px; font-weight: 700;"
        f" padding: 2px 8px; border-radius: 4px; letter-spacing: 1px;"
    )
    if status == "live":
        return base + (f"color: {C['led_green']};"
                       f" background-color: rgba(110, 255, 122, 0.10);"
                       f" border: 1px solid {C['led_green_dim']};")
    if status == "loading":
        return base + (f"color: {C['led_amber']};"
                       f" background-color: rgba(255, 182, 66, 0.10);"
                       f" border: 1px solid {C['led_amber_dim']};")
    return base + (f"color: {C['led_red']};"
                   f" background-color: rgba(255, 95, 86, 0.10);"
                   f" border: 1px solid {C['led_red_dim']};")


# ─── Chat turn styling ────────────────────────────────────────────────────────

def get_chat_line_style(role: str) -> str:
    """
    Chat turns are readout blocks with a warm left rule — brighter for the
    operator (you), dimmer for the machine.
    """
    C = COLORS
    if role == "user":
        return (
            f"background-color: rgba(17, 28, 22, 0.55);"
            f" border: 1px solid {C['border']};"
            f" border-left: 3px solid {C['a_mid']};"
            f" border-radius: 6px;"
            f" padding: 9px 13px;"
            f" margin: 0px;"
        )
    return (
        f"background-color: rgba(26, 43, 33, 0.55);"
        f" border: 1px solid {C['border']};"
        f" border-left: 3px solid {C['a_dim']};"
        f" border-radius: 6px;"
        f" padding: 9px 13px;"
        f" margin: 0px;"
    )
