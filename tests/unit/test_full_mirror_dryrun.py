"""redfish_full_mirror 크롤러 회귀 — 합성 데이터를 라이브처럼 띄워 순수 재귀 자동발견을
오프라인(127.0.0.1 loopback)으로 검증. 실장비/에뮬레이터/외부 네트워크 불필요.

검증 항목:
  1. CSUS 합성 멀티노드 트리를 '링크만 따라' 100% 캡처(하드코딩 경로 0 = 순수 자동발견).
  2. 페이지네이션(@odata.nextLink) 추적 — 2페이지 이후 멤버 누락 없음(정보 누락 방지).
  3. 출력이 본문 @odata.id 를 보존 → convert_dmtf_mockup.py 흡수 가능.
  4. 죽은 링크(404)에도 크롤이 안 죽고 살아있는 것만 캡처(에러 내성).
"""
import glob
import json
import os
import sys
import threading
from contextlib import contextmanager
from http.server import HTTPServer

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
    assert any(f["status"] == 404 for f in man["failed"])
