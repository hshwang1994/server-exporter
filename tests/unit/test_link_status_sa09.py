"""일반 NIC · 포트 링크 값과 HBA 링크 값의 분리 (2026-10-29 SA-09, 사용자 의견).

  일반 NIC · 포트(network.interfaces[] · network.ports[] · 파티션 NIC) — _normalize_link_status:
    LinkUp · Up · Connected → up / LinkDown · Down · NoLink · Disconnected · Disabled · Inactive · Offline → down /
    Starting · Training(DMTF 전이 상태) · Enabled · Active(State 값) · 미인식 값 → unknown. 원문이 있는데 unknown 이 되면 섹션당 notice 1건.
  HBA(storage.hbas[] ← network_adapters.fc_hbas[]) — 바꾸지 않는다: 값은 up/down 둘뿐, Starting · Training 은 notice 없이 down,
    Enabled · Active · 미인식 값은 down + '값 미확정' notice (2026-10-28 사용자 결정 그대로).
  F-01(같은 MAC 포트로 NIC link 보충)은 포트 값이 up 또는 down 하나로 모일 때만 동작한다 — Training 포트로 NIC 를 down 으로 채우지 않는다.
실측 recording(real_dell_r740 · real_lenovo_sr650_v4_01)의 LinkStatus 를 바꿔 재생한다. 18대 미러 · fixture 에 Starting · Training ·
Enabled · Active 는 0건이라 실장비 동작은 미검증이다(MOCK 변형). 기대값은 규칙으로 손으로 적었다(rule 95 R3).
"""
from __future__ import annotations

import copy
import json
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))
sys.path.insert(0, str(REPO / "tests" / "integration"))
for _n in ("ansible", "ansible.module_utils", "ansible.module_utils.basic"):
    sys.modules.setdefault(_n, types.ModuleType(_n))
if not hasattr(sys.modules["ansible.module_utils.basic"], "AnsibleModule"):
    sys.modules["ansible.module_utils.basic"].AnsibleModule = object

import redfish_gather as rg  # noqa: E402
import emulator_harness as H  # noqa: E402
import normalize_chain as NC  # noqa: E402

FIX = REPO / "tests" / "fixtures" / "redfish"


@pytest.fixture(autouse=True)
def _reset():
    rg._reset_notices()
    yield
    rg._reset_notices()


def _rec(name):
    return json.loads((FIX / name / "recording.json").read_text(encoding="utf-8"))


def _replay(name, rec):
    meta = json.loads((FIX / name / "meta.json").read_text(encoding="utf-8")) if (FIX / name / "meta.json").is_file() else {}
    g, n, r = H.make_replayer(rec)
    return H.run_gather(g, n, realm_impl=r, manager_layout=meta.get("manager_layout"), firmware_scope=meta.get("firmware_inventory_scope"))


def _set_link(rec, key, value):
    assert "LinkStatus" in rec[key][1], key
    rec[key][1]["LinkStatus"] = value


def _notes(section):
    return [n["message"] for n in rg.notices() if n["section"] == section]


# ── 일반 매핑 ────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, link, unmapped", [
    ("LinkUp", "up", None), ("Up", "up", None), ("Connected", "up", None),
    ("LinkDown", "down", None), ("Down", "down", None), ("NoLink", "down", None), ("Disconnected", "down", None),
    ("Disabled", "down", None), ("Inactive", "down", None), ("Offline", "down", None),
    ("Starting", "unknown", "Starting"), ("Training", "unknown", "Training"),      # DMTF 전이 상태 (종전 down)
    ("Enabled", "unknown", "Enabled"), ("Active", "unknown", "Active"),            # State 값 (종전 up)
    ("Degraded", "unknown", "Degraded"), ("Link Up", "unknown", "Link Up"),        # 미인식 (종전 원문 소문자)
    (None, "unknown", None), ("", "unknown", None), ("Unknown", "unknown", None), ("null", "unknown", None),
])
def test_network_link_mapping(raw, link, unmapped):
    assert rg._normalize_link_status(raw) == link
    assert rg._link_status_unmapped(raw) == unmapped


# ── HBA 불변: 2026-10-28 판정을 그대로 옮긴 기준 함수와 입력마다 같은지 ──────────────────────────────────────────────────────

_DOWN_20261028 = ("linkdown", "down", "nolink", "disconnected", "disabled", "inactive", "offline", "starting", "training")
_UP_20261028 = ("linkup", "up", "connected", "enabled", "active")   # 당시 일반 매핑의 up (HBA up 은 앞 3개뿐)


def _hba_20261028(pdata):
    """2026-10-28 의 _hba_link_status · _hba_link_missing · _hba_link_unresolved (당시 일반 매핑으로 갈랐다)."""
    if not isinstance(pdata, dict) or "LinkStatus" not in pdata:
        return "down", True, None
    raw = pdata.get("LinkStatus")
    status = "up" if isinstance(raw, str) and raw.strip().lower() in ("linkup", "up", "connected") else "down"
    s = "" if raw is None else str(raw).strip().lower()
    norm = "unknown" if (raw is None or s in ("", "none", "unknown", "null")) else (
        "up" if s in _UP_20261028 else ("down" if s in _DOWN_20261028 else s))
    unresolved = None if (norm == "down" or (norm == "up" and status == "up")) else ("null" if raw is None else str(raw).strip())
    return status, False, unresolved


_HBA_INPUTS = ["LinkUp", "Up", "Connected", " linkup ", "LINKUP", "LinkDown", "Down", "NoLink", "Disconnected", "Disabled",
               "Inactive", "Offline", "Starting", "Training", " TRAINING ", "Enabled", "Active", " active ", "Degraded",
               "Unknown", "none", "null", "", " ", "Link Up", None, 0, 123, True, 1.5, ["LinkUp"], {"x": 1}, "<absent>"]


@pytest.mark.parametrize("raw", _HBA_INPUTS, ids=[repr(x) for x in _HBA_INPUTS])
def test_hba_link_policy_is_unchanged_for_every_input(raw):
    pdata = {"Id": "1"} if raw == "<absent>" else {"LinkStatus": raw}
    now = (rg._hba_link_status(pdata), rg._hba_link_missing(pdata), rg._hba_link_unresolved(pdata))
    assert now == _hba_20261028(pdata)
    assert now[0] in ("up", "down")


# ── 실측 recording 변형: Dell R740 (NIC LinkStatus · 구 NetworkPort LinkStatus) ─────────────────────────────────────────────

NIC = "get::Systems/System.Embedded.1/EthernetInterfaces/"
NETAD = "get::Chassis/System.Embedded.1/NetworkAdapters/"


def test_r740_unchanged_recording_has_no_link_notice():
    res = _replay("real_dell_r740", _rec("real_dell_r740"))
    assert not [m for m in rg.notices() if "링크 상태 값 미확정" in m["message"]]
    assert {n["link_status"] for n in res["data"]["network"]} == {"up", "down"}


def test_r740_transitional_and_state_values_are_unknown_with_one_notice_per_section_and_hba_unchanged():
    rec = _rec("real_dell_r740")
    _set_link(rec, NIC + "NIC.Slot.5-1-1", "Training")                               # 원문 LinkDown
    _set_link(rec, NIC + "NIC.Slot.8-1-1", "Enabled")                                # 원문 LinkDown
    _set_link(rec, NETAD + "FC.Slot.1/NetworkPorts/FC.Slot.1-1", "Training")         # 원문 Down (FC)
    _set_link(rec, NETAD + "FC.Slot.7/NetworkPorts/FC.Slot.7-1", "Enabled")          # 원문 Down (FC)
    _set_link(rec, NETAD + "NIC.Slot.2/NetworkPorts/NIC.Slot.2-2", "Starting")       # 원문 Down (Ethernet)
    res = _replay("real_dell_r740", rec)
    d = res["data"]

    nics = {n["id"]: n["link_status"] for n in d["network"]}
    assert (nics["NIC.Slot.5-1-1"], nics["NIC.Slot.8-1-1"]) == ("unknown", "unknown")
    assert (nics["NIC.Slot.2-1-1"], nics["NIC.Slot.5-2-1"]) == ("up", "down")          # 바꾸지 않은 NIC 는 그대로
    net = [m for m in _notes("network") if "링크 상태 값 미확정" in m]
    assert len(net) == 1 and net[0].startswith("Systems/System.Embedded.1/EthernetInterfaces: ")
    assert sorted(net[0].split(" — ", 1)[1].split(", ")) == ["NIC.Slot.5-1-1=Training", "NIC.Slot.8-1-1=Enabled"]   # 순서는 컬렉션 순서

    ports = {p["port_id"]: p["link_status"] for p in d["network_adapters"]["ports"]}
    assert (ports["FC.Slot.1-1"], ports["FC.Slot.7-1"], ports["NIC.Slot.2-2"]) == ("unknown", "unknown", "unknown")
    assert (ports["FC.Slot.1-2"], ports["NIC.Slot.2-1"]) == ("down", "up")
    port_notes = [m for m in _notes("network_adapters") if "network.ports link_status" in m]
    assert len(port_notes) == 1
    assert sorted(port_notes[0].split(" — ", 1)[1].split(", ")) == [
        "FC.Slot.1/FC.Slot.1-1=Training", "FC.Slot.7/FC.Slot.7-1=Enabled", "NIC.Slot.2/NIC.Slot.2-2=Starting"]

    # HBA: 값은 up/down 둘뿐 — Training 은 notice 없이 down, Enabled 는 down + '값 미확정' (2026-10-28 정책 그대로)
    hbas = {h["port_id"]: h["link_status"] for h in d["network_adapters"]["fc_hbas"]}
    assert hbas == {"FC.Slot.1-1": "down", "FC.Slot.1-2": "down", "FC.Slot.7-1": "down", "FC.Slot.7-2": "down"}
    hba_notes = [m for m in _notes("network_adapters") if "storage.hbas link_status" in m]
    assert hba_notes == ["네트워크 카드 FC.Slot.7: FC 포트 FC.Slot.7-1=Enabled 링크 상태 값 미확정, down 으로 기록 (storage.hbas link_status)"]


# ── F-01 과의 관계: Training 포트로 NIC link 를 채우지 않는다 (real_lenovo_sr650_v4_01 NIC1) ─────────────────────────────────

V4 = "real_lenovo_sr650_v4_01"
V4_PORT = "get::Chassis/1/NetworkAdapters/slot13_0x170000/Ports/2"   # NIC1 MAC EC:E7:A7:22:59:5D 를 가진 유일한 포트 (원문 LinkDown)


def _bundle_links(res):
    ctx = NC.render(NC.raw_collect(res), until="interfaces (bundle)")
    return {i["id"]: i["link_status"] for i in ctx["_rf_norm_interfaces_bundle"]["interfaces"]}


def test_f01_fill_needs_a_settled_port_value():
    rec = _rec(V4)
    assert rec["get::Systems/1/EthernetInterfaces/NIC1"][1].get("LinkStatus") is None
    assert rec[V4_PORT][1]["Ethernet"]["AssociatedMACAddresses"] == ["EC:E7:A7:22:59:5D"]
    assert _bundle_links(_replay(V4, copy.deepcopy(rec)))["NIC1"] == "down"           # 종전 F-01 채움 (불변)

    rg._reset_notices()
    _set_link(rec, V4_PORT, "Training")
    res = _replay(V4, rec)
    assert {p["port_id"]: p["link_status"] for p in res["data"]["network_adapters"]["ports"]
            if p["adapter_id"] == "slot13_0x170000"} == {"1": "up", "2": "unknown"}
    links = _bundle_links(res)
    assert links["NIC1"] == "unknown"                                                  # 종전 Training → down 이면 down 으로 채워졌다
    assert links["NIC2"] == "up"                                                       # 다른 NIC 의 채움은 그대로
