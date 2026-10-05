"""F04 (2026-10-05): Redfish 인증 요청의 리다이렉트 경계 · 캐시 총량 상한.

표준 urllib 리다이렉트 처리기는 다른 host · 다른 port · https→http 로 이동할 때도 Authorization 을 그대로 옮기고, POST 가
301~303 을 받으면 본문 없는 GET 으로 바꿔 보낸다. 모듈의 모든 HTTP 호출은 `_urlopen` 하나를 지나며 같은 origin 안에서만
GET/HEAD 리다이렉트를 따라가고, 쓰기는 따라가지 않는다.

실제 소켓으로 확인한다: 127.0.0.1 위의 HTTP 서버 두 개(다른 port = 다른 origin)에 요청을 보내고 각 서버가 받은 Authorization 을
기록한다. 실제 비밀번호나 외부 목적지는 쓰지 않는다 (가짜 헤더값). 같은 시험이 CI Gate 에서 Runner 의 Python 으로도 돈다.
"""
from __future__ import annotations

import http.server
import json
import sys
import threading
import urllib.error as urlerr
import urllib.request as urlreq
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))

from tests.unit.test_redfish_phase3_contracts import rg  # noqa: E402  - ansible 대역을 포함한 모듈 적재 재사용

FAKE_AUTH = "Basic ZmFrZTpmYWtl"          # "fake:fake" — 실제 자격이 아니다


class _Recorder(http.server.BaseHTTPRequestHandler):
    routes: dict = {}
    seen: list = []

    def log_message(self, *_a):
        pass

    def _handle(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        type(self).seen.append((self.command, self.path, self.headers.get("Authorization")))
        status, location = type(self).routes.get(self.path, (200, None))
        self.send_response(status)
        if location:
            self.send_header("Location", location)
        body = json.dumps({"path": self.path}).encode()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = do_PATCH = do_DELETE = _handle


def _server(routes):
    handler = type("H", (_Recorder,), {"routes": dict(routes), "seen": []})
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, handler


@pytest.fixture
def two_origins():
    b, hb = _server({})
    port_b = b.server_address[1]
    a, ha = _server({
        "/same": (302, "/target"),
        "/cross": (302, f"http://127.0.0.1:{port_b}/steal"),
        "/write": (302, "/target"),
        "/write307": (307, "/target"),
    })
    yield f"http://127.0.0.1:{a.server_address[1]}", ha, hb
    a.shutdown()
    b.shutdown()


def _opener():
    return urlreq.build_opener(urlreq.HTTPHandler(), rg._SameOriginRedirect())


def _req(url, method="GET"):
    data = b"{}" if method in ("POST", "PATCH") else None
    return urlreq.Request(url, data=data, method=method, headers={"Authorization": FAKE_AUTH, "Accept": "application/json"})


def test_same_origin_redirect_still_works_with_auth(two_origins):
    base, ha, _ = two_origins
    with _opener().open(_req(base + "/same"), timeout=5) as resp:
        assert resp.status == 200 and json.loads(resp.read())["path"] == "/target"
    assert ("GET", "/target", FAKE_AUTH) in ha.seen, "같은 BMC 안의 리다이렉트는 종전처럼 인증된 채로 따라간다"


def test_cross_origin_redirect_is_blocked_and_auth_never_leaves(two_origins):
    base, _, hb = two_origins
    with pytest.raises(urlerr.HTTPError) as exc:
        _opener().open(_req(base + "/cross"), timeout=5)
    assert exc.value.code == 302 and "redirect blocked: different origin http://127.0.0.1" in str(exc.value.reason)
    assert hb.seen == [], "다른 origin 은 요청 자체를 받지 않는다"


def test_stdlib_default_would_have_leaked_the_header(two_origins):
    """대조군 — 표준 처리기는 다른 origin 으로 Authorization 을 옮긴다 (이번 수정의 이유)."""
    base, _, hb = two_origins
    with urlreq.build_opener(urlreq.HTTPHandler()).open(_req(base + "/cross"), timeout=5):
        pass
    assert hb.seen == [("GET", "/steal", FAKE_AUTH)]


@pytest.mark.parametrize("method,path", [("POST", "/write"), ("PATCH", "/write"), ("POST", "/write307"), ("DELETE", "/write")])
def test_writes_never_follow_redirects(two_origins, method, path):
    base, ha, _ = two_origins
    with pytest.raises(urlerr.HTTPError) as exc:
        _opener().open(_req(base + path, method), timeout=5)
    assert exc.value.code in (302, 307) and f"redirect not followed for {method}" in str(exc.value.reason)
    assert [s for s in ha.seen if s[1] == "/target"] == [], "재전송도 GET 변환도 없다"


@pytest.mark.parametrize("old,new,blocked", [
    ("https://192.0.2.1/redfish/v1/", "https://192.0.2.1/redfish/v1/Systems", False),
    ("https://192.0.2.1/redfish/v1/", "https://192.0.2.1:443/redfish/v1/x", False),
    ("https://192.0.2.1/redfish/v1/", "http://192.0.2.1/redfish/v1/", True),          # 하향
    ("https://192.0.2.1/redfish/v1/", "https://192.0.2.1:8443/redfish/v1/", True),    # 다른 port
    ("https://192.0.2.1/redfish/v1/", "https://bmc.example.com/redfish/v1/", True),   # 다른 host (FQDN 포함)
    ("https://192.0.2.1/redfish/v1/", "https://192.0.2.1:bad/x", True),               # 해석 불가
])
def test_origin_rule(old, new, blocked):
    handler = rg._SameOriginRedirect()
    req = urlreq.Request(old, headers={"Authorization": FAKE_AUTH})
    if blocked:
        with pytest.raises(urlerr.HTTPError):
            handler.redirect_request(req, None, 302, "Found", {}, new)
    else:
        nxt = handler.redirect_request(req, None, 302, "Found", {}, new)
        assert nxt.full_url == new and nxt.get_header("Authorization") == FAKE_AUTH


def test_production_path_uses_the_guarded_opener(monkeypatch):
    built = []

    class _Op:
        def open(self, req, timeout=None):
            return ("opened", req.full_url, timeout)

    def fake_build_opener(*handlers):
        built.append(handlers)
        return _Op()

    monkeypatch.setattr(rg, "_OPENERS", {})
    monkeypatch.setattr(rg.urlreq, "build_opener", fake_build_opener)
    out = rg._urlopen(urlreq.Request("https://192.0.2.1/redfish/v1/"), False, 7)
    assert out == ("opened", "https://192.0.2.1/redfish/v1/", 7)
    assert any(isinstance(h, rg._SameOriginRedirect) for h in built[0])
    rg._urlopen(urlreq.Request("https://192.0.2.1/redfish/v1/"), False, 7)
    assert len(built) == 1, "opener 는 verify_ssl 별로 1번만 만든다"


def test_a_test_double_for_urlopen_is_still_honoured(monkeypatch):
    seen = []
    monkeypatch.setattr(rg.urlreq, "urlopen", lambda req, context=None, timeout=None: seen.append(timeout) or "double")
    assert rg._urlopen(urlreq.Request("https://192.0.2.1/redfish/v1/"), False, 9) == "double" and seen == [9]


def test_every_http_call_goes_through_the_single_entry():
    text = (REPO / "redfish-gather" / "library" / "redfish_gather.py").read_text(encoding="utf-8")
    assert text.count("urlreq.urlopen(req,") == 1, "직접 urlopen 은 _urlopen 의 시험 대역 분기 하나뿐"
    assert text.count("_urlopen(req, verify_ssl, _effective_timeout(timeout))") == 7
    etag = text[text.index("def _get_response_etag("):text.index("def _patch_account(")]
    assert "_read_capped(resp)" in etag and "resp.read()" not in etag, "ETag 조회도 상한 안에서만 읽는다"


def test_cache_stops_growing_at_the_byte_cap(monkeypatch):
    sizes = {"A": 600, "B": 600, "C": 100}

    def impl(bmc, path, user, pw, timeout, verify):
        rg._LAST_BODY["bytes"] = sizes[path]
        return 200, {"p": path}, None

    monkeypatch.setattr(rg, "_get_impl", impl)
    monkeypatch.setattr(rg, "MAX_CACHE_BYTES", 1000)
    rg._reset_response_cache(enabled=True)
    for p in ("A", "B", "C"):
        rg._get("192.0.2.1", p, "u", "p", 5, False)
    stats = rg.cache_stats()
    assert stats["entries"] == 2 and stats["bytes"] == 700, "B 는 상한을 넘겨 캐시하지 않고(처리는 그대로), 작은 C 는 들어간다"
    st, data, err = rg._get("192.0.2.1", "B", "u", "p", 5, False)
    assert (st, data, err) == (200, {"p": "B"}, None), "캐시에 없던 응답도 그대로 돌려준다"
    rg._invalidate_response_cache()
    assert rg.cache_stats()["bytes"] == 0
