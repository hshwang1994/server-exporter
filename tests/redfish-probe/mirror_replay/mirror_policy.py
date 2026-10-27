"""미러 트리(v1/v2) -> 재생 정책. 서버(Tier 1)와 in-process 재생(Tier 2)이 같은 정책을 쓴다. 저장소 코드는 읽기만 한다.

- 2xx: 트리의 index.json 원본 바이트 그대로(헤더는 headers.json 기록분). _empty(204)는 빈 본문.
- 비-2xx: manifest 목록(absent/not_gettable/rejected/outside_account/device_error/unresolved/failed ...)의 기록 상태코드, 본문 {}.
- status 0(timeout 등 무응답): 'hang' -> 서버는 응답 없이 연결을 닫는다(근사치). Tier 2 는 (0, {}, 'Timeout') 로 돌려준다.
- 무인증 요청: ServiceRoot(''), odata, $metadata, /redfish 만 허용. 그 밖은 401 (+ manifest realm 이 있으면 WWW-Authenticate).
  실장비의 익명 허용 범위는 미러에 없으므로 DMTF 최소 집합으로 가정한다 -> 검증 한계.
- 인증: Basic 에 사용자 이름이 비어 있지 않으면 통과(비밀번호 검증 불가 -> 한계). X-Auth-Token 도 통과.

2026-10-27: 분석 Round(tests/evidence/2026-10-26-redfish-mock2-audit/tools/)의 판을 저장소에 편입하면서 저장소 루트를
이 파일 기준으로 찾도록 바꿨다(SE_REPO_ROOT 로만 덮어쓰기). 정책 자체는 분석 Round 와 같다.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get("SE_REPO_ROOT") or HERE.parents[2])
_PROBE_DIR = str(REPO / "tests" / "redfish-probe")
if _PROBE_DIR not in sys.path:
    sys.path.insert(0, _PROBE_DIR)
import replay_full_mirror as rfm  # noqa: E402  (ansible stub + redfish_gather import 포함)

ANON_KEYS = {"", "odata", "$metadata"}
DROP_HDRS = {"_status", "transfer-encoding", "connection", "content-length", "keep-alive", "date", "content-encoding"}


def _int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


class Mirror:
    def __init__(self, mirror_dir):
        self.dir = Path(mirror_dir)
        self.rmap, self.root_body, self.stats = rfm.build_response_map(self.dir)
        # key -> 디렉터리(원본 바이트/헤더를 읽기 위해) : rfm 의 비공개 헬퍼를 같은 규칙으로 재사용
        entries, _nf, _nnj, _nsk = rfm._load_entries(self.dir, rfm._load_fsmap(self.dir))
        rfm._restore_pages(entries)
        self.key_dir = {}
        self.key_empty = set()
        for e in entries:
            self.key_dir.setdefault(e["key"], e["dir"])
            if e["body"] == {} and e["status"] == 204:
                self.key_empty.add(e["key"])
        # raw(비-JSON) 항목: v2 _fsmap type=raw
        self.raw = {}
        ok, fs = rfm._read_json(self.dir / "_fsmap.json")
        if ok and isinstance(fs, dict):
            for path, ent in (fs.get("paths") or {}).items():
                if isinstance(ent, dict) and ent.get("type") == "raw":
                    k = rfm._key_of(path)
                    if k is not None:
                        self.raw[k] = ent.get("dir")
        # manifest: realm, hang(timeout) 목록
        self.realm = None
        self.hang = set()
        self.manifest = {}
        okm, man = rfm._read_json(self.dir / "_manifest.json")
        if okm and isinstance(man, dict):
            self.manifest = man
            self.realm = man.get("realm") if isinstance(man.get("realm"), str) else None
            for name in rfm._MANIFEST_STATUS_LISTS:
                for rec in man.get(name) or []:
                    if not isinstance(rec, dict):
                        continue
                    st_i = _int(rec.get("status"))
                    if st_i == 0 or rec.get("kind") == "timeout" or rec.get("cause") == "timeout":
                        k = rfm._key_of(rec.get("path"))
                        if k is not None and k not in self.rmap:
                            self.hang.add(k)
        # 무인증 ServiceRoot 기록
        self.noauth_root = None
        okn, na = rfm._read_json(self.dir / "_serviceroot_noauth.json")
        if okn and isinstance(na, dict) and isinstance(na.get("body"), dict):
            self.noauth_root = (_int(na.get("_status"), 200), na["body"])
        # /redfish 버전 인덱스
        okv, vi = rfm._read_json(self.dir / "redfish" / "index.json")
        self.version_index = vi if (okv and isinstance(vi, dict)) else {"v1": "/redfish/v1/"}

    # ---- 조회 -------------------------------------------------------------
    def _dir_of(self, key):
        return self.key_dir.get(key)

    def headers_for(self, key):
        d = self._dir_of(key)
        if d is None:
            return {}
        fp = (self.dir / d / "headers.json") if d else (self.dir / "headers.json")
        ok, h = rfm._read_json(fp)
        if not ok or not isinstance(h, dict):
            return {}
        return {k: v for k, v in h.items() if isinstance(v, str) and k.lower() not in DROP_HDRS}

    def body_bytes(self, key):
        d = self._dir_of(key)
        if d is None:
            return None
        fp = (self.dir / d / "index.json") if d else (self.dir / "index.json")
        try:
            return fp.read_bytes()
        except OSError:
            return None

    def lookup(self, key, authed):
        """-> (status, headers:dict, body:bytes|None, note). status 0 = hang(응답 없음)."""
        jsonh = {"Content-Type": "application/json"}
        if key is None:
            return 404, dict(jsonh), b"{}", "outside-redfish-v1"
        if not authed and key not in ANON_KEYS:
            h = dict(jsonh)
            if self.realm:
                h["WWW-Authenticate"] = self.realm
            return 401, h, b"{}", "anon-denied"
        if not authed and key == "" and self.noauth_root is not None:
            st, body = self.noauth_root
            h = {"Content-Type": "application/json", "OData-Version": "4.0"}
            return st, h, json.dumps(body, ensure_ascii=False).encode("utf-8"), "noauth-root"
        if key in self.hang:
            return 0, {}, None, "hang"
        if key in self.raw:
            d = self.raw[key]
            okst, stub = rfm._read_json(self.dir / d / "index.json")
            stub = stub if isinstance(stub, dict) else {}
            ctype = stub.get("_content_type") or "application/octet-stream"
            rawf = stub.get("_raw_file") or "raw.bin"
            try:
                b = (self.dir / d / rawf).read_bytes()
            except OSError:
                return 404, dict(jsonh), b"{}", "raw-missing"
            hs = {}
            okh, hh = rfm._read_json(self.dir / d / "headers.json")
            st = 200
            if okh and isinstance(hh, dict):
                hs = {k: v for k, v in hh.items() if isinstance(v, str) and k.lower() not in DROP_HDRS}
                st = _int(hh.get("_status"), 200)
            hs["Content-Type"] = ctype
            return st, hs, b, "raw"
        if key in self.rmap:
            st, body, err = self.rmap[key]
            hs = self.headers_for(key)
            if "Content-Type" not in hs:
                hs["Content-Type"] = "application/json"
            if 200 <= st < 300:
                if key in self.key_empty or st == 204:
                    return st, hs, b"", "tree-empty"
                b = self.body_bytes(key)
                if b is None:
                    b = json.dumps(body, ensure_ascii=False).encode("utf-8")
                return st, hs, b, "tree"
            return st, hs, json.dumps(body, ensure_ascii=False).encode("utf-8"), "manifest"
        return 404, dict(jsonh), b"{}", "unknown"

    # ---- Tier 2 (in-process) 어댑터 ---------------------------------------
    def module_response(self, path, authed):
        """redfish_gather._get_impl / _get_noauth 와 같은 (status, data, err) 를 돌려준다."""
        key = rfm._key_of("/redfish/v1/" + str(path).lstrip("/")) if path is not None else None
        st, hs, body, note = self.lookup(key, authed)
        if st == 0:
            return 0, {}, "Timeout after 1800s"
        if 200 <= st < 300:
            if not body:
                return st, {}, None
            try:
                data = json.loads(body.decode("utf-8", errors="replace"))
                return st, data, None
            except ValueError:
                return st, {}, f"HTTP {st}: body not JSON"
        try:
            data = json.loads(body.decode("utf-8", errors="replace")) if body else {}
        except ValueError:
            data = {}
        return st, data, rfm._err_of(st)
