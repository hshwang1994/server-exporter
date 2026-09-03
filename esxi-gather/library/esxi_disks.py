#!/usr/bin/python
# -*- coding: utf-8 -*-
# esxi-gather/library/esxi_disks.py
#
# ESXi 호스트 하드웨어/설정 수집 — vSphere API (pyvmomi).
#   - physical_disks (serial/wwn)   ← ScsiDisk
#   - controllers (storage HBA/RAID) ← hostBusAdapter + pciDevice vendor (2026-06-22 T1)
#   - listening_ports (str[])        ← firewall.ruleset enabled inbound (2026-06-22 T1)
#   - host_info (식별/네트워크/CPU)   ← dnsConfig / ipRouteConfig / vnic / pnic / cpuInfo (2026-09-03)
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
# 2026-09-03 (OS/ESXi 전수 검수 후속) host_info 파트:
#   vmware_host_facts 가 주지 않는 값만 담는다 —
#     - dnsConfig.hostName / domainName       → system.hostname / system.fqdn (B-03)
#     - ipRouteConfig.defaultGateway(+vnic)   → network.default_gateways / interfaces[].is_primary (B-28)
#     - vnic ipV6Config                       → interfaces[].addresses (family=ipv6) (B-29)
#     - pnic + pciDevice vendorName/deviceName → adapters[].manufacturer / model (B-29)
#     - cpuInfo.hz                            → cpu.max_speed_mhz (정격, B-10)
#     - summary.quickStats.uptime             → system.uptime_seconds (B-32)
#   값이 없으면 키를 None 으로 둔다 (placeholder 금지).
#
# 의존: pyvmomi (ESXi 채널 표준 의존 — REQUIREMENTS pyvmomi 9.0.0).
#       rule 10 R2(stdlib-only)는 redfish_gather.py / precheck_bundle.py 한정 — 본 모듈 비대상.
#
# source: vSphere API HostScsiDisk / ScsiLun.alternateName (HostScsiLunDurableName),
#         HostNetworkInfo (dnsConfig / ipRouteConfig / vnic / pnic), HostHardwareInfo (cpuInfo / pciDevice)
#         https://developer.vmware.com/apis/vsphere-automation/latest/
#         (확인 2026-06-22 esxi01/02 실측, 2026-09-03 tests/reference/esxi/10_100_64_1/pyvmomi_host_dump.json 대조)

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


def _s(v):
    """문자열 정리 — 빈 문자열은 None."""
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _pick_host(view, hostname):
    """standalone ESXi 는 host 가 1개다. vCenter 경유 다중 host 면 접속 대상 이름과 같은 host 를 고른다."""
    hosts = list(view.view)
    if not hosts:
        return None
    for hs in hosts:
        if hostname and _s(getattr(hs, 'name', None)) == _s(hostname):
            return hs
    return hosts[0]


def _build_host_info(content, hostname=None):
    """식별 / 네트워크 / CPU 보강 — vmware_host_facts 가 제공하지 않는 값만 (2026-09-03)."""
    view = content.viewManager.CreateContainerView(content.rootFolder, [vim.HostSystem], True)
    try:
        hs = _pick_host(view, hostname)
        if hs is None:
            return {}
        info = {}
        cfg = getattr(hs, 'config', None)
        net = getattr(cfg, 'network', None) if cfg is not None else None
        hw = getattr(hs, 'hardware', None)

        # ── DNS 설정: 호스트 이름 / 도메인 (system.hostname / fqdn 의 정본) ──
        dns = getattr(net, 'dnsConfig', None) if net is not None else None
        info['hostname'] = _s(getattr(dns, 'hostName', None)) if dns is not None else None
        info['domain_name'] = _s(getattr(dns, 'domainName', None)) if dns is not None else None
        info['search_domain'] = [str(x) for x in (getattr(dns, 'searchDomain', None) or [])] if dns is not None else []
        info['dns_servers'] = [str(x) for x in (getattr(dns, 'address', None) or [])] if dns is not None else []

        # ── 기본 게이트웨이: 호스트 ipRouteConfig 우선, 없으면 vmk 별 ipRouteSpec ──
        gw = gw_dev = gw6 = None
        rc = getattr(net, 'ipRouteConfig', None) if net is not None else None
        if rc is not None:
            gw = _s(getattr(rc, 'defaultGateway', None))
            gw_dev = _s(getattr(rc, 'gatewayDevice', None))
            gw6 = _s(getattr(rc, 'ipV6DefaultGateway', None))

        vnics = []
        for v in ((getattr(net, 'vnic', None) or []) if net is not None else []):
            spec = getattr(v, 'spec', None)
            ip = getattr(spec, 'ip', None) if spec is not None else None
            v6 = []
            cfg6 = getattr(ip, 'ipV6Config', None) if ip is not None else None
            for a in ((getattr(cfg6, 'ipV6Address', None) or []) if cfg6 is not None else []):
                v6.append({
                    'address': _s(getattr(a, 'ipAddress', None)),
                    'prefix_length': getattr(a, 'prefixLength', None),
                    'origin': _s(getattr(a, 'origin', None)),
                })
            rs = getattr(spec, 'ipRouteSpec', None) if spec is not None else None
            vrc = getattr(rs, 'ipRouteConfig', None) if rs is not None else None
            vgw = _s(getattr(vrc, 'defaultGateway', None)) if vrc is not None else None
            vgw6 = _s(getattr(vrc, 'ipV6DefaultGateway', None)) if vrc is not None else None
            dev = _s(getattr(v, 'device', None))
            if gw is None and vgw:
                gw = vgw
                gw_dev = gw_dev or dev
            if gw6 is None and vgw6:
                gw6 = vgw6
            vnics.append({
                'device': dev,
                'mac': _s(getattr(spec, 'mac', None)) if spec is not None else None,
                'mtu': getattr(spec, 'mtu', None) if spec is not None else None,
                'ipv4': _s(getattr(ip, 'ipAddress', None)) if ip is not None else None,
                'subnet_mask': _s(getattr(ip, 'subnetMask', None)) if ip is not None else None,
                'dhcp': getattr(ip, 'dhcp', None) if ip is not None else None,
                'ipv6': v6,
                'portgroup': _s(getattr(v, 'portgroup', None)),
                'gateway': vgw,
            })
        info['default_gateway'] = gw
        info['gateway_device'] = gw_dev
        info['default_gateway_ipv6'] = gw6
        info['vnics'] = vnics

        # ── 물리 NIC + PCI 장치 제조사/모델 ──
        pci_map = {}
        try:
            for pd in ((getattr(hw, 'pciDevice', None) or []) if hw is not None else []):
                pid = _s(getattr(pd, 'id', None))
                if pid:
                    pci_map[pid] = (_s(getattr(pd, 'vendorName', None)), _s(getattr(pd, 'deviceName', None)))
        except Exception:
            pass
        pnics = []
        for p in ((getattr(net, 'pnic', None) or []) if net is not None else []):
            ls = getattr(p, 'linkSpeed', None)   # None = link down
            pci = _s(getattr(p, 'pci', None))
            vend, dev_name = pci_map.get(pci, (None, None))
            pnics.append({
                'device': _s(getattr(p, 'device', None)),
                'mac': _s(getattr(p, 'mac', None)),
                'driver': _s(getattr(p, 'driver', None)),
                'pci': pci,
                'manufacturer': vend,
                'model': dev_name,
                'speed_mbps': getattr(ls, 'speedMb', None) if ls is not None else None,
                'duplex': getattr(ls, 'duplex', None) if ls is not None else None,
                'link_up': ls is not None,
            })
        info['pnics'] = pnics

        # ── CPU: 정격 클럭(hz) / 제조사 ──
        ci = getattr(hw, 'cpuInfo', None) if hw is not None else None
        hz = getattr(ci, 'hz', None) if ci is not None else None
        info['cpu_mhz'] = int(int(hz) // 1000000) if hz else None
        info['cpu_packages'] = getattr(ci, 'numCpuPackages', None) if ci is not None else None
        info['cpu_cores'] = getattr(ci, 'numCpuCores', None) if ci is not None else None
        info['cpu_threads'] = getattr(ci, 'numCpuThreads', None) if ci is not None else None
        pk = list((getattr(hw, 'cpuPkg', None) or []) if hw is not None else [])
        info['cpu_vendor'] = _s(getattr(pk[0], 'vendor', None)) if pk else None
        info['cpu_description'] = _s(getattr(pk[0], 'description', None)) if pk else None

        # ── uptime / BIOS / 시스템 식별자 ──
        qs = getattr(getattr(hs, 'summary', None), 'quickStats', None)
        up = getattr(qs, 'uptime', None) if qs is not None else None
        info['uptime_seconds'] = int(up) if up is not None else None
        bi = getattr(hw, 'biosInfo', None) if hw is not None else None
        rd = getattr(bi, 'releaseDate', None) if bi is not None else None
        info['bios_version'] = _s(getattr(bi, 'biosVersion', None)) if bi is not None else None
        try:
            info['bios_date'] = rd.strftime('%Y-%m-%d') if rd is not None else None
        except Exception:
            info['bios_date'] = _s(rd)
        si = getattr(hw, 'systemInfo', None) if hw is not None else None
        info['system_uuid'] = _s(getattr(si, 'uuid', None)) if si is not None else None
        info['serial'] = _s(getattr(si, 'serialNumber', None)) if si is not None else None
        info['vendor'] = _s(getattr(si, 'vendor', None)) if si is not None else None
        info['model'] = _s(getattr(si, 'model', None)) if si is not None else None
        return info
    finally:
        view.Destroy()


def _safe_build(part, fn, content, part_errors, default=None):
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
        return [] if default is None else default


def main():
    module = AnsibleModule(
        argument_spec=dict(
            hostname=dict(type='str', required=True),
            username=dict(type='str', required=True),
            password=dict(type='str', required=True, no_log=True),
            port=dict(type='int', default=443),
            validate_certs=dict(type='bool', default=False),
            # 2026-09-03: vCenter 경유 다중 host 에서 host_info 대상 host 를 고르는 이름 (선택).
            esxi_hostname=dict(type='str', required=False, default=None),
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
    disks, controllers, listening_ports, host_info = [], [], [], {}

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
            host_info = _safe_build('host_info',
                                    lambda c: _build_host_info(c, p.get('esxi_hostname')),
                                    content, part_errors, default={})

        result = dict(
            changed=False,
            physical_disks=disks, disk_count=len(disks),
            controllers=controllers, listening_ports=listening_ports,
            host_info=host_info,
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
