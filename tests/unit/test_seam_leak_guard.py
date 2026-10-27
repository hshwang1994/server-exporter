"""tests/conftest.py 의 redfish_gather seam 누출 가드 자기 시험 (2026-10-27, 04-test-001).

별도 pytest 프로세스(pytester subprocess)에 가드를 conftest 로 복사하고, 합성 `redfish_gather` 모듈을 sys.modules 에
심은 뒤 한 모듈이 `_get_impl` 을 바꿔 놓고 되돌리지 않는 상황을 만든다. 기대: 그 모듈 경계에서 teardown 오류 1건으로
보고되고, 다음 모듈은 원본 함수를 다시 본다(가드가 되돌림). 같은 모듈 안의 패치와 모듈 끝에 되돌린 패치는 보고하지 않는다.
in-process 로 돌리면 바깥 세션의 sys.modules 를 오염시키므로 반드시 subprocess 다.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

pytest_plugins = ["pytester"]

REPO = Path(__file__).resolve().parents[2]
GUARD = (REPO / "tests" / "conftest.py").read_text(encoding="utf-8")

# 합성 redfish_gather — 함수를 모듈 네임스페이스 안에서 정의해 __module__ 이 'redfish_gather' 가 되게 한다.
INSTALL = textwrap.dedent('''
    import sys, types

    def install():
        m = types.ModuleType("redfish_gather")
        src = chr(10).join("def %s(*a): pass" % n for n in ("_get", "_get_impl", "_get_noauth", "_probe_realm_hint"))
        exec(src, m.__dict__)
        sys.modules["redfish_gather"] = m
        return m
''')


def _src(body: str) -> str:
    return INSTALL + textwrap.dedent(body)


def test_leak_across_module_boundary_is_reported_once_and_healed(pytester):
    pytester.makeconftest(GUARD)
    pytester.makepyfile(
        test_a_clean=_src('''
            def test_clean():
                install()
        '''),
        test_b_leak=_src('''
            def test_patch_inside_module_is_fine():
                sys.modules["redfish_gather"]._get_impl = lambda *a: (404, {}, "x")

            def test_leak_stays_until_module_end():
                fn = sys.modules["redfish_gather"]._get_impl
                assert fn.__name__ == "<lambda>"          # 같은 모듈 안에서는 가드가 개입하지 않는다
        '''),
        test_c_next=_src('''
            def test_next_module_sees_original():
                fn = sys.modules["redfish_gather"]._get_impl
                assert fn.__module__ == "redfish_gather" and fn.__name__ == "_get_impl"
        '''),
    )
    result = pytester.runpytest_subprocess("-q", "-p", "no:cacheprovider")
    result.assert_outcomes(passed=4, errors=1)
    result.stdout.fnmatch_lines(["*redfish_gather seam 누출*_get_impl*"])


def test_restored_patch_is_not_reported(pytester):
    pytester.makeconftest(GUARD)
    pytester.makepyfile(
        test_a_restores=_src('''
            import pytest

            @pytest.fixture(scope="module")
            def patched():
                m = install()
                orig = m._get
                m._get = lambda *a: (200, {}, None)
                yield
                m._get = orig

            def test_one(patched):
                assert sys.modules["redfish_gather"]._get.__name__ == "<lambda>"
        '''),
        test_b_next=_src('''
            def test_original_again():
                assert sys.modules["redfish_gather"]._get.__name__ == "_get"
        '''),
    )
    result = pytester.runpytest_subprocess("-q", "-p", "no:cacheprovider")
    result.assert_outcomes(passed=2)
