import importlib.util
import os
import sys
import threading
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication, QFrame

import voice_engine as ve


class Failure(Exception):
    pass


def check(condition, label):
    if not condition:
        raise Failure(label)


def wait_for(predicate, app=None, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if app is not None:
            app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    if app is not None:
        app.processEvents()
    return bool(predicate())


def test_raw_silero_cpu_state_feedback():
    if importlib.util.find_spec("onnxruntime") is None or importlib.util.find_spec("silero_vad") is None:
        print("  SKIP  raw Silero ONNX (voice extras not installed)")
        return
    import onnxruntime as ort

    session = ort.InferenceSession(str(ve.vad_model_path()), providers=["CPUExecutionProvider"])
    check(session.get_providers() == ["CPUExecutionProvider"], "raw session uses only CPU")
    state = np.zeros((2, 1, 128), dtype=np.float32)
    audio = np.zeros((1, ve.CHUNK_SIZE + 64), dtype=np.float32)
    initial_state = state.copy()
    outputs = []
    for _ in range(2):
        previous = state
        result, state = session.run(None, {
            "input": audio,
            "state": previous,
            "sr": np.array(ve.SAMPLE_RATE, dtype=np.int64),
        })
        check(result.shape == (1, 1) and np.isfinite(result).all(), "raw probability is finite")
        check(0 <= float(result[0, 0]) <= 1, "raw probability is in range")
        check(state.shape == initial_state.shape and np.isfinite(state).all(), "raw state shape and values")
        outputs.append(state.copy())
    check(not np.array_equal(outputs[0], initial_state), "first inference updates the state")
    check(not np.array_equal(outputs[1], outputs[0]), "second inference feeds back and advances state")


def fake_ort(available, actual=None, fail_dml=False):
    calls = []

    class Session:
        def __init__(self, providers):
            self.providers = providers

        def get_providers(self):
            if actual is not None:
                return actual
            return [p[0] if isinstance(p, tuple) else p for p in self.providers]

    def inference_session(model, *, sess_options, providers):
        calls.append((model, sess_options, providers))
        if fail_dml and isinstance(providers[0], tuple):
            raise RuntimeError("DirectML unavailable")
        return Session(providers)

    return SimpleNamespace(
        SessionOptions=lambda: SimpleNamespace(execution_mode=None, enable_mem_pattern=True),
        ExecutionMode=SimpleNamespace(ORT_SEQUENTIAL="sequential"),
        get_available_providers=lambda: available,
        InferenceSession=inference_session,
    ), calls


def test_vad_cpu_fallback_without_dml():
    ort, calls = fake_ort(["CPUExecutionProvider"])
    session, provider = ve.create_vad_session(ort, Path("model.onnx"), device_id=2)
    check(provider == "CPU" and session.get_providers() == ["CPUExecutionProvider"], "CPU fallback")
    check(len(calls) == 1 and calls[0][2] == ["CPUExecutionProvider"], "no DML session attempted")
    check(calls[0][1].execution_mode == "sequential", "sequential execution set")
    check(calls[0][1].enable_mem_pattern is False, "memory pattern disabled")


def test_vad_dml_explicit_device_two():
    ort, calls = fake_ort(["DmlExecutionProvider", "CPUExecutionProvider"])
    session, provider = ve.create_vad_session(ort, Path("model.onnx"), device_id=2)
    check(provider == "DirectML", "DML selected")
    check(len(calls) == 1 and calls[0][0] == "model.onnx", "model path forwarded")
    check(calls[0][2] == [("DmlExecutionProvider", {"device_id": 2}), "CPUExecutionProvider"],
          "explicit DML device ID 2 with CPU fallback")
    check(session.get_providers()[0] == "DmlExecutionProvider", "DML provider active")


def test_vad_dml_failed_session_falls_back():
    ort, calls = fake_ort(["DmlExecutionProvider", "CPUExecutionProvider"], fail_dml=True)
    session, provider = ve.create_vad_session(ort, Path("model.onnx"), device_id=2)
    check(provider == "CPU" and session.get_providers() == ["CPUExecutionProvider"], "DML failure falls back")
    check(len(calls) == 2 and calls[1][2] == ["CPUExecutionProvider"], "fresh CPU session created")


def chunk(value):
    return np.full(ve.CHUNK_SIZE, value, dtype=np.float32)


def test_utterance_preroll_and_silence_finalization():
    buffer = ve.UtteranceBuffer(np)
    for value in range(1, 10):
        check(buffer.feed(chunk(value), 0.0) is None, "quiet preroll does not finalize")
    check(len(buffer.preroll) == 8, "preroll bounded to eight chunks")
    check(buffer.feed(chunk(10), 0.8) is None, "speech begins with preroll")
    check(buffer.feed(chunk(11), 0.0) is None, "short pause does not finalize")
    check(buffer.feed(chunk(12), 0.9) is None and buffer.silence == 0, "speech resets silence count")
    for i in range(ve.SILENCE_CHUNKS - 1):
        check(buffer.feed(chunk(20 + i), 0.0) is None, "phrase survives until silence threshold")
    phrase = buffer.feed(chunk(99), 0.0)
    expected = list(range(2, 10)) + [10, 11, 12] + list(range(20, 20 + ve.SILENCE_CHUNKS - 1)) + [99]
    check(phrase is not None and phrase.dtype == np.float32, "finalized float32 utterance")
    check(phrase.size == len(expected) * ve.CHUNK_SIZE, "all preroll, speech and silence retained")
    check(np.array_equal(phrase[::ve.CHUNK_SIZE], expected), "utterance order and preroll truncation")
    check(not buffer.speaking and not buffer.preroll and not buffer.chunks and buffer.silence == 0,
          "finalization resets buffer")


def test_utterance_reset_and_max_length():
    buffer = ve.UtteranceBuffer(np)
    buffer.feed(chunk(1), 0.0)
    buffer.feed(chunk(2), 0.8)
    buffer.feed(chunk(3), 0.0)
    buffer.reset()
    check(not buffer.speaking and not buffer.preroll and not buffer.chunks and buffer.silence == 0,
          "explicit reset drops incomplete phrase")
    with patch.object(ve, "MAX_UTTERANCE_CHUNKS", 3):
        buffer.feed(chunk(4), 0.8)
        buffer.feed(chunk(5), 0.9)
        phrase = buffer.feed(chunk(6), 0.9)
    check(phrase is not None and np.array_equal(phrase[::ve.CHUNK_SIZE], [4, 5, 6]),
          "max-length finalization does not include discarded audio")


def test_audio_callback_queue_is_bounded_and_capture_only():
    listener = ve.SpeechListener()
    stereo = np.column_stack((chunk(1), chunk(2)))
    listener._audio_callback(stereo, ve.CHUNK_SIZE, None, None)
    stereo[0, 0] = -1
    check(listener.audio_input_queue.get_nowait()[0] == 1, "callback copies first channel")
    for index in range(listener.audio_input_queue.maxsize + 1):
        listener._audio_callback(np.column_stack((chunk(index), chunk(-1))), ve.CHUNK_SIZE, None, None)
    check(listener.audio_input_queue.qsize() == listener.audio_input_queue.maxsize, "audio queue stays bounded")
    check(listener._overrun, "overrun flagged when input exceeds capacity")
    check(listener.audio_input_queue.get_nowait()[0] == 0, "oldest buffered audio not overwritten")
    check(listener.transcription_queue.empty(), "callback does not transcribe or enqueue phrases")


def test_offline_whisper_initialization_transcription_and_error():
    calls = []
    options = []
    fake_module = ModuleType("faster_whisper")

    class WhisperModel:
        def __init__(self, name, **kwargs):
            options.append((name, kwargs))

        def transcribe(self, utterance, **kwargs):
            calls.append((utterance, kwargs))
            if len(calls) == 3:
                raise ValueError("synthetic failure")
            return [SimpleNamespace(text=" hello"), SimpleNamespace(text=" world ")], None

    fake_module.WhisperModel = WhisperModel
    app = QApplication.instance() or QApplication([])
    listener = ve.SpeechListener()
    ready = threading.Event()
    texts = []
    errors = []
    listener.transcribed.connect(texts.append)
    listener.error_occurred.connect(errors.append)
    with patch.dict(sys.modules, {"faster_whisper": fake_module}):
        worker = threading.Thread(target=listener._transcribe, args=(ready,), daemon=True)
        worker.start()
        try:
            check(ready.wait(2), "Whisper ready signal")
            check(getattr(listener, "_startup_error", "") == "", "offline model initialized")
            for index in range(3):
                listener.transcription_queue.put_nowait(chunk(index))
            check(wait_for(lambda: len(calls) == 3 and len(texts) == 2 and len(errors) == 1, app),
                  "transcription and error signals received")
            check(options == [("turbo", {"device": "cpu", "compute_type": "int8",
                                          "local_files_only": True, "use_auth_token": False})],
                  "model loaded once offline on CPU int8")
            check(texts == ["hello world", "hello world"], "segment text joined and stripped")
            check(errors == ["Transcription failed: synthetic failure"], "transcription error emitted")
            check(all(kwargs == {"beam_size": 1, "language": "en"} for _, kwargs in calls),
                  "bounded English transcription settings")
            check(listener.transcription_queue.unfinished_tasks == 0, "queue tasks acknowledged")
        finally:
            listener.stop()
            worker.join(2)
            check(not worker.is_alive(), "transcriber thread stops")


class FakeChatWorker(QObject):
    token_received = Signal(str)
    generation_complete = Signal(str)
    error_occurred = Signal(str)
    stats_update = Signal(dict)

    def __init__(self):
        super().__init__()
        self.started = False

    def start(self):
        self.started = True


class FakeBackend(QObject):
    ollama_status_changed = Signal(str)
    litellm_status_changed = Signal(str)
    model_status_changed = Signal(str)

    def __init__(self, working_dir):
        super().__init__()
        self.working_dir = working_dir
        self.mode = "direct"
        self.generating = False
        self.sent = []
        self.conversation = []
        self.worker = None

    def get_engine_mode(self):
        return self.mode

    def is_generating(self):
        return self.generating

    def send_message(self, text, *, engine_mode=None, model_tag=None):
        self.sent.append((text, engine_mode, model_tag))
        self.generating = True
        self.worker = FakeChatWorker()
        return self.worker

    def finalize_response(self, text):
        self.generating = False
        self.conversation.append({"role": "assistant", "content": text})

    def shutdown(self):
        pass


class FakeSettingsPanel(QFrame):
    model_rebuild_requested = Signal()
    launch_claude_requested = Signal()

    def __init__(self, backend):
        super().__init__()


def test_gui_voice_queue_routes_through_litellm_without_clobbering_input():
    import main as gui

    app = QApplication.instance() or QApplication([])
    with patch.object(gui, "OllamaBackend", FakeBackend), \
         patch.object(gui, "SettingsPanel", FakeSettingsPanel), \
         patch.object(gui.MainWindow, "_setup_tray", lambda self: setattr(self, "_tray", None)), \
         patch.object(gui.MainWindow, "_maybe_autostart_litellm", lambda self: None), \
         patch.object(gui.history, "auto_save", lambda conversation: None):
        window = gui.MainWindow()
        window._voice_worker = SimpleNamespace(isRunning=lambda: True, stop=lambda: None, wait=lambda ms: None)
        try:
            window._ollama_live = window._model_ready = True
            window._litellm_live = False
            window._on_speech_transcribed(" offline ")
            check(list(window._pending_voice) == ["offline"] and not window.backend.sent,
                  "voice waits for LiteLLM even in direct mode")
            window._litellm_live = True
            window.chat_input.setPlainText("draft typed text")
            window._drain_voice_queue()
            check(window.chat_input.toPlainText() == "draft typed text" and not window.backend.sent,
                  "typed text remains untouched while voice is queued")
            window.chat_input.clear()
            check(wait_for(lambda: len(window.backend.sent) == 1, app), "idle queued phrase auto-drained")
            check(window.backend.sent == [("offline", "litellm_chat", None)],
                  "voice overrides direct mode for LiteLLM chat")
            check(window.backend.worker.started and window.chat_input.toPlainText() == "",
                  "fake chat worker started without a service")
            window._on_speech_transcribed(" next ")
            check(list(window._pending_voice) == ["next"] and len(window.backend.sent) == 1,
                  "speech queued while generation is busy")
            window.backend.worker.generation_complete.emit("response")
            check(wait_for(lambda: len(window.backend.sent) == 2, app),
                  "busy phrase auto-drained after generation completes")
            check(window.backend.sent[1] == ("next", "litellm_chat", None) and not window._pending_voice,
                  "second phrase routed through LiteLLM exactly once")
        finally:
            window._voice_worker = None
            window.close()
            app.processEvents()


def test_spoken_role_prefix_uses_only_registered_alias():
    import main as gui

    app = QApplication.instance() or QApplication([])
    with patch.object(gui, "OllamaBackend", FakeBackend), \
         patch.object(gui, "SettingsPanel", FakeSettingsPanel), \
         patch.object(gui.MainWindow, "_setup_tray", lambda self: setattr(self, "_tray", None)), \
         patch.object(gui.MainWindow, "_maybe_autostart_litellm", lambda self: None), \
         patch.object(gui, "load_role_aliases", return_value={"coding": "qwen2.5-coder:7b"}):
        window = gui.MainWindow()
        window._voice_worker = SimpleNamespace(isRunning=lambda: True, stop=lambda: None, wait=lambda ms: None)
        try:
            window._ollama_live = window._model_ready = window._litellm_live = True
            window._on_speech_transcribed("coding: write a test")
            check(window.backend.sent == [("write a test", "litellm_chat", "coding")],
                  "explicit coding request uses registered LiteLLM alias")
            window.backend.generating = False
            window._streaming_bubble = None
            window._on_speech_transcribed("vision: inspect the screenshot")
            check(len(window.backend.sent) == 1 and not window._pending_voice,
                  "unregistered vision never silently routes to the coding or active model")
        finally:
            window._voice_worker = None
            window.close()
            app.processEvents()


def test_backend_per_request_proxy_mode_preserves_typed_mode():
    import backend

    engine = backend.OllamaBackend(str(Path(__file__).resolve().parent))
    engine._poll_timer.stop()
    engine.set_engine_mode("direct")
    worker = engine.send_message("spoken", engine_mode="litellm_chat")
    check(worker.engine_mode == "litellm_chat", "voice worker uses the LiteLLM proxy")
    check(engine.get_engine_mode() == "direct", "typed mode remains direct")
    check(engine.conversation[-1] == {"role": "user", "content": "spoken"},
          "spoken turn enters the normal history")
    role_worker = engine.send_message("code", engine_mode="litellm_chat", model_tag="coding")
    check(role_worker.model == "coding" and engine.get_model_tag() != "coding",
          "per-request alias does not mutate the active model")


def test_qt_cross_thread_voice_signal_is_queued_to_gui_thread():
    app = QApplication.instance() or QApplication([])
    main_thread = threading.get_ident()
    listener = ve.SpeechListener()

    class Receiver(QObject):
        def __init__(self):
            super().__init__()
            self.received = []

        @Slot(str)
        def accept(self, text):
            self.received.append((text, threading.get_ident()))

    receiver = Receiver()
    listener.transcribed.connect(receiver.accept, Qt.QueuedConnection)
    thread = threading.Thread(target=lambda: listener.transcribed.emit("queued speech"))
    thread.start()
    thread.join(2)
    check(not thread.is_alive(), "sender thread finished")
    check(receiver.received == [], "cross-thread delivery waits for GUI event loop")
    check(wait_for(lambda: bool(receiver.received), app), "signal delivered by GUI event loop")
    check(receiver.received == [("queued speech", main_thread)], "slot runs on GUI thread")


TESTS = [
    test_raw_silero_cpu_state_feedback,
    test_vad_cpu_fallback_without_dml,
    test_vad_dml_explicit_device_two,
    test_vad_dml_failed_session_falls_back,
    test_utterance_preroll_and_silence_finalization,
    test_utterance_reset_and_max_length,
    test_audio_callback_queue_is_bounded_and_capture_only,
    test_offline_whisper_initialization_transcription_and_error,
    test_gui_voice_queue_routes_through_litellm_without_clobbering_input,
    test_qt_cross_thread_voice_signal_is_queued_to_gui_thread,
    test_spoken_role_prefix_uses_only_registered_alias,
    test_backend_per_request_proxy_mode_preserves_typed_mode,
]


def main():
    failed = 0
    for test in TESTS:
        try:
            test()
        except Exception as exc:
            failed += 1
            print(f"  FAIL  {test.__name__}: {type(exc).__name__}: {exc}")
        else:
            print(f"  PASS  {test.__name__}")
    print(f"{len(TESTS) - failed}/{len(TESTS)} voice tests passed")
    return int(failed != 0)


if __name__ == "__main__":
    sys.exit(main())
