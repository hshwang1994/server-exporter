# scripts/env_guard.sh — 빌드 환경 경계 (2026-10-05, F05 · F12). 실행하지 않고 source 한다.
#
# scripts/run_gather.sh 가 ansible-playbook 직전에 `. scripts/env_guard.sh <addon_validated>` 로 부른다(Jenkinsfile_portal 서버 정보 수집 단계).
# Runner · 상위 환경(agent 프로세스 환경 · 노드 · 전역 변수)에서 넘어온 시험용 · 재정의 값이 운영 수집을 바꾸지 못하게 이번 셸에서 지운다.
# Jenkins withEnv 로 값을 넣지 않는 것만으로는 agent 프로세스에서 상속된 값이 남을 수 있다. 지운 **이름**만 한 줄로 남기고 값은 쓰지 않는다.
#
# 지우는 값
#   ADDON_DIR                      이 빌드가 검사를 통과시킨 Add-on 이 없을 때만 (인자 true 면 유지 — withEnv 가 검사한 경로를 넣었다)
#   SE_FORCE_LINUX_RAW_FALLBACK    Linux raw 경로 강제 (개발 · 검증용)
#   JSON_ONLY_NO_RECONCILE         콜백의 종료 보충 끄기
#   ANSIBLE_JSON_OUTPUT_TASK · ANSIBLE_JSON_CHECKPOINT_TASK   콜백이 결과를 잡는 태스크 이름
#   ANSIBLE_STDOUT_CALLBACK        결과 출력 콜백 (ansible.cfg 의 json_only 를 덮는다)
#   SE_VENDOR_ALIASES_PATH         Redfish vendor alias 파일 경로 재정의
#   (2026-10-05 8차 R1: 수집 시간 강제값 SE_FORCE_SEC 은 이제 어디서도 읽지 않는다 — 지울 대상에서도 뺐다)
#   (2026-10-06 9차: 메모리 기준 실행 제한을 없앴다 — 가용 메모리 시험 입력 SE_MEM_AVAILABLE_MB 도 어디서도 읽지 않아 지울 대상에서 뺐다)
#
# Jenkins 밖에서 ansible-playbook 을 직접 돌리는 운영 경로는 이 파일을 지나지 않는다 — ADDON_DIR 등을 직접 주는 계약은 그대로다.
# 회귀: tests/unit/test_env_guard.py (bash 로 실제 실행).

_se_guard_names="SE_FORCE_LINUX_RAW_FALLBACK JSON_ONLY_NO_RECONCILE ANSIBLE_JSON_OUTPUT_TASK ANSIBLE_JSON_CHECKPOINT_TASK ANSIBLE_STDOUT_CALLBACK SE_VENDOR_ALIASES_PATH"
if [ "${1:-false}" != "true" ]; then
    _se_guard_names="ADDON_DIR ${_se_guard_names}"
fi
_se_guard_cleared=""
for _se_guard_v in ${_se_guard_names}; do
    if printenv "${_se_guard_v}" >/dev/null 2>&1; then
        _se_guard_cleared="${_se_guard_cleared} ${_se_guard_v}"
        unset "${_se_guard_v}"
    fi
done
if [ -n "${_se_guard_cleared}" ]; then
    echo "[수집] 상위 환경에서 넘어온 시험용 설정을 이번 실행에서 지웠습니다:${_se_guard_cleared}"
fi
unset _se_guard_names _se_guard_cleared _se_guard_v
