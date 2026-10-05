"""
Network diagnostics — shared by setup.py (CLI) and backend.py (GUI).

LiteLLM 1.102+ silently falls back to a random port when the requested port
is already occupied. These helpers let both spawn paths detect the conflict
up front and report the PID instead of leaving the user with a proxy on an
unexpected port.

Also hosts the LiteLLM health probe: the deep /health endpoint queries the
Ollama backend and takes ~5.4s to answer, so callers must never use a short
timeout against it (a 3s timeout made the GUI status LED never turn green
while chat worked fine). The fast /health/liveliness probe answers in ~5ms.
"""

import re
import socket
import subprocess
from typing import Optional

import requests


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """True if something is listening on host:port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex((host, port)) == 0


def pid_on_port(port: int) -> Optional[int]:
    """Windows: PID of the process listening on TCP `port`, else None."""
    try:
        out = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        ).stdout
    except Exception:
        return None
    for line in out.splitlines():
        if "LISTENING" not in line:
            continue
        if not re.search(rf":{port}\s", line):
            continue
        m = re.search(r"LISTENING\s+(\d+)\s*$", line.strip())
        if m:
            return int(m.group(1))
    return None


def litellm_healthy(base_url: str) -> bool:
    """True if the LiteLLM proxy at base_url is up.

    Prefers the fast /health/liveliness probe (~5ms). Falls back to the deep
    /health endpoint (~5.4s; it queries Ollama backends) for LiteLLM versions
    without the liveness route. Connection failures return False immediately.
    """
    try:
        r = requests.get(f"{base_url}/health/liveliness", timeout=5)
        if r.status_code == 200:
            return True
        if r.status_code == 404:
            # Older LiteLLM: deep health is the only probe - allow it time.
            return requests.get(f"{base_url}/health", timeout=15).status_code == 200
        return False
    except requests.exceptions.ConnectionError:
        return False
    except Exception:
        return False


def litellm_ready(base_url: str) -> bool:
    """True when LiteLLM has finished loading its config and can route.

    Spec Step 3 gates launch on /health/readiness (200 = routes live), which is
    stricter than liveliness (process up but config may still be loading).
    Falls back to liveliness for versions without the route.
    """
    try:
        r = requests.get(f"{base_url}/health/readiness", timeout=15)
        if r.status_code == 200:
            return True
        if r.status_code == 404:
            return litellm_healthy(base_url)
        return False
    except requests.exceptions.ConnectionError:
        return False
    except Exception:
        return False
