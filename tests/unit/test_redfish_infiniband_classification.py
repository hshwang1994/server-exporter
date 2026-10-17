"""Redfish `storage.infiniband[]` — 현재 모드 판정 · GUID 선택 · 고아 기능 · 안정성 (2026-10-17 InfiniBand 전면 검증).

실장비 IB 모드 BMC 캡처는 없다(공개 mockup 도 0건). 입력은 DMTF 스키마(Port.v1_19_0 · NetworkPort.v1_4_3 ·
NetworkDeviceFunction.v1_11_1)에 맞춘 **합성** 리소스이고, `rg._get` 을 route-dict 로 가려 `gather_network_adapters_chassis`
실제 경로를 돈다 (tests/unit/test_fcoe_cna_not_fc_hba.py 패턴). 기대값은 코드 출력 스냅샷이 아니라 ADR-2026-10-17 의
규칙에서 따로 정했다. 실장비 검증이 아니다.

고정하는 계약
  - 판정 근거는 현재 모드뿐: Port.LinkNetworkTechnology / NetworkPort.ActiveLinkTechnology / Port.PortProtocol / 연결 기능의
    NetDevFuncType. NetDevFuncCapabilities · Port.InfiniBand 블록 · GUID 존재 · 카드 이름은 근거가 아니다.
  - 충돌(포트 ↔ 기능, 링크 기술 ↔ PortProtocol)은 IB 로 확정하지 않고 notice 1건.
  - 항목 1개 = 포트 1개. 포트에 연결되지 않은 IB 기능은 항목이 아니다.
  - GUID: 연결 기능의 값이 하나로 일치할 때, 없으면 Port.InfiniBand 배열의 distinct non-null 이 1개일 때. 그 외 null.
  - link_status up/down/unknown (Starting/Training → unknown), rate_gbps 는 up 일 때만, rate 는 항상 null.
  - 같은 입력 → 같은 출력, 새 HTTP 요청 없음.
"""
from __future__ import annotations

import copy
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))
sys.path.insert(0, str(REPO / "filter_plugins"))

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
from identity_normalizer import normalize_ib_guid  # noqa: E402

CHASSIS = "/redfish/v1/Chassis/1"
ADP = CHASSIS + "/NetworkAdapters/HCA0"
MODEL = "HPE InfiniBand NDR200/Ethernet 200GbE 2-port QSFP112 PCIe5 x16 MCX755106AC-HEAT Adapter"
NODE = "58a2:e103:0003:96f2"
PORT0 = "58a2:e103:0003:96f2"
PORT1 = "58a2:e103:0003:96f3"
NOT_FOUND = (404, {}, "HTTP 404: Not Found")

IB_KEYS = {"adapter", "adapter_model", "model", "port", "node_guid", "port_guid", "link_status", "rate", "rate_gbps",
           "vendor", "firmware", "source"}


# ───────────────────────────────────────────────────────────────────────────
# 합성 리소스 (DMTF 스키마 모양)
# ───────────────────────────────────────────────────────────────────────────
def _port(pid, *, lt="InfiniBand", status="LinkUp", speed=200.0, pp=None, ib=None, ethernet=None, port_type=None):
    body = {"@odata.id": f"{ADP}/Ports/{pid}", "@odata.type": "#Port.v1_6_0.Port", "Id": pid, "Name": "Port",
            "LinkState": "Enabled", "Status": {"Health": "OK", "State": "Enabled"}}
    if lt is not None:
        body["LinkNetworkTechnology"] = lt
    if status is not None:
        body["LinkStatus"] = status
    if speed is not None:
        body["CurrentSpeedGbps"] = speed
    if pp is not None:
        body["PortProtocol"] = pp
    if ib is not None:
        body["InfiniBand"] = ib
    if ethernet is not None:
        body["Ethernet"] = ethernet
    if port_type is not None:
        body["PortType"] = port_type
    return body


def _ndf(nid, *, ftype="InfiniBand", caps=("Ethernet", "InfiniBand"), node=NODE, port=PORT0, assign="0", ethernet=None):
    body = {"@odata.id": f"{ADP}/NetworkDeviceFunctions/{nid}", "@odata.type": "#NetworkDeviceFunction.v1_8_0.NetworkDeviceFunction",
            "Id": nid, "Name": "NetworkDeviceFunction", "NetDevFuncCapabilities": list(caps),
            "Status": {"Health": "OK", "State": "Enabled"}}
    if ftype is not None:
        body["NetDevFuncType"] = ftype
    if node is not None or port is not None:
        body["InfiniBand"] = {"NodeGUID": node, "PermanentNodeGUID": node, "PortGUID": port, "PermanentPortGUID": port}
    if assign is not None:
        body["Links"] = {"PhysicalNetworkPortAssignment": {"@odata.id": f"{ADP}/Ports/{assign}"}}
    if ethernet is not None:
        body["Ethernet"] = ethernet
    return body


def _routes(ports, ndfs):
    routes = {
        rg._p(CHASSIS) + "/NetworkAdapters": (200, {"Members": [{"@odata.id": ADP}]}, None),
        rg._p(ADP): (200, {"Id": "HCA0", "Name": "NetworkAdapter", "Manufacturer": "MLNX", "Model": MODEL,
                           "Controllers": [{"ControllerCapabilities": {"NetworkPortCount": len(ports),
                                                                       "NetworkDeviceFunctionCount": len(ndfs)},
                                            "FirmwarePackageVersion": "28.43.1014"}],
                           "Ports": {"@odata.id": ADP + "/Ports"},
                           "NetworkDeviceFunctions": {"@odata.id": ADP + "/NetworkDeviceFunctions"}}, None),
        rg._p(ADP) + "/Ports": (200, {"Members": [{"@odata.id": p["@odata.id"]} for p in ports]}, None),
        rg._p(ADP) + "/NetworkDeviceFunctions": (200, {"Members": [{"@odata.id": n["@odata.id"]} for n in ndfs]}, None),
    }
    for p in ports:
        routes[rg._p(p["@odata.id"])] = (200, p, None)
    for n in ndfs:
        routes[rg._p(n["@odata.id"])] = (200, n, None)
    return routes


def _gather(monkeypatch, routes):
    """(out, notices, errors, 요청 경로 목록)."""
    seen = []

    def fake_get(ip, path, *a, **kw):
        seen.append(path)
        return routes.get(path, NOT_FOUND)

    monkeypatch.setattr(rg, "_get", fake_get)
    rg._reset_notices()
    out, errs = rg.gather_network_adapters_chassis("10.0.0.1", CHASSIS, "u", "p", 30, False)
    return out, [n for n in rg.notices() if n["section"] == "network_adapters"], errs, seen


# ───────────────────────────────────────────────────────────────────────────
# 판정 함수 단위
# ───────────────────────────────────────────────────────────────────────────
def _f(ftype):
    return {"func_type": ftype, "wwpn": None, "wwnn": None, "node_guid": None, "port_guid": None}


@pytest.mark.parametrize("lt, pp, ftypes, expected", [
    ("InfiniBand", None, ["InfiniBand"], "ib"),
    ("InfiniBand", None, [], "ib"),                                 # 포트 모드만 (기능 미연결)
    ("InfiniBand", "InfiniBand", ["InfiniBand", "Disabled"], "ib"),  # Disabled 는 근거 없음
    ("InfiniBand", None, ["Ethernet"], "conflict"),
    ("Ethernet", None, ["InfiniBand"], "conflict"),
    ("Ethernet", "InfiniBand", [], "conflict"),                     # 링크 기술 ↔ PortProtocol 충돌
    (None, "RoCE", ["InfiniBand"], "conflict"),
    (None, "InfiniBand", [], "ib"),                                 # PortProtocol 만
    (None, None, ["InfiniBand"], "ib"),
    (None, None, ["InfiniBand", "Ethernet"], "conflict"),
    (None, None, ["Ethernet"], "not_ib"),
    (None, None, [], "not_ib"),
    ("Ethernet", None, ["Ethernet"], "not_ib"),
    ("FibreChannel", None, ["FibreChannel"], "not_ib"),
    (None, "RoCEv2", ["Ethernet"], "not_ib"),
    (None, "iWARP", [], "not_ib"),
])
def test_ib_decision_table(lt, pp, ftypes, expected):
    assert rg._ib_decision(lt, pp, [_f(t) for t in ftypes]) == expected


def test_classify_port_protocol_does_not_decide_infiniband():
    """IB 신호가 보이는 포트/기능은 FC 도 Ethernet 도 아니다(None) — WWPN 휴리스틱에도 닿지 않는다."""
    assert rg._classify_port_protocol(None, "InfiniBand", None, None) is None
    assert rg._classify_port_protocol("InfiniBand", None, _f(None), None) is None
    ib_with_wwpn = dict(_f("InfiniBand"), wwpn="51:40:2e:c0:20:82:c2:2c")
    assert rg._classify_port_protocol(None, None, ib_with_wwpn, None) is None
    # Port.InfiniBand 블록 존재만으로는 아무것도 바뀌지 않는다 (Ethernet 포트)
    assert rg._classify_port_protocol("Ethernet", None, _f("Ethernet"), {"InfiniBand": {"AssociatedNodeGUIDs": [NODE]}}) == "Ethernet"


@pytest.mark.parametrize("raw, expected", [
    ("LinkUp", "up"), ("Up", "up"), ("LinkDown", "down"), ("NoLink", "down"), ("Down", "down"),
    ("Starting", "unknown"), ("Training", "unknown"), (None, "unknown"), ("", "unknown"), ("Weird", "unknown"),
])
def test_ib_link_status_rules(raw, expected):
    assert rg._normalize_ib_link_status(raw) == expected


# ───────────────────────────────────────────────────────────────────────────
# 시나리오 16 — IB 포트 + IB 기능
# ───────────────────────────────────────────────────────────────────────────
def test_ib_port_with_ib_function_yields_one_entry_with_guids(monkeypatch):
    routes = _routes([_port("0")], [_ndf("0")])
    out, notes, errs, _ = _gather(monkeypatch, routes)
    assert errs == [] and notes == []
    assert out["fc_hbas"] == []
    assert len(out["infiniband"]) == 1
    e = out["infiniband"][0]
    assert set(e) == IB_KEYS
    assert e == {"adapter": "HCA0", "adapter_model": MODEL, "model": MODEL, "port": "0", "node_guid": NODE, "port_guid": PORT0,
                 "link_status": "up", "rate": None, "rate_gbps": 200, "vendor": "MLNX", "firmware": "28.43.1014", "source": "redfish"}
    assert isinstance(e["rate_gbps"], int)
    assert out["ports"][0]["port_type"] == "InfiniBand" and out["ports"][0]["port_id"] == "0"
    assert out["adapters"][0]["mac"] is None, "IB 포트의 주소는 MAC 이 아니다 — adapter.mac 으로 접지 않는다"
    assert out["adapters"][0]["speed_mbps"] == 200000 and out["adapters"][0]["port_count"] == 1


def test_two_port_hca_gives_two_entries_with_distinct_port_guids(monkeypatch):
    routes = _routes([_port("0"), _port("1", status="LinkDown", speed=0.0)],
                     [_ndf("0", port=PORT0, assign="0"), _ndf("1", port=PORT1, assign="1")])
    out, notes, _, _ = _gather(monkeypatch, routes)
    assert notes == []
    assert [(e["port"], e["node_guid"], e["port_guid"], e["link_status"], e["rate_gbps"]) for e in out["infiniband"]] == [
        ("0", NODE, PORT0, "up", 200), ("1", NODE, PORT1, "down", None)]


@pytest.mark.parametrize("status, speed, exp_link, exp_rate", [
    ("LinkUp", 200.0, "up", 200), ("LinkUp", 2.5, "up", 2.5), ("LinkUp", 0.0, "up", None), ("LinkUp", None, "up", None),
    ("LinkDown", 200.0, "down", None), ("NoLink", 0.0, "down", None),
    ("Starting", 200.0, "unknown", None), ("Training", 200.0, "unknown", None), (None, 200.0, "unknown", None),
])
def test_ib_link_status_and_rate_rules(monkeypatch, status, speed, exp_link, exp_rate):
    """시나리오 7 · 8 · 10 · 11 (Redfish) — rate_gbps 는 up 일 때만, 소수 보존, rate 는 항상 null."""
    out, _, _, _ = _gather(monkeypatch, _routes([_port("0", status=status, speed=speed)], [_ndf("0")]))
    e = out["infiniband"][0]
    assert (e["link_status"], e["rate_gbps"], e["rate"]) == (exp_link, exp_rate, None)
    if exp_rate is not None:
        assert type(e["rate_gbps"]) is (float if exp_rate != int(exp_rate) else int)


def test_networkport_active_link_technology_is_also_a_mode_signal(monkeypatch):
    """구 NetworkPort(1.5 이전): ActiveLinkTechnology InfiniBand + CurrentLinkSpeedMbps (Mbps → Gbps 정확히 /1000)."""
    port = {"@odata.id": f"{ADP}/Ports/0", "Id": "0", "Name": "Network Port View", "ActiveLinkTechnology": "InfiniBand",
            "LinkStatus": "Up", "CurrentLinkSpeedMbps": 100000, "Status": {"Health": "OK"}}
    out, notes, _, _ = _gather(monkeypatch, _routes([port], [_ndf("0")]))
    assert notes == [] and out["infiniband"][0]["rate_gbps"] == 100 and out["infiniband"][0]["link_status"] == "up"


# ───────────────────────────────────────────────────────────────────────────
# 시나리오 17 · 18 — Ethernet 모드 VPI / 지원 가능 목록만
# ───────────────────────────────────────────────────────────────────────────
def test_vpi_card_in_ethernet_mode_is_not_infiniband(monkeypatch):
    """hpe_emulator_dl380a 와 같은 모양: GUID 블록 · 지원 가능 목록 [Ethernet, InfiniBand] 가 있어도 현재 모드가 Ethernet 이면 IB 아님."""
    eth = {"AssociatedMACAddresses": ["58:a2:e1:03:96:f2"]}
    routes = _routes([_port("0", lt="Ethernet", speed=100.0, ethernet=eth)],
                     [_ndf("0", ftype="Ethernet", ethernet={"MACAddress": "58:a2:e1:03:96:f2"})])
    out, notes, errs, _ = _gather(monkeypatch, routes)
    assert out["infiniband"] == [] and out["fc_hbas"] == [] and notes == [] and errs == []
    assert out["ports"][0]["port_type"] == "Ethernet"
    assert out["adapters"][0]["mac"] == "58:a2:e1:03:96:f2"


@pytest.mark.parametrize("ftype", ["Ethernet", None])
def test_capabilities_only_never_make_infiniband(monkeypatch, ftype):
    """지원 가능 목록(NetDevFuncCapabilities) 과 Port.InfiniBand 블록만으로는 IB 가 되지 않는다 (현재 모드 정보 없음)."""
    routes = _routes([_port("0", lt=None, ib={"AssociatedNodeGUIDs": [NODE], "AssociatedPortGUIDs": [PORT0]},
                            ethernet={"AssociatedMACAddresses": ["58:a2:e1:03:96:f2"]})],
                     [_ndf("0", ftype=ftype)])
    out, notes, _, _ = _gather(monkeypatch, routes)
    assert out["infiniband"] == [] and notes == []


# ───────────────────────────────────────────────────────────────────────────
# 시나리오 19 — 포트와 연결되지 않은 IB 기능
# ───────────────────────────────────────────────────────────────────────────
def test_ib_function_without_port_link_is_not_mapped_arbitrarily(monkeypatch):
    """연결 링크도 없고 `<PortId>-` 접두 부모도 없는 IB 기능 → 항목 없음 + '연결되지 않음' notice. Ethernet 포트는 그대로."""
    routes = _routes([_port("0", lt="Ethernet", speed=100.0, ethernet={"AssociatedMACAddresses": ["58:a2:e1:03:96:f2"]})],
                     [_ndf("9", assign=None)])
    out, notes, _, _ = _gather(monkeypatch, routes)
    assert out["infiniband"] == []
    assert not any(e["port"] == "9" for e in out["infiniband"])
    assert len(notes) == 1 and "InfiniBand 기능 9" in notes[0]["message"] and "연결되지 않음" in notes[0]["message"]
    assert out["ports"][0]["port_type"] == "Ethernet"


def test_orphan_ib_function_with_ib_parent_only_fills_missing_guids(monkeypatch):
    """Dell 식 `<PortId>-<n>` 기능: 부모 포트가 IB 항목이면 **항목을 더 만들지 않고** 비어 있는 GUID 만 채운다 (시나리오 25 의 변형)."""
    routes = _routes([_port("0")], [_ndf("0-1", assign=None), _ndf("0-2", assign=None)])
    out, notes, _, _ = _gather(monkeypatch, routes)
    assert notes == []
    assert [(e["port"], e["node_guid"], e["port_guid"]) for e in out["infiniband"]] == [("0", NODE, PORT0)]


def test_orphan_ib_function_under_ethernet_parent_is_a_conflict(monkeypatch):
    routes = _routes([_port("0", lt="Ethernet", speed=100.0, ethernet={"AssociatedMACAddresses": ["58:a2:e1:03:96:f2"]})],
                     [_ndf("0-1", assign=None)])
    out, notes, _, _ = _gather(monkeypatch, routes)
    assert out["infiniband"] == [] and out["ports"][0]["port_type"] == "Ethernet"
    assert len(notes) == 1 and "포트 0" in notes[0]["message"] and "확정할 수 없음" in notes[0]["message"]


# ───────────────────────────────────────────────────────────────────────────
# 시나리오 20 — GUID 배열에 복수 값
# ───────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("nodes, ports, exp_node, exp_port", [
    ([NODE], [PORT0], NODE, PORT0),
    ([NODE, None, NODE], [PORT0, PORT0], NODE, PORT0),                         # 중복·null 은 같은 값
    ([NODE, "58a2:e103:0003:96f9"], [PORT0, PORT1], None, None),               # 서로 다른 값 → null
    ([], [], None, None),
    (["0000:0000:0000:0000"], ["zz"], None, None),                             # all-zero / 형식 오류 → null
    (["58A2-E103-0003-96F2"], ["0x58a2e103000396f3"], NODE, PORT1),             # 표기 정규화
])
def test_port_guid_arrays_with_several_values_give_null(monkeypatch, nodes, ports, exp_node, exp_port):
    """기능이 연결되지 않은 IB 포트(포트 모드만): Port.InfiniBand 배열은 distinct non-null 이 1개일 때만 쓴다."""
    routes = _routes([_port("0", ib={"AssociatedNodeGUIDs": nodes, "AssociatedPortGUIDs": ports})], [])
    out, notes, _, _ = _gather(monkeypatch, routes)
    assert notes == [] and len(out["infiniband"]) == 1
    assert (out["infiniband"][0]["node_guid"], out["infiniband"][0]["port_guid"]) == (exp_node, exp_port)


def test_function_guid_wins_over_port_arrays(monkeypatch):
    routes = _routes([_port("0", ib={"AssociatedNodeGUIDs": ["58a2:e103:0003:96f9"], "AssociatedPortGUIDs": ["58a2:e103:0003:96f9"]})],
                     [_ndf("0")])
    out, _, _, _ = _gather(monkeypatch, routes)
    assert (out["infiniband"][0]["node_guid"], out["infiniband"][0]["port_guid"]) == (NODE, PORT0)


def test_non_dict_infiniband_block_is_tolerated(monkeypatch):
    routes = _routes([_port("0", ib="not_a_dict")], [])
    out, _, _, _ = _gather(monkeypatch, routes)
    assert (out["infiniband"][0]["node_guid"], out["infiniband"][0]["port_guid"]) == (None, None)


# ───────────────────────────────────────────────────────────────────────────
# 시나리오 21 — 현재 모드 충돌
# ───────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("lt, pp, ftypes, exp_port_type", [
    ("Ethernet", None, ["InfiniBand"], "Ethernet"),
    ("InfiniBand", None, ["Ethernet"], "InfiniBand"),
    (None, None, ["InfiniBand", "Ethernet"], None),
    ("Ethernet", "InfiniBand", ["InfiniBand"], "Ethernet"),
    (None, "RoCE", ["InfiniBand"], None),
    ("FibreChannel", None, ["InfiniBand"], "FibreChannel"),
])
def test_conflicting_mode_signals_give_no_entry_and_one_notice(monkeypatch, lt, pp, ftypes, exp_port_type):
    ndfs = [_ndf(str(i), ftype=t) for i, t in enumerate(ftypes)]
    out, notes, errs, _ = _gather(monkeypatch, _routes([_port("0", lt=lt, pp=pp)], ndfs))
    assert out["infiniband"] == [] and out["fc_hbas"] == []
    assert out["ports"][0]["port_type"] == exp_port_type
    assert len(notes) == 1 and "포트 0" in notes[0]["message"] and "확정할 수 없음" in notes[0]["message"]
    assert errs == [], "충돌은 수집 실패가 아니다 — errors[] 에 넣지 않는다"


def test_conflict_port_never_exposes_raw_porttype_enum(monkeypatch):
    """conflict 포트의 port_type 은 링크 기술 enum 값뿐 — raw PortType(BidirectionalPort 등) 은 쓰지 않는다 (INV-4)."""
    out, _, _, _ = _gather(monkeypatch, _routes([_port("0", lt="Ethernet", port_type="BidirectionalPort")], [_ndf("0")]))
    assert out["ports"][0]["port_type"] == "Ethernet"


# ───────────────────────────────────────────────────────────────────────────
# 시나리오 25 · 26 — 한 포트에 기능 여러 개 / 안정성
# ───────────────────────────────────────────────────────────────────────────
def test_same_port_with_two_ib_functions_is_one_entry(monkeypatch):
    agree = _routes([_port("0")], [_ndf("0"), _ndf("1", assign="0")])
    out, notes, _, _ = _gather(monkeypatch, agree)
    assert notes == [] and len(out["infiniband"]) == 1
    assert (out["infiniband"][0]["node_guid"], out["infiniband"][0]["port_guid"]) == (NODE, PORT0)

    disagree = _routes([_port("0", ib={"AssociatedPortGUIDs": [PORT0]})], [_ndf("0"), _ndf("1", assign="0", port=PORT1)])
    out, _, _, _ = _gather(monkeypatch, disagree)
    assert len(out["infiniband"]) == 1
    assert out["infiniband"][0]["node_guid"] == NODE
    assert out["infiniband"][0]["port_guid"] is None, "기능 간 불일치는 증거 충돌 — 배열로 대체하지 않는다"


def test_ib_output_is_stable_across_runs_and_member_order(monkeypatch):
    ports = [_port("0"), _port("1", status="Training")]
    ndfs = [_ndf("0", assign="0"), _ndf("1", port=PORT1, assign="1")]
    first, n1, _, _ = _gather(monkeypatch, _routes(ports, ndfs))
    second, n2, _, _ = _gather(monkeypatch, _routes(ports, ndfs))
    reversed_members, n3, _, _ = _gather(monkeypatch, _routes(ports, list(reversed(ndfs))))
    assert first == second == reversed_members and n1 == n2 == n3 == []
    assert [e["link_status"] for e in first["infiniband"]] == ["up", "unknown"]


def test_ib_path_adds_no_http_requests(monkeypatch):
    """IB 모드와 Ethernet 모드가 같은 리소스 집합만 읽는다 — NDF · Port 본문은 이미 조회하던 것이다 (request budget 불변)."""
    ib = _routes([_port("0")], [_ndf("0")])
    eth = _routes([_port("0", lt="Ethernet", ethernet={"AssociatedMACAddresses": ["58:a2:e1:03:96:f2"]})], [_ndf("0", ftype="Ethernet")])
    _, _, _, seen_ib = _gather(monkeypatch, ib)
    _, _, _, seen_eth = _gather(monkeypatch, eth)
    assert sorted(seen_ib) == sorted(seen_eth)


# ───────────────────────────────────────────────────────────────────────────
# 시나리오 28 — GUID 정규화 drift guard (stdlib 복제 ↔ 필터)
# ───────────────────────────────────────────────────────────────────────────
GUID_VECTORS = [NODE, "58A2:E103:0003:96F2", "58a2-e103-0003-96f2", "0x58a2e103000396f2", "58a2e103000396f2", " 0C42:A103:0012:3456 ",
                "0000:0000:0000:0000", "0x0000000000000000", "fe80:0000:0000:0000:0c42:a103:0012:3456", "0c42:a103:0012:345",
                "zz", "0x0002c903", "00:50:56:84:c9:5f", "", "   ", None, 12345, 0]


def test_normalize_ib_guid_matches_filter_twin():
    for v in GUID_VECTORS:
        assert rg._normalize_ib_guid(v) == normalize_ib_guid(v), v
    assert rg._normalize_ib_guid("58A2-E103-0003-96F2") == NODE
    assert rg._normalize_ib_guid("fe80:0000:0000:0000:0c42:a103:0012:3456") is None


def test_ib_entries_do_not_carry_extra_keys_or_adapter_id(monkeypatch):
    """공통 계약 키 + 호환 키(adapter_model)만. adapter/port 가 network.ports[] 의 adapter_id/port_id 와 같은 값이다."""
    out, _, _, _ = _gather(monkeypatch, _routes([_port("0")], [_ndf("0")]))
    e = out["infiniband"][0]
    assert set(e) == IB_KEYS
    assert (e["adapter"], e["port"]) == (out["ports"][0]["adapter_id"], out["ports"][0]["port_id"])
