"""HPE iLO 에뮬레이터 record/replay 하네스 (공용 모듈).

배경 (rule 21 R1 / rule 25 R7-B):
    server-exporter 의 본질적 제약은 lab 부재다. 실측 HPE 장비는 1 대뿐
    (DL380 Gen11, iLO6 v1.73). 본 하네스는 HPE 공식 iLO Redfish 에뮬레이터
    (BSD-3, v1.7.0) 를 **고품질 테스트 타깃** 으로 써서 redfish_gather.py 의
    파싱/정규화 엔진에 오프라인·결정적 회귀 안전망을 건다.

    **에뮬레이터 != 실장비.** 본 하네스가 만든 fixture / golden 은
    schema/baseline_v1/ 실측 baseline 으로 승격하지 않는다. 전부
    tests/fixtures/redfish/hpe_emulator_* 아래 "emulator-derived" 로 라벨링.

설계:
    - record (capture): rg._get / rg._get_noauth 를 실 에뮬레이터로 passthrough
      하면서 (path -> 응답) 을 기록 → recording.json.
    - replay (test): 기록된 recording.json 을 (path -> 응답) lookup 으로 주입해
      **실제** detect_vendor → _collect_all_sections → _compute_final_status 를
      오프라인에서 구동 → golden(expected_output.json) 과 비교.

    두 경로 모두 redfish_gather.py main() 의 gather mode 흐름을 1:1 미러링
    (핵심 섹션 수집은 _collect_all_sections — detect_vendor → 수집 → _compute_final_status 순).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

# ---------------------------------------------------------------------------
# redfish_gather 모듈 import (기존 unit test 와 동일 패턴 — ansible stub)
#   tests/unit/test_redfish_storage_controller.py L14~27 참조.
# ---------------------------------------------------------------------------
REPO = Path(__file__).resolve().parents[2]
_LIB = str(REPO / "redfish-gather" / "library")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

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

# import 시점의 "진짜" 네트워크 transport (swap 전 원본 보존).
_REAL_GET = rg._get
_REAL_GET_NOAUTH = rg._get_noauth

# replay 시 기록에 없는 path 응답 = 실 BMC 의 404 와 동일 형태로 반환.
# err 문자열에 'HTTP 404' 포함이 중요: redfish_gather._get 은 실 404 시 err=
# "HTTP 404: Not Found" 를 주고, _is_404_only_error 가 그 시그널로 absent endpoint 를
# 'unsupported'(capability 미지원, 노이즈 아님)로 분류한다. 'replay-miss' 만 남기면
# 같은 absent endpoint 가 'failed' 로 오분류되는 replay 인공물이 생긴다(실 BMC 와 불일치).
# 'replay-miss' 표식은 디버깅용으로 괄호 안에 보존.
_REPLAY_MISS = (404, {}, "HTTP 404: Not Found (replay-miss: path not in recording)")


def run_gather(get_impl, noauth_impl, realm_impl=None, ip="127.0.0.1",
               user="root", pw="root_password", timeout=30, verify_ssl=False,
               manager_layout=None):
    """main() gather mode 흐름을 1:1 미러링해 모듈 산출 snapshot 을 반환.

    manager_layout: rg._collect_all_sections / _collect_multi_node_topology 에 전달.
        CSUS/Superdome 캡처를 멀티노드로 재생하려면 'rmc_primary' 를 넘긴다. 기본 None →
        단일노드(기존 DMTF/표준 mockup 동작 불변, multi_node=None).

    get_impl / noauth_impl: rg._get / rg._get_noauth 를 대체할 transport.
        (record 시 passthrough+기록, replay 시 lookup)
    realm_impl: rg._probe_realm_hint 를 대체할 transport (선택, 기본 None).
        vendor=unknown fixture(예: DMTF 표준 mockup, Manufacturer 가 alias 미매치)는
        detect_vendor 의 G6 realm probe(_probe_realm_hint)에 도달한다. 이 함수는
        seam(_get/_get_noauth)을 우회해 urlreq.urlopen 을 직접 호출하므로, replay 시
        None 으로 두면 conftest hermetic 가드가 실 네트워크 시도를 차단(RuntimeError)
        한다. realm 도 seam 으로 주입해 오프라인 불변식을 유지한다. None 이면 실 함수
        유지 → live(capture/smoke) 동작 불변 (기존 호출자 backward-compat).

    Returns: dict — main() exit_json 의 gather 산출 필드 부분집합.
        list 필드는 정렬해 결정적(deterministic) 비교 가능.
    """
    saved_get, saved_noauth = rg._get, rg._get_noauth
    saved_realm = rg._probe_realm_hint
    rg._get, rg._get_noauth = get_impl, noauth_impl
    if realm_impl is not None:
        rg._probe_realm_hint = realm_impl
    try:
        vendor, system_uri, manager_uri, chassis_uri, det_errors, service_root = \
            rg.detect_vendor(ip, user, pw, timeout, verify_ssl)
        probe_facts = rg._extract_probe_facts(service_root, vendor)

        all_errors = list(det_errors)
        collected, failed, unsupported = [], [], []

        if not system_uri:
            return {
                "vendor": vendor,
                "status": "failed",
                "collected": [],
                "failed_sections": ["all"],
                "unsupported_sections": [],
                "data": {},
                "multi_node": None,
                "probe_facts": probe_facts,
                "error_count": len(all_errors),
            }

        # main() 미러링 (2026-08-11): 대표 시리얼 resolver 가 등록된 vendor 는 그 값이 필수값이다.
        # 못 얻으면 다른 시리얼 후보로 대체하지 않고 실패로 끝낸다. 미등록 vendor 는 영향 0.
        serial_resolver = rg._SERIAL_RESOLVERS.get(vendor)
        forced_serial = None
        if serial_resolver is not None:
            def _reauth_service_root():
                if not user:
                    return None
                st_r, root_r, err_r = rg._get(ip, "", user, pw, timeout, verify_ssl)
                if err_r or st_r != 200 or not isinstance(root_r, dict):
                    return None
                return root_r

            forced_serial, serial_err = serial_resolver(
                service_root, refetch=_reauth_service_root)
            if serial_err is not None:
                all_errors.append(rg._err("system", serial_err))
                return {
                    "vendor": vendor,
                    "status": "failed",
                    "collected": [],
                    "failed_sections": ["all"],
                    "unsupported_sections": [],
                    "data": {},
                    "multi_node": None,
                    "probe_facts": probe_facts,
                    "error_count": len(all_errors),
                }

        data = rg._collect_all_sections(
            ip, vendor, system_uri, manager_uri, chassis_uri,
            user, pw, timeout, verify_ssl,
            all_errors, collected, failed, unsupported,
            manager_layout=manager_layout,
            product_hint=rg._safe(service_root, "Product"),
        )

        # main() 미러링: 대표 시리얼 확정 + 실을 자리가 없으면 정상 결과로 반환하지 않는다.
        if serial_resolver is not None:
            sys_section = data.get("system")
            if isinstance(sys_section, dict) and sys_section:
                sys_section["serial"] = forced_serial
            else:
                all_errors.append(rg._err(
                    "system",
                    "서버 대표 시리얼을 결과에 실을 수 없습니다 — system 섹션 수집 실패"))
                return {
                    "vendor": vendor,
                    "status": "failed",
                    "collected": [],
                    "failed_sections": ["all"],
                    "unsupported_sections": [],
                    "data": {},
                    "multi_node": None,
                    "probe_facts": probe_facts,
                    "error_count": len(all_errors),
                }

        multi_node = rg._collect_multi_node_topology(
            ip, vendor, service_root, user, pw, timeout, verify_ssl,
            manager_layout=manager_layout,
        )
        # main() 미러링 (Round 10): multi_node errors 를 status 계산에 반영. manager_layout 이
        # rmc_primary 등으로 주입되면(CSUS/Superdome) 멀티노드 토폴로지가 실제로 수집된다.
        if isinstance(multi_node, dict):
            all_errors.extend(multi_node.get('errors') or [])
        final_status, clean = rg._compute_final_status(collected, failed, all_errors)

        # sorted(): golden 의 결정적(deterministic) 비교용 정규화. 실제 main()
        # exit_json 은 collected(미정렬) / list(set(...)) 로 emit 하지만, 그 순서는
        # PYTHONHASHSEED 의존 비결정적이고 downstream(normalize_standard.yml)은
        # sections dict 로 흡수해 순서 비의존이다 — 정렬은 fidelity 를 낮추지 않고
        # cross-run golden flakiness 만 제거한다.
        return {
            "vendor": vendor,
            "status": final_status,
            "collected": sorted(clean),
            "failed_sections": sorted(set(failed)),
            "unsupported_sections": sorted(set(unsupported)),
            "data": data,
            "multi_node": multi_node,
            "probe_facts": probe_facts,
            "error_count": len(all_errors),
        }
    finally:
        rg._get, rg._get_noauth = saved_get, saved_noauth
        rg._probe_realm_hint = saved_realm


def make_recorder():
    """실 에뮬레이터로 passthrough 하며 (path -> 응답) 을 기록.

    Returns: (get_impl, noauth_impl, recording: dict[str, list])
        recording key: 'get::<path>' / 'noauth::<path>'
        recording value: [status, data, err] (JSON 직렬화 가능)
    """
    recording: dict[str, list] = {}

    def get_impl(bmc_ip, path, username, password, timeout, verify_ssl):
        status, data, err = _REAL_GET(bmc_ip, path, username, password, timeout, verify_ssl)
        recording[f"get::{path}"] = [status, data, err]
        return status, data, err

    def noauth_impl(bmc_ip, path, timeout, verify_ssl):
        status, data, err = _REAL_GET_NOAUTH(bmc_ip, path, timeout, verify_ssl)
        recording[f"noauth::{path}"] = [status, data, err]
        return status, data, err

    return get_impl, noauth_impl, recording


def make_replayer(recording):
    """기록된 recording 을 (path -> 응답) lookup 으로 주입 (오프라인).

    제약: path 당 단일 응답. 멱등 read-only GET 전용이라 호출 순서에 따라 응답이
    달라지는 stateful sequence(ETag 조건부 / mutable 중간 상태)는 미지원 —
    redfish_gather 수집 범위(read-only inventory)에서는 불필요.

    Returns: (get_impl, noauth_impl, realm_impl)
        realm_impl: _probe_realm_hint 대체. recording 의 'realm::' 키가 있으면 그 값을,
        없으면 None 반환. 정적 mockup/HPE 캡처에는 realm 키가 없으므로(401 헤더는
        seam 으로 안 잡힘) None — vendor 가 ServiceRoot/Manufacturer 로 식별되거나
        unknown 으로 남는다. seam 우회 urlopen 을 막아 오프라인 불변식 유지.
    """
    def get_impl(bmc_ip, path, username, password, timeout, verify_ssl):
        rec = recording.get(f"get::{path}")
        if rec is None:
            return _REPLAY_MISS
        return rec[0], rec[1], rec[2]

    def noauth_impl(bmc_ip, path, timeout, verify_ssl):
        rec = recording.get(f"noauth::{path}")
        if rec is None:
            return _REPLAY_MISS
        return rec[0], rec[1], rec[2]

    def realm_impl(bmc_ip, timeout, verify_ssl):
        return recording.get("realm::") or None

    return get_impl, noauth_impl, realm_impl


# golden 비교에서 strict equality 대상.
#   - errors[] 리스트 자체(메시지 verbose)는 제외하되, error_count 는 포함해
#     "에러 0건이 silent 하게 N건으로 늘어나는" 회귀를 잡는다 (HF-4 보강).
GOLDEN_KEYS = (
    "vendor", "status", "collected", "failed_sections",
    "unsupported_sections", "data", "multi_node", "probe_facts",
    "error_count",
)
