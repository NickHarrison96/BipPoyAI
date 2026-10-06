"""
Cayde 420 theme — bone-white plating over gunmetal, lit by a visor-orange glow.

Design rules:
  - Monospace everywhere.
  - Bone white is the ink; gunmetal is the paper. Never the reverse.
  - Panels are flat and steel-outlined. Light does not come from inside a
    panel — it bleeds in through the seams, which is what `ember` is for.
  - Visor orange is the accent, and it is rationed: brand, focus, primary
    action, and glow only. If everything is orange, nothing is.
  - Green/amber/red LEDs carry status. Nothing else is allowed to be red.
  - Texture, glow, and knobs are painted in widgets.py — QSS can't do them.
"""

# ─── Palette ──────────────────────────────────────────────────────────────────

COLORS = {
    # Ground — cold gunmetal, blue-shifted so orange reads as emissive
    "bg":            "#1a1d24",
    "bg_deep":       "#101218",
    "bg_raised":     "#262a33",
    "bg_panel":      "#1f232b",
    "bg_inset":      "#14171d",
    "bg_hover":      "#2f343e",

    # Visor orange — light bleeding through the seams
    "ember":         "#ff8a2b",
    "ember_dim":     "#5e3212",

    # Bone ramp — the readout. Grey at rest, emissive only at the top end.
    "a_dim":         "#6a6f7a",
    "a_muted":       "#949aa6",
    "a_mid":         "#c2c8d2",
    "a_bright":      "#e8ecf2",
    "a_hot":         "#ff9a3c",

    # Status LEDs
    "led_green":     "#46e08a",
    "led_green_dim": "#14432a",
    "led_amber":     "#ffb020",
    "led_amber_dim": "#5c3f14",
    "led_red":       "#ff4d4d",
    "led_red_dim":   "#4a1a18",

    # Structure — steel, never orange. Orange lives in the glow layer only.
    "border":        "#2b303b",
    "border_warm":   "#454d5b",
    "border_hot":    "#6b7686",

    # ── Back-compat aliases (older main.py referenced these) ──
    "glass":                    "#171a21",
    "glass_border":             "#454d5b",
    "divider":                  "#2b303b",
    "text_primary":             "#e8ecf2",
    "text_secondary":           "#c2c8d2",
    "text_muted":               "#949aa6",
    "accent":                   "#ff9a3c",
    "success":                  "#46e08a",
    "warning":                  "#ffb020",
    "error":                    "#ff4d4d",
    "user_bubble":              "#101218",
    "user_bubble_border":       "#454d5b",
    "assistant_bubble":         "#171a21",
    "assistant_bubble_border":  "#2b303b",
}

MONO = '"Cascadia Mono", "JetBrains Mono", "Consolas", "DejaVu Sans Mono", monospace'


def rgba(key: str, alpha: float) -> str:
    """Compose a translucent tint from a palette hex, so QSS stays in sync."""
    h = COLORS[key].lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {alpha})"


# ─── Identity ─────────────────────────────────────────────────────────────────
#
# Every user-visible name comes from here. The app is "Cayde 420"; the
# assistant is addressed as "Cayde" in the chat transcript. Do NOT reach for
# the model tag (`qwythos-heretic`) in UI strings — see AGENTS.md, "Naming".

APP_NAME = "Cayde 420"
ASSISTANT_NAME = "Cayde"
GLYPH = "⬡"  # hexagon, matches the tray icon and welcome glyph
TITLE = f"{GLYPH}  {APP_NAME}"


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
        background-color: {rgba("bg_deep", 0.72)};
        border: none;
        border-bottom: 1px solid {C["border_warm"]};
    }}

    QFrame#statusStrip {{
        background-color: {rgba("bg_deep", 0.9)};
        border: none;
        border-top: 1px solid {C["border_warm"]};
    }}

    QFrame#inputDock {{
        background-color: {rgba("bg_deep", 0.72)};
        border: none;
        border-top: 1px solid {C["border_warm"]};
    }}

    QFrame#alertBar {{
        background-color: {rgba("ember_dim", 0.45)};
        border: none;
        border-bottom: 1px solid {C["led_amber"]};
    }}

    /* Steel plate — the signature panel */
    QFrame#panel {{
        background-color: {rgba("bg_panel", 0.85)};
        border: 1px solid {C["border_warm"]};
        border-radius: 4px;
    }}

    QFrame#panelInset {{
        background-color: {rgba("bg_inset", 0.88)};
        border: 1px solid {C["border"]};
        border-radius: 3px;
    }}

    /* ── SCROLL ────────────────────────────────────────────────── */
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}

    QScrollBar:vertical {{
        background: {rgba("bg_inset", 0.6)};
        width: 12px;
        margin: 0;
        border-left: 1px solid {C["border"]};
    }}
    QScrollBar::handle:vertical {{
        background: {C["border_warm"]};
        min-height: 28px;
        border-radius: 2px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {C["a_dim"]}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

    QScrollBar:horizontal {{
        background: {rgba("bg_inset", 0.6)};
        height: 12px;
        border-top: 1px solid {C["border"]};
    }}
    QScrollBar::handle:horizontal {{
        background: {C["border_warm"]}; min-width: 28px; border-radius: 2px; margin: 2px;
    }}
    QScrollBar::handle:horizontal:hover {{ background: {C["a_dim"]}; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

    /* ── BUTTONS ───────────────────────────────────────────────── */
    QPushButton {{
        background-color: {rgba("bg_raised", 0.7)};
        color: {C["a_mid"]};
        border: 1px solid {C["border_warm"]};
        border-radius: 3px;
        padding: 7px 15px;
        font-family: {MONO};
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 2px;
    }}
    QPushButton:hover {{
        background-color: {C["bg_hover"]};
        color: {C["a_hot"]};
        border-color: {C["ember"]};
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
        background-color: {rgba("ember", 0.16)};
        color: {C["a_hot"]};
        border: 1px solid {C["ember"]};
    }}
    QPushButton#primaryButton:hover {{
        background-color: {rgba("ember", 0.3)};
        color: {C["a_bright"]};
    }}
    QPushButton#primaryButton:disabled {{
        background-color: transparent;
        color: {C["a_dim"]};
        border-color: {C["border"]};
    }}

    QPushButton#dangerButton {{
        color: {C["led_red"]};
        border: 1px solid {C["led_red_dim"]};
        background-color: {rgba("led_red_dim", 0.4)};
    }}
    QPushButton#dangerButton:hover {{
        background-color: {rgba("led_red", 0.22)};
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
        background-color: {rgba("bg_hover", 0.6)};
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
        background-color: {rgba("bg_inset", 0.92)};
        border: 1px solid {C["border_warm"]};
        border-radius: 4px;
        padding: 10px 13px;
        color: {C["a_bright"]};
        font-family: {MONO};
        font-size: 13px;
        selection-background-color: {C["ember_dim"]};
        selection-color: {C["a_bright"]};
    }}
    QTextEdit#chatInput:focus {{ border-color: {C["ember"]}; }}

    QLineEdit {{
        background-color: {rgba("bg_inset", 0.92)};
        border: 1px solid {C["border"]};
        border-radius: 3px;
        padding: 6px 9px;
        color: {C["a_bright"]};
        font-family: {MONO};
        font-size: 12px;
        selection-background-color: {C["ember_dim"]};
        selection-color: {C["a_bright"]};
    }}
    QLineEdit:focus {{ border-color: {C["ember"]}; }}
    QLineEdit:disabled {{ color: {C["a_dim"]}; }}

    /* ── COMBO / SPIN ──────────────────────────────────────────── */
    QComboBox {{
        background-color: {rgba("bg_inset", 0.92)};
        border: 1px solid {C["border"]};
        border-radius: 3px;
        padding: 6px 9px;
        color: {C["a_bright"]};
        font-family: {MONO};
        font-size: 12px;
    }}
    QComboBox:hover {{ border-color: {C["border_warm"]}; }}
    QComboBox:focus {{ border-color: {C["ember"]}; }}
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
        border: 1px solid {C["border_warm"]};
        border-radius: 3px;
        color: {C["a_mid"]};
        selection-background-color: {rgba("ember", 0.24)};
        selection-color: {C["a_bright"]};
        outline: none;
        padding: 3px;
    }}

    QSpinBox, QDoubleSpinBox {{
        background-color: {rgba("bg_inset", 0.92)};
        border: 1px solid {C["border"]};
        border-radius: 3px;
        padding: 6px 9px;
        color: {C["a_bright"]};
        font-family: {MONO};
        font-size: 12px;
    }}
    QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {C["ember"]}; }}
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
        color: {C["a_bright"]};
        font-size: 19px;
        font-weight: 700;
        letter-spacing: 3px;
    }}
    QLabel#brandSub {{
        color: {C["ember"]};
        font-size: 11px;
        letter-spacing: 4px;
    }}
    QLabel#sectionRule {{
        color: {C["a_muted"]};
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 3px;
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
        color: {C["a_bright"]};
        font-size: 21px;
        font-weight: 700;
        letter-spacing: 3px;
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
        background-color: {rgba("bg_inset", 0.45)};
        border: 1px solid {C["border"]};
        border-radius: 3px;
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
        letter-spacing: 3px;
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
                       f" background-color: {rgba('led_green', 0.10)};"
                       f" border: 1px solid {C['led_green_dim']};")
    if status == "loading":
        return base + (f"color: {C['led_amber']};"
                       f" background-color: {rgba('led_amber', 0.10)};"
                       f" border: 1px solid {C['led_amber_dim']};")
    return base + (f"color: {C['led_red']};"
                   f" background-color: {rgba('led_red', 0.10)};"
                   f" border: 1px solid {C['led_red_dim']};")


# ─── Chat turn styling ────────────────────────────────────────────────────────

def get_chat_line_style(role: str) -> str:
    """
    Chat turns are readout blocks with a lit left rule — steel for the operator
    (you), visor-orange for the machine.
    """
    C = COLORS
    if role == "user":
        return (
            f"background-color: {rgba('bg_inset', 0.55)};"
            f" border: 1px solid {C['border']};"
            f" border-left: 3px solid {C['a_muted']};"
            f" border-radius: 3px;"
            f" padding: 9px 13px;"
            f" margin: 0px;"
        )
    return (
        f"background-color: {rgba('bg_panel', 0.55)};"
        f" border: 1px solid {C['border']};"
        f" border-left: 3px solid {C['ember']};"
        f" border-radius: 3px;"
        f" padding: 9px 13px;"
        f" margin: 0px;"
    )
