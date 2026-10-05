#!/usr/bin/python3
import json, os, pathlib, re, sys

_IP_PATTERN = re.compile(
    r'^(?:(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\.){3}'
    r'(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)$',
    re.ASCII,
)

def error(msg):
    print(f"[inventory] ERROR: {msg}", file=sys.stderr)
    sys.exit(1)

def validate_ip(ip, idx):
    if not _IP_PATTERN.match(ip):
        error(f"유효하지 않은 IP 형식: '{ip}' (항목[{idx}])")

def _inert(value):
    if isinstance(value, str):
        return {"__ansible_unsafe": value}
    if isinstance(value, list):
        return [_inert(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _inert(v) for k, v in value.items()
                if not str(k).startswith("__ansible_")}
    return value

def load_inventory_json():
    raw = os.environ.get("INVENTORY_JSON", "").strip()
    if not raw:
        raw = os.environ.get("inventory_json", "").strip()
    if raw:
        return raw

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
        hostvars[ip] = {"ansible_host": ip, "se_host_input": _inert(host)}
        host_keys.append(ip)

    print(json.dumps({
        "all":   {"hosts": host_keys},
        "_meta": {"hostvars": hostvars}
    }, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
