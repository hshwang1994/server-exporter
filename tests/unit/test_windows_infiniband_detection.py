"""Windows `storage.infiniband[]` — 판별 · 상태 · 속도 계약 (2026-10-17 InfiniBand 전면 검증).

실장비 IB 가 없으므로 세 층으로 본다 (실장비 검증이 아니다).
  1. 정적 (모든 플랫폼): IB win_shell 에 PnP 서비스명 폴백(ibbus/ibal/ipoib · VEN_15B3)이 없고, 매체(NdisPhysicalMedium 11) ·
     RdmaTechnology · ReceiveLinkSpeed · 팀 멀티플렉서 제외(MS_IMPLAT)가 있다. note 에 내부 규칙 번호가 없다.
  2. Jinja (모든 플랫폼): 스크립트 JSON → gather_storage.yml 의 실제 `_w_ib` · fragment 렌더 (run_storage).
  3. 실제 PowerShell (powershell.exe 가 있을 때): cmdlet 을 같은 이름의 함수로 가려 IB win_shell 원문을 돌리고 그 출력으로 2 를 잇는다.

입력값의 근거 (gather_storage.yml IB 태스크 주석의 source 줄):
  - MSFT_NetAdapter ValueMap: NdisPhysicalMedium Infiniband (11) · 802.3 (14); PhysicalMediaType 표시값 'Infiniband' / '802.3'
    (NetAdapter.Types.ps1xml); ReceiveLinkSpeed 는 bits per second; Status 표시값 Up · Disconnected · Disabled · Not Present …
  - NDK *NetworkDirectTechnology: iWARP=1 · InfiniBand=2 · RoCE=3 · RoCEv2=4 (Get-NetAdapterRdma RdmaAdapterInfo.RdmaTechnology)
  - LBFO 팀 멀티플렉서 INF(ndisimplatformmp.inf): *PhysicalMediaType=14, HWID COMPOSITEBUS\\MS_IMPLAT_MP (2026-06-22 사이트 캡처와 같다)
"""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
pytest.importorskip("jinja2")

REPO = Path(__file__).resolve().parents[2]
STOR_YML = REPO / "os-gather" / "tasks" / "windows" / "gather_storage.yml"
IB_TASK = "windows | storage | infiniband adapters (best-effort)"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_windows_storage_enum_render import disk, run_storage  # noqa: E402

IB_KEYS = {"adapter", "port", "node_guid", "port_guid", "link_status", "rate", "rate_gbps", "model", "vendor", "firmware",
           "source", "note"}


def _ib_script() -> str:
    for t in yaml.safe_load(STOR_YML.read_text(encoding="utf-8")):
        if isinstance(t, dict) and t.get("name") == IB_TASK:
            return t["ansible.windows.win_shell"]
    raise AssertionError(f"win_shell 태스크 {IB_TASK!r} 미발견")


def _code(script: str) -> str:
    return "\n".join(ln for ln in script.splitlines() if not ln.lstrip().startswith("#"))


def _w_ib_template() -> str:
    for t in yaml.safe_load(STOR_YML.read_text(encoding="utf-8")):
        sf = t.get("ansible.builtin.set_fact") if isinstance(t, dict) else None
        if isinstance(sf, dict) and "_w_ib" in sf:
            return sf["_w_ib"]
    raise AssertionError("_w_ib set_fact 미발견")


# ═══════════════════════════════════════════════════════════════════════════
# 1. 정적
# ═══════════════════════════════════════════════════════════════════════════
def test_ib_script_has_no_pnp_service_fallback_and_uses_documented_signals():
    code = _code(_ib_script())
    for gone in ("Get-PnpDevice", "ibbus", "ibal", "ipoib", "VEN_15B3", "HardwareID"):
        assert gone not in code, f"사라져야 할 토큰 {gone!r} 이 남았다"
    for kept in ("Get-NetAdapter -IncludeHidden", "NdisPhysicalMedium -eq 11", "PhysicalMediaType", "RdmaTechnology",
                 "ReceiveLinkSpeed", "MS_IMPLAT", "Multiplexor"):
        assert kept in code, f"있어야 할 토큰 {kept!r} 이 없다"
    assert code.count("Get-NetAdapter -IncludeHidden") == 1, "Get-NetAdapter 는 1회"
    assert "Enabled" not in code, "RDMA Enabled(지원 여부)는 IB 근거가 아니다"


def test_ib_note_has_no_internal_rule_numbers():
    tmpl = _w_ib_template()
    m = re.search(r"'note':\s*'([^']*)'", tmpl)
    assert m, "note 가 없다"
    note = m.group(1)
    assert not re.search(r"\brule\b|R\d+-?[A-Z]?\b|규칙 \d+", note), note
    assert "null" in note


def test_ib_entry_port_is_null_not_interface_name():
    tmpl = _w_ib_template()
    assert re.search(r"'port':\s*none", tmpl), "port 는 null — 연결 이름을 물리 포트 번호로 적지 않는다"
    assert "a.name" not in tmpl


# ═══════════════════════════════════════════════════════════════════════════
# 2. Jinja — 스크립트 JSON → _w_ib / fragment
# ═══════════════════════════════════════════════════════════════════════════
def _row(**over):
    base = {"adapter": "Mellanox ConnectX-6 VPI Adapter", "name": "Ethernet 5", "link_status": "Up", "rate": "100 Gbps",
            "rx_bps": 100000000000, "vendor": "Mellanox Technologies Ltd.", "evidence": "physical_medium"}
    base.update(over)
    return base


def _render(ib):
    return run_storage([disk(0, protocol="SAS")], ib=ib)


def test_ib_up_adapter_maps_all_fields():
    out = _render({"ib": [_row()]})
    assert len(out["storage"]["infiniband"]) == 1
    e = out["storage"]["infiniband"][0]
    assert set(e) == IB_KEYS
    assert e["adapter"] == e["model"] == "Mellanox ConnectX-6 VPI Adapter"
    assert e["port"] is None and e["node_guid"] is None and e["port_guid"] is None and e["firmware"] is None
    assert e["link_status"] == "up" and e["rate"] == "100 Gbps"
    assert e["rate_gbps"] == 100 and isinstance(e["rate_gbps"], int)
    assert e["vendor"] == "Mellanox Technologies Ltd." and e["source"] == "os"
    assert "rule" not in e["note"]
    assert out["collected"] == ["storage"] and out["errors"] == []


def test_ib_disconnected_is_down_with_null_rate():
    e = _render({"ib": [_row(link_status="Disconnected", rate="0 bps", rx_bps=0)]})["storage"]["infiniband"][0]
    assert e["link_status"] == "down" and e["rate"] is None and e["rate_gbps"] is None


def test_ib_decimal_link_speed_is_2_5():
    e = _render({"ib": [_row(rate="2.5 Gbps", rx_bps=2500000000)]})["storage"]["infiniband"][0]
    assert e["rate_gbps"] == 2.5 and isinstance(e["rate_gbps"], float) and e["rate"] == "2.5 Gbps"


@pytest.mark.parametrize("status", ["Disabled", "Not Present", "Unknown", "Dormant", "Lower Layer Down", ""])
def test_ib_non_up_non_disconnected_status_is_unknown(status):
    e = _render({"ib": [_row(link_status=status, rate="100 Gbps", rx_bps=100000000000)]})["storage"]["infiniband"][0]
    assert e["link_status"] == "unknown" and e["rate_gbps"] is None, "미확인 상태의 속도는 현재 속도가 아니다"
    assert e["rate"] == "100 Gbps"


def test_ib_up_with_zero_receive_speed_has_null_rate():
    e = _render({"ib": [_row(rate="Unknown", rx_bps=0)]})["storage"]["infiniband"][0]
    assert e["link_status"] == "up" and e["rate"] is None and e["rate_gbps"] is None


def test_ib_single_object_collapse_is_handled():
    """PS 5.1 ConvertTo-Json 은 원소 1개 배열을 객체로 접는다 — mapping 이면 [wrap]."""
    out = _render({"ib": _row()})
    assert len(out["storage"]["infiniband"]) == 1


def test_ib_blank_stdout_is_empty_list():
    out = _render(None)
    assert out["storage"]["infiniband"] == []


def test_ib_vendor_blank_is_null():
    e = _render({"ib": [_row(vendor="")]})["storage"]["infiniband"][0]
    assert e["vendor"] is None


# ═══════════════════════════════════════════════════════════════════════════
# 3. 실제 PowerShell — 가짜 cmdlet 위에서 IB win_shell 원문 실행
# ═══════════════════════════════════════════════════════════════════════════
from test_windows_call_consolidation_powershell import POWERSHELL, compact, prelude, run_encoded  # noqa: E402

needs_powershell = pytest.mark.skipif(POWERSHELL is None, reason="powershell.exe 없음 — IB 스크립트 실행 검증은 Windows 에서만")


def _adapter(name, desc, *, medium=14, media_type="802.3", status="Up", link_speed="100 Gbps", rx=100000000000,
             provider="Mellanox Technologies Ltd.", pnp="PCI\\VEN_15B3&DEV_101B&SUBSYS_000715B3&REV_00\\4&1a2b3c4d&0&00E0",
             hidden=False):
    return {"Name": name, "InterfaceDescription": desc, "NdisPhysicalMedium": medium, "PhysicalMediaType": media_type,
            "Status": status, "LinkSpeed": link_speed, "ReceiveLinkSpeed": rx, "TransmitLinkSpeed": rx,
            "DriverProvider": provider, "PnPDeviceID": pnp, "Hidden": hidden, "ConnectorPresent": True,
            "InterfaceIndex": 10, "MacAddress": "00-15-5D-00-00-01"}


IB_HCA = _adapter("Ethernet 5", "Mellanox ConnectX-6 Adapter (IPoIB)", medium=11, media_type="Infiniband")
IB_HCA_DOWN = _adapter("Ethernet 6", "Mellanox ConnectX-6 Adapter (IPoIB) #2", medium=11, media_type="Infiniband",
                       status="Disconnected", link_speed="0 bps", rx=0)
ROCE_NIC = _adapter("Ethernet 7", "Mellanox ConnectX-6 Dx Adapter", medium=14, media_type="802.3")
IWARP_NIC = _adapter("Ethernet 8", "Chelsio T6 Adapter", medium=14, media_type="802.3", provider="Chelsio Communications",
                     pnp="PCI\\VEN_1425&DEV_6407\\0")
INTEL_NIC = _adapter("Ethernet", "Intel(R) I350 Gigabit Network Connection", medium=14, media_type="802.3",
                     provider="Intel", pnp="PCI\\VEN_8086&DEV_1521\\0", link_speed="1 Gbps", rx=1000000000)
# 2026-06-22 사이트 캡처(10.100.64.120)의 팀 멀티플렉서 — INF *PhysicalMediaType=14. medium=11 변형은 방어 검증용 합성값.
TEAM_MUX = _adapter("LabTeam2", "Microsoft Network Adapter Multiplexor Driver #3", medium=14, media_type="802.3",
                    provider="Microsoft", pnp="COMPOSITEBUS\\MS_IMPLAT_MP\\{CAFED635-7A35-4993-9DD4-27679F79DF6D}",
                    link_speed="20 Gbps", rx=20000000000)
TEAM_MUX_IB_MEDIUM = dict(TEAM_MUX, Name="LabTeam3", NdisPhysicalMedium=11, PhysicalMediaType="Infiniband")

STOR_BASE = {"volumes": [], "pdisks": [], "cim": {"Win32_DiskDrive": []}, "os_disk_number": 0, "adapters": [], "pnp": []}


def _run_ib(adapters, rdma=None, pnp=None):
    fx = copy.deepcopy(STOR_BASE)
    fx["adapters"] = list(adapters)
    if rdma is not None:
        fx["rdma"] = list(rdma)
    if pnp is not None:
        fx["pnp"] = list(pnp)
    res = run_encoded(prelude("storage", fx) + compact(_ib_script()), fx)
    assert res["rc"] == 0, res["stderr"][-800:]
    lines = [ln for ln in res["stdout_lines"] if ln.strip()]
    assert len(lines) == 1, lines
    return json.loads(lines[0]), res["calls"]


def _ib_rows(doc):
    ib = doc["ib"]
    return [ib] if isinstance(ib, dict) else list(ib or [])


@needs_powershell
def test_ib_medium_adapter_is_collected():
    """시나리오 12 — 물리 매체 Infiniband(11) 어댑터는 수집, 이더넷 NIC 는 아니다. 출력은 Jinja 체인까지 잇는다."""
    doc, calls = _run_ib([INTEL_NIC, IB_HCA, ROCE_NIC])
    rows = _ib_rows(doc)
    assert [r["name"] for r in rows] == ["Ethernet 5"]
    assert rows[0]["evidence"] == "physical_medium" and rows[0]["rx_bps"] == 100000000000
    assert calls.count("Get-NetAdapter -IncludeHidden") == 1 and "Get-PnpDevice" not in calls
    e = run_storage([disk(0, protocol="SAS")], ib=doc)["storage"]["infiniband"][0]
    assert (e["adapter"], e["link_status"], e["rate"], e["rate_gbps"], e["port"]) == \
        ("Mellanox ConnectX-6 Adapter (IPoIB)", "up", "100 Gbps", 100, None)


@needs_powershell
def test_ib_medium_display_string_alone_is_enough():
    """NdisPhysicalMedium 이 비어도 PhysicalMediaType 표시값 'Infiniband'(대소문자 무시)면 수집."""
    a = dict(IB_HCA, NdisPhysicalMedium=None, PhysicalMediaType="InfiniBand")
    doc, _ = _run_ib([a])
    assert [r["name"] for r in _ib_rows(doc)] == ["Ethernet 5"]


@needs_powershell
def test_rdma_technology_infiniband_is_second_signal():
    """WinOF-2 known issue 1702662 재현: 물리 매체가 802.3 으로 보고되는 IPoIB NIC 도 RdmaTechnology=InfiniBand 면 수집 (합성 입력)."""
    ipoib_as_8023 = _adapter("Ethernet 9", "Mellanox ConnectX-5 Adapter (IPoIB)", medium=14, media_type="802.3")
    doc, calls = _run_ib([ipoib_as_8023, ROCE_NIC],
                         rdma=[{"Name": "Ethernet 9", "Enabled": True, "RdmaAdapterInfo": {"RdmaTechnology": "InfiniBand"}},
                               {"Name": "Ethernet 7", "Enabled": True, "RdmaAdapterInfo": {"RdmaTechnology": "RoCEv2"}}])
    rows = _ib_rows(doc)
    assert [(r["name"], r["evidence"]) for r in rows] == [("Ethernet 9", "rdma_technology")]
    assert calls.count("Get-NetAdapterRdma") == 1


@needs_powershell
def test_roce_and_iwarp_nics_are_excluded():
    """시나리오 13 — RoCE/iWARP 지원 NIC: 802.3 매체 + RdmaTechnology RoCE/RoCEv2/iWARP → 제외. RDMA Enabled 는 근거가 아니다."""
    doc, _ = _run_ib([ROCE_NIC, IWARP_NIC],
                     rdma=[{"Name": "Ethernet 7", "Enabled": True, "RdmaAdapterInfo": {"RdmaTechnology": "RoCEv2"}},
                           {"Name": "Ethernet 8", "Enabled": True, "RdmaAdapterInfo": {"RdmaTechnology": "iWARP"}}])
    assert _ib_rows(doc) == []


@needs_powershell
def test_lbfo_multiplexor_is_excluded_even_with_ib_medium():
    """시나리오 14 — 팀 멀티플렉서(2026-06-22 오탐 장치)는 어떤 신호가 있어도 제외."""
    doc, _ = _run_ib([TEAM_MUX, TEAM_MUX_IB_MEDIUM, IB_HCA],
                     rdma=[{"Name": "LabTeam2", "Enabled": True, "RdmaAdapterInfo": {"RdmaTechnology": "InfiniBand"}}])
    assert [r["name"] for r in _ib_rows(doc)] == ["Ethernet 5"]


@needs_powershell
def test_ib_pnp_services_alone_yield_empty_list():
    """시나리오 15 — IB 관련 PnP 장치/서비스만 있고 IB 매체 어댑터가 없으면 [] (PnP 를 보지 않는다)."""
    doc, calls = _run_ib([INTEL_NIC],
                         pnp=[{"InstanceId": "PCI\\VEN_15B3&DEV_101B\\0", "Service": "ibbus", "Class": "Net",
                               "FriendlyName": "Mellanox ConnectX-6", "Status": "OK", "HardwareID": "PCI\\VEN_15B3&DEV_101B"}])
    assert _ib_rows(doc) == [] and "Get-PnpDevice" not in calls


@needs_powershell
def test_disconnected_ib_adapter_is_included_as_down():
    """시나리오 7(Windows) — 링크 끊긴 IB 어댑터도 항목이며 down, 속도는 null."""
    doc, _ = _run_ib([IB_HCA_DOWN])
    e = run_storage([disk(0, protocol="SAS")], ib=doc)["storage"]["infiniband"][0]
    assert (e["link_status"], e["rate"], e["rate_gbps"]) == ("down", None, None)


@needs_powershell
def test_decimal_link_speed_through_powershell():
    """시나리오 10(Windows) — 2.5 Gbps 는 2.5 (종전 regex 가 25 로 읽던 값)."""
    doc, _ = _run_ib([dict(IB_HCA, LinkSpeed="2.5 Gbps", ReceiveLinkSpeed=2500000000, TransmitLinkSpeed=2500000000)])
    e = run_storage([disk(0, protocol="SAS")], ib=doc)["storage"]["infiniband"][0]
    assert e["rate_gbps"] == 2.5 and e["rate"] == "2.5 Gbps"


@needs_powershell
def test_disabled_ib_adapter_is_unknown():
    doc, _ = _run_ib([dict(IB_HCA, Status="Disabled")])
    e = run_storage([disk(0, protocol="SAS")], ib=doc)["storage"]["infiniband"][0]
    assert e["link_status"] == "unknown" and e["rate_gbps"] is None


@needs_powershell
def test_get_netadapter_failure_yields_empty_list_not_error():
    """시나리오 24(Windows) — cmdlet 종료 오류는 빈 목록 (best-effort, 스크립트 rc 0)."""
    fx = dict(copy.deepcopy(STOR_BASE), adapters=[IB_HCA], fail={"Get-NetAdapter -IncludeHidden": "WMI provider failure (fixture)"})
    res = run_encoded(prelude("storage", fx) + compact(_ib_script()), fx)
    assert res["rc"] == 0
    assert json.loads([ln for ln in res["stdout_lines"] if ln.strip()][0])["ib"] in ([], None)


@needs_powershell
def test_hidden_ib_adapter_is_still_seen():
    doc, _ = _run_ib([dict(IB_HCA, Hidden=True)])
    assert [r["name"] for r in _ib_rows(doc)] == ["Ethernet 5"]


@needs_powershell
def test_same_input_twice_is_identical():
    """시나리오 26(Windows)."""
    a, _ = _run_ib([IB_HCA, IB_HCA_DOWN, ROCE_NIC])
    b, _ = _run_ib([IB_HCA, IB_HCA_DOWN, ROCE_NIC])
    assert a == b and [r["name"] for r in _ib_rows(a)] == ["Ethernet 5", "Ethernet 6"]
