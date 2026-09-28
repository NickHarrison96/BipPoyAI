"""
Backend Engine for Qwythos AI.

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
from configs import derive_model_tag


# ─── Constants ────────────────────────────────────────────────────────────────

DEFAULT_OLLAMA_BASE_URL = settings.DEFAULTS["ollama_base_url"]
DEFAULT_LITELLM_BASE_URL = settings.DEFAULTS["litellm_base_url"]
DEFAULT_LITELLM_API_KEY = settings.DEFAULTS["litellm_api_key"]
DEFAULT_MODEL_TAG = "qwythos-9b-claude-mythos-5-1m-mtp-q4_k_m"


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

        # Check LiteLLM — keep timeout short so background thread finishes promptly
        try:
            resp = requests.get(f"{self.litellm_base_url}/health", timeout=3)
            if resp.status_code == 200:
                litellm_status = "live"
        except Exception:
            pass

        self.status_ready.emit(ollama_status, litellm_status, model_status, model_names)


# ─── LiteLLM Process Manager ─────────────────────────────────────────────────

class LiteLLMStarter(QThread):
    """
    Starts the LiteLLM proxy server in a background process.
    """
    progress_update = Signal(str)
    started_ok = Signal()
    started_error = Signal(str)

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

            port = urlparse(self.litellm_url).port or 4000
            self.progress_update.emit(f"Starting LiteLLM proxy on port {port}...")

            cmd = ["litellm", "--config", self.config_path, "--port", str(port)]

            # Spawn in a separate console window on Windows
            if os.name == 'nt':
                subprocess.Popen(
                    cmd,
                    cwd=self.working_dir,
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
            else:
                subprocess.Popen(
                    cmd,
                    cwd=self.working_dir,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

            # Wait for it to come up. LiteLLM boots slowly (~1 min) and its
            # /health endpoint itself takes ~3s to answer, so poll patiently.
            self.progress_update.emit("Waiting for LiteLLM to initialize...")
            for attempt in range(60):  # up to ~2 minutes
                time.sleep(2)
                try:
                    r = requests.get(f"{self.litellm_url}/health", timeout=10)
                    if r.status_code == 200:
                        self.progress_update.emit("LiteLLM proxy is live!")
                        self.started_ok.emit()
                        return
                except Exception:
                    pass

            # If we get here, it didn't start in time
            self.started_error.emit(
                "LiteLLM started but didn't respond within 2 minutes.\n"
                "Check the LiteLLM console window for errors."
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
                timeout=300,
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

        # Conversation history
        self.conversation: List[Dict[str, str]] = []

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
                if tag_match and tag_match.group(1) != "*":
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

    def get_system_prompt(self) -> str:
        """Get the current system prompt if one is set."""
        if self.conversation and self.conversation[0].get("role") == "system":
            return self.conversation[0].get("content", "")
        return ""

    def set_system_prompt(self, prompt: str):
        """Set or update the system prompt at the start of the conversation."""
        prompt = (prompt or "").strip()
        if self.conversation and self.conversation[0].get("role") == "system":
            if prompt:
                self.conversation[0]["content"] = prompt
            else:
                self.conversation.pop(0)
        elif prompt:
            self.conversation.insert(0, {"role": "system", "content": prompt})

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
        self._litellm_starter = starter
        return starter

    def get_model_tag(self) -> str:
        return self.model_tag

    def set_model_tag(self, tag: str):
        self.model_tag = tag

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
        right away, no restart required. Persisted to ~/.qwythos/settings.json.
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
