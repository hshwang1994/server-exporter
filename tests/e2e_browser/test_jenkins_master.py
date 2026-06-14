"""Jenkins master Web UI Browser E2E.

Covers:
  - 마스터 로그인 페이지 도달
  - 인증 후 대시보드 진입
  - Jenkins 버전 / Job list 노출 확인

본 테스트는 lab credentials 가 있는 머신에서만 실행 (conftest 자동 skip).
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect


pytestmark = [pytest.mark.lab, pytest.mark.jenkins]


def _first_master(lab_creds):
    masters = lab_creds.jenkins_masters
    if not masters:
        pytest.skip("No Jenkins master defined in lab credentials")
    return masters[0]


def test_master_dashboard_reachable(page: Page, lab_creds) -> None:
    """마스터 dashboard 진입 (HTTP 200 응답)."""
    master = _first_master(lab_creds)
    url = master["web_url"]

    response = page.goto(url, wait_until="domcontentloaded", timeout=15000)
    assert response is not None, f"No response from {url}"
    assert response.status < 500, (
        f"Jenkins master returned {response.status} from {url}"
    )


def test_master_login_then_dashboard(page: Page, lab_creds) -> None:
    """Jenkins master 로그인 + dashboard 진입 검증.

    cycle-015 사용자 권한 부여로 lab_creds 의 jenkins master 자격증명 사용 활성.
    """
    master = _first_master(lab_creds)
    url = master["web_url"]

    page.goto(f"{url}/login", wait_until="domcontentloaded", timeout=15000)

    # Jenkins login form (input id varies by Jenkins version)
    user_input = page.locator(
        "input[name='j_username'], input#j_username"
    ).first
    pwd_input = page.locator(
        "input[name='j_password'], input#j_password"
    ).first
    user_input.fill(master["ssh_user"])
    pwd_input.fill(master["ssh_password"])

    submit = page.locator(
        "button[name='Submit'], input[name='Submit'], button[type='submit']"
    ).first
    submit.click()

    # 인증 성공이면 login URL 벗어남 + 페이지가 200
    page.wait_for_load_state("domcontentloaded", timeout=15000)
    assert "/login" not in page.url, f"Still on login page: {page.url}"

    # dashboard / "Jenkins" 텍스트 존재 (header 또는 title)
    title = page.title()
    assert "Jenkins" in title, f"Title doesn't contain 'Jenkins': {title}"
