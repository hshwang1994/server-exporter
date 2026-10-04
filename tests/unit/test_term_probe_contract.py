"""tests/jenkins/harness/term_probe.sh · Jenkinsfile_term_probe (2026-10-05 최종 실행 지시 §6-2 — 실제 Runner 종료 동작 진단).

고정하는 것
  1. 진단은 자기가 만든 프로세스만 다룬다: pgrep/pkill 은 전부 고유 marker(`${U}_<경로> `)로 찾고, kill -9 · killall · marker 없는 pkill 은 없다.
  2. 세 경로를 모두 돈다: 태스크 timeout(A) · INT 경로(B, timeout --signal=INT --kill-after) · INT 무시 → kill-after(C1 ansible, C2 대조).
  3. Job 은 지정 노드에서 probe 와 Add-on hook 통합 테스트(-v)를 돌리고 두 결과 파일을 archive 한다. main 전용(*/main) · lightweight.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HARNESS = REPO / "tests" / "jenkins" / "harness"
PROBE = (HARNESS / "term_probe.sh").read_text(encoding="utf-8")

pytestmark = pytest.mark.source_text   # 저장소 메타(jenkins/jobs config · Harness Jenkinsfile)를 읽는다 — G14 overlay(production tree) 제외


def test_probe_touches_only_its_own_marker_processes():
    assert 'U="SE_TERMPROBE_${BUILD_NUMBER:-0}_$$"' in PROBE
    for line in PROBE.splitlines():
        code = line.split("#", 1)[0]
        if re.search(r"\bp(kill|grep)\b", code):
            assert '${U}_' in code or '"$1 "' in code, f"marker 없이 프로세스를 찾거나 끝낸다: {line.strip()}"
    assert "kill -9" not in PROBE and "killall" not in PROBE and "pkill -9" not in PROBE
    assert "trap cleanup EXIT" in PROBE and 'rm -rf "$WD"' in PROBE


def test_probe_covers_task_timeout_int_and_kill_after_paths():
    assert 'play "$WD/a.yml" "${U}_A" 3' in PROBE, "A: 태스크 timeout 3 s (Add-on apply.timeout 장치)"
    assert "timeout --signal=INT --kill-after=30 6 ansible-playbook" in PROBE, "B: 배치 상한 INT 경로"
    assert "trap \"\" INT; exec ansible-playbook" in PROBE and "--kill-after=6 4" in PROBE, "C1: INT 무시 ansible → kill-after"
    assert "--kill-after=3 2 bash -c \"trap '' INT; exec -a ${U}_C2 sleep 30\"" in PROBE, "C2: kill-after 대조"
    assert "ansible_connection=local" in PROBE, "대상은 localhost 뿐 — 원격 host 에 프로세스를 만들지 않는다"
    for rid in ("A", "B", "C1", "C2"):
        assert f"report {rid} " in PROBE
    assert '[ "$rc_c2" -eq 137 ] || exit 2' in PROBE


def test_term_probe_job_contract():
    jf = (HARNESS / "Jenkinsfile_term_probe").read_bytes()
    assert b"\r\n" not in jf and b"\r\n" not in (HARNESS / "term_probe.sh").read_bytes()
    text = jf.decode("utf-8")
    assert "node((params.NODE_NAME ?: 'SKHynix-Jenkins-Runner03').trim())" in text and "checkout scm" in text
    assert "bash tests/jenkins/harness/term_probe.sh term_probe.txt" in text
    assert "python3 -m pytest tests/integration/test_addon_hook_playbook.py -v -rA" in text
    assert "archiveArtifacts(artifacts: 'term_probe.txt,addon_hook_integration.txt'" in text
    assert "scripts/activate_ansible_venv.sh" in text and "/opt/ansible-env" not in text and "/app/ansible-env" not in text
    cfg = (REPO / "jenkins/jobs/clovirone-server-gather-term-probe/config.xml").read_text(encoding="utf-8")
    assert "<scriptPath>tests/jenkins/harness/Jenkinsfile_term_probe</scriptPath>" in cfg and "<name>*/main</name>" in cfg
    assert "<lightweight>true</lightweight>" in cfg and "<name>NODE_NAME</name>" in cfg
