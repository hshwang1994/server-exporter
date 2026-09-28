#!/bin/bash
# =============================================================================
# scripts/activate_ansible_venv.sh — Ansible 실행환경(venv) 선택 규칙 (source 전용)
# =============================================================================
# Jenkins Stage 와 운영 스크립트가 "어느 venv 를 쓸지" 를 정하는 유일한 곳이다.
# 파이프라인은 서버마다 다른 venv 절대경로를 직접 적지 않고 이 파일을 한 줄로 source 한다.
#
#   . "${WORKSPACE}/scripts/activate_ansible_venv.sh" || exit 1
#
# 선택 순서 (앞에서 정해지면 뒤는 보지 않는다):
#   1. SE_ANSIBLE_VENV            노드/전역 환경변수로 명시한 venv 루트. 값이 있는데 그 안에
#                                 bin/activate 가 없으면 다른 곳으로 넘어가지 않고 실패한다.
#   2. PATH 의 ansible-playbook   실경로(readlink -f) 옆에 activate 가 있으면 그 venv.
#                                 설치 자동화 Runner 는 /usr/local/bin/ansible-* 을 venv 로 링크한다.
#                                 ~/.local/bin 의 pip 설치본이나 /usr/bin 의 rpm 설치본은 activate 가
#                                 없어 채택되지 않는다.
#   3. 알려진 설치 경로 후보       /app/ansible-env (설치 자동화 새 배치) → /opt/ansible-env (옛 배치).
#                                 저장소에서 venv 절대경로가 남는 곳은 이 목록뿐이고 마지막 순위다.
#                                 SE_ANSIBLE_VENV_CANDIDATES 로 목록을 바꿀 수 있다(공백 구분, 테스트용).
#   4. 전부 없으면 확인한 값을 stderr 에 적고 실패한다 — 시스템 python 으로 조용히 넘어가지 않는다.
#
# 활성화 뒤에는 PATH 의 python3 이 venv 안의 것인지 한 번 더 확인한다.
# 성공하면 "[venv] <경로> python=<버전> (source=env|path|known)" 한 줄을 stderr 로 남긴다.
#
# 제약: 호출자의 set -e/-u/-x, trap, 작업 디렉터리를 바꾸지 않는다. 변수는 ${VAR:-} 로만 읽는다.
#       source 하면 return 1, 직접 실행하면 exit 1 로 실패를 알린다. 두 번 source 해도 무해하다.
# =============================================================================

_se_venv_select() {
    local _se_dir='' _se_how='' _se_ap='' _se_real='' _se_bindir='' _se_cand='' _se_py=''
    local _se_known="${SE_ANSIBLE_VENV_CANDIDATES-/app/ansible-env /opt/ansible-env}"

    if [ -n "${SE_ANSIBLE_VENV:-}" ]; then
        _se_dir="${SE_ANSIBLE_VENV%/}"
        if [ ! -f "${_se_dir}/bin/activate" ]; then
            echo "[venv] SE_ANSIBLE_VENV='${SE_ANSIBLE_VENV}' 안에 bin/activate 가 없습니다 — 노드 환경변수 값을 확인하십시오 (다른 경로로 넘어가지 않습니다)" >&2
            return 1
        fi
        _se_how=env
    else
        _se_ap="$(command -v ansible-playbook 2>/dev/null || true)"
        if [ -n "${_se_ap}" ] && command -v readlink >/dev/null 2>&1; then
            _se_real="$(readlink -f -- "${_se_ap}" 2>/dev/null || true)"
            _se_bindir="${_se_real%/*}"
            if [ -n "${_se_real}" ] && [ -f "${_se_bindir}/activate" ]; then
                _se_dir="${_se_bindir%/bin}"
                _se_how=path
            fi
        fi
        if [ -z "${_se_dir}" ]; then
            # shellcheck disable=SC2086  # 공백 구분 목록을 의도적으로 단어 분리한다
            for _se_cand in ${_se_known}; do
                if [ -f "${_se_cand%/}/bin/activate" ]; then
                    _se_dir="${_se_cand%/}"
                    _se_how=known
                    break
                fi
            done
        fi
    fi

    if [ -z "${_se_dir}" ] || [ ! -f "${_se_dir}/bin/activate" ]; then
        echo "[venv] Ansible 실행환경(venv)을 찾지 못했습니다 — Runner 설치(install-jenkins-runner)를 확인하거나 노드 환경변수 SE_ANSIBLE_VENV=<venv 루트> 를 등록하십시오" >&2
        echo "[venv]   SE_ANSIBLE_VENV='${SE_ANSIBLE_VENV:-}' | PATH 의 ansible-playbook='${_se_ap:-없음}' (실경로 '${_se_real:-}') | 후보='${_se_known}'" >&2
        echo "[venv]   PATH='${PATH:-}'" >&2
        return 1
    fi

    # shellcheck disable=SC1091
    if ! . "${_se_dir}/bin/activate"; then
        echo "[venv] ${_se_dir}/bin/activate 를 읽지 못했습니다" >&2
        return 1
    fi

    _se_py="$(command -v python3 2>/dev/null || true)"
    case "${_se_py}" in
        "${VIRTUAL_ENV:-/nonexistent}/bin/python3") ;;
        *)
            echo "[venv] 활성화 뒤에도 python3 이 venv 밖입니다: python3='${_se_py:-없음}' VIRTUAL_ENV='${VIRTUAL_ENV:-}'" >&2
            return 1
            ;;
    esac

    echo "[venv] ${VIRTUAL_ENV} python=$(python3 --version 2>&1) (source=${_se_how})" >&2
    return 0
}

_se_venv_select
_se_venv_rc=$?
unset -f _se_venv_select
if [ "${_se_venv_rc}" -ne 0 ]; then
    unset _se_venv_rc
    return 1 2>/dev/null || exit 1
fi
unset _se_venv_rc
