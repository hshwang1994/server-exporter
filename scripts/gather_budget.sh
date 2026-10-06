#!/bin/bash
set -u

BUILD_SEC=43200
PRE_SEC=600
FINALIZER_SEC=3600
STAGE_SEC=39000
GATHER_MAX_SEC=21600
GRACE_SEC=90
AGENT_POST_SEC=900
MIN_START_SEC=120
BASE_SEC=300
HOST_EST_OS=240
HOST_EST_ESXI=240
HOST_EST_REDFISH=605
OS_FORKS_MAX=50
ESXI_FORKS_PER_VCPU=2
REDFISH_FORKS_PER_VCPU=4
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
        MEM_REFUSED=true
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
