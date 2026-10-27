"""Tier 2: 미러를 in-process 로 재생해 모듈 수준(GOLDEN_KEYS) 산출을 남긴다 (emulator_harness.run_gather 경로).

사용: python tier2_replay.py <out_dir> <label>=<mirror_dir> [...] [--layout L] [--firmware-scope S] [--tag plain]
정책은 mirror_policy.Mirror 와 같다(익명 401 / Basic 통과 / hang=timeout). 네트워크 0.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
REPO = Path(os.environ.get("SE_REPO_ROOT") or HERE.parents[2])
os.environ.setdefault("SE_REPO_ROOT", str(REPO))
from mirror_policy import Mirror  # noqa: E402
sys.path.insert(0, str(REPO / "tests" / "integration"))
import emulator_harness as H  # noqa: E402


def make_impls(mirror: Mirror):
    def get_impl(bmc_ip, path, username, password, timeout, verify_ssl):
        return mirror.module_response(path, authed=bool(username))

    def noauth_impl(bmc_ip, path, timeout, verify_ssl):
        return mirror.module_response(path, authed=False)

    def realm_impl(bmc_ip, timeout, verify_ssl):
        # 무인증 root 가 200 이면 realm 없음; 401 이면 manifest realm 에서 vendor hint
        st, _h, _b, _n = mirror.lookup("", False)
        if st == 200:
            return None
        if mirror.realm:
            import re
            m = re.search(r'realm\s*=\s*"([^"]+)"', mirror.realm, re.IGNORECASE)
            if m:
                aliases = H.rg._load_vendor_aliases_file()
                vm = {**H.rg._FALLBACK_VENDOR_MAP, **aliases}
                return H.rg._vendor_from_text(m.group(1).lower().strip(), vm)
        return None

    return get_impl, noauth_impl, realm_impl


def replay_one(mirror_dir, layout=None, firmware_scope=None):
    """미러 1대 -> (모듈 산출 dict | None, 예외 문자열 | None, Mirror)."""
    mirror = Mirror(mirror_dir)
    g, n, r = make_impls(mirror)
    try:
        res = H.run_gather(g, n, r, ip="127.0.0.1", user="infraops", pw="x", timeout=30, verify_ssl=False,
                           manager_layout=layout, firmware_scope=firmware_scope)
        return res, None, mirror
    except Exception as e:  # 재생 자체가 죽으면 가짜 성공 대신 기록
        return None, f"{type(e).__name__}: {e}", mirror


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("targets", nargs="+", help="label=mirror_dir")
    ap.add_argument("--layout", default=None)
    ap.add_argument("--firmware-scope", default=None)
    ap.add_argument("--tag", default="plain")
    a = ap.parse_args()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary = []
    for t in a.targets:
        label, _, mdir = t.partition("=")
        t0 = time.time()
        res, err, mirror = replay_one(mdir, a.layout, a.firmware_scope)
        rec = {"label": label, "mirror": mdir, "tag": a.tag, "layout": a.layout, "firmware_scope": a.firmware_scope,
               "elapsed_s": round(time.time() - t0, 1), "exception": err,
               "mirror_stats": {k: v for k, v in mirror.stats.items()
                                if k in ("files", "keyed", "non_json", "skipped", "from_manifest", "statuses")},
               "hang": sorted(mirror.hang)}
        if res is not None:
            rec.update({"status": res.get("status"), "vendor": res.get("vendor"), "collected": res.get("collected"),
                        "failed_sections": res.get("failed_sections"), "unsupported_sections": res.get("unsupported_sections"),
                        "error_count": res.get("error_count", len(res.get("errors") or [])),
                        "probe_facts": res.get("probe_facts"),
                        "data_sections": {k: (type(v).__name__ if v is not None else None)
                                          for k, v in (res.get("data") or {}).items()},
                        "multi_node": (None if res.get("multi_node") is None else "dict")})
            with open(out / f"{label}.{a.tag}.module.json", "w", encoding="utf-8", newline="\n") as f:
                json.dump(res, f, ensure_ascii=False, indent=1, sort_keys=True, default=str)
        summary.append(rec)
        print(json.dumps({k: rec.get(k) for k in ("label", "status", "vendor", "collected", "failed_sections",
                                                   "unsupported_sections", "error_count", "elapsed_s", "exception")},
                         ensure_ascii=False), flush=True)
    with open(out / f"_summary.{a.tag}.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
