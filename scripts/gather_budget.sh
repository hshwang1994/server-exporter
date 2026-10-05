#!/bin/bash
set -u

GLOBAL_SEC=9000
RESERVE_SEC=990
STAGE_LIMIT_SEC=6900
GRACE_SEC=90
POST_SEC=180
BASE_SEC=300
MIN_SEC=600
CAP_SEC=5400
MIN_START_SEC=120
STALL_SEC=420
HOST_CAP_OS=240
HOST_CAP_ESXI=240
REDFISH_DEADLINE_SEC=540
REDFISH_BACKOFF_SEC=65
REDFISH_ACCOUNT_SEC=240
OS_FORKS_MAX=50
ESXI_FORKS_PER_VCPU=2
REDFISH_FORKS_PER_VCPU=4
PER_FORK_MB_DEFAULT=80
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
        printf '{"channel":"%s","hosts":%d,"vcpu":%d,"forks":0,"waves":0,"host_cap":%d,"gather":0,"expected":0,"hard_remaining":%d,"stage_remaining":%d,"budget":0,"limit_source":"none","stall":%d,"start":false,"reason":"not_started_memory","force":%s,"mem_avail_mb":%d,"mem_cap":%d,"mem_guard":"active","constants":{"global":%d,"reserve":%d,"stage_limit":%d,"grace":%d,"post":%d,"base":%d,"min":%d,"cap":%d,"min_start":%d,"stall":%d,"per_fork_mb":%d,"node_share_pct":%d,"fixed_mb":%d}}\n' \
            "$CH" "$H" "$VCPU" "$HOST_CAP" "$(( SE_BUILD_START_EPOCH + GLOBAL_SEC - SE_NOW_EPOCH - RESERVE_SEC ))" "$(( SE_STAGE_START_EPOCH + STAGE_LIMIT_SEC - SE_NOW_EPOCH - GRACE_SEC - POST_SEC ))" "$STALL_SEC" "${FORCE:-null}" \
            "$MEM_AVAIL_MB" "$MEM_CAP" "$GLOBAL_SEC" "$RESERVE_SEC" "$STAGE_LIMIT_SEC" "$GRACE_SEC" "$POST_SEC" "$BASE_SEC" "$MIN_SEC" "$CAP_SEC" "$MIN_START_SEC" "$STALL_SEC" "$PER_FORK_MB" "$NODE_SHARE_PCT" "$FIXED_MB"
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

LIMIT=$(min "$HARD_REMAINING" "$STAGE_REMAINING")
BUDGET="$LIMIT"
REASON="computed"
LIMIT_SOURCE="ceiling"
if [ -n "$FORCE" ]; then
    BUDGET=$(min "$FORCE" "$LIMIT")
    REASON="forced"
    LIMIT_SOURCE="forced"
fi
START=true
if [ "$BUDGET" -lt "$MIN_START_SEC" ]; then START=false; REASON="not_started_budget"; LIMIT_SOURCE="none"; fi
[ "$BUDGET" -lt 0 ] && BUDGET=0

printf '{"channel":"%s","hosts":%d,"vcpu":%d,"forks":%d,"waves":%d,"host_cap":%d,"gather":%d,"expected":%d,"hard_remaining":%d,"stage_remaining":%d,"budget":%d,"limit_source":"%s","stall":%d,"start":%s,"reason":"%s","force":%s,"mem_avail_mb":%s,"mem_cap":%s,"mem_guard":"%s","constants":{"global":%d,"reserve":%d,"stage_limit":%d,"grace":%d,"post":%d,"base":%d,"min":%d,"cap":%d,"min_start":%d,"stall":%d,"per_fork_mb":%d,"node_share_pct":%d,"fixed_mb":%d}}\n' \
    "$CH" "$H" "$VCPU" "$FORKS" "$WAVES" "$HOST_CAP" "$GATHER" "$GATHER" "$HARD_REMAINING" "$STAGE_REMAINING" "$BUDGET" "$LIMIT_SOURCE" "$STALL_SEC" "$START" "$REASON" "${FORCE:-null}" \
    "$MEM_AVAIL_OUT" "$MEM_CAP" "$MEM_GUARD" \
    "$GLOBAL_SEC" "$RESERVE_SEC" "$STAGE_LIMIT_SEC" "$GRACE_SEC" "$POST_SEC" "$BASE_SEC" "$MIN_SEC" "$CAP_SEC" "$MIN_START_SEC" "$STALL_SEC" "$PER_FORK_MB" "$NODE_SHARE_PCT" "$FIXED_MB"
