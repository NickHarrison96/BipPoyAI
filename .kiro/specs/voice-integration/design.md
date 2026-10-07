# Voice Pipeline Integration Design

## Overview

This document describes the architecture and implementation of the voice pipeline integration feature for Cayde 420. The feature enables users to speak their messages, with local transcription, role-based routing, and seamless integration into the existing chat flow.

## Architecture

### Current State

- **voice_engine.py**: Contains `SpeechListener` class with `transcription_queue` (queue.Queue)
- **main.py**: Contains `MainWindow` class with `_pending_voice` deque and existing voice button
- **backend.py**: Contains `OllamaBackend` with `send_message()` supporting `engine_mode` and `model_tag` parameters
- **GUI flow**: User types → `_send_message()` → `_send_text()` → backend.send_message() → streaming bubbles

### New Flow

```
User speaks → SpeechListener → transcription_queue → Qt signal → _on_voice_transcribed()
    ├─ Parse role prefix (regex)
    ├─ Validate role against LiteLLM config
    ├─ Check service readiness (LiteLLM, Ollama, model)
    ├─ If ready: call _send_text(text, engine_mode="litellm_chat", model_tag=role)
    └─ If not ready: discard + toast notification
```

## Components

### 1. SpeechListener (Existing)

**File**: `voice_engine.py`

**Current State**:
- Inherits from `QThread`
- Emits `transcribed` signal with raw transcript string
- `transcription_queue` is a `queue.Queue` (thread-safe)
- Worker thread produces transcriptions, main thread consumes via Qt signal

**Integration Point**:
- Already connected in `MainWindow.__init__`:
  ```python
  self._voice_worker.transcribed.connect(self._on_speech_transcribed, Qt.QueuedConnection)
  ```
- `Qt.QueuedConnection` ensures GUI thread execution

### 2. Voice Transcript Handler (New/Modified)

**File**: `main.py`

**Method**: `_on_speech_transcribed(text: str)` (existing, needs enhancement)

**Current Implementation** (simplified):
```python
def _on_speech_transcribed(self, text: str):
    text = text.strip()
    if not text or not self._voice_worker or not self._voice_worker.isRunning():
        return
    if len(self._pending_voice) == self._pending_voice.maxlen:
        self.voice_btn.setToolTip("Voice queue full; oldest phrase discarded")
    self._pending_voice.append(text)
    self._drain_voice_queue()
```

**Enhanced Implementation**:

Replace existing `_on_speech_transcribed` with:

```python
def _on_speech_transcribed(self, text: str):
    """Handle a completed voice transcription."""
    text = text.strip()
    if not text or not self._voice_worker or not self._voice_worker.isRunning():
        return
    # Route through _drain_voice_queue for role parsing, validation, and dispatch
    self._pending_voice.append(text)
    self._drain_voice_queue()
```

**Key Changes**:
- Keep current `_on_speech_transcribed` as-is (it just queues)
- Enhance `_drain_voice_queue()` to handle all logic

### 3. Voice Queue Drain (Modified)

**File**: `main.py`

**Method**: `_drain_voice_queue()` (existing, needs enhancement)

**Current Implementation** (simplified):
```python
def _drain_voice_queue(self):
    if not self._pending_voice or self.chat_input.toPlainText().strip():
        return
    if self._streaming_bubble is not None:
        return
    if self.backend.is_generating():
        QTimer.singleShot(100, self._drain_voice_queue)
        return
    if not (self._litellm_live and self._ollama_live and self._model_ready):
        self.voice_btn.setToolTip("Speech queued until LiteLLM and the model are ready")
        return
    original_text = self._pending_voice.popleft()
    text = original_text
    requested = re.match(r"^(default|reasoning|coding|vision|multimodal)\s*[:,-]\s*(.+)$",
                         text, re.IGNORECASE | re.DOTALL)
    role = requested.group(1).lower() if requested else None
    if role:
        if role not in load_role_aliases(Path(self.backend.working_dir) / "config.yaml"):
            self.voice_btn.setToolTip(f"{role.title()} route is not registered in LiteLLM")
            return
        text = requested.group(2).strip()
    if not self._send_text(text, engine_mode="litellm_chat", model_tag=role):
        self._pending_voice.appendleft(original_text)
```

**Enhanced Implementation**:

Replace with:

```python
def _drain_voice_queue(self):
    """Process the oldest queued voice transcript, if conditions allow."""
    # Don't drain if user is typing
    if not self._pending_voice or self.chat_input.toPlainText().strip():
        return
    
    # Don't interrupt ongoing generation
    if self._streaming_bubble is not None:
        return
    if self.backend.is_generating():
        QTimer.singleShot(100, self._drain_voice_queue)
        return
    
    # Service readiness gate
    if not (self._litellm_live and self._ollama_live and self._model_ready):
        # Show toast notification
        self._show_voice_toast("Voice input queued: services not ready")
        return
    
    # Drain one transcript
    original_text = self._pending_voice.popleft()
    text, role, parse_error = self._parse_voice_transcript(original_text)
    
    # Validation: role must be registered
    if parse_error:
        self._show_voice_toast(parse_error)
        return
    
    # Route to correct model via LiteLLM
    success = self._send_text(text, engine_mode="litellm_chat", model_tag=role)
    
    # Retry on failure (e.g., if generation started while we were draining)
    if not success:
        self._pending_voice.appendleft(original_text)
        QTimer.singleShot(100, self._drain_voice_queue)
```

### 4. Transcript Parser (New Helper)

**File**: `main.py`

**Method**: `_parse_voice_transcript(text: str)` (new)

```python
def _parse_voice_transcript(self, text: str) -> tuple:
    """
    Parse voice transcript for role prefix.
    
    Returns:
        (text: str, role: str, error: str | None)
        - If successful: (extracted_text, role_name, None)
        - If no prefix: (original_text, "default", None)
        - If error: ("", "", error_message)
    """
    # Try to match role prefix patterns
    # Valid prefixes: "coding:", "vision:", "default:", "reasoning:", "multimodal:"
    # Separators: :, -, or comma, with optional whitespace
    pattern = r"^(default|reasoning|coding|vision|multimodal)\s*[:,-]\s*(.+)$"
    requested = re.match(pattern, text, re.IGNORECASE | re.DOTALL)
    
    if not requested:
        # No prefix: use default role
        return (text, "default", None)
    
    role = requested.group(1).lower()
    extracted_text = requested.group(2).strip()
    
    # Validate role against LiteLLM config
    config_path = Path(self.backend.working_dir) / "config.yaml"
    if not config_path.exists():
        return ("", "", "Voice routing unavailable: config.yaml not found")
    
    registered_roles = load_role_aliases(config_path)
    if role not in registered_roles:
        return ("", "", f"Voice routing unavailable: '{role}' role not registered in LiteLLM")
    
    return (extracted_text, role, None)
```

### 5. Toast Notification (New)

**File**: `main.py`

**Method**: `_show_voice_toast(message: str)` (new)

```python
def _show_voice_toast(self, message: str):
    """
    Show a brief toast notification for voice-related events.
    
    Options:
    - Use existing status banner (statusBanner style)
    - Use QLabel overlay on input area
    - Use self.voice_btn.setToolTip() with timeout
    - Use QMessageBox.information() (modal, not recommended)
    
    Current approach: Use self.voice_btn.setToolTip() for simplicity
    """
    self.voice_btn.setToolTip(message)
    
    # Optional: auto-clear after 3 seconds
    QTimer.singleShot(3000, lambda: self.voice_btn.setToolTip(
        "Transcribe speech locally and send through LiteLLM"
    ))
```

**Alternative**: Use status banner for better visibility:

```python
def _show_voice_toast(self, message: str):
    """Show toast using the status banner."""
    self.status_banner.setVisible(True)
    self.banner_label.setText(f"Voice: {message}")
    
    # Auto-hide after 3 seconds
    if not hasattr(self, '_voice_toast_timer'):
        self._voice_toast_timer = QTimer(self)
        self._voice_toast_timer.timeout.connect(self._hide_voice_toast)
        self._voice_toast_timer.setSingleShot(True)
    
    self._voice_toast_timer.start(3000)

def _hide_voice_toast(self):
    """Hide the voice toast notification."""
    if hasattr(self, 'status_banner') and self.status_banner:
        self.status_banner.setVisible(False)
```

## Data Models

### Role Prefix Format

**Regex Pattern**:
```regex
^(default|reasoning|coding|vision|multimodal)\s*[:,-]\s*(.+)$
```

**Valid Formats**:
- `coding: Write a Python function to calculate Fibonacci`
- `vision: Describe what's in this image`
- `default: What is the capital of France?`
- `reasoning - Let's think step by step`
- `multimodal, Analyze this document`

**Invalid Formats** (discarded with toast):
- `invalid_role: This won't work`
- `codingThis has no separator`
- `: No role specified`

## Error Handling

### Error Cases and Toast Messages

1. **Service Unavailable**
   - Condition: `not (_litellm_live and _ollama_live and _model_ready)`
   - Toast: `"Voice input queued: services not ready"`
   - Action: Discard transcript, keep in queue

2. **Role Not Registered**
   - Condition: Role extracted but not in `load_role_aliases()`
   - Toast: `"Voice routing unavailable: 'coding' role not registered in LiteLLM"`
   - Action: Discard transcript

3. **Config File Missing**
   - Condition: `config.yaml` doesn't exist
   - Toast: `"Voice routing unavailable: config.yaml not found"`
   - Action: Discard transcript

4. **Backend Busy**
   - Condition: `backend.is_generating()` returns `True`
   - Toast: (no toast, just delay retry)
   - Action: Retry after 100ms

5. **Empty Transcript**
   - Condition: `not text.strip()`
   - Action: Discard silently

6. **Queue Full**
   - Condition: `_pending_voice` at `maxlen`
   - Toast: `"Voice queue full; oldest phrase discarded"`
   - Action: Discard oldest

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Transcript Role Parsing

*For any* voice transcript string containing a role prefix (default, reasoning, coding, vision, or multimodal) followed by a separator (colon, comma, or dash) and text content, parsing the transcript with `_parse_voice_transcript()` shall extract the role name in lowercase and the text content, with leading/trailing whitespace removed from both.

**Validates: Requirements 1.2**

### Property 2: Default Role Assignment

*For any* voice transcript string that does not match the role prefix pattern, calling `_parse_voice_transcript()` shall return the original text and `"default"` as the role.

**Validates: Requirements 1.7**

### Property 3: Valid Role Routing

*For any* voice transcript with a valid role prefix (matching a role registered in LiteLLM config), calling `_send_text()` shall use `engine_mode="litellm_chat"` and `model_tag` set to the parsed role.

**Validates: Requirements 1.2, 1.5**

### Property 4: Service Readiness Gate

*For any* voice transcript in the queue, if the service readiness check `(_litellm_live and _ollama_live and _model_ready)` returns `False`, the transcript shall not be dispatched and a toast notification shall be shown.

**Validates: Requirements 1.4**

### Property 5: Invalid Role Rejection

*For any* voice transcript with a role prefix that does not exist in the LiteLLM configuration, the system shall show a toast notification and discard the transcript without dispatching.

**Validates: Requirements 1.3**

### Property 6: Queue Ordering

*For any* sequence of voice transcripts queued while the backend is generating, when generation completes, the transcripts shall be processed in FIFO (first-in, first-out) order.

**Validates: Requirements 1.6**

### Property 7: Separator Format Tolerance

*For any* valid role prefix with different separators (colon, comma, or dash), the parsing regex shall match and extract the role and text correctly.

**Validates: Requirements 1.8**

### Property 8: Thread-Safe GUI Updates

*For any* transcription signal emitted from `SpeechListener` worker thread, connecting via `Qt.QueuedConnection` to `_on_speech_transcribed` shall ensure the slot executes on the GUI thread, preventing race conditions.

**Validates: Requirements 1.9**

### Property 9: Streaming Response Display

*For any* assistant streaming response, each token received via `token_received` signal shall incrementally update the assistant bubble content and scroll to the bottom.

**Validates: Requirements 1.10**

### Property 10: Generation Completion State

*For any* generation completion (success or error), the UI state shall be restored: send button enabled, stop button disabled, input field enabled and focused.

**Validates: Requirements 1.11, 1.12**

## Implementation Steps

### Phase 1: Core Parsing (Files: `main.py`)

1. Add `_parse_voice_transcript()` method to `MainWindow` class
2. Enhance `_drain_voice_queue()` to use parsing and validation
3. Add `_show_voice_toast()` method for notifications

### Phase 2: Integration Testing (Files: `tests/test_voice_integration.py`)

1. Write property-based tests for role parsing (Property 1, 2, 7)
2. Write example tests for toast notifications (Property 4, 5)
3. Write integration tests for queue ordering (Property 6)

### Phase 3: UI Polish (Files: `main.py`)

1. Choose toast implementation approach (status banner vs tooltip)
2. Add auto-clear timeout for toast notifications
3. Enhance visual feedback during voice input

### Phase 4: Edge Cases (Files: `main.py`, `voice_engine.py`)

1. Handle very long transcripts (trim if needed)
2. Handle encoding issues in transcriptions
3. Add logging for debugging (quiet by default)

## Testing Strategy

### Property-Based Tests

- **Role parsing**: Generate random role prefixes and separators, verify parsing
- **Default role**: Generate transcripts without prefixes, verify default role
- **Service gate**: Generate service states (ready/unready), verify dispatch behavior
- **Queue ordering**: Generate multiple transcripts, simulate concurrent generation, verify FIFO

### Example-Based Tests

- Invalid role names (toast message contains role name)
- Empty transcript handling (silent discard)
- Queue full scenario (oldest discarded)
- Different separator formats (colon, comma, dash)

### Integration Tests

1. **Full voice flow**: Start app → mic on → speak → verify chat entry
2. **Role routing**: Speak with prefix → verify correct model called
3. **Service unavailable**: Stop LiteLLM → speak → verify toast
4. **Concurrent typed input**: Speak while typing → verify typed takes priority
5. **Queue processing**: Speak multiple times while busy → verify FIFO

## Configuration

### Required Config.yaml Entries

```yaml
litellm_settings:
  routes:
    - model_name: "coding"
      litellm_params:
        model: "ollama_chat/<coding-model-tag>"
    - model_name: "vision"
      litellm_params:
        model: "ollama_chat/<vision-model-tag>"
    - model_name: "default"
      litellm_params:
        model: "ollama_chat/<default-model-tag>"
    # ... reasoning, multimodal
```

### Verification

Ensure `load_role_aliases()` returns dictionary with keys: `default`, `reasoning`, `coding`, `vision`, `multimodal`

## Dependencies

- **Existing**: `re` (Python regex), `queue.Queue`, `PySide6.QtCore.QTimer`
- **Existing**: `configs.load_role_aliases()` from `configs.py`
- **Existing**: `MessageBubble`, `COLORS`, `MessageBubble` styling

## Open Questions

1. **Toast implementation**: Should we use status banner or tooltip for voice notifications?
2. **Queue limit**: Is 8 transcripts sufficient, or should we increase?
3. **Timeout behavior**: Should queued transcripts expire after X minutes?
4. **Interrupt behavior**: Should voice interrupt ongoing generation? (Currently: no)
5. **Visual feedback**: Should voice button show listening state differently?

## References

- Current implementation: `main.py` lines 2437-2471 (voice handling)
- Role aliases: `configs.py` lines 302-320
- Message bubble: `main.py` lines 123-230
- Backend interface: `backend.py` lines 770-850 (`send_message`)