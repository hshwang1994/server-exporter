#!/usr/bin/env python3
"""scripts/ai/redfish_coverage_diff.py — Redfish 노출(exposed) vs 요청(requested) 리소스 커버리지 diff (2026-10-19).

수집기(redfish-gather/library/redfish_gather.py)는 자기가 아는 path 만 GET 한다. 그래서 BMC 가 노출하는 리소스 가운데
무엇을 한 번도 읽지 않는지는 코드를 읽어서는 알 수 없고, 실 장비에서 떠온 전수 미러/크롤 위에서 수집기를 실제로 돌려
요청 path 를 세어 보아야 한다. 이 스크립트가 그 diff 를 만든다.

    exposed   = 미러/크롤에 있는 2xx dict 리소스 (@odata.id → rg._p 정규화 키)
    requested = 수집기가 재생 중 실제로 GET 한 path (인증 GET + 무인증 GET — 캐시 hit 는 첫 요청에 이미 들어 있다)
    untouched = exposed − requested  → @odata.type 별 히스토그램 + 허용 목록(allowlist) 밖의 타입과 path 나열

입력 형식 2종 (자동 판별):
  (a) 전수 미러 트리  — redfish_full_mirror.py 산출 `<dir>/redfish/v1/.../index.json` (+ headers.json)
      → tests/redfish-probe/replay_full_mirror.build_response_map
  (b) 전수 크롤 디렉터리 — tests/reference/redfish/<vendor>/<ip>/*.json ({"_meta": {"uri", "code"}, "_data": body})
      → tests/integration/emulator_harness.make_crawl_recording + make_replayer

재생은 emulator_harness.run_gather (main() gather 흐름 1:1 미러) 로 하고, 요청 path 는 tests/integration/test_request_budget.py
와 같은 방식으로 _get_impl / _get_noauth seam 을 감싸서 센다. 네트워크 0 — 재생 중 urlopen 은 차단한다.

허용 목록 (기본 tests/reference/redfish/coverage_allowlist.yml):
    types:         의도적으로 읽지 않는 타입 → 사유                     (Sensor · LogEntry · Certificate …)
    conditional:   표준 path 에 데이터가 없을 때만 읽는 타입 → 사유       (PCIeDevice · NetworkInterface …)
    path_patterns: 타입은 읽지만 특정 인스턴스를 GET 전에 거르는 경우 → 정규식 → 사유 (선택)
타입 이름은 @odata.type 에서 '#' 과 버전을 뗀 마지막 토큰이다 ('#Sensor.v1_2_0.Sensor' → 'Sensor').

사용:
    python scripts/ai/redfish_coverage_diff.py <crawl_or_mirror_dir> [--layout rmc_primary] [--allowlist path] [--json out]
    python scripts/ai/redfish_coverage_diff.py tests/reference/redfish/dell/10_100_15_27
    python scripts/ai/redfish_coverage_diff.py "C:/github/서버mock데이터/HPE_CSUS3200/03" --layout rmc_primary
    python scripts/ai/redfish_coverage_diff.py <dir> --no-allowlist      # 히스토그램만 (허용 목록 적용 안 함)

종료 코드: 0 = 허용 목록 밖 타입 없음(또는 허용 목록 미적용), 1 = 허용 목록 밖 타입 있음, 2 = 입력 오류.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO / "tests" / "redfish-probe", REPO / "tests" / "integration"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# import 순서가 중요하다 — replay_full_mirror 가 ansible.module_utils.basic 을 stub 한 뒤 redfish_gather 를 import 한다.
# emulator_harness 도 같은 stub 을 setdefault 로 깔고 같은 모듈 객체(sys.modules 캐시)를 받는다.
import replay_full_mirror as RFM  # noqa: E402
import emulator_harness as H  # noqa: E402

rg = H.rg

DEFAULT_ALLOWLIST = REPO / "tests" / "reference" / "redfish" / "coverage_allowlist.yml"
_MISS = (404, {}, "HTTP 404: Not Found (coverage-miss: path not in source)")
EXAMPLES = 3


# ---------------------------------------------------------------------------
# 정규화
# ---------------------------------------------------------------------------
def norm_path(path):
    """요청/노출 path 의 비교 키 — 쿼리(`?$skip=…` 페이지네이션)와 양끝 '/' 를 뗀다. ServiceRoot 는 ''."""
    return str(path if path is not None else "").split("?", 1)[0].strip("/")


def type_name(odata_type):
    """'#Sensor.v1_2_0.Sensor' → 'Sensor', '#SensorCollection.SensorCollection' → 'SensorCollection'. 없으면 '(none)'."""
    if not isinstance(odata_type, str) or not odata_type.strip():
        return "(none)"
    tail = odata_type.strip().lstrip("#").rsplit(".", 1)[-1]
    return tail or "(none)"


def detect_format(src: Path):
    """'mirror' (redfish/v1/.../index.json 트리) | 'crawl' (평면 *.json wrapper) | None."""
    if (src / "redfish").is_dir():
        return "mirror"
    if (src / "redfish_v1.json").is_file() or any(p.name[:1] != "_" for p in src.glob("*.json")):
        return "crawl"
    return None


# ---------------------------------------------------------------------------
# 소스 적재
# ---------------------------------------------------------------------------
class Source:
    """재생 소스 — 노출 리소스 색인 + run_gather 에 꽂을 transport 3종."""

    def __init__(self, path, fmt, resources, bodies, get_impl, noauth_impl, realm_impl, stats):
        self.path = Path(path)
        self.format = fmt
        self.resources = resources  # {norm_path: {"path","uri","status","type","odata_type","readable"}}
        self.bodies = bodies        # {norm_path: body} — 수집기가 읽은 본문 안의 @odata.id 링크를 세는 데 쓴다
        self.get_impl = get_impl
        self.noauth_impl = noauth_impl
        self.realm_impl = realm_impl
        self.stats = stats


def link_key(odata_id):
    """절대 @odata.id('/redfish/v1/Chassis/1#/Fans/0') → 요청 path 키('Chassis/1'). ServiceRoot 는 ''. 무효면 None."""
    if not isinstance(odata_id, str):
        return None
    base = odata_id.split("#", 1)[0].split("?", 1)[0]
    if base.rstrip("/") == "/redfish/v1":
        return ""
    key = rg._p(base)
    return None if key == "__invalid_odata_id__" else key


def collect_links(body):
    """본문(dict/list) 안의 모든 @odata.id → 요청 path 키 집합 (rg._p 정규화 · fragment 제거)."""
    out, stack = set(), [body]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if k == "@odata.id":
                    key = link_key(v)
                    if key is not None:
                        out.add(key)
                elif isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(cur, list):
            stack.extend(x for x in cur if isinstance(x, (dict, list)))
    return out


def _resource(path, status, body):
    ok_status = isinstance(status, int) and 200 <= status < 300
    readable = ok_status and isinstance(body, dict)
    uri = body.get("@odata.id") if isinstance(body, dict) else None
    if not isinstance(uri, str):
        uri = "/redfish/v1/" + path if path else "/redfish/v1"
    if readable:
        tname = type_name(body.get("@odata.type"))
    elif ok_status:
        tname = "(non-dict body)"
    else:
        tname = "(http %s)" % status
    return {
        "path": path,
        "uri": uri,
        "status": status,
        "odata_type": body.get("@odata.type") if isinstance(body, dict) else None,
        "type": tname,
        "readable": readable,
    }


def fold_fragments(resources):
    """`…/Power#/PowerSupplies/0` 같은 fragment 키를 본 리소스(`…/Power`)로 접는다.

    전수 크롤은 링크를 따라가며 fragment 가 붙은 @odata.id 도 저장하는데, 서버는 그 요청에 본 리소스 전체를 돌려준다 —
    즉 같은 리소스의 중복 표현이다. 접지 않으면 수집기가 `…/Power` 를 한 번 읽었는데도 fragment 수십 개가 '미읽음' 으로 잡힌다.
    같은 base 에 여러 표현이 있으면 fragment 없는 쪽 · readable 쪽을 남긴다. Returns (folded, folded_count).
    """
    folded, n_folded = {}, 0
    for path, res in resources.items():
        base = path.split("#", 1)[0].rstrip("/")
        if base != path:
            n_folded += 1
        cur = folded.get(base)
        if cur is None or (res["readable"] and not cur["readable"]) or ("#" in cur["path"] and "#" not in path):
            folded[base] = dict(res, path=base)
    return folded, n_folded


def load_source(src: Path) -> Source:
    src = Path(src)
    fmt = detect_format(src)
    if fmt == "mirror":
        response_map, _service_root, stats = RFM.build_response_map(src)

        def get_impl(bmc_ip, path, username, password, timeout, verify_ssl):
            return response_map.get(norm_path(path), _MISS)

        def noauth_impl(bmc_ip, path, timeout, verify_ssl):
            return response_map.get(norm_path(path), _MISS)

        def realm_impl(bmc_ip, timeout, verify_ssl):
            return None

        resources = {k: _resource(k, v[0], v[1]) for k, v in response_map.items()}
        bodies = {k: v[1] for k, v in response_map.items() if isinstance(v[1], dict)}
        stats = {"files": stats["files"], "keyed": stats["keyed"], "dupes": len(stats["dupes"])}
    elif fmt == "crawl":
        rec = H.make_crawl_recording(src)
        get_impl, noauth_impl, realm_impl = H.make_replayer(rec)
        resources, bodies = {}, {}
        for key, val in rec.items():
            if not key.startswith("get::"):
                continue
            path = key[len("get::"):]
            resources[path] = _resource(path, val[0], val[1])
            if isinstance(val[1], dict):
                bodies[path] = val[1]
        stats = {"files": sum(1 for p in src.glob("*.json") if p.name[:1] != "_"), "keyed": len(resources), "dupes": 0}
    else:
        raise ValueError("입력 형식을 판별할 수 없다 (redfish/ 트리도, *.json 크롤도 아님): %s" % src)
    resources, stats["fragments_folded"] = fold_fragments(resources)
    bodies = {k.split("#", 1)[0].rstrip("/"): v for k, v in bodies.items()}
    return Source(src, fmt, resources, bodies, get_impl, noauth_impl, realm_impl, stats)


# ---------------------------------------------------------------------------
# 수집기 재생 + 요청 집계
# ---------------------------------------------------------------------------
def run_collector(source: Source, manager_layout=None):
    """run_gather 를 돌리며 요청 path 를 센다. Returns (requested Counter[norm_path], noauth Counter, snapshot)."""
    requested = collections.Counter()
    noauth = collections.Counter()

    def gw(bmc_ip, path, username, password, timeout, verify_ssl):
        requested[norm_path(path)] += 1
        return source.get_impl(bmc_ip, path, username, password, timeout, verify_ssl)

    def nw(bmc_ip, path, timeout, verify_ssl):
        noauth[norm_path(path)] += 1
        requested[norm_path(path)] += 1
        return source.noauth_impl(bmc_ip, path, timeout, verify_ssl)

    def _blocked(req, *args, **kwargs):
        raise RuntimeError("coverage diff 는 오프라인 재생이다 — 실 네트워크 시도: %s"
                           % getattr(req, "full_url", req))

    saved_urlopen = rg.urlreq.urlopen
    rg.urlreq.urlopen = _blocked
    try:
        snapshot = H.run_gather(gw, nw, realm_impl=source.realm_impl, manager_layout=manager_layout)
    finally:
        rg.urlreq.urlopen = saved_urlopen
    return requested, noauth, snapshot


# ---------------------------------------------------------------------------
# diff + 허용 목록
# ---------------------------------------------------------------------------
def compute_coverage(source: Source, requested):
    req = set(requested)
    exposed = {p: r for p, r in source.resources.items() if r["readable"]}
    unreadable = {p: r for p, r in source.resources.items() if not r["readable"]}
    untouched = {p: r for p, r in exposed.items() if p not in req}
    # 수집기가 실제로 읽은 본문들이 가리키는 링크 — 미읽음 리소스가 "보였는데 안 따라간 것"인지 "링크 자체가 없어 못 본 것"인지 가른다
    linked = set()
    for p in req:
        body = source.bodies.get(p)
        if body is not None:
            linked |= collect_links(body)
    by_type = collections.defaultdict(list)
    linked_by_type = collections.Counter()
    for p in sorted(untouched):
        # 표시는 키 path 기준 — 본문 @odata.id 는 Settings/fragment 변형에서 본 리소스를 가리켜 구분이 안 된다
        by_type[untouched[p]["type"]].append("/redfish/v1/" + p if p else "/redfish/v1")
        if p in linked:
            linked_by_type[untouched[p]["type"]] += 1
    exposed_by_type = collections.Counter(r["type"] for r in exposed.values())
    return {
        "exposed_readable": len(exposed),
        "exposed_unreadable": len(unreadable),
        "exposed_by_type": dict(sorted(exposed_by_type.items(), key=lambda kv: (-kv[1], kv[0]))),
        "untouched_linked_by_type": dict(linked_by_type),
        "untouched_linked_paths": sorted("/redfish/v1/" + p for p in untouched if p in linked),
        "unreadable_by_status": dict(collections.Counter(str(r["status"]) for r in unreadable.values())),
        "requested_distinct": len(req),
        "requested_total": sum(requested.values()),
        "requested_hit": len(req & set(source.resources)),
        "requested_missing": sorted(req - set(source.resources)),
        "untouched": len(untouched),
        "untouched_ratio": (len(untouched) / len(exposed)) if exposed else None,
        "untouched_by_type": dict(sorted(((t, len(v)) for t, v in by_type.items()), key=lambda kv: (-kv[1], kv[0]))),
        "_by_type_paths": dict(by_type),
    }


def load_allowlist(path):
    """허용 목록 YAML → {"types": {}, "conditional": {}, "path_patterns": {}} (없는 절은 빈 dict)."""
    import yaml  # PyYAML — tests 가 쓰는 것과 같은 의존성
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    out = {}
    for section in ("types", "conditional", "path_patterns"):
        val = doc.get(section) or {}
        if not isinstance(val, dict):
            raise ValueError("허용 목록 %s: '%s' 는 {이름: 사유} 매핑이어야 한다" % (path, section))
        out[section] = {str(k): ("" if v is None else str(v)) for k, v in val.items()}
    return out


def classify(by_type_paths, allowlist):
    """untouched 타입 → allowed / conditional / pattern / unlisted 로 가른다 (값은 path 목록)."""
    types_ok = allowlist.get("types") or {}
    cond = allowlist.get("conditional") or {}
    patterns = [(re.compile(k), k) for k in (allowlist.get("path_patterns") or {})]
    out = {"allowed": {}, "conditional": {}, "pattern": {}, "unlisted": {}}
    for t, paths in by_type_paths.items():
        if t in types_ok:
            out["allowed"][t] = list(paths)
        elif t in cond:
            out["conditional"][t] = list(paths)
        else:
            rest = []
            for p in paths:
                hit = next((k for pat, k in patterns if pat.search(p)), None)
                if hit:
                    out["pattern"].setdefault(hit, []).append(p)
                else:
                    rest.append(p)
            if rest:
                out["unlisted"][t] = rest
    return out


def audit(src, manager_layout=None, allowlist_path=None):
    """소스 적재 → 재생 → diff → (allowlist 있으면) 분류. JSON 직렬화 가능한 보고 dict 를 돌려준다."""
    source = load_source(Path(src))
    requested, noauth, snapshot = run_collector(source, manager_layout=manager_layout)
    cov = compute_coverage(source, requested)
    by_type_paths = cov.pop("_by_type_paths")
    report = {
        "source": str(source.path),
        "format": source.format,
        "manager_layout": manager_layout,
        "source_stats": source.stats,
        "vendor": snapshot.get("vendor"),
        "status": snapshot.get("status"),
        "collected": snapshot.get("collected"),
        "failed_sections": snapshot.get("failed_sections"),
        "unsupported_sections": snapshot.get("unsupported_sections"),
        "error_count": snapshot.get("error_count"),
        "noauth_requests": dict(noauth),
        **cov,
        "allowlist": str(allowlist_path) if allowlist_path else None,
        "classification": None,
        "untouched_examples": {t: paths[:EXAMPLES] for t, paths in by_type_paths.items()},
    }
    if allowlist_path:
        allowlist = load_allowlist(allowlist_path)
        cls = classify(by_type_paths, allowlist)
        report["classification"] = {
            "allowed": {t: len(v) for t, v in cls["allowed"].items()},
            "conditional": cls["conditional"],
            "pattern": cls["pattern"],
            "unlisted": cls["unlisted"],
            "allowlist_unused": sorted(
                (set(allowlist["types"]) | set(allowlist["conditional"]))
                - set(cls["allowed"]) - set(cls["conditional"])),
        }
    return report


# ---------------------------------------------------------------------------
# 출력
# ---------------------------------------------------------------------------
def _pct(x):
    return "n/a" if x is None else "%.1f%%" % (100.0 * x)


def format_summary(report, max_types=None):
    lines = []
    bar = "=" * 72
    lines.append(bar)
    lines.append("  COVERAGE : %s" % report["source"])
    lines.append("  format=%s  layout=%s  files=%s keyed=%s fragments_folded=%s" % (
        report["format"], report["manager_layout"],
        report["source_stats"].get("files"), report["source_stats"].get("keyed"),
        report["source_stats"].get("fragments_folded")))
    lines.append(bar)
    lines.append("  vendor / status  : %s / %s   collected=%s  failed=%s  unsupported=%s  errors=%s" % (
        report["vendor"], report["status"], report["collected"], report["failed_sections"],
        report["unsupported_sections"], report["error_count"]))
    lines.append("  exposed          : %d readable  (+%d non-2xx/비-dict %s)" % (
        report["exposed_readable"], report["exposed_unreadable"], report["unreadable_by_status"] or ""))
    lines.append("  requested        : %d distinct paths / %d GETs  (hit %d · 소스에 없는 path %d)" % (
        report["requested_distinct"], report["requested_total"], report["requested_hit"],
        len(report["requested_missing"])))
    lines.append("  untouched        : %d  (%s of exposed)" % (report["untouched"], _pct(report["untouched_ratio"])))
    if report["requested_missing"]:
        lines.append("  requested-but-absent (장비가 404 를 준 path): %s" % report["requested_missing"][:8])
    cls = report.get("classification")
    lines.append("  untouched by @odata.type  (untouched / exposed · linked = 수집기가 읽은 본문이 가리키는 수):")
    items = list(report["untouched_by_type"].items())
    if max_types:
        items = items[:max_types]
    totals = report.get("exposed_by_type") or {}
    linked_n = report.get("untouched_linked_by_type") or {}
    for t, n in items:
        tag = ""
        if cls:
            if t in cls["allowed"]:
                tag = "[types]"
            elif t in cls["conditional"]:
                tag = "[conditional]"
            elif t in cls["unlisted"]:
                tag = "[UNLISTED]"
            else:
                tag = "[pattern]"
        lines.append("    %-44s %5d / %-5d linked %-4d %s" % (t, n, totals.get(t, n), linked_n.get(t, 0), tag))
    if max_types and len(report["untouched_by_type"]) > max_types:
        lines.append("    … (%d more types)" % (len(report["untouched_by_type"]) - max_types))
    if cls:
        lines.append("  allowlist        : %s" % report["allowlist"])
        lines.append("    types(allowed) %d · conditional(untouched here) %d · pattern %d · UNLISTED %d" % (
            len(cls["allowed"]), len(cls["conditional"]), len(cls["pattern"]), len(cls["unlisted"])))
        if cls["conditional"]:
            lines.append("  conditional types untouched on this source (표준 path 에 데이터가 있어 fallback 미발동):")
            for t, paths in cls["conditional"].items():
                lines.append("    %-44s %5d  e.g. %s" % (t, len(paths), paths[:2]))
        if cls["unlisted"]:
            linked_paths = set(report.get("untouched_linked_paths") or [])
            lines.append("  NOT IN ALLOWLIST — 읽기 시작했거나 허용 목록에 사유를 적어라:")
            for t, paths in cls["unlisted"].items():
                lines.append("    %s (%d)" % (t, len(paths)))
                for p in paths[:EXAMPLES]:
                    lines.append("      - %s  [%s]" % (p, "linked" if p in linked_paths else "unlinked"))
        else:
            lines.append("  NOT IN ALLOWLIST : 없음")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Redfish exposed vs requested 커버리지 diff (오프라인 재생)")
    ap.add_argument("source", help="전수 미러 트리(redfish/v1/…/index.json) 또는 전수 크롤 디렉터리(*.json wrapper)")
    ap.add_argument("--layout", default=None, help="manager_layout (예: rmc_primary — CSUS/Superdome 멀티노드)")
    ap.add_argument("--allowlist", default=str(DEFAULT_ALLOWLIST),
                    help="허용 목록 YAML (기본 tests/reference/redfish/coverage_allowlist.yml)")
    ap.add_argument("--no-allowlist", action="store_true", help="허용 목록을 적용하지 않고 히스토그램만 출력")
    ap.add_argument("--json", default=None, help="보고 JSON 저장 경로")
    ap.add_argument("--max-types", type=int, default=None, help="히스토그램 출력 타입 수 상한 (기본 전부)")
    args = ap.parse_args(argv)

    src = Path(args.source)
    if not src.is_dir():
        print("[FAIL] 소스 디렉터리 없음: %s" % src, file=sys.stderr)
        return 2
    allowlist_path = None
    if not args.no_allowlist:
        allowlist_path = Path(args.allowlist)
        if not allowlist_path.is_file():
            print("[WARN] 허용 목록 없음 (%s) — 히스토그램만 출력" % allowlist_path, file=sys.stderr)
            allowlist_path = None
    try:
        report = audit(src, manager_layout=args.layout, allowlist_path=allowlist_path)
    except ValueError as e:
        print("[FAIL] %s" % e, file=sys.stderr)
        return 2

    print(format_summary(report, max_types=args.max_types))
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                       encoding="utf-8", newline="\n")
        print("  report saved     : %s" % out)
    cls = report.get("classification")
    return 1 if (cls and cls["unlisted"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
