#!/usr/bin/env python3
"""
End-to-end installer and runner: GGUF → Ollama → LiteLLM → Claude CLI.

Uses configs.py + settings.py so hardware tuning and connection settings
survive repeated runs without clobbering existing configuration.
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

if sys.version_info < (3, 11):
    print("ERROR: Python 3.11 or newer is required.")
    print(f"You are running Python {sys.version.split()[0]}.")
    print("Download the latest version from https://python.org")
    sys.exit(1)

import configs
import hardware
import memory_vault
import netutil
import settings


C_HEADER = "\033[95m"
C_CYAN   = "\033[96m"
C_GREEN  = "\033[92m"
C_YELLOW = "\033[93m"
C_RED    = "\033[91m"
C_GRAY   = "\033[90m"
C_RESET  = "\033[0m"

# Enable ANSI on Windows cmd (safe: static literal, no user input).
if os.name == "nt":
    os.system("")


def log(prefix: str, color: str, msg: str):
    print(f"{color}[{prefix}] {msg}{C_RESET}")


def verbose(m):  log("VERBOSE", C_CYAN,  m)
def success(m):  log("SUCCESS", C_GREEN, m)
def warn(m):     log("WARN",    C_YELLOW, m)
def error(m):    log("ERROR",   C_RED,   m)


def ask(msg: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    try:
        ans = input(f"\n{C_YELLOW}[?] {msg} ({hint}): {C_RESET}").strip().lower()
        if not ans:
            return default
        return ans in ("y", "yes")
    except (KeyboardInterrupt, EOFError):
        print()
        return False


def die(code: int = 0, pause: bool = True):
    if pause and sys.stdin.isatty():
        print(f"\n{C_GRAY}[!] Press Enter to close...{C_RESET}")
        try:
            input()
        except (KeyboardInterrupt, EOFError):
            pass
    sys.exit(code)


# ─── Stages ───────────────────────────────────────────────────────────────────

def download_gguf(working_dir: Path, url: str, filename: str) -> bool:
    """Download a GGUF file with a progress bar."""
    import requests

    dest = working_dir / filename
    if dest.exists():
        verbose(f"GGUF already exists: {filename}")
        return True

    print(f"\nDownloading {filename}...")
    print(f"URL: {url}")
    print("This is a large file. Please wait...\n")

    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()

        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        chunk_size = 8192

        with open(dest, 'wb') as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        mb = downloaded / (1024 * 1024)
                        total_mb = total_size / (1024 * 1024)
                        print(f"\r  {mb:.1f}/{total_mb:.1f} MB ({percent:.1f}%)", end='', flush=True)

        print(f"\n\nDownload complete: {filename}")
        return True

    except Exception as e:
        error(f"Download failed: {e}")
        if dest.exists():
            dest.unlink()
        return False


def stage_detect_gguf(working_dir: Path, auto: bool = False, requested_name: Optional[str] = None) -> Path:
    print(f"{C_HEADER}=== STAGE 1: GGUF File Check ==={C_RESET}")
    models_dir = working_dir / "Models"
    ggufs = list(models_dir.glob("*.gguf")) if models_dir.exists() else []
    if not ggufs:
        existing = configs.load_full(working_dir)
        if existing.selected_gguf:
            warn(f"No .gguf files currently in {models_dir}.")
            warn(f"Using previously configured model reference: {existing.selected_gguf}")
            # selected_gguf may already carry a "Models/" prefix; use the bare
            # filename so this does not resolve to Models/Models/<name>.gguf.
            return models_dir / Path(existing.selected_gguf).name
        error(f"No .gguf files in {models_dir}")
        error("Download the model weights first (e.g. Qwen3.5-9B-Heretic-patched2.gguf).")
        if auto or ask("Download the model now?", default=True):
            url = "https://huggingface.co/empero-ai/Qwythos-9B-Claude-Mythos-5-1M/resolve/main/Qwythos-9B-Claude-Mythos-5-1M-MTP-Q4_K_M.gguf"
            filename = "Qwythos-9B-Claude-Mythos-5-1M-MTP-Q4_K_M.gguf"
            if download_gguf(models_dir, url, filename):
                ggufs = list(models_dir.glob("*.gguf"))
                if ggufs:
                    success(f"Downloaded: {ggufs[0].name}")
                    warn("Run 'python tools/gguf_guards.py' to patch the chat template before first use.")
                    return ggufs[0]
        die(1, pause=not auto)

    if requested_name:
        for f in ggufs:
            if requested_name.lower() in f.name.lower():
                verbose(f"Matched GGUF: {f.name}")
                return f

    if len(ggufs) > 1:
        if auto:
            target = ggufs[0]
            verbose(f"Auto-selected first GGUF: {target.name}")
            return target

        verbose("Multiple GGUF files detected:")
        for i, f in enumerate(ggufs):
            print(f"  [{i}] {f.name}")
        sel = input(f"Select index (0-{len(ggufs)-1}): ").strip()
        if not sel.isdigit() or int(sel) >= len(ggufs):
            error("Invalid selection.")
            die(1, pause=not auto)
        target = ggufs[int(sel)]
    else:
        target = ggufs[0]

    verbose(f"Selected: {target.name}")
    return target


def stage_write_configs(working_dir: Path, gguf: Path, auto: bool = False) -> configs.ModelConfig:
    """Merge on-disk config + hardware recommendations, then write both files."""
    print(f"\n{C_HEADER}=== STAGE 2: Modelfile + config.yaml ==={C_RESET}")

    existing = configs.load_full(working_dir)
    # If nothing on disk yet, seed from hardware recommendations
    if not (working_dir / "Modelfile").exists():
        r = hardware.detect().recommendations
        existing = existing.with_updates(
            context_size=r.context_size,
            gpu_layers=r.gpu_layers,
            cpu_threads=r.cpu_threads,
            batch_size=r.batch_size,
            engine_mode=r.engine_mode,
        )

    cfg = existing.with_updates(
        selected_gguf=f"Models/{gguf.name}",
        model_tag=existing.model_tag or configs.derive_model_tag(gguf.name),
    )

    print(f"  gguf         = {cfg.selected_gguf}")
    print(f"  tag          = {cfg.model_tag}")
    print(f"  engine_mode  = {cfg.engine_mode}")
    print(f"  context_size = {cfg.context_size}")
    print(f"  gpu_layers   = {cfg.gpu_layers}")
    print(f"  cpu_threads  = {cfg.cpu_threads}")
    print(f"  batch_size   = {cfg.batch_size}")
    print(f"  temperature  = {cfg.temperature}")
    print(f"  ollama_url   = {cfg.ollama_base_url}")
    print(f"  litellm_url  = {cfg.litellm_url}")

    if auto or ask("Write Modelfile + config.yaml with these values?", default=True):
        configs.write_all(cfg, working_dir)
        success("Wrote Modelfile.")
        success("Wrote config.yaml.")
    else:
        verbose("Skipped writing configs.")

    return cfg


def stage_build_ollama(working_dir: Path, cfg: configs.ModelConfig, auto: bool = False):
    print(f"\n{C_HEADER}=== STAGE 3: Ollama Model Build ==={C_RESET}")

    if not auto and not ask(f"Run 'ollama create {cfg.model_tag}'?", default=True):
        verbose("Skipped Ollama build.")
        return

    if not shutil.which("ollama"):
        error("Ollama CLI not in PATH. Install from https://ollama.com")
        die(1, pause=not auto)

    # Parse the FROM source in the Modelfile; if it's a local file, it must exist.
    modelfile_path = working_dir / "Modelfile"
    if modelfile_path.exists():
        from_line = next(
            (l for l in modelfile_path.read_text(encoding="utf-8", errors="replace").splitlines()
             if l.strip().upper().startswith("FROM ")), ""
        )
        from_src = from_line[5:].strip() if from_line else ""
        # A .gguf FROM is always a local file unless it carries a URL scheme.
        # Older logic keyed off a leading '.' or '/' and skipped everything
        # containing ':', which silently excluded every absolute Windows path --
        # the exact form configs.modelfile_from_path now emits -- from these
        # checks.
        if from_src.lower().endswith(".gguf") and "://" not in from_src:
            src_path = Path(from_src)
            if not src_path.is_absolute():
                src_path = (working_dir / from_src).resolve()
            if not src_path.exists():
                error(f"Modelfile FROM source not found: {from_src}")
                error("Ollama 0.34+ returns a misleading 'invalid model name' error for missing files.")
                error("Place the .gguf file in the project directory, or edit Modelfile to point at a valid source.")
                die(1, pause=not auto)
            else:
                # A chat template with live raise_exception guards will abort
                # mid-conversation (HTTP 500) on tool-result turns, which reads
                # as a proxy fault rather than a model fault. Catch it at build
                # time instead of at 3am.
                try:
                    sys.path.insert(0, str(working_dir / "tools"))
                    import gguf_guards
                    live = sum(
                        1 for _, line in gguf_guards.iter_guards(src_path)
                        if not line.startswith("{#")
                    )
                except Exception as e:
                    warn(f"Could not inspect chat template guards ({e}); continuing.")
                    live = 0
                if live:
                    error(f"{src_path.name} has {live} live raise_exception guard(s) in its chat template.")
                    error("These abort rendering on some message shapes (notably tool results),")
                    error("which surfaces as: 500 ... Ollama_chatException ... CallExpression")
                    error("")
                    error(f"  python tools/gguf_guards.py \"{src_path}\" --patch \"{src_path.stem}-patched.gguf\"")
                    error("then point the Modelfile FROM at the patched copy.")
                    die(1, pause=not auto)

    # If the tag already exists in Ollama, offer to skip the rebuild.
    if not auto:
        existing = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if cfg.model_tag in existing.stdout:
            if not ask(f"Model '{cfg.model_tag}' already exists in Ollama. Rebuild it?", default=False):
                success(f"'{cfg.model_tag}' already registered — skipping build.")
                return

    verbose(f"ollama create {cfg.model_tag} -f ./Modelfile")
    proc = subprocess.run(
        ["ollama", "create", cfg.model_tag, "-f", "./Modelfile"],
        cwd=str(working_dir),
    )
    if proc.returncode != 0:
        error(f"ollama create failed (exit {proc.returncode})")
        die(1, pause=not auto)
    success(f"Registered '{cfg.model_tag}' with Ollama.")


def is_litellm_running(url: str) -> bool:
    """Check if LiteLLM proxy is alive (fast liveness probe, deep /health fallback)."""
    return netutil.litellm_healthy(url)


def start_litellm_proxy(working_dir: Path, cfg: configs.ModelConfig) -> bool:
    """Start LiteLLM proxy if not already running."""
    port = urlparse(cfg.litellm_url).port or 4000

    if is_litellm_running(cfg.litellm_url):
        success(f"LiteLLM proxy is already running at {cfg.litellm_url}")
        return True

    # Port busy but /health failing: LiteLLM 1.102+ would silently fall back
    # to a RANDOM port if we spawned anyway. Poll in case a previous instance
    # is still booting; if it never answers, report the conflict instead.
    if netutil.port_in_use(port):
        verbose(f"Port {port} is in use - polling for an existing instance (60s)...")
        for _ in range(30):
            time.sleep(2)
            if is_litellm_running(cfg.litellm_url):
                success(f"LiteLLM proxy is already running at {cfg.litellm_url}")
                return True
        pid = netutil.pid_on_port(port)
        error(f"Port {port} is occupied by PID {pid or 'unknown'} but not answering /health.")
        error("Starting LiteLLM now would silently move it to a random port.")
        if pid:
            error(f"Kill it first:  taskkill /PID {pid} /F")
        else:
            error(f"Find the holder:  netstat -ano | findstr :{port}")
        return False

    if not (working_dir / "config.yaml").exists():
        error("config.yaml missing. Generating config first...")
        configs.write_config_yaml(cfg, working_dir / "config.yaml")

    if not shutil.which("litellm"):
        error("LiteLLM CLI not in PATH. Run: pip install litellm")
        return False

    host = urlparse(cfg.litellm_url).hostname or "127.0.0.1"
    verbose(f"Spawning LiteLLM proxy on {host}:{port}...")
    cmd = ["litellm", "--config", str(working_dir / "config.yaml"),
           "--host", host, "--port", str(port)]
    # Force UTF-8 so LiteLLM's box-drawing startup banner cannot raise
    # UnicodeEncodeError on a cp437/cp1252 console and kill the proxy.
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    silent = settings.is_true(settings.load().get("launch_silent"))
    if os.name == "nt":
        flags = subprocess.CREATE_NO_WINDOW if silent else subprocess.CREATE_NEW_CONSOLE
        subprocess.Popen(cmd, cwd=str(working_dir), env=env,
                         creationflags=flags)
    else:
        subprocess.Popen(cmd, cwd=str(working_dir), env=env)

    verbose("Waiting for LiteLLM to initialize...")
    for _ in range(45):
        time.sleep(2)
        if is_litellm_running(cfg.litellm_url):
            success(f"LiteLLM proxy is live at {cfg.litellm_url}")
            return True

    # Diagnose the failure instead of continuing silently.
    pid = netutil.pid_on_port(port)
    if pid is None:
        error(f"Port {port} was never bound - LiteLLM likely fell back to a random port")
        error(f"(another process grabbed {port} during startup) or crashed.")
        error("Check the LiteLLM console window for the port it actually bound.")
    else:
        error(f"LiteLLM bound port {port} (PID {pid}) but /health did not answer within 90s.")
        error("Check the LiteLLM console window for errors.")
    return False


def stage_launch_stack(working_dir: Path, cfg: configs.ModelConfig, auto: bool = False, launch_claude: bool = True):
    print(f"\n{C_HEADER}=== STAGE 4: LiteLLM Proxy + Claude CLI ==={C_RESET}")

    if not auto and not ask("Spin up LiteLLM Proxy and launch Claude CLI?", default=True):
        verbose("Skipped launcher.")
        return

    if not start_litellm_proxy(working_dir, cfg):
        error("LiteLLM proxy is not available - skipping Claude CLI launch.")
        return

    # Set Anthropic spoofing environment variables for Claude CLI
    os.environ["ANTHROPIC_BASE_URL"] = cfg.litellm_url
    os.environ["ANTHROPIC_AUTH_TOKEN"] = "sk-litellm-local"
    os.environ["ANTHROPIC_API_KEY"] = ""
    os.environ["CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS"] = "1"
    os.environ["ANTHROPIC_MODEL"] = cfg.model_tag

    if not launch_claude:
        return

    if not shutil.which("claude"):
        warn("Claude CLI ('claude') not found in PATH.")
        warn("To chat with the model via CLI, install Claude Code:")
        warn("    npm install -g @anthropic-ai/claude-code")
        warn("Or start the desktop GUI:")
        warn("    python main.py  (or launch.bat)")
        return

    success(f"Launching Claude CLI with model: {cfg.model_tag}")
    # No --model flag: Claude Code validates model names against its own known
    # list and stalls on local Ollama tags. ANTHROPIC_MODEL (set above) selects
    # the model and config.yaml routes that exact tag.
    #
    # The memory vault is appended as a file, not an inline string: the block can
    # be ~10k characters, which would overflow the Windows command line and need
    # a layer of shell quoting. An empty vault writes nothing and the flag is
    # omitted entirely.
    claude_cmd = ["claude"]
    block_file = memory_vault.write_block_file(memory_vault.build_block())
    if block_file:
        claude_cmd += ["--append-system-prompt-file", str(block_file)]
        success(f"Memory vault attached ({len(block_file.read_text(encoding='utf-8'))} chars)")
    subprocess.run(claude_cmd)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Cayde 420 — Setup & Launch Automation",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--auto", "-y",
        action="store_true",
        help="Run setup non-interactively using detected hardware recommendations",
    )
    parser.add_argument(
        "--config-only",
        action="store_true",
        help="Generate Modelfile and config.yaml only, without building or running",
    )
    parser.add_argument(
        "--build",
        action="store_true",
        help="Build the Ollama model from Modelfile and exit",
    )
    parser.add_argument(
        "--proxy",
        action="store_true",
        help="Start LiteLLM proxy and exit",
    )
    parser.add_argument(
        "--claude",
        action="store_true",
        help="Ensure LiteLLM is running, set env vars, and launch Claude CLI",
    )
    parser.add_argument(
        "--no-pause",
        action="store_true",
        help="Do not pause on exit",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    working_dir = Path(__file__).parent.resolve()
    auto = args.auto
    pause = not (auto or args.no_pause)

    try:
        # If running a single target action and configs already exist, load directly without prompting
        if (args.proxy or args.claude) and (working_dir / "config.yaml").exists():
            cfg = configs.load_full(working_dir)
        else:
            gguf = stage_detect_gguf(working_dir, auto=auto)
            cfg = stage_write_configs(working_dir, gguf, auto=auto)

        if args.config_only:
            success("Config generation complete.")
            die(0, pause=pause)

        if args.build:
            stage_build_ollama(working_dir, cfg, auto=True)
            die(0, pause=pause)

        if args.proxy:
            start_litellm_proxy(working_dir, cfg)
            die(0, pause=pause)

        if args.claude:
            stage_launch_stack(working_dir, cfg, auto=True, launch_claude=True)
            die(0, pause=pause)

        # Full end-to-end wizard flow
        stage_build_ollama(working_dir, cfg, auto=auto)
        stage_launch_stack(working_dir, cfg, auto=auto, launch_claude=True)
        die(0, pause=pause)

    except SystemExit:
        raise
    except Exception as e:
        error(f"Unexpected failure: {e}")
        die(1, pause=pause)


if __name__ == "__main__":
    main()
