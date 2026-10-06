"""One-off: confirm the excludes actually kept the heavy ML stack out of the
frozen archive. Reads the PYZ module table PyInstaller generates, which is the
authoritative list of what ships inside dist/Cayde420.exe."""
import re
import sys
from pathlib import Path

EXCLUDED = ["torch", "transformers", "scipy", "pandas", "IPython", "pytest"]
REQUIRED = ["PySide6", "ollama", "mcp", "psutil", "pynvml", "requests"]
# Qt submodules are compiled extension modules (.pyd), so they live in the
# Analysis binary table rather than the pure-Python PYZ archive.
REQUIRED_BINARIES = ["PySide6.QtWidgets", "PySide6.QtGui", "PySide6.QtCore"]

pyz = Path("build/Cayde420/PYZ-00.toc")
if not pyz.exists():
    sys.exit(f"missing {pyz}")

text = pyz.read_text(encoding="utf-8", errors="replace")
# Top-level module names in the archive look like 'torch', 'torch.nn',
# 'litellm.proxy', ... quoted and comma/closing-bracket terminated.
names = set(re.findall(r"'([A-Za-z_][\w.]*)'", text))
top = {n.split(".")[0] for n in names}

analysis = Path("build/Cayde420/Analysis-00.toc")
analysis_text = analysis.read_text(encoding="utf-8", errors="replace") if analysis.exists() else ""

bad = sorted(m for m in EXCLUDED if m in top)
good = sorted(m for m in REQUIRED if m in top)

print("excluded but STILL bundled:", bad or "none")
print("required  and bundled    :", good or "none")
missing = [m for m in REQUIRED if m not in top]
if missing:
    print("required  and MISSING    :", missing)

missing_bins = [b for b in REQUIRED_BINARIES if b not in analysis_text]
print("Qt .pyd modules missing  :", missing_bins or "none")

sys.exit(1 if bad or missing or missing_bins else 0)
