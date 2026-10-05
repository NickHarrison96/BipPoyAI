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
  ← hosts the GGUF model (Qwythos-9B-Claude-Mythos-5-1M-MTP-Q4_K_M)
        │
        ▼
  Qwythos-9B.gguf  (≈5.8 GB, local file)
```

## Features

- **Pip-Boy Aesthetic Desktop GUI**: Standalone PySide6 app with CRT scanlines, cracked glass backdrop, LED indicators, and hardware dials.
- **Claude CLI Offline Spoofing**: Directs `claude` CLI requests through a local LiteLLM proxy into Ollama with zero internet connection needed.
- **Automated Hardware Profiling**: Real-time detection of CPU threads, RAM, and GPU VRAM with tailored context and offloading recommendations.
- **Flexible Tuning**: Tune context size, GPU layer offloading, thread count, batch size, and temperature via the GUI settings panel or terminal TUI.

---

## Prerequisites

- **Python 3.11+** (ensure "Add python.exe to PATH" is checked)
- **Ollama** installed and running (`ollama serve`) — https://ollama.com
- **Model weights**: `Qwythos-9B-Claude-Mythos-5-1M-MTP-Q4_K_M.gguf` (approx 5.8 GB)
  Download: https://huggingface.co/empero-ai/Qwythos-9B-Claude-Mythos-5-1M
- *(Optional)* **Claude CLI**: `npm install -g @anthropic-ai/claude-code`

---

## Quick Start

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
| `settings.py` | Persistent user connection endpoints (`~/.qwythos/settings.json`) |
| `hardware.py` | CPU/RAM/GPU detection and automatic tuning recommendations |
| `config.py` | Terminal hardware tuning TUI (`--auto`, `--show` flags supported) |
| `setup.py` | End-to-end setup and launch automation script |
| `launch.bat` | Double-click launcher for the desktop GUI |
| `setup.bat` | Double-click launcher for setup and CLI stack |

---

## Script Options & Commands

```powershell
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
```
