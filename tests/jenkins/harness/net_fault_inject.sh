#!/bin/bash
# tests/jenkins/harness/net_fault_inject.sh — 시험 6 · 18(대상 측 일시 네트워크 장애)의 장애 주입 (2026-10-07, 10차 R6). 운영 경로가 아니다.
#
# 무엇을 하나
#   시험 전용 Agent(se-probe)의 세션 cgroup 에서 나가는 패킷 중 대상 IP 1개로 가는 것만, 정해진 초 동안 버린다. 별도 nftables 표(inet se_netfault_<pid>)를
#   만들고 끝나면(정상 · 신호 · 오류 모두) 지운다. 운영 Runner 의 다른 Agent · 다른 대상 · firewalld 표는 건드리지 않는다.
#   대상의 Precheck 통과 뒤 수집 중임을 확인한 다음에만 끊는다 — 진행 기록(gather_progress.jsonl)에 그 IP 의 시작 사건(--trigger, 기본 auth_proven:
#   대상 연결로 돈 태스크가 성공 = 인증 통과)이 보이면 --after 초 뒤에 건다. 시험용 짧은 연결 설정을 넣지 않는다 — 운영 설정 그대로의 회복 · 미회복을 본다.
#
# 사용 (Runner 에서 root 로):
#   net_fault_inject.sh --progress <작업 폴더>/gather_progress.jsonl --ip <대상 IP> --cgroup <se-probe Agent 의 cgroup 경로(/user.slice/... 형식)>
#                       --hold <초> [--trigger auth_proven] [--after 0] [--max-wait 1800] --log <기록 파일>
# 기록(--log, JSON 한 줄씩): 시작 · 걸림(시각) · 풀림(시각, 버린 패킷 수) · 끝. 비밀값은 없다.
set -u
PROGRESS=""; IP=""; CG=""; HOLD=""; TRIGGER="auth_proven"; AFTER=0; MAXWAIT=1800; LOG=""
while [ $# -gt 0 ]; do
    case "$1" in
        --progress) PROGRESS="$2"; shift 2 ;;
        --ip) IP="$2"; shift 2 ;;
        --cgroup) CG="$2"; shift 2 ;;
        --hold) HOLD="$2"; shift 2 ;;
        --trigger) TRIGGER="$2"; shift 2 ;;
        --after) AFTER="$2"; shift 2 ;;
        --max-wait) MAXWAIT="$2"; shift 2 ;;
        --log) LOG="$2"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done
if [ -z "$PROGRESS" ] || ! [[ "$IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || [ -z "$CG" ] || ! [[ "$HOLD" =~ ^[0-9]+$ ]] || [ "$HOLD" -gt 1800 ] || [ -z "$LOG" ]; then
    echo "usage: --progress FILE --ip IPv4 --cgroup PATH --hold SECONDS(<=1800) --log FILE [--trigger EVENT] [--after SECONDS] [--max-wait SECONDS]" >&2
    exit 2
fi
command -v nft >/dev/null 2>&1 || { echo "nft 없음" >&2; exit 2; }
REL="${CG#/}"
[ -d "/sys/fs/cgroup/$REL" ] || { echo "cgroup 없음: $CG" >&2; exit 2; }
LEVEL=$(printf '%s' "$REL" | awk -F/ '{print NF}')
TABLE="se_netfault_$$"
now() { date -u '+%Y-%m-%dT%H:%M:%S.%3NZ'; }
note() { printf '{"at": "%s", "event": "%s", "ip": "%s", "detail": "%s"}\n' "$(now)" "$1" "$IP" "$2" >> "$LOG"; }
cleanup() {
    if nft list table inet "$TABLE" >/dev/null 2>&1; then
        local dropped
        dropped=$(nft list table inet "$TABLE" 2>/dev/null | grep -o 'packets [0-9]*' | head -1 | awk '{print $2}')
        nft delete table inet "$TABLE" 2>/dev/null
        note released "dropped_packets=${dropped:-0}"
    fi
}
trap cleanup EXIT
trap 'note signal stopped; exit 130' INT TERM
note start "trigger=${TRIGGER} after=${AFTER}s hold=${HOLD}s cgroup=${CG} level=${LEVEL}"
deadline=$((SECONDS + MAXWAIT))
seen=false
while [ "$SECONDS" -lt "$deadline" ]; do
    # json_only 의 진행 줄은 붙여 쓴 JSON 이다({"ts":…,"host":"<IP>","ip":"<IP>","event":"auth_proven",…}) — host 또는 ip 가 대상이고 사건이 맞는 줄
    if [ -f "$PROGRESS" ] && grep -F -e "\"ip\":\"$IP\"" -e "\"host\":\"$IP\"" "$PROGRESS" 2>/dev/null | grep -qF "\"event\":\"$TRIGGER\""; then
        seen=true
        break
    fi
    sleep 0.5
done
if [ "$seen" != true ]; then
    note no_trigger "the trigger event did not appear within ${MAXWAIT}s"
    exit 3
fi
note triggered "trigger seen"
[ "$AFTER" -gt 0 ] && sleep "$AFTER"
nft add table inet "$TABLE" || exit 4
nft add chain inet "$TABLE" out '{ type filter hook output priority 0; policy accept; }' || exit 4
nft add rule inet "$TABLE" out socket cgroupv2 level "$LEVEL" "$REL" ip daddr "$IP" counter drop || exit 4
note blocked "packets from the probe agent cgroup to ${IP} are dropped"
sleep "$HOLD"
cleanup
note end "done"
exit 0
