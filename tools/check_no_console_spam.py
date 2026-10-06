"""Launch dist/Cayde420.exe and prove the terminal-window spam is gone.

A `tasklist` spawned without CREATE_NO_WINDOW in a windowless (noconsole)
PyInstaller exe gets a freshly allocated console window, so its MainWindowHandle
is non-zero. With CREATE_NO_WINDOW the process still runs but owns no visible
window.

Samples visible top-level processes for SAMPLE_SECONDS once the GUI is up.
"""
import subprocess
import sys
import time
from pathlib import Path

EXE = Path("dist/Cayde420.exe")
GUI_WAIT = 60       # onefile extraction + Qt startup
SAMPLE_SECONDS = 25
WATCH = {"tasklist", "netstat", "cmd", "conhost", "powershell"}

if not EXE.exists():
    sys.exit(f"missing {EXE}")

proc = subprocess.Popen([str(EXE)])
print(f"launched pid {proc.pid}, waiting for GUI to come up...")

gui_seen = None
deadline = time.time() + GUI_WAIT
while time.time() < deadline:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-Process -Id %d -ErrorAction SilentlyContinue).MainWindowHandle" % proc.pid],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW,
    ).stdout.strip()
    if out and out != "0":
        gui_seen = time.time()
        print(f"GUI window appeared after {gui_seen - (deadline - GUI_WAIT):.1f}s")
        break
    if proc.poll() is not None:
        sys.exit(f"exe exited early with code {proc.returncode} (ordinal/DLL failure?)")
    time.sleep(1)

if gui_seen is None:
    proc.kill()
    sys.exit("GUI window never appeared within %ds" % GUI_WAIT)

# From here the 2s service-status poll is firing. Sample for visible windows.
def visible_from_watch():
    """Names of watched processes that own a visible top-level window."""
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-Process | Where-Object { $_.MainWindowHandle -ne 0 } | "
         "Select-Object -ExpandProperty Name"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW,
    ).stdout.split()
    return [n for n in out if n.lower().replace(".exe", "") in {w.lower() for w in WATCH}]

seen = []
samples = SAMPLE_SECONDS * 2
for i in range(samples):
    hits = visible_from_watch()
    if hits:
        seen.append((i, sorted(set(hits))))
    time.sleep(0.5)

proc.kill()
try:
    proc.wait(timeout=15)
except Exception:
    proc.kill()

print(f"samples taken: {samples} over {SAMPLE_SECONDS}s")
if seen:
    print(f"VISIBLE console windows observed in {len(seen)} samples:")
    for i, names in seen[:10]:
        print(f"  t=+{i/2:.1f}s  {names}")
    sys.exit(1)

print("no visible console windows from tasklist/netstat/cmd/conhost -> FIX CONFIRMED")
sys.exit(0)
