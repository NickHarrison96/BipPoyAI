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
import requests


# ─── Constants ────────────────────────────────────────────────────────────────

OLLAMA_BASE_URL = "http://127.0.0.1:11434"
LITELLM_BASE_URL = "http://127.0.0.1:4000"
LITELLM_API_KEY = "sk-ant-api03-local-mock-key-for-ollama-bypass-000000000000000000"
DEFAULT_MODEL_TAG = "qwythos-9b-claude-mythos-5-1m-mtp-q4_k_m"


# ─── Data helpers ─────────────────────────────────────────────────────────────

def derive_model_tag(gguf_filename: str) -> str:
    """Derive a valid Ollama model tag from a GGUF filename."""
    stem = Path(gguf_filename).stem
    return re.sub(r'[^a-z0-9._-]', '-', stem.lower())


# ─── Chat Worker (background thread for streaming inference) ──────────────────

class ChatWorker(QThread):
    """
    Runs a streaming /v1/chat/completions request against LiteLLM in a
    background thread. Emits tokens one-by-one so the GUI can render them live.
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
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.messages = messages
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._cancelled = False

    def cancel(self):
        """Request cancellation of the in-flight generation."""
        self._cancelled = True

    def run(self):
        full_response = ""
        token_count = 0
        start_time = time.time()

        try:
            # LiteLLM exposes an OpenAI-compatible chat completions endpoint
            payload = {
                "model": self.model,
                "messages": self.messages,
                "stream": True,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {LITELLM_API_KEY}",
            }

            resp = requests.post(
                f"{LITELLM_BASE_URL}/v1/chat/completions",
                json=payload,
                headers=headers,
                stream=True,
                timeout=600,
            )
            resp.raise_for_status()

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

        except requests.ConnectionError:
            self.error_occurred.emit(
                "Cannot connect to LiteLLM proxy on port 4000.\n"
                "Click 'Start LiteLLM' to launch the proxy, or check that Ollama is running."
            )
        except requests.Timeout:
            self.error_occurred.emit(
                "Request to LiteLLM timed out. The model may be too large for your hardware."
            )
        except requests.HTTPError as e:
            error_body = ""
            try:
                error_body = e.response.text[:500]
            except Exception:
                pass
            self.error_occurred.emit(
                f"LiteLLM API error (HTTP {e.response.status_code}):\n{error_body}"
            )
        except Exception as e:
            self.error_occurred.emit(f"Unexpected error: {str(e)}")


# ─── LiteLLM Process Manager ─────────────────────────────────────────────────

class LiteLLMStarter(QThread):
    """
    Starts the LiteLLM proxy server in a background process.
    """
    progress_update = Signal(str)
    started_ok = Signal()
    started_error = Signal(str)

    def __init__(self, config_path: str, working_dir: str, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.config_path = config_path
        self.working_dir = working_dir

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

            self.progress_update.emit("Starting LiteLLM proxy on port 4000...")

            cmd = ["litellm", "--config", self.config_path, "--port", "4000"]

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

            # Wait for it to come up
            self.progress_update.emit("Waiting for LiteLLM to initialize...")
            for attempt in range(20):  # up to 10 seconds
                time.sleep(0.5)
                try:
                    r = requests.get(f"{LITELLM_BASE_URL}/health", timeout=2)
                    if r.status_code == 200:
                        self.progress_update.emit("LiteLLM proxy is live!")
                        self.started_ok.emit()
                        return
                except Exception:
                    pass

            # If we get here, it didn't start in time
            self.started_error.emit(
                "LiteLLM started but didn't respond within 10 seconds.\n"
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

        # Resolve model tag from existing configs
        self._resolve_model_tag()

        # Active worker references
        self._chat_worker: Optional[ChatWorker] = None
        self._model_manager: Optional[ModelManager] = None
        self._litellm_starter: Optional[LiteLLMStarter] = None

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
        """Try to read model tag from existing config.yaml or Modelfile."""
        # First try config.yaml (has the actual model_name used by LiteLLM)
        config_path = Path(self.working_dir) / "config.yaml"
        if config_path.exists():
            try:
                content = config_path.read_text(encoding="utf-8")
                tag_match = re.search(r'model_name:\s*([^\s]+)', content)
                if tag_match and tag_match.group(1) != "*":
                    self.model_tag = tag_match.group(1)
                    return
            except Exception:
                pass

        # Fallback: derive from GGUF filename
        gguf_files = list(Path(self.working_dir).glob("*.gguf"))
        if gguf_files:
            self.model_tag = derive_model_tag(gguf_files[0].name)

    def check_status(self):
        """Poll both Ollama and LiteLLM APIs and emit status signals."""
        # Check Ollama
        try:
            resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
            if resp.status_code == 200:
                self.ollama_status_changed.emit("live")

                data = resp.json()
                models = data.get("models", [])
                model_names = [m.get("name", "").split(":")[0] for m in models]
                self.model_list_updated.emit(model_names)

                if self.model_tag in model_names:
                    self.model_status_changed.emit("ready")
                else:
                    self.model_status_changed.emit("not_found")
            else:
                self.ollama_status_changed.emit("offline")
                self.model_status_changed.emit("unknown")
        except Exception:
            self.ollama_status_changed.emit("offline")
            self.model_status_changed.emit("unknown")

        # Check LiteLLM
        try:
            resp = requests.get(f"{LITELLM_BASE_URL}/health", timeout=3)
            if resp.status_code == 200:
                self.litellm_status_changed.emit("live")
            else:
                self.litellm_status_changed.emit("offline")
        except Exception:
            self.litellm_status_changed.emit("offline")

    def set_system_prompt(self, prompt: str):
        """Set or update the system prompt at the start of the conversation."""
        if self.conversation and self.conversation[0].get("role") == "system":
            self.conversation[0]["content"] = prompt
        elif prompt:
            self.conversation.insert(0, {"role": "system", "content": prompt})

    def send_message(self, user_message: str) -> ChatWorker:
        """
        Send a message and start streaming the response via LiteLLM.
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
            parent=self,
        )
        self._litellm_starter = starter
        return starter

    def get_model_tag(self) -> str:
        return self.model_tag

    def set_model_tag(self, tag: str):
        self.model_tag = tag

    def update_settings(self, temperature: float, num_ctx: int, max_tokens: int = 8192):
        """Update inference settings."""
        self.temperature = temperature
        self.num_ctx = num_ctx
        self.max_tokens = max_tokens
