"""2차 Mock 원본 → 서버당 zip + SHA256SUMS + MANIFEST.json (scratchpad). 원본은 읽기만 한다."""
import hashlib, json, os, sys, time, zipfile
SRC = r"C:\github\서버mock데이터\2차"
OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
manifest = {"source": SRC, "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "tool": "make_archive.py (zipfile deflate 6)", "servers": {}}
sums = []
servers = sorted(d for d in os.listdir(SRC) if os.path.isdir(os.path.join(SRC, d)))
for s in servers:
    sdir = os.path.join(SRC, s)
    zpath = os.path.join(OUT, s + ".zip")
    nfiles = 0; nbytes = 0
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, dirs, files in os.walk(sdir):
            dirs.sort()
            for fn in sorted(files):
                p = os.path.join(root, fn)
                rel = s + "/" + os.path.relpath(p, sdir).replace(os.sep, "/")
                zf.write(p, rel)
                nfiles += 1; nbytes += os.path.getsize(p)
    m = json.load(open(os.path.join(sdir, "_manifest.json"), encoding="utf-8"))
    zsha = sha256_file(zpath)
    sums.append((zsha, s + ".zip"))
    manifest["servers"][s] = {
        "zip": s + ".zip", "zip_sha256": zsha, "zip_bytes": os.path.getsize(zpath),
        "files": nfiles, "bytes": nbytes,
        "mirror_tool_version": m.get("tool_version"), "manifest_schema": m.get("manifest_schema"),
        "result": m.get("result"), "exit_code": m.get("exit_code"), "auth_mode": m.get("auth_mode"),
        "root_product": m.get("root_product"), "root_redfish_version": m.get("root_redfish_version"),
        "started": m.get("started"), "finished": m.get("finished"), "duration_s": m.get("duration_s"),
        "discovered": m.get("discovered"), "fetched_ok": m.get("fetched_ok"),
        "counts": {k: (len(m.get(k)) if isinstance(m.get(k), list) else m.get(k)) for k in
                   ["absent", "not_gettable", "rejected", "outside_account", "device_error", "oversize", "unresolved", "excluded", "skipped", "non_json", "accept_fallback", "action_targets"]},
        "incomplete_reasons": m.get("incomplete_reasons"),
        "device_error_paths": [e.get("path") for e in (m.get("device_error") or [])],
        "firmware_versions": m.get("firmware_versions"),
        "integrity": m.get("integrity"),
    }
    print(f"{s:16} files={nfiles:5d} bytes={nbytes/1e6:6.1f}MB zip={os.path.getsize(zpath)/1e6:5.1f}MB sha256={zsha[:12]}", flush=True)
# run.log
import shutil
shutil.copyfile(os.path.join(SRC, "run.log"), os.path.join(OUT, "run.log"))
sums.append((sha256_file(os.path.join(OUT, "run.log")), "run.log"))
with open(os.path.join(OUT, "MANIFEST.json"), "w", encoding="utf-8", newline="\n") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=1)
sums.append((sha256_file(os.path.join(OUT, "MANIFEST.json")), "MANIFEST.json"))
with open(os.path.join(OUT, "SHA256SUMS"), "w", encoding="utf-8", newline="\n") as f:
    for h, n in sums:
        f.write(f"{h}  {n}\n")
tot = sum(v["zip_bytes"] for v in manifest["servers"].values())
print("TOTAL zip bytes", tot, "servers", len(servers))
