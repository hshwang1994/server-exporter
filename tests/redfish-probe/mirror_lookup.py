#!/usr/bin/env python3
"""full-mirror provenance 조회 헬퍼 — envelope 필드의 실제 Redfish source 를 1:1 대조.

replay_full_mirror.build_response_map 와 동일한 `@odata.id`→body 키잉을 재사용해, 미러
트리에서 URI 로 raw 리소스를 즉시 꺼내거나(`get`), 경로/타입으로 검색(`find`/`type`)한다.
검수 agent 가 "envelope 의 이 값이 정말 그 Redfish 리소스의 그 속성에서 왔는가" 를 추측 없이
실 raw 로 확인하기 위한 도구. stdlib 전용.

사용:
    python mirror_lookup.py get  <mirror_dir> <uri> [dotted.key ...]
    python mirror_lookup.py find <mirror_dir> <substr>
    python mirror_lookup.py type <mirror_dir> <odata_type_substr>
    python mirror_lookup.py keys <mirror_dir> <uri>         # 최상위 키만
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from replay_full_mirror import build_response_map  # noqa: E402
sys.path.insert(0, str(HERE.parents[1] / "redfish-gather" / "library"))


def _load(mirror_dir):
    rmap, root, stats = build_response_map(Path(mirror_dir))
    return rmap, root, stats


def _norm_key(uri: str) -> str:
    import redfish_gather as rg  # local import; replay already stubbed ansible
    k = rg._p(uri)
    if k == "__invalid_odata_id__" or uri.rstrip("/") == "/redfish/v1":
        return ""
    return k


def _drill(body, dotted):
    cur = body
    for part in dotted.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
                continue
            except (ValueError, IndexError):
                return "<no-index>"
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return "<missing>"
    return cur


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    cmd, mirror_dir = sys.argv[1], sys.argv[2]
    rmap, root, stats = _load(mirror_dir)

    if cmd == "get":
        uri = sys.argv[3]
        key = _norm_key(uri)
        if key not in rmap:
            print(f"[NOT-FOUND] {uri} (key={key!r})  files={stats['files']} keyed={stats['keyed']}")
            return 1
        status, body, err = rmap[key]
        if len(sys.argv) > 4:
            for dotted in sys.argv[4:]:
                print(f"{dotted} = {json.dumps(_drill(body, dotted), ensure_ascii=False)}")
        else:
            print(f"# status={status} err={err}")
            print(json.dumps(body, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    if cmd == "keys":
        uri = sys.argv[3]
        key = _norm_key(uri)
        if key not in rmap:
            print(f"[NOT-FOUND] {uri}")
            return 1
        _, body, _ = rmap[key]
        print(json.dumps(sorted(body.keys()) if isinstance(body, dict) else body, ensure_ascii=False))
        return 0

    if cmd == "find":
        sub = sys.argv[3].lower()
        hits = sorted(k for k in rmap if sub in k.lower())
        for k in hits:
            print(k)
        print(f"# {len(hits)} hits / {len(rmap)} keyed")
        return 0

    if cmd == "type":
        sub = sys.argv[3].lower()
        for k in sorted(rmap):
            _, body, _ = rmap[k]
            t = body.get("@odata.type", "") if isinstance(body, dict) else ""
            if sub in str(t).lower():
                print(f"{k}\t{t}")
        return 0

    print(f"[FAIL] unknown cmd: {cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
