"""se-indep 증거 해시 목록 (읽기 전용). usage: hash_tree.py <root> <out_file>"""
import hashlib, os, sys
root, out = sys.argv[1], sys.argv[2]
targets = ["INDEPENDENT_REVIEW_RESULT.md", "out", "tools"]
rows = []
for t in targets:
    p = os.path.join(root, t)
    if os.path.isfile(p):
        files = [p]
    else:
        files = [os.path.join(dp, f) for dp, _, fs in os.walk(p) for f in fs]
    for f in files:
        h = hashlib.sha256()
        with open(f, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        rows.append((os.path.relpath(f, root).replace(os.sep, "/"), os.path.getsize(f), h.hexdigest()))
rows.sort()
with open(out, "w", encoding="utf-8", newline="\n") as fh:
    for r, s, d in rows:
        fh.write(f"{d}  {s}  {r}\n")
print(len(rows), "files")
