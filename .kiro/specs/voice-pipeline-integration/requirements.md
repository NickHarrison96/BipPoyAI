# Requirements Document: Voice Pipeline Integration

## Introduction

This feature integrates the existing voice pipeline (Silero VAD + Whisper CPU transcription) into the Cayde 420 chat interface. Voice input will be transcribed in real-time and dispatched immediately to the backend for processing, following the exact same flow as typed chat input.

## Glossary

- **Cayde 420**: The local AI desktop application running GGUF models via Ollama + LiteLLM proxy
- **SpeechListener**: Background thread that captures microphone audio, detects voice activity with Silero VAD, and transcribes speech to text
- **transcription_queue**: Thread-safe queue that passes utterances from audio capture to Whisper transcription
- **backend**: OllamaBackend class that manages Ollama health, LiteLLM proxy, and streaming chat completion
- **send_message()**: Backend method that creates a ChatWorker for streaming inference
- **ChatWorker**: Background thread that streams responses from LiteLLM/Ollama to the GUI
- **Role Prefix**: Model role selector (default, coding, vision) embedded in user input via prefix syntax
- **Toast Notification**: Non-blocking UI notification displayed briefly to inform the user of events
- **Engine Mode**: Backend routing mode (litellm_chat, litellm_standard, direct)
- **Model Tag**: Ollama model identifier that may include role routing (e.g., "qwen3-coding")
- **Visual Context Frame**: Screen capture or webcam frame attached to voice prompts routed to vision models
- **TTS Engine**: Text-to-speech synthesizer (Kokoro, Piper, or system TTS) that converts LLM responses to audio
- **Audio Output Queue**: Thread-safe queue that buffers synthesized speech for playback

## Requirements

### Requirement 1: Immediate Transcript Dispatch

**User Story:** As a user, I want voice transcripts to be dispatched immediately so that I receive assistant responses without unnecessary delay.

#### Acceptance Criteria

1. WHEN a transcript is produced by SpeechListener, THE Cayde 420 SHALL dispatch it to backend.send_message() without buffering or queuing
2. IF LiteLLM or Ollama services are unavailable when a transcript is produced, THEN THE Cayde 420 SHALL discard the transcript and show a Toast Notification indicating service unavailability
3. WHEN service availability is restored, THE Cayde 420 SHALL resume accepting and dispatching transcripts immediately without replaying buffered content

### Requirement 2: Consistent Input Flow

**User Story:** As a user, I want voice input to follow the same flow as typed input so that the assistant response experience is identical regardless of input method.

#### Acceptance Criteria

1. WHEN a transcript is dispatched, THE Cayde 420 SHALL create a user message bubble in the chat history
2. WHEN a user message bubble is created, THE Cayde 420 SHALL immediately create an assistant streaming bubble for the response
3. WHEN the assistant streaming bubble is created, THE Cayde 420 SHALL call backend.send_message() with the transcript text, current engine_mode, and resolved model_tag
4. WHILE the ChatWorker is streaming tokens, THE Cayde 420 SHALL update the assistant streaming bubble in real-time
5. WHEN the ChatWorker emits generation_complete, THE Cayde 420 SHALL finalize the assistant message in chat history

### Requirement 3: Role Prefix Routing

**User Story:** As a user, I want to specify model roles via voice prefix so that I can route voice queries to specialized models.

#### Acceptance Criteria

1. WHERE a transcript begins with a role prefix (coding:, vision:, default:), THEN THE Cayde 420 SHALL parse the prefix and extract the role
2. WHEN a role is parsed, THE Cayde 420 SHALL validate that the role is registered in the LiteLLM config file
3. IF the role is registered, THEN THE Cayde 420 SHALL resolve the role to its model_tag and pass model_tag to backend.send_message()
4. IF the role is not registered, THEN THE Cayde 420 SHALL discard the transcript and show a Toast Notification indicating the role is not configured
5. WHERE a transcript does not begin with a role prefix, THEN THE Cayde 420 SHALL use the default model configured for the session

### Requirement 4: Service Readiness Gate

**User Story:** As a user, I want voice input to check service readiness before dispatch so that I don't send transcripts that will be silently dropped.

#### Acceptance Criteria

1. WHEN a transcript is ready for dispatch, THEN THE Voice Pipeline SHALL verify that LiteLLM is operational
2. WHEN LiteLLM is verified, THEN THE Voice Pipeline SHALL verify that Ollama is operational
3. WHEN Ollama is verified, THEN THE Voice Pipeline SHALL verify that the model identified by model_tag is loaded and ready
4. IF any service check fails, THEN THE Voice Pipeline SHALL discard the transcript and show a Toast Notification with specific failure details
5. IF all service checks pass, THEN THE Voice Pipeline SHALL dispatch the transcript to backend.send_message()

### Requirement 5: Thread-Safe UI Updates

**User Story:** As a user, I want voice input to update the UI safely so that the application remains stable during concurrent audio processing.

#### Acceptance Criteria

1. WHEN SpeechListener produces a transcript, THEN THE Voice Pipeline SHALL emit a Qt signal (transcribed) on the GUI thread
2. WHERE a UI element (message bubble, status indicator) must be updated from the transcribed signal, THEN THE Voice Pipeline SHALL use Qt slots to ensure GUI updates occur on the main thread
3. IF multiple transcripts are produced in rapid succession, THEN THE Cayde 420 SHALL queue UI updates and process them serially on the GUI thread
4. WHEN UI updates are queued, THEN THE Cayde 420 SHALL discard older queued updates when latency exceeds 200ms to prevent UI backlog

## Non-Functional Requirements

1. **Performance**: WHEN a user speaks, THEN the total latency from speech end to first token should not exceed 1.5 seconds on modern hardware (Intel i5/Ryzen 5 or better)
2. **Resource Usage**: WHEN transcription is active, THEN CPU usage should not exceed 70% on a 4-core system
3. **Offline Operation**: WHEN the application runs without a microphone, THEN the voice button should be disabled but the application should continue to function
4. **Error Resilience**: WHEN Whisper transcription fails, THEN the Voice Pipeline SHALL discard the transcript and show a Toast Notification without crashing the application
5. **No PyTorch in GUI Thread**: WHEN transcription occurs, THEN the GUI thread SHALL not load or reference PyTorch libraries

---

## Video & Visual Stream Integration

### Requirement 6: Visual Context Capture for Vision Roles

**User Story:** As a user, I want voice prompts to vision models to include current screen/webcam context so that the assistant can analyze what I'm looking at.

#### Acceptance Criteria

1. WHERE a transcript begins with the `vision:` prefix OR the active role is set to `vision`/`multimodal`, THEN THE Voice Pipeline SHALL capture a visual context frame before dispatching the transcript
2. WHEN capturing a visual context frame, THE Voice Pipeline SHALL use screen capture (active window or full screen) OR webcam feed as the image source (user configurable)
3. IF screen capture fails, THEN THE Voice Pipeline SHALL attempt webcam feed as fallback
4. IF both capture methods fail, THEN THE Voice Pipeline SHALL discard the transcript and show a Toast Notification indicating visual capture failure
5. WHEN a visual context frame is successfully captured, THEN THE Voice Pipeline SHALL attach the base64-encoded image payload alongside the transcribed text before calling `backend.send_message()`
6. WHERE `backend.send_message()` is called for a vision role, THEN THE Cayde 420 SHALL pass a message structure containing both `content` (text) and `image` (base64) fields
7. WHEN the vision model receives the payload, THEN THE Cayde 420 SHALL ensure the image data is properly formatted for the vision model's expected input (e.g., `{"role": "user", "content": [{"type": "text", "text": "..."}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}]}}`)

#### Visual Capture Implementation Notes

- **Screen Capture**: Use `PyQt5.QtGui.QScreen` or `mss` library to capture active window or full screen
- **Webcam Feed**: Use OpenCV (`cv2`) to access webcam and capture single frame
- **Frame Format**: Convert captured frame to PNG/JPEG, then base64 encode
- **Timeout**: Image capture must complete within 500ms to avoid disrupting conversation flow
- **Fallback Behavior**: If capture takes longer than 500ms, use last captured frame or discard with notification

---

## Text-to-Speech (TTS) Response Flow

### Requirement 7: Audio Response via TTS

**User Story:** As a user, I want Cayde to speak responses back to me so that voice interaction is fully bidirectional without needing to read text on screen.

#### Acceptance Criteria

1. WHEN `ChatWorker` emits `generation_complete` with a response, THEN THE Voice Pipeline SHALL pass the response text to a TTS engine
2. WHERE a TTS engine is selected (Kokoro, Piper, or system TTS), THEN THE Voice Pipeline SHALL synthesize speech audio from the response text
3. WHEN speech audio is synthesized, THEN THE Voice Pipeline SHALL queue the audio for playback via system audio output
4. WHERE audio playback is requested, THEN THE Voice Pipeline SHALL play audio asynchronously without blocking chat UI updates
5. WHEN a new transcript is produced while audio playback is in progress, THEN THE Voice Pipeline SHALL either:
   - A) Pause audio playback and resume after transcript dispatch, OR
   - B) Allow concurrent audio playback and transcript processing (user configurable)
6. IF TTS engine fails to initialize, THEN THE Voice Pipeline SHALL continue text-only operation with a single notification (no repeated failures)
7. WHERE audio playback completes, THEN THE Voice Pipeline SHALL emit a signal (`tts_complete`) so the UI can reset voice button state if needed

#### TTS Implementation Options

| TTS Engine | Pros | Cons | Integration Notes |
|------------|------|------|-------------------|
| **Kokoro** | High quality, small footprint, CPU-only | Requires model download (~250MB) | Use `kokoro-ai` package; load once, cache in worker |
| **Piper** | Local, privacy-preserving, many voices | Larger model files (~50-100MB each) | Use `piper-ai` package; support voice selection |
| **System TTS** | No dependencies, always available | Quality varies by platform | Use `pyttsx3` or Windows ` SpeechSynthesis` API |

#### Audio Queue Architecture

```
[ChatWorker] → generation_complete → [TTSWorker]
                                             │
                                             ▼
                                    [AudioOutputQueue]
                                             │
                                             ▼
                                    [AudioPlayerWorker]
                                             │
                                             ▼
                                    [System Audio Device]
```

- **TTSWorker**: QThread that converts text → audio (WAV/MP3 bytes)
- **AudioOutputQueue**: Bounded queue (max 10 items) to prevent backlog
- **AudioPlayerWorker**: QThread that streams audio to system device
- **Queue Management**: If queue is full, discard oldest audio (not user-facing)

#### Integration with Existing Pipeline

- **TTS Worker Initialization**: In `MainWindow.__init__()`, create TTSWorker when voice module loads
- **Signal Chain**: `ChatWorker.generation_complete → TTSWorker.synthesize → AudioPlayerWorker.play → tts_complete`
- **Disable TTS During Input**: WHEN `SpeechListener` is actively recording, THEN pause TTS playback
- **Mute Toggle**: Add mute button to toggle TTS on/off; persist preference to `.state/settings.json`

---
---

## Tasks

### Phase 1: Voice Pipeline Integration (Base Features)

| Task | File | Description |
|------|------|-------------|
| 1.1 | `voice_engine.py` | Add `transcription_received = Signal(str)` signal to SpeechListener |
| 1.2 | `voice_engine.py` | Emit `transcription_received.emit(phrase)` in SpeechListener.run() after transcription |
| 1.3 | `main.py` | Add `_on_voice_transcribed(text: str)` slot to MainWindow |
| 1.4 | `main.py` | Add `_parse_voice_transcript(text: str)` helper to extract role prefix |
| 1.5 | `main.py` | Add `_show_voice_toast(message: str)` notification method |
| 1.6 | `main.py` | Connect `SpeechListener.transcription_received` to `_on_voice_transcribed` |
| 1.7 | `main.py` | Add service readiness check before dispatch (LiteLLM + Ollama + model ready) |
| 1.8 | `requirements.txt` | Add `sounddevice`, `scipy` for audio capture |
| 1.9 | `requirements.txt` | Add `faster-whisper`, `ctranslate2` for CPU transcription |

### Phase 2: Visual Context Capture

| Task | File | Description |
|------|------|-------------|
| 2.1 | `requirements.txt` | Add `mss` for screen capture, `opencv-python` for webcam |
| 2.2 | `voice_engine.py` | Add `VisualContextCapture` class with screen/camera methods |
| 2.3 | `voice_engine.py` | Add `_capture_visual_frame()` method to SpeechListener |
| 2.4 | `main.py` | Update `_parse_voice_transcript()` to include visual frame for vision roles |
| 2.5 | `main.py` | Update `_on_voice_transcribed()` to attach base64 image to message payload |
| 2.6 | `backend.py` | Update `ChatWorker` to accept and format multi-modal messages (text + image) |
| 2.7 | `main.py` | Add visual capture timeout (500ms max), fallback to last frame or discard |

### Phase 3: TTS Audio Response

| Task | File | Description |
|------|------|-------------|
| 3.1 | `requirements.txt` | Add `kokoro-ai` (preferred) or `pyttsx3` for system TTS |
| 3.2 | `voice_engine.py` | Add `TTSWorker` class with `text_received` signal |
| 3.3 | `voice_engine.py` | Add `AudioOutputQueue` (bounded deque, max 10 items) |
| 3.4 | `voice_engine.py` | Add `AudioPlayerWorker` class for async audio playback |
| 3.5 | `main.py` | Connect `ChatWorker.generation_complete` to `TTSWorker.text_received` |
| 3.6 | `main.py` | Add mute toggle button in header bar, persist to settings |
| 3.7 | `main.py` | Add TTS pause during active voice recording |
| 3.8 | `main.py` | Add `tts_complete` signal to reset UI state |

### Testing

| Test | Description |
|------|-------------|
| T-1 | Voice input appears in chat with user bubble |
| T-2 | Assistant streams response to voice input |
| T-3 | Role prefix routing works (`coding:`, `vision:`) |
| T-4 | Service unavailable → notification, no chat entry |
| T-5 | Visual capture → base64 image attached for vision role |
| T-6 | TTS speaks response (optional, configurable) |
| T-7 | TTS muted → no audio, text-only response |
| T-8 | Voice recording during TTS → TTS pauses, resumes after |
| T-9 | Concurrent typed + voice input → no interference |

---

## Acceptance Test Plan

### Manual Testing Checklist

- [ ] **Base Voice Input**
  - [ ] Speak into mic → transcript appears in chat
  - [ ] Verify user bubble created, assistant bubble shows streaming
  - [ ] Check assistant response streams correctly

- [ ] **Role Prefix Routing**
  - [ ] Say "coding: explain X" → routes to coding model
  - [ ] Say "vision: what am I seeing?" → routes to vision model (with visual frame)
  - [ ] Say "default: hello" → routes to default model

- [ ] **Service Unavailability**
  - [ ] Stop LiteLLM → speak → toast notification appears
  - [ ] Stop Ollama → speak → toast notification appears
  - [ ] Model not loaded → speak → toast notification appears

- [ ] **Visual Context**
  - [ ] Vision role → verify screen capture captures active window
  - [ ] Vision role → verify image attached as base64 in message
  - [ ] Capture timeout → verify fallback or discard with notification

- [ ] **TTS Audio Response**
  - [ ] Enable TTS → speak → listen for assistant response
  - [ ] Disable TTS → speak → text-only response
  - [ ] Speak during TTS → verify TTS pauses/resumes

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `sounddevice` | ≥0.4.0 | Microphone audio capture |
| `scipy` | ≥1.11.0 | Audio resampling |
| `faster-whisper` | ≥0.10.0 | CPU Whisper transcription |
| `ctranslate2` | ≥4.0.0 | CTranslate2 inference backend |
| `mss` | ≥6.1.0 | Screen capture |
| `opencv-python` | ≥4.8.0 | Webcam frame capture |
| `kokoro-ai` | ≥1.0.0 | TTS engine (preferred) |
| `pyttsx3` | ≥2.90 | Fallback system TTS |

## Known Limitations

1. **Visual Context**: Screen capture uses active window; multi-monitor support requires additional logic
2. **TTS Latency**: Kokoro model load adds ~1-2s first-time delay
3. **Concurrent TTS/Voice**: If user speaks while TTS plays, TTS pauses (no simultaneous audio)
4. **Webcam Privacy**: Webcam access requires Windows camera permissions; fallback to screen capture