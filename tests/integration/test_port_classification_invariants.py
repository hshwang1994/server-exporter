"""포트 분류 자기모순 불변식 — 전 vendor / 전 세대 공통 가드 (cycle 2026-08-03).

왜 이 테스트가 있나:
    2026-08-03 사이트 사고에서 **같은 물리 포트**가 `network.ports[]` 에서는 `Ethernet`,
    `storage.hbas[]` 에서는 `FibreChannel` 로 보고되는 자기모순이 발생했다. 원인은 두 곳의
    분류 경로가 서로 다른 입력(포트 컨텍스트 유무)을 쓰면서 갈린 것이다.

    그때까지의 회귀는 **"우리가 아는 장비의 알려진 출력"** 만 고정하고 있었기 때문에, 처음 보는
    펌웨어에서 새로 생긴 모순을 잡지 못했다 — 사이트가 먼저 발견했다.

    본 테스트는 반대 방향이다. 기대값을 고정하는 대신 **결과가 스스로 모순되지 않는지**만 본다.
    그래서 fixture 가 없는 vendor / 세대에서도, 앞으로 추가될 장비에서도 동작한다.

불변식:
    INV-1  hbas[] / infiniband[] 항목이 어떤 포트에 매핑되면(id 동일 또는 `<port_id>-` 접두),
           그 포트의 port_type 이 Ethernet 이면 안 된다.        ← 2026-08-03 사고를 잡는 가드
    INV-2  hbas[] 항목의 port_type 은 FC 계열(FibreChannel/FCoE/iSCSI)이어야 한다.
    INV-3  infiniband[] 항목이 매핑된 포트는 InfiniBand 여야 한다.
    INV-4  ports[].port_type 은 문서화된 enum 안이어야 한다 (`docs/contract/03-fields.md` §6.3.1).

적용 대상:
    (a) recording.json 을 가진 **모든** replay fixture — 실장비 미러 4종(Dell iDRAC9 / HPE DL380
        Gen12 / HPE CSUS 3200 / Lenovo XCC3) + HPE iLO 에뮬레이터 5종 + DMTF 표준 mockup 1종
    (b) `schema/baseline_v1/*.json` 전 baseline (3-채널 envelope)

오프라인: recording.json 만 사용 — 네트워크 0.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import emulator_harness as H

REPO = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO / "tests" / "fixtures" / "redfish"
BASELINE_ROOT = REPO / "schema" / "baseline_v1"

# `docs/contract/03-fields.md` §6.3.1 — 분류 결과 enum. None/빈값은 '미분류'로 허용(구 펌웨어 raw 보존 경로).
PORT_TYPE_ENUM = {"FibreChannel", "FCoE", "iSCSI", "InfiniBand", "Ethernet"}
FC_LIKE = {"FibreChannel", "FCoE", "iSCSI"}


def _load(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _resolve_port(adapter_id, entry_port_id, ports_by_key):
    """hba/ib 항목 → 대응 포트. **같은 어댑터 안에서만** 동일 id → `<port_id>-` 접두 순으로 찾는다.

    `port_id` 는 호스트 안에서 유일하지 않다 — 실측(HPE DL380 Gen12)에서 FC HBA 와 별도
    이더넷 NIC 이 똑같이 `"1"` / `"2"` 를 쓴다. 어댑터를 무시하고 id 로만 매칭하면 FC 포트가
    다른 카드의 이더넷 포트에 붙어 **가짜 모순**이 잡힌다. 반드시 (adapter_id, port_id) 로 본다.

    접두 매칭이 필요한 이유: Dell 은 NetworkDeviceFunction Id 를 `<PortId>-<funcIdx>` 로 매긴다
    (포트 NIC.Integrated.1-1 ↔ NDF NIC.Integrated.1-1-1). 구분자 '-' 를 요구해 `...1-1` 이
    `...1-10-1` 을 삼키지 않는다.
    """
    if not entry_port_id:
        return None
    key = (adapter_id, entry_port_id)
    if key in ports_by_key:
        return ports_by_key[key]
    for (a_id, pid), ptype in ports_by_key.items():
        if a_id == adapter_id and pid and entry_port_id.startswith(pid + "-"):
            return ptype
    return None


def _check_invariants(label, ports, hbas, ibs):
    """분류 자기모순 검사. 위반 목록(문자열) 반환 — 빈 리스트면 통과."""
    bad = []
    ports = [p for p in (ports or []) if isinstance(p, dict)]
    ports_by_key = {(p.get("adapter_id"), p.get("port_id")): p.get("port_type")
                    for p in ports if p.get("port_id")}

    for p in ports:  # INV-4
        pt = p.get("port_type")
        if pt is not None and pt not in PORT_TYPE_ENUM:
            bad.append(f"{label}: ports[{p.get('port_id')}].port_type={pt!r} — enum 밖")

    for h in (hbas or []):
        if not isinstance(h, dict):
            continue
        pid, pt = h.get("port_id"), h.get("port_type")
        if pt is not None and pt not in FC_LIKE:  # INV-2
            bad.append(f"{label}: hbas[{pid}].port_type={pt!r} — FC 계열이 아님")
        mapped = _resolve_port(h.get("adapter_id"), pid, ports_by_key)
        if mapped == "Ethernet":  # INV-1 (2026-08-03 사고)
            bad.append(
                f"{label}: hbas[{h.get('adapter_id')}/{pid}] 가 Ethernet 포트에 매핑됨 — "
                f"network.ports 와 storage.hbas 가 같은 포트를 다르게 분류(자기모순)")

    for ib in (ibs or []):
        if not isinstance(ib, dict):
            continue
        pid = ib.get("port_id")
        mapped = _resolve_port(ib.get("adapter_id"), pid, ports_by_key)
        if mapped is not None and mapped != "InfiniBand":  # INV-3
            bad.append(f"{label}: infiniband[{ib.get('adapter_id')}/{pid}] 가 {mapped!r} "
                       f"포트에 매핑됨 — 자기모순")
    return bad


# ── (a) replay fixture 전수 (실미러 + 에뮬레이터 + DMTF) ─────────────────────

REPLAY_CASES = sorted(
    d for d in FIXTURE_ROOT.iterdir()
    if d.is_dir() and (d / "recording.json").is_file()
)
REPLAY_IDS = [d.name for d in REPLAY_CASES]


@pytest.mark.integration
@pytest.mark.skipif(not REPLAY_CASES, reason="replay fixture 없음")
@pytest.mark.parametrize("case_dir", REPLAY_CASES, ids=REPLAY_IDS)
def test_replay_port_classification_is_self_consistent(case_dir):
    """모든 replay fixture(전 vendor/세대)에서 포트 분류가 자기모순이 아니어야 한다."""
    recording = _load(case_dir / "recording.json")
    meta_path = case_dir / "meta.json"
    layout = _load(meta_path).get("manager_layout") if meta_path.is_file() else None
    get_impl, noauth_impl, realm_impl = H.make_replayer(recording)
    result = H.run_gather(get_impl, noauth_impl, realm_impl=realm_impl,
                          manager_layout=layout)

    na = (result.get("data") or {}).get("network_adapters") or {}
    if not isinstance(na, dict):
        pytest.skip(f"{case_dir.name}: network_adapters 미수집")
    bad = _check_invariants(case_dir.name, na.get("ports"),
                            na.get("fc_hbas"), na.get("infiniband"))
    assert not bad, "\n".join(bad)


# ── (b) baseline envelope 전수 (3-채널) ─────────────────────────────────────

BASELINES = sorted(BASELINE_ROOT.glob("*.json"))
BASELINE_IDS = [p.stem for p in BASELINES]


@pytest.mark.skipif(not BASELINES, reason="baseline 없음")
@pytest.mark.parametrize("path", BASELINES, ids=BASELINE_IDS)
def test_baseline_port_classification_is_self_consistent(path):
    """전 baseline envelope 에서도 같은 불변식이 성립해야 한다 (os/esxi/redfish 공통)."""
    d = _load(path)
    data = d.get("data") or {}
    net = data.get("network") if isinstance(data.get("network"), dict) else {}
    sto = data.get("storage") if isinstance(data.get("storage"), dict) else {}
    bad = _check_invariants(path.stem, net.get("ports"),
                            sto.get("hbas"), sto.get("infiniband"))
    assert not bad, "\n".join(bad)


# ── (c) 조립 경로 ↔ 노출 링크 일치 가드 (세대 이동 조기 경보) ────────────────
#
# redfish_gather.py 는 하위 컬렉션 경로를 대부분 **문자열로 조립**한다
# (`_p(system_uri) + '/Processors'` 등, 14곳). 링크를 따라가지 않으므로 벤더가 그 리소스를
# 다른 부모 밑에 두는 세대에서는 조용히 빗나간다 — 2026-08-03 Dell iDRAC8 사고가 정확히 그것이다
# (NetworkAdapters 가 Chassis 가 아니라 Systems 밑).
#
# 본 가드는 replay fixture 의 **부모 응답이 실제로 노출한 @odata.id** 와 우리가 조립하는 경로를
# 대조한다. 새 미러(특히 미보유 세대)를 fixture 로 넣는 순간 자동으로 검사된다.

SYSTEM_KEYS = ("Processors", "Memory", "Storage", "SimpleStorage", "EthernetInterfaces")
CHASSIS_KEYS = ("Power", "Thermal", "PowerSubsystem", "ThermalSubsystem",
                "Sensors", "NetworkAdapters", "EnvironmentMetrics")


def _rel(odata_id):
    """@odata.id → `_p()` 와 같은 상대 경로 표기."""
    p = str(odata_id or "").strip().strip("/")
    return p[len("redfish/v1/"):] if p.startswith("redfish/v1/") else p


@pytest.mark.integration
@pytest.mark.skipif(not REPLAY_CASES, reason="replay fixture 없음")
@pytest.mark.parametrize("case_dir", REPLAY_CASES, ids=REPLAY_IDS)
def test_constructed_paths_match_exposed_links(case_dir):
    """부모가 링크를 노출하면, 우리가 조립하는 경로와 같아야 한다.

    다르면 그 세대에서 우리는 **없는 경로를 물어보고 있다**는 뜻 → 조립 대신 링크 추적
    (또는 fallback 경로 추가)이 필요하다.
    """
    recording = _load(case_dir / "recording.json")
    bad = []
    for key, val in recording.items():
        if not key.startswith("get::"):
            continue
        body = val[1] if isinstance(val, list) and len(val) > 1 else None
        if not isinstance(body, dict):
            continue
        parent = key[len("get::"):].rstrip("/")
        # 부모 종류에 맞는 키만 본다 — Chassis 가 노출하는 Memory 링크는 Systems 를 가리키는
        # 다른 관계(우리는 system_uri 기준으로 조립)이므로 여기서 비교 대상이 아니다.
        if parent.startswith("Systems/") and parent.count("/") == 1:
            keys = SYSTEM_KEYS
        elif parent.startswith("Chassis/") and parent.count("/") == 1:
            keys = CHASSIS_KEYS
        else:
            continue
        for k in keys:
            link = body.get(k)
            if not (isinstance(link, dict) and link.get("@odata.id")):
                continue
            exposed = _rel(link["@odata.id"])
            constructed = f"{parent}/{k}"
            if exposed != constructed:
                bad.append(
                    f"{case_dir.name}: {parent} 가 노출한 {k} 링크={exposed!r} 인데 "
                    f"코드는 {constructed!r} 로 조립 — 이 세대에서 빗나간다")
    assert not bad, "\n".join(bad)


# ── 불변식 자체의 자기검증 (테스트가 진짜 잡는지) ───────────────────────────

def test_invariant_detects_the_2026_08_03_defect():
    """2026-08-03 사이트 사고 형태를 그대로 넣으면 INV-1 이 걸려야 한다."""
    ports = [{"adapter_id": "NIC.Integrated.1", "port_id": "NIC.Integrated.1-1",
              "port_type": "Ethernet"}]
    hbas = [{"adapter_id": "NIC.Integrated.1", "port_id": "NIC.Integrated.1-1-1",
             "port_type": "FibreChannel"}]
    bad = _check_invariants("synthetic", ports, hbas, [])
    assert bad and "자기모순" in bad[0]


def test_invariant_allows_genuine_fc_port():
    """진짜 FC 포트는 통과 — 불변식이 정상 케이스를 막지 않는다."""
    ports = [{"adapter_id": "FC.Slot.1", "port_id": "FC.Slot.1-1", "port_type": "FibreChannel"}]
    hbas = [{"adapter_id": "FC.Slot.1", "port_id": "FC.Slot.1-1", "port_type": "FibreChannel"}]
    assert _check_invariants("synthetic", ports, hbas, []) == []


def test_invariant_allows_portless_hba():
    """포트가 없는 HBA(HPE CSUS 등 port-less NDF)는 매핑 대상이 없어 통과."""
    hbas = [{"adapter_id": "PCIeCard10", "port_id": "PCIeCard10Port1",
             "port_type": "FibreChannel"}]
    assert _check_invariants("synthetic", [], hbas, []) == []


def test_invariant_prefix_match_requires_separator():
    """접두 매칭이 `...1-1` 로 `...1-10-1` 을 오매칭하지 않는다."""
    ports = [{"adapter_id": "NIC.Integrated.1", "port_id": "NIC.Integrated.1-1",
              "port_type": "Ethernet"}]
    hbas = [{"adapter_id": "NIC.Integrated.1", "port_id": "NIC.Integrated.1-10-1",
             "port_type": "FibreChannel"}]
    assert _check_invariants("synthetic", ports, hbas, []) == []


def test_invariant_does_not_cross_adapters():
    """port_id 가 어댑터 간 중복돼도(실측 HPE: FC 와 NIC 이 둘 다 "1") 가짜 모순을 만들지 않는다."""
    ports = [{"adapter_id": "FC.Slot.1", "port_id": "1", "port_type": "FibreChannel"},
             {"adapter_id": "NIC.Slot.3", "port_id": "1", "port_type": "Ethernet"}]
    hbas = [{"adapter_id": "FC.Slot.1", "port_id": "1", "port_type": "FibreChannel"}]
    assert _check_invariants("synthetic", ports, hbas, []) == []
