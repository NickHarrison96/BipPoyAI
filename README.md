# Qwythos-9B Claude Model — Local Windows Setup

This folder contains everything you need to run the Qwythos-9B Claude model locally on Windows, using Ollama and LiteLLM to route it to the Claude CLI.

## What you get

- An interactive config tool (`config.py`) to tune context size, GPU offload, CPU threads, batch size, and temperature
- An automation script (`setup.py`) that builds the Ollama model and launches the LiteLLM proxy
- A generated Modelfile and config.yaml ready for Ollama

## Prerequisites
- `Qwythos-9B-Claude-Mythos-5-1M-MTP-Q4_K_M.gguf` — the model weights (about 5.8 GB) huggingface DL: https://huggingface.co/empero-ai/Qwythos-9B-Claude-Mythos-5-1M
- Windows 10/11 (64-bit)
- Python 3.11+ installed (add Python to your PATH if you haven't)
- Ollama installed and running (`ollama serve`) — download from https://ollama.com
- Claude CLI installed (`pip install claude-code` or use the official installer)
- At least 8 GB RAM recommended; more is better for GPU offload

## Quick start (for non-technical users)

1. Open **Command Prompt** (search "cmd" in Start, right-click → Run as administrator)
2. Navigate to this folder: `cd "C:\Users\nick\Desktop\Models\Qwythos-9B-Claude-Mythos\Qwythos-9B-Claude-Mythos-5-1M-MTP-Q4_K_M"`
3. Run the setup batch file: `setup.bat`
4. Wait for the prompts — just press Enter to accept defaults
5. When it finishes, you'll see a message that the model is ready
6. Open a new Command Prompt and run: `claude --model qwythos-9b-claude-mythos-5-1m-mtp-q4_k_m`

That's it — you can now chat with the model locally.

## What each file does


- `config.py` — interactive tool to pick the GGUF file, set hardware limits, and generate `Modelfile` + `config.yaml`
- `config.yaml` — LiteLLM proxy configuration (model name, Ollama endpoint, context size)
- `setup.py` — automation script that detects the GGUF, optionally creates a model-named folder, builds a Modelfile, runs `ollama create`, spins up the LiteLLM proxy, then launches the Claude CLI through it
- `Modelfile` — Ollama model definition — FROM the GGUF, with default context 65536 and temperature 0.2
- `litellm.log` — log output from a previous run (likely from `setup.py` or `config.py`)

## Customizing hardware settings

If you want to tweak context size, GPU offload, CPU threads, batch size, or temperature, run `config.py` interactively. It will prompt you for each setting and then rebuild `Modelfile` and `config.yaml` with your choices.

## Troubleshooting

- If `setup.bat` fails with "Ollama CLI not found", make sure Ollama is installed and added to your system PATH
- If the model doesn't load, check that the GGUF file is not corrupted (try re-downloading)
- For GPU acceleration, ensure your GPU is supported by Ollama (NVIDIA CUDA, AMD ROCm, or Apple Silicon)
