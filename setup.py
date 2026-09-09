#!/usr/bin/env python3
"""
End-to-end installer: GGUF → Ollama → LiteLLM → Claude CLI.

Uses configs.py so hardware tuning survives repeated runs — no more clobbering
whatever config.py wrote with a bare-bones template.
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import configs
import hardware


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


def ask(msg: str) -> bool:
    try:
        return input(f"\n{C_YELLOW}[?] {msg} (Y/N): {C_RESET}").strip().lower() in ("y", "yes")
    except (KeyboardInterrupt, EOFError):
        print()
        return False


def die(code: int = 0):
    print(f"\n{C_GRAY}[!] Press Enter to close...{C_RESET}")
    try:
        input()
    except (KeyboardInterrupt, EOFError):
        pass
    sys.exit(code)


# ─── Stages ───────────────────────────────────────────────────────────────────

def stage_detect_gguf(working_dir: Path) -> Path:
    print(f"{C_HEADER}=== STAGE 1: GGUF File Check ==={C_RESET}")
    ggufs = list(working_dir.glob("*.gguf"))
    if not ggufs:
        error(f"No .gguf files in {working_dir}")
        die(1)

    if len(ggufs) > 1:
        verbose("Multiple GGUF files detected:")
        for i, f in enumerate(ggufs):
            print(f"  [{i}] {f.name}")
        sel = input(f"Select index (0-{len(ggufs)-1}): ").strip()
        if not sel.isdigit() or int(sel) >= len(ggufs):
            error("Invalid selection.")
            die(1)
        target = ggufs[int(sel)]
    else:
        target = ggufs[0]

    verbose(f"Selected: {target.name}")
    return target


def stage_write_configs(working_dir: Path, gguf: Path):
    """Merge on-disk config + hardware recommendations, then write both files.
    Skips the write if the user says no — but only after showing what would change."""
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
        selected_gguf=gguf.name,
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

    if ask("Write Modelfile + config.yaml with these values?"):
        configs.write_all(cfg, working_dir)
        success("Wrote Modelfile.")
        success("Wrote config.yaml.")
    else:
        verbose("Skipped writing configs.")

    return cfg


def stage_build_ollama(working_dir: Path, cfg: configs.ModelConfig):
    print(f"\n{C_HEADER}=== STAGE 3: Ollama Model Build ==={C_RESET}")

    if not ask(f"Run 'ollama create {cfg.model_tag}'?"):
        verbose("Skipped Ollama build.")
        return

    if not shutil.which("ollama"):
        error("Ollama CLI not in PATH. Install from https://ollama.com")
        die(1)

    verbose(f"ollama create {cfg.model_tag} -f ./Modelfile")
    proc = subprocess.run(
        ["ollama", "create", cfg.model_tag, "-f", "./Modelfile"],
        cwd=str(working_dir),
    )
    if proc.returncode != 0:
        error(f"ollama create failed (exit {proc.returncode})")
        die(1)
    success(f"Registered '{cfg.model_tag}' with Ollama.")


def stage_launch_stack(working_dir: Path, cfg: configs.ModelConfig):
    print(f"\n{C_HEADER}=== STAGE 4: LiteLLM Proxy + Claude CLI ==={C_RESET}")

    if not ask("Spin up LiteLLM Proxy and launch Claude CLI?"):
        verbose("Skipped launcher.")
        return

    if not (working_dir / "config.yaml").exists():
        error("config.yaml missing. Run stage 2 or config.py first.")
        die(1)
    if not shutil.which("litellm"):
        error("LiteLLM CLI not in PATH. Run: pip install litellm")
        die(1)

    verbose("Spawning LiteLLM proxy on port 4000...")
    cmd = ["litellm", "--config", str(working_dir / "config.yaml"), "--port", "4000"]
    if os.name == "nt":
        subprocess.Popen(cmd, cwd=str(working_dir),
                         creationflags=subprocess.CREATE_NEW_CONSOLE)
    else:
        subprocess.Popen(cmd, cwd=str(working_dir))

    time.sleep(3)

    os.environ["ANTHROPIC_BASE_URL"] = cfg.litellm_url
    os.environ["ANTHROPIC_AUTH_TOKEN"] = "ollama"
    os.environ["ANTHROPIC_API_KEY"] = cfg.litellm_api_key
    success(f"LiteLLM running at {cfg.litellm_url}")

    if not shutil.which("claude"):
        error("Claude CLI not in PATH.")
        die(1)
    subprocess.run(["claude", "--model", cfg.model_tag])


def main():
    try:
        working_dir = Path.cwd()
        gguf = stage_detect_gguf(working_dir)
        cfg = stage_write_configs(working_dir, gguf)
        stage_build_ollama(working_dir, cfg)
        stage_launch_stack(working_dir, cfg)
    except Exception as e:
        error("Unexpected failure:")
        print(f"{C_RED}{e}{C_RESET}")
        die(1)
    finally:
        die(0)


if __name__ == "__main__":
    main()
