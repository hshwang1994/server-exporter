#!/usr/bin/python3
"""
동적 인벤토리 스크립트 — esxi-gather

접수 목록 JSON 을 파일(INVENTORY_JSON_FILE 이 가리키는 파일 · 작업 폴더의 .inventory_input.json) 또는
환경변수(INVENTORY_JSON)에서 읽어 Ansible 동적 인벤토리를 생성한다.
inventory_json 에는 IP 만 전달. 계정은 vault 에서 로딩.
IP 필드: service_ip (1순위) → ip (fallback)
호출자가 보낸 host object 전체는 hostvar se_host_input 으로 보존한다 (Add-on 이 읽는다).

우선순위 (2026-10-10 FL-F11 — Linux 는 환경변수 하나가 131,072 바이트를 넘으면 그 프로세스 실행 자체가
"Argument list too long" 으로 실패한다. 확장형 입력 5,000대 = 510 KB 실측. 그래서 파이프라인은 파일로 넘긴다):
  1. 환경변수 INVENTORY_JSON_FILE 이 가리키는 파일 — Jenkinsfile_portal 수집 단계가 작업 폴더에
     .inventory_input.json 을 쓰고(sePrepareWorkspace · 재개 시 복원) seGatherEnv 로 이 변수를 넘긴다.
     변수가 있는데 파일이 없거나 비어 있으면 다른 곳으로 넘어가지 않고 오류다.
  2. 환경변수 INVENTORY_JSON / inventory_json (값이 있으면) — 로컬 실행 · scripts/ai/ci_gate.sh 의 syntax-check 같은 작은 입력
  3. $WORKSPACE/.inventory_input.json (WORKSPACE 가 없으면 저장소 루트) — Jenkins 밖에서 직접 실행할 때
  4. 모두 없으면 에러

INVENTORY_JSON 형식:
  [{ "service_ip": "10.x.x.1" }]          — 권장
  [{ "ip": "10.x.x.1" }]                  — fallback (하위 호환)

사용법:
  ansible-playbook -i inventory.sh ...
  ./inventory.sh --list        # Ansible 규약
  ./inventory.sh --host <ip>   # 개별 호스트
"""
import json, os, pathlib, re, sys

# re.ASCII (2026-10-05 F03): \d 가 전각 · 아랍 숫자 같은 비ASCII 숫자까지 받아 연결 단계에서야 실패하던 것을 여기서 거부한다.
#   Jenkins Validate(Jenkinsfile_portal seAcceptTargets)도 같은 규칙이다 — 사례 표 tests/fixtures/input_validation/cases.json.
_IP_PATTERN = re.compile(
    r'^(?:(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\.){3}'
    r'(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)$',
    re.ASCII,
)

def error(msg):
    print(f"[inventory] ERROR: {msg}", file=sys.stderr)
    sys.exit(1)

def validate_ip(ip, idx):
    """IPv4 형식 검증"""
    if not _IP_PATTERN.match(ip):
        error(f"유효하지 않은 IP 형식: '{ip}' (항목[{idx}])")

def _inert(value):
    """호출자가 보낸 값을 글자 그대로의 hostvar 로 옮긴다.

    ansible-core 는 스크립트 인벤토리의 문자열을 Jinja 템플릿으로 신뢰한다.
    문자열을 `__ansible_unsafe` 로 감싸 `{{ }}` 가 든 값도 해석되지 않게 한다.
    `__ansible_` 로 시작하는 키는 Ansible JSON 의 예약 표식이라 옮기지 않는다 —
    그대로 두면 인벤토리 해석이 실패해 그 빌드의 모든 대상이 결과를 잃는다.
    """
    if isinstance(value, str):
        return {"__ansible_unsafe": value}
    if isinstance(value, list):
        return [_inert(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _inert(v) for k, v in value.items()
                if not str(k).startswith("__ansible_")}
    return value

def load_inventory_json():
    """지정 파일 → 환경변수 → 작업 폴더 파일 순서로 인벤토리 JSON 문자열을 가져온다 (우선순위는 모듈 docstring)."""
    # 1순위: INVENTORY_JSON_FILE — 파이프라인이 작업 폴더에 쓴 접수 입력 파일 (환경변수 크기 한도와 무관하다)
    explicit = os.environ.get("INVENTORY_JSON_FILE", "").strip()
    if explicit:
        path = pathlib.Path(explicit)
        if not path.is_file():
            error(f"INVENTORY_JSON_FILE 이 가리키는 파일이 없습니다: {explicit}")
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            error(f"INVENTORY_JSON_FILE 이 가리키는 파일이 비어 있습니다: {explicit}")
        return content

    # 2순위: 환경변수 (대문자 또는 소문자 — Jenkins 파라미터명 그대로 내보내짐). 작은 입력 · 수동 실행 · syntax-check 용
    raw = os.environ.get("INVENTORY_JSON", "").strip()
    if not raw:
        raw = os.environ.get("inventory_json", "").strip()
    if raw:
        return raw

    # 3순위: $WORKSPACE/.inventory_input.json (Jenkins 밖 직접 실행)
    workspace = os.environ.get("WORKSPACE", "")
    if workspace:
        fallback = pathlib.Path(workspace) / ".inventory_input.json"
    else:
        fallback = pathlib.Path(__file__).resolve().parent.parent / ".inventory_input.json"

    if fallback.is_file():
        content = fallback.read_text(encoding="utf-8").strip()
        if content:
            return content

    error("INVENTORY_JSON_FILE · INVENTORY_JSON 환경변수와 .inventory_input.json 파일 모두 비어있습니다.")

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
        # 값 종류 오류는 traceback 대신 명확한 오류로 (2026-10-05 F03) — 허용 범위는 그대로다.
        if not isinstance(host, dict):
            error(f"항목[{idx}] 은 객체여야 합니다")
        value = host.get("service_ip") or host.get("ip") or ""
        if not isinstance(value, str):
            error(f"'service_ip' 또는 'ip' 값은 문자열이어야 합니다 (항목[{idx}])")
        ip = value.strip()
        if not ip:
            error(f"'service_ip' 또는 'ip' 필드 누락 (항목[{idx}])")
        validate_ip(ip, idx)
        if ip in seen:
            error(f"IP 가 중복됩니다: '{ip}' (항목[{idx}])")
        seen.add(ip)
        # host object 는 최상위로 펼치지 않고 한 키 아래에 둔다 — ansible_* 연결 변수나
        # play 변수와 이름이 겹쳐도 연결에 영향이 없다.
        hostvars[ip] = {"ansible_host": ip, "se_host_input": _inert(host)}
        host_keys.append(ip)

    print(json.dumps({
        "all":   {"hosts": host_keys},
        "_meta": {"hostvars": hostvars}
    }, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
