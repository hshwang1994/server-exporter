#!/usr/bin/env python3
"""실 미러 ServiceRoot 기준 adapter 선택 검증 (운영 detect_vendor.yml 로직 재현).

replay_full_mirror.py 는 라이브러리 수집(_get monkeypatch)만 재생하고 adapter_loader 선택은
거치지 않는다. 본 도구는 그 공백을 메운다 — 각 미러의 무인증 ServiceRoot(_serviceroot_noauth.json)
에서 vendor 감지 → _extract_probe_facts → detect_vendor.yml 의 facts 조립(model/firmware) →
adapter_common 으로 전 redfish adapter 매칭·점수 → 선택될 adapter + 점수 breakdown 을 출력한다.

용도:
  - 새 adapter / priority / firmware_patterns / model_patterns 변경 시 실 장비에서 어느 adapter 가
    선택되는지 오프라인 실측 (firmware_patterns 오실격 / priority 역전 회귀 차단).
  - HPE 만 _extract_probe_facts 가 model/firmware 를 채우고 Dell/Lenovo 등은 빈 dict → priority 선택
    임을 가시화.

stdlib + yaml only (adapter_common 과 동일). 사용:
    python tests/redfish-probe/verify_adapter_selection.py [<mirror_base_dir>]
    # <mirror_base_dir> 기본값 = C:\\github\\서버mock데이터 (없으면 argv[1] 로 지정)
"""
import json
import sys
import types
import glob
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))
sys.path.insert(0, str(REPO / "module_utils"))

# ansible.module_utils.basic stub (replay_full_mirror.py 와 동일 — 오프라인)
_b = types.ModuleType("ansible.module_utils.basic"); _b.AnsibleModule = object
_mu = types.ModuleType("ansible.module_utils"); _mu.basic = _b
_a = types.ModuleType("ansible"); _a.module_utils = _mu
sys.modules.setdefault("ansible", _a)
sys.modules.setdefault("ansible.module_utils", _mu)
sys.modules.setdefault("ansible.module_utils.basic", _b)

import redfish_gather as rg  # noqa: E402
import adapter_common as ac  # noqa: E402
import yaml  # noqa: E402

ALIASES = ac.load_vendor_aliases(str(REPO / "common" / "vars" / "vendor_aliases.yml"))
ADAPTER_DIR = REPO / "adapters" / "redfish"


def load_serviceroot(mirror_dir: Path):
    """무인증 ServiceRoot 우선(detect_vendor probe 와 동일), 없으면 authed root index.json."""
    na = mirror_dir / "_serviceroot_noauth.json"
    if na.exists():
        d = json.loads(na.read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("body"), dict):
            return d["body"], "noauth"
    idx = mirror_dir / "redfish" / "v1" / "index.json"
    if idx.exists():
        return json.loads(idx.read_text(encoding="utf-8")), "authed-root"
    return None, None


def assemble_facts(root):
    """detect_vendor.yml 의 facts 조립 재현 (무인증 → data.* 빈 가정)."""
    vendor = rg._detect_vendor_from_service_root(root) or "unknown"
    hints = rg._extract_probe_facts(root, vendor)
    model = hints.get("model_hint", "") or ""
    firmware = (hints.get("firmware_hint", "") or hints.get("manager_type", "") or "")
    return {"vendor": vendor, "model": model, "firmware": firmware}, hints


def select_adapter(facts):
    scored = []
    for path in sorted(glob.glob(str(ADAPTER_DIR / "*.yml"))):
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            continue
        data["_filename"] = os.path.basename(path)
        if ac.adapter_matches(data, facts, ALIASES):
            sc = ac.adapter_score(data, facts, ALIASES)
            if sc > -9999:
                scored.append((sc, data.get("adapter_id", data["_filename"]), data["_filename"]))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def main():
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"C:\github\서버mock데이터")
    devices = {
        "HPE_CSUS3200": ["01", "02", "03", "04"],
        "DELL_R740": ["01"],
        "HPE_DL380": ["01"],
        "Lenovo_SR650": ["01"],
    }
    rc = 0
    for dev, subs in devices.items():
        for sub in subs:
            mdir = base / dev / sub
            print("=" * 70)
            print(f"{dev}/{sub}")
            if not mdir.exists():
                print("  [MISSING]")
                rc = 2
                continue
            root, src = load_serviceroot(mdir)
            if root is None:
                print("  [NO SERVICEROOT]")
                rc = 2
                continue
            facts, hints = assemble_facts(root)
            print(f"  ServiceRoot.Product = {root.get('Product')!r}  RedfishVersion={root.get('RedfishVersion')!r}")
            print(f"  hints           : {hints}")
            print(f"  facts(vendor/model/firmware) : {facts['vendor']!r} / {facts['model']!r} / {facts['firmware']!r}")
            scored = select_adapter(facts)
            if not scored:
                print("  [SELECT] no match -> generic fallback")
            else:
                win = scored[0]
                print(f"  [SELECT] -> {win[1]}  (score={win[0]}, file={win[2]})")
                for sc, aid, fn in scored[:5]:
                    print(f"           {sc:>8}  {aid}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
