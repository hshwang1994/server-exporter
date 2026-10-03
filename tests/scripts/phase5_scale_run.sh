#!/bin/bash
# tests/scripts/phase5_scale_run.sh — Phase 5 (Plan §10-3) 규모 에뮬레이션 1회 실행기: OS 채널 실패 경로, loopback 전용.
#
# Jenkinsfile_portal Gather stage 의 ansible 실행 1회를 **대상 장비 없이** 재현한다.
#   - 합성 인벤토리: 127.0.<octet>.1.. 의 N 개 IP (WSL loopback 에는 22/5985/5986 리스너가 없어 precheck 가 RST 를 관측
#     → failure_stage=port / failure_code=TCP_CONNECTION_REFUSED → PLAY 1.5 failed-output 에서 OUTPUT)
#   - Jenkinsfile_portal 과 같은 env/인자: REPO_ROOT, ANSIBLE_CONFIG, ANSIBLE_JSON_{OUTPUT,MANIFEST,PROGRESS,CHECKPOINT}_FILE,
#     SE_AUTH_EVIDENCE_DIR, os-gather/inventory.sh + INVENTORY_JSON, `timeout --signal=INT --kill-after=90`, -f FORKS,
#     --vault-password-file(더미 — 실패 경로는 vault 를 열지 않는다), -e se_location
#   - /usr/bin/time -v 로 wall-clock / 최대 RSS(단일 프로세스 기준) 기록 + phase5_mem_sampler.py 로 트리 합산 RSS/PSS 피크
#   - Layer A(scripts/finalize_gather_output.py) 실행 시간 측정, 종료 뒤 고아 프로세스 확인(ps)
#   - 결과: WORKDIR/summary.json (phase5_report.py summarize) + 원본 파일(gather_*, time.txt, stdout.log, stderr.log, mem.json)
#
# usage: phase5_scale_run.sh --repo-root DIR --workdir DIR --hosts N [--forks F] [--budget-sec S] [--no-progress] [--octet 1] [--label TEXT]
#   --forks 생략 시 scripts/gather_budget.sh 의 os 규칙 min(N, 100).  --budget-sec 는 timeout(1) 에 들어가는 값 (기본 3600).
#   --no-progress 는 ANSIBLE_JSON_PROGRESS_FILE / ANSIBLE_JSON_CHECKPOINT_FILE 을 비운다 (기록 비용 측정용).
# 실장비에 연결하지 않는다. 127.0.0.0/8 만 쓴다. 파일에 자격증명을 쓰지 않는다.
set -u

REPO_ROOT=""; WORKDIR=""; HOSTS=""; FORKS=""; BUDGET=3600; PROGRESS=1; OCTET=1; LABEL=""; INT_AT_LINES=""
while [ $# -gt 0 ]; do
    case "$1" in
        --repo-root)  REPO_ROOT="$2"; shift 2 ;;
        --workdir)    WORKDIR="$2";   shift 2 ;;
        --hosts)      HOSTS="$2";     shift 2 ;;
        --forks)      FORKS="$2";     shift 2 ;;
        --budget-sec) BUDGET="$2";    shift 2 ;;
        --no-progress) PROGRESS=0;    shift ;;
        --octet)      OCTET="$2";     shift 2 ;;
        --label)      LABEL="$2";     shift 2 ;;
        # 혼합 상태 재현용: OUTPUT 줄이 N개 쌓인 순간 timeout(1) 프로세스에 SIGINT 를 보낸다. timeout 은 타이머 만료 때와
        # 똑같이 자식·프로세스 그룹에 INT 를 전달하지만, 타이머가 만료된 것이 아니므로 rc 는 124 가 아니라 ansible 의 99 다.
        --int-when-output-lines) INT_AT_LINES="$2"; shift 2 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done
if [ -z "$REPO_ROOT" ] || [ -z "$WORKDIR" ] || [ -z "$HOSTS" ]; then
    echo "usage: $0 --repo-root DIR --workdir DIR --hosts N [--forks F] [--budget-sec S] [--no-progress] [--octet 1] [--label TEXT]" >&2
    exit 2
fi
if [ -z "$FORKS" ]; then FORKS=$(( HOSTS < 100 ? HOSTS : 100 )); fi
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$REPO_ROOT" && pwd)"
mkdir -p "$WORKDIR"; WORKDIR="$(cd "$WORKDIR" && pwd)"
rm -rf "$WORKDIR"/gather_* "$WORKDIR"/time.txt "$WORKDIR"/stdout.log "$WORKDIR"/stderr.log "$WORKDIR"/mem.json \
       "$WORKDIR"/summary.json "$WORKDIR"/finalize.stderr "$WORKDIR"/orphans.txt "$WORKDIR"/inventory_input.json

# ── 합성 인벤토리 + 접수 manifest (Jenkinsfile_portal Validate 가 만드는 SE_MANIFEST_JSON 과 같은 키) ───────────────
python3 - "$WORKDIR" "$HOSTS" "$OCTET" "${LABEL:-1}" <<'PY'
import json, sys
ws, n, octet, label = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
ips = [f"127.0.{octet + i // 250}.{1 + i % 250}" for i in range(n)]
assert len(set(ips)) == n and all(ip.startswith("127.") for ip in ips)
with open(f"{ws}/inventory_input.json", "w", encoding="utf-8") as fh:
    fh.write(json.dumps([{"service_ip": ip} for ip in ips]))
manifest = {"schema": 1,
            "build": {"job": "phase5-emulation", "number": label, "url": None},
            "channel": "os",
            "request": {"loc": "x", "deploymentEnvironmentId": "emulation", "eventUuid": "",
                        "callbackUrl": "http://127.0.0.1:9/callback"},
            "ips": ips}
with open(f"{ws}/gather_manifest.json", "w", encoding="utf-8") as fh:
    fh.write(json.dumps(manifest) + "\n")
PY

# ── Jenkinsfile_portal Gather 와 같은 환경 ─────────────────────────────────────────────────────────────────────
export REPO_ROOT
export ANSIBLE_CONFIG="$REPO_ROOT/ansible.cfg"
export ANSIBLE_JSON_OUTPUT_FILE="$WORKDIR/gather_output.json"
export ANSIBLE_JSON_MANIFEST_FILE="$WORKDIR/gather_manifest.json"
if [ "$PROGRESS" = 1 ]; then
    export ANSIBLE_JSON_PROGRESS_FILE="$WORKDIR/gather_progress.jsonl"
    export ANSIBLE_JSON_CHECKPOINT_FILE="$WORKDIR/gather_checkpoint.jsonl"
else
    unset ANSIBLE_JSON_PROGRESS_FILE ANSIBLE_JSON_CHECKPOINT_FILE
fi
export SE_AUTH_EVIDENCE_DIR="$WORKDIR/gather_auth_evidence"
export SE_BUILD_ID="phase5-${LABEL:-run}"
export SE_EVENT_UUID=""
INVENTORY_JSON="$(cat "$WORKDIR/inventory_input.json")"; export INVENTORY_JSON

VAULT_TMP="$(mktemp)"
trap 'rm -f "$VAULT_TMP"' EXIT
printf '%s' 'phase5-dummy-vault-password-not-a-credential' > "$VAULT_TMP"   # 실패 경로는 vault 를 열지 않는다
chmod 600 "$VAULT_TMP"
chmod +x "$REPO_ROOT/os-gather/inventory.sh"
cd "$REPO_ROOT"

# ── 실행: time -v ( timeout --signal=INT --kill-after=90 BUDGET ansible-playbook ... ) + 메모리 샘플러 ───────────────
START_EPOCH="$(date +%s.%N)"
/usr/bin/time -v -o "$WORKDIR/time.txt" \
    timeout --signal=INT --kill-after=90 "$BUDGET" \
    ansible-playbook "$REPO_ROOT/os-gather/site.yml" -i "$REPO_ROOT/os-gather/inventory.sh" -f "$FORKS" \
        --vault-password-file="$VAULT_TMP" -e se_location=x \
    > "$WORKDIR/stdout.log" 2> "$WORKDIR/stderr.log" &
TIME_PID=$!
# timeout(1) 은 (--foreground 가 아니면) 자기 PID 를 PGID 로 하는 새 프로세스 그룹을 만들고 그 그룹 전체에 신호를 보낸다.
# 종료 뒤 그 PGID 로 남은 프로세스가 **이 실행의** 고아다 (같은 machine 의 다른 세션 ansible 과 구분).
TIMEOUT_PID=""
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    TIMEOUT_PID="$(pgrep -P "$TIME_PID" 2>/dev/null | head -1)"
    [ -n "$TIMEOUT_PID" ] && break
    sleep 0.1
done
python3 "$SCRIPT_DIR/phase5_mem_sampler.py" --root-pid "$TIME_PID" --out "$WORKDIR/mem.json" --interval 0.5 &
SAMPLER_PID=$!
WATCHER_PID=""
if [ -n "$INT_AT_LINES" ] && [ -n "$TIMEOUT_PID" ]; then
    (
        while kill -0 "$TIME_PID" 2>/dev/null; do
            n=0
            [ -f "$WORKDIR/gather_output.json" ] && n="$(wc -l < "$WORKDIR/gather_output.json" 2>/dev/null || echo 0)"
            if [ "${n:-0}" -ge "$INT_AT_LINES" ]; then
                printf 'fired_epoch=%s output_lines_at_fire=%s\n' "$(date +%s.%N)" "$n" > "$WORKDIR/watcher_int.txt"
                kill -INT "$TIMEOUT_PID" 2>/dev/null
                break
            fi
            sleep 0.02
        done
    ) &
    WATCHER_PID=$!
fi
wait "$TIME_PID"; RC=$?
[ -n "$WATCHER_PID" ] && { kill "$WATCHER_PID" 2>/dev/null; wait "$WATCHER_PID" 2>/dev/null; }
END_EPOCH="$(date +%s.%N)"
echo "$RC" > "$WORKDIR/gather_rc.txt"
wait "$SAMPLER_PID" 2>/dev/null || true

# ── 고아 프로세스 확인 (INT 뒤 worker / 모듈 프로세스가 남았는가) — 즉시 + 2초 뒤 ──────────────────────────────
{
    for t in 0 2; do
        [ "$t" = 2 ] && sleep 2
        echo "== pgid=${TIMEOUT_PID:-?} t+${t}s"
        ps -eo pid,pgid,ppid,etimes,stat,cmd 2>/dev/null | awk -v g="${TIMEOUT_PID:-0}" 'NR>1 && $2==g' || true
        echo "(end)"
        echo "== global t+${t}s"
        ps -eo pid,pgid,ppid,etimes,stat,cmd 2>/dev/null | grep -E '[a]nsible-playbook|[A]nsiballZ|[p]recheck_bundle' || echo "(none)"
        echo "(end)"
    done
} > "$WORKDIR/orphans.txt" 2>&1

# ── rc → outcome (Jenkinsfile_portal 과 같은 매핑) ───────────────────────────────────────────────────────────────
case "$RC" in
    0|2|4|8) OUTCOME=completed ;;
    124)     OUTCOME=timeout ;;
    137)     OUTCOME=timeout_killed ;;
    90)      OUTCOME=prep_failed ;;
    *)       OUTCOME=failed_run ;;
esac

# ── Layer A finalize (Jenkinsfile_portal post{always} 와 같은 호출) ─────────────────────────────────────────────
F_START="$(date +%s.%N)"
timeout 120 python3 "$REPO_ROOT/scripts/finalize_gather_output.py" --workspace "$WORKDIR" --repo-root "$REPO_ROOT" --outcome "$OUTCOME" \
    2> "$WORKDIR/finalize.stderr"
F_RC=$?
F_END="$(date +%s.%N)"

python3 "$SCRIPT_DIR/phase5_report.py" summarize --workdir "$WORKDIR" --hosts "$HOSTS" --forks "$FORKS" --budget-sec "$BUDGET" \
    --progress "$PROGRESS" --label "${LABEL:-}" --rc "$RC" --outcome "$OUTCOME" \
    --wall-start "$START_EPOCH" --wall-end "$END_EPOCH" --finalize-rc "$F_RC" --finalize-start "$F_START" --finalize-end "$F_END"     --timeout-pid "${TIMEOUT_PID:-0}"
