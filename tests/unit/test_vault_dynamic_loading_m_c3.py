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


# ── (1) include_vars 가 cacheable 미사용 ─────────────────────────────────────


def test_m_c3_load_vault_no_cacheable() -> None:
    """load_vault.yml 의 include_vars / set_fact 가 cacheable: yes 미사용 (M-C2 (1))."""
    content = LOAD_VAULT.read_text(encoding="utf-8")
    # cacheable: yes 또는 cacheable: True 패턴 검색
    assert "cacheable: yes" not in content.lower(), (
        "load_vault.yml: cacheable: yes 사용됨. fact_cache 진입 → 자동 반영 깨짐"
    )
    assert "cacheable: true" not in content.lower(), (
        "load_vault.yml: cacheable: True 사용됨. fact_cache 진입"
    )


def test_m_c3_load_vault_uses_include_vars() -> None:
    """load_vault.yml 가 include_vars 사용 (매 task disk read — 캐시 없음)."""
    content = LOAD_VAULT.read_text(encoding="utf-8")
    assert "include_vars" in content, (
        "load_vault.yml: include_vars 미사용 — vault 동적 로딩 path 부재"
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
    """load_vault.yml 가 accounts list 를 _rf_accounts 로 정규화 (list[0] = primary)."""
    content = LOAD_VAULT.read_text(encoding="utf-8")
    assert "_rf_accounts" in content, "load_vault.yml: _rf_accounts 변수 부재"
    assert "accounts" in content, "load_vault.yml: vault accounts 키 참조 부재"
    # 주석에 list 순서 정의 명시
    assert "primary" in content.lower(), (
        "load_vault.yml: primary/recovery role 정의 주석 부재"
    )


def test_m_c3_load_vault_legacy_fallback() -> None:
    """load_vault.yml legacy ansible_user/password fallback (backward-compat)."""
    content = LOAD_VAULT.read_text(encoding="utf-8")
    assert "ansible_user" in content, (
        "load_vault.yml: legacy ansible_user fallback 미지원 — backward-compat 깨짐"
    )
    assert "ansible_password" in content, "load_vault.yml: legacy ansible_password fallback 부재"


# ── (5) M-C2 시나리오 5: single run 중 vault 변경 영향 없음 (task scope 캐시) ─


def test_m_c3_scenario_5_single_run_no_midway_invalidation() -> None:
    """include_vars 의 name 파라미터로 task scope 변수 (run 중 변경 영향 없음).

    M-C2 시나리오 5: load_vault.yml 가 이미 실행된 후 vault file 수정 시
    현 run 의 _rf_vault_data 는 task scope 캐시 사용 → 다음 run N+1 부터 반영.

    검증: load_vault.yml 의 include_vars 가 name= 으로 변수 저장
    (host_vars 가 아닌 task 변수 — single-run 중간 invalidation 없음 — 의도된 동작).
    """
    content = LOAD_VAULT.read_text(encoding="utf-8")
    assert "name: _rf_vault_data" in content, (
        "load_vault.yml: include_vars 가 name=_rf_vault_data 로 저장 안 함 — task scope 분리 깨짐"
    )


# ── (6) vault profile resolve from adapter ──────────────────────────────────


def test_m_c3_vault_profile_from_adapter() -> None:
    """_rf_vault_profile 가 _selected_adapter.credentials.profile 에서 resolve (매 run lookup)."""
    content = LOAD_VAULT.read_text(encoding="utf-8")
    assert "_rf_vault_profile" in content, "_rf_vault_profile 변수 부재"
    assert "_selected_adapter" in content and "credentials.profile" in content, (
        "load_vault.yml: adapter.credentials.profile 에서 vault profile resolve 부재"
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
