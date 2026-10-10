"""Jenkinsfile_portal ↔ inventory.sh 접수 목록 전달 계약 (2026-10-10 FL-F11).

여기서 고정하는 것은 두 구성요소가 **소비하는 문자열**만이다 — 환경변수 이름 · 파일 이름 (제어 흐름은 Harness 가 실제 함수를 돌려 본다).
Linux 는 환경변수 하나가 131,072 바이트를 넘으면 프로세스 실행이 "Argument list too long" 으로 실패하므로(확장형 입력 5,000대 510 KB 실측)
접수 목록은 파일로 넘어가야 한다."""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PORTAL = (REPO / "Jenkinsfile_portal").read_text(encoding="utf-8")
SCRIPTS = [REPO / f"{ch}-gather" / "inventory.sh" for ch in ("os", "esxi", "redfish")]
WRITE_LINE = "writeFile(file: '.inventory_input.json', text: (params.inventory_json ?: '') + '\\n', encoding: 'UTF-8')"


def test_inventory_json_is_not_a_pipeline_environment_variable():
    assert re.search(r"^\s*INVENTORY_JSON\s*=", PORTAL, re.M) is None, "접수 목록을 환경변수 하나로 넘기면 큰 배치에서 모든 sh 단계가 실패한다"


def test_gather_env_names_the_inventory_file():
    assert '"INVENTORY_JSON_FILE=${w}/.inventory_input.json"' in PORTAL


def test_workspace_prepare_and_resume_both_write_the_inventory_file():
    assert PORTAL.count(WRITE_LINE) == 2, PORTAL.count(WRITE_LINE)
    assert "if (!fileExists('.inventory_input.json'))" in PORTAL, "같은 Runner 재개에서 입력 파일만 없을 때 되살려야 한다"


def test_inventory_scripts_read_the_file_variable_first():
    for script in SCRIPTS:
        text = script.read_text(encoding="utf-8")
        assert text.index('os.environ.get("INVENTORY_JSON_FILE"') < text.index('os.environ.get("INVENTORY_JSON"'), script
