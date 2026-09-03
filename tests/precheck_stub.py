# -*- coding: utf-8 -*-
"""precheck_bundle 테스트 공용 — ICMP 확인 결과를 **주입**한다.

2026-09-03 부터 reachable 은 "관리 TCP 응답 OR ICMP Echo 응답" 이다
(common/library/precheck_bundle.py 의 _resolve_reachability). TCP 가 전 포트 무응답이면
모듈이 ICMP 를 한 번 더 확인하는데, 테스트가 이를 그대로 두면 실제 `ping` 프로세스가 뜬다.
느릴 뿐 아니라 실행 환경(사내망 / CI / 개발 PC)에 따라 결과가 갈려 회귀가 흔들린다.

그래서 precheck 하네스는 모두 이 헬퍼로 ICMP 결과를 고정한다. 기본값은 "응답 없음" —
즉 **종전(TCP 전용) 판정과 같은 결과**라, 기존 회귀의 의미가 그대로 보존된다.
ICMP OR 판정 자체의 회귀는 tests/unit/test_precheck_icmp_reachability.py 가 잠근다.
"""

# icmp_check() 반환 계약: (replied, note)
ICMP_SILENT = (False, "icmp: 응답 없음 (테스트 스텁)")
ICMP_REPLY = (True, "icmp: Echo Reply 확인 (테스트 스텁)")


def silence_icmp(monkeypatch, pb, result=ICMP_SILENT):
    """pb.icmp_check 를 고정 결과로 대체한다 (실 ping 프로세스 금지)."""
    monkeypatch.setattr(pb, "icmp_check", lambda *_a, **_k: result)
    return result
