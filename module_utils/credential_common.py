# -*- coding: utf-8 -*-
# ==============================================================================
# credential_common.py — Credential Resolver 순수 함수
# ==============================================================================
# 질문 하나만 답한다: **"어떤 계정으로 인증할 것인가"** 의 *범위*.
#   입력: (location, target_type, 최소 식별정보)
#   출력: credential_scope + vault 상대경로
#
# 이 파일이 하지 않는 것 (의도적):
#   - 파일시스템 접근 없음          → 단위테스트가 fixture 없이 돈다
#   - 절대경로 생성 없음            → REPO_ROOT 결합은 load task 책임
#   - **Secret 취급 없음**          → username / password 는 include_vars 이후에만 존재
#   - 다른 Location / Vendor 로의 fallback 없음
#         `ic + dell` 실패 시 `cj + dell` 이나 `ic + hpe` 를 시도하는 분기가
#         **코드에 존재하지 않는다.** 정책이 아니라 구조로 막는다.
#   - Generation / Model / Firmware 참조 없음
#         세대를 아는 시점이 인증 이후라 선택축으로 쓰면 순환 의존이 된다.
#
# Adapter 와의 관계:
#   Adapter 는 "그 대상에서 어떤 방식으로 수집하는가" 를 답한다. 둘 다 `vendor` 를
#   입력으로 쓰지만 **서로의 산출물을 읽지 않는다.** 그것이 분리의 정의다.
#   (adapter 의 `credentials.profile` 은 더 이상 vault 선택에 쓰이지 않는다.)
# ==============================================================================

__metaclass__ = type

import re

#: 지원 채널
TARGET_TYPES = ("os", "esxi", "redfish")

#: OS 채널의 2번째 선택축. Play 소속으로 이미 확정된 값이라 다시 판정하지 않는다.
OS_TYPES = ("linux", "windows")

#: vault 디렉터리 루트 (저장소 상대)
VAULT_ROOT = "vault"

# ──────────────────────────────────────────────────────────────────────────────
# Redfish 표준 수집 계정(Standard Gathering Account) — **전역 1개**
# ──────────────────────────────────────────────────────────────────────────────
# 2026-08-12 Contract 확정:
#   표준 수집 계정은 Location 과도 Vendor 와도 무관하게 **하나**다.
#   ic+Dell / ic+HPE / cj+Dell / yi+Lenovo / git+Cisco … 전부 같은 계정이다.
#   따라서 경로에 location 도 vendor 도 들어가지 않는다 — 상수다.
#
# 왜 상수로 두는가:
#   함수 인자로 location/vendor 를 받아 조합하면 "언젠가 Location 별로 갈릴 수 있다" 는
#   여지가 코드에 남는다. 그 여지가 곧 9 vendor × 4 Location = 36벌 중복의 원인이었다
#   (2026-08-12 실측: 9개 vendor vault 의 primary 가 전부 동일 — distinct digest 1개).
#   상수로 두면 중복이 구조적으로 불가능하다.
#
# Recovery 계정만 (location + vendor) 축을 갖는다. 목적이 다르기 때문이다 —
# Recovery 는 수집용이 아니라 **표준 계정을 만들거나 되살리기 위한** 계정이다.
REDFISH_STANDARD_SCOPE = "common/redfish/standard"
REDFISH_STANDARD_RELPATH = "{0}/{1}.yml".format(VAULT_ROOT, REDFISH_STANDARD_SCOPE)

#: 표준 계정으로 인정하는 role. 이 role 이 아닌 항목은 표준 후보가 될 수 없다.
ROLE_PRIMARY = "primary"

#: 경로 조각으로 허용하는 문자. registry / vendor_aliases 가 오염돼도
#: `../` 같은 조각이 경로에 들어가지 못하게 하는 최종 방어선이다.
_PATH_SAFE = re.compile(r"\A[a-z0-9_-]+\Z")

# reason enum — 왜 이 scope 가 나왔는지 / 왜 못 만들었는지
REASON_RESOLVED = "resolved"
REASON_UNKNOWN_LOCATION = "unknown_location"
REASON_UNKNOWN_TARGET_TYPE = "unknown_target_type"
REASON_UNKNOWN_OS_TYPE = "unknown_os_type"
REASON_VENDOR_UNRESOLVED = "vendor_unresolved"

REASONS = (
    REASON_RESOLVED,
    REASON_UNKNOWN_LOCATION,
    REASON_UNKNOWN_TARGET_TYPE,
    REASON_UNKNOWN_OS_TYPE,
    REASON_VENDOR_UNRESOLVED,
)


def _clean(value):
    """입력 정규화 — None / 비-str / 대문자 / 공백을 흡수한다.

    BMC 나 Jenkins 파라미터에서 오는 값이므로 타입을 신뢰하지 않는다.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return value.strip().lower()


def _fail(reason, basis):
    """경로를 만들지 않는 결과. `vault_relpath` 는 항상 None 이다."""
    return {
        "credential_scope": None,
        "vault_relpath": None,
        "selection_basis": basis,
        "reason": reason,
    }


def resolve_credential_scope(
    location,
    target_type,
    known_locations,
    known_vendors=(),
    os_type=None,
    vendor=None,
):
    """(location, target_type, 최소 식별정보) → Credential scope.

    Args:
        location:        `se_location` extra-var 값
        target_type:     'os' | 'esxi' | 'redfish'
        known_locations: common/vars/locations.yml 의 키 집합
        known_vendors:   common/vars/vendor_aliases.yml 의 canonical 키 집합
                         (target_type='redfish' 일 때만 사용)
        os_type:         'linux' | 'windows' (target_type='os' 일 때만)
        vendor:          canonical vendor    (target_type='redfish' 일 때만)

    Returns:
        dict — `credential_scope`, `vault_relpath`, `selection_basis`, `reason`.
        **Secret 은 포함되지 않는다.**

        경로 규칙 (전부):
            os      → vault/<location>/os/<os_type>.yml
            esxi    → vault/<location>/esxi.yml
            redfish → vault/<location>/redfish/<vendor>.yml

        `reason != 'resolved'` 이면 `vault_relpath` 는 None 이다. 부분적으로
        추측한 경로를 절대 돌려주지 않는다 — 잘못된 자격증명 시도를 막기 위해서다.
    """
    loc = _clean(location)
    ttype = _clean(target_type)
    ostype = _clean(os_type)
    vdr = _clean(vendor)

    basis = {"location": loc, "target_type": ttype}

    known_loc = _as_set(known_locations)
    if not loc or loc not in known_loc or not _PATH_SAFE.match(loc):
        return _fail(REASON_UNKNOWN_LOCATION, basis)

    if ttype not in TARGET_TYPES:
        return _fail(REASON_UNKNOWN_TARGET_TYPE, basis)

    if ttype == "os":
        basis["os_type"] = ostype
        if ostype not in OS_TYPES:
            return _fail(REASON_UNKNOWN_OS_TYPE, basis)
        parts = (loc, "os", ostype)

    elif ttype == "esxi":
        # 선택축이 location 하나뿐이라 2번째 경로 조각이 없다.
        parts = (loc, "esxi")

    else:  # redfish
        basis["vendor"] = vdr
        known_vdr = _as_set(known_vendors)
        if not vdr or vdr not in known_vdr or not _PATH_SAFE.match(vdr):
            # vendor='unknown' / 빈 값 / 미등록 vendor — 경로를 만들지 않는다.
            # 호출자는 이 reason 을 보고 "빈 자격 1회 시도"(정체 미상 장비 best-effort)
            # 로 갈지, 실패로 끝낼지 결정한다.
            return _fail(REASON_VENDOR_UNRESOLVED, basis)
        parts = (loc, "redfish", vdr)

    return {
        "credential_scope": "/".join(parts),
        "vault_relpath": "{0}/{1}.yml".format(VAULT_ROOT, "/".join(parts)),
        "selection_basis": basis,
        "reason": REASON_RESOLVED,
    }


def resolve_redfish_credentials(
    location,
    known_locations,
    known_vendors=(),
    vendor=None,
):
    """Redfish 전용 — 축이 **둘**이라 결과도 둘이다.

    Args:
        location:        `se_location` extra-var 값
        known_locations: locations.yml 의 키 집합
        known_vendors:   vendor_aliases.yml 의 canonical 키 집합
        vendor:          canonical vendor

    Returns:
        dict — Secret 없음:
            standard_credential_scope / standard_vault_relpath
                항상 같은 값(전역 상수). location / vendor 를 보지 않는다.
            recovery_credential_scope / recovery_vault_relpath
                (location, vendor) 로 결정. 못 정하면 둘 다 None.
            reason
                **recovery 쪽 판정 결과**다. 표준 계정은 상수라 판정할 것이 없다.
                'vendor_unresolved' 여도 표준 계정은 여전히 사용 가능하다 —
                호출자는 표준으로 인증을 시도할 수 있고, 다만 복구는 할 수 없다.

    fallback 이 없다는 것은 여기서도 동일하다: 표준 vault 가 없다고 vendor vault 의
    primary 를 쓰지 않고, Dell recovery 가 없다고 HPE recovery 를 쓰지 않는다.
    각 scope 는 자기 파일 하나만 본다.
    """
    recovery = resolve_credential_scope(
        location=location,
        target_type="redfish",
        known_locations=known_locations,
        known_vendors=known_vendors,
        vendor=vendor,
    )
    return {
        "standard_credential_scope": REDFISH_STANDARD_SCOPE,
        "standard_vault_relpath": REDFISH_STANDARD_RELPATH,
        "recovery_credential_scope": recovery["credential_scope"],
        "recovery_vault_relpath": recovery["vault_relpath"],
        "selection_basis": recovery["selection_basis"],
        "reason": recovery["reason"],
    }


def standard_accounts_of(vault_data):
    """표준 vault 내용 → 표준 수집 후보. `role: primary` 만, **순서 보존**.

    role 이 primary 가 아닌 항목은 버린다. 표준 vault 에 recovery 가 섞여 들어와도
    그것으로 수집하지 않기 위해서다 (§14 — scope 를 넘나드는 대체 금지).
    """
    return [
        a for a in normalize_accounts(vault_data)
        if (a.get("role") or ROLE_PRIMARY) == ROLE_PRIMARY
    ]


def recovery_accounts_of(vault_data):
    """Recovery vault 내용 → 복구 후보. **순서 보존**.

    `role: primary` 는 제외한다. 이유는 하나다: Location/Vendor vault 에 남아 있는
    primary 를 표준 계정 대용으로 쓰는 경로를 **구조적으로** 없애기 위해서다.
    (이관 후에는 애초에 존재하지 않지만, 남아 있어도 쓰이지 않는다.)

    `normalize_accounts` 의 legacy 호환(ansible_user)은 role=primary 를 만들므로
    여기서 자동으로 제외된다 — recovery vault 의 legacy 키는 표준 계정 복제본이었다.
    """
    return [
        a for a in normalize_accounts(vault_data)
        if (a.get("role") or ROLE_PRIMARY) != ROLE_PRIMARY
    ]


def redfish_candidates(standard_accounts, recovery_accounts):
    """Redfish 인증 후보 배열 — 표준이 먼저, 그 다음 recovery.

    두 배열 **내부** 순서는 각각 그대로 둔다. vault 배열 순서 = 시도 순서라는
    기존 Contract 를 recovery 안에서도 유지한다 (role 기반 재정렬 없음).
    """
    return list(standard_accounts or []) + list(recovery_accounts or [])


def _as_set(values):
    """iterable / dict / None → 소문자 문자열 집합."""
    if not values:
        return set()
    if isinstance(values, dict):
        values = values.keys()
    return {_clean(v) for v in values if v is not None}


def normalize_accounts(vault_data, legacy_label="legacy_single"):
    """vault 내용 → 인증 후보 list. **순서를 절대 바꾸지 않는다.**

    `accounts` 배열 순서 = 시도 순서 라는 것이 현재 Contract 다
    (redfish-gather/tasks/load_vault.yml 의 원 주석, 그리고 3채널의 `loop:`).
    role 기반 재정렬은 여기서 하지 않는다 — 암호화된 vault 의 실제 배열 순서를
    실측하기 전에 정렬을 넣으면 인증 순서가 바뀌고, Redfish 에서는 reconcile
    진입 조건까지 흔들 수 있다.

    legacy 단일 자격(`ansible_user` / `ansible_password`) 호환은 유지한다.

    Returns:
        list[dict] — 각 항목에 username / password / label / role.
        vault 가 비었거나 legacy 키도 없으면 빈 list.
    """
    if not isinstance(vault_data, dict):
        return []

    accounts = vault_data.get("accounts")
    if isinstance(accounts, list) and accounts:
        return list(accounts)  # 얕은 복사 — 순서 보존, 원본 비변형

    legacy_user = vault_data.get("ansible_user") or ""
    if legacy_user:
        return [{
            "username": legacy_user,
            "password": vault_data.get("ansible_password") or "",
            "label": legacy_label,
            "role": "primary",
        }]

    return []

# ──────────────────────────────────────────────────────────────────────────────
# Linux sudo 비밀번호 후보 (2026-10-13)
# ──────────────────────────────────────────────────────────────────────────────
# OS Linux vault 의 선택 키 `sudo_passwords` — sudo 가 비밀번호를 요구하는 서버에서
# 로그인 비밀번호 **다음에** 순서대로 시도할 값들이다. username 이 없는 이유: sudo 는
# 호출 계정 자신(표준 sudoers) 또는 root(targetpw/rootpw)의 비밀번호를 검증하므로
# 계정을 고를 일이 없다. 목록이 없으면 레거시 단일 키 `ansible_become_password` 를 쓴다.
#
# 여기서도 Secret 을 해석하지 않는다 — 값은 그대로 옮기고 순서만 보존하며, 같은 값은
# 한 번만 남긴다(같은 비밀번호를 두 번 보내 PAM 실패를 두 번 쌓지 않기 위해서다).
SUDO_PASSWORDS_KEY = "sudo_passwords"
SUDO_LEGACY_KEY = "ansible_become_password"
SUDO_LEGACY_LABEL = "sudo_legacy"
ROLE_SECONDARY = "secondary"


def _secret_text(value):
    """비밀번호 값 → str 또는 None. 다듬지(trim) 않는다 — 공백만 있는 값과 비-스칼라만 버린다.

    YAML 이 따옴표 없는 값을 bool 로 읽었다면(yes/no/true/false) 그것은 비밀번호가 아니라
    표기 실수이므로 버린다. 숫자는 글자 그대로 쓴다(0 도 값이다).
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value if value.strip() else None
    return None


def _label_text(value, index):
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "sudo_{0}".format(index)


def normalize_sudo_passwords(vault_data, legacy_label=SUDO_LEGACY_LABEL):
    """vault 내용 → Linux sudo 비밀번호 후보 list. **순서 보존 · 같은 값 1회 · 예외 없음.**

    Args:
        vault_data: include_vars 로 읽은 vault 내용(dict). dict 가 아니면 빈 list.
        legacy_label: `ansible_become_password` 하나뿐일 때 붙이는 label.

    Returns:
        list[dict] — 각 항목 {password, label, role}. `sudo_passwords` 가 비어 있지 않은 list 면
        그 목록만(항목은 {password, label?, role?} dict 또는 비밀번호 문자열), 아니면 레거시 키를
        1개짜리 목록으로. role 기본값은 남은 첫 항목 primary · 나머지 secondary, label 기본값은
        'sudo_<원본 순번>'(1부터). 값이 비었거나 비-스칼라인 항목은 버린다.
    """
    if not isinstance(vault_data, dict):
        return []

    raw = vault_data.get(SUDO_PASSWORDS_KEY)
    items = []
    if isinstance(raw, list) and raw:
        for index, item in enumerate(raw, start=1):
            if isinstance(item, dict):
                password = _secret_text(item.get("password"))
                label = _label_text(item.get("label"), index)
                role = item.get("role")
            else:
                password = _secret_text(item)
                label = _label_text(None, index)
                role = None
            if password is None:
                continue
            items.append((password, label, role))
    else:
        legacy = _secret_text(vault_data.get(SUDO_LEGACY_KEY))
        if legacy is not None:
            items.append((legacy, legacy_label, ROLE_PRIMARY))

    out = []
    seen = set()
    for password, label, role in items:
        if password in seen:
            continue
        seen.add(password)
        if not (isinstance(role, str) and role.strip()):
            role = ROLE_PRIMARY if not out else ROLE_SECONDARY
        else:
            role = role.strip()
        out.append({"password": password, "label": label, "role": role})
    return out
