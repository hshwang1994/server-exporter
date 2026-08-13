"""M-C3 회귀 — vault 자동 반영 메커니즘 (M-C2 시나리오 5건 mock 검증).

cycle 2026-05-06 M-C1/M-C2 사용자 답변: vault 변경은 다음 ansible-playbook run 부터 자동 반영.

검증 항목 (M-C2 5 시나리오):
1. include_vars 가 cacheable 미사용 — load_vault.yml 정합 (코드 grep)
2. fact_caching 이 프로젝트 ansible.cfg 에 0 건 — Agent 공통 설정에서만 관리
3. redfish-gather/site.yml 에 gather_facts: no 명시
4. accounts list 정규화 로직: list[0] = primary, list[1+] = recovery
5. legacy ansible_user/password fallback (accounts 키 부재 시 backward-compat)
6. (시나리오 5) single run 중간 vault 변경 → 현 run 영향 없음 (task scope 캐시)

→ vault 변경은 다음 run 자동 반영 (YES). single run 중 변경은 NO.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
LOAD_VAULT = REPO / "redfish-gather" / "tasks" / "load_vault.yml"
ANSIBLE_CFG = REPO / "ansible.cfg"
SITE_YML = REPO / "redfish-gather" / "site.yml"

# 2026-08-12: vault 로딩 자체가 3채널 공통 task 로 옮겨졌다 (Location 축 도입).
#   load_vault.yml 은 그 결과를 Redfish 변수 이름으로 옮기는 얇은 어댑터가 됐다.
#   따라서 "자동 반영" 계약을 검증할 대상은 아래 공통 task 다.
#   이 파일의 목적(vault 변경이 다음 run 에 자동 반영되는가)은 그대로다.
CRED_DIR = REPO / "common" / "tasks" / "credential"
RESOLVE_AND_LOAD = CRED_DIR / "resolve_and_load.yml"


# ── (1) include_vars 가 cacheable 미사용 ─────────────────────────────────────


def test_m_c3_load_vault_no_cacheable() -> None:
    """vault 로딩 경로가 cacheable 미사용 (M-C2 (1)).

    `cacheable: yes` 면 fact_cache(Redis)에 남아 vault 를 고쳐도 다음 run 이
    옛 값을 쓴다 (rule 27 R6).
    """
    for path in (RESOLVE_AND_LOAD, LOAD_VAULT):
        content = path.read_text(encoding="utf-8").lower()
        assert "cacheable: yes" not in content, (
            f"{path.name}: cacheable: yes 사용됨. fact_cache 진입 → 자동 반영 깨짐"
        )
        assert "cacheable: true" not in content, (
            f"{path.name}: cacheable: True 사용됨. fact_cache 진입"
        )


def test_m_c3_load_vault_uses_include_vars() -> None:
    """공통 credential task 가 include_vars 사용 (매 task disk read — 캐시 없음).

    2026-08-12: 실제 파일 열기는 load_one.yml 로 빠졌다 (Redfish 2-scope 로딩과 공유).
    계약은 "credential 로딩 경로 전체" 에 걸리므로 디렉터리를 통째로 본다.
    """
    content = "\n".join(
        f.read_text(encoding="utf-8") for f in sorted(CRED_DIR.glob("*.yml"))
    )
    assert "include_vars" in content, (
        "resolve_and_load.yml: include_vars 미사용 — vault 동적 로딩 path 부재"
    )
    assert "vars_files" not in content, (
        "resolve_and_load.yml: vars_files 사용 — play 파싱 시점 로딩은 동적 반영이 아니다"
    )


# ── (2) 프로젝트 ansible.cfg 에 fact_caching 설정 0 건 ──────────────────────


def test_m_c3_ansible_cfg_no_fact_caching() -> None:
    """ansible.cfg 에 활성 fact_caching 설정 부재 (M-C2 (1) 보강).

    Agent 공통 설정 (/etc/ansible/ansible.cfg) 에 있으나 프로젝트 설정에는 없음.
    프로젝트 cfg 에서 활성 fact_caching = redis 같은 라인 부재 검증.
    """
    content = ANSIBLE_CFG.read_text(encoding="utf-8")
    # 주석 line 제외 (# 으로 시작) — 활성 라인만 검사
    active_lines = [
        line.strip() for line in content.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    fact_caching_active = [
        line for line in active_lines
        if line.startswith("fact_caching") and "=" in line
    ]
    assert len(fact_caching_active) == 0, (
        f"ansible.cfg: 활성 fact_caching 설정 발견 — vault 자동 반영에 영향. "
        f"라인: {fact_caching_active}"
    )


# ── (3) redfish-gather/site.yml gather_facts: no ─────────────────────────────


def test_m_c3_site_yml_gather_facts_no() -> None:
    """redfish-gather/site.yml 에 gather_facts: no 명시 (M-C2 (1) 결론)."""
    content = SITE_YML.read_text(encoding="utf-8")
    # YAML 파싱하여 plays list 의 첫 play 확인
    plays = yaml.safe_load(content)
    assert isinstance(plays, list) and len(plays) > 0, "site.yml 가 plays list 형식 아님"
    first_play = plays[0]
    gather_facts = first_play.get("gather_facts")
    # YAML 의 'no' / False 모두 허용
    assert gather_facts in (False, "no", "No", "false", "False"), (
        f"site.yml: gather_facts 가 false/no 가 아님. 실제: {gather_facts}"
    )


# ── (4) accounts list 정규화 로직 ────────────────────────────────────────────


def test_m_c3_load_vault_normalizes_accounts_list() -> None:
    """accounts list 가 _rf_accounts 로 이어지고 순서가 보존된다 (list[0] = primary 관례)."""
    content = LOAD_VAULT.read_text(encoding="utf-8")
    assert "_rf_accounts" in content, "load_vault.yml: _rf_accounts 변수 부재"
    assert "_cred_accounts" in content, (
        "load_vault.yml: 공통 resolver 결과(_cred_accounts) 를 받지 않는다"
    )
    # 순서 계약이 주석으로 남아 있어야 한다 (재정렬 재도입 방어)
    assert "primary" in content.lower(), (
        "load_vault.yml: primary/recovery role 정의 주석 부재"
    )


def test_m_c3_load_vault_legacy_fallback() -> None:
    """legacy ansible_user/password fallback (backward-compat) 이 유지되는가.

    2026-08-12: Jinja 인라인에서 module_utils/credential_common.normalize_accounts
    로 옮겼다 (3채널 공통 구현 1개). 위치만 바뀌고 동작은 같다.
    """
    content = (REPO / "module_utils" / "credential_common.py").read_text(encoding="utf-8")
    assert "ansible_user" in content, (
        "credential_common.py: legacy ansible_user fallback 미지원 — backward-compat 깨짐"
    )
    assert "ansible_password" in content, (
        "credential_common.py: legacy ansible_password fallback 부재"
    )


# ── (5) M-C2 시나리오 5: single run 중 vault 변경 영향 없음 (task scope 캐시) ─


def test_m_c3_scenario_5_single_run_no_midway_invalidation() -> None:
    """include_vars 의 name 파라미터로 task scope 변수 (run 중 변경 영향 없음).

    M-C2 시나리오 5: load_vault.yml 가 이미 실행된 후 vault file 수정 시
    현 run 의 _rf_vault_data 는 task scope 캐시 사용 → 다음 run N+1 부터 반영.

    검증: include_vars 가 name= 으로 변수 저장
    (host_vars 가 아닌 task 변수 — single-run 중간 invalidation 없음 — 의도된 동작).
    """
    content = "\n".join(
        f.read_text(encoding="utf-8") for f in sorted(CRED_DIR.glob("*.yml"))
    )
    assert "name: _cl_included" in content, (
        "load_one.yml: include_vars 가 name=_cl_included 로 저장 안 함 "
        "— task scope 분리 깨짐 (vault top-level 키가 host var 로 샌다)"
    )


# ── (6) vault 선택은 adapter 가 아니라 (location, vendor) 에서 나온다 ────────


def test_m_c3_vault_scope_not_from_adapter() -> None:
    """2026-08-12: vault 선택이 adapter 와 분리됐는지.

    종전에는 `_selected_adapter.credentials.profile` 이 vault 파일을 골랐다 —
    Adapter(어떻게 수집하는가)가 Credential(누구로 인증하는가)까지 정하는 결합이었다.
    이제는 (se_location, canonical vendor) 만으로 정한다.
    """
    content = LOAD_VAULT.read_text(encoding="utf-8")
    code = "\n".join(
        line for line in content.splitlines() if not line.lstrip().startswith("#")
    )
    assert "_selected_adapter" not in code, (
        "load_vault.yml 이 여전히 adapter 를 참조한다 — Credential/Adapter 결합 잔존"
    )
    assert "credentials.profile" not in code, (
        "load_vault.yml 이 여전히 adapter.credentials.profile 로 vault 를 고른다"
    )
    assert "fallback_profiles" not in code, (
        "fallback_profiles 루프 부활 — 다른 vendor vault 로 넘어가는 경로는 금지"
    )

    resolver = RESOLVE_AND_LOAD.read_text(encoding="utf-8")
    assert "credential_resolver" in resolver, (
        "resolve_and_load.yml 이 credential_resolver lookup 을 쓰지 않는다"
    )


# ── (7) F50 phase 4 분리 — BMC 권한 cache 와 vault 자동 반영 분리 ───────────


def test_m_c3_f50_phase4_bmc_cache_independent() -> None:
    """F50 phase 4 verify-fallback (commit 3fa39dec) 가 vault 자동 반영과 별 layer.

    M-C2 (D): BMC 권한 cache (BMC 펌웨어) ≠ vault 자동 반영 (Ansible run).
    검증: load_vault.yml 안에 BMC verify / DELETE+POST fallback 코드 부재
    (account_service.yml 또는 redfish_gather.py:account_service_provision 에 분리).
    """
    content = LOAD_VAULT.read_text(encoding="utf-8")
    # load_vault.yml 은 vault load 만 — verify-fallback / account_service 코드 미포함
    assert "verify-fallback" not in content.lower(), (
        "load_vault.yml: verify-fallback 코드 혼재 — F50 phase 4 영역 분리 깨짐"
    )
    assert "account_service_provision" not in content, (
        "load_vault.yml: account_service_provision 호출 — vault load 책임 분리 깨짐"
    )
