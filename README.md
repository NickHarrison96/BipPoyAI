---

<img width="1920" height="1040" alt="image" src="https://github.com/user-attachments/assets/f6756fda-eb75-435c-a233-eca273b68775" />


---

# Cayde 420 — Local Offline AI Assistant

A local-only desktop AI assistant for Windows running on top of Ollama and LiteLLM, featuring a bone-and-gunmetal themed GUI with visor-orange accents and seamless routing to Anthropic's Claude CLI.

```
User (Claude CLI, OpenCode, or GUI chat)
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

- **Bone-and-Gunmetal Desktop GUI**: Standalone PySide6 app with CRT scanlines, a panelled backdrop lit from the seams, LED indicators, and hardware dials.
- **Claude CLI Offline Spoofing**: Directs `claude` CLI requests through a local LiteLLM proxy into Ollama with zero internet connection needed.
- **OpenCode support**: `opencode_bridge.py` merges one local provider block into OpenCode's own config so it reaches the same model.
- **Persistent memory vault**: Markdown notes in `.state/memory/` are composed into the system prompt, so the model remembers things across sessions.
- **MCP workspace tools**: An MCP server gives the `claude` CLI file and command tools inside directories you have explicitly granted — nothing is granted by default.
- **Automated Hardware Profiling**: Real-time detection of CPU threads, RAM, and GPU VRAM with tailored context and offloading recommendations.
- **Flexible Tuning**: Tune context size, GPU layer offloading, thread count, batch size, and temperature via the GUI settings panel or terminal TUI.
- **Multi-model management**: Drop multiple GGUFs into `Models/`, pick any one at runtime, and `setup.py` builds it into Ollama automatically.
- **Dual-GPU support**: On systems with both NVIDIA and AMD GPUs, the Modelfile's `num_gpu 1` ensures the model loads on the NVIDIA GPU only (prevents VRAM issues on AMD RX 580).
- **Voice pipeline (STT)**: Optional microphone capture with Silero VAD + Whisper CPU transcription for hands-free interaction. Prefix prompts with `coding:`, `vision:`, or `default:` to route to specialized models.
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
- *(Optional)* **OpenCode**, if you want a third client on the same local model

---

## Quick Start

### 0. First-time setup
Double-click **`check_and_install_deps.bat`** to verify Python 3.11+ and Ollama are
installed, install the Python packages, and open download pages for anything missing.

### 1. Launch the Desktop GUI
Simply double-click **`launch.bat`** (or run `python main.py`).

### 2. Run with Claude CLI
Double-click **`setup.bat`** (or run `python setup.py`). It will detect your GGUF, build the Ollama model, start the LiteLLM proxy, and launch the Claude CLI session.

### 3. Run with OpenCode
Run `python opencode_bridge.py --launch`, or click **⬡ OpenCode** in the GUI header. LiteLLM must be running — it is what spoofs the Anthropic API for every client.

---

## Memory, MCP Tools & Clients

### Memory vault

Notes you want the model to keep between sessions live as one `*.md` file per
entry in `.state/memory/`. Every entry is concatenated and appended to the model
persona, so the model starts where you left off instead of blank. Edit them in
**Settings → Memory Vault**.

Composition is **additive**: an empty or disabled vault returns the persona
untouched, so a model that ships its own personality keeps it. Order is by entry
name, so the block is stable across launches and prompt caching still works.

The injected block is capped at **10,000 characters** (~2.5k tokens) out of the
32768 context window. Past the cap, entries are dropped **whole** — never sliced
mid-sentence — and the block says how many were left out, so the model knows its
memory is partial instead of quietly acting on a half-truth.

For the `claude` CLI the assembled block is written to `.state/memory_block.md`
and passed with `--append-system-prompt-file`, rather than squeezed through argv.

### MCP workspace server

`mcp_server.py` is a FastMCP server that gives the `claude` CLI tools for this
machine: list/search/read/write/edit files, run a command, plus always-safe
inspection tools (CPU/RAM/disk, installed Ollama models, the grant list).

**Nothing is granted by default.** Access is per directory, granted by hand:

```powershell
python mcp_server.py --list
python mcp_server.py --grant "C:\path\to\project"
python mcp_server.py --grant "C:\path\to\project" --read-only
python mcp_server.py --revoke "C:\path\to\project"
python mcp_server.py --register    # prints the `claude mcp add` line
python mcp_server.py --serve       # how `claude` launches it
```

Grants live in `.state/mcp_grants.json`, and each one names a directory plus
which capabilities it gets — `read`, `write`, and `shell` are separate, so a
read-only grant cannot be talked into a write or into running commands. Paths are
fully resolved (`..` and symlinks applied) *before* the containment test, so a
grant for `C:/proj` does not reach `C:/proj/../secrets` or a symlink pointing out
of the tree. Denials never confirm whether a path exists. Commands are killed
after 30s with output truncated, `read_file` refuses anything over 2 MB, and
`edit_file` refuses rather than guessing when the search text appears twice.

Registration is manual on purpose. `--register` only *prints* the `claude mcp add`
command; Cayde 420 never runs it for you, because it edits your Claude config and
persists for every future launch in this project. Remove it again with
`claude mcp remove cayde-workspace --scope local`.

> **The `shell` capability sets the command's working directory — it does not
> confine what the command can reach.** It is a `cwd` jail, not a sandbox, and
> there is no command allowlist. Grant `shell` only where that is acceptable, or
> edit `.state/mcp_grants.json` down to `["read"]`.

### OpenCode bridge

OpenCode speaks the Anthropic API too, so it reaches the same local model through
the same LiteLLM proxy. Its provider config is a JSON file OpenCode owns, so
`opencode_bridge.py` merges a single namespaced provider block (`cayde`) into
`~/.config/opencode/opencode.json` — the URL, key, model tag, and window sizes
all read from `config.yaml` rather than hardcoded. Every other provider, model,
and setting in that file is left alone, the previous version is copied to
`opencode.cayde-bak` first, and a config it cannot parse is refused rather than
overwritten.

```powershell
python opencode_bridge.py           # merge the provider block
python opencode_bridge.py --print   # show it without writing anything
python opencode_bridge.py --launch  # write, then start OpenCode
```

Re-running it is byte-identical when nothing has changed, and after switching
models the block picks the new tag up from `config.yaml`.

---

## Core Files

| File | Purpose |
|---|---|
| `main.py` | PySide6 Desktop GUI chat application |
| `backend.py` | Health polling, streaming inference worker, process management |
| `styles.py` | Theme palette (`COLORS`), `rgba()` tint helper, custom QSS stylesheets |
| `widgets.py` | Custom QPainter CRT scanlines, LEDs, hardware strip, meters |
| `configs.py` | Central `ModelConfig` schema for Modelfile and config.yaml |
| `settings.py` | Persistent connection endpoints (`.state/settings.json`) |
| `model_registry.py` | Remembers external weight paths and per-model tuning (`.state/`) |
| `hardware.py` | CPU/RAM/GPU detection and automatic tuning recommendations |
| `config.py` | Terminal hardware tuning TUI (`--auto`, `--show` flags supported) |
| `setup.py` | End-to-end setup and launch automation script |
| `memory_vault.py` | Persistent markdown memory under `.state/memory/`, composed into the system prompt |
| `mcp_grants.py` | Per-directory `read`/`write`/`shell` grants for the MCP server (`.state/mcp_grants.json`) |
| `mcp_server.py` | FastMCP workspace server — file and command tools inside granted directories |
| `opencode_bridge.py` | Merges a local LiteLLM provider into OpenCode's config, then launches it |
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

# Point OpenCode at the local stack
python opencode_bridge.py --print
python opencode_bridge.py --launch

# Manage the Claude CLI's MCP workspace access
python mcp_server.py --list
python mcp_server.py --grant "C:\path\to\project"
python mcp_server.py --register
```
