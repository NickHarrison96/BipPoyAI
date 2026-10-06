"""
Launch OpenCode against the local stack.

OpenCode and Claude Code both speak the Anthropic API, so both can be pointed at
LiteLLM on :4000 and reach the GGUF in Ollama with no internet. The only work is
telling OpenCode that the endpoint exists — its provider config is a JSON file it
owns, so this module writes one rather than mutating anything at launch.

Deliberately additive: it manages a single provider block named `cayde` inside
the user's existing config and leaves every other provider, model, and setting
alone. Rewriting their whole config to add one entry is how you lose an afternoon
to a merge conflict with yourself.

Run: python opencode_bridge.py            # write the config
     python opencode_bridge.py --print    # show what it would write
     python opencode_bridge.py --launch   # write, then start OpenCode
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import configs

# Provider id used inside opencode.json. Namespaced so it cannot collide with a
# provider the user already set up.
PROVIDER_ID = "cayde"

# OpenCode reads config from this directory (see `opencode debug paths`).
CONFIG_DIR = Path.home() / ".config" / "opencode"
CONFIG_FILE = CONFIG_DIR / "opencode.json"
BACKUP_SUFFIX = ".cayde-bak"

# Last-resort auth token, used only when settings.json has no LiteLLM key. Not a
# real credential — the proxy does not validate it today, and config.yaml has no
# auth provider configured. Prefer settings.load()["litellm_api_key"] so every
# client sends the same token.
LOCAL_TOKEN = "sk-litellm-local"


def with_api_version(url: str) -> str:
    """
    Ensure the LiteLLM URL ends in the /v1 API prefix.

    @ai-sdk/anthropic appends `/messages` to whatever baseURL it is given, so
    the base URL has to be the API root. LiteLLM serves `/v1/messages` and does
    NOT serve `/messages` — verified against a live proxy: the bare port returns
    404, which would have made every OpenCode request fail with no obvious
    connection error. This is the same shape OpenCode's own built-in Anthropic
    providers use (`https://opencode.ai/inference/anthropic/v1`).
    """
    cleaned = (url or "").rstrip("/")
    if not cleaned:
        return cleaned
    return cleaned if cleaned.endswith("/v1") else f"{cleaned}/v1"


def provider_block(model_tag: str, litellm_url: str, context: int = None,
                   output: int = None, api_key: str = None) -> dict:
    """
    The opencode.json provider entry that routes to LiteLLM.

    Uses @ai-sdk/anthropic rather than the OpenAI-compatible shim: OpenCode is
    an Anthropic-API client, and LiteLLM's /v1/messages is a faithful Anthropic
    surface. Going through the OpenAI shim would translate the request twice for
    no benefit.

    context, output and api_key all come from the live config rather than being
    pinned here. Both sizes are per-request values owned by config.yaml and tuned
    in Settings, so a block advertising a stale window tells OpenCode to truncate
    to a size the proxy is not actually serving; the token has to match the one
    every other client sends or the block only works until someone enables auth
    on the proxy. Defaults fall back to ModelConfig for direct callers that pass
    nothing, so no number is duplicated in this module.
    """
    defaults = configs.ModelConfig()
    return {
        "npm": "@ai-sdk/anthropic",
        "name": "Cayde 420 (local)",
        "options": {
            "baseURL": with_api_version(litellm_url),
            "apiKey": api_key or defaults.litellm_api_key or LOCAL_TOKEN,
        },
        "models": {
            model_tag: {
                "name": f"Cayde 420 — {model_tag}",
                "limit": {
                    "context": defaults.context_size if context is None else context,
                    "output": defaults.max_tokens if output is None else output,
                },
            }
        },
    }


def backup_path() -> Path:
    """Where write_config() leaves the pre-write copy of the config."""
    return CONFIG_FILE.with_suffix(BACKUP_SUFFIX)


def build_config(working_dir: Path) -> dict:
    """The full config to write: existing content plus our provider."""
    cfg = configs.load_full(working_dir)
    litellm_url = cfg.litellm_url or "http://127.0.0.1:4000"
    tag = cfg.model_tag or "local-model"

    doc = {}
    if CONFIG_FILE.exists():
        try:
            # utf-8-sig: a BOM is a Windows text-editor artefact, not corruption,
            # and refusing to read a perfectly good config over one would be
            # needlessly hostile. ValueError covers both JSONDecodeError and
            # UnicodeDecodeError, so undecodable bytes get the same clean refusal
            # as broken syntax instead of a traceback past the guard.
            doc = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            raise SystemExit(
                f"{CONFIG_FILE} could not be read as JSON ({exc}).\n"
                "Fix or move it by hand, then re-run — Cayde 420 will not "
                "overwrite a config it cannot read."
            )
        if not isinstance(doc, dict):
            raise SystemExit(f"{CONFIG_FILE} is not a JSON object.")

    providers = doc.setdefault("provider", {})
    if not isinstance(providers, dict):
        raise SystemExit(f"{CONFIG_FILE} has a non-object 'provider' key.")

    providers[PROVIDER_ID] = provider_block(
        tag, litellm_url,
        context=cfg.context_size,
        output=cfg.max_tokens,
        api_key=cfg.litellm_api_key,
    )
    return doc


def write_config(working_dir: Path) -> Path:
    """Merge our provider into the existing config, backing it up first."""
    doc = build_config(working_dir)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if CONFIG_FILE.exists():
        shutil.copy2(CONFIG_FILE, backup_path())

    # Written without the $schema key stripped — anything already there is kept.
    CONFIG_FILE.write_text(
        json.dumps(doc, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    return CONFIG_FILE


def _cmdline(cmd) -> str:
    """Render argv for `cmd /c start`, quoting anything with spaces.

    Without this an extra_arg like "my session" arrives as two arguments. cmd
    takes a bare string, so the quoting has to happen before the shell sees it.
    """
    return " ".join(f'"{a}"' if " " in str(a) else str(a) for a in cmd)


def launch(working_dir: Path, extra_args=None) -> int:
    """Start OpenCode in a new console, with the model preselected.

    Returns 1 when the binary is missing, 0 once the process is spawned. A
    spawned OpenCode that then exits with an error is visible in the console
    window, which is why it is started with `cmd /k` rather than closed again.
    """
    if not shutil.which("opencode"):
        print(
            "opencode is not in your PATH.\n"
            "Install it, or point the config at LiteLLM by hand:\n"
            f"    baseURL -> {configs.load_full(working_dir).litellm_url}"
        )
        return 1

    tag = configs.load_full(working_dir).model_tag or PROVIDER_ID
    cmd = ["opencode", "-m", f"{PROVIDER_ID}/{tag}"] + list(extra_args or [])

    if os.name == "nt":
        subprocess.Popen(["cmd", "/c", "start", "cmd", "/k", _cmdline(cmd)],
                         cwd=str(working_dir))
    else:
        subprocess.Popen(cmd, cwd=str(working_dir))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Point OpenCode at the local Cayde 420 stack"
    )
    parser.add_argument("--print", dest="show", action="store_true",
                        help="Show the config that would be written.")
    parser.add_argument("--launch", action="store_true",
                        help="Write the config, then start OpenCode.")
    # Deliberately no --model. The tag is the one in config.yaml, which is the
    # only name the proxy's model_list actually serves; honouring an override
    # here would write a provider block pointing at a model LiteLLM rejects at
    # request time. Re-pick the model in Settings instead.
    args = parser.parse_args(argv)

    working_dir = Path(__file__).resolve().parent
    cfg = configs.load_full(working_dir)

    print(f"  Ollama    : {cfg.ollama_base_url}")
    print(f"  LiteLLM   : {cfg.litellm_url}   (spoofs api.anthropic.com)")
    print(f"  Model tag : {cfg.model_tag}")
    print(f"  Config    : {CONFIG_FILE}")
    print()

    if args.show:
        print(json.dumps(build_config(working_dir), indent=2))
        return 0

    path = write_config(working_dir)
    print(f"Wrote provider '{PROVIDER_ID}' to {path}")
    backup = backup_path()
    print(f"Backup of the previous config: {backup}"
          f"{'' if backup.exists() else ' (none — nothing to back up)'}")
    print()
    print("Use it with:")
    print(f"    opencode -m {PROVIDER_ID}/{cfg.model_tag}")
    print()
    print("LiteLLM must be running (it is what spoofs the Anthropic API).")

    if args.launch:
        return launch(working_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())