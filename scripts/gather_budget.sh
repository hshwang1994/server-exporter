#!/bin/bash
# scripts/gather_budget.sh — 수집 배치 예산(초) 계산의 **단일 구현** (2026-10-03, Plan §6-2).
#
# Jenkinsfile_portal 이 두 번 부른다: Gather node 진입 직후(예상값 — 로그·조기 중단 판단) 와 ansible-playbook 실행 **직전**(집행값).
# 집행값만 timeout(1) 에 들어간다 — agent 대기 · checkout · Add-on 준비가 길어진 만큼 gather 가 줄고 finalization reserve 는 줄지 않는다.
# 모든 상수의 단위는 초(s). 값은 Phase 1·5 측정 뒤 보정한다 (초기 경험값: 2026-09-03 실측 host 최대 78 s × 3 = 240).
#
# 입력(환경변수)
#   SE_NOW_EPOCH          현재 시각 (필수)            SE_BUILD_START_EPOCH  빌드 시작 (필수)        SE_STAGE_START_EPOCH  Gather stage 기준점 (필수)
#                                                     — Resolve Location 끝(agent 를 얻기 전)에 찍는다. stage 상한이 agent 대기를 포함하므로 기준점도 대기 앞이다 (R6)
#   SE_MEM_AVAILABLE_MB   Runner 가용 메모리 MB (기본 /proc/meminfo MemAvailable)   SE_PER_FORK_MB · SE_NODE_SHARE_PCT · SE_FIXED_MB  메모리 보호 상수 override
#   SE_CHANNEL            os | esxi | redfish (필수)  SE_HOSTS              접수 host 수 (필수, ≥1)
#   SE_VCPU               Runner vCPU (기본 nproc)    SE_FORCE_SEC          검증용 강제 상한 (선택, 정수) — 남은 시간을 넘지 못한다
#   SE_REDFISH_CANDIDATES 표준 계정 후보 수 (기본 1)  SE_REDFISH_RECOVERY   복구 단계 포함 1/0 (기본 0)
# 출력: JSON 한 줄 — forks, waves, host_cap, gather, hard_remaining, stage_remaining, budget, start(true/false), reason, mem_avail_mb, mem_cap, mem_guard, 상수.
#        reason: computed | forced | not_started_budget(시간 부족) | not_started_memory(1 fork 도 수용 못 함) | invalid_input
# 종료 코드: 0 계산 성공 / 2 입력 불량
set -u

# ── 상수 (초) ───────────────────────────────────────────────────────────────────
GLOBAL_SEC=9000          # options.timeout 150 min — HARD_DEADLINE = 빌드 시작 + GLOBAL_SEC
RESERVE_SEC=990          # 수집 종료 → Callback 종료의 실제 경로 합: GRACE 90 + LAYER_A 120 + ARCHIVE_STASH 60 + FINALIZER_TOTAL 720
STAGE_LIMIT_SEC=6900     # Gather stage 합산 상한 115 min (= WAIT_AGENT 300 + CHECKOUT 600 + ADDON 300 + CAP 5400 + 300) — 기준점이 agent 대기 앞이라 대기가 잔여에서 차감된다
GRACE_SEC=90             # timeout --kill-after
POST_SEC=180             # Gather post{always}: LAYER_A 120 + ARCHIVE_STASH 60
BASE_SEC=300
MIN_SEC=600
CAP_SEC=5400
MIN_START_SEC=120
HOST_CAP_OS=240
HOST_CAP_ESXI=240
REDFISH_DEADLINE_SEC=540
REDFISH_BACKOFF_SEC=65
REDFISH_ACCOUNT_SEC=240
# 2026-10-03 Phase 5 WSL 실측: fork 슬롯당 프로세스 트리 PSS ≈ 36 MB(forks 100 ≈ 3.7 GB), 실패 경로 wall 은 forks 50↔100 차이 없음.
#   Runner RAM 을 측정하기 전까지 기본 50. Runner 노드 환경변수 SE_FORKS_CAP_OS 로 올린다 (docs/ai/NEXT_ACTIONS.md GP-18).
OS_FORKS_MAX=50
ESXI_FORKS_PER_VCPU=2
REDFISH_FORKS_PER_VCPU=4
# ── 메모리 보호 (P-1, 2026-10-03 Astra 3차 §11-1) — 값은 전부 **임시(미측정)**, S1/S2 실측(peak PSS · 활성 fork) 뒤 보정한다 ─────
#   mem_cap = floor((MemAvailable_MB × NODE_SHARE_PCT/100 − FIXED_MB) / PER_FORK_MB); forks = min(forks, mem_cap).
#   PER_FORK_MB 36 = WSL 실패 경로의 fork 슬롯당 PSS 관측값이지 성공 수집의 상한이 아니다. FIXED_MB 200 = ansible 컨트롤 프로세스 등 고정 비용(추정).
#   NODE_SHARE_PCT 40 = 15 executor Runner 에서 main·production 두 Job 의 Gather 가 겹칠 수 있다는 가정의 몫(예약이 아니다).
#   mem_cap ≤ 0 → 1 fork 도 수용 못 함 → start=false reason=not_started_memory (waves 계산 전에 반환). MemAvailable 을 못 읽으면
#   mem_guard=unavailable 로 두고 기존 상한으로 진행한다 — 보호가 동작한 결과로 보고하지 않는다.
PER_FORK_MB_DEFAULT=36
NODE_SHARE_PCT_DEFAULT=40
FIXED_MB_DEFAULT=200

fail() { echo "{\"start\":false,\"reason\":\"invalid_input\",\"error\":\"$1\"}"; exit 2; }
is_int() { [[ "${1:-}" =~ ^[0-9]+$ ]]; }

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
CAND="${SE_REDFISH_CANDIDATES:-1}"; is_int "$CAND" && [ "$CAND" -ge 1 ] || CAND=1
RECOV="${SE_REDFISH_RECOVERY:-0}"
FORCE="${SE_FORCE_SEC:-}"
if [ -n "$FORCE" ]; then is_int "$FORCE" || fail "SE_FORCE_SEC must be an integer"; fi

min() { if [ "$1" -lt "$2" ]; then echo "$1"; else echo "$2"; fi; }
max() { if [ "$1" -gt "$2" ]; then echo "$1"; else echo "$2"; fi; }

case "$CH" in
    os)      FORKS=$(min "$H" "$OS_FORKS_MAX"); HOST_CAP=$HOST_CAP_OS ;;
    esxi)    FORKS=$(min "$H" $((ESXI_FORKS_PER_VCPU * VCPU))); HOST_CAP=$HOST_CAP_ESXI ;;
    redfish) FORKS=$(min "$H" $((REDFISH_FORKS_PER_VCPU * VCPU)))
             HOST_CAP=$(( CAND * (REDFISH_DEADLINE_SEC + REDFISH_BACKOFF_SEC) ))
             if [ "$RECOV" = "1" ]; then HOST_CAP=$(( HOST_CAP + REDFISH_ACCOUNT_SEC )); fi ;;
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
if is_int "${MEM_AVAIL_MB:-}" && [ "$MEM_AVAIL_MB" -gt 0 ]; then
    MEM_AVAIL_OUT="$MEM_AVAIL_MB"
    MEM_CAP=$(( (MEM_AVAIL_MB * NODE_SHARE_PCT / 100 - FIXED_MB) / PER_FORK_MB ))
    MEM_GUARD="active"
    if [ "$MEM_CAP" -le 0 ]; then
        # 1 fork 도 수용 못 한다 — waves 계산(0 나누기) 전에 거부 결과를 돌려준다. 최소 자원 = FIXED_MB + PER_FORK_MB.
        printf '{"channel":"%s","hosts":%d,"vcpu":%d,"forks":0,"waves":0,"host_cap":%d,"gather":0,"hard_remaining":%d,"stage_remaining":%d,"budget":0,"start":false,"reason":"not_started_memory","force":%s,"mem_avail_mb":%d,"mem_cap":%d,"mem_guard":"active","constants":{"global":%d,"reserve":%d,"stage_limit":%d,"grace":%d,"post":%d,"base":%d,"min":%d,"cap":%d,"min_start":%d,"per_fork_mb":%d,"node_share_pct":%d,"fixed_mb":%d}}\n' \
            "$CH" "$H" "$VCPU" "$HOST_CAP" "$(( SE_BUILD_START_EPOCH + GLOBAL_SEC - SE_NOW_EPOCH - RESERVE_SEC ))" "$(( SE_STAGE_START_EPOCH + STAGE_LIMIT_SEC - SE_NOW_EPOCH - GRACE_SEC - POST_SEC ))" "${FORCE:-null}" \
            "$MEM_AVAIL_MB" "$MEM_CAP" "$GLOBAL_SEC" "$RESERVE_SEC" "$STAGE_LIMIT_SEC" "$GRACE_SEC" "$POST_SEC" "$BASE_SEC" "$MIN_SEC" "$CAP_SEC" "$MIN_START_SEC" "$PER_FORK_MB" "$NODE_SHARE_PCT" "$FIXED_MB"
        exit 0
    fi
    FORKS=$(min "$FORKS" "$MEM_CAP")
fi
WAVES=$(( (H + FORKS - 1) / FORKS ))
GATHER=$(( BASE_SEC + HOST_CAP * WAVES ))
GATHER=$(max "$GATHER" "$MIN_SEC"); GATHER=$(min "$GATHER" "$CAP_SEC")

HARD_DEADLINE=$(( SE_BUILD_START_EPOCH + GLOBAL_SEC ))
HARD_REMAINING=$(( HARD_DEADLINE - SE_NOW_EPOCH - RESERVE_SEC ))
STAGE_REMAINING=$(( SE_STAGE_START_EPOCH + STAGE_LIMIT_SEC - SE_NOW_EPOCH - GRACE_SEC - POST_SEC ))

BUDGET=$(min "$GATHER" "$HARD_REMAINING"); BUDGET=$(min "$BUDGET" "$STAGE_REMAINING")
REASON="computed"
if [ -n "$FORCE" ]; then
    # 강제값은 gather 공식을 대체하지만 남은 시간(hard · stage)은 넘지 못한다.
    BUDGET=$(min "$FORCE" "$HARD_REMAINING"); BUDGET=$(min "$BUDGET" "$STAGE_REMAINING")
    REASON="forced"
fi
START=true
if [ "$BUDGET" -lt "$MIN_START_SEC" ]; then START=false; REASON="not_started_budget"; fi
[ "$BUDGET" -lt 0 ] && BUDGET=0

printf '{"channel":"%s","hosts":%d,"vcpu":%d,"forks":%d,"waves":%d,"host_cap":%d,"gather":%d,"hard_remaining":%d,"stage_remaining":%d,"budget":%d,"start":%s,"reason":"%s","force":%s,"mem_avail_mb":%s,"mem_cap":%s,"mem_guard":"%s","constants":{"global":%d,"reserve":%d,"stage_limit":%d,"grace":%d,"post":%d,"base":%d,"min":%d,"cap":%d,"min_start":%d,"per_fork_mb":%d,"node_share_pct":%d,"fixed_mb":%d}}\n' \
    "$CH" "$H" "$VCPU" "$FORKS" "$WAVES" "$HOST_CAP" "$GATHER" "$HARD_REMAINING" "$STAGE_REMAINING" "$BUDGET" "$START" "$REASON" "${FORCE:-null}" \
    "$MEM_AVAIL_OUT" "$MEM_CAP" "$MEM_GUARD" \
    "$GLOBAL_SEC" "$RESERVE_SEC" "$STAGE_LIMIT_SEC" "$GRACE_SEC" "$POST_SEC" "$BASE_SEC" "$MIN_SEC" "$CAP_SEC" "$MIN_START_SEC" "$PER_FORK_MB" "$NODE_SHARE_PCT" "$FIXED_MB"
