"""
Read/write for Modelfile and config.yaml — the two files that drive Ollama and
the LiteLLM proxy respectively. Everything that touches those file formats
lives here so the GUI, TUI, and installer all agree on the schema.
"""

import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Optional


import settings

VALID_ENGINE_MODES = ("direct", "litellm_standard", "litellm_chat")


@dataclass
class ModelConfig:
    """Everything the app needs to know to build a Modelfile + config.yaml."""
    selected_gguf: Optional[str] = None
    model_tag: Optional[str] = None
    engine_mode: str = "litellm_chat"

    context_size: int = 32768
    gpu_layers: int = 99
    cpu_threads: int = 6
    batch_size: int = 512
    temperature: float = 0.2
    max_tokens: int = 8192

    # Reasoning models emit a `thinking` block before any text. Left enabled,
    # the whole output budget can be consumed by reasoning and the response
    # arrives with zero text — which Claude Code reports as a truncated or empty
    # stream. Default off so answers actually arrive.
    thinking: bool = False

    # LiteLLM proxy addressing (defaults synced with settings.json)
    litellm_url: str = field(default_factory=lambda: settings.load()["litellm_base_url"])
    litellm_api_key: str = field(default_factory=lambda: settings.load()["litellm_api_key"])

    # Ollama addressing
    ollama_base_url: str = field(default_factory=lambda: settings.load()["ollama_base_url"])

    def with_updates(self, **kwargs) -> "ModelConfig":
        return replace(self, **kwargs)


# ─── Tag derivation ───────────────────────────────────────────────────────────

def derive_model_tag(gguf_filename: str) -> str:
    """Turn a GGUF filename into a valid Ollama tag."""
    stem = Path(gguf_filename).stem
    return re.sub(r'[^a-z0-9._-]', '-', stem.lower())


# ─── Parsers ──────────────────────────────────────────────────────────────────

def load_modelfile(path: Path) -> ModelConfig:
    """Read a Modelfile and return the parameters it declares (fills defaults for missing keys)."""
    cfg = ModelConfig()
    if not path.exists():
        return cfg

    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return cfg

    from_match = re.search(r'^\s*FROM\s+\.\/([^\s]+)', content, re.MULTILINE)
    if from_match:
        cfg.selected_gguf = from_match.group(1)

    _int_param(content, r'num_gpu',     lambda v: setattr(cfg, "gpu_layers",   v))
    _int_param(content, r'num_thread',  lambda v: setattr(cfg, "cpu_threads",  v))
    _int_param(content, r'num_batch',   lambda v: setattr(cfg, "batch_size",   v))
    _float_param(content, r'temperature', lambda v: setattr(cfg, "temperature", v))
    # num_ctx is deliberately NOT read here: context size is owned by
    # config.yaml (see load_full). Older Modelfiles that still declare it are
    # ignored so there is exactly one source of truth.

    return cfg


def load_config_yaml(path: Path) -> dict:
    """Extract engine_mode + model_tag + api_base + inference sizing from an
    existing config.yaml. Text-based to avoid a PyYAML dependency for such a
    simple file.

    config.yaml is the single source of truth for context_size and max_tokens:
    those are per-request values that LiteLLM forwards on every call, so the
    proxy config is the only place they need to live.
    """
    out = {
        "engine_mode": "litellm_chat",
        "model_tag": None,
        "ollama_url": None,
        "context_size": None,
        "max_tokens": None,
        "thinking": None,
    }
    if not path.exists():
        return out

    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return out

    tag_match = re.search(r'model_name:\s*([^\s]+)', content)
    if tag_match and tag_match.group(1) != '"*"' and tag_match.group(1) != "*":
        out["model_tag"] = tag_match.group(1)

    url_match = re.search(r'api_base:\s*([^\s]+)', content)
    if url_match:
        out["ollama_url"] = url_match.group(1)

    _yaml_int(content, 'num_ctx', lambda v: out.__setitem__("context_size", v))
    _yaml_int(content, 'max_tokens', lambda v: out.__setitem__("max_tokens", v))
    _yaml_bool(content, 'think', lambda v: out.__setitem__("thinking", v))

    if "ollama_chat/" in content:
        out["engine_mode"] = "litellm_chat"
    elif "ollama/" in content:
        out["engine_mode"] = "litellm_standard"
    else:
        out["engine_mode"] = "direct"

    return out


def load_full(working_dir: Path) -> ModelConfig:
    """Merged view of the on-disk state.

    Division of ownership:
      Modelfile   — what the weights need baked in at `ollama create` time
                    (selected GGUF, layer placement, threads, batch, temperature).
      config.yaml — what the proxy forwards per request (context size, max tokens)
                    plus routing (tag, api_base, engine mode).

    context_size and max_tokens are read from config.yaml only. The Modelfile no
    longer declares num_ctx, so there is a single place to read and write them and
    the GUI round trip cannot silently revert a saved value.
    """
    cfg = load_modelfile(working_dir / "Modelfile")
    y = load_config_yaml(working_dir / "config.yaml")
    if y["model_tag"]:
        cfg.model_tag = y["model_tag"]
    cfg.engine_mode = y["engine_mode"]
    if y.get("ollama_url"):
        cfg.ollama_base_url = y["ollama_url"]
    if y.get("context_size"):
        cfg.context_size = y["context_size"]
    if y.get("max_tokens"):
        cfg.max_tokens = y["max_tokens"]
    if y.get("thinking") is not None:
        cfg.thinking = y["thinking"]

    # If Modelfile didn't declare a GGUF, pick the first one on disk
    if not cfg.selected_gguf:
        ggufs = list(working_dir.glob("*.gguf"))
        if ggufs:
            cfg.selected_gguf = ggufs[0].name

    if not cfg.model_tag and cfg.selected_gguf:
        cfg.model_tag = derive_model_tag(cfg.selected_gguf)

    return cfg


def _int_param(content: str, key: str, setter):
    m = re.search(rf'^\s*PARAMETER\s+{key}\s+(\d+)', content, re.MULTILINE)
    if m:
        setter(int(m.group(1)))


def _float_param(content: str, key: str, setter):
    m = re.search(rf'^\s*PARAMETER\s+{key}\s+([\d.]+)', content, re.MULTILINE)
    if m:
        setter(float(m.group(1)))


def _yaml_bool(content: str, key: str, setter) -> None:
    """Read a boolean from YAML `key: true` syntax (config.yaml)."""
    m = re.search(rf'^\s*{key}:\s*(true|false)\s*$', content, re.MULTILINE | re.IGNORECASE)
    if m:
        setter(m.group(1).lower() == "true")


def _yaml_int(content: str, key: str, setter) -> None:
    """Read an integer from YAML `key: 123` syntax (config.yaml, not a Modelfile)."""
    m = re.search(rf'^\s*{key}:\s*(\d+)\s*$', content, re.MULTILINE)
    if m:
        setter(int(m.group(1)))


# ─── Writers ──────────────────────────────────────────────────────────────────

MODELFILE_TEMPLATE = """FROM ./{gguf}

# Baked in at `ollama create` time. These are model-construction concerns: layer
# placement, thread count, batch size. They have no per-request equivalent.
#
# Context size is intentionally absent: LiteLLM forwards num_ctx on every request
# from config.yaml, so declaring it here created a second source of truth that
# overwrote saved values on the next config rebuild.
PARAMETER num_gpu {gpu_layers}
PARAMETER num_thread {cpu_threads}
PARAMETER num_batch {batch_size}
PARAMETER temperature {temperature}

SYSTEM \"\"\"
You are Claude Code, Anthropic's official CLI for software engineering.
Respond directly to user requests. Do not wrap tool calls in plain text JSON code blocks.
\"\"\"
"""


def write_modelfile(cfg: ModelConfig, path: Path) -> None:
    if not cfg.selected_gguf:
        raise ValueError("Cannot write Modelfile: no GGUF file selected.")
    path.write_text(
        MODELFILE_TEMPLATE.format(
            gguf=cfg.selected_gguf,
            gpu_layers=cfg.gpu_layers,
            cpu_threads=cfg.cpu_threads,
            batch_size=cfg.batch_size,
            temperature=cfg.temperature,
        ),
        encoding="utf-8",
    )


CONFIG_YAML_TEMPLATE = """model_list:
  - model_name: {tag}
    litellm_params:
      model: {prefix}{tag}
      api_base: {ollama_url}
      num_ctx: {context_size}
      max_tokens: {max_tokens}
      extra_body:
        think: {thinking}
  - model_name: "*"
    litellm_params:
      model: {prefix}{tag}
      api_base: {ollama_url}
      num_ctx: {context_size}
      max_tokens: {max_tokens}
      extra_body:
        think: {thinking}

litellm_settings:
  drop_params: true
  ignore_invalid_params: true
  modify_params: true
  force_timeout: 600
  json_logs: false
"""


def write_config_yaml(cfg: ModelConfig, path: Path) -> None:
    if not cfg.model_tag:
        raise ValueError("Cannot write config.yaml: no model tag set.")
    if cfg.engine_mode not in VALID_ENGINE_MODES:
        raise ValueError(f"Unknown engine_mode: {cfg.engine_mode!r}")

    prefix = "ollama_chat/" if cfg.engine_mode == "litellm_chat" else "ollama/"
    path.write_text(
        CONFIG_YAML_TEMPLATE.format(
            tag=cfg.model_tag,
            prefix=prefix,
            ollama_url=cfg.ollama_base_url,
            context_size=cfg.context_size,
            max_tokens=cfg.max_tokens,
            thinking="true" if cfg.thinking else "false",
        ),
        encoding="utf-8",
    )


def write_all(cfg: ModelConfig, working_dir: Path) -> None:
    """Persist both files in one call."""
    write_modelfile(cfg, working_dir / "Modelfile")
    write_config_yaml(cfg, working_dir / "config.yaml")
