#!/bin/bash
# Round 9: OS/ESXi contract verification — live output 수집
# 대상: Ubuntu, Windows, ESXi, RHEL(보조)
#
# production-audit (2026-04-29):
#   - 자격증명 하드코딩 제거 → 환경변수에서 읽음
#   - 자격증명이 set되지 않으면 즉시 종료 (silent fail-open 차단)
#   - 사용 예:
#       export SE_LINUX_USER=cloviradmin SE_LINUX_PASSWORD='...'
#       export SE_WINDOWS_USER=gooddit  SE_WINDOWS_PASSWORD='...'
#       export SE_ESXI_USER=root        SE_ESXI_PASSWORD='...'
#       bash tests/scripts/os_esxi_verify.sh
set -euo pipefail

# 자격증명 검증 (필수)
: "${SE_LINUX_USER:?SE_LINUX_USER 환경변수 누락 (예: cloviradmin)}"
: "${SE_LINUX_PASSWORD:?SE_LINUX_PASSWORD 환경변수 누락}"
: "${SE_WINDOWS_USER:?SE_WINDOWS_USER 환경변수 누락 (예: gooddit)}"
: "${SE_WINDOWS_PASSWORD:?SE_WINDOWS_PASSWORD 환경변수 누락}"
: "${SE_ESXI_USER:?SE_ESXI_USER 환경변수 누락 (예: root)}"
: "${SE_ESXI_PASSWORD:?SE_ESXI_PASSWORD 환경변수 누락}"

PROJECT_DIR="${PROJECT_DIR:-/home/cloviradmin/server-exporter}"
OUTPUT_DIR="${OUTPUT_DIR:-/tmp/round9_evidence}"
mkdir -p "$OUTPUT_DIR"

cd "$PROJECT_DIR"

echo "=== Round 9: OS/ESXi Contract Verification ==="
echo "Timestamp: $(date -Iseconds)"
echo ""

# 1. Ubuntu (주 검증)
echo "--- Ubuntu 10.100.64.166 ---"
INVENTORY_JSON='[{"ip":"10.100.64.166"}]' \
  ansible-playbook os-gather/site.yml \
  -e ansible_user="$SE_LINUX_USER" \
  -e ansible_password="$SE_LINUX_PASSWORD" \
  -e '{"inventory_json": [{"ip":"10.100.64.166"}]}' \
  2>&1 | tee "$OUTPUT_DIR/ubuntu_run.log" || true

# Find the output JSON
UBUNTU_OUT=$(find /tmp -name "*.json" -newer "$OUTPUT_DIR/ubuntu_run.log" -path "*10.100.64.166*" 2>/dev/null | head -1)
if [ -z "$UBUNTU_OUT" ]; then
  # Try callback output directory
  UBUNTU_OUT=$(grep -o '/[^ ]*\.json' "$OUTPUT_DIR/ubuntu_run.log" | tail -1)
fi
echo "Ubuntu output: $UBUNTU_OUT"
[ -n "$UBUNTU_OUT" ] && [ -f "$UBUNTU_OUT" ] && cp "$UBUNTU_OUT" "$OUTPUT_DIR/ubuntu_output.json"

# 2. Windows (주 검증)
echo ""
echo "--- Windows 10.100.64.120 ---"
INVENTORY_JSON='[{"ip":"10.100.64.120"}]' \
  ansible-playbook os-gather/site.yml \
  -e ansible_user="$SE_WINDOWS_USER" \
  -e ansible_password="$SE_WINDOWS_PASSWORD" \
  -e ansible_connection=winrm \
  -e ansible_winrm_server_cert_validation=ignore \
  -e ansible_port=5985 \
  -e '{"inventory_json": [{"ip":"10.100.64.120"}]}' \
  2>&1 | tee "$OUTPUT_DIR/windows_run.log" || true

WINDOWS_OUT=$(grep -o '/[^ ]*\.json' "$OUTPUT_DIR/windows_run.log" | tail -1)
echo "Windows output: $WINDOWS_OUT"
[ -n "$WINDOWS_OUT" ] && [ -f "$WINDOWS_OUT" ] && cp "$WINDOWS_OUT" "$OUTPUT_DIR/windows_output.json"

# 3. ESXi (주 검증)
echo ""
echo "--- ESXi 10.100.64.2 ---"
INVENTORY_JSON='[{"ip":"10.100.64.2"}]' \
  ansible-playbook esxi-gather/site.yml \
  -e ansible_user="$SE_ESXI_USER" \
  -e ansible_password="$SE_ESXI_PASSWORD" \
  -e '{"inventory_json": [{"ip":"10.100.64.2"}]}' \
  2>&1 | tee "$OUTPUT_DIR/esxi_run.log" || true

ESXI_OUT=$(grep -o '/[^ ]*\.json' "$OUTPUT_DIR/esxi_run.log" | tail -1)
echo "ESXi output: $ESXI_OUT"
[ -n "$ESXI_OUT" ] && [ -f "$ESXI_OUT" ] && cp "$ESXI_OUT" "$OUTPUT_DIR/esxi_output.json"

# 4. RHEL (보조 — 제한 상태 확인만)
echo ""
echo "--- RHEL 10.100.64.197 (보조 확인) ---"
echo "SSH connectivity:"
ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$SE_LINUX_USER@10.100.64.197" 'echo SSH_OK; python3 --version 2>&1; which python3 2>&1' 2>&1 || echo "SSH_FAILED"

echo ""
echo "Ansible gather attempt:"
INVENTORY_JSON='[{"ip":"10.100.64.197"}]' \
  ansible-playbook os-gather/site.yml \
  -e ansible_user="$SE_LINUX_USER" \
  -e ansible_password="$SE_LINUX_PASSWORD" \
  -e '{"inventory_json": [{"ip":"10.100.64.197"}]}' \
  2>&1 | tee "$OUTPUT_DIR/rhel_run.log" || true

echo ""
echo "=== Evidence files ==="
ls -la "$OUTPUT_DIR/"
