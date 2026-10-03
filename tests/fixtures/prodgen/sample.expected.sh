#!/bin/bash
set -u

name="${1:-}"
count=${#name}
echo "$# positional"
printf '%s\n' '# literal hash in single quotes' "# literal hash in double quotes"
cat <<'EOF'
# inside a heredoc: data, not a comment
EOF
awk 'BEGIN { print "#awk" }   # inside single quotes
'
case "$name" in
  \#*) echo "escaped hash pattern" ;;
  *) echo "other" ;;
esac
