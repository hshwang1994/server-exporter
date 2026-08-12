"""3채널 rescue diagnosis 템플릿을 **실제 Ansible 템플릿 엔진**으로 렌더한다 (2026-08-12 신설).

왜 별도 테스트인가
------------------
다른 계약 테스트(`test_failure_reason_contract` 계열)는 순수 jinja2 `NativeEnvironment` +
`_ChainableUndefined` 로 렌더한다. 그 환경은 없는 키에 속성 접근을 하면 조용히 Undefined 를
돌려주므로 `x.details is mapping` 이 False 로 평가돼 **그냥 지나간다**.

그런데 운영 ansible-core(2.19+ / 실환경 2.20.3)는 다르다. dict 에 없는 키를 속성 접근한
결과(Marker)를 테스트나 필터에 넘기는 순간 `AnsibleUndefinedVariable` 로 **죽는다**.
즉 이 계열의 파손은 순수 jinja2 테스트가 전부 통과해도 운영에서만 터진다.

실제로 2026-08-12 적대적 검수에서 esxi rescue 의
`((_diagnosis | default({}, true)).details) is mapping` 이 `_diagnosis` 미정의 /
`{}` / `details` 키 부재 세 경우 모두 운영 엔진에서 죽는 것이 확인됐다. 그러면 rescue 블록이
중단되어 `build_failed_output` 이 실행되지 않고, 그 호스트는 실패 원인을 잃은 채
`OUTPUT_BUILD_FAILED` fallback envelope 만 받는다 — 이번 작업 목적과 정반대 결과다.

환경 제약
---------
이 저장소의 개발 환경(Windows)에는 `ansible-playbook` 바이너리가 없고, ansible-core 파이썬
패키지는 있으나 POSIX 전용 모듈(fcntl 등)에 의존해 그냥은 import 되지 않는다. 그래서 그
모듈들을 최소 shim 으로 채운 뒤 Templar 만 끌어온다. shim 이 실패하면 테스트를 skip 한다
(운영 Agent 는 Linux 라 그대로 import 된다).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]


_SHIMS = (
    ("fcntl", {"fcntl": lambda *a, **k: 0, "flock": lambda *a, **k: None,
               "ioctl": lambda *a, **k: 0, "lockf": lambda *a, **k: None,
               "LOCK_EX": 2, "LOCK_SH": 1, "LOCK_UN": 8, "LOCK_NB": 4,
               "F_GETFL": 3, "F_SETFL": 4, "F_GETFD": 1, "F_SETFD": 2}),
    # tty 는 Windows 에도 있지만 `from termios import *` 라 termios 먼저 채워야 한다.
    ("termios", {"TCSANOW": 0, "TCSADRAIN": 1, "TCSAFLUSH": 2,
                 "IFLAG": 0, "OFLAG": 1, "CFLAG": 2, "LFLAG": 3,
                 "ISPEED": 4, "OSPEED": 5, "CC": 6,
                 "ECHO": 8, "ICANON": 2, "ISIG": 1, "IEXTEN": 32768,
                 "IXON": 1024, "ICRNL": 256, "INLCR": 64, "IGNCR": 128,
                 "OPOST": 1, "CSIZE": 48, "PARENB": 256, "CS8": 48,
                 "VMIN": 6, "VTIME": 5,
                 "tcgetattr": lambda *a: [0, 0, 0, 0, 0, 0, [0] * 32],
                 "tcsetattr": lambda *a: None, "error": OSError}),
    ("grp", {"getgrall": lambda: [], "getgrgid": lambda _g: None,
             "getgrnam": lambda _n: None, "struct_group": tuple}),
    ("pwd", {"getpwuid": lambda _u: None, "getpwnam": lambda _n: None,
             "getpwall": lambda: [], "struct_passwd": tuple}),
    ("resource", {"getrlimit": lambda *a: (1024, 1024), "setrlimit": lambda *a: None,
                  "RLIMIT_NOFILE": 7, "RLIM_INFINITY": -1}),
)


def _install_posix_shims() -> None:
    """Windows 에 없는 POSIX 전용 의존을 최소 대역으로 채운다 (운영 Agent 는 Linux).

    채우는 것은 **템플릿 엔진을 import 하기 위한 껍데기**뿐이다. 템플릿 평가 자체는
    실제 ansible-core 코드가 수행하므로, Marker / 데이터 태깅 같은 2.19+ 동작이 그대로 재현된다.
    """
    for name, attrs in _SHIMS:
        if name in sys.modules:
            continue
        try:
            __import__(name)
        except ImportError:
            mod = types.ModuleType(name)
            for key, value in attrs.items():
                setattr(mod, key, value)
            sys.modules[name] = mod

    # ansible.utils.multiprocessing 이 import 시점에 'fork' 컨텍스트를 요구한다 (POSIX 전용).
    import multiprocessing

    if not getattr(multiprocessing, "_se_fork_shimmed", False):
        original = multiprocessing.get_context

        def _get_context(method=None):
            try:
                return original(method)
            except ValueError:
                return original("spawn")

        multiprocessing.get_context = _get_context
        multiprocessing._se_fork_shimmed = True

    # ansible.utils.display 는 import 시점에 libc 를 열어 wcwidth 를 바인딩한다 (POSIX 전용).
    # Windows 에는 대응 심볼이 없어 import 자체가 실패하므로, 템플릿 평가에 관여하지 않는
    # 이 모듈만 통째로 무해한 대역으로 세운다. **템플릿 엔진 코드는 대역이 아니라 실물이다.**
    if "ansible.utils.display" not in sys.modules:
        try:
            import ansible.utils.display  # noqa: F401,PLC0415
        except Exception:                 # noqa: BLE001 - 플랫폼 의존 import 실패만 대역 처리
            stub = types.ModuleType("ansible.utils.display")

            class _Display:                                    # noqa: D401 - Display 대역
                verbosity = 0
                columns = 79

                def __init__(self, *a, **k):
                    pass

                def __getattr__(self, _name):
                    return lambda *a, **k: None

            stub.Display = _Display
            stub.initialize_locale = lambda *a, **k: None
            stub.get_text_width = lambda text: len(text)
            sys.modules["ansible.utils.display"] = stub


def _import_templar():
    """ansible-core 의 Templar 를 끌어온다. 실패하면 None.

    ansible-core 의 일부 모듈이 import 시점에 `os.path.sep` 를 정규식에 그대로 넣는다
    (`'(?:^|%s)+tasks%s?$' % (os.path.sep, ...)`). Windows 의 `\\` 는 정규식 이스케이프라
    컴파일이 깨진다. import 하는 동안만 POSIX 구분자로 바꿔 준다 — 템플릿 평가에는 관여하지 않는다.
    """
    _install_posix_shims()
    import ntpath
    import os
    import posixpath

    saved = (os.sep, os.path.sep, ntpath.sep)
    try:
        os.sep = os.path.sep = ntpath.sep = posixpath.sep
        from ansible.template import Templar
        return Templar
    except Exception:  # noqa: BLE001 - 플랫폼 의존. 못 쓰면 skip 한다.
        return None
    finally:
        os.sep, os.path.sep, ntpath.sep = saved


_TEMPLAR_CLS = _import_templar()


def _templar():
    if _TEMPLAR_CLS is None:  # pragma: no cover - 이 개발 환경에서만 발생
        pytest.skip("이 플랫폼에서 ansible-core 템플릿 엔진을 import 할 수 없다 "
                    "(운영 Agent 는 Linux 라 정상 동작한다)")
    return _TEMPLAR_CLS(loader=None)


def _trusted_as_template():
    """ansible-core 2.19+ 의 신뢰 태그. 버전별로 경로가 달라 후보를 순서대로 시도한다."""
    for module_path in ("ansible._internal._datatag._tags",
                        "ansible._internal._templating._transform",
                        "ansible.template"):
        try:
            module = __import__(module_path, fromlist=["TrustedAsTemplate"])
            return module.TrustedAsTemplate
        except Exception:  # noqa: BLE001
            continue
    return None


_TRUSTED = _trusted_as_template()


def _trust(text: str):
    """ansible-core 2.19+ 는 **신뢰 표시가 없는 문자열을 템플릿으로 보지 않는다.**

    태그를 못 붙이면 `templar.template()` 이 원문 문자열을 그대로 돌려주므로,
    테스트가 '통과한 것처럼' 보이면서 실제로는 아무것도 검증하지 않게 된다.
    그래서 태그 확보 실패는 조용히 넘기지 않고 skip 으로 드러낸다.
    """
    if _TRUSTED is None:  # pragma: no cover
        pytest.skip("ansible-core 의 TrustedAsTemplate 을 찾지 못해 템플릿 평가를 신뢰할 수 없다")
    return _TRUSTED().tag(text)


def _plays(site: str) -> list[dict[str, Any]]:
    return list(yaml.safe_load_all((REPO / site).read_text(encoding="utf-8")))[0]


def _iter_tasks(node: Any):
    if isinstance(node, list):
        for item in node:
            yield from _iter_tasks(item)
    elif isinstance(node, dict):
        yield node
        for key in ("block", "rescue", "always", "tasks"):
            if key in node:
                yield from _iter_tasks(node[key])


def _task_template(site: str, needle: str, key: str) -> str:
    for play in _plays(site):
        for task in _iter_tasks(play.get("tasks", [])):
            if needle in (task.get("name") or ""):
                tpl = task["ansible.builtin.set_fact"][key]
                assert isinstance(tpl, str), f"{site}:{needle}:{key} 가 문자열 템플릿이 아니다"
                return tpl
    raise AssertionError(f"{site} 에서 태스크를 찾지 못함: {needle!r}")


FAILURE_REASONS: dict[str, Any] = yaml.safe_load(
    (REPO / "common/vars/failure_reasons.yml").read_text(encoding="utf-8"))

# rescue diagnosis 를 만드는 3채널 4개 태스크 (여기가 실패하면 envelope 이 통째로 fallback 된다)
_DIAG_TASKS = [
    ("redfish-gather/site.yml", "redfish | rescue | Portal 표시용 failure_reason 보장"),
    ("esxi-gather/site.yml", "esxi | rescue | Portal 표시용 failure_reason 보장"),
    ("os-gather/site.yml", "linux | rescue | Portal 표시용 diagnosis 보장"),
    ("os-gather/site.yml", "windows | rescue | Portal 표시용 diagnosis 보장"),
]

# `_diagnosis` 가 이런 모양으로 도착할 수 있다 — precheck 가 돌기 전에 rescue 로 들어오면
# 미정의이고, 필터가 방어하면 `{}` 이며, 앞 단계만 채워지면 `details` 키가 없다.
_DIAGNOSIS_SHAPES = [
    ("undefined", None),
    ("empty-dict", {}),
    ("no-details", {"reachable": True, "port_open": True, "protocol_supported": True,
                    "auth_success": None, "failure_stage": None, "failure_code": None,
                    "failure_reason": None}),
    ("details-empty", {"reachable": True, "port_open": True, "protocol_supported": True,
                       "auth_success": None, "failure_stage": None, "failure_code": None,
                       "failure_reason": None, "details": {}}),
    ("non-mapping", "not-a-dict"),
]

_DIAGNOSIS_KEYS = {"reachable", "port_open", "protocol_supported", "auth_success",
                   "failure_stage", "failure_code", "failure_reason", "details"}


@pytest.mark.parametrize("site,task", _DIAG_TASKS, ids=[f"{s}:{t[:20]}" for s, t in _DIAG_TASKS])
@pytest.mark.parametrize("shape,value", _DIAGNOSIS_SHAPES, ids=[s for s, _ in _DIAGNOSIS_SHAPES])
def test_rescue_diagnosis_renders_on_real_ansible_engine(site, task, shape, value):
    """`_diagnosis` 가 어떤 모양으로 와도 rescue 가 죽지 않는다.

    죽으면 rescue 블록이 중단되어 build_failed_output 이 실행되지 않고, 그 호스트는
    실패 원인을 잃은 채 always 블록의 OUTPUT_BUILD_FAILED fallback 만 받는다.
    """
    templar = _templar()
    variables = dict(FAILURE_REASONS)
    variables.update({
        "_rf_auth_outcome": "unknown",
        "_rf_collect_ok": False,
        "_rf_auth_rejected": False,
        "_rf_auth_observations": [],
        "_rf_raw_collect": {},
        "_e_auth_ok": False,
        "_e_facts_ok": False,
        "_e_attempts_meta": {},
        "_os_auth_ok": False,
        "_all_sec_collected": [],
        "_os_attempts_meta": {},
        "_precheck_raw": {},
        "ansible_port": "5986",
    })
    if value is not None:
        variables["_diagnosis"] = value

    templar.available_variables = variables
    rendered = templar.template(_trust(_task_template(site, task, "_diagnosis")))

    assert isinstance(rendered, dict), f"[{site}/{shape}] diagnosis 가 dict 가 아니다: {rendered!r}"
    assert set(rendered) == _DIAGNOSIS_KEYS, f"[{site}/{shape}] 8키 shape 위반: {sorted(rendered)}"
    assert isinstance(rendered["details"], dict), f"[{site}/{shape}] details 가 dict 가 아니다"
    # status=failed 결과이므로 세 값이 모두 채워져야 한다 (CLAUDE.md §9)
    for key in ("failure_stage", "failure_code", "failure_reason"):
        assert rendered[key], f"[{site}/{shape}] {key} 가 비었다 — 실패인데 사유 없는 Result"
    assert rendered["failure_reason"] in set(FAILURE_REASONS.values()), (
        f"[{site}/{shape}] 표준 문장 밖: {rendered['failure_reason']!r}")


def test_errors_normalizer_filter_loads_and_works_in_ansible():
    """`normalize_errors` 가 실제 Ansible 필터 로더로 잡히고 list 를 보존하는지."""
    templar = _templar()
    try:
        from ansible.plugins.loader import filter_loader
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"filter_loader 사용 불가: {exc}")
    filter_loader.add_directory(str(REPO / "filter_plugins"))

    templar.available_variables = {
        "_errors_fragment": ["boom", {"section": "cpu"}, 42, None,
                             {"message": "m", "detail": {"a": 1}}],
    }
    out = templar.template(_trust("{{ _errors_fragment | normalize_errors }}"))
    assert isinstance(out, list), f"필터 반환이 list 가 아니다 (jinja2_native 문제): {type(out)}"
    assert len(out) == 4, out
    for entry in out:
        assert isinstance(entry["message"], str) and entry["message"].strip()
        assert entry["detail"] is None or isinstance(entry["detail"], str)
    # 멱등 — merge 단계와 build_errors 단계에서 두 번 통과한다
    templar.available_variables = {"_errors_fragment": out}
    assert templar.template(_trust("{{ _errors_fragment | normalize_errors }}")) == out


def test_build_output_failed_guard_renders_on_real_engine():
    """정상 경로에서 status=failed 가 됐을 때 채우는 guard 도 같은 검사를 받는다."""
    templar = _templar()
    tasks = list(yaml.safe_load_all(
        (REPO / "common/tasks/normalize/build_output.yml").read_text(encoding="utf-8")))[0]
    tpl = None
    for task in _iter_tasks(tasks):
        if "ensure failed diagnosis" in (task.get("name") or ""):
            tpl = task["ansible.builtin.set_fact"]["_diagnosis"]
    assert tpl, "build_output.yml 에서 ensure failed diagnosis 를 찾지 못함"

    for shape, value in _DIAGNOSIS_SHAPES:
        variables = dict(FAILURE_REASONS)
        variables["_out_status"] = "failed"
        if value is not None:
            variables["_diagnosis"] = value
        templar.available_variables = variables
        rendered = templar.template(_trust(tpl))
        assert set(rendered) == _DIAGNOSIS_KEYS, f"[{shape}] 8키 shape 위반"
        assert rendered["failure_reason"] == FAILURE_REASONS["_fr_gather_failed"], shape
