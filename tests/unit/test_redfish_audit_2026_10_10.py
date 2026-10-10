"""2026-10-10 감사 — Redfish 모듈 결함 재현/고정 (plan §4.3).

RD-F03  읽기 도중 끊긴 응답(IncompleteRead · BadStatusLine)은 쓰기 helper 와 같은 transport 오류(status 0)다 — 예외로 섹션을 죽이지 않는다.
D-09    vendor 정규화 한 규칙: 최장 alias · 전방 일치 · 3자 이하는 토큰 경계. 'ibm'(lenovo) 이 'iBMC'(huawei) 를 삼키지 않고 dict 순서와 무관하다.
RD-F18  BMC NIC · NetworkProtocol · PSU · ResourceBlock/Fabric 하위 조회 실패는 비차단 오류로 남는다(404 는 미노출 — 조용).
RD-F15  한 포트에 NDF 가 여럿(Ethernet + FCoE)이면 멤버 순서와 무관하게 FC 다. FC 기능마다 hba 하나.
D-07    Absent PSU 는 용량 합 · 요약 수에 들어가지 않는다.
RD-UNK  CPU 모델 자리표시자 'unknown' 은 null 이다.
"""
from __future__ import annotations

import ast
import http.client
import sys
import types
from pathlib import Path

import pytest
import yaml
from jinja2 import Environment

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))
sys.path.insert(0, str(REPO))

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
from module_utils.adapter_common import normalize_vendor  # noqa: E402

NB = rg._CODE_NON_BLOCKING_SUBRESOURCE


def _routes(monkeypatch, table):
    monkeypatch.setattr(rg, "_get", lambda ip, path, *a, **kw: table.get(path, (404, {}, "HTTP 404: Not Found")))


# ── RD-F03 ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("exc", [http.client.IncompleteRead(b"partial"), http.client.BadStatusLine("garbage"),
                                 http.client.RemoteDisconnected("closed")])
def test_read_helpers_turn_a_broken_response_into_a_transport_error(monkeypatch, exc):
    def boom(*a, **k):
        raise exc
    monkeypatch.setattr(rg, "_urlopen", boom)
    for fn, args in ((rg._get_impl, ("10.0.0.1", "Systems/1", "u", "p", 5, False)), (rg._get_noauth, ("10.0.0.1", "", 5, False))):
        code, data, err = fn(*args)
        assert code == 0 and data == {} and err.startswith("Response lost: "), (fn.__name__, code, err)
    assert rg._probe_realm_hint("10.0.0.1", 5, False) is None, "realm 힌트도 예외 대신 '힌트 없음'"


# ── D-09 ───────────────────────────────────────────────────────────────────────
VM = dict(rg._FALLBACK_VENDOR_MAP)


def test_best_alias_match_longest_token_bounded_order_independent():
    assert rg._best_alias_match("huawei technologies co., ltd.", VM) == "huawei"
    assert rg._best_alias_match("ibmc", VM) is None, "'ibm'(3자) 은 토큰 전체로만 맞는다 — 'ibmc' 를 삼키지 않는다"
    assert rg._best_alias_match("ibm", VM) == "lenovo" and rg._best_alias_match("ibm corporation", VM) == "lenovo"
    assert rg._best_alias_match("hpc systems inc.", VM) is None and rg._best_alias_match("hp", VM) == "hpe"
    assert rg._best_alias_match("hpe proliant dl380 gen11", VM) == "hpe"
    assert rg._best_alias_match("cisco systems, inc.", VM) == "cisco" and rg._best_alias_match("dell inc.", VM) == "dell"
    assert rg._best_alias_match("super micro computer, inc.", VM) == "supermicro"
    reversed_vm = dict(reversed(list(VM.items())))
    for s in ("huawei technologies", "lenovo group limited", "hewlett packard enterprise", "quanta cloud technology", "inspur systems", "ibm"):
        assert rg._best_alias_match(s, VM) == rg._best_alias_match(s, reversed_vm), s
    assert rg._best_alias_match("", VM) is None and rg._best_alias_match("   ", VM) is None


def test_vendor_from_text_prefers_aliases_then_bmc_product_hints():
    assert rg._vendor_from_text("iBMC", VM) == "huawei"                      # 종전: 'ibm' alias 가 먼저 걸려 lenovo
    assert rg._vendor_from_text("Huawei iBMC", VM) == "huawei"
    assert rg._vendor_from_text("Integrated Dell Remote Access Controller", VM) == "dell"
    assert rg._vendor_from_text("iLO 5", VM) == "hpe" and rg._vendor_from_text("XClarity Controller", VM) == "lenovo"
    assert rg._vendor_from_text("Cisco RESTful Root Service", VM) == "cisco"
    assert rg._vendor_from_text("Basic realm=\"iDRAC\"", VM) == "dell"
    assert rg._vendor_from_text("Root Service", VM) is None and rg._vendor_from_text(None, VM) is None


def test_service_root_detection_uses_the_same_rule():
    assert rg._detect_vendor_from_service_root({"Product": "iBMC"}) == "huawei"
    assert rg._detect_vendor_from_service_root({"Vendor": "IBM"}) == "lenovo"
    assert rg._detect_vendor_from_service_root({"Name": "Cisco RESTful Root Service"}) == "cisco"
    assert rg._detect_vendor_from_service_root({"Product": "HPC Systems Root"}) is None
    assert rg._detect_vendor_from_service_root({"Oem": {"Lenovo": {}}}) == "lenovo"


def test_manufacturer_normalization_matches_adapter_common_on_canonical_hits():
    """두 구현이 같은 규칙이다 — canonical 을 돌려주는 입력은 같은 vendor, 아니면 모듈은 'unknown' · adapter_common 은 원문."""
    corpus = list(VM) + ["Huawei iBMC", "iBMC", "IBM", "HPC Systems Inc.", "HP", "HPE ProLiant", "  ", "Dell Inc.", "Cisco Systems, Inc.",
                         "Lenovo ThinkSystem SR650 V2", "Supermicro", "QCT", "Inspur Information Technology Company Limited"]
    for raw in corpus:
        mod = rg._normalize_vendor_from_aliases(raw.strip().lower())
        ac = normalize_vendor(raw, aliases=VM)
        if mod != "unknown":
            assert ac == mod, (raw, mod, ac)
        else:
            assert ac in (None, raw.strip().lower()), (raw, ac)
    assert rg._normalize_vendor_from_aliases("ibmc") == "unknown"
    assert rg._normalize_vendor_from_aliases("huawei ibmc") == "huawei"


# ── RD-F18 ──────────────────────────────────────────────────────────────────────
MGR = "/redfish/v1/Managers/1"


def _mgr_routes(nic_coll=(200, {"Members": [{"@odata.id": MGR + "/EthernetInterfaces/1"}]}, None),
                nic=(200, {"IPv4Addresses": [{"Address": "10.0.0.9", "Gateway": "10.0.0.1"}], "MACAddress": "AA:BB:CC:DD:EE:FF"}, None),
                np=(200, {"HostName": "bmc1", "FQDN": "bmc1.example"}, None)):
    return {
        rg._p(MGR): (200, {"Id": "1", "FirmwareVersion": "1.0", "Model": "X", "EthernetInterfaces": {"@odata.id": MGR + "/EthernetInterfaces"},
                           "NetworkProtocol": {"@odata.id": MGR + "/NetworkProtocol"}}, None),
        rg._p(MGR + "/EthernetInterfaces"): nic_coll,
        rg._p(MGR + "/EthernetInterfaces/1"): nic,
        rg._p(MGR + "/NetworkProtocol"): np,
    }


def _nb(errors, section):
    return [e for e in errors if e.get("section") == section and e.get("code") == NB]


def test_bmc_nic_collection_failure_is_recorded_not_silent(monkeypatch):
    _routes(monkeypatch, _mgr_routes(nic_coll=(500, {}, "HTTP 500: Internal Server Error")))
    data, errors = rg.gather_bmc("10.0.0.1", MGR, "dell", "u", "p", 5, False)
    assert data["ip"] is None and len(_nb(errors, "bmc")) == 1 and "EthernetInterfaces" in _nb(errors, "bmc")[0]["message"]
    _routes(monkeypatch, _mgr_routes(nic=(503, {}, "HTTP 503: Service Unavailable")))
    data, errors = rg.gather_bmc("10.0.0.1", MGR, "dell", "u", "p", 5, False)
    assert len(_nb(errors, "bmc")) == 1 and "EthernetInterface " in _nb(errors, "bmc")[0]["message"]
    _routes(monkeypatch, _mgr_routes(np=(500, {}, "HTTP 500: boom")))
    data, errors = rg.gather_bmc("10.0.0.1", MGR, "dell", "u", "p", 5, False)
    assert data["ip"] == "10.0.0.9" and len(_nb(errors, "bmc")) == 1 and "NetworkProtocol" in _nb(errors, "bmc")[0]["message"]


def test_bmc_404_subresources_stay_quiet_and_success_has_no_errors(monkeypatch):
    _routes(monkeypatch, _mgr_routes(nic_coll=(404, {}, "HTTP 404: Not Found"), np=(404, {}, "HTTP 404: Not Found")))
    data, errors = rg.gather_bmc("10.0.0.1", MGR, "dell", "u", "p", 5, False)
    assert errors == [] and data["ip"] is None
    _routes(monkeypatch, _mgr_routes())
    data, errors = rg.gather_bmc("10.0.0.1", MGR, "dell", "u", "p", 5, False)
    assert errors == [] and data["ip"] == "10.0.0.9" and data["network_hostname"] == "bmc1.example"


CH = "/redfish/v1/Chassis/1"


def _psu_routes(coll=(200, {"Members": [{"@odata.id": CH + "/PowerSubsystem/PowerSupplies/0"}, {"@odata.id": CH + "/PowerSubsystem/PowerSupplies/1"}]}, None),
                psu0=(200, {"Name": "PS0", "PowerCapacityWatts": 800, "Status": {"State": "Enabled", "Health": "OK"}}, None),
                psu1=(200, {"Name": "PS1", "PowerCapacityWatts": 800, "Status": {"State": "Absent", "Health": None}}, None)):
    return {
        rg._p(CH) + "/PowerSubsystem": (200, {"PowerSupplies": {"@odata.id": CH + "/PowerSubsystem/PowerSupplies"}}, None),
        rg._p(CH + "/PowerSubsystem/PowerSupplies"): coll,
        rg._p(CH + "/PowerSubsystem/PowerSupplies/0"): psu0,
        rg._p(CH + "/PowerSubsystem/PowerSupplies/1"): psu1,
    }


def test_power_subsystem_psu_failures_are_recorded_and_absent_psu_is_not_capacity(monkeypatch):
    _routes(monkeypatch, _psu_routes())
    data, errors = rg._gather_power_subsystem("10.0.0.1", CH, "u", "p", 5, False)
    assert errors == [] and len(data["power_supplies"]) == 2
    assert data["power_control"]["power_capacity_watts"] == 800, "Absent 슬롯 800W 는 설치된 용량이 아니다 (D-07)"
    _routes(monkeypatch, _psu_routes(coll=(503, {}, "HTTP 503: Service Unavailable")))
    data, errors = rg._gather_power_subsystem("10.0.0.1", CH, "u", "p", 5, False)
    assert len(_nb(errors, "power")) == 1 and "PowerSupplies" in _nb(errors, "power")[0]["message"] and data["power_supplies"] == []
    _routes(monkeypatch, _psu_routes(psu1=(500, {}, "HTTP 500: boom")))
    data, errors = rg._gather_power_subsystem("10.0.0.1", CH, "u", "p", 5, False)
    assert len(data["power_supplies"]) == 1 and len(_nb(errors, "power")) == 1 and "PowerSupply " in _nb(errors, "power")[0]["message"]
    _routes(monkeypatch, _psu_routes(coll=(404, {}, "HTTP 404: Not Found")))
    data, errors = rg._gather_power_subsystem("10.0.0.1", CH, "u", "p", 5, False)
    assert errors == [] and data["power_supplies"] == []


# ── RD-F15 ──────────────────────────────────────────────────────────────────────
def _cna_routes(order):
    """CNA 한 포트에 NDF 둘 — Ethernet 기능(MAC 파생 WWN 포함) + FCoE 기능. order 는 Members 순서."""
    chassis = "/redfish/v1/Chassis/System.Embedded.1"
    adp = chassis + "/NetworkAdapters/NIC.Slot.2"
    port = adp + "/NetworkPorts/NIC.Slot.2-1"
    eth = adp + "/NetworkDeviceFunctions/NIC.Slot.2-1-1"
    fcoe = adp + "/NetworkDeviceFunctions/NIC.Slot.2-1-2"
    members = [{"@odata.id": eth}, {"@odata.id": fcoe}] if order == "eth_first" else [{"@odata.id": fcoe}, {"@odata.id": eth}]
    return chassis, {
        rg._p(chassis) + "/NetworkAdapters": (200, {"Members": [{"@odata.id": adp}]}, None),
        rg._p(adp): (200, {"Id": "NIC.Slot.2", "Manufacturer": "QLogic", "Model": "QLogic 57810 CNA",
                           "Controllers": [{"ControllerCapabilities": {"NetworkPortCount": 2}, "FirmwarePackageVersion": "7.13"}],
                           "NetworkPorts": {"@odata.id": adp + "/NetworkPorts"},
                           "NetworkDeviceFunctions": {"@odata.id": adp + "/NetworkDeviceFunctions"}}, None),
        rg._p(adp) + "/NetworkPorts": (200, {"Members": [{"@odata.id": port}]}, None),
        rg._p(port): (200, {"Id": "NIC.Slot.2-1", "LinkStatus": "Up", "AssociatedNetworkAddresses": ["00:0e:1e:aa:bb:cc"],
                            "Ethernet": {"AssociatedMACAddresses": ["00:0e:1e:aa:bb:cc"]}}, None),
        rg._p(adp) + "/NetworkDeviceFunctions": (200, {"Members": members}, None),
        rg._p(eth): (200, {"Id": "NIC.Slot.2-1-1", "NetDevFuncType": "Ethernet",
                           "FibreChannel": {"WWPN": "20:01:00:0e:1e:aa:bb:cd", "WWNN": "20:00:00:0e:1e:aa:bb:cd"},
                           "Links": {"PhysicalPortAssignment": {"@odata.id": port}}}, None),
        rg._p(fcoe): (200, {"Id": "NIC.Slot.2-1-2", "NetDevFuncType": "FibreChannelOverEthernet",
                            "FibreChannel": {"WWPN": "20:01:00:0e:1e:aa:bb:ce", "WWNN": "20:00:00:0e:1e:aa:bb:ce"},
                            "Links": {"PhysicalPortAssignment": {"@odata.id": port}}}, None),
    }


@pytest.mark.parametrize("order", ["eth_first", "fcoe_first"])
def test_cna_port_with_ethernet_and_fcoe_functions_is_fc_regardless_of_member_order(monkeypatch, order):
    chassis, routes = _cna_routes(order)
    _routes(monkeypatch, routes)
    out, errors = rg.gather_network_adapters_chassis("10.0.0.1", chassis, "u", "p", 30, False)
    assert errors == []
    assert [p["port_type"] for p in out["ports"]] == ["FCoE"], order
    assert len(out["fc_hbas"]) == 1 and out["fc_hbas"][0]["port_type"] == "FCoE"
    assert out["fc_hbas"][0]["wwpn"] == "20:01:00:0e:1e:aa:bb:ce", "hba 의 WWPN 은 FCoE 기능의 것 — Ethernet 기능의 MAC 파생 WWN 이 아니다"
    assert out["ports"][0]["associated_address"] == "20:01:00:0e:1e:aa:bb:ce"
    assert out["adapters"][0]["mac"] is None, "FC 포트의 주소는 NIC mac 으로 접히지 않는다"


# ── D-07 / RD-UNK: normalize_standard.yml 템플릿을 실제로 렌더한다 ───────────────────────
NORM = REPO / "redfish-gather" / "tasks" / "normalize_standard.yml"


def _set_fact_template(var):
    for t in yaml.safe_load(NORM.read_text(encoding="utf-8")):
        sf = (t.get("set_fact") or t.get("ansible.builtin.set_fact")) if isinstance(t, dict) else None
        if isinstance(sf, dict) and var in sf:
            return sf[var]
    raise AssertionError(var)


def _render_literal(var, **ctx):
    text = Environment().from_string(_set_fact_template(var)).render(**ctx)
    return ast.literal_eval(text.strip())


def test_power_summary_excludes_absent_psu_from_count_and_capacity():
    psus = [{"name": "PS0", "power_capacity_w": 800, "state": "Enabled", "health": "OK"},
            {"name": "PS1", "power_capacity_w": 800, "state": "Absent", "health": None}]
    s = _render_literal("_rf_power_summary", _rf_d_power={"power_supplies": psus, "power_control": {}})
    assert s["psu_count"] == 1 and s["psu_active"] == 1 and s["total_capacity_w"] == 800 and s["redundant"] is False
    assert s["capacity_unknown_count"] == 0 and s["unknown_health_count"] == 0, "Absent 슬롯은 상태 집계에도 들어가지 않는다"
    both = [dict(psus[0]), dict(psus[0], name="PS1")]
    s2 = _render_literal("_rf_power_summary", _rf_d_power={"power_supplies": both, "power_control": {}})
    assert s2["psu_count"] == 2 and s2["total_capacity_w"] == 1600 and s2["redundant"] is True


def test_cpu_summary_without_model_is_null_not_unknown():
    s = _render_literal("_rf_summary_cpu", _rf_d_cpus=[{"total_cores": 8, "speed_mhz": 2000}, {"total_cores": 8, "speed_mhz": 2000}])
    assert s["groups"][0]["model"] is None and s["groups"][0]["sockets"] == 2 and "unknown" not in repr(s)


def test_module_cpu_summary_without_model_is_null():
    raw = [{"processor_type": "CPU", "model": None, "total_cores": 4, "total_threads": 8}]
    out = rg._normalize_cpu_raw(raw) if "raw" in rg._normalize_cpu_raw.__code__.co_varnames else rg._normalize_cpu_raw(raw)
    groups = out.get("summary", out).get("groups") if isinstance(out, dict) else None
    assert groups is not None and groups[0]["model"] is None
