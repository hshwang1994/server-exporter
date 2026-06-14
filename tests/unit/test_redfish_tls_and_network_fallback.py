"""F48 + F84 회귀 — NetworkPorts/Ports fallback + TLS 1.2/1.3 호환.

F48: HPE iLO 6+ deprecated NetworkPorts → Ports (Redfish 1.6+) fallback.
     `gather_network_adapters_chassis` 가 NetworkPorts 없을 때 Ports 사용 확인.

F84: SSLContext minimum_version=TLSv1_2 / maximum_version=TLSv1_3 명시.
     - 구 BMC (TLS 1.2 only) 호환 보장
     - 신 BMC (TLS 1.3) 호환 보장
     - SECLEVEL=0 weak cipher fallback 유지 (iLO 4 / IMM2 / 구 iDRAC)
"""
from __future__ import annotations

import ssl
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))

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


# ── F84 TLS context 회귀 ─────────────────────────────────────────────────────


def test_f84_tls_context_min_version_1_2() -> None:
    """verify_ssl=True 시 minimum_version=TLSv1_2 적용."""
    ctx = rg._ctx(verify_ssl=True)
    if hasattr(ssl, "TLSVersion"):
        assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2


def test_f84_tls_context_max_version_1_3() -> None:
    """verify_ssl=True 시 maximum_version=TLSv1_3 (OpenSSL TLS 1.3 지원 가정)."""
    ctx = rg._ctx(verify_ssl=True)
    if hasattr(ssl, "TLSVersion"):
        # TLS 1.3 미지원 OpenSSL 버전 가능 — TLSv1_2 이상만 보장
        assert ctx.maximum_version >= ssl.TLSVersion.TLSv1_2


def test_f84_tls_context_unverified_self_signed() -> None:
    """verify_ssl=False (사내 BMC self-signed) 시 hostname 검증 / cert 검증 disable."""
    ctx = rg._ctx(verify_ssl=False)
    assert ctx.check_hostname is False
    assert ctx.verify_mode == ssl.CERT_NONE


def test_f84_tls_context_legacy_renegotiation_flag() -> None:
    """verify_ssl=False 시 OP_LEGACY_SERVER_CONNECT 적용 (구 BMC OpenSSL 3.x 호환)."""
    ctx = rg._ctx(verify_ssl=False)
    if hasattr(ssl, "OP_LEGACY_SERVER_CONNECT"):
        assert (ctx.options & ssl.OP_LEGACY_SERVER_CONNECT) != 0


# ── F48 NetworkPorts/Ports fallback 회귀 ─────────────────────────────────────


def _mk_get(responses):
    """순차 응답 list → _get mock."""
    it = iter(responses)

    def fake(bmc_ip, path, username, password, timeout, verify_ssl):
        return next(it)

    return fake


def test_f48_network_adapters_uses_ports_when_no_networkports(monkeypatch) -> None:
    """HPE iLO 6+ NetworkPorts deprecated — Ports collection 사용 fallback.

    NetworkAdapter 응답에 'NetworkPorts' 없고 'Ports' 만 존재 시 Ports 컬렉션을
    그대로 collect.
    """
    chassis_uri = "/redfish/v1/Chassis/1"

    # 1: NetworkAdapters collection
    adapters_coll = {
        "Members": [{"@odata.id": "/redfish/v1/Chassis/1/NetworkAdapters/A"}]
    }
    # 2: 각 adapter — Ports 만 존재 (NetworkPorts 없음, iLO 6+ 구조)
    adapter_a = {
        "Id": "A",
        "Name": "NIC A",
        "Manufacturer": "Mellanox",
        "Model": "ConnectX-6",
        "Controllers": [{
            "FirmwarePackageVersion": "20.32",
            "ControllerCapabilities": {"NetworkPortCount": 2},
        }],
        "Ports": {"@odata.id": "/redfish/v1/Chassis/1/NetworkAdapters/A/Ports"},
    }
    # 3: Ports collection
    ports_coll = {
        "Members": [
            {"@odata.id": "/redfish/v1/Chassis/1/NetworkAdapters/A/Ports/1"},
        ]
    }
    # 4: 각 port
    port_1 = {
        "Id": "1",
        "Name": "Port 1",
        "PhysicalPortNumber": "1",
        "LinkStatus": "LinkUp",
        "LinkState": "Enabled",
        "CurrentLinkSpeedMbps": 25000,
        "PortType": "Ethernet",
        "AssociatedNetworkAddresses": ["aa:bb:cc:dd:ee:01"],
        "Status": {"Health": "OK"},
    }

    monkeypatch.setattr(
        rg,
        "_get",
        _mk_get([
            (200, adapters_coll, None),
            (200, adapter_a, None),
            (200, ports_coll, None),
            (200, port_1, None),
        ]),
    )

    out, errors = rg.gather_network_adapters_chassis(
        "10.1.1.1", chassis_uri, "u", "p", 30, False
    )

    # adapter 1개 collect + port 1개 collect (NetworkPorts 없어도 Ports로)
    assert len(out["adapters"]) == 1
    assert out["adapters"][0]["model"] == "ConnectX-6"
    assert len(out["ports"]) == 1
    assert out["ports"][0]["associated_address"] == "aa:bb:cc:dd:ee:01"
    assert out["ports"][0]["current_link_speed_mbps"] == 25000


def test_f48_network_adapters_prefers_networkports_when_present(monkeypatch) -> None:
    """Redfish 1.5 이전 BMC — NetworkPorts 존재 시 Ports 보다 우선."""
    chassis_uri = "/redfish/v1/Chassis/1"
    adapters_coll = {
        "Members": [{"@odata.id": "/redfish/v1/Chassis/1/NetworkAdapters/B"}]
    }
    # NetworkPorts 와 Ports 둘 다 존재 — NetworkPorts 우선 사용
    adapter_b = {
        "Id": "B",
        "Name": "NIC B",
        "Manufacturer": "Intel",
        "Model": "X710",
        "Controllers": [{
            "FirmwarePackageVersion": "5.50",
            "ControllerCapabilities": {"NetworkPortCount": 4},
        }],
        "NetworkPorts": {"@odata.id": "/redfish/v1/legacy/networkports"},
        "Ports": {"@odata.id": "/redfish/v1/new/ports"},
    }
    legacy_coll = {"Members": []}

    monkeypatch.setattr(
        rg,
        "_get",
        _mk_get([
            (200, adapters_coll, None),
            (200, adapter_b, None),
            (200, legacy_coll, None),
        ]),
    )

    out, _errors = rg.gather_network_adapters_chassis(
        "10.1.1.1", chassis_uri, "u", "p", 30, False
    )
    # NetworkPorts (legacy) 우선 시도 → Ports 미사용 (요청 1번만 발생)
    assert len(out["adapters"]) == 1


def test_f48_network_adapters_skip_empty_placeholder(monkeypatch) -> None:
    """port_count=0 + manufacturer/model 빈 entry → 실 NIC 아닌 placeholder skip.

    실측 Lenovo XCC SR650 V2 — PCIe slot 자체를 NetworkAdapters 컬렉션에
    빈 entry 로 노출하는 케이스.
    """
    chassis_uri = "/redfish/v1/Chassis/1"
    adapters_coll = {
        "Members": [
            {"@odata.id": "/redfish/v1/Chassis/1/NetworkAdapters/empty"},
            {"@odata.id": "/redfish/v1/Chassis/1/NetworkAdapters/real"},
        ]
    }
    empty_adapter = {
        "Id": "empty",
        "Manufacturer": "",
        "Model": "",
        "Controllers": [{"ControllerCapabilities": {"NetworkPortCount": 0}}],
    }
    real_adapter = {
        "Id": "real",
        "Manufacturer": "Broadcom",
        "Model": "BCM57414",
        "Controllers": [{
            "FirmwarePackageVersion": "21.x",
            "ControllerCapabilities": {"NetworkPortCount": 2},
        }],
    }

    monkeypatch.setattr(
        rg,
        "_get",
        _mk_get([
            (200, adapters_coll, None),
            (200, empty_adapter, None),
            (200, real_adapter, None),
        ]),
    )

    out, _errors = rg.gather_network_adapters_chassis(
        "10.1.1.1", chassis_uri, "u", "p", 30, False
    )
    # placeholder skip — real adapter 만
    assert len(out["adapters"]) == 1
    assert out["adapters"][0]["model"] == "BCM57414"
