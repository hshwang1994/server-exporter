#!/usr/bin/env bash
# scripts/ai/prodgen/ci_pwsh_bootstrap.sh — PowerShell 파서(pwsh) 를 **사용자 권한**으로 준비한다 (2026-10-04, Astra 3차 §7 / 4차).
#
# prodgen 의 PowerShell 주석 제거 검증은 실제 PowerShell 파서가 필요하다(없으면 Windows task 의 주석이 class B 로 남아 승격이 막힌다 — GP-16).
# Runner 에 pwsh 가 없고 root 도 없을 때, PowerShell 의 tar.gz 배포본을 $HOME/.local/powershell 에 풀어 PATH 앞에 둔다.
# 시스템 변경 없음 · 패키지 설치 없음 · 다른 사용자 영향 없음. 다운로드 원천은 GitHub 릴리스(Runner 가 main checkout 에 GitHub 를 쓴다).
#
#   eval "$(bash scripts/ai/prodgen/ci_pwsh_bootstrap.sh --env)"   # PATH 와 DOTNET_SYSTEM_GLOBALIZATION_INVARIANT 를 export 하는 문장을 출력
#   bash scripts/ai/prodgen/ci_pwsh_bootstrap.sh --check            # 상태만 출력 (0 = pwsh 사용 가능)
#
# 환경변수: PRODGEN_PWSH_VERSION(기본 7.4.6) · PRODGEN_PWSH_HOME(기본 $HOME/.local/powershell) · PRODGEN_PWSH_URL(기본 GitHub 릴리스)
set -u
VERSION="${PRODGEN_PWSH_VERSION:-7.4.6}"
HOME_DIR="${PRODGEN_PWSH_HOME:-$HOME/.local/powershell}"
URL="${PRODGEN_PWSH_URL:-https://github.com/PowerShell/PowerShell/releases/download/v${VERSION}/powershell-${VERSION}-linux-x64.tar.gz}"
MODE="${1:---env}"

emit_env() {
    # ICU 가 없는 Runner 에서도 토크나이저가 돌도록 invariant globalization 을 켠다 (주석 토큰화에는 culture 가 필요 없다).
    echo "export PATH=\"${HOME_DIR}:\$PATH\""
    echo "export DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1"
    echo "export POWERSHELL_TELEMETRY_OPTOUT=1"
}

have_pwsh() {
    command -v pwsh >/dev/null 2>&1 || [ -x "${HOME_DIR}/pwsh" ]
}

if [ "$MODE" = "--check" ]; then
    if command -v pwsh >/dev/null 2>&1; then echo "pwsh=system $(command -v pwsh)"; exit 0; fi
    if [ -x "${HOME_DIR}/pwsh" ]; then echo "pwsh=user ${HOME_DIR}/pwsh"; exit 0; fi
    echo "pwsh=absent"; exit 1
fi

if ! have_pwsh; then
    mkdir -p "${HOME_DIR}" || { echo "# pwsh bootstrap: cannot create ${HOME_DIR}" >&2; emit_env; exit 0; }
    TMP="$(mktemp)"
    if curl -fsSL --max-time 600 -o "${TMP}" "${URL}" 2>/dev/null && tar -xzf "${TMP}" -C "${HOME_DIR}" 2>/dev/null; then
        chmod +x "${HOME_DIR}/pwsh" 2>/dev/null || true
        echo "# pwsh bootstrap: installed PowerShell ${VERSION} (user-level) into ${HOME_DIR}" >&2
    else
        echo "# pwsh bootstrap: download/extract failed from ${URL} — PowerShell comments will stay class B (build blocked by design)" >&2
    fi
    rm -f "${TMP}"
fi
emit_env
exit 0
