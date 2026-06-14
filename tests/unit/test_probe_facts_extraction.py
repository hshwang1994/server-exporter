"""
T-01 (cycle 2026-05-11) `_extract_probe_facts()` 단위 테스트.

`redfish_gather.py` 의 신규 함수가 HPE iLO 6 Gen11 ServiceRoot 무인증 응답에서
model_hint / firmware_hint / manager_type 을 정확히 추출하는지 검증.

fixture: tests/fixtures/redfish/hpe_ilo6_v1_73/01_service_root.json
       (build #133 캡처 — DL380 Gen11 / iLO 6 v1.73)

타 vendor (Dell/Lenovo/Cisco/Supermicro/Huawei/Inspur/Fujitsu/Quanta) 는 ServiceRoot
가 BMC 제품명을 expose 하므로 빈 dict 반환 보장 — 회귀 0.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_redfish_gather_module():
    """ansible.module_utils.basic 없는 환경에서도 _extract_probe_facts 만 로드.

    redfish_gather.py 는 top-level 에서 `from ansible.module_utils.basic import
    AnsibleModule` 을 시도 — pytest 환경에 ansible 없으면 ImportError.
    pytest 환경에서는 sys.modules 에 mock 등록 후 import.
    """
    if "ansible.module_utils.basic" not in sys.modules:
        # 최소 mock — AnsibleModule 만 노출. import 단계만 통과시키면 됨.
        import types
        mock_basic = types.ModuleType("ansible.module_utils.basic")
        mock_basic.AnsibleModule = type("AnsibleModule", (), {})
        mock_ansible = types.ModuleType("ansible")
        mock_ansible_mu = types.ModuleType("ansible.module_utils")
        sys.modules.setdefault("ansible", mock_ansible)
        sys.modules.setdefault("ansible.module_utils", mock_ansible_mu)
        sys.modules["ansible.module_utils.basic"] = mock_basic

    src = REPO_ROOT / "redfish-gather" / "library" / "redfish_gather.py"
    spec = importlib.util.spec_from_file_location("redfish_gather_t01", str(src))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def rfg():
    return _load_redfish_gather_module()


@pytest.fixture(scope="module")
def hpe_ilo6_service_root() -> dict:
    fixture_path = (
        REPO_ROOT / "tests" / "fixtures" / "redfish" / "hpe_ilo6_v1_73"
        / "01_service_root.json"
    )
    with open(fixture_path, encoding="utf-8") as f:
        return json.load(f)


def test_extract_probe_facts_hpe_ilo6_gen11(rfg, hpe_ilo6_service_root) -> None:
    """실 fixture (HPE DL380 Gen11 iLO 6 v1.73) 추출 검증."""
    facts = rfg._extract_probe_facts(hpe_ilo6_service_root, "hpe")
    assert facts["model_hint"] == "ProLiant DL380 Gen11", (
        f"model_hint 추출 실패: {facts}"
    )
    assert facts["firmware_hint"] == "1.73", (
        f"firmware_hint 추출 실패: {facts}"
    )
    assert facts["manager_type"] == "iLO 6", (
        f"manager_type 추출 실패: {facts}"
    )


def test_extract_probe_facts_other_vendors_empty(rfg, hpe_ilo6_service_root) -> None:
    """타 vendor 분기 (회귀 0 보장) — 같은 root 라도 빈 dict 반환."""
    for vendor in ("dell", "lenovo", "cisco", "supermicro", "huawei",
                   "inspur", "fujitsu", "quanta", "unknown"):
        facts = rfg._extract_probe_facts(hpe_ilo6_service_root, vendor)
        assert facts == {}, f"vendor={vendor} 가 빈 dict 반환해야 함 (실제: {facts})"


def test_extract_probe_facts_none_root(rfg) -> None:
    """root=None / 비-dict → 빈 dict."""
    assert rfg._extract_probe_facts(None, "hpe") == {}
    assert rfg._extract_probe_facts("not a dict", "hpe") == {}
    assert rfg._extract_probe_facts([], "hpe") == {}


def test_extract_probe_facts_empty_root(rfg) -> None:
    """root={} → 빈 dict (HPE 분기여도 추출할 게 없음)."""
    assert rfg._extract_probe_facts({}, "hpe") == {}


def test_extract_probe_facts_hpe_no_oem(rfg) -> None:
    """Product 만 있고 Oem 부재 (legacy iLO 4 가능) → model_hint 만."""
    root = {"Vendor": "HPE", "Product": "ProLiant DL380 Gen9"}
    facts = rfg._extract_probe_facts(root, "hpe")
    assert facts == {"model_hint": "ProLiant DL380 Gen9"}


def test_extract_probe_facts_hpe_oem_hp_namespace(rfg) -> None:
    """Oem.Hp namespace (iLO 4 시기 — HPE rebrand 전) fallback."""
    root = {
        "Vendor": "HP",
        "Product": "ProLiant DL380 Gen9",
        "Oem": {
            "Hp": {
                "Manager": [{
                    "ManagerFirmwareVersion": "2.55",
                    "ManagerType": "iLO 4",
                }]
            }
        }
    }
    facts = rfg._extract_probe_facts(root, "hpe")
    assert facts["model_hint"] == "ProLiant DL380 Gen9"
    assert facts["firmware_hint"] == "2.55"
    assert facts["manager_type"] == "iLO 4"


def test_extract_probe_facts_hpe_manager_dict_form(rfg) -> None:
    """Oem.Hpe.Manager 가 list 아닌 dict 형태인 fallback (펌웨어 변종 대비)."""
    root = {
        "Product": "ProLiant DL380 Gen11",
        "Oem": {
            "Hpe": {
                "Manager": {
                    "ManagerFirmwareVersion": "1.73",
                    "ManagerType": "iLO 6",
                }
            }
        }
    }
    facts = rfg._extract_probe_facts(root, "hpe")
    assert facts["model_hint"] == "ProLiant DL380 Gen11"
    assert facts["firmware_hint"] == "1.73"
    assert facts["manager_type"] == "iLO 6"


def test_extract_probe_facts_strips_whitespace(rfg) -> None:
    """추출값 공백 trim."""
    root = {
        "Product": "  ProLiant DL380 Gen11  ",
        "Oem": {"Hpe": {"Manager": [{"ManagerFirmwareVersion": " 1.73 "}]}}
    }
    facts = rfg._extract_probe_facts(root, "hpe")
    assert facts["model_hint"] == "ProLiant DL380 Gen11"
    assert facts["firmware_hint"] == "1.73"


def test_extract_probe_facts_skips_empty_strings(rfg) -> None:
    """빈 문자열 / None 필드는 facts 에 넣지 않음."""
    root = {
        "Product": "",
        "Oem": {"Hpe": {"Manager": [{"ManagerFirmwareVersion": None, "ManagerType": "iLO 6"}]}}
    }
    facts = rfg._extract_probe_facts(root, "hpe")
    assert "model_hint" not in facts
    assert "firmware_hint" not in facts
    assert facts["manager_type"] == "iLO 6"
