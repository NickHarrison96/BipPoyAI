# Quick Start Guide — For Absolute Beginners

## Before you begin

1. **Make sure you have Python installed** — search "Python" in Start, install from python.org if needed
2. **Make sure you have Ollama installed** — download from https://ollama.com
3. **Make sure you have Claude CLI installed** — `pip install claude-code` or use the official installer

## Step-by-step

1. Open **Command Prompt** (search "cmd" in Start, right-click → Run as administrator)
2. Type: `cd "C:\Users\nick\Desktop\Models\Qwythos-9B-Claude-Mythos\Qwythos-9B-Claude-Mythos-5-1M-MTP-Q4_K_M"`
3. Type: `run_setup.bat`
4. Wait — you'll see progress messages. Press Enter when prompted.
5. Open a **new** Command Prompt
6. Type: `claude --model qwythos-9b-claude-mythos-5-1m-mtp-q4_k_m`
7. You're done — chat with the model!

## What to do if something goes wrong

- **run_setup.bat says "Python not found"** — install Python from python.org and restart Command Prompt
- **Ollama says "model already exists"** — that's fine, you can skip the Ollama build step
- **Claude CLI says "model not found"** — run `setup.bat` first to build the model in Ollama
