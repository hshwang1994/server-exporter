
_se_guard_names="SE_FORCE_LINUX_RAW_FALLBACK JSON_ONLY_NO_RECONCILE ANSIBLE_JSON_OUTPUT_TASK ANSIBLE_JSON_CHECKPOINT_TASK ANSIBLE_STDOUT_CALLBACK SE_VENDOR_ALIASES_PATH SE_FORCE_SEC SE_MEM_AVAILABLE_MB"
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
