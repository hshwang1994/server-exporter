#!/bin/bash
# WSL(root distro) 안에서 zip 들을 /root/se_mirrors 로 푼다 (ext4 — /mnt/c 보다 수십 배 빠르다)
set -e
SP_L="$1"
mkdir -p /root/se_mirrors
cd /root/se_mirrors
for z in "$SP_L"/archive/*.zip "$SP_L"/archive_mock1/mock1.zip; do
  echo "extract: $z"
  python3 -m zipfile -e "$z" .
done
find /root/se_mirrors -maxdepth 2 -type d | sort
echo "files: $(find /root/se_mirrors -type f | wc -l)"
du -sh /root/se_mirrors
