#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tier 1 합성 미러 만들기 (2026-10-29, WSL 에서 실행 — stdlib 만).

expected.json 의 cases[*].edits 대로 원본 미러를 사본으로 복사하고 JSON 1~3 곳만 바꾼다.
- 원본 미러는 읽기만 한다. 사본 경로가 이미 있으면 그 case 는 중단한다(덮어쓰지 않음).
- 각 edit 의 old 값이 현재 파일 값과 다르면 중단한다(엉뚱한 파일을 고치지 않게).
- 수정 전후 sha256 을 manifest(JSON)로 남긴다. 사본은 커밋하지 않는다.

사용: python3 make_syn.py <expected.json> <manifest_out.json> [case ...]
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _walk(obj, dotted):
    # 최상위에 그 이름의 키가 있으면 그대로 쓴다('Drives@odata.count' 처럼 점이 든 키). 없으면 점으로 내려간다('body.Fabrics').
    if dotted in obj:
        return obj, dotted
    parts = dotted.split(".")
    for k in parts[:-1]:
        obj = obj[k]
    return obj, parts[-1]


def apply_edit(root, e):
    fp = root / e["file"]
    before = sha256(fp)
    doc = json.loads(fp.read_text(encoding="utf-8"))
    parent, key = _walk(doc, e["key"])
    op = e["op"]
    if op in ("delete", "set") and "old" in e:
        if parent.get(key) != e["old"]:
            raise SystemExit("old mismatch %s %s: %r != %r" % (e["file"], e["key"], parent.get(key), e["old"]))
    if op == "delete":
        del parent[key]
    elif op == "set":
        parent[key] = e["value"]
    elif op == "list_remove":
        cur = parent[key]
        for item in e["remove"]:
            if item not in cur:
                raise SystemExit("list_remove: %r not in %s %s" % (item, e["file"], e["key"]))
        parent[key] = [x for x in cur if x not in e["remove"]]
    else:
        raise SystemExit("unknown op %s" % op)
    fp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"file": e["file"], "op": op, "key": e["key"], "sha256_before": before, "sha256_after": sha256(fp)}


def main():
    exp_path, man_out = Path(sys.argv[1]), Path(sys.argv[2])
    only = set(sys.argv[3:])
    exp = json.loads(exp_path.read_text(encoding="utf-8"))
    mroot, sroot = Path(exp["mirror_root"]), Path(exp["syn_root"])
    sroot.mkdir(parents=True, exist_ok=True)
    out = {"expected_sha256": sha256(exp_path), "mirror_root": str(mroot), "syn_root": str(sroot), "cases": {}}
    for name in sorted(exp["cases"]):
        if only and name not in only:
            continue
        c = exp["cases"][name]
        src, dst = mroot / c["base_dir"], sroot / name
        if dst.exists():
            raise SystemExit("exists, refusing to overwrite: %s" % dst)
        shutil.copytree(src, dst, symlinks=True)
        out["cases"][name] = {"base_dir": str(src), "syn_dir": str(dst),
                              "edits": [apply_edit(dst, e) for e in c["edits"]]}
        print("made", name, "->", dst)
    man_out.write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
