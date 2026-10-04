#!/bin/bash
case "${1:-}" in
    *[Uu]sername*) printf '%s\n' "${ADDON_REPO_USER:-}" ;;
    *)             printf '%s\n' "${ADDON_REPO_PASSWORD:-}" ;;
esac
