# Tasks Document: Voice Pipeline Integration

## Overview

This document contains the implementation tasks for the voice pipeline integration feature. Tasks are ordered by priority and dependency.

---

## Phase 1: Base Voice Pipeline Integration (STT Only)

### Task 1.1: Add transcription_received signal to SpeechListener

**File**: `voice_engine.py`

**Description**: SpeechListener already has a `transcribed` signal. Verify it's emitting on GUI thread and create `transcription_received` alias if needed.

**Implementation**:
```python
# In voice_engine.py SpeechListener class
transcription_received = Signal(str)  # Add this signal
```

**Testing**: Verify signal emits when transcription completes

---

### Task 1.2: Connect transcription_received to main.py slot

**File**: `main.py`

**Description**: Connect SpeechListener's transcription_received signal to a new slot

**Implementation**:
```python
# In MainWindow.__init__()
self._voice_worker.transcription_received.connect(self._on_voice_transcribed, Qt.QueuedConnection)
```

**Testing**: Verify voice transcript appears in chat when speaking

---

### Task 1.3: Implement _on_voice_transcribed slot

**File**: `main.py`

**Description**: Parse transcript, validate role prefix, check service readiness, dispatch to backend

**Implementation**:
```python
@Slot(str)
def _on_voice_transcribed(self, text: str):
    """Handle voice transcript - parse role, validate, dispatch."""
    text = text.strip()
    if not text:
        return
    
    # Parse role prefix
    role, content = self._parse_voice_transcript(text)
    
    # Check service readiness
    if not (self._litellm_live and self._ollama_live and self._model_ready):
        self._show_voice_toast("LiteLLM/Ollama not ready")
        return
    
    # Validate role if specified
    if role:
        if role not in load_role_aliases(Path(self.backend.working_dir) / "config.yaml"):
            self._show_voice_toast(f"Role '{role}' not configured")
            return
    
    # Dispatch to backend
    self._send_text(content, engine_mode="litellm_chat", model_tag=role)
```

**Testing**: Verify transcript routes correctly to appropriate model

---

### Task 1.4: Add _parse_voice_transcript helper

**File**: `main.py`

**Description**: Parse transcript to extract role prefix and content

**Implementation**:
```python
def _parse_voice_transcript(self, text: str) -> Tuple[Optional[str], str]:
    """Parse voice transcript for role prefix.
    
    Returns: (role, content) tuple where role may be None.
    """
    pattern = r"^(default|reasoning|coding|vision|multimodal)\s*[:,-]\s*(.+)$"
    match = re.match(pattern, text, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).lower(), match.group(2).strip()
    return None, text
```

**Testing**: Verify parsing handles all role prefixes and formats

---

### Task 1.5: Add _show_voice_toast method

**File**: `main.py`

**Description**: Create toast notification for voice-specific messages

**Implementation**:
```python
def _show_voice_toast(self, message: str, duration: int = 3000):
    """Show temporary toast notification for voice events."""
    # Create QLabel, position in bottom-right, auto-dismiss
    toast = QLabel(message, self)
    toast.setStyleSheet(f"""
        background-color: {rgba('ember', 0.9)};
        color: {rgba('bone')};
        padding: 10px 15px;
        border-radius: 6px;
        font-family: {self.font().family()};
        font-size: 12px;
    """)
    toast.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint)
    toast.setAttribute(Qt.WA_ShowWithoutActivating)
    toast.move(self.width() - 250, self.height() - 100)
    toast.show()
    
    # Auto-dismiss timer
    QTimer.singleShot(duration, toast.close)
```

**Testing**: Verify toast displays and disappears correctly

---

### Task 1.6: Add service readiness checks

**File**: `main.py`

**Description**: Verify LiteLLM, Ollama, and model are ready before dispatch

**Implementation**:
```python
def _check_voice_service_readiness(self) -> Tuple[bool, str]:
    """Check if voice dispatch is safe."""
    if not self._litellm_live:
        return False, "LiteLLM not ready"
    if not self._ollama_live:
        return False, "Ollama not ready"
    if not self._model_ready:
        return False, "Model not loaded"
    return True, ""
```

**Testing**: Verify proper rejection when services unavailable

---

## Phase 2: Visual Context Capture (Optional - VISION ROLES)

### Task 2.1: Add mss and opencv-python to requirements.txt

**File**: `requirements.txt`

**Description**: Add screen capture and webcam dependencies

```
mss>=6.1.0
opencv-python>=4.8.0
```

---

### Task 2.2: Add VisualContextCapture class

**File**: `voice_engine.py`

**Description**: Create class for screen/webcam frame capture

**Implementation**:
```python
class VisualContextCapture:
    def __init__(self):
        self.last_frame = None
        self.source = "screen"  # or "webcam"
    
    def capture_screen(self) -> Optional[bytes]:
        """Capture active window or full screen."""
        try:
            import mss
            with mss.mss() as sct:
                monitor = sct.monitors[1]  # Primary monitor
                screenshot = sct.grab(monitor)
                return mss.tools.to_png(screenshot.rgb, screenshot.size)
        except Exception:
            return None
    
    def capture_webcam(self) -> Optional[bytes]:
        """Capture single frame from webcam."""
        try:
            import cv2
            cap = cv2.VideoCapture(0)
            ret, frame = cap.read()
            cap.release()
            if ret:
                _, buf = cv2.imencode('.png', frame)
                return buf.tobytes()
        except Exception:
            return None
        return None
    
    def capture_frame(self, timeout_ms: int = 500) -> Optional[bytes]:
        """Capture with timeout, fallback to last frame."""
        start = time.time()
        while time.time() - start < timeout_ms / 1000:
            if self.source == "screen":
                frame = self.capture_screen()
            else:
                frame = self.capture_webcam()
            if frame:
                self.last_frame = frame
                return frame
        return self.last_frame
```

**Testing**: Verify capture works on both screen and webcam

---

### Task 2.3: Update _parse_voice_transcript for visual context

**File**: `main.py`

**Description**: Attach visual frame for vision roles

**Implementation**:
```python
def _parse_voice_transcript(self, text: str) -> Tuple[Optional[str], str, Optional[bytes]]:
    """Parse transcript with optional visual context."""
    role, content = self._parse_voice_transcript(text)
    
    if role in ("vision", "multimodal"):
        from voice_engine import VisualContextCapture
        cap = VisualContextCapture()
        image = cap.capture_frame()
        return role, content, image
    
    return role, content, None
```

---

### Task 2.4: Update backend to handle multi-modal messages

**File**: `backend.py`

**Description**: Modify ChatWorker to accept and format image data

**Implementation**:
```python
def __init__(... image: Optional[bytes] = None):
    self.image = image
    # ... rest of init

def _format_messages(self, messages):
    """Format messages with optional image for vision models."""
    if self.image:
        import base64
        img_b64 = base64.b64encode(self.image).decode('utf-8')
        return [{
            "role": "user",
            "content": [
                {"type": "text", "text": messages[-1]["content"]},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}}
            ]
        }]
    return messages
```

---

## Phase 3: TTS Audio Response (Optional - AUDIO OUTPUT)

### Task 3.1: Add kokoro-ai or pyttsx3 to requirements.txt

**File**: `requirements.txt`

**Description**: Add TTS engine dependency

```
kokoro-ai>=1.0.0
# OR for system TTS:
# pyttsx3>=2.90
```

---

### Task 3.2: Add TTSWorker class

**File**: `voice_engine.py`

**Description**: Create worker for text-to-speech synthesis

**Implementation**:
```python
class TTSWorker(QThread):
    """Synthesize speech from text using Kokoro or system TTS."""
    audio_ready = Signal(bytes)  # WAV/MP3 bytes
    error_occurred = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = None
        self._text_queue = queue.Queue(maxsize=10)
        self._stop_event = threading.Event()
    
    def synthesize(self, text: str):
        """Queue text for synthesis."""
        try:
            self._text_queue.put_nowait(text)
        except queue.Full:
            pass  # Drop oldest if full
    
    def run(self):
        """Synthesize queued text."""
        while not self._stop_event.is_set():
            try:
                text = self._text_queue.get(timeout=0.1)
                audio = self._synth(text)
                self.audio_ready.emit(audio)
            except queue.Empty:
                continue
    
    def _synth(self, text: str) -> bytes:
        """Synthesize text to audio bytes."""
        # Use Kokoro or system TTS here
        pass
```

---

### Task 3.3: Connect generation_complete to TTSWorker

**File**: `main.py`

**Description**: Route assistant responses to TTS

**Implementation**:
```python
def _on_generation_complete(self, full_response: str):
    # ... existing completion logic ...
    
    # Send to TTS
    self._tts_worker.synthesize(full_response)
    
    # ... rest of existing code ...
```

---

## Testing

### Unit Tests
- [ ] `_parse_voice_transcript` handles all role prefixes
- [ ] `_show_voice_toast` displays and disappears
- [ ] `_check_voice_service_readiness` returns correct states

### Integration Tests
- [ ] Voice input appears in chat with user bubble
- [ ] Role prefix routing works (`coding:`, `vision:`)
- [ ] Service unavailable → notification, no chat entry
- [ ] TTS speaks response (when enabled)

---

## Notes

- **Thread Safety**: All Qt signals use `Qt.QueuedConnection` for GUI thread execution
- **Timeouts**: Visual capture limited to 500ms; audio queue bounded at 10 items
- **Fallback**: Service unavailability discards transcript with notification
- **Mute Toggle**: Add preference in `.state/settings.json` for TTS on/off