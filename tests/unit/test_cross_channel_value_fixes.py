"""채널 간 값 정합 — Redfish 쪽 수정 4건 (2026-10-18): X1 CIMC UUID 바이트 순서 · X2 CPU 정격/터보 · X3 스레드 수 원천 · X9 NIC 모델 폴백.

근거는 같은 물리 서버 2쌍의 교차 대조다 (tests/regression/test_cross_channel_consistency.py — Redfish 크롤 ↔ OS/ESXi live envelope):
  - X1  Cisco C220 M5: CIMC System.UUID B190019F-56CE-4ED4-… ↔ ESXi 9f0190b1-ce56-d44e-… (앞 3필드 바이트 순서). Dell 은 OS 와 같다.
  - X2  cpu.max_speed_mhz 는 정격(base) 인데 Redfish 는 MaxSpeedMHz(터보 최대)를 냈다 — Dell 4000 vs Linux 2400, Cisco 4000 vs ESXi 2195.
  - X3  CIMC 4.1 의 per-processor TotalThreads(22) 는 코어 수다 — ProcessorSummary.LogicalProcessorCount 가 있으면 그것이 정본.
  - X9  Dell R760 NIC.Embedded.1 의 Model null — FirmwareInventory 이름("Broadcom NetXtreme Gigabit Ethernet (BCM5720) - <MAC>")으로 채운다.
normalize_standard.yml 의 실제 식(hardware.uuid · cpu.logical_threads · cpu.max_speed_mhz · cpu.turbo_max_mhz)을 렌더한다.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
import yaml

yaml = pytest.importorskip("yaml")
from jinja2.nativetypes import NativeEnvironment  # noqa: E402

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
from identity_normalizer import normalize_uuid, uuid_byteswap  # noqa: E402

NORM = REPO / "redfish-gather" / "tasks" / "normalize_standard.yml"
ADAPTERS = REPO / "adapters" / "redfish"


def _fragment():
    for task in yaml.safe_load(NORM.read_text(encoding="utf-8")):
        sf = task.get("ansible.builtin.set_fact") if isinstance(task, dict) else None
        if isinstance(sf, dict) and isinstance(sf.get("_data_fragment"), dict) and "hardware" in sf["_data_fragment"]:
            return sf["_data_fragment"]
    raise AssertionError("normalize_standard 의 _data_fragment(hardware) 태스크를 찾지 못했다")


def _render(expr, **ctx):
    env = NativeEnvironment()
    env.filters.update({"normalize_uuid": normalize_uuid, "uuid_byteswap": uuid_byteswap})
    return env.from_string(expr).render(**ctx)


# ── X2: 정격 클럭 원천 ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text, mhz", [
    ("Intel(R) Xeon(R) Platinum 8260 CPU @ 2.40GHz", 2400),
    ("Intel(R) Xeon(R) CPU E5-2699 v4 @ 2.20GHz", 2200),
    ("Intel(R) Xeon(R) Silver 4310 CPU @ 2.10GHz", 2100),
    ("Intel(R) Xeon(R) Gold 6434H Processor", None),
    ("AMD EPYC 7302P 16-Core Processor               ", None),
    ("INTEL(R) XEON(R) GOLD 6530", None),
    (None, None), (42, None),
])
def test_brand_string_base_clock(text, mhz):
    assert rg._brand_base_mhz(text) == mhz


@pytest.mark.parametrize("pdata, mhz", [
    ({"MaxSpeedMHz": 4000, "OperatingSpeedMHz": 2400, "Model": "Intel(R) Xeon(R) Platinum 8260 CPU @ 2.40GHz"}, 2400),          # Dell R740 실측
    ({"MaxSpeedMHz": 4000, "Oem": {"Hpe": {"RatedSpeedMHz": 2100}}, "Model": "Intel(R) Xeon(R) Silver 4310 CPU @ 2.10GHz"}, 2100),  # HPE iLO 실측
    ({"MaxSpeedMHz": 4100, "Oem": {"Hpe": {"RatedSpeedMHz": 3000}}, "Model": "AMD EPYC 7302P 16-Core Processor"}, 3000),         # HPE AMD 실측 — 브랜드에 주파수 없음
    ({"MaxSpeedMHz": 4300, "Oem": {"Lenovo": {"CurrentClockSpeedMHz": 3600}}, "Model": "Intel(R) Xeon(R) 6724P"}, 3600),        # Lenovo XCC 실측
    ({"MaxSpeedMHz": 4100, "BaseSpeedMHz": 3700, "Model": "Intel(R) Xeon(R) Gold 6434H Processor"}, 3700),                      # HPE CSUS RMC 실측
    ({"MaxSpeedMHz": 3700, "OperatingSpeedMHz": 2333, "Model": "Multi-Core Intel(R) Xeon(R) processor 7xxx Series"}, 2333),     # DMTF 목업
    ({"MaxSpeedMHz": 3700, "Model": "Intel(R) Xeon(R) CPU E5-2699 v4 @ 2.20GHz"}, 2200),                                        # Cisco CIMC 실측
    ({"MaxSpeedMHz": 4000, "Model": "AMD EPYC 7763 64-Core Processor"}, None),                                                 # 정격 원천 없음 — 터보를 넣지 않는다
    ({"OperatingSpeedMHz": 2300, "Model": "Intel(R) Xeon(R) Gold 6248R CPU @ 3.00GHz"}, 3000),                                 # 브랜드(정격) 가 현재 클럭보다 앞
    ({"BaseSpeedMHz": 2000, "Oem": {"Hpe": {"RatedSpeedMHz": 2100}}, "Model": "x @ 2.20GHz"}, 2000),                           # 표준 BaseSpeedMHz 가 최우선
    ({"BaseSpeedMHz": "abc", "OperatingSpeedMHz": "2400"}, 2400),                                                              # 숫자 문자열 허용 · 쓰레기 무시
    ({}, None), (None, None),
])
def test_cpu_base_speed_source_order(pdata, mhz):
    assert rg._cpu_base_speed_mhz(pdata) == mhz


def test_gather_processors_emits_base_and_turbo(monkeypatch):
    sysu = "/redfish/v1/Systems/System.Embedded.1"
    routes = {
        rg._p(sysu) + "/Processors": (200, {"Members": [{"@odata.id": sysu + "/Processors/CPU.Socket.1"}]}, None),
        rg._p(sysu) + "/Processors/CPU.Socket.1": (200, {"Id": "CPU.Socket.1", "Model": "Intel(R) Xeon(R) Platinum 8260 CPU @ 2.40GHz",
                                                          "MaxSpeedMHz": 4000, "OperatingSpeedMHz": 2400, "TotalCores": 24, "TotalThreads": 48,
                                                          "ProcessorType": "CPU", "Status": {"State": "Enabled"}}, None),
    }
    monkeypatch.setattr(rg, "_get", lambda ip, path, *a, **kw: routes.get(path, (404, {}, "HTTP 404")))
    procs, errors = rg.gather_processors("10.0.0.1", sysu, "u", "p", 30, False)
    assert errors == []
    assert (procs[0]["speed_mhz"], procs[0]["max_speed_mhz"], procs[0]["total_threads"]) == (2400, 4000, 48)


def test_normalize_cpu_clock_leaves():
    cpu = _fragment()["cpu"]
    cpus = [{"speed_mhz": 2400, "max_speed_mhz": 4000, "total_threads": 48}, {"speed_mhz": 2400, "max_speed_mhz": 4000, "total_threads": 48}]
    assert _render(cpu["max_speed_mhz"], _rf_d_cpus=cpus, _rf_d_system={}) == 2400
    assert _render(cpu["turbo_max_mhz"], _rf_d_cpus=cpus, _rf_d_system={}) == 4000
    assert _render(cpu["turbo_max_mhz"], _rf_d_cpus=[{"speed_mhz": 2400, "total_threads": 48}], _rf_d_system={}) is None, "구 모듈 출력(키 없음)도 죽지 않는다"
    assert _render(cpu["max_speed_mhz"], _rf_d_cpus=[{"speed_mhz": None, "max_speed_mhz": 4000, "total_threads": 48}], _rf_d_system={}) is None, \
        "정격을 모르면 null — 터보를 정격 자리에 넣지 않는다"


# ── X3: 논리 스레드 수 ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("cpus, lpc, expected", [
    ([{"total_threads": 22}, {"total_threads": 22}], 88, 88),      # CIMC 4.1 실측: TotalThreads 는 코어 수 — ProcessorSummary 가 정본
    ([{"total_threads": 48}, {"total_threads": 48}], 96, 96),      # Dell R740 — 둘이 같다
    ([{"total_threads": 22}, {"total_threads": 22}], None, 44),    # LogicalProcessorCount 없음(iLO · XCC) → 종전 합산
    ([{"total_threads": 22}, {"total_threads": 22}], 0, 44),       # 0 은 모르는 값
    ([], 32, 32),                                                  # per-processor 없음(CSUS 파티션) → 요약값
    ([], None, None),
])
def test_logical_threads_prefers_processor_summary(cpus, lpc, expected):
    cpu = _fragment()["cpu"]
    system = {"cpu_summary": {"logical_processor_count": lpc}} if lpc is not None else {"cpu_summary": {}}
    assert _render(cpu["logical_threads"], _rf_d_cpus=cpus, _rf_d_system=system) == expected


# ── A-2 (2026-10-19): adapter 가 LogicalProcessorCount 를 "코어 수" 라고 밝힌 펌웨어(HPE CSUS 3200 RMC — 실측 4노드 Bios HThread=Enabled,
#   LogicalProcessorCount == Count × TotalCores, TotalThreads == 2 × TotalCores)는 per-processor 합이 우선이다. 다른 adapter 는 X3 그대로.
CORES_FLAG = {"vendor_notes": {"processor_summary_logical_count": "cores"}}


@pytest.mark.parametrize("cpus, lpc, adapter, expected", [
    ([{"total_threads": 16}] * 4, 32, CORES_FLAG, 64),             # CSUS node01 실측: 요약 32(코어) → 합 64
    ([{"total_threads": 32}] * 4, 64, CORES_FLAG, 128),            # CSUS node03 실측
    ([], 32, CORES_FLAG, 32),                                      # per-processor 를 못 읽었으면 요약값으로 폴백
    ([{"total_threads": 16}] * 4, 32, {"vendor_notes": {}}, 32),   # 플래그 없음 → X3 그대로(요약 우선)
    ([{"total_threads": 16}] * 4, 32, {}, 32),
])
def test_logical_threads_adapter_flag_cores(cpus, lpc, adapter, expected):
    cpu = _fragment()["cpu"]
    system = {"cpu_summary": {"logical_processor_count": lpc}}
    assert _render(cpu["logical_threads"], _rf_d_cpus=cpus, _rf_d_system=system, _selected_adapter=adapter) == expected


def test_only_scaleup_adapters_declare_cores_flag():
    """플래그는 실측 근거가 있는 CSUS 3200 과, 사용자 지시로 같은 패밀리인 Superdome Flex 두 adapter 에만 있다."""
    flagged = set()
    for p in sorted((REPO / "adapters" / "redfish").glob("*.yml")):
        a = yaml.safe_load(p.read_text(encoding="utf-8"))
        if ((a.get("vendor_notes") or {}).get("processor_summary_logical_count") or "") == "cores":
            flagged.add(a["adapter_id"])
    assert flagged == {"redfish_hpe_csus_3200", "redfish_hpe_superdome_flex"}


# ── X1: UUID 바이트 순서 ───────────────────────────────────────────────────────────────────
CIMC_RAW = "B190019F-56CE-4ED4-A1DD-6571DAAEDAD7"
ESXI_UUID = "9f0190b1-ce56-d44e-a1dd-6571daaedad7"


def test_uuid_is_byteswapped_only_when_the_adapter_declares_smbios_raw():
    uuid_expr = _fragment()["hardware"]["uuid"]
    raw = {"vendor_notes": {"uuid_byte_order": "smbios_raw"}}
    assert _render(uuid_expr, _rf_d_system={"uuid": CIMC_RAW}, _selected_adapter=raw) == ESXI_UUID
    assert _render(uuid_expr, _rf_d_system={"uuid": CIMC_RAW}, _selected_adapter={}) == CIMC_RAW.lower(), "선언 없는 adapter 는 그대로"
    assert _render(uuid_expr, _rf_d_system={"uuid": CIMC_RAW}) == CIMC_RAW.lower(), "_selected_adapter 미정의도 그대로"
    assert _render(uuid_expr, _rf_d_system={"uuid": "4c4c4544-0053-4210-8050-c7c04f4b3534"}, _selected_adapter={"vendor_notes": {}}) == \
        "4c4c4544-0053-4210-8050-c7c04f4b3534", "Dell 실측 — OS 와 같아 바꾸지 않는다"
    assert _render(uuid_expr, _rf_d_system={"uuid": None}, _selected_adapter=raw) is None
    assert _render(uuid_expr, _rf_d_system={}, _selected_adapter=raw) is None


def test_only_the_lab_tested_cimc_adapter_declares_the_byte_order():
    declared = {}
    for p in sorted(ADAPTERS.glob("*.yml")):
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        order = ((doc.get("vendor_notes") or {}).get("uuid_byte_order"))
        if order:
            declared[p.name] = order
    assert declared == {"cisco_cimc.yml": "smbios_raw"}, "실측(C220 M5 CIMC 4.1) 이 있는 adapter 만 — 다른 세대/벤더는 근거 없이 적지 않는다"


# ── X9: NIC 모델 폴백 ──────────────────────────────────────────────────────────────────────
def _netad():
    return {"adapters": [{"id": "NIC.Embedded.1", "model": None}, {"id": "NIC.Embedded.10", "model": None},
                         {"id": "NIC.Slot.2", "model": "BRCM 10GbE 2P 57412S Adptr"}, {"id": "FC.Slot.1", "model": None}],
            "ports": [{"adapter_id": "NIC.Embedded.1", "adapter_model": None, "port_id": "NIC.Embedded.1-1"},
                      {"adapter_id": "NIC.Slot.2", "adapter_model": "BRCM 10GbE 2P 57412S Adptr", "port_id": "NIC.Slot.2-1"}],
            "fc_hbas": [{"adapter_id": "FC.Slot.1", "adapter_model": None, "port_id": "FC.Slot.1-1"}]}


FW = [
    {"id": "Installed-27481-23.61.3__NIC.Embedded.1-1-1", "component": "NIC.Embedded.1-1-1",
     "name": "Broadcom NetXtreme Gigabit Ethernet (BCM5720) - 20:04:0F:FB:11:64", "version": "23.61.3"},
    {"id": "Installed-27481-23.61.3__NIC.Embedded.1-2-1", "component": "NIC.Embedded.1-2-1",
     "name": "Broadcom NetXtreme Gigabit Ethernet (BCM5720) - 20:04:0F:FB:11:65", "version": "23.61.3"},
    {"id": "Installed-9__NIC.Embedded.10-1-1", "component": "NIC.Embedded.10-1-1", "name": "Other Ethernet - AA:BB:CC:DD:EE:FF", "version": "1"},
    {"id": "Installed-104483-16.25.11__FC.Slot.1-1", "component": "FC.Slot.1-1", "name": "QLogic QLE2692 16Gbps Dual Port Fibre Channel Controller", "version": "16.25.11"},
    {"id": "Installed-BIOS", "component": "BIOS.Setup.1-1", "name": "BIOS", "version": "2.1"},
]


def test_adapter_model_is_filled_from_the_matching_firmware_entry():
    rg._reset_notices()
    netad = _netad()
    rg._fill_adapter_models_from_firmware(netad, FW)
    models = {a["id"]: a["model"] for a in netad["adapters"]}
    assert models["NIC.Embedded.1"] == "Broadcom NetXtreme Gigabit Ethernet (BCM5720)", "포트 MAC 접미는 뗀다"
    assert models["NIC.Embedded.10"] == "Other Ethernet", "NIC.Embedded.1 의 하위로 오인하지 않는다 ('-' 구분)"
    assert models["NIC.Slot.2"] == "BRCM 10GbE 2P 57412S Adptr", "이미 있는 Model 은 건드리지 않는다"
    assert models["FC.Slot.1"] == "QLogic QLE2692 16Gbps Dual Port Fibre Channel Controller"
    assert netad["ports"][0]["adapter_model"] == "Broadcom NetXtreme Gigabit Ethernet (BCM5720)"
    assert netad["ports"][1]["adapter_model"] == "BRCM 10GbE 2P 57412S Adptr"
    assert netad["fc_hbas"][0]["adapter_model"] == "QLogic QLE2692 16Gbps Dual Port Fibre Channel Controller"
    msgs = [n["message"] for n in rg.notices() if n["section"] == "network_adapters"]
    assert len(msgs) == 3 and all("펌웨어 목록 이름" in m for m in msgs)


def test_no_matching_firmware_leaves_model_null_without_notice():
    rg._reset_notices()
    netad = {"adapters": [{"id": "NIC.Mezzanine.1", "model": None}], "ports": [], "fc_hbas": []}
    rg._fill_adapter_models_from_firmware(netad, FW)
    assert netad["adapters"][0]["model"] is None and rg.notices() == []


def test_fill_is_robust_to_odd_inputs():
    rg._fill_adapter_models_from_firmware(None, FW)
    rg._fill_adapter_models_from_firmware({"adapters": "x"}, FW)
    rg._fill_adapter_models_from_firmware({"adapters": [{"id": None, "model": None}, "junk"]}, [None, {"id": 1, "name": "n"}, {"id": "a__b"}])
    netad = {"adapters": [{"id": 7, "model": None}]}
    rg._fill_adapter_models_from_firmware(netad, [{"id": "7", "name": "Seven - 00:11:22:33:44:55"}])
    assert netad["adapters"][0]["model"] == "Seven", "정수 Id 도 문자열로 맞춘다"
