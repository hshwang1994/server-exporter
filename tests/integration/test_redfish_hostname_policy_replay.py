"""Redfish hostname 정책 — 실장비 캡처 재생으로 수집부터 최종 봉투 hostname 까지 (2026-10-15).

한 줄로 잇는다 (네트워크 0):
    redfish_gather.py 녹화본 재생(emulator_harness)
    → adapter 재선택 (실 adapter_common 점수, reselect_adapter.yml 과 같은 인증 후 facts)
    → normalize_standard.yml 의 hostname 태스크 2개 ("system hostname source" · "system hostname / fqdn")
    → build_output.yml 의 hostname · hostname_source 식.

사례
    - real_hpe_csus3200 원본: 2026-06 사이트 node01 (Partition0.HostName=null, RMC=RMC7CA62A413692)
    - 사용자 사례 변형 (합성): 같은 녹화본에 2026-10-15 사용자 사이트 실측값을 대입한다 —
      Systems/Partition0.HostName=svu703327-net7, Managers/RMC NetworkProtocol · EthernetInterfaces/1 HostName=ycgsfaibap01
    - RMC 이름 없음 변형 (합성): RMC 이름을 비우면 Partition 이름으로 대체한다
    - real_dell_r740 · real_hpe_dl380 · real_lenovo_sr650: 종전 값 그대로 (CSUS 외 영향 0)
"""
from __future__ import annotations

import copy
import glob
import json
import re
import sys
from pathlib import Path

import pytest
import yaml
from jinja2.nativetypes import NativeEnvironment

import emulator_harness as H

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "module_utils"))
from adapter_common import adapter_matches, adapter_score, load_vendor_aliases  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "redfish"
NORMALIZE = REPO / "redfish-gather" / "tasks" / "normalize_standard.yml"
BUILD_OUTPUT = REPO / "common" / "tasks" / "normalize" / "build_output.yml"
ALIASES = load_vendor_aliases(str(REPO / "common" / "vars" / "vendor_aliases.yml"))
ADAPTERS = [yaml.safe_load(Path(p).read_text(encoding="utf-8"))
            for p in sorted(glob.glob(str(REPO / "adapters" / "redfish" / "*.yml")))]
ENV = NativeEnvironment()


def _set_fact(name_sub):
    for t in yaml.safe_load(NORMALIZE.read_text(encoding="utf-8")):
        if isinstance(t, dict) and name_sub in str(t.get("name", "")):
            return t["ansible.builtin.set_fact"]
    raise AssertionError(f"normalize_standard.yml: '{name_sub}' 태스크 없음")


def _build_output_exprs():
    text = BUILD_OUTPUT.read_text(encoding="utf-8")
    h = re.search(r"_out_hostname:\s*>-\n(.*?)\n\s*_out_hostname_source:", text, re.S)
    s = re.search(r"_out_hostname_source:\s*>-\n(.*?)\n\n- name:", text, re.S)
    assert h and s, "build_output.yml 의 hostname 식 추출 실패"
    return ENV.from_string(h.group(1).strip()), ENV.from_string(s.group(1).strip())


T_HOST, T_SRC = _build_output_exprs()
SRC_TASK = _set_fact("system hostname source")
ID_TASK = _set_fact("system hostname / fqdn")


def _select_adapter(result):
    """reselect_adapter.yml 의 인증 후 facts(vendor · System model · BMC firmware)로 실 점수 선택."""
    data = result["data"]
    facts = {"vendor": result["vendor"],
             "model": (data.get("system") or {}).get("model") or "",
             "firmware": (data.get("bmc") or {}).get("firmware_version") or ""}
    scored = [(adapter_score(a, facts, ALIASES), a) for a in ADAPTERS if adapter_matches(a, facts, ALIASES)]
    scored = [x for x in scored if x[0] > -9999]
    scored.sort(key=lambda x: x[0], reverse=True)
    assert scored, f"선택되는 adapter 없음: {facts}"
    return scored[0][1]


def _replay(case, patch=None):
    recording = json.loads((FIXTURES / case / "recording.json").read_text(encoding="utf-8"))
    if patch:
        recording = copy.deepcopy(recording)
        patch(recording)
    meta = FIXTURES / case / "meta.json"
    meta_d = json.loads(meta.read_text(encoding="utf-8")) if meta.is_file() else {}
    get_impl, noauth_impl, realm_impl = H.make_replayer(recording)
    # 2026-10-19 (A-9): meta.json 의 firmware_inventory_scope(CSUS 만 complex_only)도 넘긴다 — 운영 모듈 인자와 같은 조건으로 재생
    return H.run_gather(get_impl, noauth_impl, realm_impl=realm_impl, manager_layout=meta_d.get("manager_layout"),
                        firmware_scope=meta_d.get("firmware_inventory_scope"))


def _envelope_hostname(result, adapter):
    """normalize 태스크 2개 → system fragment → build_output 식. 반환 (hostname, source, system.hostname, system.fqdn)."""
    ctx = {"_rf_d_system": result["data"].get("system") or {}, "_rf_d_bmc": result["data"].get("bmc"),
           "_selected_adapter": adapter}
    ctx["_rf_sys_hostname_raw"] = ENV.from_string(SRC_TASK["_rf_sys_hostname_raw"]).render(**ctx)
    short = ENV.from_string(ID_TASK["_rf_sys_hostname_short"]).render(**ctx)
    fqdn = ENV.from_string(ID_TASK["_rf_sys_fqdn"]).render(**ctx)
    merged = {"system": {"hostname": short, "fqdn": fqdn}, "bmc": result["data"].get("bmc")}
    return T_HOST.render(_merged_data=merged), T_SRC.render(_merged_data=merged), short, fqdn


def _set_body(recording, key, **fields):
    assert key in recording, f"녹화본에 {key} 없음"
    recording[key][1].update(fields)


def _user_site(recording):
    _set_body(recording, "get::Systems/Partition0", HostName="svu703327-net7")
    _set_body(recording, "get::Managers/RMC/NetworkProtocol", HostName="ycgsfaibap01")
    _set_body(recording, "get::Managers/RMC/EthernetInterfaces/1", HostName="ycgsfaibap01")


def _no_rmc_name(recording):
    _set_body(recording, "get::Systems/Partition0", HostName="svu703327-net7")
    _set_body(recording, "get::Managers/RMC/NetworkProtocol", HostName=None, FQDN=None)
    _set_body(recording, "get::Managers/RMC/EthernetInterfaces/1", HostName=None, FQDN=None)


@pytest.mark.integration
class TestCsusHostnamePolicyReplay:
    def test_csus_capture_selects_csus_adapter_with_bmc_first(self):
        adapter = _select_adapter(_replay("real_hpe_csus3200"))
        assert adapter["adapter_id"] == "redfish_hpe_csus_3200"
        assert adapter["vendor_notes"]["hostname_priority"] == "bmc_first"

    def test_user_site_case_uses_rmc_name(self):
        result = _replay("real_hpe_csus3200", _user_site)
        host, src, short, fqdn = _envelope_hostname(result, _select_adapter(result))
        assert (host, src, short, fqdn) == ("ycgsfaibap01", "system", "ycgsfaibap01", None)
        # 요구 4: 파티션별 원본 유지 (모듈 산출 — normalize 는 multi_node 를 그대로 통과시킨다)
        assert result["multi_node"]["partitions"][0]["system"]["hostname"] == "svu703327-net7"
        assert result["data"]["system"]["hostname"] == "svu703327-net7"
        # 요구 5: RMC 정보 유지
        bmc = result["data"]["bmc"]
        assert (bmc["dns_name"], bmc["network_hostname"]) == ("ycgsfaibap01", "ycgsfaibap01")
        mgr = result["multi_node"]["managers"][0]["bmc"]
        assert (mgr["dns_name"], mgr["network_hostname"]) == ("ycgsfaibap01", "ycgsfaibap01")

    def test_rmc_name_missing_falls_back_to_partition(self):
        result = _replay("real_hpe_csus3200", _no_rmc_name)
        assert result["data"]["bmc"]["network_hostname"] is None
        host, src, short, fqdn = _envelope_hostname(result, _select_adapter(result))
        assert (host, src, short, fqdn) == ("svu703327-net7", "system", "svu703327-net7", None)

    def test_original_capture_node01(self):
        result = _replay("real_hpe_csus3200")
        host, src, short, fqdn = _envelope_hostname(result, _select_adapter(result))
        assert (host, src, short, fqdn) == ("RMC7CA62A413692", "system", "RMC7CA62A413692", None)
        assert result["multi_node"]["partitions"][0]["system"]["hostname"] is None


@pytest.mark.integration
@pytest.mark.parametrize("case,host,src", [
    ("real_dell_r740", "DELL01", "system"),
    ("real_hpe_dl380", "ILOSGHD3KHHRP", "bmc"),
    ("real_lenovo_sr650", "XCC-7DGD-J902E57T", "bmc"),
])
def test_other_vendors_unchanged(case, host, src):
    result = _replay(case)
    adapter = _select_adapter(result)
    assert "hostname_priority" not in (adapter.get("vendor_notes") or {})
    got_host, got_src, _short, _fqdn = _envelope_hostname(result, adapter)
    assert (got_host, got_src) == (host, src)


def test_only_csus_adapter_sets_hostname_priority():
    found = {a["adapter_id"]: (a.get("vendor_notes") or {}).get("hostname_priority")
             for a in ADAPTERS if (a.get("vendor_notes") or {}).get("hostname_priority")}
    assert found == {"redfish_hpe_csus_3200": "bmc_first"}
