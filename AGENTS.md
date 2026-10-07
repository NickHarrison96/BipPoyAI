# Cayde 420 â€” Project Bible

> This file is the single source of truth for project context.
> Read it fully before making any changes. Keep it updated as things ship.

---

## What This Project Is

**Cayde 420** is a **local-only AI desktop application** for Windows.
It lets you run a GGUF model entirely offline using:

```
User (Claude CLI, OpenCode, or GUI chat)
        â”‚
        â–¼
  LiteLLM Proxy  :4000
  â† spoofs the Anthropic API so `claude` CLI works offline without any internet
        â”‚
        â–¼
  Ollama  :11434
  â† hosts one or more GGUF models built from `Models/`
        â”‚
        â–¼
  Models/*.gguf  (user-populated; active model is `qwythos-heretic`
                  built from `Qwen3.5-9B-Heretic-patched2.gguf`)
```

**Key architectural fact:** LiteLLM is mandatory â€” it is not optional middleware.
It exists specifically to spoof `api.anthropic.com` so that the `claude` CLI (Claude Code)
connects to it thinking it's talking to Anthropic, but actually routes to Ollama locally.
`setup.py` sets the Claude Code env vars (`ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`,
`ANTHROPIC_MODEL`, `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS`) to make this transparent.

**Do not pass `--model <ollama-tag>` to `claude`.** Claude Code validates model names
against its own known list and hangs on local Ollama tags (`unrecognized_model`).
Set `ANTHROPIC_MODEL` to the exact tag in `config.yaml` instead. `model_list` must
contain only that tag â€” a `"*"` wildcard entry silently served the wrong weights
(see "No wildcard" below).

**Force UTF-8 in every child process.** LiteLLM prints a box-drawing banner at startup
and Ollama emits non-ASCII bytes; on a cp437/cp1252 console these raise
`UnicodeEncodeError` / `UnicodeDecodeError`. LiteLLM dies before serving anything, so
LiteLLM spawns need `PYTHONIOENCODING=utf-8` + `PYTHONUTF8=1`, and every
`subprocess.run(..., text=True)` needs `encoding="utf-8", errors="replace"`.

There are **three ways to use the stack:**
1. **GUI** (`main.py`) â€” chat interface, sends requests to LiteLLM directly
2. **Claude CLI** â€” `claude` (no `--model`; `ANTHROPIC_MODEL` is set), routed through LiteLLM â†’ Ollama
3. **OpenCode** â€” same spoofed Anthropic endpoint, different client. Its provider
   config is a JSON file OpenCode owns, so `opencode_bridge.py` merges one
   namespaced `cayde` provider block into `~/.config/opencode/opencode.json` and
   leaves everything else alone. Never rewrite that whole file to add one entry.

---

## File Map

| File | Role | Status |
|---|---|---|
| `main.py` | PySide6 GUI â€” chat bubbles, settings sidebar, status bar | Active |
| `backend.py` | Ollama + LiteLLM health check, streaming worker, model/proxy management | Active |
| `styles.py` | Theme â€” COLORS dict, `rgba()` tint helper, QSS stylesheet, status pills | Active |
| `widgets.py` | Custom QPainter widgets: CrackedBackdrop, ScanlineOverlay, LEDDot, Knob, BarMeter, MascotGlyph, HardwareStrip | Active, wired into main.py |
| `configs.py` | ModelConfig dataclass + Modelfile / config.yaml read-write (single source of truth) | Active |
| `settings.py` | Persistent connection endpoints (`.state/settings.json`) | Active |
| `model_registry.py` | Machine-local bookkeeping: external weight paths + per-model tuning (`.state/`) | Active |
| `hardware.py` | CPU/RAM/GPU detection (pynvml) + recommendation engine | Active |
| `config.py` | Terminal TUI for hardware tuning (uses configs.py + hardware.py; supports --auto, --show) | Active |
| `setup.py` | Automation: GGUF â†’ Ollama build â†’ LiteLLM launch â†’ Claude CLI (supports CLI flags) | Active |
| `history.py` | Chat history persistence â€” JSON sessions + auto-save in `~/.qwythos/history/` (legacy path, retained) | Active |
| `memory_vault.py` | Persistent markdown memory â€” read/write `*.md` under `.state/memory/`, compose the injection block | Active |
| `mcp_grants.py` | Per-directory `read`/`write`/`shell` grants for the MCP server â€” pure data layer, no MCP SDK import | Active |
| `mcp_server.py` | FastMCP workspace server â€” file and command tools inside granted directories; also `--grant`/`--revoke`/`--list`/`--register` CLI | Active, manual registration |
| `model_registry.py` | Machine-local bookkeeping: external weight paths + per-model tuning (`.state/`) | Active |
| `opencode_bridge.py` | Merges one `cayde` provider block into `~/.config/opencode/opencode.json` so OpenCode can reach LiteLLM; then launches it | Active |
| `Modelfile` | Ollama model definition â€” points to GGUF, sets hardware params | Generated, gitignored |
| `config.yaml` | LiteLLM proxy config â€” model routing, Ollama endpoint, context | Generated, gitignored |
| `Models/` | GGUF weights (`_originals/` holds unpatched copies). Auto-excluded from git | Directory, user-populated |
| `Modelfiles/` | Generated per-model Modelfiles (absolute paths, gitignored) | Directory, generated |
| `.state/` | Per-PC local state: settings.json, external_paths.json, models.json, memory/, mcp_grants.json | Directory, gitignored |
| `tools/gguf_guards.py` | Inspect/neutralise chat-template guards; validates GGUF integrity | Active |
| `requirements.txt` | Python deps: litellm, PySide6, requests, psutil, pynvml, ollama, mcp | Complete |
| `check_and_install_deps.bat` | Scans for Python/Ollama/npm, opens download pages, installs requirements.txt | Active |
| `launch.bat` | Double-click launcher: python main.py with error pause | Active |
| `setup.bat` | Double-click launcher: python setup.py with argument forwarding | Active |

### Do NOT touch directly
- `Modelfile` â€” regenerated by Settings â†’ Save & Rebuild Configs (and gitignored)
- `config.yaml` â€” regenerated by Settings â†’ Save & Rebuild Configs (and gitignored)
- `.state/` â€” per-PC state; never commit it

These files are machine-local: `Modelfile`/`config.yaml` contain absolute paths
that Ollama/LiteLLM require on this machine, and `.state/` holds endpoints and
per-model tuning. A fresh clone regenerates all of them from the `Models/` it has
on disk, so no machine-specific data is ever committed.

### Naming: three things are deliberately not the same

The app is **Cayde 420**. Two other names survive in the codebase on purpose â€”
do not "tidy" them:

| Name | Where | Why it stays |
|---|---|---|
| `~/.qwythos/history/` | `history.py:16` | Renaming orphans the user's existing saved conversations. There is no migration shim; adding one is a separate decision. |
| `qwythos-heretic` and friends | Ollama tags, derived from GGUF filenames via `derive_model_tag` | These are **model** names, not app names. The weights are a Qwythos-9B Mythos fine-tune. Renaming a tag means `ollama create` per model plus a `config.yaml` regen. |
| `Qwythos-9B-...gguf` | `setup.py` HF download URL, `Models/` | The upstream filename on HuggingFace. Must match byte-for-byte to download. |

The GUI may label the assistant "Cayde" in user-facing strings (role label,
window title, export header) while the tag underneath stays `qwythos-heretic` â€”
those are separate concerns and conflating them is how the tag ends up wrong.

### Who owns which setting

The two generated files deliberately own **disjoint** concerns. Do not let them
overlap again â€” that was the cause of silently reverted tuning.

| Setting | Owned by | Why |
|---|---|---|
| GGUF path, layer placement, threads, batch | `Modelfile` | baked in at `ollama create` time; no per-request equivalent |
| temperature, top_p, top_k, repeat_penalty | `Modelfile` | sampling behaviour belongs to the model |
| model persona (SYSTEM) | `Modelfile` | baked into the model; empty = keep the model's own |
| **context size (`num_ctx`)**, `max_tokens` | `config.yaml` | LiteLLM forwards these on **every request**, so the proxy config is the only place they need to live |
| model tag, `api_base`, engine mode | `config.yaml` | routing concern |

`load_full()` reads `context_size` and `max_tokens` from `config.yaml` only. The
Modelfile no longer declares `num_ctx`; an older Modelfile that still has it is
ignored. Direct-Ollama mode sends `num_ctx` per request in `options` for the same
reason â€” it can no longer inherit the value from the model.

**Never hardcode a SYSTEM prompt in `MODELFILE_TEMPLATE`.** It did once, and
rebuilding silently replaced the personality of whichever model was installed â€”
Heretic's own prompt was overwritten with a Claude Code persona. The persona is now
`ModelConfig.system_prompt`, editable in Settings â†’ Hardware â†’ Model Persona, and
empty means "keep the model's own".

The same applies to sampling params: `top_p`, `top_k` and `repeat_penalty` are
`Optional` and emit a `# PARAMETER x (using model default)` comment when unset,
rather than imposing a value the model did not ask for.

### Why context size is 32768, not 65536

On an 8GB GPU the 65536-context KV cache does not fit beside the weights, so
Ollama offloads ~24% of layers to CPU and throughput collapses to ~5 tok/s. At
32768 the cache stays resident (~9% offload) for ~9.8 tok/s â€” measured on an
RTX 2070 SUPER. `config.yaml` is the file to change.

Do not hand-edit `config.yaml` to record this: it is regenerated from a template
that emits no comments, so any note added there is lost on the next rebuild.

---

### Chat-template guards can abort requests

A GGUF's chat template may ship `raise_exception` guards such as

```
{{- raise_exception('No user query found in messages.') }}
```

These abort rendering for message shapes the template does not expect and surface
as an opaque `500 ... Ollama_chatException ... While executing CallExpression`,
which reads like a proxy fault. The common trigger is a **tool-result turn**:
after a tool call the trailing message is a `tool_result`, not user text, so a
template looking for a user query to frame the response finds none. Small prompts
pass; reading a file does not.

Check any model before using it:

```
python tools/gguf_guards.py <model.gguf>              # report
python tools/gguf_guards.py <model.gguf> --patch out.gguf
```

Patching rewrites each guard to an equal-length Jinja comment (`{{-` â†’ `{#-`,
`}}` â†’ `#}`), so the template's byte length and every later offset are unchanged
and the GGUF metadata stays valid. `setup.py` refuses to build from a GGUF with
live guards.

`gguf_guards` also validates the file is a structurally complete GGUF before
scanning or patching; a corrupt or truncated file is refused rather than
silently patched into a corrupt output.

**After `ollama create`, restart Ollama or force-unload the model.** A rebuild
writes a new manifest, but an already-loaded runner keeps serving the previous
weights until it unloads â€” so the fix appears not to work.

### No wildcard in config.yaml

`model_list` must contain only the exact model tag. An earlier `model_name: "*"`
entry routed *every* requested name to that model, so selecting a different model
in the UI or the Claude Model field silently served the wrong weights while the
UI showed the requested name. A wrong name now fails with HTTP 400 instead.

## Model layout

Weights live in `Models/` at the project root. `selected_gguf` is stored as
`Models/<filename>` (or a bare `<filename>` when the GUI dropdown sets it), and
`configs.modelfile_from_path` renders it as an **absolute** forward-slash path.
Ollama on Windows rejects a `FROM ./Models/<file>` line â€” it derives a model name
from the source string, the leading `.` fails validation, and the server answers
with a misleading "Error: 400 Bad Request: invalid model name" that looks like a
bad tag. The Modelfile is regenerated whenever the model changes, so the absolute
path costs nothing in portability.

The active model is chosen at runtime, not baked in: the Settings â†’ GGUF File
dropdown lists **only** the files inside `Models/`. A model that lives on another
drive is added via Browseâ€¦, and its location is remembered in
`.state/external_paths.json` so the tracked configs never hard-code this machine's
absolute path. Selecting a model rewrites the Modelfile and `config.yaml` together
via `write_all`, which refuses to write if the tag and weights disagree.

Switching models restores that model's own tuning from `.state/models.json`
(keyed by filename â€” context, temperature, sampling params, and the Ollama tag)
so a model installed under a custom tag (e.g. `qwythos-heretic`) keeps it and its
settings when you switch back. If the selected model's tag is not yet installed
in Ollama, the GUI prompts to create it from the Modelfile.

Adding a model: drop the `.gguf` in `Models/`, check it with
`python tools/gguf_guards.py Models/<file>` â€” this validates the file is a
well-formed GGUF and reports live chat-template guards â€” patch it if needed,
then pick it in Settings or run `setup.py`. Unpatched originals can be parked in
`Models/_originals/`; the `*.gguf` glob is non-recursive so they stay out of the
dropdown.

---

## Design System

### Visual Theme: Cayde 420
Bone plating over gunmetal, lit by a visor-orange glow.

- **Monospace everywhere** â€” font stack: Cascadia Mono â†’ JetBrains Mono â†’ Consolas â†’ DejaVu Sans Mono
- **Bone is text, gunmetal is background** â€” never reversed
- **Orange is rationed** â€” `ember` is for brand, focus, primary action, and glow only. If everything is orange, nothing is.
- **Green is status-only** â€” `led_green` appears on lamps and the "live" pill, nowhere else. `BarMeter` ramps bone â†’ orange so load never reads as an error.
- `COLORS` dict in `styles.py` is the single source of truth for all palette values
- Derive translucent tints with `styles.rgba(key, alpha)` rather than hand-writing `rgba()` literals â€” literals drift out of sync when the palette changes
- **App name comes from `styles.APP_NAME` / `ASSISTANT_NAME` / `TITLE`, not literals.** Never type "Cayde 420" into a UI string, and never reach for the model tag there instead. Heading labels use `letter-spacing` (3â€“4px) to get the tracked-out Destiny feel rather than ALL CAPS, so the casing stays uniform across every surface.
- QSS stylesheets live entirely in `styles.py` â€” no inline QSS strings in `main.py` except one-off bubble overrides
- Custom painted widgets (texture, glow, LEDs, knobs) live in `widgets.py` â€” QSS cannot express these

### Widget Conventions
- `CrackedBackdrop` + `ScanlineOverlay` â€” always full-window, always `WA_TransparentForMouseEvents`, resized in `resizeEvent`
- `LEDDot.set_state()` â€” states: "green", "amber", "red", "off"
- `HardwareStrip.set_lamps(pwr, io, gpu)` + `set_plate(text)` â€” called from `_sync_hw_strip()` in MainWindow
- `BarMeter.set_level(0.0-1.0)` â€” driven by `tokens_per_sec / 30.0`

---

## Module Dependency Graph

```
main.py
  â”œâ”€â”€ backend.py      (OllamaBackend, ChatWorker, ModelManager, LiteLLMStarter, StatusWorker)
  â”œâ”€â”€ styles.py       (get_main_stylesheet, rgba, COLORS)
  â”œâ”€â”€ widgets.py      (all custom painted widgets)
  â”œâ”€â”€ configs.py      (ModelConfig, load_full, write_all, derive_model_tag)
  â”œâ”€â”€ settings.py     (load, save)
  â”œâ”€â”€ history.py      (auto_save, save_session, load_session, list_sessions, load_auto_save)
  â”œâ”€â”€ memory_vault.py (read/write/build_block/compose_system_prompt/strip_vault)
  â””â”€â”€ hardware.py     (detect â†’ HardwareReport + Recommendations)

backend.py
  â”œâ”€â”€ configs.py      (derive_model_tag)
  â”œâ”€â”€ memory_vault.py (compose_system_prompt, strip_vault)
  â””â”€â”€ settings.py

configs.py
  â””â”€â”€ settings.py

config.py
  â”œâ”€â”€ configs.py
  â”œâ”€â”€ hardware.py
  â””â”€â”€ settings.py

setup.py
  â”œâ”€â”€ configs.py
  â”œâ”€â”€ hardware.py
  â”œâ”€â”€ memory_vault.py (build_block, write_block_file â€” for the CLI flag)
  â””â”€â”€ settings.py

mcp_server.py
  â””â”€â”€ mcp_grants.py   (has_capability / describe / default_root)

mcp_grants.py
  â””â”€â”€ settings.py     (SETTINGS_DIR only â€” resolves .state/mcp_grants.json)

opencode_bridge.py
  â””â”€â”€ configs.py      (load_full â€” tag, URLs, context/max_tokens)

widgets.py
  â””â”€â”€ styles.py       (COLORS only)
```

`backend.py` and `widgets.py` do NOT import each other. Keep it that way.
`settings.py`, `history.py`, and `mcp_grants.py` have zero GUI imports â€” pure
data layers. `mcp_server.py` imports the MCP SDK lazily inside `build_server()`,
so `--grant`/`--list` work without it. `main.py` imports `opencode_bridge`
inside the OpenCode button handler, not at module scope.

---

## Key Patterns

### Config round-trip (always use this)
```python
from pathlib import Path
from configs import load_full, write_all, ModelConfig

cfg = load_full(Path(working_dir))          # reads Modelfile + config.yaml
cfg2 = cfg.with_updates(context_size=65536) # immutable update
write_all(cfg2, Path(working_dir))          # writes both files
```
Never hand-roll Modelfile/config.yaml strings in the GUI. That was the V0.1 bug we fixed in V0.2.

### Backend URL access (live-mutable)
`backend.py` uses instance-level `ollama_base_url`, `litellm_base_url`, `litellm_api_key` on `OllamaBackend`, with an `update_urls()` method for hot-swapping. Persisted via `settings.py` to `.state/settings.json`.

### Streaming signals (ChatWorker)
```
token_received(str)       â†’ append to bubble, scroll
generation_complete(str)  â†’ finalize, auto-save history
error_occurred(str)       â†’ render error bubble
stats_update(dict)        â†’ drive BarMeter + HardwareStrip plate
```

### Status signal flow
```
backend.check_status() (every 5s)
  â†’ ollama_status_changed("live"|"offline")            â†’ LEDDot + _sync_hw_strip + _update_banner
  â†’ litellm_status_changed("live"|"offline")           â†’ LEDDot + _sync_hw_strip + _update_banner
  â†’ model_status_changed("ready"|"not_found"|"unknown") â†’ LEDDot + _sync_hw_strip + _update_banner
  â†’ model_list_updated(list[str])                      â†’ model switcher dropdown in Settings sidebar
```

---

## Version History

### V0.1 â€” Initial commit (b3eaac7)
- Basic PySide6 chat GUI functional
- Ollama + LiteLLM backend with streaming
- TUI config tool (config.py)
- `configs.py` and `hardware.py` written but not wired into GUI
- `widgets.py` written but never imported anywhere

### V0.2 â€” Widget integration + config cleanup
- All `widgets.py` widgets wired into `main.py` (CrackedBackdrop, ScanlineOverlay, LEDDot, HardwareStrip, BarMeter, MascotGlyph)
- `SettingsPanel` refactored: uses `configs.load_full()` / `configs.write_all()` instead of hand-rolled template
- Added Connection settings group (Engine Mode, LiteLLM URL/Key, Ollama URL)
- Added Auto-detect Hardware button (calls `hardware.detect()`)
- `requirements.txt` completed (added pynvml, ollama)
- Status bar: QLabel pills â†’ LEDDot, plain stats label â†’ BarMeter + HardwareStrip

---

## Roadmap

> This section is owner-maintained. Agents: do not rewrite this section, only check it for context.
> Owner: add/edit items freely â€” move ðŸ”² to âœ… when done and add a version tag.

### V0.3 â€” Wiring + Persistence

- âœ… **Live URL wiring** â€” `backend.py` URL constants became instance vars; `update_urls()` method; `_apply_settings()` pushes URLs into backend immediately without restart and persists to `.state/settings.json`
- âœ… **Direct Ollama mode** â€” `ChatWorker` supports native Ollama `/api/chat` streaming when `engine_mode == "direct"`, bypassing LiteLLM entirely; status banner and hardware strip adapt to direct mode
- âœ… **System prompt editor** â€” `QTextEdit` in Settings sidebar Model & Persona group; `_apply_settings()` calls `backend.set_system_prompt()`
- âœ… **Live Ollama model switcher** â€” editable `QComboBox` in Settings sidebar populated from `model_list_updated` signal; switching calls `backend.set_model_tag()`
- âœ… **Asynchronous health polling (No UI lockups)** â€” health check polling decoupled from Qt GUI thread into background `StatusWorker(QThread)`
- âœ… **CPU thread allocation (3c/6t cap)** â€” `hardware.py` recommendations and defaults allocate 3 cores / 6 threads (`num_thread 6`) to prevent heavy inference from starving the host OS and GUI
- âœ… **Chat history persistence** â€” `history.py` module; JSON sessions in `~/.qwythos/history/`; auto-save on generation complete; Load/Save buttons in header bar; restores on launch via Load

### V0.4 â€” Ideas

- âœ… **Conversation export** â€” `Ctrl+S` exports to Markdown via `QFileDialog`; `MessageBubble` copy button for single messages
- ðŸ”² Multi-model comparison view (same prompt â†’ 2 models side-by-side)
- âœ… **Token count display per message** â€” `estimate_tokens()` heuristic (~4 chars/token) shown as `~N tokens` under each bubble
- âœ… **Keyboard shortcuts** â€” `Ctrl+L` clear, `Ctrl+N` new session, `Ctrl+S` save conversation (via `QShortcut`)
- âœ… **Auto-scroll toggle** â€” follows output only while user is at the bottom; scrolling up pauses, scrolling back down resumes
- âœ… **Copy button on assistant bubbles** â€” click to copy full response to clipboard with "Copied" feedback
- âœ… **System tray icon / minimize to tray** â€” `_setup_tray()` generates icon at runtime; `closeEvent` hides to tray with notification; Show/Hide + Quit menu; click tray to toggle
- âœ… **Auto-start LiteLLM on app launch** â€” checkbox in Settings â†’ Connection; persisted to `settings.json`; `_maybe_autostart_litellm()` fires 1.5s after launch
- âœ… **Stop button always visible** â€” enabled/disabled instead of shown/hidden; `ChatWorker.cancel()` closes the active response to unblock `iter_lines()` immediately
- âœ… **Launch Claude CLI from GUI** â€” `âš¡ Claude CLI` button in header; sets `ANTHROPIC_*` env vars, spawns `claude` in a new console window (no `--model`; see above)

### V0.5 â€” Multi-model onboarding + Windows fixes (2026-10-05)

- âœ… **Project-local model layout** â€” weights in `Models/`, generated per-model Modelfiles in `Modelfiles/` (gitignored); the GGUF dropdown and `setup.py` scan `Models/` and derive an Ollama tag from the filename.
- âœ… **Ollama Windows FROM fix** â€” `configs.modelfile_from_path` emits an absolute forward-slash path; Ollama rejects `./Models/...` with a misleading "invalid model name". Bare dropdown names resolve into `Models/`.
- âœ… **Tag sanitisation** â€” `derive_model_tag` caps tags at 80 chars with a hash suffix (collision-safe) and strips leading separators Ollama rejects.
- âœ… **GGUF integrity validation** â€” `tools/gguf_guards.py` refuses to scan or patch a corrupt file (via the `gguf` package or a structural walk).
- âœ… **setup.py guard-check fixes** â€” skips URL `FROM`s, no longer misclassifies absolute Windows paths, and drops a misplaced `die()` that aborted every local build.
- âœ… **Onboarded three guarded models** â€” `Qwen3.5-4B-EmperoAI-Heretic-guarded`, `Qwythos-9B-Claude-Mythos-5-1M-MTP-Q4_K_M-guarded`, and the active `qwythos-heretic`.
- âœ… **Dependency checker script** â€” `check_and_install_deps.bat` scans for Python 3.11+ (with a real version check), Ollama (with a fallback for its non-PATH default install), and optional npm; opens download pages for missing tools and installs `requirements.txt`.
- âœ… **Drag-and-drop GGUF install** â€” drag .gguf files onto app window to copy to Models/, validate GGUF integrity, show installation instructions.
- âœ… **Service control buttons** â€” Settings panel has Start/Kill buttons for LiteLLM and Ollama with status polling and health log viewers.
- ðŸ”² **Defiant Fable onboarding** â€” source GGUF is corrupt (the `gguf` parser fails); re-download required before it can be built.

### V0.6 â€” Agent capabilities (planned, ordered by cost/benefit)

Build order is deliberate: cheapest-and-most-useful first, so each item lands
on a working app rather than arriving with the last batch.

**1. âœ… Memory vault (persistent markdown memory)**
`memory_vault.py` â€” flat module, pure data layer, no GUI imports (mirrors
`history.py`). Reads/writes `*.md` under `.state/memory/` and returns the
concatenated block for injection.
- Composition is additive via `compose_system_prompt(persona)`: an empty or
  disabled vault returns the persona byte-for-byte, so a model keeps its own
  baked-in SYSTEM block. `configs.MODELFILE_TEMPLATE` is untouched.
- `strip_vault()` strips a previously-injected block before the persona
  round-trips through the Settings text box, so repeated Apply cannot stack
  copies until the cap truncates real memory.
- Capped at `DEFAULT_MAX_CHARS` (10k). Entries are dropped whole, never sliced,
  and the omission is stated in the block so the model knows its memory is
  partial.
- Reaches the CLI through `--append-system-prompt-file` against a generated
  `.state/memory_block.md` â€” the block is too large for argv and would need a
  layer of shell quoting through `start cmd /k`.
- Editor in Settings â†’ Memory Vault; enable checkbox, entry picker, live token
  readout that turns amber over budget.

**2. âœ… MCP workspace server (tools for the Claude CLI)**
`mcp_server.py` â€” FastMCP server exposing workspace file/command tools, with the
grant data split into `mcp_grants.py` so the GUI, the TUI, and the server can all
read and edit grants without importing the MCP SDK. `claude` launches it via
`python mcp_server.py --serve`.
- **Denied by default.** `mcp_grants.py` ships an empty grant list and
  `.state/mcp_grants.json` is per-PC, gitignored state, so a fresh clone can read
  nothing at all until the user runs `--grant`. There is deliberately no
  first-launch auto-grant: that silently widens what an LLM can reach the first
  time the CLI is started.
- **Explicit per-directory grants, stored resolved.** One absolute directory per
  grant, no wildcard, no "parent implies child". `grant()` resolves before
  writing, so a stored grant cannot later be re-pointed by moving the process
  cwd. An entry with no valid capabilities is dropped rather than defaulted to a
  full grant, and an unknown capability key in a hand-edited JSON is ignored.
- **Read, write, and shell are separate capabilities.** A read-only grant cannot
  be talked into a write, and shell is never implied by write. Note that
  `--grant` *without* `--read-only` grants all three at once â€” `--read-only` is
  the only way to get read and nothing else from the CLI.
- **Resolve before compare.** `resolve_grant` fully resolves the target (`..`
  and symlinks applied) *before* the containment test. Comparing the literal
  string is the classic escape â€” `C:/proj/../secrets` looks like it starts with
  `C:/proj` and is not inside it.
- **Every spawn is bounded.** 30s hard timeout, 30k chars per output stream, no
  shell interpolation, and a 2 MB ceiling on `read_file`. `edit_file` refuses
  rather than guessing when the search text appears more than once.
- âš ï¸ **`shell` gates the working directory, not the command's reach.** It is a
  `cwd` jail, not a syscall sandbox: a granted command can still read and write
  anywhere the user can. There is **no command allowlist** â€” the guide's
  `execute_powershell_cmd` was not shipped and `run_command` accepts any command
  string. Grant `shell` only where that is acceptable, or edit `.state/mcp_grants.json`
  down to `["read"]`.
- **Denials never leak the filesystem.** An out-of-grant path gets the same
  message whether or not it exists, and no raw exception class is surfaced.
- **Manual registration only.** `--register` prints the `claude mcp add` line and
  exits. Cayde 420 never runs it, because it mutates the user's Claude config and
  persists for every future launch in this project.
- `tests/test_mcp_jail.py` â€” 14 tests: no-grant denial, `..` traversal, symlink
  escape, capability separation, revoke-immediately, disclosure-free denials, the
  30s timeout, the output cap, and a hand-edited grants file failing to smuggle
  in a capability.

**3. ðŸ”² Vision / image input**
Drag-and-drop or paste an image into the chat input â†’ base64 â†’ multi-modal
message content array.
- âš ï¸ **Blocked on model acquisition.** All three models in `Models/` are text-only
  Heretic fine-tunes; none can see. A vision-capable GGUF must be onboarded
  first. Code is the easy half.
- âš ï¸ **Must route through LiteLLM, not `api_base=11434`.** LiteLLM is mandatory
  precisely because it spoofs the Anthropic API for `claude`. A direct-to-Ollama
  path means the CLI cannot see images even when the GUI can.
- `config.yaml` serves one exact tag. A second vision model needs a routing
  decision, and the "no wildcard" rule stands â€” a second model is an explicit
  second `model_list` entry, never `"*"`.

**4. ðŸ”² Voice (STT, then TTS)**
`voice_engine.py` â€” record + transcribe in a `QThread`, mirroring the existing
`ChatWorker`/`StatusWorker` pattern so the GUI thread never blocks.
- `faster-whisper` on CPU, int8, `base` model. The model must be loaded **once**
  and held by the worker; the guide reloads it per request, which adds seconds of
  stall to every utterance.
- Record-then-transcribe, not streaming, to start. STT first; TTS is a separate
  item once STT is stable.
- `sounddevice` + `scipy` are new deps and must be added to `requirements.txt`
  and `pyproject.toml` together.

**5. ðŸ”² Hand tracking / gesture control** â€” lowest priority, do last
Webcam pinch-to-cursor, mapping to Qt widgets via a `QThread`.
- âš ï¸ **Dependency risk, verify in an isolated venv first.** Local Python is 3.13;
  `mediapipe` resolves to 1.0.1, but the guide uses the legacy
  `mp.solutions.hands` API and 1.0.x moved to the Tasks API (`HandLandmarker`).
  Confirm the shipped version actually exposes `solutions` before writing a line.
- Needs a pinch deadzone/deadband. Raw per-frame pinch state jitters and will
  feel broken driving a real widget.
- Heaviest deps of anything on this list for the least certain payoff, and it
  needs a gesture vocabulary designed for the whole app before it is useful.

**Deliberately not adopted:** the guides' `src/gui/`, `src/core/`, `src/mcp/`
restructure. It contradicts the flat-module dependency graph above, and
`pyproject.toml`'s `py-modules` list plus `config.py`/`setup.py` all assume flat.
New modules stay flat. Revisit only if the app genuinely outgrows flat layout.

### Backlog

- âœ… **Multi-GGUF management** â€” `GGUF File` dropdown in Settings â†’ Model & Persona; switching rebuilds Modelfile/config.yaml and hot-swaps the model tag
- âœ… **Drag-and-drop GGUF install** â€” drag .gguf files onto app window to copy to Models/, validate GGUF integrity, and show installation instructions
- âœ… **Tool/plugin system for the model** â€” framework created in `plugins/` directory for extensible tools (web search, file read, code exec)
- ðŸ”² **Multi-model comparison view** â€” same prompt, two models side-by-side

---

## How to Run

```powershell
# Install deps (once)
pip install -r requirements.txt

# Launch GUI
python main.py
# or double-click:
launch.bat

# Full setup (first time or new model)
setup.bat
# or
python setup.py

# Terminal config TUI (hardware tuning without the GUI)
python config.py

# Point OpenCode at the same local stack, then start it
python opencode_bridge.py --launch

# Grant the claude CLI access to a directory, then register the MCP server
python mcp_server.py --grant "C:\path\to\project"
python mcp_server.py --register    # prints the `claude mcp add` line; run it yourself
```

**Prerequisites:**
- Python 3.11+
- Ollama installed and running (`ollama serve`) â€” https://ollama.com
- One or more GGUF models in `Models/` (see "Model layout" above); the active model is `Qwen3.5-9B-Heretic-patched2.gguf` (â‰ˆ5.8 GB), built as the Ollama tag `qwythos-heretic`
- `litellm` available in PATH (satisfied by `pip install -r requirements.txt`)
- *(Optional)* `claude` and/or `opencode` on PATH, for the CLI paths above

---

## Gotchas & Known Issues

| Issue | Notes |
|
- GPU config: NVIDIA RTX 2070 SUPER (primary, 8GB VRAM) on PCIe x16 slot 1; AMD RX 580 (auxiliary, 8GB VRAM) on PCIe x4 slot. llamaGPU support files at C:\Users\nick\Desktop\llamaGPU (vulkan + nvidia folders). **Critical fix**: Modelfile `num_gpu 99` → `num_gpu 1` to force NVIDIA-only usage. Without this, Ollama spreads layers across both GPUs causing VRAM issues. Also ensure `CUDA_VISIBLE_DEVICES="0"` in main.py Ollama launch env (already correct).

---|---|
| Backend URLs are live-mutable | Fixed in V0.3 via `settings.py` and `OllamaBackend.update_urls()`. Endpoints are hot-swapped without restart and persisted to `.state/settings.json`. |
| UI lockups during polling | Resolved in V0.3 by offloading synchronous `requests.get` health checks into a background `StatusWorker(QThread)`. The main GUI event loop is never blocked. |
| CPU starvation during inference | Resolved in V0.3 by allocating 3 cores / 6 threads (`num_thread 6`) instead of 100% of CPU cores, leaving capacity for the OS and UI. |
| LiteLLM crash mid-generation | Resolved: `ChatWorker.cancel()` closes the active response to unblock `iter_lines()`; exception handler checks `_cancelled` and emits normal completion instead of an error. |
| `derive_model_tag` was duplicated | Fixed: single definition lives in `configs.py`; `backend.py` imports it from there. |
| The MCP server can reach the whole disk | It cannot, and the denial is not a UI nicety â€” `mcp_grants.py` ships an empty grant list, `.state/mcp_grants.json` is per-PC and gitignored, and every path tool refuses until the user runs `python mcp_server.py --grant <dir>`. `read`/`write`/`shell` are separate capabilities and the containment test runs on the fully resolved path. One honest limit: `shell` bounds the command's **working directory** only, so grant it only where a command running with your own privileges is acceptable. |
| `claude mcp add` would persist into every future launch | Hence manual registration. `python mcp_server.py --register` prints the exact command and exits; nothing in Cayde 420 runs it. Remove it again with `claude mcp remove cayde-workspace --scope local`. |
| OpenCode's config is a file OpenCode owns | `opencode_bridge.py` merges only its own `cayde` provider block into `~/.config/opencode/opencode.json`, takes a backup to `opencode.cayde-bak` first, and refuses outright (leaving the file alone) if it cannot parse it. Re-running it with nothing changed is byte-identical. Never rewrite the whole file to add one entry. |

---

## Agent Handoff Notes

1. **Read this file first, then `main.py` top-to-bottom** â€” fastest orientation path.
2. **Never write Modelfile or config.yaml by hand** â€” always use `configs.write_all(ModelConfig(...), path)`.
3. **Never add inline QSS strings to `main.py`** â€” add color/style to `styles.py`, reference via `COLORS` and `rgba()`.
4. **Never import `main.py` from any other module** â€” it is the root entry point only.
5. **Check the Roadmap section above** before proposing new features â€” the owner updates it.
6. **Verify changes with:** `python -c "from main import *; from configs import *; from widgets import *; print('OK')"`

