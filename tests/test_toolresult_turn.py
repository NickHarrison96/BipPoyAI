"""Reproduce the failure: a tool_result turn carrying a large payload.

This is the shape that triggered 'No user query found in messages.' - the last
message is a tool result rather than user text.
"""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import configs

BIG = ("def handler():\n" + "    x = 1\n" * 400 + "\n") * 1

try:
    tag = configs.load_full(Path(".")).model_tag
except Exception as e:
    print("ERROR could not read config.yaml to resolve the active model tag:",
          type(e).__name__, str(e)[:200])
    print("Run this probe from the repo root so ./config.yaml is readable.")
    sys.exit(1)
if not tag:
    print("ERROR config.yaml has no active model tag - rebuild configs "
          "(Settings -> Save & Rebuild Configs) and re-run.")
    sys.exit(1)

payload = {
    "model": tag,
    "max_tokens": 200,
    "messages": [
        {"role": "user", "content": "Read main.py and summarise it."},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "Read",
             "input": {"file_path": "main.py"}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": BIG}]},
    ],
}

req = urllib.request.Request(
    "http://localhost:4000/v1/messages",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json",
             "x-api-key": "sk-litellm-local",
             "anthropic-version": "2023-06-01"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=900) as r:
        j = json.loads(r.read().decode())
    text = "".join(b["text"] for b in j["content"] if b["type"] == "text")
    print("HTTP", r.status, "| stop_reason:", j.get("stop_reason"))
    print("tool_result chars sent:", len(BIG))
    print("PASSED - no template exception")
    print("TEXT:", text[:200] if text else "(empty)")
except urllib.error.HTTPError as e:
    body = e.read().decode("utf-8", "replace")
    print("HTTP", e.code, "- STILL FAILING")
    print(body[:900])
except urllib.error.URLError as e:
    print("ERROR cannot reach the LiteLLM proxy at http://localhost:4000 -",
          str(e.reason)[:200])
    print("Start LiteLLM (Settings -> LiteLLM -> Start) and re-run this probe.")
except Exception as e:
    print("ERROR", type(e).__name__, str(e)[:200])