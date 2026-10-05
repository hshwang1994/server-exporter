#!/bin/bash
# scripts/addon_checkout.sh — Add-on 저장소를 이 빌드의 작업 공간에 받는다 (Jenkinsfile_portal Gather stage 가 부른다).
#
#   scripts/addon_checkout.sh <저장소 URL> <ref> <대상 디렉터리>
#
# ref 는 브랜치 이름 · refs/tags/<태그> · 전체(40자) 커밋 해시다. 세 형태를 같은 흐름으로 받는다.
#   1차: 그 ref 하나만 얕게(depth 1) fetch — 브랜치 · 태그 · 전체 해시 모두 fetch 대상이 된다
#   2차: 서버가 해시 직접 fetch 를 막으면 브랜치 · 태그 전체를 받아 그 안에서 해석한다
# 짧은 해시는 받지 않는다 — 서버에 따라 1차가 거부돼 결과가 갈리기 때문이다.
#
# 환경변수
#   ADDON_REPO_SSL_VERIFY  "true" 면 TLS 인증서를 검증한다. 그 밖(기본)에는 이 스크립트가 실행하는 git 명령에만
#                          -c http.sslVerify=false 를 붙인다 — 전역 git 설정 · 메인 저장소 체크아웃 · 다른 Job 에 영향이 없다.
#   GIT_ASKPASS 등         자격증명은 호출자가 git 이 아는 환경변수로 넘긴다. 이 스크립트는 자격증명을 읽지도 적지도 않는다.
#
# git 명령마다 180초 제한(timeout 이 있을 때) — 응답 없는 저장소가 빌드를 붙잡지 않는다.
# 대상 디렉터리는 시작할 때 지운다 — 이전 빌드의 파일이 남지 않는다.
# 성공: stdout 에 `[addon] <URL>@<ref> <해시>` 한 줄, rc 0. 실패: stderr 에 `[addon] unavailable: <사유>`, rc 1.
set -u

repo="${1:-}"
ref="${2:-}"
dest="${3:-}"

fail() {
    echo "[addon] unavailable: $*" >&2
    exit 1
}

[ -n "$repo" ] && [ -n "$ref" ] && [ -n "$dest" ] || fail "사용법: addon_checkout.sh <저장소 URL> <ref> <대상 디렉터리>"
case "$repo" in -*) fail "저장소 URL 형식 오류: '$repo'";; esac
case "$ref" in
    -*|*..*|*' '*|*'	'*) fail "ref 형식 오류: '$ref' (브랜치 · refs/tags/<태그> · 40자 커밋 해시)";;
esac
if printf '%s' "$ref" | grep -Eq '^[0-9a-fA-F]{4,39}$'; then
    fail "커밋은 40자 전체 해시로 적습니다: '$ref'"
fi
command -v git >/dev/null 2>&1 || fail "git 이 없습니다"

opts=()
if [ "${ADDON_REPO_SSL_VERIFY:-false}" != "true" ]; then
    opts=(-c http.sslVerify=false)
fi
export GIT_TERMINAL_PROMPT=0          # 자격증명이 없으면 묻지 않고 실패한다 (빌드가 멈추지 않는다)
# Add-on 저장소 받기의 상한 — 2026-10-05 (8차 R3): 180 → 1800초. 수집을 시작하기 전의 준비 단계라 상한은 둔다
#   (Git 서버가 응답하지 않으면 수집 자체가 시작하지 못한다). 정상 받기(수 초)보다 충분히 길게 둔다.
tmo=()
if command -v timeout >/dev/null 2>&1; then
    tmo=(timeout 1800)
fi

err="$(mktemp)"
trap 'rm -f "$err"' EXIT
reason() {   # git stderr 의 마지막 의미 있는 줄
    grep -v '^\s*$' "$err" | tail -n 1 | tr -d '\r'
}

rm -rf -- "$dest" && mkdir -p -- "$dest" || fail "디렉터리를 준비하지 못했습니다: $dest"
git -C "$dest" init -q 2>"$err" || fail "git init 실패: $(reason)"
git -C "$dest" remote add origin "$repo" 2>"$err" || fail "저장소 URL 을 등록하지 못했습니다: $(reason)"

if "${tmo[@]}" git -C "$dest" "${opts[@]}" fetch -q --depth 1 origin "$ref" 2>"$err"; then
    git -C "$dest" checkout -q --detach FETCH_HEAD 2>"$err" || fail "checkout 실패: $(reason)"
else
    first="$(reason)"
    "${tmo[@]}" git -C "$dest" "${opts[@]}" fetch -q origin \
        '+refs/heads/*:refs/remotes/origin/*' '+refs/tags/*:refs/tags/*' 2>"$err" \
        || fail "저장소를 받지 못했습니다 (${repo}@${ref}): ${first:-$(reason)}"
    sha="$(git -C "$dest" rev-parse --verify -q "${ref}^{commit}" \
        || git -C "$dest" rev-parse --verify -q "origin/${ref#refs/heads/}^{commit}")" \
        || fail "ref 를 찾지 못했습니다: '${ref}' (${first})"
    git -C "$dest" checkout -q --detach "$sha" 2>"$err" || fail "checkout 실패: $(reason)"
fi

echo "[addon] ${repo}@${ref} $(git -C "$dest" rev-parse HEAD)"
