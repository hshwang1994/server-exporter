#!/usr/bin/env python3
"""Round 13: Remote identifier collection test runner.

SSH into Ansible host, sync modified files, run os-gather for each target,
and extract identifier fields from the JSON output.

Usage:
  python tests/scripts/remote_identifier_test.py
"""
import paramiko
import json
import sys
import os
import time

# ── Config ──────────────────────────────────────────────────────────────
# production-audit (2026-04-29): 자격증명 하드코딩 제거 — 환경변수 강제.
# 사용 예: SE_ANSIBLE_HOST=10.100.64.166 SE_ANSIBLE_USER=cloviradmin SE_ANSIBLE_PASS=... python ...
# 모듈 import 시점에는 검증하지 않음 (pytest collection 차단 방지). main() 실행 시 검증.
ANSIBLE_HOST = os.environ.get("SE_ANSIBLE_HOST", "10.100.64.166")
ANSIBLE_USER = os.environ.get("SE_ANSIBLE_USER", "cloviradmin")
ANSIBLE_PASS = os.environ.get("SE_ANSIBLE_PASS", "")
REMOTE_DIR = "/home/cloviradmin/server-exporter"
OUTPUT_DIR = "/tmp/round13_identifier"

# Files to sync (local path relative to repository root)
FILES_TO_SYNC = [
    "os-gather/tasks/linux/gather_system.yml",
]

# Test matrix: (label, channel, target_ip, extra_vars)
TESTS = [
    ("Ubuntu-no-become",      "os",      "10.100.64.166", {}),
    ("Ubuntu-with-become",    "os",      "10.100.64.166", {"ansible_become_password": ANSIBLE_PASS}),
    ("RHEL-no-become",        "os",      "10.100.64.197", {}),
    ("Baremetal-no-become",   "os",      "10.100.64.96",  {}),
    ("Baremetal-with-become", "os",      "10.100.64.96",  {"ansible_become_password": ANSIBLE_PASS}),
    ("Windows",               "os",      "10.100.64.120", {"ansible_user": "gooddit"}),
    ("ESXi",                  "esxi",    "10.100.64.2",   {"ansible_user": "root"}),
]


def ssh_connect():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(ANSIBLE_HOST, username=ANSIBLE_USER, password=ANSIBLE_PASS, timeout=15)
    return client


def ssh_exec(client, cmd, timeout=120):
    """Execute command and return (stdout, stderr, rc)."""
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    rc = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out, err, rc


def sync_files(client):
    """Upload modified files to remote host."""
    sftp = client.open_sftp()
    local_base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    for rel_path in FILES_TO_SYNC:
        local_path = os.path.join(local_base, rel_path.replace("/", os.sep))
        remote_path = f"{REMOTE_DIR}/{rel_path}"

        # Ensure remote directory exists
        remote_dir = "/".join(remote_path.split("/")[:-1])
        ssh_exec(client, f"mkdir -p {remote_dir}")

        print(f"  Uploading: {rel_path}")
        sftp.put(local_path, remote_path)

    sftp.close()


def run_gather(client, label, channel, target_ip, extra_vars):
    """Run ansible-playbook and capture output."""
    playbook = {
        "os": "os-gather/site.yml",
        "esxi": "esxi-gather/site.yml",
        "redfish": "redfish-gather/site.yml",
    }[channel]

    # Build extra-vars string
    ev_parts = [f"-e ansible_user={extra_vars.get('ansible_user', ANSIBLE_USER)}"]
    ev_parts.append(f"-e ansible_password='{ANSIBLE_PASS}'")
    if "ansible_become_password" in extra_vars:
        ev_parts.append(f"-e ansible_become_password='{extra_vars['ansible_become_password']}'")

    ev_str = " ".join(ev_parts)
    log_file = f"{OUTPUT_DIR}/{label}.log"

    cmd = (
        f"cd {REMOTE_DIR} && "
        f"export REPO_ROOT={REMOTE_DIR} && "
        f"export ANSIBLE_CONFIG={REMOTE_DIR}/ansible.cfg && "
        f"mkdir -p {OUTPUT_DIR} && "
        f"ansible-playbook {playbook} "
        f"-i '{target_ip},' "
        f"{ev_str} "
        f"2>&1 | tee {log_file}"
    )

    print(f"\n{'='*70}")
    print(f"[{label}] {channel}-gather → {target_ip}")
    print(f"{'='*70}")

    out, err, rc = ssh_exec(client, cmd, timeout=180)
    return out, log_file


def extract_identifiers(raw_output, label):
    """Extract identifier fields from ansible output."""
    result = {
        "label": label,
        "status": None,
        "serial_number": "PARSE_ERROR",
        "system_uuid": "PARSE_ERROR",
        "hosting_type": "PARSE_ERROR",
        "corr_serial": "PARSE_ERROR",
        "corr_uuid": "PARSE_ERROR",
        "diagnostics": [],
    }

    # json_only callback outputs JSON in the "msg" field of OUTPUT task
    # Try to find JSON output
    import re

    # Method 1: Look for OUTPUT task JSON in the msg field
    # The callback outputs something like: "msg": "{\"status\": ...}"
    json_candidates = []

    for line in raw_output.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Try direct JSON parse
        if line.startswith("{"):
            try:
                d = json.loads(line)
                if "status" in d or "data" in d:
                    json_candidates.append(d)
            except json.JSONDecodeError:
                pass

    # Method 2: regex for "msg": "escaped json"
    msg_pattern = r'"msg"\s*:\s*"(\{.*?\})"'
    for match in re.finditer(msg_pattern, raw_output, re.DOTALL):
        try:
            raw_json = match.group(1).replace('\\"', '"').replace('\\\\', '\\')
            d = json.loads(raw_json)
            if "status" in d or "data" in d:
                json_candidates.append(d)
        except (json.JSONDecodeError, Exception):
            pass

    # Method 3: Look for full JSON block between braces
    brace_pattern = r'\{[^{}]*"status"[^{}]*"data"[^{}]*\}'
    # This is too simplistic for nested JSON, try a different approach
    # Look for lines that contain status and data keys
    for match in re.finditer(r'(\{.+\})', raw_output):
        try:
            d = json.loads(match.group(1))
            if "status" in d and "data" in d:
                json_candidates.append(d)
        except (json.JSONDecodeError, Exception):
            pass

    if not json_candidates:
        result["status"] = "NO_OUTPUT_FOUND"
        # Check if there's a failure indication
        if "UNREACHABLE" in raw_output:
            result["status"] = "UNREACHABLE"
        elif "FAILED" in raw_output:
            result["status"] = "GATHER_FAILED"
        return result

    # Use the last valid JSON (the OUTPUT task)
    data = json_candidates[-1]
    result["status"] = data.get("status", "?")

    system = data.get("data", {}).get("system", {})
    result["serial_number"] = system.get("serial_number")
    result["system_uuid"] = system.get("system_uuid")
    result["hosting_type"] = system.get("hosting_type")

    corr = data.get("correlation", {})
    result["corr_serial"] = corr.get("serial_number")
    result["corr_uuid"] = corr.get("system_uuid")

    # Extract identifier-related diagnostics
    errors = data.get("errors", [])
    for e in errors:
        msg = e.get("message", "")
        if "serial" in msg.lower() or "uuid" in msg.lower() or "identifier" in msg.lower():
            result["diagnostics"].append(msg)

    return result


def main():
    if not ANSIBLE_PASS:
        raise SystemExit("SE_ANSIBLE_PASS 환경변수 누락 — 자격증명을 환경변수로 전달하세요.")
    print("Round 13: Identifier Collection Verification")
    print(f"Timestamp: {time.strftime('%Y-%m-%dT%H:%M:%S')}")
    print(f"Ansible Host: {ANSIBLE_HOST}")
    print()

    # Connect
    print("Connecting to Ansible host...")
    client = ssh_connect()
    print("Connected.")

    # Sync files
    print("\nSyncing modified files...")
    sync_files(client)
    print("Sync complete.")

    # Verify sync
    out, err, rc = ssh_exec(client, f"head -5 {REMOTE_DIR}/os-gather/tasks/linux/gather_system.yml")
    print(f"Remote file check: rc={rc}")

    # Run tests
    results = []
    for label, channel, target_ip, extra_vars in TESTS:
        try:
            raw_output, log_file = run_gather(client, label, channel, target_ip, extra_vars)
            result = extract_identifiers(raw_output, label)
            results.append(result)

            # Print immediate result
            print(f"\n  Result: status={result['status']}")
            print(f"  serial_number: {result['serial_number']}")
            print(f"  system_uuid:   {result['system_uuid']}")
            print(f"  hosting_type:  {result['hosting_type']}")
            if result["diagnostics"]:
                for d in result["diagnostics"]:
                    print(f"  diag: {d}")
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({"label": label, "status": f"ERROR: {e}",
                          "serial_number": None, "system_uuid": None,
                          "hosting_type": None, "corr_serial": None,
                          "corr_uuid": None, "diagnostics": []})

    # ── Redfish R760 (separate — uses vault auto-loading) ──
    print(f"\n{'='*70}")
    print("[Redfish-R760] redfish-gather → 10.100.15.34")
    print(f"{'='*70}")
    try:
        cmd = (
            f"cd {REMOTE_DIR} && "
            f"export REPO_ROOT={REMOTE_DIR} && "
            f"export ANSIBLE_CONFIG={REMOTE_DIR}/ansible.cfg && "
            f"mkdir -p {OUTPUT_DIR} && "
            f"ansible-playbook redfish-gather/site.yml "
            f"-i '10.100.15.34,' "
            f"2>&1 | tee {OUTPUT_DIR}/Redfish-R760.log"
        )
        out, err, rc = ssh_exec(client, cmd, timeout=180)
        rf_result = extract_identifiers(out, "Redfish-R760")
        results.append(rf_result)
        print(f"\n  Result: status={rf_result['status']}")
        print(f"  serial_number: {rf_result['serial_number']}")
        print(f"  system_uuid:   {rf_result['system_uuid']}")
    except Exception as e:
        print(f"  ERROR: {e}")
        results.append({"label": "Redfish-R760", "status": f"ERROR: {e}",
                        "serial_number": None, "system_uuid": None,
                        "hosting_type": None, "corr_serial": None,
                        "corr_uuid": None, "diagnostics": []})

    # ── Summary Table ──
    print("\n")
    print("=" * 100)
    print("SUMMARY TABLE: Identifier Collection Results")
    print("=" * 100)
    print()
    print(f"{'Label':<25} {'Status':<10} {'serial_number':<45} {'system_uuid':<40} {'hosting_type':<12} {'Diag'}")
    print("-" * 160)
    for r in results:
        serial = str(r.get("serial_number", ""))[:43]
        uuid = str(r.get("system_uuid", ""))[:38]
        hosting = str(r.get("hosting_type", ""))[:10]
        diag_count = len(r.get("diagnostics", []))
        diag_str = f"{diag_count} diag(s)" if diag_count > 0 else "none"
        print(f"{r['label']:<25} {str(r.get('status','?')):<10} {serial:<45} {uuid:<40} {hosting:<12} {diag_str}")

    print()
    print("=" * 100)
    print("BAREMETAL PAIR COMPARISON (OS 10.100.64.96 ↔ Redfish 10.100.15.34)")
    print("=" * 100)
    bm = next((r for r in results if r["label"] == "Baremetal-with-become"), None)
    rf = next((r for r in results if r["label"] == "Redfish-R760"), None)
    if bm and rf:
        print(f"  OS serial:      {bm.get('serial_number')}")
        print(f"  Redfish serial: {rf.get('serial_number')}")
        print(f"  OS UUID:        {bm.get('system_uuid')}")
        print(f"  Redfish UUID:   {rf.get('system_uuid')}")
        os_uuid = str(bm.get("system_uuid", "")).lower().replace("-", "")
        rf_uuid = str(rf.get("system_uuid", "")).lower().replace("-", "")
        print(f"  UUID match:     {os_uuid == rf_uuid if os_uuid and rf_uuid else 'cannot compare'}")
    else:
        print("  (one or both results missing)")

    # Save results JSON
    try:
        results_json = json.dumps(results, indent=2, ensure_ascii=False, default=str)
        cmd = f"cat > {OUTPUT_DIR}/summary.json << 'JSONEOF'\n{results_json}\nJSONEOF"
        ssh_exec(client, cmd)
        print(f"\nResults saved to {ANSIBLE_HOST}:{OUTPUT_DIR}/summary.json")
    except Exception as e:
        print(f"Warning: could not save results: {e}")

    client.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
