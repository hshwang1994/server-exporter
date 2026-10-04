"""Ansible Vault 1.1 파일 복호화 + 구조 검증 (Windows 호환).

ansible-vault CLI 없이 cryptography 패키지로 직접 복호화한다.

목적 — Location Vault 이관 검증 (2026-08-12):
    Location 축이 생기면서 vault 파일이 `vault/<location>/...` 로 늘어난다. 이관 중에는
    "파일은 만들었는데 복호화가 안 된다 / accounts 스키마가 다르다 / role 이 빠졌다" 가
    실행 시점(=실장비 인증 시도 시점)에야 드러나기 쉽다. 그 전에 잡는다.

검증 항목:
    1. 헤더가 `$ANSIBLE_VAULT` 인가
    2. 현재 마스터 키로 복호화되는가
    3. `accounts[]` 가 있고 각 항목에 username / password / label / role 이 있는가
       (또는 legacy 단일 자격 `ansible_user` / `ansible_password`)
    4. role 이 {primary, recovery, secondary} 안에 있고 primary 가 1개 이상인가
    5. Redfish 는 label 이 vendor 허용 집합과 정합인가 (docs/21 §6.5)
    6. [경고] accounts[0].role != primary — 배열 순서가 곧 시도 순서이므로
       recovery 가 먼저 오면 의도한 것인지 확인이 필요하다 (차단하지는 않는다)
    7. locations.yml 의 각 Location 에 대해 기대 경로 존재 여부 (이관 진행 상황)

**Secret 값은 어떤 경우에도 출력하지 않는다.**
    password 는 물론 username 도 찍지 않는다. 존재 여부(bool)와 개수, label, role 만 낸다.
    `tests/unit/test_vault_check_no_secret_output.py` 가 이 성질을 강제한다.

사용법:
    SE_VAULT_PASSWORD=... python scripts/ai/vault_decrypt_check.py
    python scripts/ai/vault_decrypt_check.py --password-file /path/to/pass
    python scripts/ai/vault_decrypt_check.py --layout-only     # 복호화 없이 구조만
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, hmac, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parents[2]

VALID_ROLES = frozenset({"primary", "recovery", "secondary"})
REQUIRED_ACCOUNT_KEYS = ("username", "password", "label", "role")

# 정본 = docs/21_vault-operations.md §6.5 / tests/unit/test_adapter_vault_label_consistency.py
VENDOR_ALLOWED_LABELS: dict[str, frozenset[str]] = {
    "dell": frozenset({"dell_fallback_1", "dell_fallback_2", "dell_current", "lab_dell_root"}),
    "hpe": frozenset({"hpe_fallback", "hpe_current", "hpe_factory"}),
    "lenovo": frozenset({"lenovo_fallback", "lenovo_current", "lenovo_factory"}),
    "supermicro": frozenset({"supermicro_factory"}),
    "cisco": frozenset({"cisco_current", "cisco_factory"}),
    "huawei": frozenset({"huawei_factory"}),
    "inspur": frozenset({"inspur_factory"}),
    "fujitsu": frozenset({"fujitsu_factory"}),
    "quanta": frozenset({"quanta_factory"}),
}


def decrypt_vault(file_path: Path, password: str) -> str:
    raw = file_path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    if not lines or not lines[0].startswith("$ANSIBLE_VAULT"):
        raise ValueError(f"Not a vault file: {file_path}")

    payload_hex = "".join(line.strip() for line in lines[1:])
    decoded = bytes.fromhex(payload_hex).decode("utf-8")
    parts = decoded.split("\n")
    if len(parts) < 3:
        raise ValueError(f"Invalid vault format: {file_path}")

    salt = bytes.fromhex(parts[0])
    expected_hmac = bytes.fromhex(parts[1])
    ciphertext = bytes.fromhex(parts[2])

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=80,
        salt=salt,
        iterations=10000,
        backend=default_backend(),
    )
    keys = kdf.derive(password.encode("utf-8"))
    key1, key2, iv = keys[0:32], keys[32:64], keys[64:80]

    h = hmac.HMAC(key2, hashes.SHA256(), backend=default_backend())
    h.update(ciphertext)
    h.verify(expected_hmac)

    # ansible vault 1.1 = AES-256-CTR + PKCS7 padding (ansible code 일관성용)
    cipher = Cipher(algorithms.AES(key1), modes.CTR(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    plaintext = unpadder.update(padded) + unpadder.finalize()
    return plaintext.decode("utf-8")


def vendor_of(rel_path: str) -> str | None:
    """`vault/<loc>/redfish/<vendor>.yml` → vendor. Redfish 가 아니면 None."""
    parts = Path(rel_path).parts
    if len(parts) >= 4 and parts[-2] == "redfish":
        return Path(parts[-1]).stem
    # flat 구조 호환: vault/redfish/<vendor>.yml
    if len(parts) == 3 and parts[1] == "redfish":
        return Path(parts[-1]).stem
    return None


def kind_of(relpath: str) -> str:
    """파일이 어떤 역할의 vault 인지 (2026-08-12 표준/복구 분리).

    standard : vault/common/redfish/standard.yml — 전역 표준 수집 계정 (primary 만)
    recovery : vault/<loc>/redfish/<vendor>.yml  — 복구 계정 (recovery 만)
    single   : 그 밖 (OS / ESXi / 구 flat) — primary 1개 이상 필요
    """
    p = relpath.replace("\\", "/")
    if p == "vault/common/redfish/standard.yml":
        return "standard"
    parts = p.split("/")
    if len(parts) == 4 and parts[0] == "vault" and parts[2] == "redfish":
        return "recovery"
    return "single"


def inspect_accounts(plaintext: str, vendor: str | None = None,
                     kind: str = "single") -> dict[str, Any]:
    """복호화 결과의 **구조**만 본다. 값은 담지 않는다.

    kind 에 따라 기대 role 이 다르다 — 복구 vault 에 primary 가 없는 것은 정상이고,
    오히려 **있으면** 표준 계정 중복이라 문제다.
    """
    import yaml

    try:
        data = yaml.safe_load(plaintext) or {}
    except yaml.YAMLError as e:
        return {"yaml_parse_ok": False, "error": str(e), "problems": ["YAML 파싱 실패"]}

    if not isinstance(data, dict):
        return {"yaml_parse_ok": True, "is_dict": False, "type": type(data).__name__,
                "problems": ["최상위가 매핑이 아니다"]}

    accounts = data.get("accounts")
    problems: list[str] = []
    warnings: list[str] = []

    result: dict[str, Any] = {
        "yaml_parse_ok": True,
        "is_dict": True,
        "top_level_keys": sorted(data.keys()),
        "has_accounts_key": "accounts" in data,
        "accounts_count": len(accounts) if isinstance(accounts, list) else 0,
        # 존재 여부만 — 값은 담지 않는다
        "has_legacy_user": bool(data.get("ansible_user")),
        "has_legacy_password": bool(data.get("ansible_password")),
        "has_become_password": bool(data.get("ansible_become_password")),
    }

    if isinstance(accounts, list) and accounts:
        labels = [(a.get("label") if isinstance(a, dict) else None) for a in accounts]
        roles = [(a.get("role") if isinstance(a, dict) else None) for a in accounts]
        result["account_labels"] = labels
        result["account_roles"] = roles
        # username 은 찍지 않는다 — 존재 여부만
        result["account_username_present"] = [
            bool(a.get("username")) if isinstance(a, dict) else False for a in accounts
        ]

        for idx, acct in enumerate(accounts):
            if not isinstance(acct, dict):
                problems.append(f"accounts[{idx}] 가 매핑이 아니다")
                continue
            missing = [k for k in REQUIRED_ACCOUNT_KEYS if not acct.get(k)]
            if missing:
                problems.append(f"accounts[{idx}] 필수 키 누락: {missing}")
            role = acct.get("role")
            if role and role not in VALID_ROLES:
                problems.append(f"accounts[{idx}] role={role!r} 는 {sorted(VALID_ROLES)} 밖")

        if kind == "recovery":
            extra = sorted({r for r in roles if r != "recovery"})
            if extra:
                problems.append(
                    f"복구 vault 에 recovery 아닌 role 이 있다: {extra} — "
                    "표준 계정은 vault/common/redfish/standard.yml 한 곳에만 둔다"
                )
        elif "primary" not in roles:
            problems.append("role=primary 후보가 없다 (표준 계정 전환 경로가 동작하지 않는다)")
        if kind == "standard":
            extra = sorted({r for r in roles if r != "primary"})
            if extra:
                problems.append(
                    f"표준 vault 에 primary 아닌 role 이 있다: {extra} — "
                    "복구 계정은 vault/<loc>/redfish/<vendor>.yml 에 둔다"
                )
            if len(accounts) != 1:
                warnings.append(
                    f"표준 vault 의 accounts 가 {len(accounts)}개다 — 표준 계정은 1개가 원칙이다"
                )
        if kind != "recovery" and roles and roles[0] != "primary":
            # 차단하지 않는다 — 의도적일 수 있다. 다만 배열 순서 = 시도 순서다.
            warnings.append(
                f"accounts[0].role={roles[0]!r} — 배열 순서가 곧 인증 시도 순서다. "
                "recovery 를 먼저 시도하는 것이 의도인지 확인하라"
            )

        # 허용 label set 의 정본은 adapter 의 `credentials.recovery_accounts[].vault_label`
        # 이다 (tests/unit/test_adapter_vault_label_consistency.py). 즉 **recovery 후보의
        # label 집합**이지 vault 전체 label 집합이 아니다.
        #   primary(표준 수집 계정)의 label 은 adapter recovery 목록에 없는 것이 정상이고,
        #   실제로 9 vendor 모두 primary 는 vendor 공통 label 을 쓴다.
        # 2026-08-12: 종전에는 primary 까지 이 set 에 넣고 검사해서 9건 전부 오탐이었다.
        if vendor and vendor in VENDOR_ALLOWED_LABELS:
            allowed = VENDOR_ALLOWED_LABELS[vendor]
            unknown = [
                (a.get("label") if isinstance(a, dict) else None)
                for a in accounts
                if isinstance(a, dict)
                and a.get("role") == "recovery"
                and a.get("label")
                and a.get("label") not in allowed
            ]
            if unknown:
                problems.append(
                    f"vendor={vendor} recovery label 이 허용 set 밖: {unknown} "
                    f"(허용: {sorted(allowed)})"
                )
    elif not result["has_legacy_user"]:
        problems.append("accounts 도 legacy ansible_user 도 없다 — 인증 후보가 0개가 된다")

    result["problems"] = problems
    result["warnings"] = warnings
    return result


def expected_paths_from_registry() -> dict[str, list[str]]:
    """locations.yml + vendor_aliases.yml 로부터 기대 vault 경로를 만든다 (이관 진행 확인용)."""
    import yaml

    reg = REPO_ROOT / "common" / "vars" / "locations.yml"
    aliases = REPO_ROOT / "common" / "vars" / "vendor_aliases.yml"
    if not reg.is_file() or not aliases.is_file():
        return {}
    locations = (yaml.safe_load(reg.read_text(encoding="utf-8")) or {}).get("locations", {})
    vendors = (yaml.safe_load(aliases.read_text(encoding="utf-8")) or {}).get("vendor_aliases", {})

    out: dict[str, list[str]] = {}
    for loc in locations:
        paths = [f"vault/{loc}/os/linux.yml", f"vault/{loc}/os/windows.yml",
                 f"vault/{loc}/esxi.yml"]
        paths += [f"vault/{loc}/redfish/{v}.yml" for v in sorted(vendors)]
        out[loc] = paths
    return out


def discover_vault_files() -> list[Path]:
    """vault/ 아래 모든 vault 파일 (숨김 파일 제외 — .lab-credentials.yml 은 대상 아님)."""
    vault_root = REPO_ROOT / "vault"
    if not vault_root.is_dir():
        return []
    return sorted(
        f for f in vault_root.rglob("*.yml")
        if not any(part.startswith(".") for part in f.relative_to(vault_root).parts)
    )


def report_migration_layout() -> None:
    """Location 별 기대 경로의 존재 여부. 이관 진행 상황을 한눈에 본다."""
    expected = expected_paths_from_registry()
    if not expected:
        print("[INFO] locations.yml / vendor_aliases.yml 을 읽지 못해 layout 검사를 건너뛴다")
        return
    print("\n=== Location Vault layout (이관 진행 상황) ===")
    for loc, paths in expected.items():
        present = [p for p in paths if (REPO_ROOT / p).is_file()]
        print(f"  {loc}: {len(present)}/{len(paths)} 존재")
        missing = [p for p in paths if p not in present]
        if missing:
            print(f"    미생성: {missing}")


def resolve_password(args: argparse.Namespace) -> str | None:
    """마스터 키 획득. **기본값을 코드에 두지 않는다.**

    종전에는 이 파일에 실제 마스터 비밀번호가 기본 인자로 박혀 있었다. 저장소에 평문
    자격증명을 두지 않는다는 원칙을 정면으로 어기는 상태였으므로 제거했다.
    """
    if args.password_file:
        return Path(args.password_file).read_text(encoding="utf-8").strip()
    env = os.environ.get("SE_VAULT_PASSWORD") or os.environ.get("ANSIBLE_VAULT_PASSWORD")
    if env:
        return env
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="vault 복호화 + 구조 검증 (Secret 미출력)")
    parser.add_argument("--password-file", help="마스터 키 파일 경로")
    parser.add_argument("--layout-only", action="store_true",
                        help="복호화 없이 경로 존재 여부만 확인")
    args = parser.parse_args()

    report_migration_layout()

    if args.layout_only:
        return 0

    password = resolve_password(args)
    if not password:
        print(
            "\n[ERROR] 마스터 키를 찾지 못했다. 다음 중 하나를 지정하라:\n"
            "  SE_VAULT_PASSWORD=... python scripts/ai/vault_decrypt_check.py\n"
            "  python scripts/ai/vault_decrypt_check.py --password-file <path>\n"
            "  python scripts/ai/vault_decrypt_check.py --layout-only\n"
            "(코드에 기본 비밀번호를 두지 않는다 — 2026-08-12 제거)",
            file=sys.stderr,
        )
        return 2

    files = discover_vault_files()
    if not files:
        print(f"[ERROR] vault 파일이 없다: {REPO_ROOT / 'vault'}", file=sys.stderr)
        return 1

    overall_ok = True
    for f in files:
        rel = f.relative_to(REPO_ROOT).as_posix()
        print(f"\n=== {rel} ===")
        try:
            plaintext = decrypt_vault(f, password)
        except Exception as e:
            overall_ok = False
            print(f"[FAIL] decrypt: {type(e).__name__}: {e}")
            continue
        print("[OK]   decrypt success")

        info = inspect_accounts(plaintext, vendor=vendor_of(rel), kind=kind_of(rel))
        problems = info.pop("problems", [])
        warnings = info.pop("warnings", [])
        for k, v in info.items():
            print(f"  {k}: {v}")
        for w in warnings:
            print(f"  [WARN] {w}")
        for p in problems:
            overall_ok = False
            print(f"  [FAIL] {p}")

    print("\n" + ("[PASS] 전량 통과" if overall_ok else "[FAIL] 문제 있는 파일이 있다"))
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
