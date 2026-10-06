#!/usr/bin/env python3
"""
Interactive TUI for tuning the Modelfile + config.yaml.

All the actual logic (hardware probe, file I/O) lives in hardware.py and
configs.py so the GUI and CLI share the exact same schema.
"""

import argparse
import os
import sys
from pathlib import Path

import hardware
import configs
import settings

# ─── ANSI helpers ─────────────────────────────────────────────────────────────

C_HEADER = "\033[95m"
C_CYAN   = "\033[96m"
C_GREEN  = "\033[92m"
C_YELLOW = "\033[93m"
C_RED    = "\033[91m"
C_RESET  = "\033[0m"

# Both os.system calls below use static literals (no user input) — safe.
# `cls` is a cmd builtin on Windows, so subprocess.run(["cls"]) won't work.
if os.name == "nt":
    os.system("")  # enable ANSI on cmd


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def _engine_label(mode: str) -> str:
    return {
        "direct":           "Direct Ollama (Port 11434)",
        "litellm_standard": "LiteLLM Proxy — Standard (ollama/)",
        "litellm_chat":     "LiteLLM Proxy — Chat Mode (ollama_chat/)",
    }.get(mode, mode)


def print_hardware_summary(hw: hardware.HardwareReport):
    print(f"\n{C_HEADER}=== Hardware Detection ==={C_RESET}")
    print(f"CPU cores : {hw.cpu_cores}")
    print(f"RAM       : {hw.ram_gb:.1f} GB")
    if hw.gpu:
        print(f"GPU       : {hw.gpu.name} ({hw.gpu.total_vram_gb:.1f} GB VRAM)")
    else:
        print("GPU       : none detected")
    print(f"Ollama    : {'running' if hw.ollama_running else 'not detected'}\n")

    r = hw.recommendations
    print("Recommended Settings:")
    print(f"  context_size = {r.context_size}")
    print(f"  gpu_layers   = {r.gpu_layers}")
    print(f"  cpu_threads  = {r.cpu_threads}")
    print(f"  batch_size   = {r.batch_size}")
    print(f"  engine_mode  = {r.engine_mode}\n")


def auto_apply(working_dir: Path):
    hw = hardware.detect()
    cfg = configs.load_full(working_dir)
    r = hw.recommendations

    cfg = cfg.with_updates(
        context_size=r.context_size,
        gpu_layers=r.gpu_layers,
        cpu_threads=r.cpu_threads,
        batch_size=r.batch_size,
        engine_mode=r.engine_mode,
    )

    configs.write_all(cfg, working_dir)
    print(f"{C_GREEN}[OK] Applied hardware recommendations to Modelfile and config.yaml:{C_RESET}")
    print(f"     Context: {cfg.context_size}, GPU Layers: {cfg.gpu_layers}, CPU Threads: {cfg.cpu_threads}, Batch: {cfg.batch_size}")


def show_config(working_dir: Path):
    hw = hardware.detect()
    cfg = configs.load_full(working_dir)
    conn = settings.load()

    print_hardware_summary(hw)

    print(f"{C_HEADER}=== Current Configuration ==={C_RESET}")
    print(f"Target GGUF   : {cfg.selected_gguf or '(none)'}")
    print(f"Model Tag     : {cfg.model_tag or '(none)'}")
    print(f"Engine Mode   : {_engine_label(cfg.engine_mode)}")
    print(f"Context Size  : {cfg.context_size} tokens")
    print(f"GPU Layers    : {cfg.gpu_layers}")
    print(f"CPU Threads   : {cfg.cpu_threads}")
    print(f"Batch Size    : {cfg.batch_size}")
    print(f"Temperature   : {cfg.temperature}")
    print(f"Ollama URL    : {conn['ollama_base_url']}")
    print(f"LiteLLM URL   : {conn['litellm_base_url']}")


# ─── Main menu ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Cayde 420 Hardware Tuning TUI")
    parser.add_argument("--auto", "-a", action="store_true", help="Auto-detect hardware, apply recommendations, and save immediately")
    parser.add_argument("--show", action="store_true", help="Show current hardware and config without entering the interactive menu")
    args = parser.parse_args()

    working_dir = Path(__file__).parent.resolve()

    if args.auto:
        auto_apply(working_dir)
        return

    if args.show:
        show_config(working_dir)
        return

    ggufs = list(working_dir.glob("*.gguf"))
    hw = hardware.detect()
    cfg = configs.load_full(working_dir)

    # Fill in any unset fields from hardware recommendations if still on defaults
    if cfg.context_size == configs.ModelConfig().context_size and hw.recommendations.context_size != cfg.context_size:
        cfg = cfg.with_updates(context_size=hw.recommendations.context_size)

    while True:
        clear()
        print(f"{C_HEADER}====================================================={C_RESET}")
        print(f"{C_HEADER}  Local Claude Model Setup & Hardware Configurator{C_RESET}")
        print(f"{C_HEADER}====================================================={C_RESET}\n")

        print(f"1. Target GGUF File   : {C_CYAN}{cfg.selected_gguf or '(none)'}{C_RESET}")
        print(f"2. Model Nickname Tag : {C_CYAN}{cfg.model_tag or '(none)'}{C_RESET}")
        print(f"3. Connection Engine  : {C_YELLOW}[{_engine_label(cfg.engine_mode)}]{C_RESET}")
        print("-----------------------------------------------------")
        print("  HARDWARE & RESOURCE CONTROLS")
        print("-----------------------------------------------------")
        print(f"4. RAM Context Limit  : {C_CYAN}{cfg.context_size} tokens{C_RESET}")
        print(f"5. GPU Offload Layers : {C_CYAN}{cfg.gpu_layers} (99 = full VRAM offload){C_RESET}")
        print(f"6. CPU Core Threads   : {C_CYAN}{cfg.cpu_threads} threads{C_RESET}")
        print(f"7. VRAM Batch Size    : {C_CYAN}{cfg.batch_size} tokens{C_RESET}")
        print(f"8. Creativity (Temp)  : {C_CYAN}{cfg.temperature}{C_RESET}")
        print()
        print(f"R. Show hardware recommendations & apply")
        print(f"{C_GREEN}S. Save Settings & Rebuild Modelfile/config.yaml{C_RESET}")
        print(f"Q. Quit\n")

        try:
            choice = input("Select an option: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(0)

        if choice == "1":
            if not ggufs:
                input("No .gguf files in this folder. Press Enter.")
                continue
            print("\nAvailable GGUF Files:")
            for i, f in enumerate(ggufs):
                print(f"  [{i}] {f.name}")
            sel = input("Select index: ").strip()
            if sel.isdigit() and int(sel) < len(ggufs):
                new_gguf = ggufs[int(sel)].name
                cfg = cfg.with_updates(
                    selected_gguf=new_gguf,
                    model_tag=configs.derive_model_tag(new_gguf),
                )

        elif choice == "2":
            new_tag = input("\nEnter new model nickname tag: ").strip()
            if new_tag:
                cfg = cfg.with_updates(model_tag=configs.derive_model_tag(new_tag))

        elif choice == "3":
            print("\nSelect Connection Engine Mode:")
            print("  [1] Direct Ollama (Port 11434)")
            print("  [2] LiteLLM Proxy — Standard (ollama/)")
            print("  [3] LiteLLM Proxy — Chat Mode (ollama_chat/) [Recommended]")
            sel = input("Choice (1-3): ").strip()
            mode = {"1": "direct", "2": "litellm_standard", "3": "litellm_chat"}.get(sel)
            if mode:
                cfg = cfg.with_updates(engine_mode=mode)

        elif choice == "4":
            print("\nSelect Context Limit:")
            print("  [1] 8192    [2] 16384    [3] 32768    [4] 65536")
            m = {"1": 8192, "2": 16384, "3": 32768, "4": 65536}.get(input("Choice: ").strip())
            if m:
                cfg = cfg.with_updates(context_size=m)

        elif choice == "5":
            try:
                cfg = cfg.with_updates(gpu_layers=int(input("\nGPU layers (99 = max): ").strip()))
            except ValueError:
                pass

        elif choice == "6":
            try:
                cfg = cfg.with_updates(cpu_threads=int(input("\nCPU threads (e.g. 6): ").strip()))
            except ValueError:
                pass

        elif choice == "7":
            print("\nSelect Batch Size:  [1] 256   [2] 512   [3] 1024")
            m = {"1": 256, "2": 512, "3": 1024}.get(input("Choice: ").strip())
            if m:
                cfg = cfg.with_updates(batch_size=m)

        elif choice == "8":
            try:
                t = float(input("\nTemperature (0.0–2.0): ").strip())
                cfg = cfg.with_updates(temperature=max(0.0, min(2.0, t)))
            except ValueError:
                pass

        elif choice == "r":
            print_hardware_summary(hw)
            r = hw.recommendations
            if input("Apply? (y/n): ").strip().lower() == "y":
                cfg = cfg.with_updates(
                    context_size=r.context_size,
                    gpu_layers=r.gpu_layers,
                    cpu_threads=r.cpu_threads,
                    batch_size=r.batch_size,
                    engine_mode=r.engine_mode,
                )
                print(f"{C_GREEN}[OK] Applied.{C_RESET}")
                input("Press Enter.")

        elif choice == "s":
            print(f"\n{C_HEADER}=== Saving ==={C_RESET}")
            try:
                configs.write_all(cfg, working_dir)
                print(f"{C_GREEN}[OK] Modelfile updated.{C_RESET}")
                print(f"{C_GREEN}[OK] config.yaml updated.{C_RESET}")
            except ValueError as e:
                print(f"{C_RED}[ERROR] {e}{C_RESET}")
            input(f"\n{C_CYAN}Press Enter to exit...{C_RESET}")
            sys.exit(0)

        elif choice == "q":
            sys.exit(0)


if __name__ == "__main__":
    main()
