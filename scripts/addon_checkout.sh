#!/bin/bash
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
export GIT_TERMINAL_PROMPT=0
tmo=()
if command -v timeout >/dev/null 2>&1; then
    tmo=(timeout 1800)
fi

err="$(mktemp)"
trap 'rm -f "$err"' EXIT
reason() {
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
