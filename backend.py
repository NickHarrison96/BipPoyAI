"""
Backend Engine for Cayde 420.

Architecture:
  Ollama (port 11434, hosts the GGUF model)
    → LiteLLM Proxy (port 4000, translates to OpenAI-compatible API)
      → This backend (sends /v1/chat/completions requests)

Handles:
  - Health checks for both Ollama AND LiteLLM
  - Starting/managing LiteLLM proxy process
  - Model management (is model registered in Ollama? create from Modelfile)
  - Streaming chat inference via LiteLLM's OpenAI-compatible /v1/chat/completions
  - Background threading so the GUI never freezes
"""

import json
import os
import time
import subprocess
import shutil
import re
from pathlib import Path
from typing import Optional, List, Dict

from PySide6.QtCore import QThread, Signal, QObject, QTimer
from urllib.parse import urlparse
import requests

import settings
import netutil
import memory_vault
from configs import derive_model_tag


# ─── Constants ────────────────────────────────────────────────────────────────

DEFAULT_OLLAMA_BASE_URL = settings.DEFAULTS["ollama_base_url"]
DEFAULT_LITELLM_BASE_URL = settings.DEFAULTS["litellm_base_url"]
DEFAULT_LITELLM_API_KEY = settings.DEFAULTS["litellm_api_key"]
# Fallback only — _resolve_model_tag() replaces this from config.yaml/Modelfile on
# startup. Kept neutral so it does not name a model the user may not have.
DEFAULT_MODEL_TAG = "local-model"


def normalize_url(url: str) -> str:
    """Trim whitespace and any trailing slashes so URLs compose cleanly."""
    return (url or "").strip().rstrip("/")


# ─── Chat Worker (background thread for streaming inference) ──────────────────

class ChatWorker(QThread):
    """
    Runs a streaming chat completion request in a background thread.
    Supports:
      - Direct Ollama mode (/api/chat, native JSON streaming)
      - LiteLLM proxy mode (/v1/chat/completions, OpenAI SSE streaming)
    """
    token_received = Signal(str)           # individual token chunk
    generation_complete = Signal(str)       # full assembled response
    error_occurred = Signal(str)            # error message
    stats_update = Signal(dict)             # {"tokens_per_sec": float, "total_tokens": int}

    def __init__(
        self,
        messages: List[Dict[str, str]],
        model: str = DEFAULT_MODEL_TAG,
        temperature: float = 0.2,
        max_tokens: int = 8192,
        num_ctx: int = 32768,
        engine_mode: str = "litellm_chat",
        ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL,
        litellm_base_url: str = DEFAULT_LITELLM_BASE_URL,
        litellm_api_key: str = DEFAULT_LITELLM_API_KEY,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.messages = messages
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.num_ctx = num_ctx
        self.engine_mode = engine_mode
        self.ollama_base_url = normalize_url(ollama_base_url)
        self.litellm_base_url = normalize_url(litellm_base_url)
        self.litellm_api_key = litellm_api_key
        self._cancelled = False
        self._resp = None  # active streaming response, closed on cancel

    def cancel(self):
        """Request cancellation of the in-flight generation."""
        self._cancelled = True
        # Close the response to unblock iter_lines() if it's waiting on data
        if self._resp is not None:
            try:
                self._resp.close()
            except Exception:
                pass

    def run(self):
        start_time = time.time()
        if self.engine_mode == "direct":
            self._run_direct(start_time)
        else:
            self._run_litellm(start_time)

    def _run_direct(self, start_time: float):
        """Stream directly from Ollama /api/chat endpoint."""
        full_response = ""
        token_count = 0

        try:
            payload = {
                "model": self.model,
                "messages": self.messages,
                "stream": True,
                "options": {
                    "temperature": self.temperature,
                    "num_predict": self.max_tokens,
                    # Sent per request because the Modelfile no longer bakes in
                    # num_ctx — config.yaml owns the configured context size.
                    "num_ctx": self.num_ctx,
                },
            }

            resp = requests.post(
                f"{self.ollama_base_url}/api/chat",
                json=payload,
                stream=True,
                timeout=600,
            )
            resp.raise_for_status()
            self._resp = resp

            for line in resp.iter_lines(decode_unicode=True):
                if self._cancelled:
                    break

                if not line:
                    continue

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg = data.get("message", {})
                content = msg.get("content", "")
                if content:
                    full_response += content
                    token_count += 1
                    self.token_received.emit(content)

                    elapsed = time.time() - start_time
                    if elapsed > 0 and token_count % 5 == 0:
                        tps = token_count / elapsed
                        self.stats_update.emit({
                            "tokens_per_sec": round(tps, 1),
                            "total_tokens": token_count,
                        })

                if data.get("done", False):
                    break

            elapsed = time.time() - start_time
            if elapsed > 0 and token_count > 0:
                tps = token_count / elapsed
                self.stats_update.emit({
                    "tokens_per_sec": round(tps, 1),
                    "total_tokens": token_count,
                })

            if not self._cancelled:
                self.generation_complete.emit(full_response)
            else:
                self.generation_complete.emit(full_response + "\n\n*(generation stopped)*")

        except Exception as e:
            # If cancel closed the response, this is expected — not an error
            if self._cancelled:
                self.generation_complete.emit(full_response + "\n\n*(generation stopped)*")
                return
            if isinstance(e, requests.ConnectionError):
                port = urlparse(self.ollama_base_url).port or 11434
                self.error_occurred.emit(
                    f"Cannot connect to Ollama on {self.ollama_base_url} (port {port}).\n"
                    "Please make sure Ollama is running (`ollama serve`)."
                )
            elif isinstance(e, requests.Timeout):
                self.error_occurred.emit(
                    "Request to Ollama timed out. The model may be too large for your hardware."
                )
            elif isinstance(e, requests.HTTPError):
                error_body = ""
                try:
                    error_body = e.response.text[:500]
                except Exception:
                    pass
                self.error_occurred.emit(
                    f"Ollama API error (HTTP {e.response.status_code}):\n{error_body}"
                )
            else:
                self.error_occurred.emit(f"Unexpected error: {str(e)}")

    def _run_litellm(self, start_time: float):
        """Stream via LiteLLM /v1/chat/completions endpoint."""
        full_response = ""
        token_count = 0

        try:
            payload = {
                "model": self.model,
                "messages": self.messages,
                "stream": True,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.litellm_api_key}",
            }

            resp = requests.post(
                f"{self.litellm_base_url}/v1/chat/completions",
                json=payload,
                headers=headers,
                stream=True,
                timeout=600,
            )
            resp.raise_for_status()
            self._resp = resp

            for line in resp.iter_lines(decode_unicode=True):
                if self._cancelled:
                    break

                if not line:
                    continue

                # SSE format: lines start with "data: "
                if line.startswith("data: "):
                    data_str = line[6:]  # strip "data: " prefix

                    if data_str.strip() == "[DONE]":
                        break

                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    # OpenAI streaming format: choices[0].delta.content
                    choices = data.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        content = delta.get("content", "")

                        if content:
                            full_response += content
                            token_count += 1
                            self.token_received.emit(content)

                            # Emit stats periodically
                            elapsed = time.time() - start_time
                            if elapsed > 0 and token_count % 5 == 0:
                                tps = token_count / elapsed
                                self.stats_update.emit({
                                    "tokens_per_sec": round(tps, 1),
                                    "total_tokens": token_count,
                                })

                        # Check finish_reason
                        finish = choices[0].get("finish_reason")
                        if finish is not None:
                            break

            # Final stats
            elapsed = time.time() - start_time
            if elapsed > 0 and token_count > 0:
                tps = token_count / elapsed
                self.stats_update.emit({
                    "tokens_per_sec": round(tps, 1),
                    "total_tokens": token_count,
                })

            if not self._cancelled:
                self.generation_complete.emit(full_response)
            else:
                self.generation_complete.emit(full_response + "\n\n*(generation stopped)*")

        except Exception as e:
            # If cancel closed the response, this is expected — not an error
            if self._cancelled:
                self.generation_complete.emit(full_response + "\n\n*(generation stopped)*")
                return
            if isinstance(e, requests.ConnectionError):
                port = urlparse(self.litellm_base_url).port or 4000
                self.error_occurred.emit(
                    f"Cannot connect to LiteLLM proxy on {self.litellm_base_url} (port {port}).\n"
                    "Click 'Start LiteLLM' to launch the proxy, or check that Ollama is running."
                )
            elif isinstance(e, requests.Timeout):
                self.error_occurred.emit(
                    "Request to LiteLLM timed out. The model may be too large for your hardware."
                )
            elif isinstance(e, requests.HTTPError):
                error_body = ""
                try:
                    error_body = e.response.text[:500]
                except Exception:
                    pass
                self.error_occurred.emit(
                    f"LiteLLM API error (HTTP {e.response.status_code}):\n{error_body}"
                )
            else:
                self.error_occurred.emit(f"Unexpected error: {str(e)}")


# ─── Status Worker (Background polling thread) ────────────────────────────────

class StatusWorker(QThread):
    """
    Background worker that probes Ollama and LiteLLM health endpoints.
    Completely decouples HTTP network requests from the Qt main GUI thread
    so the UI never locks up or freezes during polling.
    """
    status_ready = Signal(str, str, str, list)  # ollama_status, litellm_status, model_status, model_names

    def __init__(
        self,
        ollama_base_url: str,
        litellm_base_url: str,
        model_tag: str,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.ollama_base_url = ollama_base_url
        self.litellm_base_url = litellm_base_url
        self.model_tag = model_tag

    def run(self):
        ollama_status = "offline"
        model_status = "unknown"
        model_names = []
        litellm_status = "offline"

        # Check Ollama
        try:
            resp = requests.get(f"{self.ollama_base_url}/api/tags", timeout=2)
            if resp.status_code == 200:
                ollama_status = "live"
                data = resp.json()
                models = data.get("models", [])
                model_names = [m.get("name", "").split(":")[0] for m in models]
                if self.model_tag in model_names:
                    model_status = "ready"
                else:
                    model_status = "not_found"
        except Exception:
            pass

        # Check LiteLLM — fast liveness probe (deep /health takes ~5.4s because
        # it queries Ollama, which blew the old 3s timeout and left the LED
        # stuck on "offline" while chat worked fine).
        if netutil.litellm_healthy(self.litellm_base_url):
            litellm_status = "live"

        self.status_ready.emit(ollama_status, litellm_status, model_status, model_names)


# ─── LiteLLM Process Manager ─────────────────────────────────────────────────

class LiteLLMStarter(QThread):
    """
    Starts the LiteLLM proxy server in a background process.
    """
    progress_update = Signal(str)
    started_ok = Signal()
    started_error = Signal(str)
    proc_started = Signal(object)  # the spawned Popen, so the backend can clean it up

    def __init__(
        self,
        config_path: str,
        working_dir: str,
        litellm_url: str = DEFAULT_LITELLM_BASE_URL,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.config_path = config_path
        self.working_dir = working_dir
        self.litellm_url = normalize_url(litellm_url)

    def run(self):
        try:
            litellm_path = shutil.which("litellm")
            if not litellm_path:
                self.started_error.emit(
                    "LiteLLM CLI not found in system PATH.\n"
                    "Run: pip install litellm"
                )
                return

            if not Path(self.config_path).exists():
                self.started_error.emit(
                    f"config.yaml not found at:\n{self.config_path}\n"
                    "Run the Settings → Save & Rebuild to generate it."
                )
                return

            def health_ok() -> bool:
                # Spec Step 3: gate on /health/readiness so Claude CLI never
                # launches against a proxy that is up but still loading config.
                return netutil.litellm_ready(self.litellm_url)

            port = urlparse(self.litellm_url).port or 4000
            host = urlparse(self.litellm_url).hostname or "127.0.0.1"

            if health_ok():
                self.progress_update.emit("LiteLLM proxy is already running!")
                self.started_ok.emit()
                return

            # Port busy but /health failing: LiteLLM 1.102+ would silently fall
            # back to a RANDOM port if we spawned anyway. Poll in case a previous
            # instance is still booting; otherwise report the conflict.
            if netutil.port_in_use(port):
                self.progress_update.emit(
                    f"Port {port} is in use - polling existing instance..."
                )
                for _ in range(30):
                    time.sleep(2)
                    if health_ok():
                        self.progress_update.emit("LiteLLM proxy is already running!")
                        self.started_ok.emit()
                        return
                pid = netutil.pid_on_port(port)
                self.started_error.emit(
                    f"Port {port} is occupied by PID {pid or 'unknown'} "
                    f"but not answering /health.\n\n"
                    "Starting LiteLLM now would silently move it to a random port.\n"
                    + (f"Kill it first:  taskkill /PID {pid} /F" if pid
                       else f"Find the holder:  netstat -ano | findstr :{port}")
                )
                return

            self.progress_update.emit(f"Starting LiteLLM proxy on {host}:{port}...")

            cmd = ["litellm", "--config", self.config_path,
                   "--host", host, "--port", str(port)]

            # LiteLLM prints a box-drawing banner at startup. On a non-UTF8
            # console (cp437/cp1252) that raises UnicodeEncodeError inside
            # proxy_startup_event and the proxy dies before serving anything.
            # Force UTF-8 in the child's environment so startup always succeeds.
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"

            # A console window is useful while diagnosing, but once the stack is
            # known-good the user wants it gone. CREATE_NO_WINDOW suppresses it.
            silent = settings.is_true(settings.load().get("launch_silent"))
            if os.name == 'nt':
                flags = (
                    subprocess.CREATE_NO_WINDOW
                    if silent
                    else subprocess.CREATE_NEW_CONSOLE
                )
                proc = subprocess.Popen(
                    cmd,
                    cwd=self.working_dir,
                    env=env,
                    creationflags=flags,
                )
            else:
                proc = subprocess.Popen(
                    cmd,
                    cwd=self.working_dir,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            self.proc_started.emit(proc)

            # Wait for it to come up. LiteLLM boots slowly (~1 min) and its
            # /health endpoint itself takes ~3s to answer, so poll patiently.
            self.progress_update.emit("Waiting for LiteLLM to initialize...")
            for attempt in range(60):  # up to ~2 minutes
                time.sleep(2)
                if health_ok():
                    self.progress_update.emit("LiteLLM proxy is live!")
                    self.started_ok.emit()
                    return

            # Diagnose the failure instead of a generic timeout.
            if netutil.pid_on_port(port) is None:
                self.started_error.emit(
                    f"Port {port} was never bound - LiteLLM likely fell back to a "
                    f"random port (another process grabbed {port} during startup) "
                    f"or crashed.\nCheck the LiteLLM console window for the port "
                    f"it actually bound."
                )
            else:
                self.started_error.emit(
                    f"LiteLLM bound port {port} but /health did not answer within "
                    f"2 minutes.\nCheck the LiteLLM console window for errors."
                )

        except Exception as e:
            self.started_error.emit(f"Failed to start LiteLLM:\n{str(e)}")


# ─── Model Manager ───────────────────────────────────────────────────────────

class ModelManager(QThread):
    """
    Background thread that creates the Ollama model from the Modelfile.
    """
    progress_update = Signal(str)
    finished_ok = Signal()
    finished_error = Signal(str)

    def __init__(self, model_tag: str, working_dir: str, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.model_tag = model_tag
        self.working_dir = working_dir

    def run(self):
        try:
            ollama_path = shutil.which("ollama")
            if not ollama_path:
                self.finished_error.emit(
                    "Ollama CLI not found in system PATH.\n"
                    "Please install Ollama from https://ollama.com"
                )
                return

            modelfile_path = Path(self.working_dir) / "Modelfile"
            if not modelfile_path.exists():
                self.finished_error.emit(
                    f"Modelfile not found at {modelfile_path}\n"
                    "Cannot create model without a Modelfile."
                )
                return

            self.progress_update.emit(f"Creating model '{self.model_tag}'...")
            self.progress_update.emit("This may take a moment for large models...")

            process = subprocess.run(
                ["ollama", "create", self.model_tag, "-f", str(modelfile_path)],
                cwd=self.working_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

            if process.returncode == 0:
                self.progress_update.emit("Model registered successfully!")
                self.finished_ok.emit()
            else:
                stderr = process.stderr.strip() if process.stderr else "Unknown error"
                self.finished_error.emit(f"ollama create failed:\n{stderr}")

        except subprocess.TimeoutExpired:
            self.finished_error.emit("Model creation timed out after 5 minutes.")
        except Exception as e:
            self.finished_error.emit(f"Unexpected error during model creation:\n{str(e)}")


# ─── Model Preloader (spec Step 1: load weights, keep warm) ───────────────────

class ModelPreloader(QThread):
    """
    Runs `ollama run <tag> "" --keepalive 24h` so the weights are resident in
    VRAM before the first request instead of paging in mid-conversation.
    """
    progress_update = Signal(str)
    finished_ok = Signal()
    finished_error = Signal(str)

    def __init__(self, model_tag: str, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.model_tag = model_tag

    def run(self):
        try:
            self.progress_update.emit(f"Loading weights for '{self.model_tag}'...")
            process = subprocess.run(
                ["ollama", "run", self.model_tag, "", "--keepalive", "24h"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if process.returncode == 0:
                self.progress_update.emit("Model loaded and kept warm for 24h.")
                self.finished_ok.emit()
            else:
                stderr = (process.stderr or "").strip()
                self.finished_error.emit(stderr or "ollama run failed.")
        except subprocess.TimeoutExpired:
            self.finished_error.emit("Preload timed out after 10 minutes.")
        except Exception as e:
            self.finished_error.emit(str(e))


# ─── Ollama Backend (main interface for the GUI) ─────────────────────────────

class OllamaBackend(QObject):
    """
    High-level interface between the GUI and the Ollama+LiteLLM stack.

    Provides:
      - Status polling (is Ollama alive? is LiteLLM alive? is the model loaded?)
      - Chat with streaming (routed through LiteLLM)
      - Model creation (via Ollama CLI)
      - LiteLLM proxy management (start/stop)
    """

    # Status signals
    ollama_status_changed = Signal(str)    # "live" | "offline"
    litellm_status_changed = Signal(str)   # "live" | "offline"
    model_status_changed = Signal(str)     # "ready" | "not_found" | "unknown"
    model_list_updated = Signal(list)      # list of available model names

    def __init__(self, working_dir: str, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.working_dir = working_dir
        self.model_tag = DEFAULT_MODEL_TAG
        self.engine_mode = "litellm_chat"

        # Connection endpoints — live-mutable via update_urls(), no restart needed
        persisted = settings.load()
        self.ollama_base_url = persisted["ollama_base_url"]
        self.litellm_base_url = persisted["litellm_base_url"]
        self.litellm_api_key = persisted["litellm_api_key"]

        # Resolve model tag from existing configs
        self._resolve_model_tag()

        # Active worker references
        self._chat_worker: Optional[ChatWorker] = None
        self._model_manager: Optional[ModelManager] = None
        self._litellm_starter: Optional[LiteLLMStarter] = None
        self._status_worker: Optional[StatusWorker] = None
        self._litellm_proc = None  # spawned LiteLLM Popen, terminated on shutdown
        self._preloader: Optional[ModelPreloader] = None
        self._preloaded = False  # preload the weights once per session

        # Conversation history
        self.conversation: List[Dict[str, str]] = []

        # Whether the memory vault is injected into the system prompt. Notes are
        # always kept on disk; this only controls whether they are sent.
        self._memory_enabled = True

        # Inference settings (defaults match Modelfile)
        self.temperature = 0.2
        self.num_ctx = 32768
        self.max_tokens = 8192

        # Status polling timer
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self.check_status)
        self._poll_timer.start(5000)  # every 5 seconds

        # Initial check
        QTimer.singleShot(500, self.check_status)

    def _resolve_model_tag(self):
        """Try to read model tag and engine mode from existing config.yaml or Modelfile."""
        config_path = Path(self.working_dir) / "config.yaml"
        if config_path.exists():
            try:
                content = config_path.read_text(encoding="utf-8")
                tag_match = re.search(r'model_name:\s*([^\s]+)', content)
                # config.yaml writes the wildcard quoted ("*"), so reject both forms
                # — otherwise model_tag becomes the 3-character string '"*"'.
                if tag_match and tag_match.group(1).strip('"') != "*":
                    self.model_tag = tag_match.group(1)

                if "ollama_chat/" in content:
                    self.engine_mode = "litellm_chat"
                elif "ollama/" in content:
                    self.engine_mode = "litellm_standard"
                else:
                    self.engine_mode = "direct"
                return
            except Exception:
                pass

        # Fallback: derive from GGUF filename
        gguf_files = list(Path(self.working_dir).glob("*.gguf"))
        if gguf_files:
            self.model_tag = derive_model_tag(gguf_files[0].name)

    def check_status(self):
        """Poll both Ollama and LiteLLM APIs in a background thread without blocking the GUI."""
        if self._status_worker and self._status_worker.isRunning():
            return  # Previous poll still in-flight, avoid piling up

        worker = StatusWorker(
            ollama_base_url=self.ollama_base_url,
            litellm_base_url=self.litellm_base_url,
            model_tag=self.model_tag,
            parent=self,
        )
        worker.status_ready.connect(self._on_status_ready)
        self._status_worker = worker
        worker.start()

    def _on_status_ready(self, ollama_status: str, litellm_status: str, model_status: str, model_names: list):
        self.ollama_status_changed.emit(ollama_status)
        self.litellm_status_changed.emit(litellm_status)
        self.model_status_changed.emit(model_status)
        if model_names:
            self.model_list_updated.emit(model_names)
        # Spec Step 1: first time the model is confirmed present, warm it up.
        if model_status == "ready" and not self._preloaded:
            self._preloaded = True
            self.preload_model()

    def preload_model(self) -> Optional[ModelPreloader]:
        """Kick off the weight preload (spec Step 1) in a background thread."""
        if self._preloader and self._preloader.isRunning():
            return self._preloader
        preloader = ModelPreloader(model_tag=self.model_tag, parent=self)
        self._preloader = preloader
        preloader.start()
        return preloader

    def get_system_prompt(self) -> str:
        """Get the current system prompt if one is set.

        Returns the persona *without* any injected memory block. Callers that
        write this value back out (the Settings text box) need the bare persona —
        otherwise every Apply would round-trip a block that compose_system_prompt
        is about to append again.
        """
        return memory_vault.strip_vault(self._raw_system_prompt())

    def _raw_system_prompt(self) -> str:
        """The conversation's system message exactly as stored, vault included."""
        if self.conversation and self.conversation[0].get("role") == "system":
            return self.conversation[0].get("content", "")
        return ""

    def set_system_prompt(self, prompt: str):
        """Set or update the system prompt at the start of the conversation.

        The persona is stored bare and the memory block is composed on top, so
        the vault can change without the persona picking up a stale copy.
        """
        persona = memory_vault.strip_vault(prompt)
        self._sync_system_message(persona)

    def set_memory_enabled(self, enabled: bool):
        """Turn vault injection on or off and re-compose immediately."""
        self._memory_enabled = bool(enabled)
        self._sync_system_message(self.get_system_prompt())

    def refresh_memory(self):
        """Re-compose the system prompt from the current vault contents.

        Called after the vault is edited. With the vault empty or disabled this
        is a no-op on the persona, so a model with its own baked-in SYSTEM block
        keeps it.
        """
        self._sync_system_message(self.get_system_prompt())

    def _sync_system_message(self, persona: str):
        """Rebuild conversation[0] from the persona plus the vault block."""
        composed = memory_vault.compose_system_prompt(
            persona, enabled=self._memory_enabled
        )
        has_system = bool(self.conversation) and self.conversation[0].get("role") == "system"
        if composed:
            if has_system:
                self.conversation[0]["content"] = composed
            else:
                self.conversation.insert(0, {"role": "system", "content": composed})
        elif has_system:
            self.conversation.pop(0)

    def get_engine_mode(self) -> str:
        return self.engine_mode

    def set_engine_mode(self, mode: str):
        if mode in ("direct", "litellm_standard", "litellm_chat"):
            self.engine_mode = mode

    def send_message(self, user_message: str) -> ChatWorker:
        """
        Send a message and start streaming the response.
        Uses direct Ollama or LiteLLM depending on engine_mode.
        Returns the ChatWorker so the GUI can connect to its signals.
        """
        self.conversation.append({
            "role": "user",
            "content": user_message,
        })

        worker = ChatWorker(
            messages=list(self.conversation),  # copy
            model=self.model_tag,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            num_ctx=self.num_ctx,
            engine_mode=self.engine_mode,
            ollama_base_url=self.ollama_base_url,
            litellm_base_url=self.litellm_base_url,
            litellm_api_key=self.litellm_api_key,
            parent=self,
        )

        self._chat_worker = worker
        return worker

    def finalize_response(self, full_response: str):
        """Called when generation completes — adds assistant message to history."""
        # Strip the "(generation stopped)" marker if present for clean history
        clean = full_response.replace("\n\n*(generation stopped)*", "")
        self.conversation.append({
            "role": "assistant",
            "content": clean,
        })

    def stop_generation(self):
        """Cancel the current generation if one is running."""
        if self._chat_worker and self._chat_worker.isRunning():
            self._chat_worker.cancel()

    def is_generating(self) -> bool:
        """Check if a generation is currently in progress."""
        return self._chat_worker is not None and self._chat_worker.isRunning()

    def clear_conversation(self):
        """Reset conversation history (preserves system prompt if set)."""
        system_prompt = None
        if self.conversation and self.conversation[0].get("role") == "system":
            system_prompt = self.conversation[0]
        self.conversation = []
        if system_prompt:
            self.conversation.append(system_prompt)

    def create_model(self) -> ModelManager:
        """
        Kick off model creation from the Modelfile in a background thread.
        Returns the ModelManager so the GUI can connect to its signals.
        """
        manager = ModelManager(
            model_tag=self.model_tag,
            working_dir=self.working_dir,
            parent=self,
        )
        self._model_manager = manager
        return manager

    def start_litellm(self) -> LiteLLMStarter:
        """
        Start the LiteLLM proxy in a background thread.
        Returns the LiteLLMStarter so the GUI can connect to its signals.
        """
        config_path = str(Path(self.working_dir) / "config.yaml")
        starter = LiteLLMStarter(
            config_path=config_path,
            working_dir=self.working_dir,
            litellm_url=self.litellm_base_url,
            parent=self,
        )
        starter.proc_started.connect(self._remember_litellm_proc)
        self._litellm_starter = starter
        return starter

    def _remember_litellm_proc(self, proc):
        self._litellm_proc = proc

    def shutdown(self):
        """Terminate managed child processes (spec Step 5: process cleanup)."""
        # Stop background polling so nothing fires during teardown
        self._poll_timer.stop()

        for worker in (self._chat_worker, self._status_worker,
                       self._litellm_starter, self._preloader):
            if worker is not None and worker.isRunning():
                if worker is self._chat_worker:
                    worker.cancel()
                worker.quit()
                worker.wait(5000)
                if worker.isRunning():
                    worker.terminate()
                    worker.wait(1000)

        proc = self._litellm_proc
        self._litellm_proc = None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
        except Exception:
            pass

    def get_model_tag(self) -> str:
        return self.model_tag

    def set_model_tag(self, tag: str):
        self.model_tag = tag

    def installed_models(self) -> List[str]:
        """Names (without ':latest') of the models currently registered in Ollama.

        Synchronous — used at model-switch time so the GUI can warn immediately
        when the selected weights have not been built into Ollama yet. Returns an
        empty list when Ollama is offline.
        """
        try:
            resp = requests.get(f"{self.ollama_base_url}/api/tags", timeout=2)
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                return [m.get("name", "").split(":")[0] for m in models]
        except Exception:
            pass
        return []

    def update_settings(self, temperature: float, num_ctx: int, max_tokens: int = 8192, engine_mode: Optional[str] = None):
        """Update inference settings."""
        self.temperature = temperature
        self.num_ctx = num_ctx
        self.max_tokens = max_tokens
        if engine_mode:
            self.set_engine_mode(engine_mode)

    def get_urls(self) -> Dict[str, str]:
        """Current connection endpoints."""
        return {
            "ollama_base_url": self.ollama_base_url,
            "litellm_base_url": self.litellm_base_url,
            "litellm_api_key": self.litellm_api_key,
        }

    def update_urls(
        self,
        ollama_base_url: Optional[str] = None,
        litellm_base_url: Optional[str] = None,
        litellm_api_key: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        Hot-swap connection endpoints.

        Takes effect immediately — the running session polls the new addresses
        right away, no restart required. Persisted to .state/settings.json.
        Any argument left as None keeps its current value, and empty strings are
        ignored so a blank field can never wipe a working endpoint.
        """
        updates = {
            "ollama_base_url": normalize_url(ollama_base_url) if ollama_base_url is not None else None,
            "litellm_base_url": normalize_url(litellm_base_url) if litellm_base_url is not None else None,
            "litellm_api_key": litellm_api_key if litellm_api_key is not None else None,
        }

        changed = False
        for key, value in updates.items():
            if value is None:
                continue
            if value and getattr(self, key) != value:
                setattr(self, key, value)
                changed = True

        if changed:
            settings.save({
                "ollama_base_url": self.ollama_base_url,
                "litellm_base_url": self.litellm_base_url,
                "litellm_api_key": self.litellm_api_key,
            })
            # Re-poll immediately so the status LEDs reflect the new endpoints
            self.check_status()

        return self.get_urls()
