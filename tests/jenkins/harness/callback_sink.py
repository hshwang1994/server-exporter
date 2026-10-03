#!/usr/bin/env python3
"""callback_sink.py — main 전용 Harness 의 Callback POST 수신기 (2026-10-04, Astra 3차 §5-1).

왜 있나: `python3 -m http.server` 는 GET/HEAD 만 처리해 Callback POST 를 받지 못한다. 이 수신기는 Jenkinsfile_portal 의 finalizer 가
보내는 `POST /api/jenkins/gather/<target_type>` 를 실제로 받아 body 를 검증하고, **시험이 지정한 응답**(2xx · 5xx · 지연 · 연결 끊기)을
돌려주며, 수신 기록을 시험별 파일로 남긴다. 운영 코드가 아니다 — production manifest 의 forbidden(`tests/**`) 아래에 있다.

사용 (Harness Job 또는 로컬):
  python3 tests/jenkins/harness/callback_sink.py --port 18080 --record /tmp/sink/normal.jsonl --status 200
  python3 tests/jenkins/harness/callback_sink.py --port 18080 --record /tmp/sink/retry.jsonl --status 503,503,200   # 응답 순서
  python3 tests/jenkins/harness/callback_sink.py --port 18080 --record /tmp/sink/slow.jsonl --status 200 --delay 5
  python3 tests/jenkins/harness/callback_sink.py --port 18080 --record /tmp/sink/drop.jsonl --mode close             # 연결 끊기(응답 없음)
  … --pidfile /tmp/sink/pid  로 pid 를 남기면 Harness 가 종료 시 kill 한다.

검증 (각 POST 마다 기록):
  - path 가 /api/jenkins/gather/<target_type> 인가, target_type ∈ {os, esxi, redfish}
  - body 가 JSON object 이고 loc / deploymentEnvironmentId / eventUuid / gatherInfoJson(list) 를 가지는가
  - gatherInfoJson 의 각 원소가 13 키 envelope 인가, ip 집합 (--expect-ips 가 있으면 그 집합과 같은가)
  - 기록 JSON 한 줄: ts, method, path, status_sent, ok, problems[], body_sha256, hosts, loc, deploymentEnvironmentId, eventUuid, bytes
GET /healthz 는 200 "ok" — **도달성 확인용일 뿐** Callback 성공의 증거가 아니다 (기록하지 않는다).
"""
import argparse
import hashlib
import json
import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict, List, Optional, Set, Tuple

try:
    from http.server import ThreadingHTTPServer
except ImportError:  # Python 3.6 (RHEL 8 platform-python) — the sink may run on the controller, whose python is not ours to choose
    import socketserver

    class ThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):  # type: ignore[no-redef]
        daemon_threads = True

KEYS13 = {"schema_version", "target_type", "collection_method", "ip", "hostname", "vendor", "status",
          "sections", "diagnosis", "meta", "correlation", "errors", "data"}
TARGETS = {"os", "esxi", "redfish"}


class SinkState:
    def __init__(self, statuses: List[int], delay: float, mode: str, record: str, expect_ips: Optional[Set[str]]):
        self.statuses = statuses
        self.delay = delay
        self.mode = mode
        self.record = record
        self.expect_ips = expect_ips
        self.count = 0
        self.lock = threading.Lock()

    def next_status(self) -> int:
        with self.lock:
            idx = min(self.count, len(self.statuses) - 1)
            self.count += 1
            return self.statuses[idx]

    def write(self, rec: dict) -> None:
        line = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
        with self.lock:
            os.makedirs(os.path.dirname(os.path.abspath(self.record)), exist_ok=True)
            with open(self.record, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        sys.stderr.write("[sink] " + line[:300] + "\n")
        sys.stderr.flush()


def validate(path: str, raw: bytes, expect_ips: Optional[Set[str]]) -> Tuple[bool, List[str], Dict]:
    problems: List[str] = []
    info: dict = {"hosts": [], "loc": None, "deploymentEnvironmentId": None, "eventUuid": None}
    parts = path.split("?", 1)[0].strip("/").split("/")
    if len(parts) != 4 or parts[:3] != ["api", "jenkins", "gather"] or parts[3] not in TARGETS:
        problems.append(f"path {path!r} is not /api/jenkins/gather/<os|esxi|redfish>")
    target_type = parts[3] if len(parts) == 4 else None
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        problems.append(f"body is not JSON: {e.__class__.__name__}")
        return False, problems, info
    if not isinstance(body, dict):
        problems.append("body is not a JSON object")
        return False, problems, info
    for key in ("loc", "deploymentEnvironmentId", "eventUuid", "gatherInfoJson"):
        if key not in body:
            problems.append(f"missing {key}")
    info["loc"] = body.get("loc")
    info["deploymentEnvironmentId"] = body.get("deploymentEnvironmentId")
    info["eventUuid"] = body.get("eventUuid")
    envs = body.get("gatherInfoJson")
    if not isinstance(envs, list):
        problems.append("gatherInfoJson is not a list")
        return False, problems, info
    hosts = []
    for i, env in enumerate(envs):
        if not isinstance(env, dict):
            problems.append(f"gatherInfoJson[{i}] is not an object")
            continue
        if set(env.keys()) != KEYS13:
            problems.append(f"gatherInfoJson[{i}] keys != 13 (missing={sorted(KEYS13 - set(env))}, extra={sorted(set(env) - KEYS13)})")
        if target_type and env.get("target_type") != target_type:
            problems.append(f"gatherInfoJson[{i}] target_type {env.get('target_type')!r} != path {target_type!r}")
        hosts.append(str(env.get("ip")))
    info["hosts"] = hosts
    if len(set(hosts)) != len(hosts):
        problems.append("duplicate ip in gatherInfoJson")
    if expect_ips is not None and set(hosts) != expect_ips:
        problems.append(f"ip set {sorted(set(hosts))} != expected {sorted(expect_ips)}")
    return not problems, problems, info


def make_handler(state: SinkState):
    class Handler(BaseHTTPRequestHandler):
        server_version = "se-harness-sink/1"

        def log_message(self, fmt, *args):   # 기본 access log 는 끈다 — 기록은 record 파일로
            return

        def do_GET(self):
            if self.path.split("?", 1)[0] == "/healthz":
                payload = b"ok"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            self.send_response(405)
            self.end_headers()

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length > 0 else b""
            ok, problems, info = validate(self.path, raw, state.expect_ips)
            status = state.next_status()
            rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "method": "POST", "path": self.path, "bytes": len(raw),
                   "body_sha256": hashlib.sha256(raw).hexdigest(), "ok": ok, "problems": problems,
                   "status_sent": None if state.mode == "close" else status, "mode": state.mode, **info}
            if state.delay > 0:
                time.sleep(state.delay)
            if state.mode == "close":
                state.write(rec)
                try:
                    self.connection.close()
                finally:
                    return
            payload = json.dumps({"received": ok, "problems": problems, "hosts": len(info["hosts"]), "status": status},
                                 ensure_ascii=False).encode("utf-8")
            state.write(rec)   # 응답보다 먼저 기록한다 — 클라이언트가 응답 직후 기록 파일을 읽어도 비어 있지 않게
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return Handler


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=18080)
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--record", required=True, help="수신 기록 JSONL (시험별로 분리)")
    ap.add_argument("--status", default="200", help="응답 코드 순서, 쉼표 구분 (마지막 값이 계속 반복) — 예 503,503,200")
    ap.add_argument("--delay", type=float, default=0.0, help="응답 전 지연(초)")
    ap.add_argument("--mode", choices=["respond", "close"], default="respond", help="close = 응답 없이 연결 끊기")
    ap.add_argument("--expect-ips", default="", help="기대 ip 집합(쉼표) — 다르면 problems 에 기록")
    ap.add_argument("--pidfile", default="")
    ap.add_argument("--max-seconds", type=int, default=3600, help="자동 종료(초) — Harness 가 죽어도 프로세스가 남지 않게")
    a = ap.parse_args(argv)
    statuses = [int(s) for s in a.status.split(",") if s.strip()]
    expect = {s.strip() for s in a.expect_ips.split(",") if s.strip()} or None
    state = SinkState(statuses or [200], a.delay, a.mode, a.record, expect)
    httpd = ThreadingHTTPServer((a.bind, a.port), make_handler(state))
    if a.pidfile:
        os.makedirs(os.path.dirname(os.path.abspath(a.pidfile)), exist_ok=True)
        with open(a.pidfile, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))

    def stop(*_):
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    # daemon: a non-daemon Timer kept the process alive after SIGTERM until max_seconds — the listening socket stayed open but
    # unserviced, so the next sink could not bind and health checks hung (Harness #26 2026-10-04).
    timer = threading.Timer(a.max_seconds, stop)
    timer.daemon = True
    timer.start()
    sys.stderr.write(f"[sink] listening on {a.bind}:{a.port} statuses={statuses} delay={a.delay} mode={a.mode} record={a.record}\n")
    sys.stderr.flush()
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()          # release the port right away
        if a.pidfile:
            try:
                os.unlink(a.pidfile)
            except OSError:
                pass
        sys.stderr.write("[sink] stopped\n")
        sys.stderr.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
