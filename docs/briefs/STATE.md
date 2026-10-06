# STATE — read this first

Working dir: `C:\Users\nick\Documents\GitHub\Cayde-420`
Branch: `main`. Last commit: `a399fd4 kk`.

> ⚠️ **A very large changeset is UNCOMMITTED.** Everything from the rename through
> the memory vault, the MCP server, and the OpenCode bridge is sitting in the
> working tree. If you are a subagent, do not run `git checkout`, `git stash`, or
> anything destructive. If you are the owner, this wants a commit.

## Verify state before trusting this file

```
python -c "from main import *; from configs import *; from widgets import *; print('OK')"
python tests/test_memory_vault.py
python tests/test_mcp_jail.py
python tests/test_opencode_bridge.py
```

---

## The goal

Cayde 420 is a local-only offline AI desktop app. The owner wants it to be a
**buddy AI** drivable from any client — a self-contained offline Claude Code
CLI, OpenCode, the GUI — all pointed at their own `.gguf` weights with no
internet. MCP is the extension seam for adding capabilities (voice, video) to
whichever client is in use.

## Architecture (do not break these)

```
claude CLI  /  opencode  /  GUI
        │
        ▼
  LiteLLM Proxy :4000        ← spoofs api.anthropic.com. MANDATORY.
        │                      Without it the CLI clients cannot talk to a
        ▼                      local Ollama tag at all.
  Ollama :11434
        │
        ▼
  Models/*.gguf
```

Rules that exist because breaking them caused real bugs:

- **Never hand-write `Modelfile` or `config.yaml`.** Always
  `configs.write_all(cfg, working_dir)`.
- **Never hardcode a SYSTEM prompt.** It silently overwrote Heretic's
  personality once. Persona is `ModelConfig.system_prompt`; the memory vault is
  composed additively on top.
- **No `"*"` wildcard in `model_list`.** It routed every model name to one set of
  weights while the UI showed whatever was asked for. A wrong name must fail.
- **Do not pass `--model <ollama-tag>` to `claude`.** It validates against its own
  list and hangs. Set `ANTHROPIC_MODEL` instead.
- **Context is 32768, not 65536.** 65536 does not fit beside the weights on an
  8 GB GPU; throughput collapses from ~9.8 to ~5 tok/s.
- **Force UTF-8 in child processes** (`PYTHONIOENCODING=utf-8`, `PYTHONUTF8=1`)
  or LiteLLM dies before serving.
- **Flat modules only.** Both upstream guides proposed `src/gui/`, `src/core/`,
  `src/mcp/`. Rejected — contradicts the dependency graph and `py-modules`.
- **App name comes from `styles.APP_NAME` / `ASSISTANT_NAME` / `TITLE`.**
- **Never type the model tag (`qwythos-heretic`) into a UI string.** It is a model
  name, not the app name.
- **An OpenCode baseURL must end in `/v1`.** See the resolved bug below.

## Shipped and verified

| Thing | Verified by |
|---|---|
| Rename to Cayde 420 (identity only) | grep + import |
| Destiny restyle (gunmetal + visor orange) | offscreen render |
| `memory_vault.py` + GUI editor + CLI flag | `test_memory_vault.py` — 13 tests |
| `mcp_grants.py` + `mcp_server.py` | `test_mcp_jail.py` — 14 tests |
| `opencode_bridge.py` | `test_opencode_bridge.py` — 25 tests |
| OpenCode button in GUI header | offscreen instantiate |
| `mcp` in requirements.txt + pyproject | verified installed version |

**52 tests across three suites, all green.**

## The resolved `/v1` bug — worth understanding

`@ai-sdk/anthropic` appends `/messages` to whatever `baseURL` it is given. The
bridge was writing `http://127.0.0.1:4000`, so OpenCode requested
`/messages`. Verified against a live LiteLLM:

```
POST /v1/messages  -> HTTP 400   (route exists)
POST /messages     -> HTTP 404   (route does not exist)
```

Every OpenCode request would have 404'd. `with_api_version()` in
`opencode_bridge.py` now normalises the URL, and three caller-side tests assert
the *wiring*, not just the helper — because a correct helper nobody calls is
exactly the failure mode that slipped through.

## Verified facts about the environment

- **Ollama is NOT running.** Live end-to-end checks are impossible until the
  owner starts it. Say so rather than claiming something works untested.
- **`opencode.json` and `opencode.jsonc` MERGE.** Both are read. Confirmed via
  `opencode debug config`: `MCP_DOCKER` (from `.json`) and `ollama` (from
  `.jsonc`) both appear in the resolved config. Writing to `.json` is correct.
- **LiteLLM starts standalone** without Ollama — `litellm --config config.yaml
  --port 4123` serves routes and answers 400 on a bad model name. Useful for
  probing the proxy without the whole stack. Kill it when done.
- `mcp` 1.29.0 installed; `FastMCP` imports. Tool callables are reachable as
  `server._tool_manager._tools[name].fn` (private, but the tests use it).
- Python 3.13.15. `claude` CLI present. `opencode` 1.18.32 present.

## Traps

- **PowerShell 5.1 `Get-Content -Raw | Set-Content` CORRUPTS UTF-8.** Em-dashes
  become `â€"`. This already happened once and had to be reverted. Never rewrite
  a source file through the shell — use the edit tool.
- **Do not run `opencode debug config` casually.** It dumps thousands of lines of
  model catalog into the transcript. Grep the saved output file under
  `~/.local/share/opencode/tool-output/` instead.
- Offscreen Qt (`QT_QPA_PLATFORM=offscreen`) renders text as tofu boxes. That is
  a platform font artifact, not a bug. Real fonts exist.
- `mcp_server.py` grants: `--grant` alone gives read+write+shell. There is no
  CLI combination for read+write-without-shell; that requires hand-editing
  `.state/mcp_grants.json`.

## Honest limits of what was built

- **`shell` is a `cwd` jail, not a syscall sandbox.** A granted command can read
  and write anywhere the owner can. There is **no command allowlist**. Grant
  `shell` only where a command running with your own privileges is acceptable.
  Documented plainly rather than overclaimed.
- **OpenCode end-to-end has never actually run.** Only the config-merge
  behaviour is covered by tests. The GUI button and `--launch` are unproven
  until someone starts Ollama + LiteLLM and clicks it.
- **Defiant Fable GGUF is corrupt** — needs re-download before it can be built.
- **Vision (V0.6 item 3) is blocked** — no vision-capable model exists. All
  three GGUFs are text-only. Code is the easy half.

## Remaining backlog

1. **Commit the changeset.** Everything above is uncommitted.
2. **`build_exe.bat`** is untracked and stale — references
   `build\QwythosAI.ico`, left behind by the rename.
3. **End-to-end verify the OpenCode path** once Ollama is up.
4. **Grant the MCP server a directory** and try it from a real `claude` session.
5. V0.6 items 3 (vision), 4 (voice), 5 (hand tracking) — 3 is blocked.GPU config noted: RX 580 8GB in PCIe x4 slot, RTX 2070 SUPER remains in x16 slot 1. llamaGPU support files at C:\Users\nick\Desktop\llamaGPU (vulkan + nvidia folders). No code changes requested, notes only.
Global llama.cpp installed; separate Vulkan (RX 580) and NVIDIA (RTX 2070 SUPER) support files placed at C:\Users\nick\Desktop\llamaGPU. Plan: split GPU workload across devices. Notes only for now.
