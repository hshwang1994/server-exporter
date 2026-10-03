"""Windows storage — gather_storage.yml 의 *실제* set_fact 템플릿 렌더 회귀 (2026-10-03, C3/C4).

PowerShell 이 등록하는 결과 모양 그대로(`_w_disk_raw.stdout_lines` = 디스크당 압축 JSON 1줄,
`_w_hba_raw.stdout` = JSON 객체 1개)를 합성해 task YAML 에서 꺼낸 템플릿으로 렌더한다.
Python mirror 가 아니라 production 표현식을 직접 검증한다 (test_windows_cpu_summary_collapse_r17 패턴).

고정하는 계약
-------------
C4 physical_disks
  - BusType / MediaType / HealthStatus 의 입력 형태(UInt16 / Int32 / 숫자 문자열 / 표시 문자열) 정규화는
    PowerShell 책임이다. 그 실제 실행은 test_windows_storage_powershell_static.py 가 맡는다.
    여기서는 그 결과 JSON 이 normalize 단계를 지나도 값과 대소문자가 그대로인지, 그리고
    미분류 BusType 처리 계약을 본다.
  - 닫힌 enum 에 대응이 없는 BusType 은 protocol=null, errors[] 정확히 1건(section=storage,
    detail 에 bus_type_raw=[...]). 섹션은 collected 그대로라 status 는 바뀌지 않는다 (시나리오 B).
  - Win32_DiskDrive.InterfaceType 보조 판정이 protocol 을 채운 디스크는 오류를 만들지 않는다.
  - 실장비 10.100.64.120 (build192) 의 physical_disks / summary 와 같은 결과.
C3 hbas
  - 어댑터와 매칭되지 않은 포트는 model/vendor/driver/firmware=null. 첫 번째 어댑터 값을 빌리지 않는다.
  - ConnectionType 은 숫자(1=Fibre Channel, 2=iSCSI)와 문자열을 모두 인식하고 출력 값은 종전과 같다.
  - OperationalStatus 는 MSFT_InitiatorPort ValueMap (2 Operational / 6 Link Down / 7 Port Error) 대로.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
pytest.importorskip("jinja2")
from jinja2.nativetypes import NativeEnvironment  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "filter_plugins"))
from identity_normalizer import normalize_wwn  # noqa: E402

STOR_YML = REPO / "os-gather" / "tasks" / "windows" / "gather_storage.yml"
EVIDENCE_120 = REPO / "tests" / "evidence" / "2026-09-03-live" / "build192_win2022_10.100.64.120.json"
FIELD_DICT = REPO / "schema" / "field_dictionary.yml"

UNMAPPED_MSG = "일부 디스크의 연결 인터페이스 종류를 분류하지 못해 해당 항목을 비워 두었습니다."
STORAGE_FAILED_MSG = "스토리지 정보 수집에 실패했습니다. 대상 상태와 수집 로그를 확인하세요."

PROTOCOL_ENUM = yaml.safe_load(FIELD_DICT.read_text(encoding="utf-8"))["fields"][
    "storage.physical_disks[].protocol"]["enum"]


# ---------------------------------------------------------------------------
# 렌더 하네스
# ---------------------------------------------------------------------------
def _bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "on")


def _regex_replace(value, pattern="", replacement="", ignorecase=False, multiline=False):
    flags = (re.I if ignorecase else 0) | (re.M if multiline else 0)
    return re.sub(pattern, replacement, str(value), flags=flags)


def _env():
    env = NativeEnvironment()
    env.filters["from_json"] = json.loads
    env.filters["bool"] = _bool
    env.filters["regex_replace"] = _regex_replace
    env.filters["normalize_wwn"] = normalize_wwn
    return env


def _render(tmpl, ctx):
    if not isinstance(tmpl, str):
        return tmpl
    return _env().from_string(tmpl).render(**ctx)


def run_storage(disks=(), volumes=(), hba=None, ib=None, disk_rc=0):
    """PowerShell 등록 결과 → gather_storage.yml 의 set_fact 체인(파일 순서) → fragment."""
    ctx = {
        "_w_vol_raw": {"stdout_lines": [json.dumps(v) for v in volumes], "rc": 0},
        "_w_disk_raw": {"stdout_lines": [json.dumps(d) for d in disks], "rc": disk_rc},
        "_w_hba_raw": {"stdout": json.dumps(hba) if hba is not None else ""},
        "_w_ib_raw": {"stdout": json.dumps(ib) if ib is not None else ""},
    }
    frag = None
    for task in yaml.safe_load(STOR_YML.read_text(encoding="utf-8")):
        sf = (task or {}).get("ansible.builtin.set_fact") if isinstance(task, dict) else None
        if not isinstance(sf, dict):
            continue
        if "_data_fragment" in sf:
            frag = sf
            continue
        # 같은 set_fact 안의 변수끼리는 서로의 새 값을 보지 못한다 (Ansible 의미) — 태스크 전 ctx 로 렌더
        ctx.update({k: _render(v, ctx) for k, v in sf.items()})
    assert frag is not None, "build fragment 태스크 미발견"
    return {
        "storage": {k: _render(v, ctx) for k, v in frag["_data_fragment"]["storage"].items()},
        "errors": _render(frag["_errors_fragment"], ctx),
        "collected": _render(frag["_sections_collected_fragment"], ctx),
        "failed": _render(frag["_sections_failed_fragment"], ctx),
    }


def disk(i, *, protocol, media="HDD", health="OK", total=1000204886016, bus_type_raw=None,
         model="DISK MODEL", serial=None, wwn=None, is_os=False):
    """physical disks win_shell 이 디스크마다 출력하는 JSON 한 줄 (ConvertTo-Json -Compress)."""
    return {"device": f"\\\\.\\PHYSICALDRIVE{i}", "model": model, "serial": serial, "wwn": wwn,
            "total": total, "media": media, "protocol": protocol, "health": health,
            "is_os_disk": is_os, "bus_type_raw": bus_type_raw}


# ═══════════════════════════════════════════════════════════════════════════
# C4 — physical_disks protocol / media_type / health
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("protocol", PROTOCOL_ENUM)
def test_enum_protocol_passes_through_unchanged(protocol):
    out = run_storage([disk(0, protocol=protocol)])
    assert out["storage"]["physical_disks"][0]["protocol"] == protocol
    assert out["errors"] == []
    assert out["collected"] == ["storage"] and out["failed"] == []


def test_unmapped_bus_types_yield_null_protocol_and_exactly_one_error():
    """BusType 2(ATAPI) / 16(Storage Spaces) 는 닫힌 enum 에 대응이 없다 → null + 오류 1건."""
    disks = [disk(0, protocol=None, bus_type_raw=2),
             disk(1, protocol=None, bus_type_raw=16),
             disk(2, protocol=None, bus_type_raw=16),
             disk(3, protocol="SATA")]
    out = run_storage(disks)
    assert [d["protocol"] for d in out["storage"]["physical_disks"]] == [None, None, None, "SATA"]
    assert len(out["errors"]) == 1, out["errors"]
    err = out["errors"][0]
    assert err["section"] == "storage"
    assert err["message"] == UNMAPPED_MSG
    assert "bus_type_raw=[2,16]" in err["detail"], err["detail"]
    # 데이터는 수집됐다 — 섹션 status 는 그대로 (errors[] 는 status 를 바꾸지 않는다, 시나리오 B)
    assert out["collected"] == ["storage"] and out["failed"] == []


def test_unmapped_display_name_is_kept_verbatim_in_detail():
    """Storage 모듈 표시 문자열("Spaces", "UFS") 은 원문 그대로 근거로 남는다."""
    out = run_storage([disk(0, protocol=None, bus_type_raw="Spaces"),
                       disk(1, protocol=None, bus_type_raw="UFS")])
    assert len(out["errors"]) == 1
    assert "bus_type_raw=[Spaces,UFS]" in out["errors"][0]["detail"]


def test_interface_type_fallback_classified_disk_raises_no_error():
    """BusType 3(ATA) 은 enum 대응이 없지만 Win32_DiskDrive.InterfaceType 'IDE' 가 채운다 (종전 출력 유지)."""
    out = run_storage([disk(0, protocol="IDE", bus_type_raw=3)])
    assert out["storage"]["physical_disks"][0]["protocol"] == "IDE"
    assert out["errors"] == []


def test_zero_size_disk_is_not_reported():
    """출력에서 빠지는 디스크(용량 0) 의 BusType 은 오류 근거가 아니다."""
    out = run_storage([disk(0, protocol=None, bus_type_raw=16, total=0), disk(1, protocol="SAS")])
    assert [d["protocol"] for d in out["storage"]["physical_disks"]] == ["SAS"]
    assert out["errors"] == []


def test_line_without_bus_type_raw_key_is_tolerated():
    """bus_type_raw 키가 없는 줄(BusType 미관측) 도 렌더된다 — 오류를 지어내지 않는다."""
    d = disk(0, protocol=None)
    d.pop("bus_type_raw")
    out = run_storage([d])
    assert out["storage"]["physical_disks"][0]["protocol"] is None
    assert out["errors"] == []


def test_nothing_collected_keeps_only_the_existing_failure_entry():
    out = run_storage([], [])
    assert out["collected"] == [] and out["failed"] == ["storage"]
    assert [e["message"] for e in out["errors"]] == [STORAGE_FAILED_MSG]


@pytest.mark.parametrize("media,health", [("SSD", "OK"), ("HDD", "Warning"),
                                          ("SCM", "Critical"), (None, None)])
def test_media_type_and_health_pass_through(media, health):
    out = run_storage([disk(0, protocol="NVMe", media=media, health=health)])
    d = out["storage"]["physical_disks"][0]
    assert (d["media_type"], d["health"]) == (media, health)


def test_unmapped_message_follows_section_message_quality_rules():
    """common/vars/section_messages.yml 머리말 규칙: 숫자 / 영문 enum / 긴 대시 / 가운데점 금지."""
    assert not re.search(r"[0-9A-Za-z]", UNMAPPED_MSG)
    assert "—" not in UNMAPPED_MSG and "·" not in UNMAPPED_MSG
    assert UNMAPPED_MSG.endswith("다.")
    text = STOR_YML.read_text(encoding="utf-8")
    assert f"'message': '{UNMAPPED_MSG}'" in text, "production 문장이 테스트 기대값과 다르다"


def _evidence_120():
    return json.loads(EVIDENCE_120.read_text(encoding="utf-8"))["data"]["storage"]


def ps_lines_like_120():
    """build192 (10.100.64.120, Windows Server 2022 VM) 의 디스크 2개를 만든 PowerShell 출력 모양.

    Get-PhysicalDisk 표시 문자열 경로(BusType "SAS" / MediaType "HDD" / HealthStatus "Healthy")
    의 결과다. 용량은 total_mb=102398 이 나오는 바이트 값.
    """
    total = 102398 * 1048576 + 524288
    return [
        {"device": "\\\\.\\PHYSICALDRIVE1", "model": "VMware Virtual disk SCSI Disk Device",
         "serial": "6000c295c31a6c4817cc54edfa38c1b6", "wwn": "6000C295C31A6C4817CC54EDFA38C1B6",
         "total": total, "media": "HDD", "protocol": "SAS", "health": "OK", "is_os_disk": False,
         "bus_type_raw": None},
        {"device": "\\\\.\\PHYSICALDRIVE0", "model": "VMware Virtual disk SCSI Disk Device",
         "serial": "6000c291a8a27597a22732589449427c", "wwn": "6000C291A8A27597A22732589449427C",
         "total": total, "media": "HDD", "protocol": "SAS", "health": "OK", "is_os_disk": True,
         "bus_type_raw": None},
    ]


def test_real_host_120_output_is_identical():
    out = run_storage(ps_lines_like_120())
    ev = _evidence_120()
    assert out["storage"]["physical_disks"] == ev["physical_disks"]
    assert out["storage"]["summary"] == ev["summary"]
    assert out["storage"]["hbas"] == ev["hbas"] == []
    assert out["errors"] == []


# ═══════════════════════════════════════════════════════════════════════════
# C3 — hbas: 어댑터 매칭 / ConnectionType / OperationalStatus
# ═══════════════════════════════════════════════════════════════════════════
_ADP_A = {"node_wwn": "20:00:00:24:ff:01:02:03", "manufacturer": "Acme", "model": "FC-A",
          "driver": "acmefc.sys", "firmware": "9.1"}
_ADP_B = {"node_wwn": "20:00:00:24:ff:0a:0b:0c", "manufacturer": "Bolt", "model": "FC-B",
          "driver": "boltfc.sys", "firmware": "2.0"}
_ATTRS = ("model", "vendor", "driver", "firmware")


def port(node, wwpn, conn="Fibre Channel", oper="Operational"):
    """initiator ports win_shell 의 ports[] 원소 (Format-Wwn 정규화 후 문자열)."""
    return {"node_addr": node, "port_addr": wwpn, "conn_type": conn, "oper_status": oper}


def hbas(ports, adapters=(), port_attrs=()):
    return run_storage([disk(0, protocol="SAS")],
                       hba={"ports": ports, "adapters": list(adapters),
                            "port_attrs": list(port_attrs)})["storage"]["hbas"]


def test_matched_port_takes_its_own_adapter_attributes():
    out = hbas([port("20:00:00:24:ff:01:02:03", "21:00:00:24:ff:01:02:03")], [_ADP_A, _ADP_B])
    assert [out[0][k] for k in _ATTRS] == ["FC-A", "Acme", "acmefc.sys", "9.1"]


def test_unmatched_port_gets_null_attributes_not_first_adapter():
    """종전: node WWN 매칭 실패 시 adapters[0] 값을 빌려 써서 다른 HBA 의 모델/펌웨어가 붙었다."""
    out = hbas([port("20:00:00:24:ff:01:02:03", "21:00:00:24:ff:01:02:03"),
                port("20:00:00:24:ff:99:99:99", "21:00:00:24:ff:99:99:99")], [_ADP_A])
    assert len(out) == 2, "포트는 그대로 남는다"
    assert [out[0][k] for k in _ATTRS] == ["FC-A", "Acme", "acmefc.sys", "9.1"]
    assert [out[1][k] for k in _ATTRS] == [None, None, None, None]
    assert out[1]["wwpn"] == "21:00:00:24:ff:99:99:99"


def test_iscsi_initiator_never_inherits_fc_adapter_attributes():
    out = hbas([port("iqn.1991-05.com.microsoft:host01", "iscsi any port", conn="iSCSI")], [_ADP_A])
    assert out[0]["port_type"] == "iSCSI"
    assert [out[0][k] for k in _ATTRS] == [None, None, None, None]


def test_adapter_key_matches_regardless_of_case():
    """어댑터 node WWN 표기가 대문자여도 정규화 키로 맞춘다 (첫 어댑터 우연 일치에 기대지 않는다)."""
    upper_b = dict(_ADP_B, node_wwn="20:00:00:24:FF:0A:0B:0C")
    out = hbas([port("20:00:00:24:ff:0a:0b:0c", "21:00:00:24:ff:0a:0b:0c")], [_ADP_A, upper_b])
    assert [out[0][k] for k in _ATTRS] == ["FC-B", "Bolt", "boltfc.sys", "2.0"]


def test_single_port_object_collapse_still_handled():
    """PS5.1 ConvertTo-Json 이 원소 1개 배열을 객체로 접는 경우 (회귀 방어)."""
    out = run_storage([disk(0, protocol="SAS")],
                      hba={"ports": port("20:00:00:24:ff:01:02:03", "21:00:00:24:ff:01:02:03"),
                           "adapters": _ADP_A, "port_attrs": []})["storage"]["hbas"]
    assert len(out) == 1 and out[0]["model"] == "FC-A"


@pytest.mark.parametrize("conn,port_type,connection", [
    (1, "FibreChannel", "Fibre Channel"),        # MSFT_InitiatorPort.ConnectionType 원값 (UInt16)
    ("1", "FibreChannel", "Fibre Channel"),      # PowerShell [string] 캐스트 결과
    ("Fibre Channel", "FibreChannel", "Fibre Channel"),   # Storage 모듈 표시 문자열 (종전 그대로)
    ("FibreChannel", "FibreChannel", "FibreChannel"),
    (2, "iSCSI", "iSCSI"),
    ("2", "iSCSI", "iSCSI"),
    ("iSCSI", "iSCSI", "iSCSI"),
])
def test_connection_type_numeric_and_string_forms(conn, port_type, connection):
    out = hbas([port("20:00:00:24:ff:01:02:03", "21:00:00:24:ff:01:02:03", conn=conn)])
    assert len(out) == 1, f"ConnectionType {conn!r} 포트가 빠졌다"
    assert out[0]["port_type"] == port_type
    assert out[0]["connection"] == connection
    if port_type == "FibreChannel":
        assert out[0]["wwpn"] == "21:00:00:24:ff:01:02:03"
    else:
        assert out[0]["wwpn"] is None


@pytest.mark.parametrize("conn", [0, "0", "Other", 3, "3", "SAS", "Unknown", "", None])
def test_non_fc_non_iscsi_initiators_are_excluded(conn):
    """SAS / Other initiator 는 hbas[] 가 아니다 (storage controller 영역 — 종전과 같음)."""
    assert hbas([port("50:00:00:00:00:00:00:01", "50:00:00:00:00:00:00:02", conn=conn)]) == []


@pytest.mark.parametrize("oper,link", [
    ("Operational", "up"), ("2", "up"),
    ("Link Down", "down"), ("6", "down"),
    ("Port Error", "down"), ("7", "down"),
    ("User Offline", "unknown"), ("3", "unknown"),
    ("Loopback", "unknown"), ("8", "unknown"),
    ("Unknown", "unknown"), ("1", "unknown"), ("", "unknown"),
    # OperationalStatus 는 UInt16[] — 여러 값이면 PowerShell 이 쉼표로 이어 붙인다
    ("6,7", "down"), ("2,8", "up"), ("Operational,Loopback", "up"),
])
def test_oper_status_follows_initiator_port_valuemap(oper, link):
    out = hbas([port("20:00:00:24:ff:01:02:03", "21:00:00:24:ff:01:02:03", oper=oper)])
    assert out[0]["link_status"] == link


def test_port_speed_join_by_normalized_wwpn():
    pa = {"port_wwn": "21:00:00:24:ff:01:02:03", "node_wwn": "20:00:00:24:ff:01:02:03",
          "speed_gbps": 16, "port_state": 2}
    out = hbas([port("20:00:00:24:ff:01:02:03", "21:00:00:24:ff:01:02:03")], [_ADP_A], [pa])
    assert out[0]["link_speed_gbps"] == 16
