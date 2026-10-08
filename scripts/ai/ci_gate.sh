#!/bin/bash
# scripts/ai/ci_gate.sh — main 의 오프라인 검증 gate (하네스 소유, production 제외).
#
# 왜 있나: Jenkins 의 Validate Schema stage(tests/validate_field_dictionary.py 정적 검사)가 수집 파이프라인에서
#   빠지면서, 같은 검사와 오프라인 회귀를 커밋 전 / CI 에서 한 명령으로 돌리기 위한 진입점이다.
#   Jenkinsfile_ci · pre-commit · 로컬이 모두 이 스크립트를 부른다 — 검사 목록은 여기 한 곳에만 둔다.
#
# 사용:
#   bash scripts/ai/ci_gate.sh            # 전부
#   CI_GATE_SKIP_PYTEST=1 bash scripts/ai/ci_gate.sh    # 정적 검사만
#   CI_GATE_PYTEST_ARGS="-x" bash scripts/ai/ci_gate.sh # pytest 추가 인자
#   CI_GATE_SKIP_CORPUS=1 bash scripts/ai/ci_gate.sh    # finalize corpus(Layer A oracle 대조) 건너뜀 — PARTIAL
#   CI_GATE_JUNIT_DIR=<dir> bash scripts/ai/ci_gate.sh  # pytest 실행 기록(JUnit)을 <dir>/ci_gate_junit_{unit,integration}.xml 로 남긴다 —
#                                                       # CI 의 Time Limits 단계가 같은 실행의 시험 ID 를 대조한다(2026-10-08). 비우면 남기지 않는다
#
# 종료 코드: 0 = 전부 통과, 1 = 하나라도 실패, 2 = 환경 부족으로 건너뛴 단계가 있음(통과 아님 — 보고에 "부분 실행" 으로 적는다)
set -uo pipefail
cd "$(dirname "$0")/../.."

# Python 선택: 실제로 실행되는 것만 고른다 (Windows Git Bash 의 `python3` 는 스토어 설치 안내 스텁일 수 있다 — rc 49).
PY=${PYTHON:-}
if [ -z "$PY" ]; then
    for cand in python3 python; do
        if "$cand" -c "import sys; sys.exit(0)" >/dev/null 2>&1; then PY=$cand; break; fi
    done
fi
if [ -z "$PY" ]; then echo "[ci_gate] 실행할 수 있는 python이 없습니다. PYTHON=<경로>로 지정하세요."; exit 1; fi
echo "[ci_gate] python: $("$PY" -c 'import sys; print(sys.executable, sys.version.split()[0])')"

fail=0
skipped=0
step() { echo; echo "== [ci_gate] $1"; }
run()  { "$@"; local rc=$?; if [ $rc -ne 0 ]; then echo "-- [ci_gate] FAIL (rc=$rc): $*"; fail=1; fi; }

step "python compile (plugins / libraries / scripts)"
run "$PY" -m compileall -q callback_plugins filter_plugins lookup_plugins module_utils common/library redfish-gather/library esxi-gather/library scripts

step "field_dictionary 검사"
run "$PY" tests/validate_field_dictionary.py

step "output schema drift"
run "$PY" scripts/ai/hooks/output_schema_drift_check.py

step "vendor boundary / harness consistency"
run "$PY" scripts/ai/verify_vendor_boundary.py
run "$PY" scripts/ai/verify_harness_consistency.py

step "finalize corpus (결과 정리 결과를 정답지와 비교)"
if [ "${CI_GATE_SKIP_CORPUS:-0}" = "1" ]; then
    echo "-- [ci_gate] corpus skipped (CI_GATE_SKIP_CORPUS=1)"; skipped=1
elif [ -f tests/scripts/finalize_corpus_check.py ] && [ -d tests/fixtures/finalize_corpus ]; then
    run "$PY" tests/scripts/finalize_corpus_check.py
else
    echo "-- [ci_gate] 건너뜀: tests/fixtures/finalize_corpus 또는 검사 스크립트가 없습니다."; skipped=1
fi

if [ "${CI_GATE_SKIP_PYTEST:-0}" != "1" ]; then
    step "pytest offline (unit, e2e, regression, integration -m 'not live')"
    if "$PY" -m pytest --version >/dev/null 2>&1; then
        # tests/e2e_browser 는 playwright 가 필요한 브라우저 테스트라 여기서 돌리지 않는다.
        # tests/integration 은 따로 돈다 — e2e 와 integration 이 각자 `conftest` 를 rootdir 모듈로 import 해 한 세션에서 이름이 충돌한다.
        JUNIT_MAIN=(); JUNIT_INT=()
        if [ -n "${CI_GATE_JUNIT_DIR:-}" ]; then
            JUNIT_MAIN=(--junitxml "$CI_GATE_JUNIT_DIR/ci_gate_junit_unit.xml")
            JUNIT_INT=(--junitxml "$CI_GATE_JUNIT_DIR/ci_gate_junit_integration.xml")
        fi
        run "$PY" -m pytest tests/unit tests/e2e tests/regression -q -p no:cacheprovider ${JUNIT_MAIN[@]+"${JUNIT_MAIN[@]}"} ${CI_GATE_PYTEST_ARGS:-}
        run "$PY" -m pytest tests/integration -m "not live" -q -p no:cacheprovider ${JUNIT_INT[@]+"${JUNIT_INT[@]}"} ${CI_GATE_PYTEST_ARGS:-}
    else
        echo "-- [ci_gate] 건너뜀: 이 python에 pytest가 없습니다. requirements-test.txt를 설치한 뒤 다시 실행하세요."; skipped=1
    fi
else
    echo "-- [ci_gate] pytest skipped (CI_GATE_SKIP_PYTEST=1)"; skipped=1
fi

step "ansible-playbook --syntax-check (3 채널)"
# Windows 의 ansible 은 지원되지 않는다(실행 시 WinError). 실제로 --version 이 도는 환경(WSL/Linux Runner)에서만 돌린다.
if ansible-playbook --version >/dev/null 2>&1; then
    export ANSIBLE_CONFIG="$PWD/ansible.cfg"
    # 실제 inventory 스크립트로 확인한다(prodgen G11 과 같은 방식, TEST-NET 대상 1개). ansible.cfg 는 script · auto 플러그인만 켜서
    #   `-i localhost,` 같은 목록 인벤토리는 해석되지 않는다(경고만 내고 지나갔다 — 2026-10-05 CI #21 에서 확인).
    for ch in os-gather esxi-gather redfish-gather; do
        case "$ch" in redfish-gather) inv='[{"bmc_ip":"192.0.2.1"}]' ;; *) inv='[{"service_ip":"192.0.2.1"}]' ;; esac
        run env INVENTORY_JSON="$inv" REPO_ROOT="$PWD" ansible-playbook --syntax-check -i "$ch/inventory.sh" "$ch/site.yml"
    done
else
    echo "-- [ci_gate] 건너뜀: 실행할 수 있는 ansible-playbook이 없어 syntax-check를 하지 않았습니다. WSL이나 Runner에서 실행하세요."; skipped=1
fi

echo
if [ $fail -ne 0 ]; then echo "[ci_gate] RESULT: FAIL"; exit 1; fi
if [ $skipped -ne 0 ]; then echo "[ci_gate] RESULT: PARTIAL (건너뛴 단계가 있어 통과로 보지 않습니다)"; exit 2; fi
echo "[ci_gate] RESULT: PASS"
