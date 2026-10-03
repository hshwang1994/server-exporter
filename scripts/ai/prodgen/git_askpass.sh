#!/usr/bin/env bash
# scripts/ai/prodgen/git_askpass.sh — GIT_ASKPASS helper for prodgen pushes from CI (2026-10-04).
#
# git calls this with one prompt argument, e.g. "Username for 'https://github.com': " or "Password for 'https://user@10.100.64.156': ".
# The answer comes from environment variables bound by Jenkins withCredentials — nothing is written to disk and nothing is echoed
# except the requested value on stdout (to git).
#   GitHub : PRODGEN_GIT_USER_GITHUB / PRODGEN_GIT_PASSWORD_GITHUB
#   GitLab : PRODGEN_GIT_USER_GITLAB / PRODGEN_GIT_PASSWORD_GITLAB   (host 10.100.64.156)
#   fallback: PRODGEN_GIT_USER / PRODGEN_GIT_PASSWORD
# Use with GIT_TERMINAL_PROMPT=0 so a missing credential fails fast instead of hanging.
set -u
prompt="${1:-}"
host="generic"
case "$prompt" in
    *10.100.64.156*) host="gitlab" ;;
    *github.com*)    host="github" ;;
esac

pick() {   # pick <kind: USER|PASSWORD> — indirect expansion of PRODGEN_GIT_<kind>_<HOST>, then the generic fallback
    local kind="$1" var="" v=""
    case "$host" in
        github) var="PRODGEN_GIT_${kind}_GITHUB" ;;
        gitlab) var="PRODGEN_GIT_${kind}_GITLAB" ;;
    esac
    if [ -n "$var" ]; then
        v="${!var:-}"
    fi
    if [ -z "$v" ]; then
        var="PRODGEN_GIT_${kind}"
        v="${!var:-}"
    fi
    printf '%s\n' "$v"
}

case "$prompt" in
    Username*|username*) pick USER ;;
    Password*|password*) pick PASSWORD ;;
    *) exit 1 ;;
esac
