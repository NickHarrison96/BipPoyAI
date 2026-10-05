"""
Inspect or neutralise the raise_exception guards in a GGUF chat template.

Claude Code aborted with HTTP 500s whose message named a Jinja CallExpression
inside the model's own chat template. These templates ship with guards such as

    {{- raise_exception('No user query found in messages.') }}

that abort rendering when a message shape the template does not expect arrives.
The common case is a tool-result turn: after a tool call the trailing message
carries a tool_result rather than user text, so a template that looks for a user
query to frame the response finds none and raises. Small prompts pass; reading a
file does not.

Usage
-----
  python tools/gguf_guards.py <model.gguf>              # report
  python tools/gguf_guards.py <model.gguf> --patch out.gguf

Patching rewrites each guard to an equal-length Jinja comment:

    {{- raise_exception('...') }}   ->   {#- raise_exception('...') #}

{{- and {#- are both three bytes, }} and #} are both two, so the template's
length and every subsequent byte offset are unchanged. That is what keeps the
GGUF metadata valid without recomputing it.

The source file is never modified; --patch always writes elsewhere.
"""

import re
import sys
from pathlib import Path

CHUNK = 8 * 1024 * 1024
OVERLAP = 128 * 1024

# {{- raise_exception( ... ) }}  ->  {#- raise_exception( ... ) #}
GUARD = re.compile(rb"\{\{-(?P<body>\s*raise_exception\(.*?\))\s*\}\}", re.DOTALL)


def iter_guards(path: Path):
    """Yield (offset, guard_text) for every raise_exception guard in the file."""
    carry = b""
    offset = 0
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(CHUNK)
            if not chunk:
                break
            data = carry + chunk
            base = offset - len(carry)
            if b"raise_exception" in data:
                text = data.decode("utf-8", "replace")
                for m in re.finditer(r"raise_exception", text):
                    start = text.rfind("\n", 0, m.start()) + 1
                    end = text.find("\n", m.end())
                    line = text[start:end if end != -1 else None].strip()
                    yield base + m.start(), line
            carry = data[-OVERLAP:]
            offset += len(chunk)


def report(path: Path) -> int:
    """Print guard status. Returns the number of LIVE (unpatched) guards."""
    live, done, seen = 0, 0, set()
    for _, line in iter_guards(path):
        if line.startswith("{#"):
            done += 1
        else:
            live += 1
        if line not in seen:
            seen.add(line)
            marker = "patched" if line.startswith("{#") else "LIVE   "
            print(f"  [{marker}] {line[:100]}")
    print()
    print(f"  live guards   : {live}")
    print(f"  already off   : {done}")
    return live


def patch(src: Path, dst: Path) -> int:
    """Write a copy with every live guard commented out. Size must not change."""
    count = 0

    def repl(m):
        nonlocal count
        new = b"{#-" + m.group("body") + b" #}"
        if len(new) != len(m.group(0)):
            raise SystemExit("internal error: patch changed length")
        count += 1
        return new

    with open(src, "rb") as fin, open(dst, "wb") as fout:
        carry = b""
        while True:
            chunk = fin.read(CHUNK)
            if not chunk:
                break
            data = carry + chunk
            # Only rewrite the region we can safely re-scan next iteration.
            fout.write(GUARD.sub(repl, data[:-OVERLAP]))
            carry = data[-OVERLAP:]
        fout.write(GUARD.sub(repl, carry))

    a, b = src.stat().st_size, dst.stat().st_size
    if a != b:
        dst.unlink(missing_ok=True)
        raise SystemExit(f"size mismatch: {a} -> {b}; refusing to keep the output")
    print(f"  guards neutralised : {count}")
    print(f"  size               : {a:,} (unchanged)")
    return count


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}

    if not args:
        print(__doc__)
        return 2

    src = Path(args[0])
    if not src.exists():
        print(f"not found: {src}")
        return 2

    print(f"model: {src}")
    print(f"size : {src.stat().st_size:,} bytes")
    print()

    if "--patch" in flags:
        if len(args) < 2:
            print("--patch needs an output path")
            return 2
        dst = Path(args[1])
        print("patching guards ->", dst)
        patch(src, dst)
        print()
        print("verifying output:")
        report(dst)
        return 0

    live = report(src)
    if live:
        print()
        print(f"  {live} live guard(s) will abort on some message shapes.")
        print(f"  Fix:  python {Path(sys.argv[0]).name} {src} --patch <out.gguf>")
        return 1
    print("  OK - no live guards; this model can handle tool-result turns.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())