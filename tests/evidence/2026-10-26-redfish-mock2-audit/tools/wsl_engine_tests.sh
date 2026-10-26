#!/bin/bash
cd /mnt/c/github/ClovirONE/clovirone-server-gathering || exit 1
export ANSIBLE_CONFIG=/mnt/c/github/ClovirONE/clovirone-server-gathering/ansible.cfg
export PYTHONUTF8=1
if ! python3 -m pytest --version >/dev/null 2>&1; then echo "PYTEST_MISSING_IN_WSL"; python3 -m pytest --version 2>&1 | head -2; exit 3; fi
python3 -m pytest --version
python3 -m pytest tests/integration/test_build_output_no_data_playbook.py tests/integration/test_addon_hook_playbook.py -q -p no:cacheprovider -m "not live" 2>&1 | tail -15
echo "rc=${PIPESTATUS[0]}"
