"""
Read/write for Modelfile and config.yaml — the two files that drive Ollama and
the LiteLLM proxy respectively. Everything that touches those file formats
lives here so the GUI, TUI, and installer all agree on the schema.
"""

import hashlib
import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Optional


import settings

import model_registry

VALID_ENGINE_MODES = ("direct", "litellm_standard", "litellm_chat")

# Ollama refuses model names longer than 80 characters.
MAX_TAG_LENGTH = 80


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

    # Sampling params baked in at `ollama create` time. These belong to the model,
    # not to the proxy, so they live in the Modelfile. Leaving them at the GGUF's
    # own defaults is fine — set them only when a model expects specific values.
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    repeat_penalty: Optional[float] = None

    # Persona baked into the model. Deliberately a field rather than template
    # text: a hardcoded SYSTEM silently overwrote the personality of whichever
    # model was rebuilt, which is how Heretic's own prompt got clobbered.
    system_prompt: str = ""

    # Set when the user deliberately names a model something other than what its
    # filename implies. Suppresses the tag-vs-weights check in coherence_issues.
    tag_is_custom: bool = False

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
    """Turn a GGUF filename (or full path) into a valid Ollama tag.

    Preserves the original case. Ollama tags are case-insensitive for matching
    but the HTTP API and `ollama list` preserve case, so a lowercased tag would
    not round-trip through the model dropdown. Only invalid characters are
    replaced. Ollama requires the first character to be alphanumeric, and
    rejects names longer than 80 characters; over-long names are truncated with
    a short hash of the full stem appended so two long-named models cannot
    collide on the same tag.
    """
    stem = Path(gguf_filename).stem
    tag = re.sub(r'[^a-zA-Z0-9._-]', '-', stem)
    tag = tag.lstrip("-._")
    if not tag:
        tag = "model"
    if len(tag) > MAX_TAG_LENGTH:
        digest = hashlib.sha256(stem.encode("utf-8")).hexdigest()[:6]
        keep = MAX_TAG_LENGTH - len(digest) - 1
        tag = f"{tag[:keep].rstrip('-._')}-{digest}"
    return tag


def modelfile_from_path(selected_gguf: str, working_dir=None) -> str:
    """Render the Modelfile FROM value for a GGUF reference.

    Always absolute, always forward slashes. Ollama on Windows cannot import a
    local GGUF through a './Models/...' FROM line: it derives a model name from
    the source string, the leading '.' fails name validation, and the server
    answers with a misleading "Error: 400 Bad Request: invalid model name" that
    looks like a problem with the chosen tag. An absolute path is accepted.

    Resolution goes through model_registry so a bare filename that refers to an
    out-of-project weight (tracked in .external_paths.json) still resolves to
    the real bytes on this machine.
    """
    return model_registry.resolve(selected_gguf, working_dir).as_posix()


def coherence_issues(cfg: "ModelConfig", registered_tags=None, working_dir=None) -> list:
    """Ways the config.yaml model tag and the Modelfile can disagree.

    The two files are written together from one ModelConfig, so they agree right
    after a write. They drift when something edits one in isolation — a partial
    write, a hand edit, or a rebuild from a different Modelfile. When that
    happens the proxy keeps routing to one model while the panel describes
    another, and the GUI then re-writes the stale value back.

    A tag that differs from the filename is not automatically wrong: renaming a
    model is normal, and `qwythos-heretic` legitimately names
    `Qwen3.5-9B-Heretic-patched.gguf`. Pass the tags Ollama has registered and a
    mismatch is only reported when the tag names nothing that exists, which is
    the drift case.

    Returns a list of human-readable problems; empty means coherent.
    """
    issues = []
    if not cfg.model_tag:
        issues.append("No model tag set, so config.yaml has nothing to route to.")
        return issues
    if not cfg.selected_gguf:
        issues.append(
            "No GGUF selected, so the Modelfile has no weights to point at."
        )
        return issues

    gguf_path = Path(cfg.selected_gguf)
    # Relative entries ("Models/x.gguf" or a bare external name) resolve through
    # the registry against the project directory and .external_paths.json, not
    # the process cwd — otherwise the check reports a false "missing" file.
    resolved = model_registry.resolve(cfg.selected_gguf, working_dir)
    if not resolved.exists():
        issues.append(
            f"Modelfile points at a model file that does not exist:\n"
            f"    {gguf_path}"
        )

    implied = derive_model_tag(gguf_path.name)
    # A tag that differs from the weights is only suspicious when it names
    # something Ollama does not have. A registered tag is a deliberate rename
    # and is left alone.
    known = set(registered_tags or ())
    if implied != cfg.model_tag and not cfg.tag_is_custom:
        if not known or cfg.model_tag not in known:
            issues.append(
                f"Model tag '{cfg.model_tag}' does not match the selected weights.\n"
                f"    Modelfile : {gguf_path.name}\n"
                f"    implies   : '{implied}'\n"
                f"config.yaml would route to '{cfg.model_tag}' while the Modelfile "
                f"describes {gguf_path.name}."
            )
    return issues


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

    from_match = re.search(r'^\s*FROM\s+(\S+)', content, re.MULTILINE)
    if from_match:
        raw = from_match.group(1).strip().strip('"').strip("'")
        # './model.gguf' is repo-local; anything else is an absolute path.
        # Modelfiles must use forward slashes (Ollama requirement), so convert
        # back to native separators here — that way a path chosen via a file
        # dialog reads back exactly as it was selected.
        if raw.startswith("./") or raw.startswith(".\\"):
            raw = raw[2:]
        else:
            raw = os.path.normpath(raw)
        # Normalise to the portable reference ("Models/<file>" or a bare name
        # tracked in .external_paths.json) so the config does not hard-code this
        # machine's absolute path.
        cfg.selected_gguf = model_registry.canonicalize(raw)

    _int_param(content, r'num_gpu',     lambda v: setattr(cfg, "gpu_layers",   v))
    _int_param(content, r'num_thread',  lambda v: setattr(cfg, "cpu_threads",  v))
    _int_param(content, r'num_batch',   lambda v: setattr(cfg, "batch_size",   v))
    _float_param(content, r'temperature', lambda v: setattr(cfg, "temperature", v))
    # Records that the model tag is a deliberate rename rather than drift.
    # Lives in the Modelfile so the acknowledgement travels with the weights
    # instead of depending on Ollama being online when the check runs.
    if re.search(r'^\s*#\s*tag:\s*custom\s*$', content, re.MULTILINE):
        cfg.tag_is_custom = True
    _float_param(content, r'top_p',     lambda v: setattr(cfg, "top_p",     v))
    _int_param(content, r'top_k',        lambda v: setattr(cfg, "top_k",     v))
    _float_param(content, r'repeat_penalty', lambda v: setattr(cfg, "repeat_penalty", v))

    # SYSTEM """...""" — may span lines. Absent means the model keeps its own
    # default persona, which is stored as an empty string.
    sys_match = re.search(r'^\s*SYSTEM\s+"""(.*?)"""', content, re.MULTILINE | re.DOTALL)
    if sys_match:
        cfg.system_prompt = sys_match.group(1).strip()
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

    # If Modelfile didn't declare a GGUF, pick the first one in Models/
    if not cfg.selected_gguf:
        models_dir = working_dir / "Models"
        ggufs = list(models_dir.glob("*.gguf")) if models_dir.exists() else []
        if ggufs:
            cfg.selected_gguf = f"Models/{ggufs[0].name}"

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

MODELFILE_TEMPLATE = """FROM {gguf_from}

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
{tag_marker}{optional_params}{system_block}"""


def _modelfile_tag_marker(cfg: ModelConfig) -> str:
    """Record a deliberate tag rename so coherence_issues accepts it offline."""
    if cfg.tag_is_custom:
        return "# tag: custom\n"
    return ""


def _modelfile_optional_params(cfg: ModelConfig) -> str:
    """Sampling params, emitted only when set.

    Blank lines are kept rather than filtered, so the layout stays stable
    whether or not the user configured them.
    """
    parts = []
    for key, value in (
        ("top_p", cfg.top_p),
        ("top_k", cfg.top_k),
        ("repeat_penalty", cfg.repeat_penalty),
    ):
        if value is None:
            parts.append("# PARAMETER %s (using model default)\n" % key)
        else:
            parts.append(f"PARAMETER {key} {value}\n")
    return "".join(parts)


def _modelfile_system_block(cfg: ModelConfig) -> str:
    """SYSTEM block, emitted only when a persona is configured."""
    prompt = (cfg.system_prompt or "").strip()
    if not prompt:
        return "\n# No SYSTEM block: the model keeps its own default persona.\n"
    return f'\nSYSTEM """{prompt}"""\n'


def write_modelfile(cfg: ModelConfig, path: Path, working_dir=None) -> None:
    if not cfg.selected_gguf:
        raise ValueError("Cannot write Modelfile: no GGUF file selected.")
    path.write_text(
        MODELFILE_TEMPLATE.format(
            gguf_from=modelfile_from_path(cfg.selected_gguf, working_dir),
            gpu_layers=cfg.gpu_layers,
            cpu_threads=cfg.cpu_threads,
            batch_size=cfg.batch_size,
            temperature=cfg.temperature,
            tag_marker=_modelfile_tag_marker(cfg),
            optional_params=_modelfile_optional_params(cfg),
            system_block=_modelfile_system_block(cfg),
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


def write_all(cfg: ModelConfig, working_dir: Path, registered_tags=None) -> None:
    """Persist both files in one call.

    Refuses to write when the model tag and the selected weights disagree, since
    that silently produces a proxy that routes somewhere other than the model
    the panel is describing. Callers that legitimately want a custom tag should
    resolve the issue first (see coherence_issues) rather than force past this.
    """
    issues = coherence_issues(cfg, registered_tags, working_dir)
    if issues:
        raise ValueError(
            "Refusing to save — the model tag and the selected weights disagree:\n\n"
            + "\n".join(issues)
            + "\n\nFix the model tag or re-pick the GGUF, then save again."
        )
    write_modelfile(cfg, working_dir / "Modelfile", working_dir)
    write_config_yaml(cfg, working_dir / "config.yaml")
