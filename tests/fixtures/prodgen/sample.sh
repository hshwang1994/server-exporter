#!/bin/bash
# sample.sh — prodgen golden fixture (standalone shell)
# shellcheck disable=SC2034  # tool directives are removable
set -u

name="${1:-}"            # trailing comment
count=${#name}           # ${#var} is a length expansion, not a comment
echo "$# positional"     # $# is the argument count
printf '%s\n' '# literal hash in single quotes' "# literal hash in double quotes"
cat <<'EOF'
# inside a heredoc: data, not a comment
EOF
awk 'BEGIN { print "#awk" }   # inside single quotes
'
case "$name" in
  \#*) echo "escaped hash pattern" ;;   # trailing after case arm
  *) echo "other" ;;
esac
# final comment
