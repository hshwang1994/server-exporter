"""tests/ 공용 pytest 가드 — redfish_gather 전송 seam 누출 감시 (2026-10-27, 04-test-001).

같은 pytest 프로세스에서 한 테스트가 redfish_gather 의 전송 seam(_get / _get_impl / _get_noauth / _probe_realm_hint)을
바꿔 놓고 되돌리지 않으면 뒤 테스트 파일이 통째로 깨진다(2026-10-26 기준선: unit 19 · e2e 2 · regression 15 건이
replay_full_mirror.install_fakes 하나 때문). 모듈 경계마다 네 seam 이 redfish_gather 자신의 함수인지 확인하고,
아니면 그 테스트를 teardown 오류로 표면화한 뒤 원본으로 되돌려 연쇄 실패를 막는다.

- 모듈 안에서는 검사하지 않는다 — tests/unit/test_csus_fixture_replay.py 처럼 module scope fixture 가 rg._get 을
  바꿨다가 모듈 끝에 되돌리는 패턴이 있다. 모듈 경계에서는 그 복원이 끝나 있어야 한다.
- redfish_gather 를 여기서 import 하지 않는다(lazy: sys.modules 에 있을 때만 본다). sys.path 도 건드리지 않는다 —
  tests/integration/conftest.py 머리말의 conftest 충돌 사유.
"""
import sys

import pytest

_SEAMS = ("_get", "_get_impl", "_get_noauth", "_probe_realm_hint")
_ORIGINALS = {}


def _module():
    return sys.modules.get("redfish_gather")


def _is_own(mod, name):
    fn = getattr(mod, name, None)
    return getattr(fn, "__module__", None) == mod.__name__ and getattr(fn, "__name__", None) == name


@pytest.hookimpl(trylast=True)
def pytest_runtest_teardown(item, nextitem):
    mod = _module()
    if mod is None:
        return
    if nextitem is not None and getattr(nextitem, "module", None) is getattr(item, "module", None):
        return                                   # 같은 모듈 안 — module scope 패치는 허용
    leaked = [n for n in _SEAMS if not _is_own(mod, n)]
    if not leaked:
        for n in _SEAMS:
            _ORIGINALS.setdefault(n, getattr(mod, n))
        return
    detail = {n: f"{getattr(getattr(mod, n), '__module__', '?')}.{getattr(getattr(mod, n), '__qualname__', '?')}" for n in leaked}
    for n in leaked:
        if n in _ORIGINALS:
            setattr(mod, n, _ORIGINALS[n])        # 뒤 모듈을 지키기 위해 되돌린다 — 보고는 아래에서
    pytest.fail(f"redfish_gather seam 누출: {detail} — 이 모듈의 테스트/fixture 가 seam 을 되돌리지 않았다 "
                f"(emulator_harness.run_gather 또는 replay_full_mirror.installed_fakes 처럼 finally 로 복원할 것)",
                pytrace=False)
