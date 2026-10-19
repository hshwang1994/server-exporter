"""Redfish 커버리지 감사 — 전수 크롤에서 수집기가 한 번도 읽지 않는 리소스 타입은 모두 허용 목록에 사유가 있어야 한다 (2026-10-19).

배경: redfish_gather.py 는 자기가 아는 path 만 GET 한다. 실 장비 전수 크롤(tests/reference/redfish/<vendor>/<ip>/)과 비교하면
노출 리소스의 90% 이상이 미읽음인데, 대부분은 센서·로그·인증서·스키마·설정(Settings/Pending) 같은 비인벤토리다. 그러나 그 사이에
PCIeDevice · NetworkInterface · OEM 장치 인벤토리 같은 "읽어야 할지 판단이 필요한" 타입도 섞여 있어, 미읽음 타입을 허용 목록
(tests/reference/redfish/coverage_allowlist.yml)으로 한 줄씩 사유를 달아 고정한다. 새 타입이 미읽음으로 나타나면 — 코드가 읽기를
그만뒀거나, 장비가 새 리소스를 노출하기 시작했거나 — 이 시험이 멈추고 "읽기 시작했거나 허용 목록에 사유를 적어라" 고 말한다.

도구: scripts/ai/redfish_coverage_diff.py (크롤을 recording 으로 바꿔 emulator_harness.run_gather 로 오프라인 재생 · 네트워크 0).
범위: 기본은 vendor 당 첫 번째(정렬) 사용 가능한 IP 하나 — 환경변수 SE_COVERAGE_ALL=1 이면 전부. ServiceRoot 만 남은 실패 크롤
(503/timeout, 파일 10개 미만)은 건너뛴다. SE_COVERAGE_REPORT=1 이면 tests/reference/redfish/coverage_report.json 을 갱신한다
(기본 실행은 파일을 쓰지 않는다). manager_layout 은 tests/reference 에 CSUS 가 없어 전부 None 이다.
production tree 에는 scripts/ai · tests/reference 가 없으므로 모듈 수준에서 skip 한다.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CRAWL_ROOT = REPO / "tests" / "reference" / "redfish"
ALLOWLIST = CRAWL_ROOT / "coverage_allowlist.yml"
REPORT = CRAWL_ROOT / "coverage_report.json"
SCRIPT = REPO / "scripts" / "ai" / "redfish_coverage_diff.py"

if not SCRIPT.is_file():
    pytest.skip("scripts/ai/redfish_coverage_diff.py 없음 (production tree 에는 scripts/ai 가 없다)", allow_module_level=True)
if not ALLOWLIST.is_file():
    pytest.skip("tests/reference/redfish/coverage_allowlist.yml 없음", allow_module_level=True)

yaml = pytest.importorskip("yaml")
if str(SCRIPT.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT.parent))
import redfish_coverage_diff as RCD  # noqa: E402

MIN_FILES = 10          # ServiceRoot 하나만 남은 실패 크롤(cisco 10.100.15.1 = 503 · 10.100.15.3 = timeout) 제외
EXAMPLES = 3            # 실패 메시지의 타입당 예시 path 수
MANAGER_LAYOUT = {}     # vendor 디렉터리 이름 → manager_layout. CSUS/Superdome 크롤이 들어오면 {"hpe_csus": "rmc_primary"} 식으로 추가.


def _usable(crawl_dir: Path) -> bool:
    if not (crawl_dir / "redfish_v1.json").is_file():
        return False
    return sum(1 for p in crawl_dir.glob("*.json") if p.name[:1] != "_") >= MIN_FILES


def _cases():
    cases = []
    if not CRAWL_ROOT.is_dir():
        return cases
    all_ips = os.environ.get("SE_COVERAGE_ALL") == "1"
    for vendor_dir in sorted(p for p in CRAWL_ROOT.iterdir() if p.is_dir()):
        usable = [d for d in sorted(vendor_dir.iterdir()) if d.is_dir() and _usable(d)]
        if not usable:
            continue
        cases.extend(usable if all_ips else usable[:1])
    return cases


CASES = _cases()
IDS = [f"{d.parent.name}/{d.name}" for d in CASES]


def _load_allowlist():
    return yaml.safe_load(ALLOWLIST.read_text(encoding="utf-8")) or {}


def _write_report(key: str, report: dict) -> None:
    """SE_COVERAGE_REPORT=1 일 때만 — 크롤별 결과를 coverage_report.json 에 병합(read-modify-write)."""
    if os.environ.get("SE_COVERAGE_REPORT") != "1":
        return
    doc = {}
    if REPORT.is_file():
        try:
            doc = json.loads(REPORT.read_text(encoding="utf-8")) or {}
        except ValueError:
            doc = {}
    cls = report["classification"] or {}
    entry = {
        "generated_at": _dt.date.today().isoformat(),
        "source": str(Path(report["source"]).relative_to(REPO)).replace("\\", "/"),
        "manager_layout": report["manager_layout"],
        "vendor": report["vendor"],
        "status": report["status"],
        "collected": report["collected"],
        "exposed_readable": report["exposed_readable"],
        "exposed_unreadable": report["exposed_unreadable"],
        "requested_distinct": report["requested_distinct"],
        "requested_total": report["requested_total"],
        "requested_missing": report["requested_missing"],
        "untouched": report["untouched"],
        "untouched_ratio": report["untouched_ratio"],
        "untouched_by_type": report["untouched_by_type"],
        "exposed_by_type": report["exposed_by_type"],
        "allowed_types": cls.get("allowed"),
        "conditional_untouched": cls.get("conditional"),
        "pattern_matched": cls.get("pattern"),
        "unlisted": cls.get("unlisted"),
        "allowlist_unused_here": cls.get("allowlist_unused"),
    }
    doc.setdefault("_about", "tests/regression/test_redfish_coverage_audit.py 가 SE_COVERAGE_REPORT=1 일 때 쓴다 — 크롤별 exposed/requested/untouched 와 허용 목록 분류")
    doc.setdefault("crawls", {})[key] = entry
    REPORT.write_text(json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


@pytest.mark.skipif(not CASES, reason="tests/reference/redfish 에 사용 가능한 크롤이 없다")
@pytest.mark.parametrize("crawl_dir", CASES, ids=IDS)
def test_untouched_types_are_allowlisted(crawl_dir: Path):
    vendor = crawl_dir.parent.name
    report = RCD.audit(crawl_dir, manager_layout=MANAGER_LAYOUT.get(vendor), allowlist_path=ALLOWLIST)
    _write_report(f"{vendor}/{crawl_dir.name}", report)

    # 재생 자체가 실패하면 "미읽음" 은 의미가 없다 — 그 경우를 허용 목록 뒤에 숨기지 않는다.
    assert report["status"] in ("success", "partial"), (
        f"{vendor}/{crawl_dir.name}: 재생 status={report['status']} (vendor={report['vendor']}, "
        f"failed={report['failed_sections']}) — 크롤 재생이 깨졌다. 커버리지 판정 이전 문제.")
    assert report["requested_distinct"] >= 20, f"{vendor}/{crawl_dir.name}: 요청 path 가 {report['requested_distinct']}개뿐 — 재생이 조기 종료됐다"

    unlisted = report["classification"]["unlisted"]
    if unlisted:
        lines = [
            f"{vendor}/{crawl_dir.name}: 허용 목록에 없는 미읽음 타입 {len(unlisted)}개 "
            f"(exposed {report['exposed_readable']} · requested {report['requested_distinct']} · untouched {report['untouched']})",
            "읽기 시작했거나 허용 목록에 사유를 적어라 — tests/reference/redfish/coverage_allowlist.yml (types / conditional / path_patterns)",
        ]
        for tname, paths in unlisted.items():
            lines.append(f"  - {tname} ({len(paths)} paths, exposed {report['exposed_by_type'].get(tname)})")
            for p in paths[:EXAMPLES]:
                lines.append(f"      {p}")
        pytest.fail("\n".join(lines))


def test_allowlist_is_well_formed():
    """사유 없는 항목 · 두 절에 동시에 있는 타입 · 컴파일되지 않는 path 정규식을 거부한다."""
    import re

    doc = _load_allowlist()
    for section in ("types", "conditional", "path_patterns"):
        assert isinstance(doc.get(section), dict) and doc[section], f"'{section}' 절이 비었거나 매핑이 아니다"
        for name, reason in doc[section].items():
            assert isinstance(reason, str) and reason.strip(), f"{section}.{name}: 사유(한 줄)가 없다"
    both = set(doc["types"]) & set(doc["conditional"])
    assert not both, f"types 와 conditional 양쪽에 있는 타입: {sorted(both)} — 한 곳에만 둔다"
    for pat in doc["path_patterns"]:
        re.compile(pat)
    for name in list(doc["types"]) + list(doc["conditional"]):
        assert "." not in name and not name.startswith("#"), f"{name}: 타입 이름은 '#' 과 버전을 뗀 마지막 토큰이어야 한다 (예: Sensor)"


def test_allowlist_keeps_documented_conditional_reads():
    """조건부 읽기(fallback)로 문서화된 타입이 types 로 조용히 옮겨가지 않는다 (2026-10-19 A-5 · A-8 · Power/Thermal/Storage fallback)."""
    doc = _load_allowlist()
    expected = {
        "PCIeDevice", "PCIeDeviceCollection", "PCIeFunction", "PCIeFunctionCollection", "PCIeSlots",
        "NetworkInterface", "NetworkInterfaceCollection", "DriveCollection", "Chassis",
        "PowerSubsystem", "ThermalSubsystem", "SimpleStorage", "StorageController",
    }
    missing = expected - set(doc["conditional"])
    assert not missing, f"conditional 절에서 빠진 타입: {sorted(missing)}"
