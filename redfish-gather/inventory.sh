#!/usr/bin/python3
"""
동적 인벤토리 스크립트 — redfish-gather

INVENTORY_JSON 환경변수 또는 .inventory_input.json 파일을 파싱하여
Ansible 동적 인벤토리를 생성한다.
inventory_json 에는 IP 만 전달. 벤더는 Redfish Manufacturer 로 자동 감지.
계정은 표준=vault/common/redfish/standard.yml, 복구=vault/<loc>/redfish/<vendor>.yml 에서 로딩.
IP 필드: bmc_ip (1순위) → ip (fallback)

우선순위:
  1. 환경변수 INVENTORY_JSON (값이 있으면 사용)
  2. workspace의 .inventory_input.json 파일 (Jenkinsfile writeFile 로 생성)
  3. 둘 다 없으면 에러

INVENTORY_JSON 형식:
  [{ "bmc_ip": "10.x.x.201" }]            — 권장
  [{ "ip": "10.x.x.201" }]                — fallback (하위 호환)

사용법:
  ansible-playbook -i inventory.sh ...
  ./inventory.sh --list        # Ansible 규약
  ./inventory.sh --host <ip>   # 개별 호스트
"""
import json, os, pathlib, re, sys

_IP_PATTERN = re.compile(
    r'^(?:(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\.){3}'
    r'(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)$'
)

def error(msg):
    print(f"[inventory] ERROR: {msg}", file=sys.stderr)
    sys.exit(1)

def validate_ip(ip, idx):
    """IPv4 형식 검증"""
    if not _IP_PATTERN.match(ip):
        error(f"유효하지 않은 IP 형식: '{ip}' (항목[{idx}])")

def load_inventory_json():
    """환경변수 → 파일 순서로 인벤토리 JSON 문자열을 가져온다."""
    # 1순위: 환경변수 (대문자 또는 소문자 — Jenkins 파라미터명 그대로 내보내짐)
    raw = os.environ.get("INVENTORY_JSON", "").strip()
    if not raw:
        raw = os.environ.get("inventory_json", "").strip()
    if raw:
        return raw

    # 2순위: .inventory_input.json 파일 (Jenkinsfile writeFile 로 생성됨)
    workspace = os.environ.get("WORKSPACE", "")
    if workspace:
        fallback = pathlib.Path(workspace) / ".inventory_input.json"
    else:
        fallback = pathlib.Path(__file__).resolve().parent.parent / ".inventory_input.json"

    if fallback.is_file():
        content = fallback.read_text(encoding="utf-8").strip()
        if content:
            return content

    error("INVENTORY_JSON 환경변수와 .inventory_input.json 파일 모두 비어있습니다.")

def main():
    # --host 처리 (Ansible 규약)
    if len(sys.argv) > 1:
        if sys.argv[1] == '--host' and len(sys.argv) > 2:
            host_arg = sys.argv[2].strip()
            if not _IP_PATTERN.match(host_arg):
                error(f"--host 인자가 유효한 IP 가 아닙니다: '{host_arg}'")
            print(json.dumps({"ansible_host": host_arg}))
            return
        elif sys.argv[1] != '--list':
            # --list 아닌 알 수 없는 인자 → 빈 인벤토리
            print(json.dumps({"all": {"hosts": []}, "_meta": {"hostvars": {}}}))
            return

    raw = load_inventory_json()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        error(f"INVENTORY_JSON 파싱 실패: {e}")
    if not isinstance(payload, list) or not payload:
        error("INVENTORY_JSON 은 비어있지 않은 배열이어야 합니다.")

    hostvars, host_keys, seen = {}, [], set()
    for idx, host in enumerate(payload):
        ip = (host.get("bmc_ip") or host.get("ip") or "").strip()
        if not ip:
            error(f"'bmc_ip' 또는 'ip' 필드 누락 (항목[{idx}])")
        validate_ip(ip, idx)
        if ip in seen:
            error(f"IP 가 중복됩니다: '{ip}' (항목[{idx}])")
        seen.add(ip)
        # inventory_hostname = ip (BMC 는 호스트명 없음)
        hostvars[ip] = {"ansible_host": ip}
        host_keys.append(ip)

    print(json.dumps({
        "all":   {"hosts": host_keys},
        "_meta": {"hostvars": hostvars}
    }, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
