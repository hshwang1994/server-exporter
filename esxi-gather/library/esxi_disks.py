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
# 2026-10-03 (C8) 수집 대상 HostSystem 은 실행당 1개:
#   종전에는 디스크 / 컨트롤러 / 방화벽 파트가 ContainerView 의 **모든** HostSystem 을 합산했고
#   host_info 는 이름이 안 맞으면 hosts[0] 을 썼다. view 도 파트마다 따로 만들었다 (실행당 4회).
#   지금은 view 를 한 번 만들어 _select_host 로 host 1개를 고르고 네 파트가 그 host 만 읽는다.
#   고르지 못하면(0개 / 불일치 / 복수 일치) part_errors['host_select'] 로 알리고 네 파트는 비운다.
#   방화벽 규칙의 범위 끝은 pyVmomi 필드 endPort 로 읽는다 (종전에 읽던 portRange 는 없는 속성).
#   SmartConnect 는 설치된 pyVmomi 가 httpConnectionTimeout 을 받을 때만 모듈 timeout 을 넘긴다.
#
# 의존: pyvmomi (ESXi 채널 표준 의존 — REQUIREMENTS pyvmomi 9.0.0).
#       rule 10 R2(stdlib-only)는 redfish_gather.py / precheck_bundle.py 한정 — 본 모듈 비대상.
#
# source: vSphere API HostScsiDisk / ScsiLun.alternateName (HostScsiLunDurableName),
#         HostNetworkInfo (dnsConfig / ipRouteConfig / vnic / pnic), HostHardwareInfo (cpuInfo / pciDevice),
#         HostFirewallRule (port / endPort / direction / protocol)
#         https://developer.vmware.com/apis/vsphere-automation/latest/
#         (확인 2026-06-22 esxi01/02 실측, 2026-09-03 tests/reference/esxi/10_100_64_1/pyvmomi_host_dump.json 대조,
#          2026-10-03 같은 덤프의 firewall_rules[].rule[].endPort 대조 + pyVmomi 9.0.0.0 SmartConnect 시그니처)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import inspect
import socket
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

# vSphere 소켓 timeout 기본값(초) — ESXi precheck(_precheck_timeout) 과 같은 값.
_DEFAULT_TIMEOUT_SEC = 30

# 다중 host 선택에서 esxi_hostname 과 비교하는 식별자 (사유 문장에도 그대로 쓴다).
_SELECT_IDS = 'name / summary.config.name / vmk IPv4(config.network.vnic[].spec.ip.ipAddress)'


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


def _build_disks(target):
    hs = _as_target(target).host()
    if hs is None:
        return []
    out = []
    ss = hs.configManager.storageSystem
    if ss is None or ss.storageDeviceInfo is None:
        return []
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
    # canonicalName 기준 정렬(결정적 출력)
    return sorted(out, key=lambda d: d.get('id') or '')


def _build_controllers(target):
    """storage HBA/RAID 컨트롤러 — hostBusAdapter + pciDevice vendor 보강."""
    hs = _as_target(target).host()
    if hs is None:
        return []
    out = []
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
        return []
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
    return sorted(out, key=lambda c: c.get('id') or '')


def _range_end(rule, start):
    """HostFirewallRule.endPort 가 start 와 다른 범위 끝이면 그 값, 아니면 None.

    notices 전용 계산이라 값이 이상해도 포트 목록을 깨뜨리지 않는다 (예외 대신 None).
    """
    try:
        end = int(getattr(rule, 'endPort', None) or 0)
    except (TypeError, ValueError):
        return None
    return end if (end and end != start) else None


def _build_listening_ports(target):
    """firewall.ruleset enabled inbound 포트 → str[] (OS 채널 system.runtime.listening_ports 계약과 동일).

    범위 규칙(endPort != port)은 종전처럼 시작 포트 하나로 보고하고, 범위였다는 사실은
    notices 에 남긴다 (2026-10-03 C8 — 범위 전개 / UDP 제외는 값 계약 변경이라 별도 결정).
    """
    t = _as_target(target)
    hs = t.host()
    if hs is None:
        return []
    ports = set()
    fw = getattr(hs.config, 'firewall', None)
    if fw is None:
        return []
    for rs in (fw.ruleset or []):
        if not getattr(rs, 'enabled', False):
            continue
        for rule in (rs.rule or []):
            if getattr(rule, 'direction', None) != 'inbound':
                continue
            p = getattr(rule, 'port', None)
            if p:
                start = int(p)
                ports.add(start)
                end = _range_end(rule, start)
                if end is not None:
                    t.notice('system', 'port range %d-%d reported as %d (firewall ruleset %s, %s)'
                             % (start, end, start, _s(getattr(rs, 'key', None)),
                                _s(getattr(rule, 'protocol', None))))
    return [str(p) for p in sorted(ports)]


def _s(v):
    """문자열 정리 — 빈 문자열은 None."""
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _list_hosts(content):
    """ContainerView 로 HostSystem 목록을 얻는다 — 실행당 _Target.resolve 에서 한 번만 불린다.

    view 는 목록을 읽은 뒤 바로 파기한다. 목록 원소는 관리 객체 참조라 view 를 파기한 뒤에도
    속성 조회에 그대로 쓸 수 있다.
    """
    view = content.viewManager.CreateContainerView(content.rootFolder, [vim.HostSystem], True)
    try:
        return list(view.view or [])
    finally:
        view.Destroy()


def _host_identifiers(hs):
    """다중 host 선택에서 비교하는 식별자 — name / summary.config.name / vmk IPv4 (빈 값 제외)."""
    ids = [_s(getattr(hs, 'name', None))]
    summary_cfg = getattr(getattr(hs, 'summary', None), 'config', None)
    ids.append(_s(getattr(summary_cfg, 'name', None)) if summary_cfg is not None else None)
    cfg = getattr(hs, 'config', None)
    net = getattr(cfg, 'network', None) if cfg is not None else None
    for v in ((getattr(net, 'vnic', None) or []) if net is not None else []):
        spec = getattr(v, 'spec', None)
        ip = getattr(spec, 'ip', None) if spec is not None else None
        ids.append(_s(getattr(ip, 'ipAddress', None)) if ip is not None else None)
    return [i for i in ids if i]


def _select_host(hosts, esxi_hostname):
    """수집 대상 HostSystem 1개를 고른다 → (host, None) 또는 (None, 사유).

    - 1개 (standalone ESXi): 인자와 무관하게 그 host. 인자는 짧은 ansible_hostname 이거나 null 일 수
      있고 HostSystem.name 은 FQDN 이나 IP 일 수 있어 비교하지 않는다.
    - 2개 이상 (vCenter 경유): name / summary.config.name / vmk IPv4 중 하나가 인자와 정확히 같은
      (대소문자 무시) host 가 **정확히 1개**일 때만 고른다. 부분 일치·유사 일치는 하지 않는다.
    - 0개 / 인자 없음 / 일치 0개 / 일치 2개 이상: 고르지 않는다. hosts[0] 같은 추정은 다른 host 의
      데이터를 이 대상의 것으로 보고하게 만든다.
    """
    total = len(hosts)
    if total == 1:
        return hosts[0], None
    if total == 0:
        return None, 'HostSystem 0개 — 수집 대상 host 가 없습니다'
    want = _s(esxi_hostname)
    if want is None:
        return None, ('HostSystem %d개 — esxi_hostname 인자가 없어 수집 대상 host 를 고를 수 없습니다 '
                      '(비교 식별자: %s)' % (total, _SELECT_IDS))
    key = want.lower()
    matched = [hs for hs in hosts if key in [i.lower() for i in _host_identifiers(hs)]]
    if len(matched) == 1:
        return matched[0], None
    if not matched:
        return None, ('HostSystem %d개 중 esxi_hostname=%r 과 정확히 일치하는 host 가 없습니다 '
                      '(비교 식별자: %s, 대소문자 무시)' % (total, want, _SELECT_IDS))
    names = [_s(getattr(hs, 'name', None)) or '?' for hs in matched]
    shown = ', '.join(names[:5]) + (' 외 %d개' % (len(names) - 5) if len(names) > 5 else '')
    return None, ('HostSystem %d개 중 esxi_hostname=%r 과 일치하는 host 가 %d개입니다 (%s) — '
                  '임의로 고르지 않습니다 (비교 식별자: %s)' % (total, want, len(matched), shown, _SELECT_IDS))


class _Target(object):
    """이번 실행의 수집 대상 HostSystem 1개 + 비치명 notices — 네 파트가 같은 객체를 공유한다.

    resolve() 가 view 를 한 번만 만들어 _select_host 로 host 를 고른다 (두 번째 호출부터는 재사용).
      - select_error : 0개 / 불일치 / 복수 일치 사유. main() 이 part_errors['host_select'] 로 올린다.
      - 목록 / 식별자 조회의 예외는 담아 두었다가 host() 를 부른 파트마다 다시 던진다 — 종전처럼
        파트별 사유로 남아 collect_disks.yml 이 storage / system errors 로 올린다 (재시도는 없다).
    """

    def __init__(self, content, esxi_hostname=None):
        self.content = content
        self.esxi_hostname = esxi_hostname
        self.select_error = None
        self.notices = []
        self._host = None
        self._exc = None
        self._resolved = False

    def resolve(self):
        if not self._resolved:
            self._resolved = True
            try:
                self._host, self.select_error = _select_host(_list_hosts(self.content),
                                                             self.esxi_hostname)
            except Exception as e:
                self._exc = e
        return self

    def host(self):
        """고른 HostSystem (선택 실패면 None). 목록 조회가 실패했으면 그 예외를 다시 던진다."""
        self.resolve()
        if self._exc is not None:
            raise self._exc
        return self._host

    def notice(self, section, message):
        """수집은 됐지만 알아둘 사실 1건 (redfish_gather.py 의 notices 와 같은 모양). 중복은 담지 않는다."""
        entry = {'section': section, 'message': str(message)}
        if entry not in self.notices:
            self.notices.append(entry)


def _as_target(target, esxi_hostname=None):
    """빌더 입력 → _Target.

    main() 은 _Target 하나를 네 파트에 넘긴다 (view 1회 · host 1개 공유). ServiceContent 를 바로
    넘기는 종전 호출 형태는 그 자리에서 host 를 고른다 — 이때만 esxi_hostname 을 쓴다.
    """
    return target if isinstance(target, _Target) else _Target(target, esxi_hostname)


def _build_host_info(target, hostname=None):
    """식별 / 네트워크 / CPU 보강 — vmware_host_facts 가 제공하지 않는 값만 (2026-09-03).

    hostname 은 ServiceContent 를 바로 넘기는 종전 호출 형태에서만 쓰인다 (_as_target).
    """
    hs = _as_target(target, hostname).host()
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
    # vSphere summary.hardware.cpuMhz 와 같은 값이 되도록 반올림 (실측 hz=2194999xxx → 2195, 절삭하면 2194)
    info['cpu_mhz'] = int(round(int(hz) / 1000000.0)) if hz else None
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


def _safe_build(part, fn, target, part_errors, default=None):
    """빌더 하나의 실패가 나머지 파트까지 삼키지 않게 격리한다.

    2026-08-12 (N36): 종전에는 main() 의 단일 try 가 세 빌더를 모두 감싸고 있어서
    listening_ports 하나가 죽으면 이미 만들어 둔 physical_disks / controllers 까지
    통째로 빈 list 로 반환됐고, 호출자는 '연결 실패' 와 '일부 파트 실패' 를 구분할 수
    없었다. 파트 이름을 키로 사유를 모아 두면 태스크가 어느 섹션의 errors 로 올릴지
    결정할 수 있다.
    """
    try:
        return fn(target)
    except Exception as e:
        part_errors[part] = str(e)
        return [] if default is None else default


def _accepts_kwarg(fn, name):
    """fn 의 시그니처에 name 이 이름 있는 매개변수로 있는가. 확인할 수 없으면 False (종전 호출 유지).

    **kwargs 만 받는 구현은 그 이름을 실제로 쓰는지 알 수 없으므로 지원으로 보지 않는다.
    """
    signature = getattr(inspect, 'signature', None)   # Python 2 에는 없다
    if signature is None:
        return False
    try:
        param = signature(fn).parameters.get(name)
    except (TypeError, ValueError):
        return False
    return param is not None and param.kind in (param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY)


def _connect_kwargs(params, ssl_context):
    """SmartConnect 인자 — httpConnectionTimeout 은 설치된 pyVmomi 가 받을 때만 넣는다 (2026-10-03 C8).

    pyVmomi 9.0.0.0 의 pyVim.connect.SmartConnect 는 httpConnectionTimeout=None 을 받고
    SoapStubAdapter 가 HTTPSConnection(timeout=...) 으로 넘긴다 — 연결과 각 소켓 읽기/쓰기에 걸리는
    timeout 이다 (응답 전체 시간 상한이 아니다). connectionPoolTimeout 은 유휴 연결 풀 수명이라 넘기지 않는다.
    """
    kwargs = dict(host=params['hostname'], user=params['username'], pwd=params['password'],
                  port=params['port'], sslContext=ssl_context)
    if _accepts_kwarg(SmartConnect, 'httpConnectionTimeout'):
        timeout = params.get('timeout') or 0
        kwargs['httpConnectionTimeout'] = timeout if timeout > 0 else _DEFAULT_TIMEOUT_SEC
    return kwargs


def main():
    module = AnsibleModule(
        argument_spec=dict(
            hostname=dict(type='str', required=True),
            username=dict(type='str', required=True),
            password=dict(type='str', required=True, no_log=True),
            port=dict(type='int', default=443),
            validate_certs=dict(type='bool', default=False),
            # host 가 2개 이상 보일 때(vCenter 경유) 네 파트의 대상 host 를 고르는 값 (선택).
            #   name / summary.config.name / vmk IPv4 와 정확히 비교한다. host 1개면 쓰지 않는다 (2026-10-03 C8).
            esxi_hostname=dict(type='str', required=False, default=None),
            # 2026-10-03 (C8): vSphere 소켓 timeout(초). SmartConnect 가 httpConnectionTimeout 을 받을 때만 쓴다.
            timeout=dict(type='int', default=_DEFAULT_TIMEOUT_SEC),
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
    target = None
    disks, controllers, listening_ports, host_info = [], [], [], {}

    try:
        # 2026-10-03 (C8): pyVmomi 의 첫 요청(버전 탐색 GET /sdk/vimServiceVersions.xml)은 httpConnectionTimeout 을 받지 않아
        #   무응답 서버에서 timeout 없이 멈춘다. 모듈은 자기 프로세스에서만 돌므로 접속 구간에 한해 소켓 기본 timeout 을 건다.
        _prev_default_timeout = socket.getdefaulttimeout()
        _connect_timeout = p.get('timeout') if isinstance(p.get('timeout'), int) and p.get('timeout') > 0 else _DEFAULT_TIMEOUT_SEC
        try:
            socket.setdefaulttimeout(_connect_timeout)
            si = SmartConnect(**_connect_kwargs(p, ctx))
            content = si.RetrieveContent()
            connect_ok = True
        except Exception as e:
            # 수집 실패는 graceful — 빈 list + error (호출 task 가 failed_when:false 로 흡수, rule 27 R4)
            part_errors['connect'] = str(e)
        finally:
            socket.setdefaulttimeout(_prev_default_timeout)

        if connect_ok:
            # 네 파트가 같은 HostSystem 1개를 읽는다 — view 는 여기서 한 번만 만든다 (2026-10-03 C8).
            target = _Target(content, p.get('esxi_hostname')).resolve()
            if target.select_error is not None:
                # 0개 / 불일치 / 복수 일치: 어느 host 의 데이터도 쓰지 않는다 (hosts[0] 추정 금지).
                part_errors['host_select'] = target.select_error
            else:
                disks = _safe_build('physical_disks', _build_disks, target, part_errors)
                controllers = _safe_build('controllers', _build_controllers, target, part_errors)
                listening_ports = _safe_build('listening_ports', _build_listening_ports,
                                              target, part_errors)
                host_info = _safe_build('host_info', _build_host_info,
                                        target, part_errors, default={})

        result = dict(
            changed=False,
            physical_disks=disks, disk_count=len(disks),
            controllers=controllers, listening_ports=listening_ports,
            host_info=host_info,
            # 2026-08-12 (N36): 아래 3키는 **추가만** 한 것이다 (기존 키 삭제/리네임 없음).
            #   호출 task(collect_disks.yml)가 어느 섹션의 errors 로 올릴지 정하는 근거다.
            #   connect_ok   : 접속 자체가 됐는지 (false 면 네 파트 모두 미수집)
            #   failed_parts : 실패한 파트 이름 목록 (정렬 — 출력 결정성)
            #                  'host_select' = 대상 host 를 고르지 못해 네 파트 모두 미수집 (2026-10-03 C8)
            #   part_errors  : 파트 → 사유. 사용자 문장이 아니라 errors[].detail 근거다.
            connect_ok=connect_ok,
            failed_parts=sorted(part_errors.keys()),
            part_errors=part_errors,
            # 2026-10-03 (C8): 비치명 통보 [{section, message}] — 추가만 한 키다 (모듈 결과 내부,
            #   envelope 아님). 예: 방화벽 범위 규칙을 시작 포트로 보고했다는 사실.
            notices=list(target.notices) if target is not None else [],
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
