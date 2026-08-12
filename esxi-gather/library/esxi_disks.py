#!/usr/bin/python
# -*- coding: utf-8 -*-
# esxi-gather/library/esxi_disks.py
#
# ESXi 호스트 하드웨어/설정 수집 — vSphere API (pyvmomi).
#   - physical_disks (serial/wwn)   ← ScsiDisk
#   - controllers (storage HBA/RAID) ← hostBusAdapter + pciDevice vendor (2026-06-22 T1)
#   - listening_ports (str[])        ← firewall.ruleset enabled inbound (2026-06-22 T1)
#
# (구) 물리 디스크 전용 → 호스트 정보 수집기로 확장. 연결 1회 재사용.
#
# 배경: community.vmware.vmware_host_disk_info 는 canonical_name + size 만 반환 →
#       serial / vendor / model / ssd 부재. 본 모듈은
#       storageSystem.storageDeviceInfo.scsiLun(ScsiDisk) 에서
#         - canonicalName  → wwn (naa.*)   + id/device
#         - alternateName[namespace=SERIALNUM] → serial (ASCII 디코딩)
#         - vendor/model/ssd/capacity
#       를 OS/Redfish 와 동일 canonical physical_disks 스키마로 정규화한다.
#
# 의존: pyvmomi (ESXi 채널 표준 의존 — REQUIREMENTS pyvmomi 9.0.0).
#       rule 10 R2(stdlib-only)는 redfish_gather.py / precheck_bundle.py 한정 — 본 모듈 비대상.
#
# source: vSphere API HostScsiDisk / ScsiLun.alternateName (HostScsiLunDurableName)
#         https://developer.vmware.com/apis/vsphere-automation/latest/  (확인 2026-06-22, esxi01/02 실측)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import ssl
import traceback

from ansible.module_utils.basic import AnsibleModule

PYVMOMI_IMP_ERR = None
try:
    from pyVim.connect import SmartConnect, Disconnect
    from pyVmomi import vim
    HAS_PYVMOMI = True
except ImportError:
    HAS_PYVMOMI = False
    PYVMOMI_IMP_ERR = traceback.format_exc()


def _decode_serial(lun):
    """alternateName namespace=SERIALNUM 의 data(부호 byte)를 ASCII 로 디코딩. 없으면 serialNumber."""
    for an in (getattr(lun, 'alternateName', None) or []):
        if getattr(an, 'namespace', None) == 'SERIALNUM':
            b = [x & 0xff for x in an.data]
            s = ''.join(chr(x) for x in b if 32 <= x <= 126).strip()
            if s:
                return s
    sn = getattr(lun, 'serialNumber', None)
    if sn and str(sn).strip().lower() not in ('unavailable', ''):
        return str(sn).strip()
    return None


def _build_disks(content):
    out = []
    view = content.viewManager.CreateContainerView(content.rootFolder, [vim.HostSystem], True)
    try:
        for hs in view.view:
            ss = hs.configManager.storageSystem
            if ss is None or ss.storageDeviceInfo is None:
                continue
            for lun in (ss.storageDeviceInfo.scsiLun or []):
                if not isinstance(lun, vim.host.ScsiDisk):
                    continue
                cn = getattr(lun, 'canonicalName', None)
                cap = getattr(lun, 'capacity', None)
                total_mb = int((cap.block * cap.blockSize) / 1048576) if cap else None
                wwn = cn if (cn and str(cn).startswith('naa.')) else None
                model = (getattr(lun, 'model', '') or '').strip() or None
                vendor = (getattr(lun, 'vendor', '') or '').strip() or None
                ssd = getattr(lun, 'ssd', None)
                full_model = (vendor + ' ' + model).strip() if (vendor and model) else (model or None)
                out.append({
                    'id': cn,
                    'device': cn,
                    'model': full_model,
                    'serial': _decode_serial(lun),
                    'wwn': wwn,
                    'total_mb': total_mb,
                    'media_type': ('SSD' if ssd else 'HDD') if ssd is not None else None,
                    'protocol': None,
                    'health': None,
                })
    finally:
        view.Destroy()
    # canonicalName 기준 정렬(결정적 출력)
    return sorted(out, key=lambda d: d.get('id') or '')


def _build_controllers(content):
    """storage HBA/RAID 컨트롤러 — hostBusAdapter + pciDevice vendor 보강."""
    out = []
    view = content.viewManager.CreateContainerView(content.rootFolder, [vim.HostSystem], True)
    try:
        for hs in view.view:
            # pci(addr) → vendorName 맵
            pci_vendor = {}
            try:
                for pd in (hs.hardware.pciDevice or []):
                    if getattr(pd, 'id', None):
                        pci_vendor[pd.id] = (getattr(pd, 'vendorName', '') or '').strip() or None
            except Exception:
                pass
            sd = getattr(hs.config, 'storageDevice', None)
            if sd is None:
                continue
            for hba in (sd.hostBusAdapter or []):
                model = (getattr(hba, 'model', '') or '').strip() or None
                pci = getattr(hba, 'pci', None)
                # type: BlockHba/FibreChannelHba/SerialAttachedHba → SATA/FC/SAS
                tname = type(hba).__name__
                ctype = ('SATA' if 'BlockHba' in tname
                         else 'FC' if 'FibreChannel' in tname
                         else 'SAS' if 'SerialAttached' in tname
                         else 'iSCSI' if 'InternetScsi' in tname
                         else None)
                out.append({
                    'id': getattr(hba, 'device', None),
                    'name': model,
                    'controller_model': model,
                    'controller_manufacturer': pci_vendor.get(pci),
                    'driver': getattr(hba, 'driver', None),
                    'controller_type': ctype,
                    'pci': pci,
                    'health': None,
                    'drives': [],
                })
    finally:
        view.Destroy()
    return sorted(out, key=lambda c: c.get('id') or '')


def _build_listening_ports(content):
    """firewall.ruleset enabled inbound 포트 → str[] (OS 채널 system.runtime.listening_ports 계약과 동일)."""
    ports = set()
    view = content.viewManager.CreateContainerView(content.rootFolder, [vim.HostSystem], True)
    try:
        for hs in view.view:
            fw = getattr(hs.config, 'firewall', None)
            if fw is None:
                continue
            for rs in (fw.ruleset or []):
                if not getattr(rs, 'enabled', False):
                    continue
                for rule in (rs.rule or []):
                    if getattr(rule, 'direction', None) != 'inbound':
                        continue
                    p = getattr(rule, 'port', None)
                    if p:
                        ports.add(int(p))
                    pr = getattr(rule, 'portRange', None)
                    if pr is not None and getattr(pr, 'start', None):
                        ports.add(int(pr.start))
    finally:
        view.Destroy()
    return [str(p) for p in sorted(ports)]


def _safe_build(part, fn, content, part_errors):
    """빌더 하나의 실패가 나머지 파트까지 삼키지 않게 격리한다.

    2026-08-12 (N36): 종전에는 main() 의 단일 try 가 세 빌더를 모두 감싸고 있어서
    listening_ports 하나가 죽으면 이미 만들어 둔 physical_disks / controllers 까지
    통째로 빈 list 로 반환됐고, 호출자는 '연결 실패' 와 '일부 파트 실패' 를 구분할 수
    없었다. 파트 이름을 키로 사유를 모아 두면 태스크가 어느 섹션의 errors 로 올릴지
    결정할 수 있다.
    """
    try:
        return fn(content)
    except Exception as e:
        part_errors[part] = str(e)
        return []


def main():
    module = AnsibleModule(
        argument_spec=dict(
            hostname=dict(type='str', required=True),
            username=dict(type='str', required=True),
            password=dict(type='str', required=True, no_log=True),
            port=dict(type='int', default=443),
            validate_certs=dict(type='bool', default=False),
        ),
        supports_check_mode=True,
    )
    if not HAS_PYVMOMI:
        module.fail_json(msg='pyvmomi (pyVim/pyVmomi) 미설치', exception=PYVMOMI_IMP_ERR)

    p = module.params
    ctx = None if p['validate_certs'] else ssl._create_unverified_context()

    si = None
    # 파트 이름 → 실패 사유. 'connect' 는 접속/ServiceContent 단계 실패를 뜻한다.
    part_errors = {}
    connect_ok = False
    content = None
    disks, controllers, listening_ports = [], [], []

    try:
        try:
            si = SmartConnect(host=p['hostname'], user=p['username'], pwd=p['password'],
                              port=p['port'], sslContext=ctx)
            content = si.RetrieveContent()
            connect_ok = True
        except Exception as e:
            # 수집 실패는 graceful — 빈 list + error (호출 task 가 failed_when:false 로 흡수, rule 27 R4)
            part_errors['connect'] = str(e)

        if connect_ok:
            disks = _safe_build('physical_disks', _build_disks, content, part_errors)
            controllers = _safe_build('controllers', _build_controllers, content, part_errors)
            listening_ports = _safe_build('listening_ports', _build_listening_ports,
                                          content, part_errors)

        result = dict(
            changed=False,
            physical_disks=disks, disk_count=len(disks),
            controllers=controllers, listening_ports=listening_ports,
            # 2026-08-12 (N36): 아래 3키는 **추가만** 한 것이다 (기존 키 삭제/리네임 없음).
            #   호출 task(collect_disks.yml)가 어느 섹션의 errors 로 올릴지 정하는 근거다.
            #   connect_ok   : 접속 자체가 됐는지 (false 면 세 파트 모두 미수집)
            #   failed_parts : 실패한 파트 이름 목록 (정렬 — 출력 결정성)
            #   part_errors  : 파트 → 사유. 사용자 문장이 아니라 errors[].detail 근거다.
            connect_ok=connect_ok,
            failed_parts=sorted(part_errors.keys()),
            part_errors=part_errors,
        )
        if part_errors:
            # 기존 계약 유지: 'error' 키의 존재 자체가 "무언가 실패" 신호다
            # (collect_disks.yml 의 _e_disks_ok 판정식이 이 키를 본다).
            result['error'] = part_errors.get('connect') or '; '.join(
                '%s: %s' % (k, v) for k, v in sorted(part_errors.items()))
        module.exit_json(**result)
    finally:
        if si is not None:
            try:
                Disconnect(si)
            except Exception:
                pass


if __name__ == '__main__':
    main()
