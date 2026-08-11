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
    _assert_claims_match_observation,
    _assert_grid_ready,
    _env,
    _task_by_name,
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
    return env.from_string(tpl[key]).render(**ctx)


def _decide(statuses: list[Any], *, candidates: int, collect_ok: bool = False):
    """후보별 관측 리스트 → (auth_rejected, diagnosis)."""
    accounts = [{"label": f"c{i}"} for i in range(candidates)]
    rejected = _render(_REJECT_TASK,
                       {"_rf_auth_statuses": statuses, "_rf_accounts": accounts})
    diag = _render(_DIAG_TASK,
                   {"_diagnosis": dict(_PRECHECK_OK),
                    "_rf_collect_ok": collect_ok,
                    "_rf_auth_rejected": rejected})
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

    if expect_reject:
        assert diag["auth_success"] is False, label
        assert diag["failure_stage"] == "auth", label
        assert diag["failure_code"] == "AUTH_PROBE_FAILED", label
        assert "인증이 거부되었습니다" in diag["failure_reason"], label
    else:
        assert diag["auth_success"] is None, (
            f"[{label}] 원인 미확정 실패가 섞였는데 거부로 확정하면 안 된다")
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
    assert diag["auth_success"] is None
    assert "정보 수집 후 결과를 처리하는 중" in diag["failure_reason"]


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
    assert diag["auth_success"] is None
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
