"""esxi_disks.py `_build_host_info` — vSphere 객체 → host_info dict (2026-09-03).

pyvmomi 없이 SimpleNamespace 로 HostSystem 을 흉내 내 다음을 고정한다:
- dnsConfig.hostName / domainName → hostname / domain_name
- ipRouteConfig 가 비어 있으면 vnic.spec.ipRouteSpec.ipRouteConfig.defaultGateway 로 폴백 + gateway_device
- pnic ↔ pciDevice 매핑 (manufacturer / model), link down 이면 speed null / link_up false
- vnic IPv6 주소, cpuInfo.hz → cpu_mhz(정격), quickStats.uptime, biosInfo.releaseDate → YYYY-MM-DD
"""
from __future__ import annotations

import importlib
from datetime import datetime
from types import SimpleNamespace as NS

from tests.unit.test_esxi_section_errors import _load_module


def _module():
    m = _load_module()
    m = importlib.reload(m)
    m.vim = NS(HostSystem=object)
    return m


def _host(gateway_on_host: bool):
    dns = NS(hostName="esxi01", domainName="lab.local", searchDomain=["lab.local"], address=["10.0.0.53"])
    rc = NS(defaultGateway="10.0.0.254" if gateway_on_host else None,
            gatewayDevice="vmk0" if gateway_on_host else None, ipV6DefaultGateway=None)
    vnic = NS(device="vmk0", portgroup="Management Network",
              spec=NS(mac="00:50:56:AA:BB:CC", mtu=1500,
                      ip=NS(ipAddress="10.0.0.10", subnetMask="255.255.255.0", dhcp=False,
                            ipV6Config=NS(ipV6Address=[NS(ipAddress="fe80::250:56ff:feaa:bbcc", prefixLength=64, origin="linklayer")])),
                      ipRouteSpec=NS(ipRouteConfig=NS(defaultGateway="10.0.0.254", ipV6DefaultGateway=None))))
    pnic_up = NS(device="vmnic0", mac="00:11:22:33:44:55", driver="ixgben", pci="0000:3b:00.0", linkSpeed=NS(speedMb=10000, duplex=True))
    pnic_down = NS(device="vmnic1", mac="00:11:22:33:44:56", driver="ixgben", pci="0000:3b:00.1", linkSpeed=None)
    pci = [NS(id="0000:3b:00.0", vendorName="Example Silicon Corp", deviceName="Ethernet Controller X710"),
           NS(id="0000:3b:00.1", vendorName="Example Silicon Corp", deviceName="Ethernet Controller X710")]
    hw = NS(pciDevice=pci,
            cpuInfo=NS(hz=2195000000, numCpuPackages=2, numCpuCores=44, numCpuThreads=88),
            cpuPkg=[NS(vendor="intel", description="Example CPU @ 2.20GHz")],
            biosInfo=NS(biosVersion="1.2.3", releaseDate=datetime(2021, 2, 2, 9, 0)),
            systemInfo=NS(uuid="9f0190b1-ce56-d44e-a1dd-6571daaedad7", serialNumber="SER123", vendor="Example Systems Inc", model="Rack-1"))
    return NS(name="esxi01", config=NS(network=NS(dnsConfig=dns, ipRouteConfig=rc, vnic=[vnic], pnic=[pnic_up, pnic_down])),
              hardware=hw, summary=NS(quickStats=NS(uptime=12345)))


def _content(hosts):
    view = NS(view=hosts, Destroy=lambda: None)
    return NS(viewManager=NS(CreateContainerView=lambda root, types, rec: view), rootFolder=None)


def test_host_info_gateway_falls_back_to_vnic_route():
    m = _module()
    info = m._build_host_info(_content([_host(gateway_on_host=False)]), "esxi01")
    assert info["hostname"] == "esxi01" and info["domain_name"] == "lab.local"
    assert info["dns_servers"] == ["10.0.0.53"]
    assert info["default_gateway"] == "10.0.0.254" and info["gateway_device"] == "vmk0"
    assert info["vnics"][0]["ipv6"][0]["address"] == "fe80::250:56ff:feaa:bbcc"
    assert info["vnics"][0]["gateway"] == "10.0.0.254"
    assert info["cpu_mhz"] == 2195 and info["cpu_vendor"] == "intel"
    assert info["uptime_seconds"] == 12345
    assert info["bios_date"] == "2021-02-02" and info["bios_version"] == "1.2.3"
    assert info["system_uuid"] == "9f0190b1-ce56-d44e-a1dd-6571daaedad7" and info["serial"] == "SER123"


def test_host_info_pnic_pci_mapping_and_link_state():
    m = _module()
    info = m._build_host_info(_content([_host(gateway_on_host=True)]), "esxi01")
    assert info["gateway_device"] == "vmk0"
    up, down = info["pnics"]
    assert up["manufacturer"] == "Example Silicon Corp" and up["model"] == "Ethernet Controller X710"
    assert up["speed_mbps"] == 10000 and up["link_up"] is True
    assert down["speed_mbps"] is None and down["link_up"] is False and down["manufacturer"] == "Example Silicon Corp"


def test_host_info_picks_named_host_and_returns_empty_without_hosts():
    m = _module()
    other = _host(gateway_on_host=True)
    other.name = "esxi99"
    other.config.network.dnsConfig.hostName = "esxi99"
    info = m._build_host_info(_content([other, _host(gateway_on_host=True)]), "esxi01")
    assert info["hostname"] == "esxi01"
    assert m._build_host_info(_content([]), "esxi01") == {}


def test_module_result_includes_host_info_and_isolated_failure():
    """host_info 파트가 죽어도 다른 파트는 살고 failed_parts 에 이름이 남는다."""
    import tests.unit.test_esxi_section_errors as base
    m = _module()

    class _SI:
        def RetrieveContent(self):
            return object()

    m.SmartConnect = lambda **kw: _SI()
    m.Disconnect = lambda si: None
    m._build_disks = lambda c: [{"id": "naa.1"}]
    m._build_controllers = lambda c: []
    m._build_listening_ports = lambda c: ["443"]

    def _boom(c, h=None):
        raise RuntimeError("no dns")
    m._build_host_info = _boom
    try:
        m.main()
    except base._ExitJson as exc:
        got = exc.payload
    assert got["host_info"] == {} and got["failed_parts"] == ["host_info"]
    assert got["physical_disks"] == [{"id": "naa.1"}] and got["listening_ports"] == ["443"]
    assert "no dns" in got["error"]
