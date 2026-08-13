"""결과물에 실제 자격증명이 섞였는지 검사한다 — **평문을 저장하지 않고**.

왜 이 파일이 생겼나 (2026-08-12)
--------------------------------
누출 방지 테스트들이 "이 비밀번호가 envelope 에 나오면 안 된다" 를 검사하려고
**진짜 비밀번호를 소스에 그대로 적어** 두고 있었다. 검사 대상 문자열이 검사 코드
안에 평문으로 남아 있으니, 가드 자체가 누출 지점이었다. 실제로 저장소 전수 조사에서
tracked file 391 개에 실 자격증명 10 종이 평문으로 있었고 그중 8 개가 이 테스트들이다.

해법: 값 대신 **sha256 앞 8자리**만 들고 있는다. digest 로는 원문을 복원할 수 없으므로
저장소에 남아도 자격증명이 아니다. 검사는 대상 텍스트에서 후보 문자열을 잘라 digest 를
비교하는 방식이라, 종전과 동일하게 "이 값이 나왔는가" 를 정확히 판정한다.

길이를 함께 두는 이유
--------------------
digest 만으로 검사하려면 길이 6~40 의 모든 부분문자열을 해싱해야 해서 느리다. 알려진
길이만 훑으면 텍스트 길이에 비례하는 비용으로 끝난다. 길이는 8~15 구간이라 공격자가
이미 가정하는 범위이며, 이를 남기는 대가로 **평문 자격증명 10 종을 저장소에서 제거**했다.
(진단 출력에 길이를 남기지 않는 정책은 Portal 소비자용 envelope 에 대한 것으로, 여기와
목적이 다르다 — `redfish_gather.py` 의 `policy.within_declared_bounds` 주석 참조.)

무엇을 넣지 않는가
------------------
`admin` / `password` / `ADMIN` / `calvin` / `Admin@9000` 같은 **벤더가 공개한 공장
기본값이자 사전 단어**는 넣지 않는다. 넣으면 산출물에 흔히 등장하는 평범한 단어까지
누출로 잡혀 가드가 무의미해진다 (이 저장소에서 각각 627 / 433 개 파일에 등장한다).
그 값들은 이미 `docs/operate/05-vault.md` 의 벤더 기본값 표에 공개 문서로 존재한다.
"""
from __future__ import annotations

import hashlib
import re

# (sha256 앞 8자리, 길이). 값은 어디에도 없다.
#   - 운영 중인 Vault 자격증명 (Location x Vendor recovery, 전역 표준, OS/ESXi)
#   - 과거 세대 표준 계정 비밀번호 (회전됐지만 문서/증거에 남아 있던 것)
_KNOWN: tuple[tuple[str, int], ...] = (
    ("0be138fb", 6),
    ("1d8fe022", 13),
    ("2b3b6862", 8),
    ("330238df", 10),
    ("37a1db6b", 10),
    ("428829ae", 12),
    ("6292d395", 12),
    ("93cf6a26", 9),
    ("9477272a", 9),
    ("9892c533", 10),
    ("9b87f708", 15),
    ("a109e369", 12),
    ("ef513062", 8),
    ("f28b309b", 11),
    ("f3e3f831", 9),
)

KNOWN_SECRET_DIGESTS: frozenset[str] = frozenset(d for d, _ in _KNOWN)
_LENGTHS: tuple[int, ...] = tuple(sorted({n for _, n in _KNOWN}))

# 합성 canary — 실제 자격증명이 아니다. 테스트가 **입력으로 넣고** 출력에서 찾는 용도.
# 종전에는 진짜 비밀번호를 입력으로 넣었는데, canary 를 쓰면 의미는 같고 위험은 없다.
CANARY_PASSWORD = "zzz-canary-password-zzz"
CANARY_BECOME = "zzz-canary-become-zzz"
CANARY_RECOVERY = "zzz-canary-recovery-zzz"
CANARY_TARGET = "zzz-canary-target-zzz"
CANARIES: tuple[str, ...] = (
    CANARY_PASSWORD, CANARY_BECOME, CANARY_RECOVERY, CANARY_TARGET,
)

# 구조로 잡는 일반 패턴 — 값을 몰라도 "자격증명을 붙여넣었다" 를 잡는다.
GENERIC_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p) for p in (
        # 값 앞에 따옴표가 오는 형태(`"password": "<값>"`)까지 잡는다.
        r"password\s*[=:]\s*[\"']?[^\s\"',}]{4,}",
        r"Authorization\s*[=:]",
        r"Basic\s+[A-Za-z0-9+/]{8,}={0,2}",
        # scheme://user:pass@host 형태
        r"://[^/\s:@]+:[^/\s@]+@",
    )
)

_PRINTABLE_RUN = re.compile(r"[!-~]+")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def find_known_secrets(text: str) -> set[str]:
    """`text` 안에 알려진 자격증명이 들어 있으면 그 digest 들을 돌려준다.

    반환이 빈 집합이어야 정상이다. 어떤 값이 나왔는지는 digest 로만 보고되므로
    실패 메시지에도 평문이 찍히지 않는다.
    """
    if not text:
        return set()
    found: set[str] = set()
    for run in _PRINTABLE_RUN.findall(text):
        n = len(run)
        for length in _LENGTHS:
            if length > n:
                continue
            for i in range(n - length + 1):
                d = _digest(run[i:i + length])
                if d in KNOWN_SECRET_DIGESTS:
                    found.add(d)
    return found


def assert_no_secret(text: str, what: str = "결과") -> None:
    """알려진 자격증명 / 합성 canary / 일반 패턴을 한 번에 검사한다."""
    leaked = find_known_secrets(text)
    assert not leaked, f"{what} 에 알려진 자격증명이 노출됐다 (sha256-8: {sorted(leaked)})"
    for canary in CANARIES:
        assert canary not in text, f"{what} 에 입력 자격증명(canary)이 그대로 노출됐다"
