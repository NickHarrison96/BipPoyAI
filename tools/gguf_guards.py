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
import struct
import sys
from pathlib import Path

CHUNK = 8 * 1024 * 1024
OVERLAP = 128 * 1024

# {{- raise_exception( ... ) }}  ->  {#- raise_exception( ... ) #}
GUARD = re.compile(rb"\{\{-(?P<body>\s*raise_exception\(.*?\))\s*\}\}", re.DOTALL)

# GGUF metadata may legitimately hold a chat template that is a few hundred KB,
# but nothing anywhere near 16 MiB (the cap Ollama enforces). Tensor and
# metadata key names are a handful of bytes. Anything beyond these bounds means
# the parser has desynced from a corrupt or truncated file, not a real value.
MAX_NAME = 4096
MAX_STRING = 16 * 1024 * 1024


class CorruptGGUF(Exception):
    """The file is not a valid, complete GGUF."""


def validate_gguf(path: Path) -> None:
    """Raise CorruptGGUF if `path` is not a structurally valid GGUF.

    A corrupt file (bad header, desynced metadata, or a garbage tensor-info
    name/offset) is easy to mistake for a working model: a guard scan can still
    find `raise_exception` text inside the chat template, and `--patch` will
    happily copy the corruption and report success. Ollama then fails later
    with a cryptic "error reading GGUF item ...". Catch it here instead.

    The `gguf` package is used when available (authoritative); otherwise a
    conservative structural walk validates the header, every metadata entry,
    and every tensor info against the file's own length fields.
    """
    size = path.stat().st_size

    try:
        import gguf  # type: ignore
    except ImportError:
        gguf = None

    if gguf is not None:
        try:
            gguf.GGUFReader(str(path))
            return
        except Exception as e:  # noqa: BLE001 - any failure here is corruption
            raise CorruptGGUF(str(e)) from e

    _validate_gguf_manual(path, size)


def _validate_gguf_manual(path: Path, size: int) -> None:
    """Dependency-free structural validation used when `gguf` is not installed."""
    scalar_size = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}

    with open(path, "rb") as fh:
        head = fh.read(24)
        if len(head) != 24 or head[:4] != b"GGUF":
            raise CorruptGGUF("missing or invalid GGUF magic header")
        _, _, tensor_count, kv_count = struct.unpack("<4sIQQ", head)

        def read(n: int) -> bytes:
            b = fh.read(n)
            if len(b) != n:
                raise CorruptGGUF("file truncated (unexpected EOF)")
            return b

        for i in range(kv_count):
            (klen,) = struct.unpack("<Q", read(8))
            if klen > MAX_NAME:
                raise CorruptGGUF(f"metadata key {i}: absurd name length {klen}")
            read(klen)
            (vtype,) = struct.unpack("<I", read(4))
            if vtype not in scalar_size and vtype not in (8, 9):
                raise CorruptGGUF(f"metadata key {i}: invalid value type {vtype}")
            if vtype == 8:
                (slen,) = struct.unpack("<Q", read(8))
                if slen > MAX_STRING:
                    raise CorruptGGUF(f"metadata key {i}: string length {slen} exceeds maximum")
                read(slen)
            elif vtype == 9:
                (etype,) = struct.unpack("<I", read(4))
                (count,) = struct.unpack("<Q", read(8))
                if etype == 8:
                    for _ in range(count):
                        (slen,) = struct.unpack("<Q", read(8))
                        if slen > MAX_STRING:
                            raise CorruptGGUF(f"metadata key {i}: array string length {slen} exceeds maximum")
                        read(slen)
                else:
                    esize = scalar_size.get(etype)
                    if esize is None:
                        raise CorruptGGUF(f"metadata key {i}: invalid array element type {etype}")
                    if count * esize > size:
                        raise CorruptGGUF(f"metadata key {i}: array larger than file")
                    read(count * esize)
            else:
                read(scalar_size[vtype])

        for i in range(tensor_count):
            (nlen,) = struct.unpack("<Q", read(8))
            if nlen < 1 or nlen > MAX_NAME:
                raise CorruptGGUF(f"tensor {i}: absurd name length {nlen}")
            read(nlen)
            (ndims,) = struct.unpack("<I", read(4))
            if ndims > 16:
                raise CorruptGGUF(f"tensor {i}: absurd dimension count {ndims}")
            read(8 * ndims)
            (ttype,) = struct.unpack("<I", read(4))
            if ttype > 63:
                raise CorruptGGUF(f"tensor {i}: invalid tensor type {ttype}")
            (offset,) = struct.unpack("<Q", read(8))
            if offset > size:
                raise CorruptGGUF(f"tensor {i}: offset {offset} beyond file size")


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

    try:
        validate_gguf(src)
    except CorruptGGUF as e:
        print(f"  ERROR: this file is not a valid GGUF ({e}).")
        print("  It is likely truncated or corrupt. Re-download or re-export it")
        print("  before scanning or patching; a patch of a corrupt file is itself corrupt.")
        return 2

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