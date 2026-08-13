"""실장비 미러(`tests/reference/redfish/**`)를 계정 경로 재생에 쓰는 harness.

왜 필요한가 (2026-08-12):
  저장소에는 Dell 5호스트 / HPE 1 / Lenovo 1 / Cisco 1 의 **실제 BMC 응답 미러**가
  들어 있고 그 안에 AccountService / Accounts / ManagerAccount / Roles 가 모두 있다.
  그런데 이 자산을 읽는 테스트가 **0건**이었다(audit D-8). 계정 동작은 전부 손으로 쓴
  mock 으로만 검증되고 있었다 — 즉 "우리가 상상한 응답" 만 통과시켜 왔다.

  여기서는 미러를 그대로 재생해 **읽기 단계**(Capability Discovery / 계정 존재 판정 /
  Family 선택)를 검증한다. 쓰기는 재생하지 않는다 — 미러에는 쓰기 응답이 없고,
  없는 것을 지어내면 그 순간 mock 으로 되돌아간다.

미러 형식: 각 JSON 은 `{"_meta": {"uri": ..., "code": ...}, "_data": {...}}`.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REFERENCE = REPO / "tests" / "reference" / "redfish"

sys.path.insert(0, str(REPO / "redfish-gather" / "library"))

_stub_basic = types.ModuleType("ansible.module_utils.basic")
_stub_basic.AnsibleModule = object
_stub_module_utils = types.ModuleType("ansible.module_utils")
_stub_module_utils.basic = _stub_basic
_stub_ansible = types.ModuleType("ansible")
_stub_ansible.module_utils = _stub_module_utils
sys.modules.setdefault("ansible", _stub_ansible)
sys.modules.setdefault("ansible.module_utils", _stub_module_utils)
sys.modules.setdefault("ansible.module_utils.basic", _stub_basic)

import redfish_gather as rg  # noqa: E402


def _norm(uri: str) -> str:
    """URI → `_get(path)` 가 받는 형태로 정규화 (`/redfish/v1/` 접두사 제거)."""
    return rg._p(uri) if uri else ""


def load_mirror(host_dir: Path) -> dict:
    """한 호스트 디렉터리의 계정 관련 미러를 {정규화 path: (code, body)} 로 읽는다."""
    table = {}
    for f in sorted(host_dir.glob("redfish_v1*.json")):
        name = f.name.lower()
        # 계정 경로 + ServiceRoot + Manager 만 싣는다 (미러 전체는 수천 개다).
        if not (name == "redfish_v1.json"
                or "accountservice" in name
                or name.startswith("redfish_v1_managers")):
            continue
        if name.endswith("_keys.json"):     # 키 목록만 담은 보조 파일
            continue
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            continue
        meta, data = doc.get("_meta") or {}, doc.get("_data")
        uri, code = meta.get("uri"), meta.get("code")
        if not uri or not isinstance(data, dict):
            continue
        table[_norm(uri)] = (int(code or 200), data)
    return table


def make_get(table, missing=(404, {}, "HTTP 404: Not Found")):
    """`rg._get` 대체 — 미러에 없는 path 는 실제 BMC 처럼 404 로 돌려준다."""
    def _get(bmc_ip, path, username, password, timeout, verify_ssl):
        key = _norm(path) if path else ""
        if key in table:
            code, data = table[key]
            return code, data, (None if code == 200 else f"HTTP {code}")
        return missing
    return _get


def hosts(vendor: str):
    """해당 vendor 의 미러 호스트 디렉터리들 (AccountService 미러가 있는 것만)."""
    base = REFERENCE / vendor
    if not base.is_dir():
        return []
    out = []
    for d in sorted(base.iterdir()):
        if d.is_dir() and (d / "redfish_v1_accountservice.json").exists():
            out.append(d)
    return out
