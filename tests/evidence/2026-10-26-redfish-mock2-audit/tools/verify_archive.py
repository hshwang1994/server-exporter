"""zip 11개를 추출 루트에 풀고 원본과 파일 수·상대경로·sha256 을 전수 대조한다 (원본은 읽기만)."""
import hashlib, os, sys, zipfile, json
SRC = r"C:\github\서버mock데이터\2차"; ARCH = sys.argv[1]; EXT = sys.argv[2]
def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""): h.update(c)
    return h.hexdigest()
os.makedirs(EXT, exist_ok=True)
report = {}
ok_all = True
for s in sorted(d for d in os.listdir(SRC) if os.path.isdir(os.path.join(SRC, d))):
    with zipfile.ZipFile(os.path.join(ARCH, s + ".zip")) as zf:
        zf.extractall(EXT)
    src_map = {}
    for root, dirs, files in os.walk(os.path.join(SRC, s)):
        for fn in files:
            p = os.path.join(root, fn); src_map[os.path.relpath(p, os.path.join(SRC, s)).replace(os.sep, "/")] = sha(p)
    ext_map = {}
    for root, dirs, files in os.walk(os.path.join(EXT, s)):
        for fn in files:
            p = os.path.join(root, fn); ext_map[os.path.relpath(p, os.path.join(EXT, s)).replace(os.sep, "/")] = sha(p)
    missing = sorted(set(src_map) - set(ext_map)); extra = sorted(set(ext_map) - set(src_map))
    diff = sorted(k for k in src_map if k in ext_map and src_map[k] != ext_map[k])
    ok = not missing and not extra and not diff
    ok_all &= ok
    report[s] = {"src_files": len(src_map), "ext_files": len(ext_map), "missing": missing[:5], "extra": extra[:5], "sha_diff": diff[:5], "ok": ok}
    print(f"{s:16} src={len(src_map):5d} ext={len(ext_map):5d} missing={len(missing)} extra={len(extra)} sha_diff={len(diff)} -> {'OK' if ok else 'FAIL'}", flush=True)
# SHA256SUMS check
bad = []
for line in open(os.path.join(ARCH, "SHA256SUMS"), encoding="utf-8"):
    h, n = line.strip().split("  ", 1)
    if sha(os.path.join(ARCH, n)) != h: bad.append(n)
print("SHA256SUMS verify:", "OK" if not bad else f"FAIL {bad}")
json.dump(report, open(os.path.join(ARCH, "_verify_report.json"), "w", encoding="utf-8"), indent=1)
print("RESULT", "OK" if ok_all and not bad else "FAIL")
