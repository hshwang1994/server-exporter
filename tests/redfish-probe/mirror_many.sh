#!/usr/bin/env bash
# 여러 BMC/RMC 를 동시에 미러링한다 (redfish_full_mirror.py v2 를 호스트마다 프로세스 1개로 실행).
#
# 사용:
#   read -rs -p "BMC password: " BMC_PW; echo; export BMC_PW
#   bash mirror_many.sh targets.txt
#
# targets.txt 한 줄 = 대상 하나:   IP[:PORT]  계정  출력폴더  [auth]
#   auth = auto(기본) | session | basic     HPE CSUS / Superdome RMC 처럼 Basic 전용 장비는 basic
#   # 로 시작하는 줄과 빈 줄은 무시한다. 비밀번호는 파일에 적지 않는다 (환경변수 BMC_PW).
#
# 환경변수:
#   BMC_PW        (필수) 비밀번호 - 자식 프로세스에는 --password-env 로만 전달한다 (ps 에 노출되지 않음)
#   MIRROR_JOBS   동시 실행 수 (기본 4)
#   MIRROR_ARGS   크롤러에 그대로 넘길 추가 인자 (예: "--resume --retries 5")
#   PYTHON        파이썬 (기본 python3, 없으면 /usr/libexec/platform-python)
#   MIRROR_PY     크롤러 경로 (기본: 이 스크립트 옆 redfish_full_mirror.py)
#
# 호스트별 로그는 <출력폴더>/_crawl.log, 종료코드는 <출력폴더>/_exit_code 에 남는다.
# 종료코드: 0 = 전부 COMPLETE, 1 = 그 외가 하나라도 있음, 2 = 사용법/환경 오류, 130 = 중단.
# bash 4.2+ 호환 (wait -n / mapfile -d 를 쓰지 않는다). xargs 도 필요 없다 (Rocky 8 최소 이미지).
set -u

here=$(cd "$(dirname "$0")" && pwd)
targets=${1:-targets.txt}
MIRROR_PY=${MIRROR_PY:-$here/redfish_full_mirror.py}
JOBS=${MIRROR_JOBS:-4}
EXTRA=${MIRROR_ARGS:-}

if [ -z "${PYTHON:-}" ]; then
  if command -v python3 >/dev/null 2>&1; then PYTHON=python3
  elif [ -x /usr/libexec/platform-python ]; then PYTHON=/usr/libexec/platform-python
  else echo "[CRIT] python3 를 찾을 수 없습니다 (PYTHON=... 로 지정)" >&2; exit 2; fi
fi
[ -f "$targets" ] || { echo "[CRIT] targets 파일이 없습니다: $targets" >&2; exit 2; }
[ -f "$MIRROR_PY" ] || { echo "[CRIT] 크롤러가 없습니다: $MIRROR_PY" >&2; exit 2; }
if [ -z "${BMC_PW:-}" ]; then
  echo "[CRIT] BMC_PW 환경변수가 비어 있습니다. 예: read -rs -p 'BMC password: ' BMC_PW; export BMC_PW" >&2
  exit 2
fi
export BMC_PW

declare -A ip_pid      # IP -> 실행 중인 pid (같은 IP 는 직렬화: BMC 세션 한도/잠금 카운터를 공유한다)
declare -A pid_out     # pid -> 출력 폴더
declare -A seen_out
all_pids=()
outdirs=()
lineno=0
skipped=0
interrupted=0

stop_children() {
  interrupted=1
  echo "[WARN] 중단 신호 - 크롤러에 종료를 전달합니다 (세션 로그아웃 뒤 종료)" >&2
  for p in $(jobs -rp); do kill -TERM "$p" 2>/dev/null; done
}
trap stop_children INT TERM

while IFS= read -r line || [ -n "$line" ]; do
  lineno=$((lineno + 1))
  [ "$interrupted" -eq 1 ] && break
  line=${line%$'\r'}
  case "$line" in ''|\#*) continue ;; esac
  IFS=$' \t' read -r ip user out auth rest <<< "$line"
  auth=${auth:-auto}
  if [ -z "$ip" ] || [ -z "$user" ] || [ -z "$out" ]; then
    echo "[SKIP] $targets:$lineno 열이 부족합니다 (IP 계정 출력폴더 [auth])"; skipped=$((skipped + 1)); continue
  fi
  case "$auth" in auto|session|basic) ;; *)
    echo "[SKIP] $targets:$lineno auth 는 auto|session|basic 중 하나여야 합니다: $auth"; skipped=$((skipped + 1)); continue ;;
  esac
  if [ -n "${seen_out[$out]:-}" ]; then
    echo "[WARN] $targets:$lineno 출력 폴더가 중복입니다: $out (앞 줄 결과를 덮어씁니다)"
  fi
  seen_out[$out]=1
  # 동시 실행 수 제한 + 같은 IP 직렬화
  while :; do
    [ "$interrupted" -eq 1 ] && break
    busy=0
    prev=${ip_pid[$ip]:-}
    if [ -n "$prev" ] && kill -0 "$prev" 2>/dev/null; then busy=1; fi
    if [ "$(jobs -rp | wc -l)" -lt "$JOBS" ] && [ "$busy" -eq 0 ]; then break; fi
    sleep 1
  done
  [ "$interrupted" -eq 1 ] && break
  if ! mkdir -p "$out"; then
    echo "[SKIP] $targets:$lineno 출력 폴더를 만들 수 없습니다: $out"; skipped=$((skipped + 1)); continue
  fi
  # shellcheck disable=SC2086   (MIRROR_ARGS 는 의도적으로 단어 분리한다)
  "$PYTHON" "$MIRROR_PY" -r "$ip" -u "$user" -D "$out" --auth "$auth" --password-env BMC_PW $EXTRA \
    > "$out/_crawl.log" 2>&1 &
  pid=$!
  ip_pid[$ip]=$pid
  pid_out[$pid]=$out
  all_pids+=("$pid")
  outdirs+=("$out")
  echo "[START] $ip -> $out (auth=$auth, pid=$pid)"
done < "$targets"

for pid in "${all_pids[@]}"; do
  wait "$pid"
  echo $? > "${pid_out[$pid]}/_exit_code"
done

if [ "${#outdirs[@]}" -eq 0 ]; then echo "[CRIT] 실행할 대상이 없습니다" >&2; exit 2; fi
echo
"$PYTHON" "$MIRROR_PY" --summarize "${outdirs[@]}"
rc=$?
[ "$skipped" -gt 0 ] && { echo "  [WARN] 형식 오류로 건너뛴 줄: $skipped"; rc=1; }
[ "$interrupted" -eq 1 ] && exit 130
exit $rc
