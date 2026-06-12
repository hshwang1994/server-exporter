#!/usr/bin/env python3
"""Redfish 전수 재귀 미러 — 장비가 실제로 노출하는 모든 @odata.id를 자동 발견해 raw 저장.

목적 (제한 운영망 1회 캡처 → 인터넷망에서 코드 완성):
    운영망의 실 CSUS RMC(또는 임의 Redfish BMC)에 1회 접속해, 우리 수집 코드의
    "가정된 경로"를 전혀 쓰지 않고 ServiceRoot 부터 응답에 들어있는 모든 @odata.id 를
    재귀로 따라가 트리 전체를 raw 로 떠온다. 떠온 트리를 인터넷망으로 반출해
    tests/fixtures/redfish/<...>/ 에 넣으면 convert_dmtf_mockup.py /
    test_csus_fixture_replay.py 가 그대로 오프라인 재생 → 실 raw 기준으로 CSUS 개더링
    코드를 완성한다.

설계 원칙:
    1. 우리 코드 비의존 — redfish_gather / adapter / 가정 경로를 일절 호출하지 않는다.
       지금 우리 CSUS 수집이 failed 로 떨어지는 건 합성 fixture 로 만든 경로가 실제와
       다를 수 있기 때문이다. 그래서 장비가 실제로 준 @odata.id 링크만 신뢰한다.
    2. 깊은 스캔 — Members / Links 뿐 아니라 Oem.* / 중첩 dict·list 어디에 있든 @odata.id
       를 전부 수집한다. 벤더는 OEM 안쪽에 nav 링크를 숨겨 두는 경우가 많다.
    3. 에러 내성 — 개별 endpoint 실패(404/500/timeout)는 기록만 하고 크롤 전체는 계속.
       (우리 라이브 수집이 한 방에 abort 되는 것과 정반대 — 한 번뿐인 캡처를 한 endpoint
        때문에 통째로 날리지 않는다.)
    4. 자가 진단 — 한 번뿐이라, 끝에 도달/인증/발견·성공·실패 수·미인증 root·realm 을
       _manifest.json + stdout 요약으로 남긴다. "다 떴는지" 를 현장에서 즉시 확인.

stdlib 전용(urllib / ssl / json / base64) — 운영망 무설치 실행. 프로젝트 stdlib-only 원칙 동일.

출력 형식 (= DMTF mockup = convert_dmtf_mockup.py 입력):
    <out>/redfish/v1/.../index.json    각 리소스 raw 본문 (@odata.id 보존)
    <out>/redfish/v1/.../headers.json  HTTP status + 응답 헤더
    <out>/_manifest.json               크롤 요약·자가진단
    <out>/_serviceroot_noauth.json     무인증 ServiceRoot (detect/auth 경로 재구성용)

사용:
    python redfish_full_mirror.py -r <RMC_IP[:443]> -u <admin> -p <pw> -D <out_dir>
    # dry-run (로컬 mock, http):
    python redfish_full_mirror.py --scheme http -r 127.0.0.1:8443 -u x -p y -D <out_dir>
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from collections import deque

# 파일시스템(특히 Windows)에서 디렉터리명에 못 쓰는 문자. 본문 @odata.id 는 보존하고
# 디스크 경로명만 치환하므로, 재생 시 키잉(본문 @odata.id 기준)에는 영향 없다.
_FS_BAD = re.compile(r'[\x00-\x1f<>:"|?*\\]')


def _ctx(verify: bool) -> ssl.SSLContext:
    """self-signed BMC 인증서 허용 (verify=False 기본). redfish_gather.py 와 동일 정책."""
    c = ssl.create_default_context()
    if not verify:
        c.check_hostname = False
        c.verify_mode = ssl.CERT_NONE
    return c


def _norm(path: str) -> str:
    """nav URI 를 방문/비교용으로 정규화: 절대 URL→경로, #fragment 제거, base 끝 / 제거.

    주의: `?query` 는 보존한다. 페이지네이션 nextLink(예: `?$skip=50`, `?page=2`)는
    쿼리로만 1페이지와 구별되므로, 쿼리를 떼면 같은 경로로 정규화돼 'seen' 처리되어
    2페이지 이후가 통째로 누락된다(정보 손실). fragment(#)만 제거한다.
    """
    if not path:
        return ""
    m = re.match(r"^https?://[^/]+(/.*)$", path)
    if m:
        path = m.group(1)
    path = path.split("#", 1)[0]
    if "?" in path:
        base, q = path.split("?", 1)
        base = base.rstrip("/") if len(base) > 1 else base
        return f"{base}?{q}"
    if len(path) > 1:
        path = path.rstrip("/")
    return path


def _fetch(scheme, host, path, headers, ctx, timeout):
    """단일 GET. (status, headers, json_body, err) 반환. 예외는 err 문자열로 흡수."""
    url = f"{scheme}://{host}{path}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as r:
            raw = r.read()
            hdrs = {k: v for k, v in r.getheaders()}
            status = r.status
        # 일부 BMC(특히 HPE iLO 계열 / CSUS RMC)는 Accept-Encoding 무관하게 gzip/deflate 로
        # 응답한다. urllib 은 우리가 헤더를 명시하면 자동 해제하지 않으므로 직접 푼다 — 안 풀면
        # json.loads 가 깨져 _non_json 으로 저장되고 그 안의 @odata.id 링크가 전부 누락 →
        # 서브트리 통째 손실(요구1). 깨진 압축은 무시하고 비-JSON 으로 흘려보낸다.
        enc = next((v for k, v in hdrs.items() if k.lower() == "content-encoding"), "").lower()
        if raw and ("gzip" in enc or "deflate" in enc):
            try:
                raw = gzip.decompress(raw) if "gzip" in enc else zlib.decompress(raw)
            except Exception:
                try:
                    raw = zlib.decompress(raw, -zlib.MAX_WBITS)  # raw deflate(zlib 헤더 없음)
                except Exception:
                    pass
        try:
            data = json.loads(raw) if raw else {}
        except Exception:
            # 비-JSON 응답(예: CSDL/xml)도 흔적은 남긴다.
            data = {"_non_json": raw[:4000].decode("utf-8", "replace")}
        return status, hdrs, data, None
    except urllib.error.HTTPError as e:
        try:
            ebody = e.read()
            edata = json.loads(ebody) if ebody else {}
        except Exception:
            edata = {}
        return e.code, dict(e.headers or {}), edata, f"HTTP {e.code}: {e.reason}"
    except Exception as e:  # noqa: BLE001 — 한 endpoint 실패가 크롤을 멈추면 안 된다.
        return 0, {}, {}, f"{type(e).__name__}: {e}"


def _collect_ids(obj, out: set) -> None:
    """응답 JSON 어디에 있든 모든 nav URI 를 재귀 수집(중첩 dict/list, Oem 포함).

    수집 대상 세 가지 — 모두 GET 가능한 리소스 링크라 따라가야 정보 누락이 없다:
      - `@odata.id`              : 일반 리소스/멤버 참조
      - `...@odata.nextLink`     : 컬렉션 페이지네이션(다음 페이지). 안 따라가면 큰 컬렉션
                                   (DIMM/드라이브/펌웨어 다수)의 2페이지 이후가 통째로 누락.
      - `...@Redfish.ActionInfo` : Action 파라미터 기술 리소스(예: ResetActionInfo). 값이
                                   @odata.id 객체가 아니라 bare 문자열 경로라 별도 매칭 필요.
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and (
                k == "@odata.id"
                or k.endswith("@odata.nextLink")
                or k.endswith("@Redfish.ActionInfo")
            ):
                out.add(v)
            else:
                _collect_ids(v, out)
    elif isinstance(obj, list):
        for it in obj:
            _collect_ids(it, out)


def _save(out_dir, path, status, hdrs, data) -> None:
    rel = path.strip("/")
    # 제어문자(0x00-0x1f) 치환 + 세그먼트 200자 제한 — 깊은 트리에서 Windows MAX_PATH(260)/
    # NTFS 컴포넌트(255) 초과로 save 가 죽지 않게. 본문 @odata.id 는 그대로 보존.
    segs = [_FS_BAD.sub("_", s)[:200] for s in rel.split("/") if s] if rel else []
    d = os.path.join(out_dir, *segs)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "index.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
    with open(os.path.join(d, "headers.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"_status": status, **hdrs}, f, indent=2, ensure_ascii=False, sort_keys=True)


def _bracket_ipv6(host: str) -> str:
    """IPv6 리터럴(콜론 2개 이상, 대괄호 없음)을 [addr]/[addr]:port 로 감싼다.

    안 감싸면 urlopen 이 ValueError → 전 fetch 가 조용히 status 0 → 한 번뿐인 캡처를
    '도달 불가'로 오진한다. bare IPv6 입력을 자동 보정한다(포트 포함형은 대괄호 입력 권장).
    """
    if host.startswith("["):
        return host
    addr, port = host, ""
    if host.count(":") == 1 and host.rsplit(":", 1)[1].isdigit():
        addr, port = host.rsplit(":", 1)
    if addr.count(":") >= 2:  # IPv6 리터럴
        return f"[{addr}]" + (f":{port}" if port else "")
    return host


def main() -> int:
    # 운영망 박스가 cp949/비-UTF8 콘솔이어도 --help / 요약 print 가 죽지 않게 stdout 을 utf-8 로
    # 먼저 고정한다(parse_args 가 --help 를 출력하기 전에). 한 번뿐인 캡처 — 인코딩 때문에
    # 사용법/결과를 못 보는 일이 없게.
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")  # py3.7+
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="Redfish 전수 재귀 미러 (자동 발견)")
    ap.add_argument("--host", "-r", required=True, help="ip[:port] 또는 [ipv6]:port")
    ap.add_argument("--user", "-u", default="")
    ap.add_argument("--password", "-p", default="")
    ap.add_argument("--out", "-D", required=True, help="출력 디렉터리")
    ap.add_argument("--scheme", choices=["https", "http"], default="https")
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--verify", action="store_true",
                    help="TLS 인증서 검증 (기본 off — self-signed BMC)")
    ap.add_argument("--max", type=int, default=200000, help="안전 상한(리소스 수)")
    ap.add_argument("--root", default="/redfish/v1/", help="시작 경로")
    args = ap.parse_args()
    args.host = _bracket_ipv6(args.host)

    ctx = _ctx(args.verify)
    # 보수적 헤더: Accept 만. (Lenovo XCC3 1.17.0 교훈 — OData-Version/User-Agent 동봉 시
    # reject 하는 BMC 가 있다. 사이트 실측 > spec.)
    base_headers = {"Accept": "application/json"}
    auth_headers = dict(base_headers)
    if args.user:
        tok = base64.b64encode(f"{args.user}:{args.password}".encode()).decode()
        auth_headers["Authorization"] = f"Basic {tok}"

    os.makedirs(args.out, exist_ok=True)
    root = _norm(args.root) or "/redfish/v1"

    manifest = {
        "host": args.host, "scheme": args.scheme, "root": root,
        "reachable": None, "auth_ok": None, "root_product": None,
        "root_redfish_version": None, "realm": None,
        "discovered": 0, "fetched_ok": 0, "failed": [], "auth_failures": [],
        "skipped": [], "truncated": 0, "firmware_versions": [],
    }

    # 0) 무인증 ServiceRoot — detect_vendor/auth 경로 재구성용. 실패해도 무시.
    st_na, hdrs_na, d_na, _ = _fetch(args.scheme, args.host, root + "/", base_headers, ctx, args.timeout)
    if st_na:
        manifest["reachable"] = True
        try:
            with open(os.path.join(args.out, "_serviceroot_noauth.json"), "w",
                      encoding="utf-8", newline="\n") as f:
                json.dump({"_status": st_na, "body": d_na}, f, indent=2, ensure_ascii=False)
        except OSError as _e:  # noauth 저장 실패가 BFS/manifest 까지 막으면 안 된다.
            print(f"[WARN] _serviceroot_noauth.json save 실패: {_e}", file=sys.stderr)
        # 0b) realm 캡처(Session-only BMC 진단).
        #  - ServiceRoot 자체가 인증 게이트면 그 401/403 헤더에서 바로.
        #  - 루트가 공개면 루트에서 "발견한" 첫 링크를 무인증 GET → 401 이면.
        #    하드코딩 경로 없이 — 자동발견 원칙 유지.
        if st_na in (401, 403):
            manifest["realm"] = hdrs_na.get("WWW-Authenticate") or hdrs_na.get("www-authenticate")
        if not manifest["realm"]:
            _probe_ids: set = set()
            _collect_ids(d_na, _probe_ids)
            for _pid in sorted(_probe_ids):
                _np = _norm(_pid)
                if _np and _np.startswith("/") and _np != root:
                    _stp, _hdp, _, _ = _fetch(args.scheme, args.host, _np, base_headers, ctx, args.timeout)
                    if _stp in (401, 403):
                        manifest["realm"] = _hdp.get("WWW-Authenticate") or _hdp.get("www-authenticate")
                    break

    # 1) BFS 재귀 — 장비가 준 nav 링크만 따라간다. 경로 접두사 가정 0. visited 로 순환 차단.
    seen, queued = set(), set()
    q = deque([root])
    queued.add(root)
    # 같은 장비 호스트(크로스-호스트 절대 URL 구별용). 대괄호 IPv6/포트 포함형도 hostname 만 추출.
    _self_host = urllib.parse.urlsplit(f"//{args.host}").hostname or args.host

    def _enqueue(raw_id) -> None:
        """발견한 링크를 큐에 추가. 접두사 가정 없이 절대경로면 전부 따라간다(/rest/v1 등 포함).
        다른 호스트를 가리키는 절대 URL / 경로가 아닌 값만 skip 하고 manifest 에 남겨 가시화한다."""
        if not isinstance(raw_id, str):
            return
        # cross-host 절대 URL(http(s)://otherhost/...)은 같은 장비 캡처 목적상 따라가지 않는다.
        # _norm 이 host 를 떼어 같은-호스트 요청으로 둔갑하는 것을 막고 false 404 노이즈도 차단.
        parsed = urllib.parse.urlsplit(raw_id)
        if parsed.scheme and parsed.hostname and parsed.hostname != _self_host:
            if all(s.get("link") != raw_id for s in manifest["skipped"]):
                manifest["skipped"].append({"link": raw_id, "reason": "cross-host"})
            return
        np = _norm(raw_id)
        if not np or not np.startswith("/"):
            if all(s.get("link") != raw_id for s in manifest["skipped"]):
                manifest["skipped"].append({"link": raw_id, "reason": "non-path"})
            return
        if np not in seen and np not in queued:
            queued.add(np)
            q.append(np)

    try:
        while q and len(seen) < args.max:
            path = q.popleft()
            if path in seen:
                continue
            seen.add(path)

            fetch_path = path + "/" if path == root else path  # root 변수 사용(--root 비기본도 일관)
            status, hdrs, data, err = _fetch(args.scheme, args.host, fetch_path,
                                             auth_headers, ctx, args.timeout)
            # transient(전송계층) 실패는 1회 재시도. status 0 = HTTPError 가 아닌 네트워크 예외.
            # 한 번뿐인 캡처에서 순간 hiccup 으로 서브트리 전체를 영구히 잃지 않게.
            if status == 0:
                time.sleep(1.5)
                status, hdrs, data, err = _fetch(args.scheme, args.host, fetch_path,
                                                 auth_headers, ctx, args.timeout)

            try:
                _save(args.out, path, status, hdrs, data)
            except OSError as exc:  # save 실패가 크롤 전체를 멈추면 안 된다(요구4).
                manifest["failed"].append({"path": path, "status": status, "error": f"save: {exc}"})

            if 200 <= status < 300:  # 200 외 2xx 본문도 링크 추출(서브트리 누락 방지)
                manifest["fetched_ok"] += 1
                if manifest["reachable"] is None:  # noauth가 transient 실패해도 BFS 2xx면 도달 확정
                    manifest["reachable"] = True
                if path != root:
                    manifest["auth_ok"] = True  # 보호 리소스 2xx = 인증 성공 증명
                if path == root and isinstance(data, dict):
                    manifest["root_product"] = data.get("Product")
                    manifest["root_redfish_version"] = data.get("RedfishVersion")
                if isinstance(data, dict) and data.get("Version") is not None and "Updateable" in data:
                    manifest["firmware_versions"].append(
                        {"name": data.get("Name"), "version": data.get("Version")})
                ids: set = set()
                _collect_ids(data, ids)
                for raw_id in ids:
                    _enqueue(raw_id)
            else:
                rec = {"path": path, "status": status, "error": err}
                manifest["failed"].append(rec)
                if status in (401, 403):
                    manifest["auth_failures"].append(rec)

        if q:  # 상한(--max) 도달로 큐가 남으면 명시 — 조용한 truncation 방지.
            manifest["truncated"] = len(q)
    finally:
        # 예외 / KeyboardInterrupt 에도 manifest 는 항상 남긴다 — 거기까지의 캡처 진단 보존.
        manifest["discovered"] = len(seen)
        if q and not manifest["truncated"]:  # 비정상 종료로 위 if q 가 안 돈 경우도 기록
            manifest["truncated"] = len(q)
        _mpath = os.path.join(args.out, "_manifest.json")
        try:
            with open(_mpath, "w", encoding="utf-8", newline="\n") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False, sort_keys=True)
        except Exception as _mex:  # manifest 마저 못 쓰면(디스크/경로) stderr 로라도 진단 보존.
            print(f"[WARN] manifest write 실패 ({_mex}); stderr 로 덤프:", file=sys.stderr)
            print(json.dumps(manifest, indent=2, ensure_ascii=False), file=sys.stderr)

    # 자가 진단 요약 — 현장에서 "다 떴는지" 즉시 판단.
    print("=" * 60)
    print(f"  REDFISH FULL MIRROR - {args.host}")
    print("=" * 60)
    print(f"  reachable      : {manifest['reachable']}")
    print(f"  auth_ok        : {manifest['auth_ok']}  (보호 리소스 200 여부)")
    print(f"  root product   : {manifest['root_product']}  (RedfishVersion={manifest['root_redfish_version']})")
    print(f"  realm          : {manifest['realm']}")
    print(f"  discovered     : {manifest['discovered']}")
    print(f"  fetched 2xx    : {manifest['fetched_ok']}")
    print(f"  failed         : {len(manifest['failed'])}  (401/403={len(manifest['auth_failures'])})")
    print(f"  skipped        : {len(manifest['skipped'])}  (비-경로/cross-host 링크)")
    if manifest["auth_failures"]:
        print("  [WARN] 권한 갭(401/403) - 더 높은 권한 계정 필요 가능:")
        for r in manifest["auth_failures"][:10]:
            print(f"      {r['status']}  {r['path']}")
    if manifest["fetched_ok"] > 0 and manifest["auth_ok"] is None:
        # 보호 리소스 2xx 0건인데 fetched_ok>0 = ServiceRoot 만 잡힌 모호한 상태.
        # 302→HTML captive-portal redirect 나 Basic 미지원(Session-only)일 때 rc=0 으로
        # '성공처럼' 끝날 수 있어 — 한 번뿐인 캡처에서 운영자가 오인하지 않게 명시 경고.
        print("  [WARN] auth_ok=None - 보호 리소스 2xx 0건. 302->HTML captive-portal redirect "
              "또는 Basic 미지원(Session-only) 가능. _serviceroot_noauth.json 의 _non_json 여부 확인.",
              file=sys.stderr)
    if manifest.get("truncated"):
        print(f"  [WARN] CRAWL TRUNCATED - 큐에 {manifest['truncated']}개 남음. --max 올리거나 truncation 수용.")
    if manifest["fetched_ok"] == 0:
        print("  [FAIL] 2xx 응답 0건 - 도달/인증/Redfish 활성화(RMC 라이선스) 먼저 확인.")
    print(f"  output         : {os.path.abspath(args.out)}")
    return 0 if manifest["fetched_ok"] > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
