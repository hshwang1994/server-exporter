"""esxi_disks.py — 수집 대상 HostSystem 1개 선택 / 방화벽 포트 범위 / 연결 timeout (2026-10-03, C8).

종전 모듈의 결함 (코드로 확인):
  - 물리 디스크 / 컨트롤러 / 방화벽 포트는 ContainerView 의 **모든** HostSystem 을 합산했다.
    host 가 여럿 보이면(vCenter 경유) 다른 host 의 디스크·포트가 이 대상의 것으로 섞였다.
  - host_info 는 이름이 안 맞으면 hosts[0] 을 썼다.
  - 파트마다 ContainerView 를 따로 만들었다 (실행당 4회).
  - 방화벽 규칙의 범위 끝을 존재하지 않는 `portRange` 속성에서 읽었다 (pyVmomi 필드는 `endPort`).
  - SmartConnect 에 timeout 을 넘기지 않았다.

고정하는 계약:
  (a) host 1개(standalone ESXi)면 esxi_hostname 과 무관하게 그 host 를 쓴다.
  (b)(c) host 2개 이상이면 name / summary.config.name / vmk IPv4 가 인자와 정확히(대소문자 무시)
      같은 host 1개만 쓴다.
  (d)(e) 일치 0개 / 2개 이상 / host 0개면 part_errors['host_select'] + 모든 파트 빈 값.
      어느 host 의 데이터도 읽지 않는다 (hosts[0] 추정 금지).
  (f) 방화벽 규칙 endPort != port 이면 시작 포트만 내보내고(값 계약 불변) notices 1건.
  (g) ContainerView 는 실행당 1번.
  (h) 설치된 SmartConnect 가 httpConnectionTimeout 을 받으면 모듈 timeout 을 넘기고, 아니면 넘기지 않는다.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

import tests.unit.test_esxi_section_errors as base

REPO = Path(__file__).resolve().parents[2]
# 실장비 캡처 (10.100.64.1 = esxi01). production 브랜치에는 tests/reference 가 없다 → skip.
_DUMP = REPO / "tests" / "reference" / "esxi" / "10_100_64_1" / "pyvmomi_host_dump.json"
_PORT = {"a": 1001, "b": 1002}


# ---------------------------------------------------------------------------
# pyVmomi 대역
# ---------------------------------------------------------------------------
class _ScsiDisk(object):
    """vim.host.ScsiDisk 대역 — _build_disks 의 isinstance 판정용."""

    def __init__(self, canonical, serial):
        self.canonicalName = canonical
        self.capacity = NS(block=2097152, blockSize=512)
        self.vendor = "EXAMPLE"
        self.model = "SSD-1"
        self.ssd = True
        self.alternateName = []
        self.serialNumber = serial


class _SerialAttachedHba(object):
    """HostSerialAttachedHba 대역 — 클래스 이름으로 controller_type(SAS) 이 정해진다."""

    def __init__(self, device, pci):
        self.device = device
        self.model = "Example SAS HBA"
        self.pci = pci
        self.driver = "example_sas"


def _ruleset(key, rules, enabled=True):
    """HostFirewallRuleset 대역. rules = [(port, endPort, direction, protocol), ...]"""
    return NS(key=key, enabled=enabled,
              rule=[NS(port=p, endPort=e, direction=d, portType="dst", protocol=proto)
                    for (p, e, d, proto) in rules])


class _Host(object):
    """HostSystem 대역.

    data_reads 는 **데이터 파트만** 읽는 속성(configManager / hardware)의 읽기 횟수다.
    host 선택은 name / summary / config 만 보므로, 선택에 실패한 실행에서 이 값이 0 이면
    어느 host 의 데이터도(hosts[0] 포함) 결과에 쓰이지 않았다는 뜻이다.
    """

    def __init__(self, tag, name, vmk_ip, summary_name=None, rulesets=None):
        self.name = name
        self.summary = NS(config=NS(name=summary_name), quickStats=NS(uptime=3600))
        self.data_reads = 0
        pci = "pci-" + tag
        vnic = NS(device="vmk0", portgroup="Management Network",
                  spec=NS(mac="00:50:56:00:00:01", mtu=1500,
                          ip=NS(ipAddress=vmk_ip, subnetMask="255.255.255.0", dhcp=False,
                                ipV6Config=None),
                          ipRouteSpec=None))
        network = NS(dnsConfig=NS(hostName="esxi-" + tag, domainName="lab.local",
                                  searchDomain=[], address=[]),
                     ipRouteConfig=NS(defaultGateway="10.0.0.254", gatewayDevice="vmk0",
                                      ipV6DefaultGateway=None),
                     vnic=[vnic], pnic=[])
        if rulesets is None:
            rulesets = [_ruleset("svc-" + tag, [(_PORT.get(tag, 1009), None, "inbound", "tcp")])]
        self.config = NS(network=network,
                         storageDevice=NS(hostBusAdapter=[_SerialAttachedHba("vmhba-" + tag, pci)]),
                         firewall=NS(ruleset=rulesets))
        self._config_manager = NS(storageSystem=NS(storageDeviceInfo=NS(
            scsiLun=[_ScsiDisk("naa." + tag, "SER-DISK-" + tag)])))
        self._hardware = NS(
            pciDevice=[NS(id=pci, vendorName="Example Vendor", deviceName="Example HBA")],
            cpuInfo=NS(hz=2000000000, numCpuPackages=1, numCpuCores=8, numCpuThreads=16),
            cpuPkg=[NS(vendor="intel", description="Example CPU")],
            biosInfo=None,
            systemInfo=NS(uuid="uuid-" + tag, serialNumber="SER-" + tag,
                          vendor="Example Systems", model="Rack-1"))

    @property
    def configManager(self):
        self.data_reads += 1
        return self._config_manager

    @property
    def hardware(self):
        self.data_reads += 1
        return self._hardware


class _Content(object):
    """ServiceContent 대역 — ContainerView 생성/파기 횟수를 센다."""

    def __init__(self, hosts, fail=None):
        self.rootFolder = object()
        self.views = 0
        self.destroyed = 0
        self._hosts = list(hosts)
        self._fail = fail
        self.viewManager = NS(CreateContainerView=self._create)

    def _create(self, root, types, recursive):
        self.views += 1
        if self._fail:
            raise RuntimeError(self._fail)
        return NS(view=list(self._hosts), Destroy=self._destroy)

    def _destroy(self):
        self.destroyed += 1


# ---------------------------------------------------------------------------
# 모듈 실행
# ---------------------------------------------------------------------------
def _module():
    m = importlib.reload(base._load_module())
    m.vim = NS(HostSystem=object, host=NS(ScsiDisk=_ScsiDisk))
    return m


def _run(content, esxi_hostname=None, connect=None, spec_out=None, **extra_params):
    """main() 을 실제 빌더로 끝까지 돌려 exit_json payload 를 돌려준다."""
    m = _module()
    params = dict(hostname="192.0.2.10", username="u", password="p", port=443,
                  validate_certs=False, esxi_hostname=esxi_hostname)
    params.update(extra_params)

    class _Mod(base._StubAnsibleModule):
        def __init__(self, argument_spec=None, supports_check_mode=False):
            if spec_out is not None:
                spec_out.append(argument_spec)
            self.params = dict(params)

    m.AnsibleModule = _Mod
    m.SmartConnect = connect or (lambda **kw: NS(RetrieveContent=lambda: content))
    m.Disconnect = lambda si: None
    try:
        m.main()
    except base._ExitJson as exc:
        return exc.payload
    raise AssertionError("exit_json 이 호출되지 않았다")


def _assert_parts_from(got, tag):
    """네 파트가 모두 같은 host(tag) 하나에서만 나왔다."""
    assert got["failed_parts"] == [] and "error" not in got, got.get("part_errors")
    assert [d["id"] for d in got["physical_disks"]] == ["naa." + tag]
    assert got["disk_count"] == 1
    assert [c["id"] for c in got["controllers"]] == ["vmhba-" + tag]
    assert got["listening_ports"] == [str(_PORT.get(tag, 1009))]
    assert got["host_info"]["serial"] == "SER-" + tag
    assert got["host_info"]["hostname"] == "esxi-" + tag


def _assert_fail_closed(got, *hosts):
    """선택 실패 — host_select 1건, 모든 파트 빈 값, 어느 host 의 데이터도 읽지 않았다."""
    assert got["connect_ok"] is True
    assert got["failed_parts"] == ["host_select"], got.get("part_errors")
    assert got["error"].startswith("host_select: ")
    assert got["physical_disks"] == [] and got["disk_count"] == 0
    assert got["controllers"] == [] and got["listening_ports"] == []
    assert got["host_info"] == {}
    assert got["notices"] == []
    for hs in hosts:
        assert hs.data_reads == 0, f"{hs.name} 의 데이터를 읽었다 — 선택 실패인데 추정 host 를 썼다"
    return got["part_errors"]["host_select"]


def _two_hosts(ip_a="10.0.0.11", ip_b="10.0.0.12"):
    return _Host("a", "esxi-a.lab.local", ip_a), _Host("b", "esxi-b.lab.local", ip_b)


# ═══════════════════════════════════════════════════════════════════════════
# (a) standalone — host 1개면 인자와 무관하게 그 host
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("arg", [None, "esxi01", "ESXI-A.LAB.LOCAL", "10.9.9.9", "unrelated"])
def test_a_single_host_is_used_regardless_of_hostname_argument(arg):
    """인자는 짧은 ansible_hostname 이거나 null 이고, HostSystem.name 은 FQDN/IP 일 수 있다."""
    got = _run(_Content([_Host("a", "esxi-a.lab.local", "10.0.0.11")]), esxi_hostname=arg)
    _assert_parts_from(got, "a")


# ═══════════════════════════════════════════════════════════════════════════
# (b)(c) host 2개 이상 — 정확히 일치하는 host 1개만
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("arg", ["esxi-b.lab.local", "ESXI-B.Lab.Local"])
def test_b_two_hosts_pick_the_exact_name_match(arg):
    a, b = _two_hosts()
    got = _run(_Content([a, b]), esxi_hostname=arg)
    _assert_parts_from(got, "b")
    assert a.data_reads == 0, "선택되지 않은 host 의 데이터를 읽었다"


def test_b_two_hosts_pick_the_summary_config_name_match():
    a = _Host("a", "10.0.0.11", "10.0.0.11", summary_name="esxi-a.lab.local")
    b = _Host("b", "10.0.0.12", "10.0.0.12", summary_name="esxi-b.lab.local")
    got = _run(_Content([a, b]), esxi_hostname="esxi-b.lab.local")
    _assert_parts_from(got, "b")
    assert a.data_reads == 0


def test_c_two_hosts_pick_the_vmk_ipv4_match():
    a, b = _two_hosts()
    got = _run(_Content([b, a]), esxi_hostname="10.0.0.11")
    _assert_parts_from(got, "a")
    assert b.data_reads == 0


# ═══════════════════════════════════════════════════════════════════════════
# (d)(e) 선택 실패 — host_select + 빈 파트, hosts[0] 추정 없음
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("arg", [
    None,                 # 인자 없음
    "esxi-c.lab.local",   # 어느 host 와도 다름
    "esxi-b",             # 'esxi-b.lab.local' 의 앞부분 — 부분 일치는 일치가 아니다
    "10.0.0.1",           # '10.0.0.11' / '10.0.0.12' 의 앞부분
])
def test_d_two_hosts_without_a_match_fail_closed(arg):
    a, b = _two_hosts()
    msg = _assert_fail_closed(_run(_Content([a, b]), esxi_hostname=arg), a, b)
    assert "HostSystem 2개" in msg, msg
    if arg:
        assert arg in msg, msg
    for field in ("name", "summary.config.name", "vmk"):
        assert field in msg, f"어떤 식별자를 비교했는지 사유에 없다: {msg}"


def test_d_view_without_hosts_is_a_host_select_failure():
    msg = _assert_fail_closed(_run(_Content([]), esxi_hostname="esxi01"))
    assert "0개" in msg, msg


def test_e_two_hosts_matching_the_same_value_are_ambiguous():
    a, b = _two_hosts(ip_a="10.0.0.50", ip_b="10.0.0.50")   # 격리망 vmk IP 중복
    msg = _assert_fail_closed(_run(_Content([a, b]), esxi_hostname="10.0.0.50"), a, b)
    assert "esxi-a.lab.local" in msg and "esxi-b.lab.local" in msg, msg


# ═══════════════════════════════════════════════════════════════════════════
# (f) 방화벽 포트 범위 — 시작 포트만(값 계약 불변) + notices
# ═══════════════════════════════════════════════════════════════════════════
def test_f_port_range_emits_start_port_and_one_notice():
    hs = _Host("a", "esxi-a.lab.local", "10.0.0.11", rulesets=[
        _ruleset("sshServer", [(22, None, "inbound", "tcp")]),
        _ruleset("gdbserver", [(1000, 9999, "inbound", "tcp")]),
        _ruleset("vMotion", [(8000, 8000, "inbound", "tcp")]),               # endPort == port
        _ruleset("remoteSerialPort", [(1024, 65535, "inbound", "tcp")], enabled=False),
        _ruleset("nfsClient", [(0, 65535, "outbound", "tcp")]),
    ])
    got = _run(_Content([hs]))
    assert got["failed_parts"] == []
    assert got["listening_ports"] == ["22", "1000", "8000"], "값 계약(시작 포트 str[]) 이 바뀌었다"
    assert len(got["notices"]) == 1, got["notices"]
    notice = got["notices"][0]
    assert notice["section"] == "system"
    assert notice["message"].startswith("port range 1000-9999 reported as 1000"), notice
    assert "gdbserver" in notice["message"]


def test_f_single_port_rules_add_no_notice():
    hs = _Host("a", "esxi-a.lab.local", "10.0.0.11", rulesets=[
        _ruleset("sshServer", [(22, None, "inbound", "tcp")]),
        _ruleset("vMotion", [(8000, 8000, "inbound", "tcp")]),
    ])
    got = _run(_Content([hs]))
    assert got["listening_ports"] == ["22", "8000"]
    assert got["notices"] == []


def _dump_rulesets(enable=()):
    raw = json.loads(_DUMP.read_text(encoding="utf-8"))["firewall_rules"]
    return [_ruleset(rs["key"],
                     [(r["port"], r["endPort"], r["direction"], r["protocol"]) for r in (rs.get("rule") or [])],
                     enabled=bool(rs["enabled"]) or rs["key"] in enable)
            for rs in raw]


def test_f_reference_host_ports_are_unchanged_without_notices():
    """실장비 esxi01 — 활성 inbound 범위 규칙이 없다. 포트 목록은 종전 출력 그대로, notices 0."""
    if not _DUMP.exists():
        pytest.skip("ESXi reference dump 없음")
    got = _run(_Content([_Host("a", "esxi01", "10.100.64.1", rulesets=_dump_rulesets())]),
               esxi_hostname="esxi01")
    assert got["listening_ports"] == ["22", "68", "80", "161", "443", "902", "5988", "5989",
                                      "8000", "8300", "8301", "8302", "9080"]
    assert got["notices"] == []


def test_f_reference_range_rules_produce_notices_when_enabled():
    """같은 캡처에서 gdbserver(inbound 1000-9999, 50000-50999) 를 켜면 시작 포트 2개 + notices 2건."""
    if not _DUMP.exists():
        pytest.skip("ESXi reference dump 없음")
    got = _run(_Content([_Host("a", "esxi01", "10.100.64.1",
                               rulesets=_dump_rulesets(enable={"gdbserver"}))]))
    assert "1000" in got["listening_ports"] and "50000" in got["listening_ports"]
    assert "9999" not in got["listening_ports"]
    msgs = [n["message"] for n in got["notices"]]
    assert len(msgs) == 2, msgs
    assert msgs[0].startswith("port range 1000-9999 reported as 1000")
    assert msgs[1].startswith("port range 50000-50999 reported as 50000")


# ═══════════════════════════════════════════════════════════════════════════
# (g) ContainerView 는 실행당 1번
# ═══════════════════════════════════════════════════════════════════════════
def test_g_container_view_is_created_once_per_run():
    content = _Content([_Host("a", "esxi-a.lab.local", "10.0.0.11")])
    got = _run(content, esxi_hostname="esxi-a")
    _assert_parts_from(got, "a")
    assert (content.views, content.destroyed) == (1, 1)


def test_g_container_view_is_created_once_with_many_hosts():
    content = _Content(_two_hosts())
    got = _run(content, esxi_hostname="10.0.0.12")
    _assert_parts_from(got, "b")
    assert (content.views, content.destroyed) == (1, 1)


def test_g_view_failure_is_reported_per_part_after_a_single_attempt():
    """목록 조회 예외는 종전처럼 네 파트 각각의 사유로 남는다 — 단, 시도는 1번이다."""
    content = _Content([], fail="NoPermission: System.View")
    got = _run(content, esxi_hostname="esxi01")
    assert content.views == 1, "실패한 view 생성을 파트마다 다시 시도했다"
    assert got["connect_ok"] is True
    assert got["failed_parts"] == ["controllers", "host_info", "listening_ports", "physical_disks"]
    assert all("NoPermission" in v for v in got["part_errors"].values()), got["part_errors"]


# ═══════════════════════════════════════════════════════════════════════════
# (h) SmartConnect httpConnectionTimeout — 시그니처에 있을 때만
# ═══════════════════════════════════════════════════════════════════════════
_UNSET = object()


def test_h_smartconnect_gets_module_timeout_when_signature_has_it():
    content = _Content([_Host("a", "esxi-a.lab.local", "10.0.0.11")])
    calls = []

    def smart(host=None, user=None, pwd=None, port=None, sslContext=None,
              httpConnectionTimeout=_UNSET, connectionPoolTimeout=_UNSET):
        calls.append((httpConnectionTimeout, connectionPoolTimeout))
        return NS(RetrieveContent=lambda: content)

    got = _run(content, connect=smart, timeout=17)
    assert got["connect_ok"] is True
    assert calls == [(17, _UNSET)], "timeout 미전달 또는 connectionPoolTimeout 전달"


def test_h_smartconnect_without_timeout_parameter_is_called_as_before():
    """구버전 시그니처 — 모르는 kwarg 를 넘기면 TypeError 로 접속 자체가 실패한다."""
    content = _Content([_Host("a", "esxi-a.lab.local", "10.0.0.11")])
    calls = []

    def smart(host=None, user=None, pwd=None, port=None, sslContext=None):
        calls.append(host)
        return NS(RetrieveContent=lambda: content)

    got = _run(content, connect=smart, timeout=17)
    assert got["connect_ok"] is True and calls == ["192.0.2.10"], got.get("part_errors")


def test_h_kwargs_only_signature_is_not_treated_as_support():
    """**kwargs 만 받는 SmartConnect 는 지원 근거가 아니다 — 이름이 있는 매개변수만 본다."""
    content = _Content([_Host("a", "esxi-a.lab.local", "10.0.0.11")])
    seen = []

    def smart(**kw):
        seen.append(sorted(kw))
        return NS(RetrieveContent=lambda: content)

    _run(content, connect=smart, timeout=17)
    assert seen == [["host", "port", "pwd", "sslContext", "user"]]


def test_h_timeout_argument_is_declared_with_a_positive_default():
    specs = []
    _run(_Content([_Host("a", "esxi-a.lab.local", "10.0.0.11")]), spec_out=specs)
    spec = specs[0]["timeout"]
    assert spec["type"] == "int" and spec["default"] > 0, spec


# ═══════════════════════════════════════════════════════════════════════════
# 알려진 배선 공백 — collect_disks.yml 이 host_select 를 섹션에 올리지 않는다
# ═══════════════════════════════════════════════════════════════════════════
def test_host_select_failure_reaches_errors_fragment():
    out = base._errors(base._DISKS, base._DISKS_TASK, {
        "_e_disks_failed_parts": ["host_select"],
        "_e_disks_err": "host_select: HostSystem 2개 중 일치 host 없음"})
    assert {e["section"] for e in out} == {"storage", "system"}
