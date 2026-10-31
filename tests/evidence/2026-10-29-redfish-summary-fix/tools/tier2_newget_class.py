import json, sys, os
from pathlib import Path
REPO = Path(sys.argv[1]); sys.path.insert(0, str(REPO / "tests" / "redfish-probe" / "mirror_replay"))
os.environ.setdefault("SE_REPO_ROOT", str(REPO))
from mirror_policy import Mirror
E = "C:/github/ClovirONE/mock2-fix-20261028/extract"; M1 = "C:/github/서버mock데이터/1차"
dirs = {"csus3200_01": f"{E}/csus3200_01", "csus3200_02": f"{E}/csus3200_02", "csus3200_03": f"{E}/csus3200_03",
        "dl380_gen12_01": f"{E}/dl380_gen12_01", "dl380_gen12_02": f"{E}/dl380_gen12_02", "dl380_gen12_04": f"{E}/dl380_gen12_04",
        "r1_DELL_R740_01": f"{M1}/DELL_R740/01", "r1_HPE_CSUS3200_01": f"{M1}/HPE_CSUS3200/01", "r1_HPE_CSUS3200_02": f"{M1}/HPE_CSUS3200/02",
        "r1_HPE_CSUS3200_03": f"{M1}/HPE_CSUS3200/03", "r1_HPE_CSUS3200_04": f"{M1}/HPE_CSUS3200/04", "r1_HPE_DL380_01": f"{M1}/HPE_DL380/01",
        "dl380_gen12_03": f"{E}/dl380_gen12_03"}
paths = {}
for line in open(sys.argv[2], encoding="utf-8"):
    r = json.loads(line); paths.setdefault(r["label"], []).append(r["path"])
# r1 CSUS 01/02 already requested Chassis/r001u01/Drives before (A-10); include for completeness
paths.setdefault("r1_HPE_CSUS3200_01", []).append("Chassis/r001u01/Drives")
paths.setdefault("r1_HPE_CSUS3200_02", []).append("Chassis/r001u01/Drives")
out = []
for label, ps in sorted(paths.items()):
    m = Mirror(dirs[label])
    for p in ps:
        st, _h, body, note = m.lookup(p, True)
        b = body
        if isinstance(b, (bytes, bytearray)): b = b.decode("utf-8", "replace")
        if isinstance(b, str):
            try: b = json.loads(b)
            except Exception: b = None
        n = len(b.get("Members") or []) if isinstance(b, dict) and "Members" in b else None
        ld = len(((b or {}).get("Links") or {}).get("Drives") or []) if isinstance(b, dict) else None
        dl = "Drives" in b if isinstance(b, dict) else None
        cls = "MIRROR_REAL" if note in ("tree", "tree-empty", "manifest", "raw") else "MOCK_LIMITATION"
        out.append({"label": label, "path": p, "status": st, "note": note, "members": n, "links_drives": ld, "has_drives_link": dl, "class": cls})
for r in out: print(json.dumps(r, ensure_ascii=False))
