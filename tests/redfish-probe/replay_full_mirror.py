#!/usr/bin/env python3
"""redfish_full_mirror.py 로 떠온 전수 미러를 실제 gather 코드에 오프라인 재생.

redfish_full_mirror.py 가 장비에서 떠온 `<out>/redfish/v1/.../index.json` (+ headers.json)
트리를 @odata.id 로 키잉한 GET 응답 맵으로 만들고, redfish_gather.py 의 `_get` /
`_get_noauth` 를 그 맵으로 monkeypatch 한 뒤 `main()` 과 동일한 수집 흐름
(detect_vendor → _collect_all_sections → _collect_multi_node_topology →
_compute_final_status) 을 그대로 구동한다.

목적: 가정된 합성 fixture 가 아니라 *실 장비가 실제로 준 raw* 기준으로 수집 envelope 를
재현해 — 필드 출처(어느 Redfish path/필드에서 왔는지) / 누락 / 타입 / 병합 / 실패 처리 /
결과 JSON 구조를 오프라인 검수. stdlib 전용.

사용:
    python replay_full_mirror.py <mirror_dir> [--layout rmc_primary] [--out env.json]
    # <mirror_dir> = redfish_full_mirror.py 의 -D 산출물 (예: .../DELL_R740/01)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))

# redfish_gather 는 ansible.module_utils.basic.AnsibleModule 를 import. 오프라인 stub.
_stub_basic = types.ModuleType("ansible.module_utils.basic")
_stub_basic.AnsibleModule = object
_stub_module_utils = types.ModuleType("ansible.module_utils")
_stub_module_utils.basic = _stub_basic
_stub_ansible = types.ModuleType("ansible")
_stub_ansible.module_utils = _stub_module_utils
sys.modules.setdefault("ansible", _stub_ansible)
sys.modules.setdefault("ansible.module_utils", _stub_module_utils)
sys.modules.setdefault("ansible.module_utils.basic", _stub_basic)

import redfish_gather as rg  # noqa: E402


def _reason(status: int) -> str:
    return {
        200: "OK", 201: "Created", 204: "No Content",
        400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
        404: "Not Found", 405: "Method Not Allowed", 500: "Internal Server Error",
        501: "Not Implemented", 503: "Service Unavailable",
    }.get(status, "Unknown")


def build_response_map(mirror_dir: Path):
    """미러 트리 → {path_key: (status, body, err)} + service_root body.

    path_key = rg._p(body['@odata.id'])  (gather 의 _get 호출 path 와 동일 정규화).
    status   = headers.json 의 _status (없으면 200).
    service_root (@odata.id == '/redfish/v1') 는 _p 가 무효 처리하므로 별도 키 '' 로 등록.
    """
    response_map: dict[str, tuple] = {}
    service_root = None
    n_files = 0
    n_keyed = 0
    dupes = []

    for index_fp in mirror_dir.rglob("index.json"):
        n_files += 1
        try:
            with open(index_fp, encoding="utf-8") as fh:
                body = json.load(fh)
        except Exception:
            continue
        # status from sibling headers.json
        status = 200
        hdr_fp = index_fp.parent / "headers.json"
        if hdr_fp.exists():
            try:
                with open(hdr_fp, encoding="utf-8") as fh:
                    hdrs = json.load(fh)
                status = int(hdrs.get("_status", 200))
            except Exception:
                status = 200

        if not isinstance(body, dict):
            continue
        oid = body.get("@odata.id")
        if not isinstance(oid, str):
            continue

        if oid.rstrip("/") == "/redfish/v1":
            service_root = body
            # service root 도 인증 경로(_get(bmc_ip,''))로 접근 가능하게 '' 키 등록
            err = None if 200 <= status < 300 else f"HTTP {status}: {_reason(status)}"
            response_map[""] = (status, body, err)
            continue

        key = rg._p(oid)
        if key == "__invalid_odata_id__":
            continue
        err = None if 200 <= status < 300 else f"HTTP {status}: {_reason(status)}"
        if key in response_map and response_map[key][1] is not body:
            dupes.append(key)
        response_map[key] = (status, body, err)
        n_keyed += 1

    return response_map, service_root, {"files": n_files, "keyed": n_keyed, "dupes": dupes}


def install_fakes(response_map: dict):
    """rg 의 모든 HTTP 진입점을 맵 기반 fake 로 교체."""

    def fake_get(bmc_ip, path, username, password, timeout, verify_ssl):
        if path in response_map:
            return response_map[path]
        return 404, {}, f"HTTP 404: {_reason(404)}"

    def fake_get_noauth(bmc_ip, path, timeout, verify_ssl):
        if path in response_map:
            return response_map[path]
        return 404, {}, f"HTTP 404: {_reason(404)}"

    rg._get = fake_get
    rg._get_noauth = fake_get_noauth


def run(mirror_dir: Path, manager_layout=None):
    response_map, service_root, stats = build_response_map(mirror_dir)
    install_fakes(response_map)

    creds = ("u", "p", 10, False)
    bmc_ip = "10.0.0.1"

    vendor, system_uri, manager_uri, chassis_uri, det_errors, root = rg.detect_vendor(
        bmc_ip, *creds
    )
    all_errors = list(det_errors)
    collected, failed, unsupported = [], [], []
    probe_facts = rg._extract_probe_facts(root, vendor)

    if not system_uri:
        envelope = {
            "status": "failed", "vendor": vendor,
            "collected": [], "failed_sections": ["all"], "unsupported_sections": [],
            "errors": all_errors, "data": {}, "probe_facts": probe_facts,
            "multi_node": None,
        }
        return envelope, stats, (system_uri, manager_uri, chassis_uri)

    result_data = rg._collect_all_sections(
        bmc_ip, vendor, system_uri, manager_uri, chassis_uri,
        *creds, all_errors, collected, failed, unsupported,
        manager_layout=manager_layout,
        product_hint=rg._safe(root, "Product"),
    )

    multi_node = rg._collect_multi_node_topology(
        bmc_ip, vendor, root, *creds, manager_layout=manager_layout
    )
    if isinstance(multi_node, dict):
        all_errors.extend(multi_node.get("errors") or [])

    final_status, clean = rg._compute_final_status(collected, failed, all_errors)

    envelope = {
        "status": final_status, "vendor": vendor,
        "collected": clean, "failed_sections": sorted(set(failed)),
        "unsupported_sections": sorted(set(unsupported)),
        "errors": all_errors, "data": result_data, "probe_facts": probe_facts,
        "multi_node": multi_node,
    }
    return envelope, stats, (system_uri, manager_uri, chassis_uri)


def main() -> int:
    ap = argparse.ArgumentParser(description="full mirror → gather 오프라인 재생")
    ap.add_argument("mirror_dir", help="redfish_full_mirror.py -D 산출물 디렉터리")
    ap.add_argument("--layout", default=None, help="manager_layout (예: rmc_primary)")
    ap.add_argument("--out", default=None, help="envelope JSON 저장 경로")
    args = ap.parse_args()

    mirror_dir = Path(args.mirror_dir)
    if not mirror_dir.exists():
        print(f"[FAIL] mirror_dir 없음: {mirror_dir}", file=sys.stderr)
        return 2

    envelope, stats, uris = run(mirror_dir, manager_layout=args.layout)

    out_json = json.dumps(envelope, indent=2, ensure_ascii=False, sort_keys=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(out_json)

    print("=" * 60)
    print(f"  REPLAY: {mirror_dir}")
    print("=" * 60)
    print(f"  mirror files   : {stats['files']}  keyed: {stats['keyed']}  dupes: {len(stats['dupes'])}")
    print(f"  vendor         : {envelope['vendor']}")
    print(f"  system_uri     : {uris[0]}")
    print(f"  manager_uri    : {uris[1]}")
    print(f"  chassis_uri    : {uris[2]}")
    print(f"  status         : {envelope['status']}")
    print(f"  collected      : {envelope['collected']}")
    print(f"  failed         : {envelope['failed_sections']}")
    print(f"  unsupported    : {envelope['unsupported_sections']}")
    print(f"  errors         : {len(envelope['errors'])}")
    print(f"  data sections  : {sorted(envelope['data'].keys())}")
    if args.out:
        print(f"  envelope saved : {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
