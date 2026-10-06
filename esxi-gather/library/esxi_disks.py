#!/usr/bin/python
# -*- coding: utf-8 -*-

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

_DEFAULT_TIMEOUT_SEC = 1800

_SELECT_IDS = 'name / summary.config.name / vmk IPv4(config.network.vnic[].spec.ip.ipAddress)'


def _decode_serial(lun):
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
    return sorted(out, key=lambda d: d.get('id') or '')


def _build_controllers(target):
    hs = _as_target(target).host()
    if hs is None:
        return []
    out = []
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
    try:
        end = int(getattr(rule, 'endPort', None) or 0)
    except (TypeError, ValueError):
        return None
    return end if (end and end != start) else None


def _build_listening_ports(target):
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
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _list_hosts(content):
    view = content.viewManager.CreateContainerView(content.rootFolder, [vim.HostSystem], True)
    try:
        return list(view.view or [])
    finally:
        view.Destroy()


def _host_identifiers(hs):
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
        self.resolve()
        if self._exc is not None:
            raise self._exc
        return self._host

    def notice(self, section, message):
        entry = {'section': section, 'message': str(message)}
        if entry not in self.notices:
            self.notices.append(entry)


def _as_target(target, esxi_hostname=None):
    return target if isinstance(target, _Target) else _Target(target, esxi_hostname)


def _build_host_info(target, hostname=None):
    hs = _as_target(target, hostname).host()
    if hs is None:
        return {}
    info = {}
    cfg = getattr(hs, 'config', None)
    net = getattr(cfg, 'network', None) if cfg is not None else None
    hw = getattr(hs, 'hardware', None)

    dns = getattr(net, 'dnsConfig', None) if net is not None else None
    info['hostname'] = _s(getattr(dns, 'hostName', None)) if dns is not None else None
    info['domain_name'] = _s(getattr(dns, 'domainName', None)) if dns is not None else None
    info['search_domain'] = [str(x) for x in (getattr(dns, 'searchDomain', None) or [])] if dns is not None else []
    info['dns_servers'] = [str(x) for x in (getattr(dns, 'address', None) or [])] if dns is not None else []

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
        ls = getattr(p, 'linkSpeed', None)
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

    ci = getattr(hw, 'cpuInfo', None) if hw is not None else None
    hz = getattr(ci, 'hz', None) if ci is not None else None
    info['cpu_mhz'] = int(round(int(hz) / 1000000.0)) if hz else None
    info['cpu_packages'] = getattr(ci, 'numCpuPackages', None) if ci is not None else None
    info['cpu_cores'] = getattr(ci, 'numCpuCores', None) if ci is not None else None
    info['cpu_threads'] = getattr(ci, 'numCpuThreads', None) if ci is not None else None
    pk = list((getattr(hw, 'cpuPkg', None) or []) if hw is not None else [])
    info['cpu_vendor'] = _s(getattr(pk[0], 'vendor', None)) if pk else None
    info['cpu_description'] = _s(getattr(pk[0], 'description', None)) if pk else None

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
    try:
        return fn(target)
    except Exception as e:
        part_errors[part] = str(e)
        return [] if default is None else default


def _accepts_kwarg(fn, name):
    signature = getattr(inspect, 'signature', None)
    if signature is None:
        return False
    try:
        param = signature(fn).parameters.get(name)
    except (TypeError, ValueError):
        return False
    return param is not None and param.kind in (param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY)


def _connect_kwargs(params, ssl_context):
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
            esxi_hostname=dict(type='str', required=False, default=None),
            timeout=dict(type='int', default=_DEFAULT_TIMEOUT_SEC),
        ),
        supports_check_mode=True,
    )
    if not HAS_PYVMOMI:
        module.fail_json(msg='pyvmomi (pyVim/pyVmomi) 미설치', exception=PYVMOMI_IMP_ERR)

    p = module.params
    ctx = None if p['validate_certs'] else ssl._create_unverified_context()

    si = None
    part_errors = {}
    connect_ok = False
    content = None
    target = None
    disks, controllers, listening_ports, host_info = [], [], [], {}

    try:
        _prev_default_timeout = socket.getdefaulttimeout()
        _connect_timeout = p.get('timeout') if isinstance(p.get('timeout'), int) and p.get('timeout') > 0 else _DEFAULT_TIMEOUT_SEC
        try:
            socket.setdefaulttimeout(_connect_timeout)
            si = SmartConnect(**_connect_kwargs(p, ctx))
            content = si.RetrieveContent()
            connect_ok = True
        except Exception as e:
            part_errors['connect'] = str(e)
        finally:
            socket.setdefaulttimeout(_prev_default_timeout)

        if connect_ok:
            target = _Target(content, p.get('esxi_hostname')).resolve()
            if target.select_error is not None:
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
            connect_ok=connect_ok,
            failed_parts=sorted(part_errors.keys()),
            part_errors=part_errors,
            notices=list(target.notices) if target is not None else [],
        )
        if part_errors:
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
