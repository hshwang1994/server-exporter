#!/bin/bash
# Tier 1 미러 준비 (Ubuntu-24.04 root). 2차 11대 = 저장소 zip(SHA256SUMS 확인) 추출, 1차 7대 = 원본 폴더 복사(원본은 읽기만).
# 출력: 미러별 파일 수 · 내용 digest(정렬된 sha256sum 목록의 sha256) — 1차는 원본과 사본을 둘 다 계산해 같음을 확인한다.
set -euo pipefail
M=/root/se_mirrors_fix_20261028
REPO=/mnt/c/github/ClovirONE/clovirone-server-gathering
SRC1="/mnt/c/github/서버mock데이터/1차"
OUT="${1:?usage: prep_mirrors.sh <digest out file (linux path)>}"

if [ -e "$M" ]; then echo "already exists: $M (중단 — 덮어쓰지 않는다)"; exit 2; fi

( cd "$REPO/tests/reference/redfish/mock2" && sha256sum -c SHA256SUMS )
bash "$REPO/tests/redfish-probe/mirror_replay/extract_mirrors.sh" "$M" "$REPO"/tests/reference/redfish/mock2/*.zip

declare -a R1=("DELL_R740/01" "HPE_CSUS3200/01" "HPE_CSUS3200/02" "HPE_CSUS3200/03" "HPE_CSUS3200/04" "HPE_DL380/01" "Lenovo_SR650/01")
for rel in "${R1[@]}"; do
  mkdir -p "$M/mock1/$(dirname "$rel")"
  cp -a "$SRC1/$rel" "$M/mock1/$rel"
done

digest() { ( cd "$1" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | cut -c1-64 ); }
count() { find "$1" -type f | wc -l; }

{
  echo "# mirror digests (sha256 of LC_ALL=C sorted 'sha256sum' list) — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "## 2nd round (extracted from tests/reference/redfish/mock2/*.zip, SHA256SUMS OK)"
  for d in "$M"/csus3200_0* "$M"/dl380_gen12_0* "$M"/sr650_v4_0*; do
    echo "$(basename "$d") files=$(count "$d") digest=$(digest "$d")"
  done
  echo "## 1st round (copied from external folder; source digest == copy digest required)"
  for rel in "${R1[@]}"; do
    s=$(digest "$SRC1/$rel"); c=$(digest "$M/mock1/$rel")
    st=SAME; [ "$s" = "$c" ] || st=DIFF
    echo "mock1/$rel files=$(count "$M/mock1/$rel") src=$s copy=$c $st"
  done
} > "$OUT"
cat "$OUT"
