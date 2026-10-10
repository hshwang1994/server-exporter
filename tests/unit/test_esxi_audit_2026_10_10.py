"""2026-10-10 감사 — ESXi 채널 결함 고정 (plan §4.4).

ESXI-09  datastore 'total'/'free' 문자열의 단위 접미사 — TB x1024, GB x1, MB /1024 (종전: TB 만 보고 MB 를 GB 로 읽었다). 실제 normalize 템플릿을 렌더한다.
ESXI-12  controller_type: BlockHba 를 전부 SATA 로 적지 않는다 — 드라이버 계열로 SATA / RAID / NVMe, 모르면 null.
D-03     firewall 유효 정책(defaultPolicy.incomingBlocked)이 host_info 로 나온다.
ESXI-13  attempted_count 는 실제로 시도한 후보 수다 — try_one_credential 이 올리고 try_credentials 가 그 수를 적는다 (텍스트 계약).
ESXI-03  collect_config 가 esxi_hostname 을 넘기고, 이름 서버 오류 조건은 dns_info 만 본다 (텍스트 계약).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
import yaml
from jinja2 import Environment

from tests.unit.test_esxi_disks_host_info import _content, _host, _module

REPO = Path(__file__).resolve().parents[2]
E = REPO / "esxi-gather" / "tasks"


def _set_fact_template(path: Path, var: str) -> str:
    for t in yaml.safe_load(path.read_text(encoding="utf-8")):
        sf = (t.get("set_fact") or t.get("ansible.builtin.set_fact")) if isinstance(t, dict) else None
        if isinstance(sf, dict) and var in sf:
            return sf[var]
    raise AssertionError(var)


def _env():
    env = Environment()
    env.filters["regex_replace"] = lambda s, pat, repl="": re.sub(pat, repl, str(s))
    return env


@pytest.mark.parametrize("total,free,exp_total_mb,exp_free_mb", [
    ("1.5 TB", "500 GB", 1572864, 512000),
    ("500 GB", "100 GB", 512000, 102400),
    ("512 MB", "100 MB", 512, 100),
    ("2 tb", "1 tb", 2097152, 1048576),
])
def test_datastore_string_sizes_handle_tb_gb_mb(total, free, exp_total_mb, exp_free_mb):
    tmpl = _env().from_string(_set_fact_template(E / "normalize_storage.yml", "_e_norm_datastores"))
    out = ast.literal_eval(tmpl.render(_e_raw_ds=[{"name": "ds1", "type": "VMFS", "total": total, "free": free, "accessible": True}]).strip())
    assert out[0]["total_mb"] == exp_total_mb and out[0]["free_mb"] == exp_free_mb, out
    assert out[0]["used_mb"] == exp_total_mb - exp_free_mb


def test_datastore_capacity_bytes_path_unchanged():
    tmpl = _env().from_string(_set_fact_template(E / "normalize_storage.yml", "_e_norm_datastores"))
    out = ast.literal_eval(tmpl.render(_e_raw_ds=[{"name": "ds", "capacity": 1073741824, "freeSpace": 536870912}]).strip())
    assert out[0]["total_mb"] == 1024 and out[0]["free_mb"] == 512 and out[0]["usage_percent"] == 50.0


@pytest.mark.parametrize("tname,driver,expected", [
    ("vim.host.BlockHba", "vmw_ahci", "SATA"),
    ("vim.host.BlockHba", "lsi_mr3", "RAID"),
    ("vim.host.BlockHba", "megaraid_sas", "RAID"),
    ("vim.host.BlockHba", "smartpqi", "RAID"),
    ("vim.host.BlockHba", "nvme_pcie", "NVMe"),
    ("vim.host.BlockHba", "nvme", "NVMe"),
    ("vim.host.BlockHba", "some_unknown_drv", None),
    ("vim.host.BlockHba", None, None),
    ("vim.host.FibreChannelHba", "lpfc", "FC"),
    ("vim.host.SerialAttachedHba", "lsi_msgpt3", "SAS"),
    ("vim.host.InternetScsiHba", "iscsi_vmk", "iSCSI"),
])
def test_controller_type_by_hba_kind_and_driver(tname, driver, expected):
    m = _module()
    assert m._controller_type(tname, driver) == expected


def test_build_controllers_uses_driver_family():
    m = _module()

    class BlockHba:
        def __init__(self, device, driver, model):
            self.device, self.driver, self.model, self.pci = device, driver, model, "0000:00:17.0"

    host = _host(gateway_on_host=True)
    host.config.storageDevice = NS(hostBusAdapter=[BlockHba("vmhba0", "vmw_ahci", "Lewisburg SATA"), BlockHba("vmhba1", "lsi_mr3", "PERC H740P"),
                                                    BlockHba("vmhba2", "nvme_pcie", "NVMe SSD Controller")])
    out = m._build_controllers(_content([host]))
    assert [(c["id"], c["controller_type"]) for c in out] == [("vmhba0", "SATA"), ("vmhba1", "RAID"), ("vmhba2", "NVMe")]


def test_host_info_exposes_firewall_default_policy():
    m = _module()
    host = _host(gateway_on_host=True)
    host.config.firewall = NS(defaultPolicy=NS(incomingBlocked=True, outgoingBlocked=False))
    info = m._build_host_info(_content([host]), "esxi01")
    assert info["firewall_incoming_blocked"] is True and info["firewall_outgoing_blocked"] is False
    host2 = _host(gateway_on_host=True)
    info2 = m._build_host_info(_content([host2]), "esxi01")
    assert info2["firewall_incoming_blocked"] is None and info2["firewall_outgoing_blocked"] is None, "정책을 못 읽으면 None (규칙 기반 종전 판정으로)"


def test_runtime_firewall_state_prefers_default_policy():
    env = Environment()
    env.tests["failed"] = lambda r: isinstance(r, dict) and bool(r.get("failed"))   # Ansible `is failed`
    tmpl = env.from_string(_set_fact_template(E / "collect_runtime.yml", "_e_runtime_firewall_state"))
    rules = {"esxi01": [{"enabled": True, "key": "sshServer"}]}
    assert tmpl.render(_e_raw_host={"firewall_incoming_blocked": True}, _e_firewall_result={"hosts_firewall_info": rules}, _e_hostname="esxi01").strip() == "active"
    assert tmpl.render(_e_raw_host={"firewall_incoming_blocked": False}, _e_firewall_result={"hosts_firewall_info": rules}, _e_hostname="esxi01").strip() == "inactive"
    # 정책을 못 읽으면 종전 규칙 기반 판정
    assert tmpl.render(_e_raw_host={}, _e_firewall_result={"hosts_firewall_info": rules}, _e_hostname="esxi01").strip() == "active"
    assert tmpl.render(_e_raw_host={}, _e_firewall_result={"hosts_firewall_info": {}}, _e_hostname="esxi01").strip() == "None"


def test_text_contracts_config_hostname_dns_condition_and_attempt_counter():
    cfg = (E / "collect_config.yml").read_text(encoding="utf-8")
    assert 'esxi_hostname:  "{{ _e_hostname | default(_e_ip, true) }}"' in cfg, "vmware_host_config_info 는 esxi_hostname 이 필수다 (ESXI-03)"
    net = (E / "normalize_network.yml").read_text(encoding="utf-8")
    assert "and not (_e_dns_ok | default(false) | bool)) -%}" in net and "and (_e_config_ok | default(false) | bool))) -%}" not in net
    for f in ("collect_dns.yml", "collect_network_extended.yml"):
        t = (E / f).read_text(encoding="utf-8")
        assert "ansible_user" not in t and "ansible_password" not in t, f"{f}: 자격은 _e_user/_e_pass 하나다 (ESXI-21)"
    for ch, var in (("esxi-gather", "_e_cred_tries"), ("os-gather", "_os_cred_tries")):
        one = (REPO / ch / "tasks" / "try_one_credential.yml").read_text(encoding="utf-8")
        all_ = (REPO / ch / "tasks" / "try_credentials.yml").read_text(encoding="utf-8")
        assert f'{var}: "{{{{ ({var} | default(0) | int) + 1 }}}}"' in one, ch
        assert f'attempted_count: "{{{{ {var} | default(0) | int }}}}"' in all_, ch
        assert f"{var}: 0" in all_, ch
