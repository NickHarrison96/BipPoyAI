"""Offline microphone capture, Silero ONNX VAD, and CPU Whisper transcription."""

import importlib.metadata
import os
import queue
import sys
import threading
from collections import deque
from pathlib import Path

from PySide6.QtCore import QThread, Signal

SAMPLE_RATE = 16000
CHUNK_SIZE = 512
SILENCE_CHUNKS = 25
MAX_UTTERANCE_CHUNKS = 30 * SAMPLE_RATE // CHUNK_SIZE


def vad_model_path() -> Path:
    override = os.environ.get("CAYDE_VAD_MODEL")
    if override:
        path = Path(override).expanduser()
    elif getattr(sys, "frozen", False):
        path = Path(sys._MEIPASS) / "silero_vad" / "data" / "silero_vad.onnx"
    else:
        try:
            path = Path(importlib.metadata.distribution("silero-vad").locate_file(
                "silero_vad/data/silero_vad.onnx"
            ))
        except importlib.metadata.PackageNotFoundError as exc:
            raise RuntimeError("Install the optional voice dependencies to enable the microphone.") from exc
    if not path.is_file():
        raise RuntimeError("Silero ONNX weights are unavailable offline. Install the voice extras first.")
    return path


def create_vad_session(ort, model_path: Path, device_id=None):
    options = ort.SessionOptions()
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.enable_mem_pattern = False
    if device_id is not None and "DmlExecutionProvider" in ort.get_available_providers():
        providers = [("DmlExecutionProvider", {"device_id": device_id}), "CPUExecutionProvider"]
        try:
            session = ort.InferenceSession(str(model_path), sess_options=options, providers=providers)
            if session.get_providers()[0] == "DmlExecutionProvider":
                return session, "DirectML"
        except Exception:
            pass
    session = ort.InferenceSession(str(model_path), sess_options=options, providers=["CPUExecutionProvider"])
    return session, "CPU"


class SileroVad:
    def __init__(self, session, np):
        self.session = session
        self.np = np
        self.reset()

    def reset(self):
        self.state = self.np.zeros((2, 1, 128), dtype=self.np.float32)
        self.context = self.np.zeros((1, 64), dtype=self.np.float32)

    def probability(self, chunk):
        audio = self.np.concatenate((self.context, chunk.reshape(1, CHUNK_SIZE)), axis=1)
        output, self.state = self.session.run(None, {
            "input": audio,
            "state": self.state,
            "sr": self.np.array(SAMPLE_RATE, dtype=self.np.int64),
        })
        self.context = audio[:, -64:]
        return float(output[0, 0])


class UtteranceBuffer:
    def __init__(self, np, threshold=0.5):
        self.np = np
        self.threshold = threshold
        self.preroll = deque(maxlen=8)
        self.reset()

    def reset(self):
        self.speaking = False
        self.silence = 0
        self.chunks = []
        self.preroll.clear()

    def feed(self, chunk, probability):
        if probability > self.threshold:
            if not self.speaking:
                self.speaking = True
                self.chunks = list(self.preroll)
            self.silence = 0
            self.chunks.append(chunk)
        elif self.speaking:
            self.chunks.append(chunk)
            self.silence += 1
        else:
            self.preroll.append(chunk)
        if self.speaking and (self.silence >= SILENCE_CHUNKS or len(self.chunks) >= MAX_UTTERANCE_CHUNKS):
            utterance = self.np.concatenate(self.chunks).astype(self.np.float32)
            self.reset()
            return utterance
        return None


class SpeechListener(QThread):
    transcribed = Signal(str)
    status_changed = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, parent=None, dml_device_id=None):
        super().__init__(parent)
        self.dml_device_id = dml_device_id
        self.audio_input_queue = queue.Queue(maxsize=128)
        self.transcription_queue = queue.Queue(maxsize=4)
        self._stop_event = threading.Event()
        self._overrun = False

    def stop(self):
        self._stop_event.set()

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            self._overrun = True
        try:
            self.audio_input_queue.put_nowait(indata[:, 0].copy())
        except queue.Full:
            self._overrun = True

    def _transcribe(self, ready):
        try:
            from faster_whisper import WhisperModel
            model = WhisperModel("turbo", device="cpu", compute_type="int8",
                                 local_files_only=True, use_auth_token=False)
        except Exception as exc:
            self._startup_error = str(exc)
            ready.set()
            return
        ready.set()
        while not self._stop_event.is_set():
            try:
                utterance = self.transcription_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                segments, _ = model.transcribe(utterance, beam_size=1, language="en")
                text = "".join(segment.text for segment in segments).strip()
                if text and not self._stop_event.is_set():
                    self.transcribed.emit(text)
            except Exception as exc:
                self.error_occurred.emit(f"Transcription failed: {exc}")
            finally:
                self.transcription_queue.task_done()

    def run(self):
        try:
            import numpy as np
            import onnxruntime as ort
            import sounddevice as sd

            device_id = self.dml_device_id
            if device_id is None and os.environ.get("CAYDE_VAD_DML_DEVICE_ID"):
                device_id = int(os.environ["CAYDE_VAD_DML_DEVICE_ID"])
            session, provider = create_vad_session(ort, vad_model_path(), device_id)
            if device_id is not None and provider == "CPU":
                self.status_changed.emit("DirectML unavailable; VAD is using CPU")
            else:
                self.status_changed.emit(f"VAD: {provider} | Whisper: CPU int8")
            vad = SileroVad(session, np)
            utterances = UtteranceBuffer(np)

            ready = threading.Event()
            self._startup_error = ""
            transcriber = threading.Thread(target=self._transcribe, args=(ready,), daemon=True)
            transcriber.start()
            while not ready.wait(0.1):
                if self._stop_event.is_set():
                    return
            if self._startup_error:
                raise RuntimeError(f"Offline Whisper Turbo is unavailable: {self._startup_error}")
            if self._stop_event.is_set():
                return

            device = sd.query_devices(kind="input")
            channels = int(device["max_input_channels"])
            if channels < 1:
                raise RuntimeError("No microphone input channels available")
            with sd.InputStream(device=None, channels=channels, samplerate=SAMPLE_RATE,
                                blocksize=CHUNK_SIZE, callback=self._audio_callback):
                self.status_changed.emit(f"Listening: {device['name']}")
                while not self._stop_event.is_set():
                    try:
                        chunk = self.audio_input_queue.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    if self._overrun:
                        self._overrun = False
                        vad.reset()
                        utterances.reset()
                        self.status_changed.emit("Audio overrun; incomplete phrase discarded")
                    phrase = utterances.feed(chunk, vad.probability(chunk))
                    if phrase is not None:
                        try:
                            self.transcription_queue.put_nowait(phrase)
                        except queue.Full:
                            self.status_changed.emit("Transcription queue full; phrase discarded")
        except Exception as exc:
            if not self._stop_event.is_set():
                self.error_occurred.emit(str(exc))
        finally:
            self._stop_event.set()
