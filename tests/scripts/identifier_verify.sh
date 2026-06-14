#!/bin/bash
# Round 13: Identifier Collection Verification — DMI direct-read fallback
# 대상: Ubuntu VM (no-become/with-become), RHEL VM, Baremetal (no-become/with-become),
#       Windows VM, ESXi, Redfish (Dell R760 BMC)
#
# 실행: Jenkins agent 또는 Ansible 설치된 Linux 호스트에서
#   cd /home/cloviradmin/server-exporter
#   bash tests/scripts/identifier_verify.sh
set -euo pipefail

# production-audit (2026-04-29): 자격증명 환경변수 강제 — 하드코딩된 password를
# git history에 남기지 않고, 자격증명 누락 시 silent fail-open 차단.
: "${SE_LINUX_USER:?SE_LINUX_USER 환경변수 누락 (예: cloviradmin)}"
: "${SE_LINUX_PASSWORD:?SE_LINUX_PASSWORD 환경변수 누락}"
: "${SE_LINUX_BECOME_PASSWORD:=$SE_LINUX_PASSWORD}"
: "${SE_WINDOWS_USER:?SE_WINDOWS_USER 환경변수 누락 (예: gooddit)}"
: "${SE_WINDOWS_PASSWORD:?SE_WINDOWS_PASSWORD 환경변수 누락}"
: "${SE_ESXI_USER:?SE_ESXI_USER 환경변수 누락 (예: root)}"
: "${SE_ESXI_PASSWORD:?SE_ESXI_PASSWORD 환경변수 누락}"

PROJECT_DIR="${PROJECT_DIR:-$(pwd)}"
OUTPUT_DIR="/tmp/round13_identifier"
rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"

cd "$PROJECT_DIR"
export REPO_ROOT="$PROJECT_DIR"
export ANSIBLE_STDOUT_CALLBACK=json_only
export ANSIBLE_CONFIG="$PROJECT_DIR/ansible.cfg"

echo "=== Round 13: Identifier Collection Verification ==="
echo "Timestamp: $(date -Iseconds)"
echo "REPO_ROOT: $REPO_ROOT"
echo ""

# Helper: Extract identifier fields from JSON output
extract_ids() {
  local logfile="$1"
  local label="$2"
  # json_only callback wraps output in OUTPUT task — extract the msg JSON
  python3 -c "
import json, sys, re

with open('$logfile', 'r') as f:
    content = f.read()

# Find JSON in OUTPUT task msg
pattern = r'\"msg\"\s*:\s*\"(\{.*?\})\"'
matches = re.findall(pattern, content, re.DOTALL)
if not matches:
    # Try direct JSON parse of last line
    for line in reversed(content.strip().split('\n')):
        line = line.strip()
        if line.startswith('{'):
            try:
                d = json.loads(line)
                if 'data' in d or 'status' in d:
                    matches = [line]
                    break
            except:
                pass

if not matches:
    print(f'$label: NO OUTPUT JSON FOUND')
    sys.exit(0)

# Parse the JSON (may need unescape)
raw = matches[-1]
try:
    data = json.loads(raw)
except:
    data = json.loads(raw.replace('\\\\\"','\"'))

system = data.get('data',{}).get('system',{})
errors = data.get('errors',[])
corr   = data.get('correlation',{})
status = data.get('status','?')

print(f'$label:')
print(f'  status:        {status}')
print(f'  serial_number: {system.get(\"serial_number\", \"MISSING_FIELD\")}')
print(f'  system_uuid:   {system.get(\"system_uuid\", \"MISSING_FIELD\")}')
print(f'  hosting_type:  {system.get(\"hosting_type\", \"MISSING_FIELD\")}')
print(f'  corr.serial:   {corr.get(\"serial_number\", \"MISSING_FIELD\")}')
print(f'  corr.uuid:     {corr.get(\"system_uuid\", \"MISSING_FIELD\")}')
if errors:
    for e in errors:
        if 'serial' in str(e) or 'uuid' in str(e) or 'identifier' in str(e).lower():
            print(f'  diag: {e.get(\"message\",\"\")}')
print()
" 2>&1 || echo "$label: PARSE ERROR"
}

# ═══════════════════════════════════════════════════════════════
# 1. Ubuntu VM — no become (DMI fallback will fail without sudo password)
# ═══════════════════════════════════════════════════════════════
echo "--- [1/7] Ubuntu 10.100.64.166 (no become) ---"
REPO_ROOT="$PROJECT_DIR" \
  ansible-playbook os-gather/site.yml \
  -i "10.100.64.166," \
  -e ansible_user="$SE_LINUX_USER" \
  -e ansible_password="$SE_LINUX_PASSWORD" \
  2>&1 | tee "$OUTPUT_DIR/ubuntu_no_become.log" || true
extract_ids "$OUTPUT_DIR/ubuntu_no_become.log" "Ubuntu-no-become"

# ═══════════════════════════════════════════════════════════════
# 2. Ubuntu VM — with become (DMI fallback should succeed)
# ═══════════════════════════════════════════════════════════════
echo "--- [2/7] Ubuntu 10.100.64.166 (with become) ---"
REPO_ROOT="$PROJECT_DIR" \
  ansible-playbook os-gather/site.yml \
  -i "10.100.64.166," \
  -e ansible_user="$SE_LINUX_USER" \
  -e ansible_password="$SE_LINUX_PASSWORD" \
  -e ansible_become_password="$SE_LINUX_BECOME_PASSWORD" \
  2>&1 | tee "$OUTPUT_DIR/ubuntu_with_become.log" || true
extract_ids "$OUTPUT_DIR/ubuntu_with_become.log" "Ubuntu-with-become"

# ═══════════════════════════════════════════════════════════════
# 3. RHEL VM — no become
# ═══════════════════════════════════════════════════════════════
echo "--- [3/7] RHEL 10.100.64.197 (no become) ---"
REPO_ROOT="$PROJECT_DIR" \
  ansible-playbook os-gather/site.yml \
  -i "10.100.64.197," \
  -e ansible_user="$SE_LINUX_USER" \
  -e ansible_password="$SE_LINUX_PASSWORD" \
  2>&1 | tee "$OUTPUT_DIR/rhel_no_become.log" || true
extract_ids "$OUTPUT_DIR/rhel_no_become.log" "RHEL-no-become"

# ═══════════════════════════════════════════════════════════════
# 4. Baremetal — no become
# ═══════════════════════════════════════════════════════════════
echo "--- [4/7] Baremetal 10.100.64.96 (no become) ---"
REPO_ROOT="$PROJECT_DIR" \
  ansible-playbook os-gather/site.yml \
  -i "10.100.64.96," \
  -e ansible_user="$SE_LINUX_USER" \
  -e ansible_password="$SE_LINUX_PASSWORD" \
  2>&1 | tee "$OUTPUT_DIR/baremetal_no_become.log" || true
extract_ids "$OUTPUT_DIR/baremetal_no_become.log" "Baremetal-no-become"

# ═══════════════════════════════════════════════════════════════
# 5. Baremetal — with become
# ═══════════════════════════════════════════════════════════════
echo "--- [5/7] Baremetal 10.100.64.96 (with become) ---"
REPO_ROOT="$PROJECT_DIR" \
  ansible-playbook os-gather/site.yml \
  -i "10.100.64.96," \
  -e ansible_user="$SE_LINUX_USER" \
  -e ansible_password="$SE_LINUX_PASSWORD" \
  -e ansible_become_password="$SE_LINUX_BECOME_PASSWORD" \
  2>&1 | tee "$OUTPUT_DIR/baremetal_with_become.log" || true
extract_ids "$OUTPUT_DIR/baremetal_with_become.log" "Baremetal-with-become"

# ═══════════════════════════════════════════════════════════════
# 6. Windows VM
# ═══════════════════════════════════════════════════════════════
echo "--- [6/7] Windows 10.100.64.120 ---"
REPO_ROOT="$PROJECT_DIR" \
  ansible-playbook os-gather/site.yml \
  -i "10.100.64.120," \
  -e ansible_user="$SE_WINDOWS_USER" \
  -e ansible_password="$SE_WINDOWS_PASSWORD" \
  2>&1 | tee "$OUTPUT_DIR/windows.log" || true
extract_ids "$OUTPUT_DIR/windows.log" "Windows"

# ═══════════════════════════════════════════════════════════════
# 7a. ESXi
# ═══════════════════════════════════════════════════════════════
echo "--- [7a/7] ESXi 10.100.64.2 ---"
REPO_ROOT="$PROJECT_DIR" \
  ansible-playbook esxi-gather/site.yml \
  -i "10.100.64.2," \
  -e ansible_user="$SE_ESXI_USER" \
  -e ansible_password="$SE_ESXI_PASSWORD" \
  2>&1 | tee "$OUTPUT_DIR/esxi.log" || true
extract_ids "$OUTPUT_DIR/esxi.log" "ESXi"

# ═══════════════════════════════════════════════════════════════
# 7b. Redfish — Dell R760 BMC (entity linking pair)
# ═══════════════════════════════════════════════════════════════
echo "--- [7b/7] Redfish Dell R760 BMC 10.100.15.34 ---"
REPO_ROOT="$PROJECT_DIR" \
  ansible-playbook redfish-gather/site.yml \
  -i "10.100.15.34," \
  2>&1 | tee "$OUTPUT_DIR/redfish_r760.log" || true
extract_ids "$OUTPUT_DIR/redfish_r760.log" "Redfish-R760"

# ═══════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════
echo ""
echo "================================================================"
echo "Evidence files:"
ls -la "$OUTPUT_DIR/"
echo ""
echo "================================================================"
echo "Quick diff — Baremetal no-become vs with-become:"
diff <(grep -E 'serial|uuid' "$OUTPUT_DIR/baremetal_no_become.log" | head -5) \
     <(grep -E 'serial|uuid' "$OUTPUT_DIR/baremetal_with_become.log" | head -5) || true
echo ""
echo "Quick diff — Ubuntu no-become vs with-become:"
diff <(grep -E 'serial|uuid' "$OUTPUT_DIR/ubuntu_no_become.log" | head -5) \
     <(grep -E 'serial|uuid' "$OUTPUT_DIR/ubuntu_with_become.log" | head -5) || true
echo "================================================================"
echo "Done. Review logs in $OUTPUT_DIR/"
