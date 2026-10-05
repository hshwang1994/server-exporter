#!/bin/bash
# tests/jenkins/harness/term_probe.sh — 실제 Runner 의 종료 동작 진단 (main 전용, 2026-10-05 최종 실행 지시 §6-2 · GP-14 · GP-19). 운영 코드가 아니다.
#
# 이 Runner 의 ansible-core · coreutils timeout 으로 세 경로를 실제로 돌려 관측한다:
#   A. 태스크 timeout (Add-on hook 의 include_role apply.timeout 과 같은 장치): 끊긴 태스크의 자식 프로세스가 남는가
#   B. 배치 상한의 INT 경로 (Jenkinsfile_portal: timeout --signal=INT --kill-after=… ansible-playbook): rc 와 자식 잔존
#   C. kill-after 경로: INT 를 무시하는 실행(INT 소실 재현) → KILL → rc 137 과 자식 잔존. C1 = ansible-playbook, C2 = 대조(sleep)
# 대상은 localhost(connection=local)뿐이다 — 원격 host 의 자식 잔존은 이 진단의 범위 밖이다(같은 장치가 원격에서 남기는 것은 별도).
# 이 스크립트가 만든 프로세스만 고유 marker(SE_TERMPROBE_<빌드>_<pid>_<경로>)로 찾고 정리한다. 다른 프로세스는 건드리지 않는다.
#   usage: bash tests/jenkins/harness/term_probe.sh <output file>
# 종료 코드: 0 관측 완료 · 1 자기 marker 프로세스를 정리하지 못함 · 2 대조(C2)가 kill-after 를 재현하지 못함(도구 이상)
set -u
OUT="${1:-term_probe.txt}"
U="SE_TERMPROBE_${BUILD_NUMBER:-0}_$$"
WD="$(mktemp -d)"
cleanup() {
    for s in A B C1 C2; do pkill -f "${U}_${s} " 2>/dev/null || true; done
    rm -rf "$WD"
}
trap cleanup EXIT
exec > >(tee "$OUT") 2>&1

echo "[term-probe] node=$(hostname) kernel=$(uname -r) user=$(id -un) marker=${U}"
echo "[term-probe] $(ansible --version 2>/dev/null | head -1) | python=$(python3 --version 2>&1) | $(timeout --version 2>/dev/null | head -1)"
printf 'localhost ansible_connection=local ansible_python_interpreter=%s\n' "$(command -v python3)" > "$WD/inv.ini"
# 저장소 ansible.cfg 는 script · auto 인벤토리 플러그인만 켜고 unparsed_is_failed=True 다(2026-10-05 F03) — 이 진단의 ini 인벤토리를 읽게 켠다
export ANSIBLE_INVENTORY_ENABLED=ini,script,auto

play() {   # play <file> <marker> [task timeout s]
    {
        echo "- hosts: localhost"
        echo "  gather_facts: false"
        echo "  tasks:"
        echo "    - name: term-probe child"
        if [ -n "${3:-}" ]; then echo "      timeout: $3"; fi
        echo "      ansible.builtin.shell: exec -a $2 sleep 45"
        echo "      args:"
        echo "        executable: /bin/bash"
    } > "$1"
}
left() { pgrep -f "$1 " 2>/dev/null | wc -l | tr -d ' '; }   # marker 뒤 공백 — exec -a 로 argv0 가 marker, argv1 이 45
now() { date +%s.%N; }
el() { awk -v a="$1" -v b="$2" 'BEGIN { printf "%.1f", b - a }'; }
report() {   # report <id> <rc> <t0> <t1> <log>
    local id="$1" rc="$2" t0="$3" t1="$4" log="$5" n1 n2
    sleep 2
    n1=$(left "${U}_${id}")
    pkill -f "${U}_${id} " 2>/dev/null || true
    sleep 1
    n2=$(left "${U}_${id}")
    echo "[term-probe] RESULT ${id} rc=${rc} elapsed=$(el "$t0" "$t1")s leftover_children=${n1} after_cleanup=${n2}"
    grep -iE "expected time frame|timed out|timeout|interrupt|User interrupted|ERROR!" "$log" 2>/dev/null | head -3 | sed "s/^/[term-probe]   ${id} log: /"
}

# ── A. 태스크 timeout 3 s (Add-on apply.timeout 과 같은 장치) — 플레이북 전체는 120 s 로 감싼다
play "$WD/a.yml" "${U}_A" 3
t0=$(now); timeout 120 ansible-playbook -i "$WD/inv.ini" "$WD/a.yml" > "$WD/a.log" 2>&1; rc=$?; t1=$(now)
report A "$rc" "$t0" "$t1" "$WD/a.log"

# ── B. 배치 상한 INT 경로 — 6 s 에 INT, 30 s 뒤 KILL (Jenkinsfile 은 <budget> 과 90 s)
play "$WD/b.yml" "${U}_B"
t0=$(now); timeout --signal=INT --kill-after=30 6 ansible-playbook -i "$WD/inv.ini" "$WD/b.yml" > "$WD/b.log" 2>&1; rc=$?; t1=$(now)
report B "$rc" "$t0" "$t1" "$WD/b.log"

# ── C1. INT 를 무시하는 ansible-playbook (상속된 SIG_IGN — INT 소실 재현) → kill-after 6 s
play "$WD/c1.yml" "${U}_C1"
t0=$(now); timeout --signal=INT --kill-after=6 4 bash -c 'trap "" INT; exec ansible-playbook -i "$0" "$1"' "$WD/inv.ini" "$WD/c1.yml" > "$WD/c1.log" 2>&1; rc=$?; t1=$(now)
report C1 "$rc" "$t0" "$t1" "$WD/c1.log"

# ── C2. 대조: INT 를 무시하는 단일 프로세스 → kill-after 3 s → rc 137 이어야 한다(coreutils timeout 의 KILL 경로)
t0=$(now); timeout --signal=INT --kill-after=3 2 bash -c "trap '' INT; exec -a ${U}_C2 sleep 30" > "$WD/c2.log" 2>&1; rc_c2=$?; t1=$(now)
report C2 "$rc_c2" "$t0" "$t1" "$WD/c2.log"

rest=0
for s in A B C1 C2; do n=$(left "${U}_${s}"); rest=$((rest + n)); done
echo "[term-probe] marker processes remaining after cleanup: ${rest}"
[ "$rest" -eq 0 ] || exit 1
[ "$rc_c2" -eq 137 ] || exit 2
exit 0
