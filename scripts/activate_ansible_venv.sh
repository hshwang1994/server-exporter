#!/bin/bash

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
