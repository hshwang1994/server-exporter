#!/bin/bash
# scripts/gather_budget.sh — 수집 실행 한계(초) 계산의 **단일 구현** (2026-10-03 Plan §6-2, 2026-10-05 8차 R3 개정).
#
# Jenkinsfile_portal 이 ansible-playbook 실행 **직전**에 한 번 부른다. 출력의 limit 이 timeout(1) 값이 된다.
# 모든 상수의 단위는 초(s).
#
# 시간 한계 (8차 R3 — 사용자 요구: 빠른 종료보다 실제 수집 완료가 우선이다. 운영 서버의 부하 · 작업량은 미리 알 수 없다)
#   빌드 전체 BUILD_SEC(12시간) = 입력 확인 · 실행 위치 확인 PRE_SEC(10분) + 서버 정보 수집 단계 STAGE_SEC + 결과 확인 및 전송 FINALIZER_SEC(1시간).
#   실제 수집(ansible-playbook)은 시작부터 최대 GATHER_MAX_SEC(6시간)이다. 수집 단계 안에서, 수집이 끝난 뒤의 결과 정리 · 보존 몫(AGENT_POST_SEC)과
#   중단 신호 뒤의 정리 시간(GRACE_SEC = timeout --kill-after)을 먼저 뺀다.
#     limit = min(GATHER_MAX_SEC, 수집 단계 남은 시간 − GRACE − AGENT_POST, 빌드 남은 시간 − FINALIZER − GRACE − AGENT_POST)
#   Runner 대기 · checkout · Add-on 준비로 시간을 써서 6시간을 다 줄 수 없으면 limit_source=build_limit 이다 — 6시간을 보장했다고 하지 않는다.
#   예상 시간(expected)은 안내와 자원 계획용이다. 아무것도 그 값으로 중단하지 않는다(정체 감시 · 예상 시간 기준 중단은 2026-10-05 에 없앴다).
#
# 입력(환경변수)
#   SE_NOW_EPOCH          현재 시각 (필수)        SE_BUILD_START_EPOCH  빌드 시작 (필수)
#   SE_STAGE_START_EPOCH  서버 정보 수집 단계의 기준점 (필수) — 실행 위치 확인 끝(Runner 를 얻기 전). 단계 한계가 Runner 대기를 포함하기 때문이다
#   SE_CHANNEL            os | esxi | redfish (필수)  SE_HOSTS  접수 대상 수 (필수, ≥1)
#   SE_VCPU               Runner vCPU (기본 nproc)
#   SE_FORKS_CAP_OS · SE_PER_FORK_MB · SE_NODE_SHARE_PCT · SE_FIXED_MB   Runner 노드 환경변수로 두는 동시 실행 · 메모리 보호 조정값
#   SE_MEM_AVAILABLE_MB   시험 입력 — 가용 메모리 MB. Jenkinsfile 은 이 값을 지우고 부르므로 운영에서는 /proc/meminfo 만 읽는다.
#                         값이 있어도 동시 실행 수를 줄이거나 시작을 막을 뿐, 실행 한계는 바꾸지 못한다.
#   (SE_FORCE_SEC 같은 강제 한계 입력은 없다 — 2026-10-05 R1 에서 운영 파라미터와 함께 없앴다. 상위 환경에 남아 있어도 읽지 않는다.)
# 출력: JSON 한 줄 — channel, hosts, vcpu, forks, waves, expected, gather_max, stage_remaining, build_remaining, limit, limit_source,
#        start(true/false), reason, mem_avail_mb, mem_cap, mem_guard, constants.
#        reason: computed | not_started_budget(남은 시간 부족) | not_started_memory(1 fork 도 수용 못 함) | invalid_input
#        limit_source: gather_limit(6시간 한계 그대로) | build_limit(빌드 남은 시간이 더 짧다) | none(시작 안 함)
# 종료 코드: 0 계산 성공 / 2 입력 불량
set -u

# ── 시간 한계 (초) — Jenkinsfile_portal seConstants() 와 같아야 한다 (tests/unit/test_time_limits.py) ────────────────────
BUILD_SEC=43200          # options.timeout 12시간. 결과 확인 및 전송(post)도 이 안에서 돈다
PRE_SEC=600              # 입력 확인 5분 + 실행 위치 확인 5분
FINALIZER_SEC=3600       # 결과 확인 및 전송 1시간
STAGE_SEC=39000          # 서버 정보 수집 단계 = BUILD − PRE − FINALIZER
GATHER_MAX_SEC=21600     # 실제 수집 6시간 (시작 기준)
GRACE_SEC=90             # timeout --kill-after — 중단 신호(INT) 뒤 ansible 이 자식까지 정리할 시간
AGENT_POST_SEC=900       # 수집 단계 안의 결과 정리 · 보관 · 전달 · 작업 폴더 정리 몫 (단계별 제한 없이 이 몫 안에서)
MIN_START_SEC=120        # 이보다 짧으면 시작하지 않는다 (not_started_budget)
# ── 예상 시간 (표시 · 자원 계획용) ───────────────────────────────────────────────────────────────────────────────────
BASE_SEC=300
HOST_EST_OS=240          # 2026-09-03 실측 host 최대 78 s × 3
HOST_EST_ESXI=240
HOST_EST_REDFISH=605     # 표준 계정 수집 실측 최장(Cisco CIMC 353 s)에 여유를 둔 값 — 복구 경로는 더 걸릴 수 있다
# ── 동시 실행 ───────────────────────────────────────────────────────────────────────────────────────────────────────
# OS forks 기본 상한 50 — Runner 노드 환경변수 SE_FORKS_CAP_OS 로 올린다(메모리 보호가 상한으로 자른다).
OS_FORKS_MAX=50
ESXI_FORKS_PER_VCPU=2
REDFISH_FORKS_PER_VCPU=4
# ── 메모리 보호 (P-1, 2026-10-04 Runner 실측으로 확정 — GP-18) ─────────────────────────────────────────────────────────
#   mem_cap = floor((MemAvailable_MB × NODE_SHARE_PCT/100 − FIXED_MB) / PER_FORK_MB); forks = min(forks, mem_cap).
#   실측(perf-observe Job, 13 host 성공 배치 5회 + 18 host 혼합 1회, Runner01/02 7.5 GB · 4 vCPU): 활성 slot 당 PSS 평균 36 MB, slot 최악치 69 MB(Windows WinRM worker),
#   ansible 메인 python 최대 86 MB, 트리 peak 459~620 MB, swap 0. PER_FORK_MB 80 = 69 + 여유, FIXED_MB 200 = 86 + 여유.
#   NODE_SHARE_PCT 40 = 한 Runner 에 수집 빌드가 겹칠 수 있다는 가정의 몫(예약이 아니다). 2026-10-05 측정: 같은 Runner 에 3~4 빌드가 겹쳐도 남은 메모리 4.68 GB 이상.
#   mem_cap ≤ 0 → 1 fork 도 수용 못 함 → start=false reason=not_started_memory. MemAvailable 을 못 읽으면 mem_guard=unavailable 로 두고 기존 상한으로 진행한다.
PER_FORK_MB_DEFAULT=80
NODE_SHARE_PCT_DEFAULT=40
FIXED_MB_DEFAULT=200

fail() { echo "{\"start\":false,\"reason\":\"invalid_input\",\"error\":\"$1\"}"; exit 2; }
is_int() { [[ "${1:-}" =~ ^[0-9]+$ ]]; }
min() { if [ "$1" -lt "$2" ]; then echo "$1"; else echo "$2"; fi; }

for v in SE_NOW_EPOCH SE_BUILD_START_EPOCH SE_STAGE_START_EPOCH SE_HOSTS; do
    is_int "${!v:-}" || fail "$v must be a non-negative integer"
done
CH="${SE_CHANNEL:-}"
case "$CH" in os|esxi|redfish) ;; *) fail "SE_CHANNEL must be os|esxi|redfish" ;; esac
H="$SE_HOSTS"; [ "$H" -ge 1 ] || fail "SE_HOSTS must be >= 1"
VCPU="${SE_VCPU:-}"
if [ -z "$VCPU" ]; then VCPU="$(nproc 2>/dev/null || echo 2)"; fi
is_int "$VCPU" && [ "$VCPU" -ge 1 ] || VCPU=2
if [ -n "${SE_FORKS_CAP_OS:-}" ] && is_int "$SE_FORKS_CAP_OS" && [ "$SE_FORKS_CAP_OS" -ge 1 ]; then OS_FORKS_MAX="$SE_FORKS_CAP_OS"; fi

case "$CH" in
    os)      FORKS=$(min "$H" "$OS_FORKS_MAX"); HOST_EST=$HOST_EST_OS ;;
    esxi)    FORKS=$(min "$H" $((ESXI_FORKS_PER_VCPU * VCPU))); HOST_EST=$HOST_EST_ESXI ;;
    redfish) FORKS=$(min "$H" $((REDFISH_FORKS_PER_VCPU * VCPU))); HOST_EST=$HOST_EST_REDFISH ;;
esac
[ "$FORKS" -ge 1 ] || FORKS=1

PER_FORK_MB="${SE_PER_FORK_MB:-$PER_FORK_MB_DEFAULT}"; NODE_SHARE_PCT="${SE_NODE_SHARE_PCT:-$NODE_SHARE_PCT_DEFAULT}"; FIXED_MB="${SE_FIXED_MB:-$FIXED_MB_DEFAULT}"
is_int "$PER_FORK_MB" && [ "$PER_FORK_MB" -ge 1 ] || PER_FORK_MB=$PER_FORK_MB_DEFAULT
is_int "$NODE_SHARE_PCT" && [ "$NODE_SHARE_PCT" -ge 1 ] && [ "$NODE_SHARE_PCT" -le 100 ] || NODE_SHARE_PCT=$NODE_SHARE_PCT_DEFAULT
is_int "$FIXED_MB" || FIXED_MB=$FIXED_MB_DEFAULT
MEM_AVAIL_MB="${SE_MEM_AVAILABLE_MB:-}"
if [ -z "$MEM_AVAIL_MB" ] && [ -r /proc/meminfo ]; then
    MEM_AVAIL_MB="$(awk '/^MemAvailable:/ { printf "%d", $2 / 1024 }' /proc/meminfo 2>/dev/null)"
fi
MEM_GUARD="unavailable"; MEM_CAP="null"; MEM_AVAIL_OUT="null"
MEM_REFUSED=false
if is_int "${MEM_AVAIL_MB:-}" && [ "$MEM_AVAIL_MB" -gt 0 ]; then
    MEM_AVAIL_OUT="$MEM_AVAIL_MB"
    MEM_CAP=$(( (MEM_AVAIL_MB * NODE_SHARE_PCT / 100 - FIXED_MB) / PER_FORK_MB ))
    MEM_GUARD="active"
    if [ "$MEM_CAP" -le 0 ]; then
        MEM_REFUSED=true      # 1 fork 도 수용 못 한다. 최소 자원 = FIXED_MB + PER_FORK_MB
    else
        FORKS=$(min "$FORKS" "$MEM_CAP")
    fi
fi

if [ "$MEM_REFUSED" = true ]; then
    FORKS=0; WAVES=0; EXPECTED=0
else
    WAVES=$(( (H + FORKS - 1) / FORKS ))
    EXPECTED=$(( BASE_SEC + HOST_EST * WAVES ))
fi

STAGE_REMAINING=$(( SE_STAGE_START_EPOCH + STAGE_SEC - SE_NOW_EPOCH - GRACE_SEC - AGENT_POST_SEC ))
BUILD_REMAINING=$(( SE_BUILD_START_EPOCH + BUILD_SEC - FINALIZER_SEC - SE_NOW_EPOCH - GRACE_SEC - AGENT_POST_SEC ))
AVAILABLE=$(min "$STAGE_REMAINING" "$BUILD_REMAINING")
if [ "$GATHER_MAX_SEC" -le "$AVAILABLE" ]; then
    LIMIT=$GATHER_MAX_SEC; LIMIT_SOURCE="gather_limit"
else
    LIMIT=$AVAILABLE; LIMIT_SOURCE="build_limit"
fi
START=true; REASON="computed"
if [ "$MEM_REFUSED" = true ]; then
    START=false; REASON="not_started_memory"; LIMIT_SOURCE="none"
elif [ "$LIMIT" -lt "$MIN_START_SEC" ]; then
    START=false; REASON="not_started_budget"; LIMIT_SOURCE="none"
fi
[ "$LIMIT" -lt 0 ] && LIMIT=0

printf '{"channel":"%s","hosts":%d,"vcpu":%d,"forks":%d,"waves":%d,"expected":%d,"gather_max":%d,"stage_remaining":%d,"build_remaining":%d,"limit":%d,"limit_source":"%s","start":%s,"reason":"%s","mem_avail_mb":%s,"mem_cap":%s,"mem_guard":"%s","constants":{"build":%d,"pre":%d,"stage":%d,"finalizer":%d,"gather_max":%d,"grace":%d,"agent_post":%d,"min_start":%d,"base":%d,"host_est":%d,"per_fork_mb":%d,"node_share_pct":%d,"fixed_mb":%d}}\n' \
    "$CH" "$H" "$VCPU" "$FORKS" "$WAVES" "$EXPECTED" "$GATHER_MAX_SEC" "$STAGE_REMAINING" "$BUILD_REMAINING" "$LIMIT" "$LIMIT_SOURCE" "$START" "$REASON" \
    "$MEM_AVAIL_OUT" "$MEM_CAP" "$MEM_GUARD" \
    "$BUILD_SEC" "$PRE_SEC" "$STAGE_SEC" "$FINALIZER_SEC" "$GATHER_MAX_SEC" "$GRACE_SEC" "$AGENT_POST_SEC" "$MIN_START_SEC" "$BASE_SEC" "$HOST_EST" \
    "$PER_FORK_MB" "$NODE_SHARE_PCT" "$FIXED_MB"
