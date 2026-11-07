#!/bin/bash
# zip 으로 보관된 전수 미러를 ext4 디렉터리로 푼다 (/mnt/c 에서 index.json 수천 개를 읽는 것보다 수십 배 빠르다).
# 사용: extract_mirrors.sh <dest_root> <zip ...>
#   예: extract_mirrors.sh /root/se_mirrors /mnt/c/<repo>/tests/reference/redfish/mock2/*.zip
set -e
DEST="${1:?usage: extract_mirrors.sh <dest_root> <zip ...>}"; shift
mkdir -p "$DEST"
cd "$DEST"
for z in "$@"; do
  echo "extract: $z"
  python3 -m zipfile -e "$z" .
done
find "$DEST" -maxdepth 2 -type d | sort
echo "files: $(find "$DEST" -type f | wc -l)"
du -sh "$DEST"
