"""Reproduce the failure: a tool_result turn carrying a large payload.

This is the shape that triggered 'No user query found in messages.' - the last
message is a tool result rather than user text.
"""
import json
import urllib.request

BIG = ("def handler():\n" + "    x = 1\n" * 400 + "\n") * 1

payload = {
    "model": "qwythos-heretic",
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
except Exception as e:
    print("ERROR", type(e).__name__, str(e)[:200])