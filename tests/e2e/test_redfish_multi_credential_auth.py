"""Phase 5-A 보정: Redfish 복수 Credential 후보의 auth_success 집계 규칙.

문제
----
`auth_evidence.first_auth_status` 는 **후보 하나**의 관측이다 (후보마다 redfish_gather 가
별도 모듈 프로세스로 실행된다). 후보 하나가 401 을 받았다는 사실만으로 Credential Probe
**전체**를 "인증 거부" 로 확정하면, 다른 후보가 timeout / TLS / 403 로 실패한 경우까지
원인을 단정하게 된다.

최종 규칙 (셋 다 만족해야 auth_success=false)
  1. 실제로 시도한 후보가 1개 이상
  2. 후보 수만큼 관측이 쌓임 (누락 없음)
  3. 모든 후보의 **첫 인증 응답**이 401

그 외는 전부 null. 하나라도 성공하면 rescue 에 오지 않는다(true 경로).

`first_auth_status` 가 "첫" 요청인 점이 중요하다. 인증이 통과한 뒤(200) 하위 리소스에서
나온 401 은 기록되지 않으므로 Credential 실패로 승격되지 않는다.

네트워크 0 — 실제 요청을 만들지 않고, 후보별 관측 리스트를 그대로 넣어 production
site.yml 의 판정 템플릿을 렌더한다.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))

_b = types.ModuleType("ansible.module_utils.basic")
_b.AnsibleModule = object
_m = types.ModuleType("ansible.module_utils")
_m.basic = _b
_a = types.ModuleType("ansible")
_a.module_utils = _m
sys.modules.setdefault("ansible", _a)
sys.modules.setdefault("ansible.module_utils", _m)
sys.modules.setdefault("ansible.module_utils.basic", _b)

import redfish_gather as rg  # noqa: E402

from tests.e2e.test_failure_reason_contract import (  # noqa: E402
    FAILURE_REASONS,
    _assert_claims_match_observation,
    _assert_grid_ready,
    _env,
    _task_by_name,
    render_redfish_rescue,
)

_SITE = "redfish-gather/site.yml"
_REJECT_TASK = "redfish | rescue | 인증 거부 실증 판정"
_DIAG_TASK = "redfish | rescue | Portal 표시용 failure_reason 보장"

_PRECHECK_OK = {
    "reachable": True, "port_open": True, "protocol_supported": True,
    "auth_success": None, "failure_stage": None, "failure_code": None,
    "failure_reason": None, "details": {},
}


def _ansible_select_equalto(seq, _test, value):
    """ansible `select('equalto', X)` 대역."""
    return [item for item in (seq or []) if item == value]


def _render(task_name: str, ctx: dict[str, Any]) -> Any:
    tpl = _task_by_name(_SITE, task_name)["ansible.builtin.set_fact"]
    key = "_rf_auth_rejected" if task_name == _REJECT_TASK else "_diagnosis"
    env = _env()
    env.filters["select"] = _ansible_select_equalto
    # 2026-08-11 (Phase 6-B): rescue 는 사용자 문구를 common/vars/failure_reasons.yml 에서
    # 받는다 (play 의 vars_files). 렌더 시 동일하게 주입한다.
    return env.from_string(tpl[key]).render(**{**FAILURE_REASONS, **ctx})


def _decide(statuses: list[Any], *, candidates: int, collect_ok: bool = False):
    """후보별 관측 리스트 → (auth_rejected, diagnosis).

    2026-08-12: rescue 는 거부 판정(_rf_auth_rejected) 뒤에 자격 관측을
    `_rf_auth_outcome` (passed / rejected / unknown) 으로 확정하고, diagnosis 4필드를
    그 하나에서만 파생한다. try_one_account.yml 이 statuses 와 같은 순서로 쌓는
    `_rf_auth_observations` 도 함께 만들어 실제 실행과 같은 입력을 준다.
    """
    # 2026-08-12 (audit C-2): 분모는 **표준 후보** 수다. `_rf_auth_statuses` 가
    #   표준 후보에서만 쌓이므로(try_one_account.yml 의 loop 대상이 `_rf_standard_accounts`)
    #   분모도 같은 배열이어야 한다. 종전에는 표준+복구 병합 배열을 셌고, 그래서
    #   복구 후보가 하나라도 있으면 auth_success 가 영영 false 로 확정되지 못했다.
    accounts = [{"label": f"c{i}", "role": "primary"} for i in range(candidates)]
    rejected = _render(_REJECT_TASK,
                       {"_rf_auth_statuses": statuses,
                        "_rf_standard_accounts": accounts,
                        # 복구 후보가 섞여 있어도 판정이 흔들리지 않아야 한다.
                        "_rf_accounts": accounts + [{"label": "rec", "role": "recovery"}]})
    observations = [{"role": "primary", "label": f"c{i}", "status": st}
                    for i, st in enumerate(statuses)]
    diag = render_redfish_rescue({"_diagnosis": dict(_PRECHECK_OK),
                                  "_rf_collect_ok": collect_ok,
                                  "_rf_auth_rejected": rejected,
                                  "_rf_auth_observations": observations})
    return rejected, diag


# ═══════════════════════════════════════════════════════════════════════════
# 사용자 지정 8 조합
# ═══════════════════════════════════════════════════════════════════════════
CASES = [
    ("1. A 401 / B 401",              [401, 401],   2, False, None),
    ("2. A timeout / B 401",          [None, 401],  2, False, None),
    ("3. A 401 / B timeout",          [401, None],  2, False, None),
    ("4. A 403 / B 401",              [403, 401],   2, False, None),
    ("5. A 401 / B 403",              [401, 403],   2, False, None),
    ("6. A transport·TLS / B 401",    [None, 401],  2, False, None),
    ("7. A 401 / B 성공",             [401, 200],   2, True,  None),
    ("8. 단일 후보 401",              [401],        1, False, None),
]

# 기대: 1 과 8 만 false, 나머지는 null
EXPECTED_REJECTED = {"1. A 401 / B 401": True, "8. 단일 후보 401": True}


@pytest.mark.parametrize("label,statuses,candidates,collect_ok,_x", CASES,
                         ids=[c[0] for c in CASES])
def test_multi_credential_auth_success_aggregation(label, statuses, candidates,
                                                   collect_ok, _x):
    rejected, diag = _decide(statuses, candidates=candidates, collect_ok=collect_ok)
    expect_reject = EXPECTED_REJECTED.get(label, False)

    assert bool(rejected) is expect_reject, (
        f"[{label}] 집계 결과가 다르다 (statuses={statuses})")

    # 2026-08-11 (Phase 6-B / §26): 401 실증은 **기계 필드로만** 표현한다. 사용자 문장은
    # 거부/미확정 모두 4번(자격증명)으로 같다 — Portal 사용자의 조치가 같기 때문이다.
    if expect_reject:
        assert diag["auth_success"] is False, label
        assert diag["failure_stage"] == "auth", label
        assert diag["failure_code"] == "AUTH_PROBE_FAILED", label
    elif collect_ok or any(isinstance(s, int) and 200 <= s < 400 for s in statuses):
        # 자격을 실은 요청이 통과한 직접 관측 — 인증은 됐고 그 뒤에서 실패한 것이다
        assert diag["auth_success"] is True, label
        assert diag["failure_stage"] == "gather", label
    else:
        assert diag["auth_success"] is None, (
            f"[{label}] 원인 미확정 실패가 섞였는데 거부로 확정하면 안 된다")
    if not collect_ok and not any(isinstance(s, int) and 200 <= s < 400 for s in statuses):
        assert diag["failure_reason"] == FAILURE_REASONS["_fr_credential_failed"], label
    assert "인증이 거부" not in diag["failure_reason"], label

    _assert_grid_ready(diag["failure_reason"], label)
    _assert_claims_match_observation(diag, label)


def test_case7_success_path_does_not_reach_rescue():
    """조합 7 은 후보 B 가 성공했으므로 수집이 성공한다.

    성공 경로는 rescue 로 오지 않고 site.yml 이 auth_success=true 로 덮어쓴다.
    여기서는 **혹시 rescue 로 오더라도** 거부로 확정하지 않는 것만 고정한다.
    """
    rejected, diag = _decide([401, 200], candidates=2, collect_ok=True)
    assert bool(rejected) is False
    # 2026-08-12: 후보 B 가 200 으로 인증을 통과한 것을 실제로 관측했다.
    #   종전에는 이 경우도 auth_success=null 이었는데, 관측된 성공을 '모름' 으로 두면
    #   문장("대상 접속은 확인됐지만")과 Boolean 이 서로 다른 이야기를 한다.
    assert diag["auth_success"] is True
    # 수집이 된 뒤의 실패는 5번 문구(수집 실패)를 쓴다.
    assert diag["failure_reason"] == FAILURE_REASONS["_fr_gather_failed"]
    assert diag["failure_stage"] == "gather"


# ═══════════════════════════════════════════════════════════════════════════
# 경계 조건
# ═══════════════════════════════════════════════════════════════════════════
def test_no_candidates_never_rejects():
    """빈 자격 경로(무자격 요청)의 401 은 '등록된 자격증명 거부' 가 아니다."""
    rejected, diag = _decide([], candidates=0)
    assert bool(rejected) is False
    assert diag["auth_success"] is None


def test_missing_observation_never_rejects():
    """후보 수보다 관측이 적으면(누락) 확정하지 않는다."""
    rejected, _ = _decide([401], candidates=2)
    assert bool(rejected) is False


def test_extra_observation_never_rejects():
    """관측이 후보 수보다 많아도(예상 밖 상태) 확정하지 않는다."""
    rejected, _ = _decide([401, 401, 401], candidates=2)
    assert bool(rejected) is False


@pytest.mark.parametrize("statuses", [
    [200], [403], [500], [503], [None], [0], [404],
    [401, 500], [500, 401], [401, None, 401],
])
def test_any_non_401_blocks_rejection(statuses):
    rejected, _ = _decide(statuses, candidates=len(statuses))
    assert bool(rejected) is False, statuses


@pytest.mark.parametrize("count", [1, 2, 3, 5])
def test_all_401_rejects_for_any_candidate_count(count):
    rejected, diag = _decide([401] * count, candidates=count)
    assert bool(rejected) is True
    assert diag["auth_success"] is False


# ═══════════════════════════════════════════════════════════════════════════
# "첫 인증 응답" 의미 — 인증 성공 후의 401 은 승격되지 않는다
# ═══════════════════════════════════════════════════════════════════════════
def test_401_after_successful_auth_is_not_recorded(monkeypatch):
    """첫 요청 200(인증 통과) → 이후 하위 리소스 401 이어도 관측값은 200 이다."""
    rg._reset_auth_observation()
    seq = iter([200, 401, 401])
    monkeypatch.setattr(rg, "_get_impl", lambda *_a, **_k: (next(seq), {}, None))

    for path in ("Systems", "Systems/1/Storage", "AccountService"):
        rg._get("192.0.2.10", path, "u", "p", 5, False)

    assert rg.auth_evidence()["first_auth_status"] == 200, (
        "인증 통과 뒤의 권한·리소스 401 을 Credential 실패로 승격하면 안 된다")

    rejected, diag = _decide([rg.auth_evidence()["first_auth_status"]], candidates=1)
    assert bool(rejected) is False
    # 2026-08-12: 첫 인증 요청이 200 이었다 = 인증 통과를 직접 관측했다. 따라서
    #   auth_success=true 이고 멈춘 단계는 gather 다. "하위 리소스 401 을 credential
    #   실패로 승격하지 않는다" 는 원래 취지는 그대로 유지된다 (거부 확정 안 함).
    assert diag["auth_success"] is True
    assert diag["failure_stage"] == "gather"
    rg._reset_auth_observation()


def test_first_status_is_the_credentialed_request(monkeypatch):
    """무인증 ServiceRoot 가 앞서 나가도 기록되는 것은 자격증명 요청의 status 다."""
    rg._reset_auth_observation()

    class _Resp:
        status = 200

        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr(rg.urlreq, "urlopen", lambda *_a, **_k: _Resp())
    rg._get_noauth("192.0.2.10", "", 5, False)          # 무인증 — 기록 안 됨
    assert rg.auth_evidence()["first_auth_status"] is None

    monkeypatch.setattr(rg, "_get_impl", lambda *_a, **_k: (401, {}, None))
    rg._get("192.0.2.10", "Systems", "u", "p", 5, False)  # 인증 — 기록됨
    assert rg.auth_evidence()["first_auth_status"] == 401
    rg._reset_auth_observation()


def test_no_string_parsing_in_aggregation():
    """§18 — 집계는 정수 비교만 한다."""
    text = (REPO / _SITE).read_text(encoding="utf-8")
    block = text.split(_REJECT_TASK)[1].split("- name:")[0]
    assert "select('equalto', 401)" in block
    for banned in ("'HTTP 401'", '"HTTP 401"', "regex_search", "search(", "in msg"):
        assert banned not in block, banned


# ═══════════════════════════════════════════════════════════════════════════
# audit C-2 회귀 — 복구 후보가 있어도 401 실증이 사라지면 안 된다
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("recovery_count", [0, 1, 4])
def test_recovery_candidates_do_not_erase_the_401_evidence(recovery_count):
    """복구 후보 수가 몇이든 표준 후보가 전부 401 이면 인증 거부로 확정된다.

    2026-08-12 (audit C-2): 분모를 표준+복구 병합 배열로 세는 바람에, **복구가 가능한
    상황에서만** (=복구 후보가 존재할 때만) auth_success 가 null 로 남았다. 계정 쓰기를
    정당화한 바로 그 401 이 결과에 안 남는, 가장 필요한 자리에서 진단이 비는 구조였다.
    실제 Dell 구성이 표준 1 + 복구 4 라 이 경로가 상시 발동했다.
    """
    standard = [{"label": "std", "role": "primary"}]
    recovery = [{"label": f"rec{i}", "role": "recovery"} for i in range(recovery_count)]
    rejected = _render(_REJECT_TASK, {
        "_rf_auth_statuses": [401],
        "_rf_standard_accounts": standard,
        "_rf_accounts": standard + recovery,
    })
    assert bool(rejected) is True, (
        f"복구 후보 {recovery_count} 개 때문에 401 실증이 사라졌다")
