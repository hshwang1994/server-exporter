"""Jenkins callback_body.json(gatherInfoJson 봉투 목록) 대조 · 요약 (2026-11-09).

대조 키: status · sections · errors · correlation · data.hardware.serial · diagnosis(details 제외 최상위) ·
diagnosis.details 의 serial_number · notices · account_service · 키 집합 · 봉투 키 집합.
변동 값(센서 · 사용률 · 시각)은 대조하지 않는다 — 계약 판정에 쓰는 키만 본다.
"""
from __future__ import annotations

import collections
import json
from pathlib import Path


def envelopes(path: Path) -> list[dict]:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    g = d.get("gatherInfoJson")
    return json.loads(g) if isinstance(g, str) else (g or [])


def view(e: dict) -> dict:
    dg = dict(e.get("diagnosis") or {})
    det = dg.pop("details", None) or {}
    return {
        "status": e.get("status"),
        "sections": e.get("sections"),
        "errors": e.get("errors"),
        "correlation": e.get("correlation"),
        "hardware.serial": ((e.get("data") or {}).get("hardware") or {}).get("serial"),
        "diagnosis": dg,
        "details.serial_number": det.get("serial_number"),
        "details.notices": det.get("notices"),
        "details.account_service": det.get("account_service"),
        "details.keys": sorted(det),
        "envelope.keys": sorted(e),
    }


def compare(prev_path: Path, new_path: Path, label: str = "") -> tuple[int, list[str]]:
    """(차이 host 수, 보고 줄). 0 이면 같다."""
    prev = {e.get("ip"): e for e in envelopes(prev_path)}
    new = {e.get("ip"): e for e in envelopes(new_path)}
    out: list[str] = []
    bad = 0
    if set(prev) != set(new):
        out.append(f"[NG] host set differs: only prev={sorted(set(prev) - set(new))} only new={sorted(set(new) - set(prev))}")
        bad += 1
    for ip in sorted(set(prev) & set(new)):
        a, b = view(prev[ip]), view(new[ip])
        diff = [k for k in a if a[k] != b[k]]
        if diff:
            bad += 1
            out.append(f"[DIFF] {ip}: {', '.join(diff)}")
            for k in diff:
                out.append(f"    {k}: prev={json.dumps(a[k], ensure_ascii=False)[:300]}")
                out.append(f"    {k}: new ={json.dumps(b[k], ensure_ascii=False)[:300]}")
        else:
            out.append(f"[SAME] {ip}: status={b['status']} serial={b['hardware.serial']}")
    return bad, [f"== {label} hosts prev={len(prev)} new={len(new)} differing={bad}", *out]


def summarize(path: Path) -> dict:
    es = envelopes(path)
    st = collections.Counter(e.get("status") for e in es)
    codes = collections.Counter((e.get("diagnosis") or {}).get("failure_code") for e in es if e.get("status") != "success")
    acct = [((e.get("diagnosis") or {}).get("details") or {}).get("account_service") for e in es if e.get("target_type") == "redfish"]
    return {
        "hosts": len(es),
        "status": dict(st),
        "failure_codes": dict(codes),
        "errors": sum(len(e.get("errors") or []) for e in es),
        "success_with_serial": sum(1 for e in es if e.get("status") == "success" and (e.get("correlation") or {}).get("serial_number")),
        "details_serial_number": sum(1 for e in es if "serial_number" in ((e.get("diagnosis") or {}).get("details") or {})),
        "redfish_account_service_empty": f"{sum(1 for a in acct if not a)}/{len(acct)}" if acct else None,
        "envelope_keys_13": all(len(e) == 13 for e in es),
    }
