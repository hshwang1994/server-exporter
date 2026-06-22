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
    try:
        si = SmartConnect(host=p['hostname'], user=p['username'], pwd=p['password'],
                          port=p['port'], sslContext=ctx)
        content = si.RetrieveContent()
        disks = _build_disks(content)
        controllers = _build_controllers(content)
        listening_ports = _build_listening_ports(content)
        module.exit_json(changed=False, physical_disks=disks, disk_count=len(disks),
                         controllers=controllers, listening_ports=listening_ports)
    except Exception as e:
        # 수집 실패는 graceful — 빈 list + error (호출 task 가 failed_when:false 로 흡수, rule 27 R4)
        module.exit_json(changed=False, physical_disks=[], disk_count=0,
                         controllers=[], listening_ports=[], error=str(e))
    finally:
        if si is not None:
            try:
                Disconnect(si)
            except Exception:
                pass


if __name__ == '__main__':
    main()
