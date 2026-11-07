"""미러 재생 HTTPS 서버 (Tier 1). 실제 ansible-playbook / redfish_gather.py 가 https://127.0.0.1/redfish/v1/... 로 접근한다.

사용: python3 mirror_https_server.py <mirror_dir> --cert C --key K [--port 443] [--bind 127.0.0.1]
                                      [--log access.jsonl] [--ready-file F] [--pid-file P]
- 443 은 특권 포트라 root(또는 sysctl net.ipv4.ip_unprivileged_port_start=443)가 필요하다. 모듈은 포트 없는 URL 을 만들므로
  (redfish_gather._get_impl) 다른 포트로는 재생할 수 없다.
- Authorization 헤더 값은 절대 기록하지 않는다 (anon/basic/token 분류만).
- 종료: --pid-file 에 적힌 PID 로 SIGTERM (run_tier1.py 가 그렇게 한다 - 같은 포트 pkill 금지, rule 80).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import signal
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mirror_policy import Mirror, rfm  # noqa: E402

LOG_LOCK = threading.Lock()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mirror_dir")
    ap.add_argument("--cert", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--port", type=int, default=443)
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--log", default=None)
    ap.add_argument("--ready-file", default=None)
    ap.add_argument("--pid-file", default=None)
    a = ap.parse_args()
    t0 = time.time()
    mirror = Mirror(a.mirror_dir)
    logf = open(a.log, "a", encoding="utf-8") if a.log else None
    tokens = set()

    def log(rec):
        if logf:
            with LOG_LOCK:
                logf.write(json.dumps(rec, ensure_ascii=False) + "\n")
                logf.flush()

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "MirrorReplay/1.1"
        sys_version = ""

        def log_message(self, *args):  # 기본 stderr 로그 억제 (Authorization 노출 방지)
            pass

        def _auth(self):
            tok = self.headers.get("X-Auth-Token")
            if tok and tok in tokens:
                return "token"
            h = self.headers.get("Authorization") or ""
            if h.lower().startswith("basic "):
                try:
                    dec = base64.b64decode(h[6:].strip()).decode("utf-8", "replace")
                except Exception:
                    return "anon"
                user = dec.split(":", 1)[0]
                return "basic" if user else "anon"
            return "anon"

        def _send(self, status, headers, body):
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _handle(self, method):
            parts = urlsplit(self.path)
            pq = parts.path + ("?" + parts.query if parts.query else "")
            auth = self._auth()
            authed = auth != "anon"
            if parts.path.rstrip("/") == "/redfish":
                body = json.dumps(mirror.version_index).encode("utf-8")
                log({"t": time.time(), "m": method, "p": pq, "k": "/redfish", "s": 200, "a": auth, "n": "version-index"})
                return self._send(200, {"Content-Type": "application/json", "OData-Version": "4.0"}, body)
            key = rfm._key_of(pq)
            if method == "POST" and key == "SessionService/Sessions":
                tok = secrets.token_hex(16)
                tokens.add(tok)
                log({"t": time.time(), "m": method, "p": pq, "k": key, "s": 201, "a": auth, "n": "session-create"})
                hdrs = {"Content-Type": "application/json", "X-Auth-Token": tok,
                        "Location": "/redfish/v1/SessionService/Sessions/1"}
                return self._send(201, hdrs, json.dumps({"@odata.id": "/redfish/v1/SessionService/Sessions/1", "Id": "1"}).encode())
            if method not in ("GET", "HEAD"):
                log({"t": time.time(), "m": method, "p": pq, "k": key, "s": 405, "a": auth, "n": "method-not-replayed"})
                return self._send(405, {"Content-Type": "application/json", "Allow": "GET"}, b"{}")
            st, hs, body, note = mirror.lookup(key, authed)
            log({"t": time.time(), "m": method, "p": pq, "k": key, "s": st, "a": auth, "n": note})
            if st == 0:
                # 무응답 근사: 아무것도 보내지 않고 연결을 끊는다
                try:
                    self.connection.shutdown(1)
                except OSError:
                    pass
                self.close_connection = True
                return
            self._send(st, hs, body or b"")

        def do_GET(self):
            self._handle("GET")

        def do_HEAD(self):
            self._handle("HEAD")

        def do_POST(self):
            self._handle("POST")

        def do_PATCH(self):
            self._handle("PATCH")

        def do_PUT(self):
            self._handle("PUT")

        def do_DELETE(self):
            self._handle("DELETE")

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(a.cert, a.key)
    srv = ThreadingHTTPServer((a.bind, a.port), H)
    srv.daemon_threads = True
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    if a.pid_file:
        with open(a.pid_file, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    info = {"mirror": a.mirror_dir, "keys": len(mirror.rmap), "raw": len(mirror.raw), "hang": sorted(mirror.hang),
            "realm": mirror.realm, "noauth_root": mirror.noauth_root is not None,
            "statuses": mirror.stats.get("statuses"), "load_s": round(time.time() - t0, 1), "pid": os.getpid()}
    print("READY " + json.dumps(info, ensure_ascii=False), flush=True)
    if a.ready_file:
        with open(a.ready_file, "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False)

    def _stop(signum, frame):
        threading.Thread(target=srv.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    try:
        srv.serve_forever()
    finally:
        srv.server_close()
        if logf:
            logf.close()
        if a.pid_file:
            try:
                os.unlink(a.pid_file)
            except OSError:
                pass


if __name__ == "__main__":
    main()
