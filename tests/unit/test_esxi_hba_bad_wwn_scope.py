"""ESXi `_e_ext_hba_bad_wwn` — hbas[] 에 남는 vmhba 만 WWN 형식을 본다 (2026-10-19 B-12).

종전 collect_network_extended.yml 은 모든 vmhba 의 port_wwn/node_wwn 을 훑었다 — hbas[] 에 들어가지도 않는 SAS/RAID 어댑터의
SAS 주소(8옥텟 colon-hex 가 아님)로 storage errors[] 에 malformed_wwn 오류가 났다(오탐). 이제 _e_ext_hbas 가 남긴 vmhba(FC/FCoE/iSCSI)
의 이름 집합만 본다 — 분류 조건을 복제하지 않으므로 두 판정이 갈릴 수 없다.

하네스는 test_esxi_partial_failures_c9 의 것 (실제 YAML set_fact 전부를 순서대로 렌더). 실장비 미검증.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "unit"))

from test_esxi_hba_normalize import FC_PORT2, FC_UP, _hbas, _storage_errors  # noqa: E402

EXT = REPO / "esxi-gather" / "tasks" / "collect_network_extended.yml"

# SAS HBA — SAS 주소가 WWN 자리에 온다 (15 hex → 8옥텟 colon-hex 가 아님). RAID — 모듈의 int64 음수 변환.
SAS_BAD = {"device": "vmhba1", "type": "SerialAttachedHba", "driver": "lsi_msgpt3", "model": "LSI SAS3008", "status": "online",
           "node_wwn": "50:01:43:80:1e:8c:3a:b", "port_wwn": None}
RAID_BAD = {"device": "vmhba0", "type": "Block Adapter", "driver": "lsi_mr3", "model": "PERC H740P", "status": "unknown",
            "node_wwn": "-3f:ff:ff:6f:05:e4:d3:c3"}
FC_BAD = dict(FC_UP, port_wwn="-3f:ff:ff:6f:05:e4:d3:c3", node_wwn="20:00:00:90:fa:1b:2c:3")


def test_sas_and_raid_adapters_with_malformed_wwn_and_no_fc_or_iscsi_record_nothing():
    hbas, ctx = _hbas([SAS_BAD, RAID_BAD])
    assert hbas == [] and ctx["_e_ext_hba_bad_wwn"] == []
    assert _storage_errors(ctx) == [] and ctx["_sections_collected_fragment"] == ["network"]


def test_fc_adapter_with_malformed_wwn_is_still_listed_and_recorded():
    hbas, ctx = _hbas([FC_BAD])
    assert hbas[0]["wwpn"] is None and hbas[0]["wwnn"] is None
    assert ctx["_e_ext_hba_bad_wwn"] == ["vmhba2:port_wwn=-3f:ff:ff:6f:05:e4:d3:c3", "vmhba2:node_wwn=20:00:00:90:fa:1b:2c:3"]
    errs = _storage_errors(ctx)
    assert len(errs) == 1 and "cause=malformed_wwn" in errs[0]["detail"] and "count=2" in errs[0]["detail"]


def test_mixed_host_only_the_kept_adapters_are_checked():
    """SAS 의 깨진 주소는 무시, FC 의 깨진 WWN 만 남는다 — 종전엔 SAS 까지 세어 count 가 3 이었다."""
    hbas, ctx = _hbas([SAS_BAD, FC_BAD, RAID_BAD, FC_PORT2])
    assert [h["name"] for h in hbas] == ["vmhba2", "vmhba3"]
    assert ctx["_e_ext_hba_bad_wwn"] == ["vmhba2:port_wwn=-3f:ff:ff:6f:05:e4:d3:c3", "vmhba2:node_wwn=20:00:00:90:fa:1b:2c:3"]
    assert "count=2" in _storage_errors(ctx)[0]["detail"]


def test_sas_malformed_next_to_well_formed_fc_records_nothing():
    hbas, ctx = _hbas([SAS_BAD, FC_UP])
    assert [h["name"] for h in hbas] == ["vmhba2"] and ctx["_e_ext_hba_bad_wwn"] == [] and _storage_errors(ctx) == []


def test_iscsi_adapter_is_kept_so_its_malformed_wwn_counts():
    iscsi = {"device": "vmhba64", "type": "iSCSI", "driver": "iscsi_vmk", "model": "iSCSI Software Adapter", "status": "online", "node_wwn": "abc"}
    hbas, ctx = _hbas([iscsi])
    assert [h["port_type"] for h in hbas] == ["iSCSI"] and ctx["_e_ext_hba_bad_wwn"] == ["vmhba64:node_wwn=abc"]


@pytest.mark.parametrize("details", [[SAS_BAD, FC_BAD, RAID_BAD], [FC_BAD, FC_PORT2], [RAID_BAD], []])
def test_recorded_devices_are_always_a_subset_of_hbas_names(details):
    """불변식: bad_wwn 의 device 는 hbas[].name 밖에 없다 (두 판정이 같은 집합에서 나온다)."""
    hbas, ctx = _hbas(details)
    recorded = {entry.split(":", 1)[0] for entry in ctx["_e_ext_hba_bad_wwn"]}
    assert recorded <= {h["name"] for h in hbas}, (recorded, [h["name"] for h in hbas])


def test_bad_wwn_fact_is_derived_from_the_hbas_fact_in_a_later_task():
    """구조 가드: _e_ext_hba_bad_wwn 은 _e_ext_hbas 보다 뒤 task 에서 _e_ext_hbas[].name 을 읽는다 — 분류 조건(fc/fcoe/iscsi 드라이버 목록)을 복제하지 않는다."""
    block = yaml.safe_load(EXT.read_text(encoding="utf-8"))[0]["block"]
    facts = [(i, k, v) for i, t in enumerate(block) for k, v in (t.get("ansible.builtin.set_fact") or {}).items()]
    (hbas_idx, _, _), = [(i, k, v) for i, k, v in facts if k == "_e_ext_hbas"]
    (bad_idx, _, bad_tpl), = [(i, k, v) for i, k, v in facts if k == "_e_ext_hba_bad_wwn"]
    assert bad_idx > hbas_idx, "같은 set_fact 안에서는 다른 키를 참조할 수 없다"
    assert "_e_ext_hbas" in bad_tpl and "map(attribute='name')" in bad_tpl
    assert "fc_drivers" not in bad_tpl and "iscsi_drivers" not in bad_tpl and "fibre" not in bad_tpl
