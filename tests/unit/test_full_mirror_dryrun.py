"""redfish_full_mirror 크롤러 회귀 — 합성 데이터를 라이브처럼 띄워 순수 재귀 자동발견을
오프라인(127.0.0.1 loopback)으로 검증. 실장비/에뮬레이터/외부 네트워크 불필요.

검증 항목:
  1. CSUS 합성 멀티노드 트리를 '링크만 따라' 100% 캡처(하드코딩 경로 0 = 순수 자동발견).
  2. 페이지네이션(@odata.nextLink) 추적 — 2페이지 이후 멤버 누락 없음(정보 누락 방지).
  3. 출력이 본문 @odata.id 를 보존 → convert_dmtf_mockup.py 흡수 가능.
  4. 죽은 링크(404)에도 크롤이 안 죽고 살아있는 것만 캡처(에러 내성).
  5. (v2) 404/405/400류/401·403 은 오류가 아니라 정보 버킷. 미완료(unresolved)는 장비/망이 불안정할 때뿐이고
     같은 -D 로 --resume 하면 빈 곳만 받아 COMPLETE 로 수렴.
  6. (v2) 세션 로그인(토큰만 사용, 종료 DELETE) / 토큰 만료 재로그인 1회 / 잘못된 비밀번호는 자격 요청 2회 이하에서 중단 /
     Basic 전용 장비(세션 POST 401)를 자격 거절로 오판하지 않음 / 비밀번호와 토큰은 어떤 산출물에도 없음.
  7. (v2) 링크 범위(Location[].Uri · Actions target · Link 헤더 · $metadata 로컬 스키마), 비-JSON/바이너리 raw 저장,
     SSE 제외, // 접기, Windows 예약어/대소문자 충돌/긴 경로, lone surrogate, Python 3.6 구문 가드.
"""
import base64
import glob
import json
import os
import re
import socketserver
import sys
import threading
import time
from contextlib import contextmanager
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROBE = os.path.join(REPO, "tests", "redfish-probe")
CSUS_FIXT = os.path.join(REPO, "tests", "fixtures", "redfish", "hpe_csus_3200")
if PROBE not in sys.path:
    sys.path.insert(0, PROBE)

import _serve_fixtures_as_redfish as srv  # noqa: E402
import redfish_full_mirror as mirror  # noqa: E402


@contextmanager
def _serve(resource_map):
    """resource_map(@odata.id→body)을 라이브 Redfish 처럼 127.0.0.1 임의 포트로 서빙."""
    srv.Handler.MAP = resource_map
    httpd = HTTPServer(("127.0.0.1", 0), srv.Handler)  # 바인드+리슨은 생성자에서 완료
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield port
    finally:
        httpd.shutdown()


def _crawl(port, out):
    old = sys.argv
    sys.argv = ["redfish_full_mirror.py", "--scheme", "http", "-r", f"127.0.0.1:{port}",
                "-u", "x", "-p", "y", "-D", out, "--timeout", "5"]
    try:
        return mirror.main()
    finally:
        sys.argv = old


def _manifest(out):
    with open(os.path.join(out, "_manifest.json"), encoding="utf-8") as f:
        return json.load(f)


def _index_paths(out):
    return [p.replace(os.sep, "/")
            for p in glob.glob(os.path.join(out, "**", "index.json"), recursive=True)]


def test_csus_multinode_fully_autodiscovered(tmp_path):
    served = srv.load(CSUS_FIXT)
    assert len(served) >= 36, "CSUS 합성 fixture 로드 실패"
    out = str(tmp_path / "m")
    with _serve(served) as port:
        rc = _crawl(port, out)
    assert rc == 0
    man = _manifest(out)
    # 서빙된 모든 리소스를 '링크만 따라' 전부 200 캡처 = 하드코딩 경로 없는 순수 자동발견 증명
    assert man["fetched_ok"] == len(served), (man["fetched_ok"], len(served))
    assert man["reachable"] is True and man["auth_ok"] is True
    assert man["root_product"] == "Compute Scale-up Server 3200"
    paths = _index_paths(out)
    for token in ["Partition0", "Partition1", "Partition2", "RMC", "PDHC0",
                  "PDHC1", "Bay1.iLO5", "Base", "Expansion1", "Expansion2", "FlexGrid"]:
        assert any("/" + token + "/" in p for p in paths), f"{token} 미캡처"


def test_pagination_nextlink_followed(tmp_path):
    """컬렉션이 2페이지로 쪼개진 서비스 — nextLink 안 따라가면 2페이지 멤버(item2) 누락."""
    rmap = {
        "/redfish/v1": {"@odata.id": "/redfish/v1",
                        "Coll": {"@odata.id": "/redfish/v1/Coll"}},
        "/redfish/v1/Coll": {"@odata.id": "/redfish/v1/Coll",
                             "Members": [{"@odata.id": "/redfish/v1/Coll/1"}],
                             "Members@odata.nextLink": "/redfish/v1/Coll?$skip=1"},
        "/redfish/v1/Coll?$skip=1": {"@odata.id": "/redfish/v1/Coll?$skip=1",
                                     "Members": [{"@odata.id": "/redfish/v1/Coll/2"}]},
        "/redfish/v1/Coll/1": {"@odata.id": "/redfish/v1/Coll/1", "Name": "one"},
        "/redfish/v1/Coll/2": {"@odata.id": "/redfish/v1/Coll/2", "Name": "two"},
    }
    out = str(tmp_path / "m")
    with _serve(rmap) as port:
        rc = _crawl(port, out)
    assert rc == 0
    man = _manifest(out)
    assert man["fetched_ok"] == 5, man["fetched_ok"]  # root+Coll+page2+item1+item2
    paths = _index_paths(out)
    assert any("/Coll/2/" in p for p in paths), "2페이지 멤버(item2) 누락 — nextLink 미추적"


def test_action_info_followed(tmp_path):
    """@Redfish.ActionInfo(bare 문자열 경로)도 따라가 캡처한다 — Action 파라미터 리소스 누락 방지."""
    rmap = {
        "/redfish/v1": {"@odata.id": "/redfish/v1",
                        "Systems": {"@odata.id": "/redfish/v1/Systems"}},
        "/redfish/v1/Systems": {"@odata.id": "/redfish/v1/Systems",
                                "Members": [{"@odata.id": "/redfish/v1/Systems/1"}]},
        "/redfish/v1/Systems/1": {"@odata.id": "/redfish/v1/Systems/1",
                                  "Actions": {"#ComputerSystem.Reset": {
                                      "@Redfish.ActionInfo": "/redfish/v1/Systems/1/ResetActionInfo"}}},
        "/redfish/v1/Systems/1/ResetActionInfo": {"@odata.id": "/redfish/v1/Systems/1/ResetActionInfo"},
    }
    out = str(tmp_path / "m")
    with _serve(rmap) as port:
        rc = _crawl(port, out)
    assert rc == 0
    paths = _index_paths(out)
    assert any("/ResetActionInfo/" in p for p in paths), "@Redfish.ActionInfo 미캡처"


def test_gzip_response_decoded(tmp_path):
    """Content-Encoding: gzip 응답도 해제해 링크를 추출한다 (HPE iLO/CSUS 계열 — 서브트리 누락 방지)."""
    import gzip as _gz
    from http.server import BaseHTTPRequestHandler

    bodies = {
        "/redfish/v1": {"@odata.id": "/redfish/v1", "Systems": {"@odata.id": "/redfish/v1/Systems"}},
        "/redfish/v1/Systems": {"@odata.id": "/redfish/v1/Systems",
                                "Members": [{"@odata.id": "/redfish/v1/Systems/1"}]},
        "/redfish/v1/Systems/1": {"@odata.id": "/redfish/v1/Systems/1"},
    }

    def _k(p):
        p = p.split("#", 1)[0].rstrip("/")
        return p or "/redfish/v1"

    class GzipHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            b = bodies.get(_k(self.path))
            if b is None:
                self.send_response(404)
                self.end_headers()
                return
            payload = _gz.compress(json.dumps(b).encode("utf-8"))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Encoding", "gzip")  # urllib 자동 해제 안 함 → 크롤러가 풀어야
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *a):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), GzipHandler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        out = str(tmp_path / "m")
        rc = _crawl(port, out)
    finally:
        httpd.shutdown()
    assert rc == 0
    man = _manifest(out)
    # gzip 이 풀려야 링크가 추출돼 Systems/1 까지 도달 = 3개. 안 풀리면 root만 = 1개.
    assert man["fetched_ok"] == 3, man["fetched_ok"]
    assert any("/Systems/1/" in p for p in _index_paths(out)), "gzip 응답에서 링크 추출 실패"


def test_output_preserves_odata_id(tmp_path):
    out = str(tmp_path / "m")
    with _serve(srv.load(CSUS_FIXT)) as port:
        _crawl(port, out)
    sr = json.load(open(os.path.join(out, "redfish", "v1", "index.json"), encoding="utf-8"))
    assert sr.get("@odata.id"), "본문 @odata.id 미보존 → convert_dmtf_mockup 키잉 불가"


def test_e2e_crawler_tree_reconstructs_csus_multinode(tmp_path):
    """캡처→코드완성 경로 검증: 크롤러 트리 → convert._load_mockup → run_gather(rmc_primary)
    로 CSUS 멀티노드(파티션3/매니저4/섀시3)가 실제로 재구성되는지. manager_layout 배선의 핵심."""
    from pathlib import Path
    integ = os.path.join(REPO, "tests", "integration")
    if integ not in sys.path:
        sys.path.insert(0, integ)
    import convert_dmtf_mockup as conv  # noqa: E402
    import emulator_harness as H  # noqa: E402

    # 1) 합성 CSUS 를 크롤해 트리 산출
    out = str(tmp_path / "tree")
    with _serve(srv.load(CSUS_FIXT)) as port:
        assert _crawl(port, out) == 0
    # 2) 트리 → 응답맵 (convert 의 rglob 경로 = 크롤러 출력 형식과 일치)
    full, _nf, _sk = conv._load_mockup(Path(out))
    assert "noauth::" in full, "ServiceRoot noauth:: 미생성"
    # 3) manager_layout 없이 → 단일노드(기존 동작 불변)
    gi, ni, ri, _ = conv._instrumented_replayer(full)
    assert H.run_gather(gi, ni, realm_impl=ri)["multi_node"] is None
    # 4) manager_layout='rmc_primary' → 멀티노드 재구성
    gi, ni, ri, _ = conv._instrumented_replayer(full)
    mn = H.run_gather(gi, ni, realm_impl=ri, manager_layout="rmc_primary")["multi_node"]
    assert isinstance(mn, dict) and mn.get("enabled") is True, mn
    s = mn["summary"]
    assert (s["partition_count"], s["manager_count"], s["chassis_count"]) == (3, 4, 3), s


def test_resilient_to_dead_links(tmp_path):
    """죽은 링크(404)에도 크롤은 안 죽고 살아있는 리소스만 캡처 + 404 는 기록만."""
    rmap = {
        "/redfish/v1": {"@odata.id": "/redfish/v1", "X": {"@odata.id": "/redfish/v1/X"}},
        "/redfish/v1/X": {"@odata.id": "/redfish/v1/X",
                          "Members": [{"@odata.id": "/redfish/v1/X/alive"},
                                      {"@odata.id": "/redfish/v1/X/dead"}]},
        "/redfish/v1/X/alive": {"@odata.id": "/redfish/v1/X/alive"},
        # X/dead 는 일부러 없음 → 404
    }
    out = str(tmp_path / "m")
    with _serve(rmap) as port:
        rc = _crawl(port, out)
    assert rc == 0
    man = _manifest(out)
    assert man["fetched_ok"] == 3  # root + X + alive
    # v2: 장비가 링크는 냈지만 없는 경로(404)는 오류가 아니라 absent 로 분류한다.
    assert [a["status"] for a in man["absent"]] == [404]
    assert man["absent"][0]["path"] == "/redfish/v1/X/dead"
    assert man["absent"][0]["referrer"] == "/redfish/v1/X"
    assert man["failed"] == [] and man["unresolved"] == []
    assert man["result"] == "COMPLETE"


# ================================================================================================
# v2 하네스 - 세션 로그인/토큰 검증/장애 주입이 가능한 가짜 Redfish 서비스
# ================================================================================================

PUBLIC = ("/redfish", "/redfish/v1", "/redfish/v1/odata", "/redfish/v1/$metadata")
SESSIONS = "/redfish/v1/SessionService/Sessions"


class _TS(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True


def make_handler(resources, **opts):
    """resources(키 -> 본문)를 서빙하는 핸들러 클래스와 상태(state)를 만든다.

    opts: user/password/sessions/basic/login_status/session_limit/expire_after/status/flaky/
          retry_after/raw/headers/trip/slow/accept_json_406/session_slash
    state: log=[(method, path, 인증종류)], deleted=[세션번호], tokens, authed_gets, down
    """
    cfg = {"user": "x", "password": "y", "sessions": True, "basic": True, "login_status": None,
           "session_limit": False, "expire_after": None, "status": {}, "flaky": {}, "retry_after": {},
           "raw": {}, "headers": {}, "trip": {}, "slow": {}, "accept_json_406": (), "session_slash": False}
    cfg.update(opts)
    state = {"tokens": {}, "next": 1, "authed_gets": 0, "log": [], "deleted": [], "down": False,
             "flaky": dict((k, list(v)) for k, v in cfg["flaky"].items()),
             "slow": dict((k, list(v)) for k, v in cfg["slow"].items())}

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *a):
            pass

        def _kind(self):
            tok = self.headers.get("X-Auth-Token")
            if tok is not None:
                return "token" if tok in state["tokens"] else "badtoken"
            az = self.headers.get("Authorization")
            if az and az.startswith("Basic "):
                good = base64.b64encode(("%s:%s" % (cfg["user"], cfg["password"])).encode()).decode()
                return "basic" if az[6:] == good else "badbasic"
            return "none"

        def _send(self, code, obj, headers=None, raw=None, ctype="application/json"):
            payload = raw if raw is not None else json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):  # noqa: N802
            key = srv._key(self.path)
            kind = self._kind()
            state["log"].append(("GET", key, kind))
            if key not in PUBLIC:
                if kind in ("none", "badtoken", "badbasic") or (kind == "basic" and not cfg["basic"]):
                    return self._send(401, {"error": {"message": "unauthorized"}})
                state["authed_gets"] += 1
                if cfg["expire_after"] == state["authed_gets"] and kind == "token":
                    state["tokens"].clear()
                    return self._send(401, {"error": {"message": "session expired"}})
                if key in cfg["trip"]:
                    state["down"] = True
                if state["down"]:
                    return self._send(503, {"error": {"message": "outage"}})
            delays = state["slow"].get(key)
            if delays:
                time.sleep(delays.pop(0))
            queue = state["flaky"].get(key)
            if queue:
                code = queue.pop(0)
                hdr = {"Retry-After": cfg["retry_after"][key]} if key in cfg["retry_after"] else {}
                return self._send(code, {"error": {"message": "flaky"}}, hdr)
            if key in cfg["status"]:
                val = cfg["status"][key]
                code, hdr = val if isinstance(val, tuple) else (val, {})
                hdr = dict(hdr)
                if code == 405:
                    hdr["Allow"] = "POST"
                return self._send(code, {"error": {"message": "forced %d" % code}}, hdr)
            if key in cfg["accept_json_406"] and self.headers.get("Accept") == "application/json":
                return self._send(406, {"error": {"message": "not acceptable"}})
            extra = cfg["headers"].get(key, {})
            if key in cfg["raw"]:
                ctype, data = cfg["raw"][key]
                return self._send(200, None, extra, raw=data, ctype=ctype)
            body = resources.get(key)
            if body is None:
                return self._send(404, {"error": {"code": "Base.1.0.ResourceNotFound"}})
            return self._send(200, body, extra)

        def do_POST(self):  # noqa: N802
            key = srv._key(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            state["log"].append(("POST", key, "none"))
            if not cfg["sessions"] or key != SESSIONS:
                return self._send(404, {"error": {"message": "no such resource"}})
            if cfg["session_slash"] and not self.path.split("?")[0].endswith("/"):
                return self._send(404, {"error": {"message": "trailing slash required"}})
            if cfg["session_limit"]:
                info = {"MessageId": "Base.1.0.SessionLimitExceeded"}
                return self._send(503, {"error": {"@Message.ExtendedInfo": [info]}})
            if cfg["login_status"]:
                return self._send(cfg["login_status"], {"error": {"message": "login refused"}})
            try:
                creds = json.loads(body)
            except ValueError:
                return self._send(400, {"error": {"message": "bad json"}})
            if creds.get("UserName") != cfg["user"] or creds.get("Password") != cfg["password"]:
                return self._send(401, {"error": {"message": "invalid credentials"}})
            num = state["next"]
            state["next"] += 1
            token = "tok-%d" % num
            state["tokens"][token] = num
            loc = "%s/%d" % (SESSIONS, num)
            return self._send(201, {"@odata.id": loc, "UserName": cfg["user"]},
                              {"X-Auth-Token": token, "Location": loc})

        def do_DELETE(self):  # noqa: N802
            key = srv._key(self.path)
            kind = self._kind()
            state["log"].append(("DELETE", key, kind))
            m = re.match(r"^" + re.escape(SESSIONS) + r"/(\d+)$", key)
            if m and kind == "token":
                state["tokens"].pop(self.headers.get("X-Auth-Token"), None)
                state["deleted"].append(int(m.group(1)))
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            return self._send(404, {"error": {"message": "no such session"}})

    return H, state


@contextmanager
def _serve_cls(handler_cls):
    httpd = _TS(("127.0.0.1", 0), handler_cls)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield port
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture
def fast(monkeypatch):
    """대기를 기록만 하고 건너뛴다. 비밀번호는 환경변수로만 준다 (argv 노출 없음)."""
    sleeps = []
    monkeypatch.setattr(mirror, "_sleep", lambda s: sleeps.append(s))
    monkeypatch.setenv("MIRROR_TEST_PW", "y")
    return sleeps


def _run(port, out, *extra, **kw):
    argv = ["--scheme", "http", "-r", "127.0.0.1:%d" % port, "-u", kw.get("user", "x"), "-D", out,
            "--timeout", str(kw.get("timeout", 5)), "--quiet", "--password-env", "MIRROR_TEST_PW"]
    return mirror.main(argv + list(extra))


def _root(**extra):
    body = {"@odata.id": "/redfish/v1", "Name": "Root", "Product": "MockBMC", "RedfishVersion": "1.9.0"}
    body.update(extra)
    return body


def _tree(*paths):
    """root 가 각 path 를 L0, L1, ... 링크로 가리키고 각 path 는 단순 리소스인 트리."""
    res = {"/redfish/v1": _root(**dict(("L%d" % i, {"@odata.id": p}) for i, p in enumerate(paths)))}
    for p in paths:
        res[p] = {"@odata.id": p, "Name": p.rsplit("/", 1)[-1]}
    return res


def _calls(state, method, kinds=None):
    return [e for e in state["log"] if e[0] == method and (kinds is None or e[2] in kinds)]


# ================================================================================================
# v2 시험 A - 인증 / 세션 / 잠금 방지
# ================================================================================================

def test_session_flow_token_only_and_logout(tmp_path, fast):
    """세션 로그인 POST 1회 + 보호 리소스는 토큰으로만 + 종료 DELETE 1회. 토큰은 어떤 파일에도 남지 않는다."""
    cls, st = make_handler(_tree("/redfish/v1/A", "/redfish/v1/B"))
    out = str(tmp_path / "m")
    with _serve_cls(cls) as port:
        assert _run(port, out) == 0
    man = _manifest(out)
    assert man["auth_mode"] == "session" and man["result"] == "COMPLETE"
    assert len(_calls(st, "POST")) == 1 and len(_calls(st, "DELETE")) == 1
    assert man["session"]["logout_status"] == 204 and st["deleted"] == [1]
    protected = [e for e in _calls(st, "GET") if e[1] not in PUBLIC]
    assert protected and all(e[2] in ("token", "none") for e in protected)   # none = 무인증 realm 탐침
    assert not any(e[2] in ("basic", "badbasic") for e in st["log"])
    for root, _d, files in os.walk(out):
        for fn in files:
            text = open(os.path.join(root, fn), "rb").read().decode("utf-8", "replace").lower()
            assert "x-auth-token" not in text and "tok-" not in text and "set-cookie" not in text, fn


def test_token_expiry_relogin_once(tmp_path, fast):
    """도중에 토큰이 만료되면 canary GET 으로 확인한 뒤 재로그인 1회 -> 그 리소스까지 빠짐없이 받는다."""
    paths = ["/redfish/v1/R%d" % i for i in range(6)]
    cls, st = make_handler(_tree(*paths), expire_after=3)
    out = str(tmp_path / "m")
    with _serve_cls(cls) as port:
        assert _run(port, out) == 0
    man = _manifest(out)
    assert man["result"] == "COMPLETE" and man["fetched_ok"] == 7        # root + 6
    assert man["session"]["relogins"] == 1
    assert len(_calls(st, "POST")) == 2 and st["deleted"] == [2]          # 마지막 세션만 종료
    assert man["outside_account"] == []


def test_wrong_password_aborts_with_at_most_two_credential_requests(tmp_path, fast, monkeypatch):
    """틀린 비밀번호: 자격증명을 담은 요청은 세션 POST 1 + Basic 확인 1 = 2회 이하에서 중단 (잠금 방지)."""
    monkeypatch.setenv("MIRROR_TEST_PW", "WRONG")
    cls, st = make_handler(_tree("/redfish/v1/A", "/redfish/v1/B", "/redfish/v1/C"))
    out = str(tmp_path / "m")
    with _serve_cls(cls) as port:
        rc = _run(port, out)
    man = _manifest(out)
    assert rc == 3 and man["result"] == "ABORT" and man["abort_reason"] == "credentials_rejected"
    cred = [e for e in st["log"] if e[0] == "POST" or e[2] in ("basic", "badbasic", "badtoken")]
    assert len(cred) <= 2, cred
    assert man["fetched_ok"] == 0


@pytest.mark.parametrize("opts", [{"sessions": False}, {"login_status": 401}, {"session_limit": True}])
def test_auto_falls_back_to_basic_without_rejecting(tmp_path, fast, opts):
    """세션 미지원 / Basic 전용 장비(세션 POST 가 401) / 세션 한도 초과: 단정하지 않고 Basic 으로 교차 확인한다."""
    cls, st = make_handler(_tree("/redfish/v1/A", "/redfish/v1/B"), **opts)
    out = str(tmp_path / "m")
    with _serve_cls(cls) as port:
        rc = _run(port, out)
    man = _manifest(out)
    assert rc == 0 and man["result"] == "COMPLETE" and man["auth_mode"] == "basic", man["abort_reason"]
    assert man["abort_reason"] is None and man["fetched_ok"] == 3
    if opts.get("session_limit"):
        assert len(_calls(st, "POST")) == 1 + mirror.LOGIN_LIMIT_RETRIES


def test_explicit_auth_modes(tmp_path, fast):
    """--auth session 은 세션 미지원이면 중단, --auth basic 은 세션 POST 를 아예 보내지 않는다."""
    cls, st = make_handler(_tree("/redfish/v1/A"), sessions=False)
    out = str(tmp_path / "s")
    with _serve_cls(cls) as port:
        rc = _run(port, out, "--auth", "session")
    assert rc == 3 and _manifest(out)["abort_reason"] == "session_unsupported"
    cls, st = make_handler(_tree("/redfish/v1/A"))
    out = str(tmp_path / "b")
    with _serve_cls(cls) as port:
        rc = _run(port, out, "--auth", "basic")
    man = _manifest(out)
    assert rc == 0 and man["auth_mode"] == "basic" and _calls(st, "POST") == []


def test_basic_401_streak_guard_aborts_early(tmp_path, fast):
    """Basic 모드에서 인증 성공이 한 번도 없는 채 401 이 연속되면 즉시 중단한다 (수천 번 틀린 요청 금지)."""
    res = _tree(*["/redfish/v1/P%d" % i for i in range(20)])
    cls, st = make_handler(res, sessions=False, basic=False)    # Basic 을 거부하는 장비
    out = str(tmp_path / "m")
    with _serve_cls(cls) as port:
        rc = _run(port, out, "--auth", "basic")
    man = _manifest(out)
    assert rc == 3 and man["abort_reason"] == "credentials_rejected"
    assert len(_calls(st, "GET", ("basic",))) <= 2


def test_password_never_written_anywhere(tmp_path, fast, monkeypatch, capsys):
    """비밀번호는 stdout/stderr/manifest/headers/어떤 산출 파일에도 없다. -p 를 쓰면 경고만 낸다."""
    secret = "S3cr3t-Pw-Value"
    monkeypatch.setenv("MIRROR_TEST_PW", secret)
    cls, st = make_handler(_tree("/redfish/v1/A"), password=secret)
    out = str(tmp_path / "m")
    with _serve_cls(cls) as port:
        assert _run(port, out) == 0
    seen = capsys.readouterr()
    assert secret not in seen.out and secret not in seen.err
    for root, _d, files in os.walk(out):
        for fn in files:
            assert secret.encode() not in open(os.path.join(root, fn), "rb").read(), fn
    cls, st = make_handler(_tree("/redfish/v1/A"), password=secret)
    out2 = str(tmp_path / "m2")
    with _serve_cls(cls) as port:
        argv = ["--scheme", "http", "-r", "127.0.0.1:%d" % port, "-u", "x", "-p", secret, "-D", out2, "--quiet"]
        assert mirror.main(argv) == 0
    seen = capsys.readouterr()
    assert "[WARN]" in seen.err and secret not in seen.out


# ================================================================================================
# v2 시험 B - 재시도 / 분류 / resume 수렴
# ================================================================================================

def test_transient_5xx_is_retried_then_succeeds(tmp_path, fast):
    cls, st = make_handler(_tree("/redfish/v1/Flaky", "/redfish/v1/B"),
                           flaky={"/redfish/v1/Flaky": [503, 500]})
    out = str(tmp_path / "m")
    with _serve_cls(cls) as port:
        assert _run(port, out) == 0
    man = _manifest(out)
    assert man["result"] == "COMPLETE" and man["fetched_ok"] == 3
    assert man["unresolved"] == [] and man["device_error"] == []
    assert len([e for e in st["log"] if e[1] == "/redfish/v1/Flaky" and e[2] == "token"]) == 3
    assert man["summary"]["retries"] >= 2
    assert mirror.BACKOFF_BASE in fast and mirror.BACKOFF_BASE * 2 in fast


def test_retry_after_header_is_honored(tmp_path, fast):
    cls, st = make_handler(_tree("/redfish/v1/Slow"), flaky={"/redfish/v1/Slow": [429]},
                           retry_after={"/redfish/v1/Slow": "7"})
    out = str(tmp_path / "m")
    with _serve_cls(cls) as port:
        assert _run(port, out) == 0
    assert 7.0 in fast and _manifest(out)["fetched_ok"] == 2


def test_retry_after_parsing():
    f = mirror._retry_after_seconds
    assert f("7", 60) == 7.0 and f(" 2.5 ", 60) == 2.5
    assert f("9999", 60) == 60.0                                   # 상한
    assert f("-5", 60) == 0.0 and f("nan", 60) == 0.0              # 과거/비정상은 0
    assert f("", 60) is None and f(None, 60) is None and f("soon", 60) is None
    assert f(formatdate(time.time() - 3600, usegmt=True), 60) == 0.0   # 과거 HTTP-date
    future = f(formatdate(time.time() + 30, usegmt=True), 60)
    assert 25 < future <= 30
    assert f(formatdate(time.time() + 3600, usegmt=True), 60) == 60.0


def test_persistent_500_on_healthy_device_is_device_error_not_failure(tmp_path, fast):
    res = _tree("/redfish/v1/Broken", "/redfish/v1/Fine")
    cls, st = make_handler(res, status={"/redfish/v1/Broken": 500})
    out = str(tmp_path / "m")
    with _serve_cls(cls) as port:
        assert _run(port, out) == 0
    man = _manifest(out)
    assert man["result"] == "COMPLETE" and man["complete_with_exclusions"] is True
    assert [e["path"] for e in man["device_error"]] == ["/redfish/v1/Broken"]
    assert man["unresolved"] == [] and man["failed"] == []
    out2 = str(tmp_path / "m2")
    cls, st = make_handler(res, status={"/redfish/v1/Broken": 500})
    with _serve_cls(cls) as port:
        assert _run(port, out2, "--strict") == 1                   # --strict 는 device_error 도 미완료
    assert _manifest(out2)["result"] == "INCOMPLETE"


def test_outage_is_unresolved_and_resume_converges(tmp_path, fast):
    """장비가 도중에 불안정해지면 unresolved(INCOMPLETE). 같은 -D 로 --resume 하면 빈 곳만 받아 COMPLETE."""
    res = _tree("/redfish/v1/A", "/redfish/v1/B", "/redfish/v1/C")
    out = str(tmp_path / "m")
    cls, st = make_handler(res, trip={"/redfish/v1/B": True})
    with _serve_cls(cls) as port:
        rc1 = _run(port, out)
    man1 = _manifest(out)
    assert rc1 == 1 and man1["result"] == "INCOMPLETE"
    assert sorted(e["path"] for e in man1["unresolved"]) == ["/redfish/v1/B", "/redfish/v1/C"]
    cls, st = make_handler(res)
    with _serve_cls(cls) as port:
        rc2 = _run(port, out, "--resume")
    man2 = _manifest(out)
    assert rc2 == 0 and man2["result"] == "COMPLETE" and man2["unresolved"] == []
    assert man2["fetched_ok"] == 4 and man2["summary"]["resumed_from_disk"] >= 2
    got = [e[1] for e in _calls(st, "GET", ("token",))]
    assert "/redfish/v1/A" not in got and {"/redfish/v1/B", "/redfish/v1/C"} <= set(got)


def test_403_is_not_retried_and_not_an_error(tmp_path, fast):
    cls, st = make_handler(_tree("/redfish/v1/Secret", "/redfish/v1/Open"),
                           status={"/redfish/v1/Secret": 403})
    out = str(tmp_path / "m")
    with _serve_cls(cls) as port:
        assert _run(port, out) == 0
    man = _manifest(out)
    assert man["result"] == "COMPLETE" and [e["path"] for e in man["outside_account"]] == ["/redfish/v1/Secret"]
    assert len([e for e in st["log"] if e[1] == "/redfish/v1/Secret" and e[2] == "token"]) == 1
    assert man["auth_failures"] == man["outside_account"]            # v1 호환 별칭


def test_timeout_is_retried_with_longer_timeout(tmp_path, fast):
    cls, st = make_handler(_tree("/redfish/v1/Slow"), slow={"/redfish/v1/Slow": [1.6]})
    out = str(tmp_path / "m")
    with _serve_cls(cls) as port:
        assert _run(port, out, timeout=1) == 0
    man = _manifest(out)
    assert man["result"] == "COMPLETE" and man["fetched_ok"] == 2 and man["summary"]["retries"] >= 1


def test_not_acceptable_is_retried_with_any_accept(tmp_path, fast):
    cls, st = make_handler(_tree("/redfish/v1/Weird"), accept_json_406=("/redfish/v1/Weird",))
    out = str(tmp_path / "m")
    with _serve_cls(cls) as port:
        assert _run(port, out) == 0
    man = _manifest(out)
    assert man["fetched_ok"] == 2 and [e["path"] for e in man["accept_fallback"]] == ["/redfish/v1/Weird"]
    assert man["rejected"] == []


# ================================================================================================
# v2 시험 C - 링크 발견 범위 / 비-JSON 저장 / 파일 매핑
# ================================================================================================

def _read(path):
    with open(path, "rb") as f:
        return f.read()


def test_binary_attachment_streamed_and_stub_is_valid_json(tmp_path, fast):
    """AdditionalDataURI 같은 바이너리는 raw 파일로 스트리밍 저장. index.json 스텁은 @odata.id 없는 유효 JSON."""
    blob = bytes(bytearray(range(256))) * 40
    res = {"/redfish/v1": _root(AdditionalDataURI="/redfish/v1/Bin")}
    cls, st = make_handler(res, raw={"/redfish/v1/Bin": ("application/octet-stream", blob)})
    out = str(tmp_path / "m")
    with _serve_cls(cls) as port:
        assert _run(port, out) == 0
    man = _manifest(out)
    assert man["summary"]["ok_raw"] == 1 and man["result"] == "COMPLETE"
    d = os.path.join(out, "redfish", "v1", "Bin")
    assert _read(os.path.join(d, "raw.bin")) == blob
    stub = json.loads(_read(os.path.join(d, "index.json")).decode("utf-8"))
    assert stub["_non_json"] is True and stub["_bytes"] == len(blob) and "@odata.id" not in stub
    assert not [f for f in os.listdir(out) if f.endswith(".part")]
    # 소비자(convert_dmtf_mockup)가 스텁을 무해하게 건너뛰는지
    full, _n, skipped = _load_mockup_for_test(out)
    assert "get::/redfish/v1/Bin" not in full and skipped >= 1


def _load_mockup_for_test(out):
    integ = os.path.join(REPO, "tests", "integration")
    if integ not in sys.path:
        sys.path.insert(0, integ)
    import convert_dmtf_mockup as conv
    return conv._load_mockup(Path(out))


def test_metadata_xml_saved_raw_and_local_schema_followed(tmp_path, fast):
    xml = (b'<edmx:Edmx><edmx:Reference Uri="/redfish/v1/schema/Foo_v1.xml"/>'
           b'<edmx:Reference Uri="http://redfish.dmtf.org/schemas/v1/Bar.xml"/></edmx:Edmx>')
    cls, st = make_handler({"/redfish/v1": _root()}, raw={
        "/redfish/v1/$metadata": ("application/xml", xml),
        "/redfish/v1/schema/Foo_v1.xml": ("application/xml", b"<Schema/>")})
    out = str(tmp_path / "m")
    with _serve_cls(cls) as port:
        assert _run(port, out) == 0
    man = _manifest(out)
    assert _read(os.path.join(out, "redfish", "v1", "$metadata", "raw.xml")) == xml
    assert _read(os.path.join(out, "redfish", "v1", "schema", "Foo_v1.xml", "raw.xml")) == b"<Schema/>"
    assert [w["bucket"] for w in man["wellknown"] if w["path"].endswith("$metadata")] == ["ok"]
    assert any(s["reason"] == "cross-host" for s in man["skipped"])
    assert man["fetched_ok"] == 2                       # root + Foo (wellknown 은 fetched_ok 에 불포함)


def test_oversize_binary_is_excluded_not_failing(tmp_path, fast):
    res = {"/redfish/v1": _root(DownloadURI="/redfish/v1/Big")}
    cls, st = make_handler(res, raw={"/redfish/v1/Big": ("application/octet-stream", b"x" * 5000)})
    out = str(tmp_path / "m")
    with _serve_cls(cls) as port:
        assert _run(port, out, "--max-bytes-per-resource", "2000") == 0
    man = _manifest(out)
    assert man["result"] == "COMPLETE" and man["complete_with_exclusions"] is True
    assert [(e["reason"], e["bytes"]) for e in man["excluded"]] == [("oversize", 5000)]
    assert not os.path.exists(os.path.join(out, "redfish", "v1", "Big"))


def test_action_target_405_is_not_an_error(tmp_path, fast):
    act = "/redfish/v1/Systems/1/Actions/ComputerSystem.Reset"
    res = _tree("/redfish/v1/Systems/1")
    res["/redfish/v1/Systems/1"]["Actions"] = {"#ComputerSystem.Reset": {"target": act}}
    cls, st = make_handler(res, status={act: 405})
    out = str(tmp_path / "m")
    with _serve_cls(cls) as port:
        assert _run(port, out) == 0
    man = _manifest(out)
    assert man["result"] == "COMPLETE"
    assert [(e["path"], e["allow"]) for e in man["not_gettable"]] == [(act, "POST")]
    assert [a["bucket"] for a in man["action_targets"]] == ["not_gettable"]
    cls, st = make_handler(res, status={act: 405})
    out2 = str(tmp_path / "m2")
    with _serve_cls(cls) as port:
        assert _run(port, out2, "--no-action-targets") == 0
    assert not [e for e in st["log"] if e[1] == act]
    assert [e["reason"] for e in _manifest(out2)["excluded"]] == ["no-action-targets"]


def test_location_uri_followed_foreign_skipped_and_rehosted(tmp_path, fast):
    reg = {"@odata.id": "/redfish/v1/Registries/Base",
           "Location": [{"Language": "en", "Uri": "/redfish/v1/RegFiles/Base.json",
                         "PublicationUri": "http://redfish.dmtf.org/registries/Base.json"}]}
    res = {"/redfish/v1": _root(Registries={"@odata.id": "/redfish/v1/Registries/Base"},
                                Other={"@odata.id": "https://bmc01.example.net/redfish/v1/Foreign"},
                                Ext={"@odata.id": "https://elsewhere.example.net/other/x"}),
           "/redfish/v1/Registries/Base": reg,
           "/redfish/v1/RegFiles/Base.json": {"@odata.id": "/redfish/v1/RegFiles/Base.json", "Messages": {}},
           "/redfish/v1/Foreign": {"@odata.id": "/redfish/v1/Foreign"}}
    cls, st = make_handler(res)
    out = str(tmp_path / "m")
    with _serve_cls(cls) as port:
        assert _run(port, out) == 0
    man = _manifest(out)
    assert man["fetched_ok"] == 4 and man["absent"] == []
    assert [r["path"] for r in man["rehosted"]] == ["/redfish/v1/Foreign"]
    assert sorted(s["link"] for s in man["skipped"]) == [
        "http://redfish.dmtf.org/registries/Base.json", "https://elsewhere.example.net/other/x"]


def test_sse_stream_endpoints_are_excluded_without_any_get(tmp_path, fast):
    """ServerSentEventUri / .../SSE 는 GET 하면 스트림이 멈춰 오분류된다 - 요청 자체를 하지 않는다."""
    res = {"/redfish/v1": _root(EventService={"@odata.id": "/redfish/v1/EventService"}),
           "/redfish/v1/EventService": {"@odata.id": "/redfish/v1/EventService",
                                        "ServerSentEventUri": "/redfish/v1/SSE",
                                        "Hidden": {"@odata.id": "/redfish/v1/EventService/SSE"}},
           "/redfish/v1/SSE": {"@odata.id": "/redfish/v1/SSE"},
           "/redfish/v1/EventService/SSE": {"@odata.id": "/redfish/v1/EventService/SSE"}}
    cls, st = make_handler(res)
    out = str(tmp_path / "m")
    with _serve_cls(cls) as port:
        assert _run(port, out) == 0
    assert not [e for e in st["log"] if e[1].upper().endswith("/SSE")]
    man = _manifest(out)
    assert sorted(e["reason"] for e in man["excluded"]) == ["policy:ServerSentEventUri", "policy:sse"]
    assert man["result"] == "COMPLETE"


def test_double_slash_link_collapses_to_one_request(tmp_path, fast):
    """Lenovo 의 //중복 슬래시 링크가 같은 디렉터리의 정상 200 저장본을 404 로 덮어쓰던 손실 재현 방지."""
    res = {"/redfish/v1": _root(A={"@odata.id": "/redfish/v1//Dup"}, B={"@odata.id": "/redfish/v1/Dup"}),
           "/redfish/v1/Dup": {"@odata.id": "/redfish/v1/Dup", "Name": "kept"}}
    cls, st = make_handler(res)
    out = str(tmp_path / "m")
    with _serve_cls(cls) as port:
        assert _run(port, out) == 0
    man = _manifest(out)
    assert man["absent"] == [] and man["fetched_ok"] == 2
    assert len([e for e in st["log"] if e[1].endswith("Dup") and e[2] == "token"]) == 1
    assert not [e for e in st["log"] if "//" in e[1]]
    saved = json.loads(_read(os.path.join(out, "redfish", "v1", "Dup", "index.json")).decode("utf-8"))
    assert saved["Name"] == "kept"


def test_collection_count_mismatch_is_recorded_not_failed(tmp_path, fast):
    res = _tree("/redfish/v1/Coll")
    res["/redfish/v1/Coll"].update({"Members@odata.count": 3, "Members": [{"@odata.id": "/redfish/v1/Coll/1"}]})
    res["/redfish/v1/Coll/1"] = {"@odata.id": "/redfish/v1/Coll/1"}
    cls, st = make_handler(res)
    out = str(tmp_path / "m")
    with _serve_cls(cls) as port:
        assert _run(port, out) == 0
    man = _manifest(out)
    assert man["count_mismatch"] == [{"path": "/redfish/v1/Coll", "declared": 3, "actual": 1}]
    assert man["result"] == "COMPLETE"


def test_fs_reserved_names_case_collisions_and_long_paths(tmp_path, fast):
    """Windows 예약어(Aux/COM1), 대소문자만 다른 경로, 아주 긴 세그먼트를 안전한 별개 디렉터리로 저장하고 기록한다."""
    long_seg = "L" * 300
    paths = ["/redfish/v1/Eth/Aux", "/redfish/v1/Eth/COM1", "/redfish/v1/Sys/bios", "/redfish/v1/Sys/Bios",
             "/redfish/v1/Deep/" + long_seg]
    cls, st = make_handler(_tree(*paths))
    out = str(tmp_path / "m")
    with _serve_cls(cls) as port:
        assert _run(port, out) == 0
    man = _manifest(out)
    assert man["fetched_ok"] == 6 and man["result"] == "COMPLETE"
    fsmap = json.loads(_read(os.path.join(out, "_fsmap.json")).decode("utf-8"))["paths"]
    dirs = [fsmap[p]["dir"] for p in paths]
    assert len(set(d.lower() for d in dirs)) == len(dirs)                 # 대소문자 무시 충돌 없음
    assert dirs[0].endswith("Aux_") and dirs[1].endswith("COM1_")
    assert man["summary"]["max_rel_path_chars"] <= 200
    for p, d in zip(paths, dirs):
        body = json.loads(_read(os.path.join(out, *d.split("/"), "index.json")).decode("utf-8"))
        assert body["@odata.id"] == p


def test_link_header_target_is_followed(tmp_path, fast):
    res = _tree("/redfish/v1/A")
    res["/redfish/v1/Schemas/X.json"] = {"@odata.id": "/redfish/v1/Schemas/X.json", "title": "X"}
    hdrs = {"/redfish/v1/A": {"Link": "</redfish/v1/Schemas/X.json>; rel=describedby"}}
    cls, st = make_handler(res, headers=hdrs)
    out = str(tmp_path / "m")
    with _serve_cls(cls) as port:
        assert _run(port, out) == 0
    assert os.path.isfile(os.path.join(out, "redfish", "v1", "Schemas", "X.json", "index.json"))
    assert _manifest(out)["fetched_ok"] == 3


def test_redirect_to_other_host_is_refused(tmp_path, fast):
    """다른 호스트로의 리다이렉트는 따라가지 않는다 (토큰/Basic 이 밖으로 새지 않게). 오류가 아니라 rejected."""
    res = _tree("/redfish/v1/Redir", "/redfish/v1/Fine")
    cls, st = make_handler(res, status={"/redfish/v1/Redir": (302, {"Location": "http://evil.example.net/steal"})})
    out = str(tmp_path / "m")
    with _serve_cls(cls) as port:
        assert _run(port, out) == 0
    man = _manifest(out)
    assert [(e["path"], e["status"]) for e in man["rejected"]] == [("/redfish/v1/Redir", 302)]
    assert man["redirected"] == [] and man["result"] == "COMPLETE"


def test_lone_surrogate_body_is_saved_not_fatal(tmp_path, fast):
    """본문에 lone surrogate 가 있어 UTF-8 인코딩이 안 되던 v1 의 크롤 전체 중단을 재현하지 않는다."""
    bad = b'{"@odata.id":"/redfish/v1/Sur","Name":"bad' + bytes([92]) + b'ud800"}'
    res = {"/redfish/v1": _root(Sur={"@odata.id": "/redfish/v1/Sur"})}
    cls, st = make_handler(res, raw={"/redfish/v1/Sur": ("application/json", bad)})
    out = str(tmp_path / "m")
    with _serve_cls(cls) as port:
        assert _run(port, out) == 0
    man = _manifest(out)
    assert man["result"] == "COMPLETE" and man["unresolved"] == []
    saved = json.loads(_read(os.path.join(out, "redfish", "v1", "Sur", "index.json")).decode("utf-8"))
    assert saved["@odata.id"] == "/redfish/v1/Sur"


def test_exit_codes_empty_and_unreachable(tmp_path, fast):
    cls, st = make_handler({})                                    # 루트도 없는 장비: 2xx 0건
    out = str(tmp_path / "e")
    with _serve_cls(cls) as port:
        assert _run(port, out) == 2
    assert _manifest(out)["result"] == "EMPTY"
    probe = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)  # 포트만 얻고 닫아 연결 거부 상태로 만든다
    closed = probe.server_address[1]
    probe.server_close()
    out = str(tmp_path / "u")
    assert _run(closed, out, "--retries", "0") == 4
    man = _manifest(out)
    assert man["result"] == "ABORT" and man["abort_reason"] == "unreachable"


def test_summarize_prints_table_and_exit_code(tmp_path, fast, capsys):
    cls, st = make_handler(_tree("/redfish/v1/A"))
    ok_dir = str(tmp_path / "ok")
    with _serve_cls(cls) as port:
        assert _run(port, ok_dir) == 0
    capsys.readouterr()
    assert mirror.main(["--summarize", ok_dir]) == 0
    assert "COMPLETE" in capsys.readouterr().out
    assert mirror.main(["--summarize", ok_dir, str(tmp_path / "missing")]) == 1
    text = capsys.readouterr().out
    assert "NO_MANIFEST" in text and "COMPLETE 1" in text


def test_source_stays_python36_compatible():
    """RHEL/Rocky 8 기본 python3(3.6)에서 돌아야 한다: 3.6 문법으로 파싱되고 3.7+ 전용 기능을 안 쓴다."""
    import ast
    src = open(os.path.join(PROBE, "redfish_full_mirror.py"), encoding="utf-8").read()
    tree = ast.parse(src, feature_version=(3, 6))
    assert "from __future__ import annotations" not in src
    for banned in ("fromisoformat", "removeprefix", "removesuffix", "ssl.TLSVersion.TLSv1_2"):
        assert banned not in src, banned
    for node in ast.walk(tree):
        ann = [getattr(node, "annotation", None), getattr(node, "returns", None)]
        for a in ann:
            assert not isinstance(a, ast.Subscript), "subscripted annotation breaks py3.6"


def test_v2_tree_is_consumed_by_replay_and_convert(tmp_path):
    """v2 산출물(wellknown/스텁/신규 파일 포함)을 replay_full_mirror 와 convert 가 그대로 소비한다."""
    import replay_full_mirror as rep
    out = str(tmp_path / "m")
    with _serve(srv.load(CSUS_FIXT)) as port:
        assert _crawl(port, out) == 0
    rmap, root, stats = rep.build_response_map(Path(out))
    assert root is not None and stats["keyed"] >= 35
    full, _n, _skipped = _load_mockup_for_test(out)
    assert "noauth::" in full
    env, _stats, _uris = rep.run(Path(out), manager_layout="rmc_primary")
    assert env["multi_node"] and env["multi_node"]["summary"]["partition_count"] == 3


def test_session_uri_keeps_trailing_slash_for_bmcs_that_require_it(tmp_path, fast):
    """iLO 처럼 세션 생성 POST 에 끝 슬래시를 요구하는 장비: Links.Sessions 값을 그대로 써서 세션이 성립한다."""
    res = _tree("/redfish/v1/A")
    res["/redfish/v1"]["Links"] = {"Sessions": {"@odata.id": SESSIONS + "/"}}
    cls, st = make_handler(res, session_slash=True)
    out = str(tmp_path / "m")
    with _serve_cls(cls) as port:
        assert _run(port, out) == 0
    man = _manifest(out)
    assert man["auth_mode"] == "session" and man["session"]["source"] == "Links.Sessions"
    assert man["session"]["sessions_uri"].endswith("/Sessions/") and man["session"]["login_status"] == 201


# ================================================================================================
# v2 시험 D - 순수 함수 / 시험이 닿지 않던 분기
# ================================================================================================

def test_norm_and_quote_path():
    n = mirror._norm
    assert n("/redfish/v1//Dup/") == "/redfish/v1/Dup"                       # // 접기 + 끝 / 제거
    assert n("https://bmc.example/redfish/v1/Systems#/Foo") == "/redfish/v1/Systems"
    assert n("/redfish/v1/Coll?$skip=50") == "/redfish/v1/Coll?$skip=50"      # query 보존 (페이지네이션)
    assert n("") == "" and n("/") == "/"
    assert mirror._keep_path("https://h/redfish/v1/SessionService/Sessions/") == "/redfish/v1/SessionService/Sessions/"
    q = mirror._quote_path
    assert q("/redfish/v1/Systems/서버 1") == "/redfish/v1/Systems/%EC%84%9C%EB%B2%84%201"
    assert q("/a/Aux%00?$skip=1") == "/a/Aux%00?$skip=1"                      # 기존 %XX 와 구분자는 보존


def test_fs_segment_is_safe():
    f = mirror._fs_segment
    assert f("..") == "_" and f(".") == "_" and f("   ") == "_"
    assert f("a" + chr(92) + "b") == "a_b" and f("x:y?z") == "x_y_z"   # 금지 문자(백슬래시 포함) 치환
    assert f("COM1") == "COM1_" and f("aux.txt") == "aux.txt_" and f("index.json") == "index.json_"
    assert f("Foo. ") == "Foo" and f("Bay1.iLO5") == "Bay1.iLO5"
    assert len(f("L" * 400)) <= 200 and len(f("가" * 200).encode("utf-8")) <= 240


def test_collect_links_kinds():
    body = {"@odata.id": "/redfish/v1/X", "@odata.context": "/redfish/v1/$metadata#X", "@odata.type": "#X.X",
            "Members": [{"@odata.id": "/redfish/v1/X/1"}], "Members@odata.nextLink": "/redfish/v1/X?$skip=1",
            "Actions": {"#X.Reset": {"target": "/redfish/v1/X/Actions/X.Reset",
                                     "@Redfish.ActionInfo": "/redfish/v1/X/ResetInfo"}},
            "Location": [{"Uri": "/redfish/v1/Reg/A.json", "ArchiveUri": "/redfish/v1/Reg/A.zip"}],
            "@Redfish.Settings": {"SettingsObject": {"@odata.id": "/redfish/v1/X/Settings"}},
            "Image": "http://boot/x.iso", "$ref": "http://dmtf/x.json", "HttpPushUriTargets": ["/redfish/v1/Z"],
            "Paths": ["/redfish/v1/P1"], "Note": "/not/a/redfish/path", "Empty": ""}
    kinds = dict((v, k) for v, k, _key in mirror._collect_links(body))
    assert kinds["/redfish/v1/X"] == "odata.id" and kinds["/redfish/v1/X/1"] == "odata.id"
    assert kinds["/redfish/v1/X?$skip=1"] == "nextLink" and kinds["/redfish/v1/X/ResetInfo"] == "actioninfo"
    assert kinds["/redfish/v1/X/Actions/X.Reset"] == "target"
    assert kinds["/redfish/v1/Reg/A.json"] == "uri" and kinds["/redfish/v1/Reg/A.zip"] == "uri"
    assert kinds["/redfish/v1/X/Settings"] == "odata.id" and kinds["/redfish/v1/P1"] == "path_string"
    for skipped in ("/redfish/v1/$metadata#X", "http://boot/x.iso", "http://dmtf/x.json", "/redfish/v1/Z",
                    "/not/a/redfish/path", ""):
        assert skipped not in kinds


def test_make_ctx_policy():
    import ssl
    ctx = mirror._make_ctx(False, False)
    assert ctx.verify_mode == ssl.CERT_NONE and ctx.check_hostname is False
    if hasattr(ssl, "TLSVersion"):
        legacy = mirror._make_ctx(False, True)
        assert legacy.minimum_version == ssl.TLSVersion.MINIMUM_SUPPORTED
    assert mirror._make_ctx(True).verify_mode == ssl.CERT_REQUIRED


def test_resume_from_tree_without_fsmap(tmp_path, fast):
    """_fsmap.json 이 없는 트리(v1 산출물, 강제 종료)에서도 저장본을 복원해 재사용한다."""
    cls, st = make_handler(_tree("/redfish/v1/A", "/redfish/v1/B"))
    out = str(tmp_path / "m")
    with _serve_cls(cls) as port:
        assert _run(port, out) == 0
    os.remove(os.path.join(out, "_fsmap.json"))
    cls, st = make_handler(_tree("/redfish/v1/A", "/redfish/v1/B"))
    with _serve_cls(cls) as port:
        assert _run(port, out, "--resume") == 0
    man = _manifest(out)
    assert man["summary"]["resumed_from_disk"] == 3 and man["fetched_ok"] == 3
    got = [e[1] for e in _calls(st, "GET", ("token",))]
    assert "/redfish/v1/A" not in got and "/redfish/v1/B" not in got


def test_exclude_regex_skips_matching_paths(tmp_path, fast):
    cls, st = make_handler(_tree("/redfish/v1/Logs/1", "/redfish/v1/Keep"))
    out = str(tmp_path / "m")
    with _serve_cls(cls) as port:
        assert _run(port, out, "--exclude", "/Logs/") == 0
    man = _manifest(out)
    assert [(e["reason"], e["link"]) for e in man["excluded"]] == [("user-exclude", "/redfish/v1/Logs/1")]
    assert not [e for e in st["log"] if e[1] == "/redfish/v1/Logs/1" and e[2] == "token"]


def test_interrupt_still_logs_out_and_writes_outputs(tmp_path, fast, monkeypatch):
    """Ctrl-C / SIGTERM 은 같은 경로: 세션 DELETE + manifest 기록 + 종료코드 130 + 큐 잔량은 truncated."""
    cls, st = make_handler(_tree(*["/redfish/v1/R%d" % i for i in range(8)]))
    calls = {"n": 0}
    original = mirror.Crawler._process

    def interrupting(self, item):
        calls["n"] += 1
        if calls["n"] == 6:
            raise KeyboardInterrupt()
        return original(self, item)

    monkeypatch.setattr(mirror.Crawler, "_process", interrupting)
    out = str(tmp_path / "m")
    with _serve_cls(cls) as port:
        rc = _run(port, out)
    man = _manifest(out)
    assert rc == 130 and man["interrupted"] is True and man["result"] == "INCOMPLETE"
    assert st["deleted"] == [1] and man["truncated"] > 0
    assert os.path.isfile(os.path.join(out, "_fsmap.json"))
