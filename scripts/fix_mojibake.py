"""Repair files damaged by a Windows PowerShell 5 round-trip (Get-Content reads UTF-8 without BOM as ANSI, Set-Content -Encoding utf8 writes a BOM):
'§' became 'Â§', '—' became 'â€”', and a BOM was added. python scripts/fix_mojibake.py <file> [...]  (--check only reports)
Undo = decode the damaged text as UTF-8, encode it back to cp1252, decode that as UTF-8. A file is only rewritten when the result is clean."""
import sys

BAD = ("Â", "Ã", "â€")


def repair(text):
    try:
        fixed = text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        out = []                                                        # line by line: keep a line that is fine, fix one that is damaged
        for ln in text.splitlines(keepends=True):
            if any(b in ln for b in BAD):
                try:
                    ln = ln.encode("cp1252").decode("utf-8")
                except (UnicodeEncodeError, UnicodeDecodeError):
                    pass
            out.append(ln)
        fixed = "".join(out)
    return fixed


check = "--check" in sys.argv
for path in [a for a in sys.argv[1:] if a != "--check"]:
    raw = open(path, "rb").read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw[3:].decode("utf-8") if bom else raw.decode("utf-8")
    damaged = any(b in text for b in BAD)
    if not bom and not damaged:
        print(f"ok      {path}")
        continue
    fixed = repair(text) if damaged else text
    left = any(b in fixed for b in BAD)
    print(f"{'CHECK ' if check else 'fixed '} {path}: bom={bom} damaged={damaged}{' STILL DAMAGED, not written' if left else ''}")
    if not check and not left:
        open(path, "wb").write(fixed.encode("utf-8"))
