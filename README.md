---

<img width="1920" height="1040" alt="image" src="https://github.com/user-attachments/assets/f6756fda-eb75-435c-a233-eca273b68775" />


---

# Qwythos AI (BipPoyAI) — Local Offline AI Assistant

A local-only desktop AI assistant for Windows running on top of Ollama and LiteLLM, featuring an amber/green Pip-Boy themed GUI and seamless routing to Anthropic's Claude CLI.

```
User (Claude CLI or GUI chat)
        │
        ▼
  LiteLLM Proxy  :4000
  ← spoofs the Anthropic API so `claude` CLI works offline without any internet
        │
        ▼
  Ollama  :11434
  ← hosts one or more GGUF models built from `Models/`
        │
        ▼
  Models/*.gguf  (user-populated; active model is `qwythos-heretic`)
```

## Features

- **Pip-Boy Aesthetic Desktop GUI**: Standalone PySide6 app with CRT scanlines, cracked glass backdrop, LED indicators, and hardware dials.
- **Claude CLI Offline Spoofing**: Directs `claude` CLI requests through a local LiteLLM proxy into Ollama with zero internet connection needed.
- **Automated Hardware Profiling**: Real-time detection of CPU threads, RAM, and GPU VRAM with tailored context and offloading recommendations.
- **Flexible Tuning**: Tune context size, GPU layer offloading, thread count, batch size, and temperature via the GUI settings panel or terminal TUI.
- **Multi-model management**: Drop multiple GGUFs into `Models/`, pick any one at runtime, and `setup.py` builds it into Ollama automatically.
- **Chat-template guard tooling**: `tools/gguf_guards.py` inspects and patches the `raise_exception` guards that make some models crash on tool-result turns, and validates GGUF integrity.

---

## Prerequisites

- **Python 3.11+** (ensure "Add python.exe to PATH" is checked)
- **Ollama** installed and running (`ollama serve`) — https://ollama.com
- **Model weights**: one or more GGUF models in `Models/`. The active model is
  `Qwen3.5-9B-Heretic-patched2.gguf` (~5.8 GB), built as the Ollama tag
  `qwythos-heretic`. Verify any model before use:
  `python tools/gguf_guards.py Models/<file>.gguf`
- *(Optional)* **Claude CLI**: `npm install -g @anthropic-ai/claude-code`

---

## Quick Start

### 0. First-time setup
Double-click **`check_and_install_deps.bat`** to verify Python 3.11+ and Ollama are
installed, install the Python packages, and open download pages for anything missing.

### 1. Launch the Desktop GUI
Simply double-click **`launch.bat`** (or run `python main.py`).

### 2. Run with Claude CLI
Double-click **`setup.bat`** (or run `python setup.py`). It will detect your GGUF, build the Ollama model, start the LiteLLM proxy, and launch the Claude CLI session.

---

## Core Files

| File | Purpose |
|---|---|
| `main.py` | PySide6 Desktop GUI chat application |
| `backend.py` | Health polling, streaming inference worker, process management |
| `styles.py` | Pip-Boy styling, color palette, custom QSS stylesheets |
| `widgets.py` | Custom QPainter CRT scanlines, LEDs, hardware strip, meters |
| `configs.py` | Central `ModelConfig` schema for Modelfile and config.yaml |
| `settings.py` | Persistent connection endpoints (`.state/settings.json`) |
| `model_registry.py` | Remembers external weight paths and per-model tuning (`.state/`) |
| `hardware.py` | CPU/RAM/GPU detection and automatic tuning recommendations |
| `config.py` | Terminal hardware tuning TUI (`--auto`, `--show` flags supported) |
| `setup.py` | End-to-end setup and launch automation script |
| `tools/gguf_guards.py` | Inspect/neutralise chat-template guards; validate GGUF integrity |
| `check_and_install_deps.bat` | Scans for Python/Ollama/npm, opens download pages for missing tools, installs `requirements.txt` |
| `launch.bat` | Double-click launcher for the desktop GUI |
| `setup.bat` | Double-click launcher for setup and CLI stack |

---

## Script Options & Commands

```powershell
# Check and install missing dependencies
check_and_install_deps.bat

# Install dependencies
pip install -r requirements.txt

# Start Desktop GUI
launch.bat
python main.py

# Interactive Setup & Claude CLI Launcher
setup.bat
python setup.py

# Automated setup with hardware recommendations
python setup.py --auto

# Start LiteLLM proxy only
python setup.py --proxy

# Build Ollama model only
python setup.py --build

# Hardware Tuning TUI
python config.py

# Auto-apply hardware recommendations to Modelfile & config.yaml
python config.py --auto

# Inspect detected hardware and active configuration
python config.py --show

# Inspect/repair a model's chat-template guards
python tools/gguf_guards.py Models/<file>.gguf
python tools/gguf_guards.py Models/<file>.gguf --patch Models/<file>-guarded.gguf
```
