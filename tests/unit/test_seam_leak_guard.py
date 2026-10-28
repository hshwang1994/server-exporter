"""tests/conftest.py 의 redfish_gather seam 누출 가드 자기 시험 (2026-10-27, 04-test-001).

별도 pytest 프로세스(pytester subprocess)에 가드를 conftest 로 복사하고, 합성 `redfish_gather` 모듈을 sys.modules 에
심은 뒤 한 모듈이 `_get_impl` 을 바꿔 놓고 되돌리지 않는 상황을 만든다. 기대: 그 모듈 경계에서 teardown 오류 1건으로
보고되고, 다음 모듈은 원본 함수를 다시 본다(가드가 되돌림). 같은 모듈 안의 패치와 모듈 끝에 되돌린 패치는 보고하지 않는다.
in-process 로 돌리면 바깥 세션의 sys.modules 를 오염시키므로 반드시 subprocess 다.
"""
from __future__ import annotations

import os
import site
import textwrap
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

REPO = Path(__file__).resolve().parents[2]
GUARD = (REPO / "tests" / "conftest.py").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _portable_child_env(monkeypatch):
    """하위 pytest 가 실행 환경과 무관하게 같은 조건으로 돈다 (2026-10-28, 독립 검증 CI G1).

    (1) pytester 는 하위 프로세스의 HOME 을 임시 폴더로 바꾼다. pytest 가 사용자 site(`pip install --user` — 이 저장소의 WSL 확인 환경)에만
        있으면 하위 프로세스가 pytest 를 못 찾아 가드와 무관하게 실패한다 → PYTHONUSERBASE 를 지금 값으로 고정한다(venv 는 사용자 site 가 꺼져 그대로).
    (2) pytester 는 하위 출력을 UTF-8 로 읽는다. Windows cp949 콘솔에서는 하위 pytest 가 가드 문구의 '—' 를 쓰지 못해 줄 전체를 escape 하고
        아래 한글 패턴이 맞지 않는다(수정 전 HEAD 도 같다) → 하위 출력 인코딩을 UTF-8 로 맞춘다. 단언은 바꾸지 않는다.
    """
    if site.ENABLE_USER_SITE and "PYTHONUSERBASE" not in os.environ:
        monkeypatch.setenv("PYTHONUSERBASE", site.getuserbase())
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")


def _assert_child_pytest_ran(result):
    """하위 pytest 가 실제로 시험을 돌렸는가 — 가져오기 실패를 가드 판정(오류 · 통과 수)으로 오인하지 않게 먼저 본다."""
    err = result.stderr.str()
    assert "No module named pytest" not in err and "No module named 'pytest'" not in err, err
    try:
        outcomes = result.parseoutcomes()
    except ValueError:            # 요약 줄이 없다 = 하위 pytest 가 시험 단계까지 가지 못했다
        outcomes = {}
    assert outcomes, (result.ret, result.stdout.str(), err)

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
    _assert_child_pytest_ran(result)
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
    _assert_child_pytest_ran(result)
    result.assert_outcomes(passed=2)
