"""Windows 비종료 조회 오류 · DIMM 불완전 총량 (2026-10-10 C8).

종전 결함(검수 재현 — 실제 PowerShell 본문 + 가짜 cmdlet):
  - network: 공용 조회(routes · adapters · DNS)는 비종료 오류를 잡지만 별도의 `Get-NetAdapter -Physical` 은 빠져, 공급자 오류와 정상 행이
    함께 와도 failed_parts · errors 가 비었다.
  - memory: `Win32_PhysicalMemory` 를 SilentlyContinue 로 읽어 공급자 오류를 감추고, DIMM 일부(32768 MB)를 설치 총량으로 확정했다(OS 가시량 65536 MB).
수정 후 기대:
  - network: 행은 그대로 두고 adapters 구성요소 실패 → network 부분 오류 1건(섹션 성공 유지).
  - memory: 받은 슬롯 · 그룹은 두고 설치량을 확정하지 않는다 — total_mb = OS 가시량(total_basis os_visible), installed_mb null,
    summary.grand_total_gb null(그룹 집계와 OS 가시량을 섞지 않는다), 경고 1건(cause=read_failed). 슬롯이 아예 없으면 종전 fallback.
크기 차이만으로 실패를 만들지 않는다 — 공급자 오류가 근거다. 정상 빈 목록 · ObjectNotFound · 전체 성공은 종전과 같다.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
pytest.importorskip("jinja2")

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "unit"))
sys.path.insert(0, str(REPO / "filter_plugins"))

import test_windows_call_consolidation_powershell as PS  # noqa: E402
from errors_normalizer import normalize_errors  # noqa: E402
from identity_normalizer import dmi_sentinel_null, normalize_mac, normalize_uuid, normalize_wwn  # noqa: E402
from linux_raw_harness import ansible_env, render_tree  # noqa: E402
from test_windows_call_consolidation_render import new_text, run_chain  # noqa: E402

needs_powershell = pytest.mark.skipif(PS.POWERSHELL is None, reason="powershell.exe 가 필요하다(Windows 호스트)")


def _final(frag):
    """fragment → 공통 merge_fragment → build_sections → build_status → build_errors (실제 YAML 식)."""
    env = ansible_env()
    env.filters.update({"normalize_mac": normalize_mac, "normalize_uuid": normalize_uuid, "normalize_wwn": normalize_wwn,
                        "dmi_sentinel_null": dmi_sentinel_null,
                        "normalize_errors": normalize_errors, "union": lambda a, b: list(dict.fromkeys(list(a) + list(b)))})
    ctx = {"_all_sec_supported": [], "_all_sec_collected": [], "_all_sec_failed": [], "_all_sec_unsupported": [], "_all_errors": [], **frag}
    for name in ("merge_fragment", "build_sections", "build_status", "build_errors"):
        for task in yaml.safe_load((REPO / "common" / "tasks" / "normalize" / f"{name}.yml").read_text(encoding="utf-8")):
            if "ansible.builtin.set_fact" in task:
                ctx.update({k: render_tree(env, v, ctx) for k, v in task["ansible.builtin.set_fact"].items()})
    return ctx


# ── network: Get-NetAdapter -Physical ────────────────────────────────────────────────────────────────────────

@needs_powershell
def test_physical_adapter_provider_error_is_recorded_and_rows_are_kept():
    base, _ = run_chain(new_text("network"), {}, PS.PsShell("network", copy.deepcopy(PS.NET_TEAM)))
    fixture = copy.deepcopy(PS.NET_TEAM)
    fixture["soft_fail"] = {"Get-NetAdapter -Physical": "physical adapter provider failed (fixture)"}
    frag, ctx = run_chain(new_text("network"), {}, PS.PsShell("network", fixture))
    assert len(frag["_data_fragment"]["network"]["adapters"]) == len(base["_data_fragment"]["network"]["adapters"]) > 0
    assert ctx["_w_net_parts_failed"] == ["adapters"]
    assert frag["_sections_collected_fragment"] == ["network"]
    errs = frag["_errors_fragment"]
    assert len(errs) == 1 and errs[0]["section"] == "network" and "parts=adapters" in errs[0]["detail"]
    assert "physical adapter provider failed" in errs[0]["detail"]
    final = _final(frag)
    assert final["_norm_sections"]["network"] == "success" and final["_out_status"] == "success"
    assert [e["section"] for e in final["_norm_errors"]] == ["network"]


@needs_powershell
def test_physical_adapter_object_not_found_is_not_a_failure():
    fixture = copy.deepcopy(PS.NET_TEAM)
    shell = PS.PsShell("network", fixture)
    shell.prelude += r'''
function Get-NetAdapter {
[CmdletBinding()] param([Parameter(Position=0)][string[]]$Name, [uint32[]]$InterfaceIndex, [switch]$Physical, [switch]$IncludeHidden)
$r = @(@($script:__fx.adapters) | Where-Object { $IncludeHidden -or -not $_.Hidden })
if ($Physical) { $r = @($r | Where-Object { $_.ConnectorPresent }); Write-Error -Message 'no hidden adapter (fixture)' -Category ObjectNotFound }
$r
}
'''
    frag, ctx = run_chain(new_text("network"), {}, shell)
    assert ctx["_w_net_parts_failed"] == [] and frag["_errors_fragment"] == []


# ── memory: Win32_PhysicalMemory ─────────────────────────────────────────────────────────────────────────────

FACTS = {"ansible_memtotal_mb": 65536, "ansible_memfree_mb": 1000}


def _partial_shell():
    fixture = copy.deepcopy(PS.MEM_NORMAL)
    fixture["cim"]["Win32_PhysicalMemory"] = fixture["cim"]["Win32_PhysicalMemory"][:1]
    shell = PS.PsShell("memory", fixture)
    shell.prelude += r'''
function Get-CimInstance {
[CmdletBinding()] param([Parameter(Position=0)][string]$ClassName, [string]$Namespace, [string]$Filter)
Write-Error -Message 'partial DIMM provider failure (fixture)' -Category InvalidOperation
$script:__fx.cim.$ClassName
}
'''
    return shell


@needs_powershell
def test_full_dimm_read_is_unchanged():
    frag, _ = run_chain(new_text("memory"), dict(FACTS), PS.PsShell("memory", copy.deepcopy(PS.MEM_NORMAL)))
    mem = frag["_data_fragment"]["memory"]
    slots = [s for s in PS.MEM_NORMAL["cim"]["Win32_PhysicalMemory"]]
    assert len(mem["slots"]) == len(slots)
    assert mem["total_basis"] == "physical_installed" and mem["installed_mb"] == mem["total_mb"]
    assert mem["summary"]["grand_total_gb"] == sum(g["group_total_gb"] for g in mem["summary"]["groups"])
    assert frag["_errors_fragment"] == []


@needs_powershell
def test_partial_dimm_rows_with_provider_error_keep_slots_but_not_the_partial_total():
    frag, ctx = run_chain(new_text("memory"), dict(FACTS), _partial_shell())
    mem = frag["_data_fragment"]["memory"]
    assert ctx["_w_mem_read_failed"] is True
    assert len(mem["slots"]) == 1, "받은 DIMM 행은 보존한다"
    assert mem["total_mb"] == 65536 and mem["total_basis"] == "os_visible" and mem["installed_mb"] is None
    assert len(mem["summary"]["groups"]) == 1 and mem["summary"]["grand_total_gb"] is None, "일부 슬롯 합을 전체 합계로 쓰지 않는다"
    errs = frag["_errors_fragment"]
    assert len(errs) == 1 and errs[0]["section"] == "memory"
    assert "cause=read_failed" in errs[0]["detail"] and "slots=1" in errs[0]["detail"]
    assert "partial DIMM provider failure" in errs[0]["detail"]
    assert frag["_sections_collected_fragment"] == ["memory"], "값을 확정하지 못했다는 경고일 뿐 섹션 실패가 아니다"
    final = _final(frag)
    assert final["_norm_sections"]["memory"] == "success" and [e["section"] for e in final["_norm_errors"]] == ["memory"]


@needs_powershell
def test_full_dimm_read_failure_keeps_the_existing_fallback():
    frag, _ = run_chain(new_text("memory"), dict(FACTS), PS.PsShell("memory", copy.deepcopy(PS.MEM_FAIL)))
    mem = frag["_data_fragment"]["memory"]
    assert mem["slots"] == [], "빈 행을 만들지 않는다"
    assert mem["total_mb"] == 65536 and mem["total_basis"] == "os_visible" and mem["installed_mb"] is None
    assert mem["summary"]["grand_total_gb"] == 64, "슬롯이 없을 때의 종전 fallback(가시량 기준)"
    errs = frag["_errors_fragment"]
    assert len(errs) == 1 and "cause=read_failed" in errs[0]["detail"] and "slots=0" in errs[0]["detail"]


@needs_powershell
def test_no_modules_reported_without_error_is_still_no_output():
    fixture = copy.deepcopy(PS.MEM_NORMAL)
    fixture["cim"]["Win32_PhysicalMemory"] = []
    frag, _ = run_chain(new_text("memory"), dict(FACTS), PS.PsShell("memory", fixture))
    errs = frag["_errors_fragment"]
    assert len(errs) == 1 and "cause=no_output" in errs[0]["detail"], "오류 없이 0개면 종전 분류 그대로"
