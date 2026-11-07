set -u
V=$HOME/venv-se-ci-20261028
# 이 세션이 방금 만든 실패 잔재(pip 없음)만 지운다
if [ -e "$V" ]; then
  if [ ! -e "$V/bin/pip" ] && [ -f "$V/pyvenv.cfg" ]; then rm -rf "$V"; else echo "exists: $V"; exit 3; fi
fi
# python3.12-venv(ensurepip) 미설치 → pip 없이 만든 뒤 시스템 pip 24.0 의 --python 으로 venv 에 pip 를 넣는다(시스템 패키지 설치 0)
python3.12 -m venv --without-pip "$V" || exit 1
python3.12 -m pip --python "$V/bin/python" install -q --upgrade pip || exit 1
"$V/bin/pip" install -q -r /mnt/c/github/ClovirONE/clovirone-server-gathering/requirements-test.txt 'ansible-core==2.20.3' pywinrm pyvmomi || exit 1
# collection 은 venv site-packages 에 둔다 — 사용자 ~/.ansible/collections 를 건드리지 않고 ANSIBLE_* 환경변수도 쓰지 않는다(sys.path 스캔 기본 켜짐)
"$V/bin/ansible-galaxy" collection install community.vmware ansible.windows -p "$V/lib/python3.12/site-packages" || exit 1
"$V/bin/python" --version
"$V/bin/ansible" --version | head -3
"$V/bin/ansible-galaxy" collection list 2>/dev/null | grep -E 'community.vmware|ansible.windows'
"$V/bin/pip" freeze | grep -iE "^(ansible-core|pytest|pywinrm|pyvmomi|paramiko|requests|pip)=="
grep include-system-site-packages "$V/pyvenv.cfg"
echo VENV_DONE
