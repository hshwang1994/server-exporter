"""같은 물리 서버를 두 채널로 수집한 결과가 **같아야 할 값**에서 같은가 (2026-10-18 — 채널 간 값 정합 전수조사).

쌍 (시리얼로 같은 장비임을 확인):
  - Cisco C220 M5 FCH2116V1V0 : Redfish 크롤 tests/reference/redfish/cisco/10_100_15_2 ↔ ESXi esxi02 live envelope (2026-09-03)
  - Dell R760 GSBPK54         : Redfish 크롤 tests/reference/redfish/dell/10_100_15_34 ↔ Linux r760-6 live envelope (2026-09-03)
Redfish 쪽은 전수 크롤을 recording 으로 바꿔 모듈을 오프라인 재생하고(네트워크 0), hardware.uuid · cpu.* 는 normalize_standard.yml 의
실제 식을 그 adapter 로 렌더한다. 의미가 달라서 다른 값(network.adapters 개수 · DIMM locator · fqdn · 메모리 total 기준 · NIC 펌웨어 표기)은
단언하지 않는다 — 기록만 한다(사용자 결정 2026-10-18). 같아야 하는데 다른 값은 버그다 (X1 uuid · X2 정격 클럭 · X3 스레드 · hbas WWPN).

알려진 펌웨어 한계(단언에서 제외 · 문서 docs/contract/03-fields.md):
  - CIMC 4.1 은 ProcessorSummary.LogicalProcessorCount 가 없고 per-processor TotalThreads 가 코어 수(22)라 Redfish logical_threads 44 vs ESXi 88.
  - CIMC 는 카드 2장의 vHBA 4개를 정의하지만 ESXi 는 카드 1장의 fnic 2개만 열거한다 — hbas 는 ESXi ⊆ Redfish 로 본다.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
from jinja2.nativetypes import NativeEnvironment  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "integration"))
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))
sys.path.insert(0, str(REPO / "filter_plugins"))
for _n in ("ansible", "ansible.module_utils", "ansible.module_utils.basic"):
    sys.modules.setdefault(_n, types.ModuleType(_n))
if not hasattr(sys.modules["ansible.module_utils.basic"], "AnsibleModule"):
    sys.modules["ansible.module_utils.basic"].AnsibleModule = object

import emulator_harness as H  # noqa: E402
from identity_normalizer import normalize_uuid, uuid_byteswap  # noqa: E402
from serial_normalizer import normalize_os_serial  # noqa: E402

CRAWL = REPO / "tests" / "reference" / "redfish"
LIVE = REPO / "tests" / "evidence" / "2026-09-03-live"
NORM = REPO / "redfish-gather" / "tasks" / "normalize_standard.yml"
ADAPTERS = REPO / "adapters" / "redfish"

PAIRS = [
    pytest.param(("cisco/10_100_15_2", "build195_esxi02_10.100.64.2.json", "cisco_cimc.yml"), id="cisco-c220-esxi02"),
    pytest.param(("dell/10_100_15_34", "build196_r760_baremetal_10.100.64.96.json", "dell_idrac9.yml"), id="dell-r760-linux"),
]


def _fragment():
    for task in yaml.safe_load(NORM.read_text(encoding="utf-8")):
        sf = task.get("ansible.builtin.set_fact") if isinstance(task, dict) else None
        if isinstance(sf, dict) and isinstance(sf.get("_data_fragment"), dict) and "hardware" in sf["_data_fragment"]:
            return sf["_data_fragment"]
    raise AssertionError("normalize_standard _data_fragment(hardware) 미발견")


def _render(expr, **ctx):
    env = NativeEnvironment()
    env.filters.update({"normalize_uuid": normalize_uuid, "uuid_byteswap": uuid_byteswap, "normalize_os_serial": normalize_os_serial})
    return env.from_string(expr).render(**ctx)


def _cpu_only(procs):
    return [p for p in (procs or []) if isinstance(p, dict) and str(p.get("processor_type") or "").strip().upper() in ("CPU", "CORE", "")]


@pytest.fixture(params=PAIRS)
def pair(request):
    crawl_rel, live_name, adapter_name = request.param
    crawl_dir, live_path, adapter_path = CRAWL / crawl_rel, LIVE / live_name, ADAPTERS / adapter_name
    for p in (crawl_dir, live_path, adapter_path):
        if not p.exists():
            pytest.skip(f"{p.relative_to(REPO)} 없음")
    rec = H.make_crawl_recording(crawl_dir)
    get_impl, noauth_impl, realm_impl = H.make_replayer(rec)
    result = H.run_gather(get_impl, noauth_impl, realm_impl=realm_impl)
    live = json.loads(live_path.read_text(encoding="utf-8"))
    adapter = yaml.safe_load(adapter_path.read_text(encoding="utf-8")) or {}
    frag = _fragment()
    system = result["data"]["system"] or {}
    cpus = _cpu_only(result["data"].get("processors"))
    redfish = {
        "serial": _render(frag["hardware"]["serial"], _rf_d_system=system),
        "uuid": _render(frag["hardware"]["uuid"], _rf_d_system=system, _selected_adapter=adapter),
        "vendor": system.get("manufacturer"),
        "model": system.get("model"),
        "sockets": len(cpus) or None,
        "cores_physical": sum(int(p.get("total_cores") or 0) for p in cpus) or None,
        "logical_threads": _render(frag["cpu"]["logical_threads"], _rf_d_cpus=cpus, _rf_d_system=system),
        "max_speed_mhz": _render(frag["cpu"]["max_speed_mhz"], _rf_d_cpus=cpus, _rf_d_system=system),
        "turbo_max_mhz": _render(frag["cpu"]["turbo_max_mhz"], _rf_d_cpus=cpus, _rf_d_system=system),
        "hbas": (result["data"].get("network_adapters") or {}).get("fc_hbas") or [],
        "has_lpc": bool((system.get("cpu_summary") or {}).get("logical_processor_count")),
    }
    return request.param[0], redfish, live, result


def test_redfish_replay_of_the_crawl_succeeds(pair):
    label, redfish, live, result = pair
    assert result["status"] in ("success", "partial"), (label, result["status"], result.get("failed_sections"))
    assert redfish["serial"] and live["data"]["hardware"]["serial"], "시리얼이 있어야 같은 장비인지 확인할 수 있다"


def test_same_server_has_the_same_serial(pair):
    label, redfish, live, _ = pair
    assert redfish["serial"] == live["data"]["hardware"]["serial"], (label, redfish["serial"], live["data"]["hardware"]["serial"])


def test_same_server_has_the_same_uuid_after_normalize(pair):
    """X1: CIMC 는 SMBIOS 원시 바이트 순서 — adapter 선언(uuid_byte_order) 으로 앞 3필드를 바꿔 OS/ESXi 와 같아진다. Dell 은 원래 같다."""
    label, redfish, live, _ = pair
    assert redfish["uuid"] == live["data"]["hardware"]["uuid"], (label, redfish["uuid"], live["data"]["hardware"]["uuid"])
    assert redfish["uuid"] == live["correlation"]["system_uuid"]


def test_same_server_has_the_same_vendor_sockets_and_cores(pair):
    label, redfish, live, _ = pair
    cpu = live["data"]["cpu"]
    assert (redfish["sockets"], redfish["cores_physical"]) == (cpu["sockets"], cpu["cores_physical"]), (label, redfish, cpu)
    assert (redfish["vendor"] or "").split()[0].lower() == (live["data"]["hardware"]["vendor"] or "").split()[0].lower(), (label, redfish["vendor"], live["data"]["hardware"]["vendor"])


def test_base_clock_matches_within_one_percent(pair):
    """X2: Redfish 는 MaxSpeedMHz(터보)를 정격 자리에 냈다 — Dell 4000 vs 2400, Cisco 4000 vs 2195. ESXi cpuInfo.hz 는 반올림이라 1% 허용."""
    label, redfish, live, _ = pair
    live_mhz = live["data"]["cpu"]["max_speed_mhz"]
    assert redfish["max_speed_mhz"] is not None and live_mhz, (label, redfish["max_speed_mhz"], live_mhz)
    assert abs(redfish["max_speed_mhz"] - live_mhz) <= max(1, live_mhz // 100), (label, redfish["max_speed_mhz"], live_mhz)


def test_turbo_clock_matches_within_five_percent_when_both_channels_have_it(pair):
    """X2: 터보 최대는 BMC 가 스펙 시트 값(iDRAC MaxSpeedMHz 4000), Linux 는 cpufreq/MSR 값(lscpu 'CPU max MHz' 4100)을 내 원천 정밀도가
    다르다 — 같은 뜻이라 5% 안에서 같아야 하고(정격 2400 이 여기 들어오면 잡힌다), 더 좁게는 맞출 수 없다(기록)."""
    label, redfish, live, _ = pair
    live_turbo = live["data"]["cpu"].get("turbo_max_mhz")
    if live_turbo is None:
        pytest.skip(f"{label}: 이 OS 채널은 turbo_max_mhz 를 내지 않는다 (ESXi API 미제공)")
    assert redfish["turbo_max_mhz"] is not None, (label, "Redfish 가 MaxSpeedMHz 를 냈다면 turbo_max_mhz 가 있어야 한다")
    assert abs(redfish["turbo_max_mhz"] - live_turbo) <= live_turbo * 5 // 100, (label, redfish["turbo_max_mhz"], live_turbo)
    assert redfish["turbo_max_mhz"] > redfish["max_speed_mhz"], (label, "터보 최대는 정격보다 크다")


def test_logical_threads_match_when_the_bmc_reports_a_summary_count(pair):
    """X3: ProcessorSummary.LogicalProcessorCount 가 있는 BMC(Dell)는 OS 와 같아야 한다. 없는 BMC(CIMC 4.1)는 TotalThreads 합이 코어 수라
    ESXi 보다 작다 — 펌웨어 한계로 기록만 한다(크게 나오면 버그)."""
    label, redfish, live, _ = pair
    live_threads = live["data"]["cpu"]["logical_threads"]
    if redfish["has_lpc"]:
        assert redfish["logical_threads"] == live_threads, (label, redfish["logical_threads"], live_threads)
    else:
        assert redfish["logical_threads"] is not None and redfish["logical_threads"] <= live_threads, (label, redfish["logical_threads"], live_threads)


def test_os_hbas_are_a_subset_of_redfish_hbas_by_wwpn(pair):
    """논리(OS/ESXi) HBA 는 물리(Redfish) HBA 의 부분집합이다 — WWPN 으로 맞춘다. 두 채널 모두 1 항목 = 물리 FC 포트 1개."""
    label, redfish, live, _ = pair
    live_wwpns = {h["wwpn"] for h in (live["data"]["storage"].get("hbas") or []) if h.get("wwpn")}
    redfish_wwpns = {h["wwpn"] for h in redfish["hbas"] if h.get("wwpn")}
    assert live_wwpns <= redfish_wwpns, (label, sorted(live_wwpns - redfish_wwpns))
    assert len(redfish_wwpns) == len(redfish["hbas"]), (label, "Redfish 항목마다 WWPN 이 있어야 한다", redfish["hbas"])


def test_hba_link_status_uses_only_the_canonical_values(pair):
    label, redfish, live, _ = pair
    for h in redfish["hbas"] + list(live["data"]["storage"].get("hbas") or []):
        assert h.get("link_status") in ("up", "down"), (label, h)
