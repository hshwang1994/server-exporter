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
import re
import sys
import types
import urllib.parse
from collections import Counter
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
        200: "OK", 201: "Created", 202: "Accepted", 204: "No Content",
        400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
        405: "Method Not Allowed", 406: "Not Acceptable", 408: "Request Timeout", 409: "Conflict",
        410: "Gone", 415: "Unsupported Media Type", 422: "Unprocessable Entity", 429: "Too Many Requests",
        500: "Internal Server Error", 501: "Not Implemented", 502: "Bad Gateway",
        503: "Service Unavailable", 504: "Gateway Timeout",
    }.get(status, "Unknown")


def _err_of(status: int):
    return None if 200 <= status < 300 else f"HTTP {status}: {_reason(status)}"


# v1 크롤러가 쿼리가 붙은 경로(페이지네이션)를 디렉터리명으로 바꿀 때 쓴 규칙. v2 는 redfish_full_mirror._fs_segment.
_V1_BAD = re.compile(r'[\x00-\x1f<>:"|?*\x5c]')
_REPLAY_IP = "10.0.0.1"
_MANIFEST_STATUS_LISTS = ("absent", "not_gettable", "rejected", "outside_account", "device_error", "unresolved",
                          "wellknown", "failed", "auth_failures")      # 뒤 둘은 v1 manifest 의 목록 이름(v2 에서는 별칭)


def _read_json(fp: Path):
    try:
        with open(fp, encoding="utf-8") as fh:
            return True, json.load(fh)
    except (OSError, ValueError):          # UnicodeDecodeError / JSONDecodeError 는 ValueError 계열
        return False, None


def _load_fsmap(mirror_dir: Path) -> dict:
    """v2 크롤러의 _fsmap.json -> {상대 디렉터리(소문자): 요청 경로(쿼리 포함)}. 없거나 깨졌으면 빈 dict (v1 트리).
    크롤러는 대소문자를 무시해도 폴더 이름이 유일하도록 저장하므로 소문자로 조회한다. Windows(NTFS)에 풀면 중간 폴더의
    대소문자가 합쳐져 디스크의 폴더 이름과 _fsmap.json 의 dir 대소문자가 어긋나기 때문이다."""
    ok, data = _read_json(mirror_dir / "_fsmap.json")
    out = {}
    if ok and isinstance(data, dict) and isinstance(data.get("paths"), dict):
        for path, ent in data["paths"].items():
            if isinstance(ent, dict) and isinstance(ent.get("dir"), str):
                out[ent["dir"].lower()] = path
    return out


def _key_of(path):
    """요청 경로(쿼리 포함, 절대 URL 가능) -> gather 의 _get() 인수 키. ServiceRoot 는 ''.
    gather 키는 /redfish/v1 기준 상대 경로라 그 밖의 경로(/redfish, /html/...)는 다른 리소스와 충돌하므로 None 이다."""
    if not isinstance(path, str):
        return None
    if "://" in path:
        parts = urllib.parse.urlsplit(path)
        path = parts.path + ("?" + parts.query if parts.query else "")
    base, sep, query = path.partition("?")
    if base.rstrip("/") == "/redfish/v1":
        return ""
    if not base.startswith("/redfish/v1/"):
        return None
    key = rg._p(base)
    return None if key == "__invalid_odata_id__" else key + (sep + query if sep else "")


def _dir_candidates(key: str):
    """키 -> 크롤러가 그 요청을 저장했을 수 있는 상대 디렉터리 후보 (v1 규칙, v2 규칙, 트리 루트가 redfish/v1 인 경우 포함)."""
    segs = [s for s in key.split("/") if s]
    names = ["/".join(_V1_BAD.sub("_", s)[:200] for s in segs)]
    try:
        import redfish_full_mirror as tool
        v2 = "/".join(tool._fs_segment(s) for s in segs)
        if v2 not in names:
            names.append(v2)
    except ImportError:
        pass
    return ["redfish/v1/" + n for n in names] + names


def _next_key(current_key: str, link):
    """Members@odata.nextLink -> 다음 페이지 키. gather 의 _nextlink_path 와 같은 해석 (다른 호스트면 경로만 취한다)."""
    k = rg._nextlink_path(_REPLAY_IP, current_key, link)
    if k is None and isinstance(link, str):
        parts = urllib.parse.urlsplit(urllib.parse.urljoin(
            "https://%s/redfish/v1/%s" % (_REPLAY_IP, current_key.lstrip("/")), link.strip()))
        if parts.path.startswith("/redfish/v1"):
            k = _key_of(parts.path + ("?" + parts.query if parts.query else ""))
    return k


def _n_members(body) -> int:
    members = body.get("Members") if isinstance(body, dict) else None
    return len(members) if isinstance(members, list) else 0


def _load_entries(mirror_dir: Path, dir_to_path: dict):
    """index.json 마다 (디렉터리, 본문, 상태, 요청 키). 요청 경로를 모르는 v1 항목은 @odata.id 로 키잉한다."""
    files = sorted(mirror_dir.rglob("index.json"), key=lambda p: str(p).lower())
    entries, n_non_json, n_skipped = [], 0, 0
    for index_fp in files:
        rel = index_fp.parent.relative_to(mirror_dir).as_posix()
        rel = "" if rel == "." else rel
        ok, body = _read_json(index_fp)
        if not ok or not isinstance(body, dict):
            n_skipped += 1
            continue
        status = 200
        hdr_fp = index_fp.parent / "headers.json"
        if hdr_fp.exists():
            okh, hdrs = _read_json(hdr_fp)
            if okh and isinstance(hdrs, dict):
                try:
                    status = int(hdrs.get("_status", 200))
                except (TypeError, ValueError):
                    status = 200
        if status <= 0:                            # v1 이 전송 실패(timeout 등)를 status 0 으로 남긴 항목 - HTTP 응답이 아니다
            n_skipped += 1
            continue
        if body.get("_non_json") is True:          # raw.<확장자> 로 따로 저장된 XML / 바이너리의 안내 파일
            n_non_json += 1
            continue
        req = dir_to_path.get(rel.lower())
        oid = body.get("@odata.id")
        if body.get("_empty") is True:             # 204 / 본문 없는 응답
            req, body = (req or body.get("_path")), {}
        elif req is None and isinstance(oid, str):
            req = oid
        elif req is None and not 200 <= status < 300:   # v1 의 오류 본문(@odata.id 없음): 디렉터리 경로를 요청 경로로 본다
            req = "/" + rel
        key = _key_of(req)
        if key is None:
            n_skipped += 1
            continue
        entries.append({"dir": rel, "body": body, "status": status, "key": key, "fixed": rel.lower() in dir_to_path})
    return entries, len(files), n_non_json, n_skipped


def _restore_pages(entries: list) -> None:
    """v1 트리: 후속 페이지 본문의 @odata.id 는 컬렉션 id 그대로라 1페이지를 덮어썼다. nextLink 를 따라 후속 페이지
    디렉터리를 찾아 그 페이지의 요청 키(?쿼리 포함)를 돌려준다. 요청 경로를 이미 아는 항목(v2)은 건드리지 않는다."""
    by_dir = dict((e["dir"].lower(), e) for e in entries)
    todo = [e for e in entries if isinstance(e["body"].get("Members@odata.nextLink"), str)]
    visited = set()
    while todo:
        e = todo.pop()
        if e["dir"] in visited:
            continue
        visited.add(e["dir"])
        nk = _next_key(e["key"], e["body"].get("Members@odata.nextLink"))
        target = None
        for cand in (_dir_candidates(nk) if nk else []):
            if cand.lower() in by_dir:
                target = by_dir[cand.lower()]
                break
        if target is None:
            continue
        if not target["fixed"]:
            target["key"] = nk
        if isinstance(target["body"].get("Members@odata.nextLink"), str):
            todo.append(target)


def _page_report(response_map: dict):
    """nextLink 사슬마다 페이지 수 / 실제 멤버 수 / 1페이지의 Members@odata.count 를 대조한다. 끊기거나 수가 다르면 기록한다."""
    next_of = {}
    for key, (_st, body, _err) in response_map.items():
        link = body.get("Members@odata.nextLink") if isinstance(body, dict) else None
        nk = _next_key(key, link) if isinstance(link, str) else None
        if nk:
            next_of[key] = nk
    followed = set(next_of.values())
    pages, mismatch = [], []
    for head in sorted(k for k in next_of if k not in followed):
        cur, seen, total, n_pages, cut = head, {head}, _n_members(response_map[head][1]), 1, None
        while cur in next_of:
            nk = next_of[cur]
            if nk in seen:
                cut = "cycle"
                break
            if nk not in response_map:
                cut = "missing_page"
                break
            seen.add(nk)
            cur, n_pages = nk, n_pages + 1
            total += _n_members(response_map[nk][1])
        declared = response_map[head][1].get("Members@odata.count")
        declared = declared if isinstance(declared, int) and not isinstance(declared, bool) else None
        rec = {"collection": head, "pages": n_pages, "members": total, "declared": declared, "cut": cut,
               "match": (declared == total) if (declared is not None and cut is None) else None}
        pages.append(rec)
        if cut or (declared is not None and declared != total):
            mismatch.append(rec)
    return pages, mismatch


def build_response_map(mirror_dir: Path):
    """미러 트리 -> {path_key: (status, body, err)} + service_root body + stats.

    path_key 는 gather 의 _get() 인수와 같다 (rg._p 정규화, ?쿼리 포함, ServiceRoot 는 '').
      - v2 트리(_fsmap.json): 크롤러가 실제로 요청한 경로로 키잉한다 (페이지네이션 2페이지 이후도 ?쿼리 로 구분).
      - v1 트리: 본문 @odata.id 로 키잉하되 nextLink 사슬로 후속 페이지의 요청 키를 복원한다.
    status 는 headers.json 의 _status 다. 2xx 가 아닌 항목은 200 으로 올리지 않고 (status, body, 'HTTP n: 사유') 로 둔다.
    v2 manifest 의 absent / outside_account / not_gettable / rejected / device_error 상태도 (본문 없이) 되살린다.
    stats: files / keyed / dupes / pages / page_mismatch / non_json / skipped / from_manifest / statuses.
    """
    mirror_dir = Path(mirror_dir)
    entries, n_files, n_non_json, n_skipped = _load_entries(mirror_dir, _load_fsmap(mirror_dir))
    _restore_pages(entries)

    response_map, service_root, dupes, n_keyed = {}, None, [], 0
    for e in entries:
        if e["key"] in response_map:
            dupes.append(e["key"])
        response_map[e["key"]] = (e["status"], e["body"], _err_of(e["status"]))
        if e["key"] == "":
            service_root = e["body"]            # ServiceRoot 는 인증 경로(_get(bmc_ip, ''))로도 접근 가능
        else:
            n_keyed += 1

    from_manifest = 0
    ok_m, man = _read_json(mirror_dir / "_manifest.json")
    if ok_m and isinstance(man, dict):
        for name in _MANIFEST_STATUS_LISTS:
            for rec in man.get(name) or []:
                status = rec.get("status") if isinstance(rec, dict) else None
                if not isinstance(status, int) or isinstance(status, bool) or status < 300:
                    continue                    # 2xx 는 트리에서 읽고, 0 / -1 은 응답이 없었던 경우다
                key = _key_of(rec.get("path"))
                if key is None or key in response_map:
                    continue
                response_map[key] = (status, {}, _err_of(status))
                from_manifest += 1

    pages, page_mismatch = _page_report(response_map)
    stats = {"files": n_files, "keyed": n_keyed, "dupes": dupes, "pages": pages, "page_mismatch": page_mismatch,
             "non_json": n_non_json, "skipped": n_skipped, "from_manifest": from_manifest,
             "statuses": dict(Counter(v[0] for v in response_map.values()))}
    return response_map, service_root, stats


def load_mockup_records(mirror_dir):
    """convert_dmtf_mockup 용 평탄 맵 {'get::<키>': [status, body, err], 'noauth::': ...} 와 (총 index.json 수, 건너뛴 수)."""
    rmap, root, stats = build_response_map(Path(mirror_dir))
    full = {}
    for key, (status, body, err) in rmap.items():
        if key == "":
            full["noauth::"] = [status, body, err]
            full["get::"] = [status, body, err]
        else:
            full["get::" + key] = [status, body, err]
    return full, stats["files"], stats["skipped"] + stats["non_json"]


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


def run(mirror_dir: Path, manager_layout=None, firmware_scope=None):
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
        firmware_scope=firmware_scope,
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
    ap.add_argument("--firmware-scope", default=None,
                    help="adapter vendor_notes.firmware_inventory_scope (예: complex_only — CSUS 3200 / Superdome Flex)")
    ap.add_argument("--out", default=None, help="envelope JSON 저장 경로")
    args = ap.parse_args()

    mirror_dir = Path(args.mirror_dir)
    if not mirror_dir.exists():
        print(f"[FAIL] mirror_dir 없음: {mirror_dir}", file=sys.stderr)
        return 2

    envelope, stats, uris = run(mirror_dir, manager_layout=args.layout, firmware_scope=args.firmware_scope)

    out_json = json.dumps(envelope, indent=2, ensure_ascii=False, sort_keys=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(out_json)

    print("=" * 60)
    print(f"  REPLAY: {mirror_dir}")
    print("=" * 60)
    print(f"  mirror files   : {stats['files']}  keyed: {stats['keyed']}  dupes: {len(stats['dupes'])}")
    non_2xx = sum(n for code, n in stats["statuses"].items() if not 200 <= code < 300)
    print(f"  pagination     : {len(stats['pages'])} collections  mismatches: {len(stats['page_mismatch'])}  "
          f"non-2xx keys: {non_2xx} (from manifest {stats['from_manifest']})  non_json: {stats['non_json']}")
    for rec in stats["page_mismatch"][:10]:
        print(f"      [WARN] {rec['collection']}: pages={rec['pages']} members={rec['members']} "
              f"declared={rec['declared']} cut={rec['cut']}")
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
