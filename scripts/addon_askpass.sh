#!/bin/bash
# scripts/addon_askpass.sh — git 이 자격증명을 물을 때 환경변수로 답한다 (GIT_ASKPASS).
# Jenkinsfile_portal 이 SE_ADDON_CREDENTIALS_ID 가 있을 때만 withCredentials 로 SE_ADDON_USER / SE_ADDON_PASSWORD 를 넣고
# 이 파일을 GIT_ASKPASS 로 지정한다. git 은 프롬프트 문장을 첫 인자로 준다 ("Username for …" / "Password for …").
# 값이 없으면 빈 줄을 돌려준다 — git 이 인증 실패로 끝나고 빌드는 멈추지 않는다.
case "${1:-}" in
    *[Uu]sername*) printf '%s\n' "${SE_ADDON_USER:-}" ;;
    *)             printf '%s\n' "${SE_ADDON_PASSWORD:-}" ;;
esac
