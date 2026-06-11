#!/usr/bin/env python3
"""fixture 디렉터리를 라이브 Redfish 서비스처럼 HTTP 서빙 — redfish_full_mirror.py dry-run 전용.

장비 없는 인터넷망에서 크롤러의 재귀·자동발견 로직을 검증하기 위한 dev 도구다.
tests/fixtures/redfish/<dir>/*.json 을 @odata.id 로 키잉해 GET 으로 돌려준다.
(test_csus_fixture_replay.py 의 _build_response_map 과 동일 발상.)

운영망에는 가져가지 않는다 — dry-run 전용. stdlib(http.server) 만 사용.

사용: python _serve_fixtures_as_redfish.py <fixture_dir> [port]
"""
from __future__ import annotations

import glob
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


def _key(odata_id: str) -> str:
    # fragment 만 제거하고 query 는 보존(페이지네이션 nextLink 구별) — 크롤러 _norm 과 일치.
    k = odata_id.split("#", 1)[0]
    if "?" in k:
        base, q = k.split("?", 1)
        base = base.rstrip("/") if len(base) > 1 else base
        return f"{base}?{q}"
    if len(k) > 1:
        k = k.rstrip("/")
    return k or "/redfish/v1"


def load(fixture_dir: str) -> dict:
    m = {}
    for fp in glob.glob(os.path.join(fixture_dir, "**", "*.json"), recursive=True):
        try:
            with open(fp, encoding="utf-8") as f:
                body = json.load(f)
        except Exception:
            continue
        if isinstance(body, dict):
            oid = body.get("@odata.id")
            if isinstance(oid, str):
                m[_key(oid)] = body
    return m


class Handler(BaseHTTPRequestHandler):
    MAP: dict = {}

    def do_GET(self):  # noqa: N802
        body = self.MAP.get(_key(self.path))
        if body is None:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":{"code":"Base.1.0.ResourceNotFound"}}')
            return
        b = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):  # 조용히
        pass


if __name__ == "__main__":
    fixture_dir = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8443
    Handler.MAP = load(fixture_dir)
    print(f"loaded {len(Handler.MAP)} resources from {fixture_dir}; serving on 127.0.0.1:{port}", flush=True)
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
