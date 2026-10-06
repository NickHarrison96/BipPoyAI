# Quick Start Guide

## Before You Begin

1. **Python 3.11+** installed and added to PATH (https://python.org)
2. **Ollama** installed and running (`ollama serve`) — https://ollama.com
3. **Model Weights** — Place `Qwen3.5-9B-Heretic-patched2.gguf` in the `Models/` directory

---

## Option 1: Desktop GUI

1. Double-click **`launch.bat`** (or run `python main.py` in your terminal).
2. The standalone Cayde 420 chat window will open.
3. If LiteLLM proxy isn't started yet, click **"Start LiteLLM"** in the top warning banner.
4. Type your prompt and chat!

---

## Option 2: Claude CLI (Terminal)

1. Double-click **`setup.bat`** (or run `python setup.py` in your terminal).
2. The setup script will:
   - Detect your `.gguf` file
   - Configure `Modelfile` and `config.yaml` based on detected hardware
   - Build the model in Ollama (`ollama create`)
   - Start the local LiteLLM proxy on port 4000
   - Launch `claude` (no --model flag; ANTHROPIC_MODEL is set automatically)
3. Chat directly from your command line with Claude CLI talking to your offline Ollama model!

---

## Option 3: OpenCode (Terminal)

Run `python opencode_bridge.py --launch` (or click **⬡ OpenCode** in the GUI header) to merge a local provider into OpenCode's config and start it against the same LiteLLM proxy.

---

## Command Reference

| Goal | Command |
|---|---|
| Launch Desktop GUI | `launch.bat` or `python main.py` |
| Interactive Setup Wizard | `setup.bat` or `python setup.py` |
| Automated Setup (no prompts) | `python setup.py --auto` |
| Build Ollama Model Only | `python setup.py --build` |
| Start LiteLLM Proxy Only | `python setup.py --proxy` |
| Terminal Hardware Tuning TUI | `python config.py` |
| Auto-tune Hardware Settings | `python config.py --auto` |
| Show Current Hardware & Config | `python config.py --show` |
| Launch OpenCode on the local model | `python opencode_bridge.py --launch` |
| Grant `claude` access to a directory | `python mcp_server.py --grant "C:\path\to\project"` |

---

## Troubleshooting

- **Python not found**: Ensure Python is added to your system PATH.
- **Ollama CLI not found**: Make sure Ollama is installed from https://ollama.com and running.
- **Dependencies missing**: Run `pip install -r requirements.txt`.
