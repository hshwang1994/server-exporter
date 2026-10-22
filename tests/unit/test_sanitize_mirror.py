"""sanitize_mirror 회귀 — 캡처 미러의 관리 IP 와 호스트 이름을 형식이 유효한 대체값으로 일관되게 바꾸는 반출용 도구.

검증: 같은 실제 값 -> 같은 대체값(호스트/파일/실행 사이), 같은 /24 유지, 버전·ID·마스크·공개 URL 보존, IPv6/WWN/MAC/시각 구분,
인증서 본문·바이너리 제외, 파일/폴더 이름 치환, 형식 보존, 반출 전 검사(누출 감지), 입력/출력 겹침과 재처리 거부,
출력과 보고서에 실제 값이 없을 것. 합성 데이터만 쓴다 (실제 장비 값 없음).
"""
import ipaddress
import json
import os
import re
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROBE = os.path.join(REPO, "tests", "redfish-probe")
if PROBE not in sys.path:
    sys.path.insert(0, PROBE)

import sanitize_mirror as sm  # noqa: E402

REAL_IPS = ["11.65.23.24", "11.65.23.1", "11.65.1.10", "11.65.1.11", "11.65.1.20", "10.20.30.40", "10.20.30.41",
            "10.20.30.50", "172.30.5.9"]
REAL_NAMES = ["bmc-seoul-01", "corp.example.co.kr", "ntp1", "siem", "BMC-BUSAN-02"]
IP_RX = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")


def _write(root, rel, content):
    p = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if isinstance(content, bytes):
        with open(p, "wb") as f:
            f.write(content)
    elif isinstance(content, str):
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
    else:
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            json.dump(content, f, indent=2, sort_keys=True, ensure_ascii=False)
    return p


def _mirror(root, host="h1", ip="11.65.23.24", name="bmc-seoul-01"):
    h = host + "/"
    _write(root, h + "_manifest.json", {"host": ip + ":443", "options": {"user": "svc"}, "result": "COMPLETE"})
    _write(root, h + "_crawl.log", "mirror of %s:443 (%s)\n" % (ip, name))
    _write(root, h + "redfish/v1/index.json", {"@odata.id": "/redfish/v1", "Name": "Root"})
    _write(root, h + "redfish/v1/Managers/1/EthernetInterfaces/1/index.json", {
        "@odata.id": "/redfish/v1/Managers/1/EthernetInterfaces/1", "HostName": name,
        "FQDN": name + ".corp.example.co.kr", "MACAddress": "AA:BB:CC:DD:EE:FF",
        "IPv4Addresses": [{"Address": ip, "Gateway": "11.65.23.1", "SubnetMask": "255.255.255.0"}],
        "IPv6Addresses": [{"Address": "fe80::1234:56ff:fe78:9abc"}, {"Address": "2001:db8:aaaa:1::24"}],
        "NameServers": ["11.65.1.10", "11.65.1.11", "0.0.0.0"]})
    _write(root, h + "redfish/v1/Managers/1/NetworkProtocol/index.json", {
        "HostName": name, "NTP": {"NTPServers": ["ntp1.corp.example.co.kr", "11.65.1.20"]}})
    _write(root, h + "redfish/v1/Logs/Entries/index.json", {"Members": [
        {"Message": "User admin logged in from 10.20.30.40 (host %s)." % name, "MessageArgs": ["admin", "10.20.30.40"]},
        {"Message": "Firmware version 2.81.81.81 installed on %s.corp.example.co.kr" % name},
        {"Message": "line one\n10.20.30.41 connected, then 10.20.30.50:443 and https://10.20.30.50/redfish"}]})
    fw = "redfish/v1/UpdateService/FirmwareInventory/Installed-25227-6.10.00.00__iDRAC.Embedded.1-1/index.json"
    _write(root, h + fw, {"Id": "Installed-25227-6.10.00.00__iDRAC.Embedded.1-1", "Version": "6.10.00.00",
                          "FirmwareVersion": "2.81.81.81", "Name": "BMC Firmware 1.2.3.4", "SoftwareId": "3.4.5.6"})
    _write(root, h + "redfish/v1/EventService/Subscriptions/1/index.json",
           {"Destination": "https://siem.corp.example.co.kr:8443/events", "Context": "ctx"})
    _write(root, h + "redfish/v1/Registries/index.json",
           {"PublicationUri": "https://redfish.dmtf.org/registries/Base.1.0.0.json"})
    _write(root, h + "redfish/v1/Certs/1/index.json",
           {"CertificateString": "-----BEGIN CERTIFICATE-----\nMIIBabc+/=\nZm9v\n-----END CERTIFICATE-----"})
    _write(root, h + "redfish/v1/Bin/index.json", {"_non_json": True, "_raw_file": "raw.bin", "_bytes": 8})
    _write(root, h + "redfish/v1/Bin/raw.bin", bytes(bytearray([0, 1, 2, 3, 0x31, 0x30, 0x2e, 0x31])))
    _write(root, h + "redfish/v1/$metadata/raw.xml", '<edmx:Edmx><x host="%s" ip="10.20.30.50"/></edmx:Edmx>\n' % name)
    return os.path.join(root, host)


def _run(inp, out, mp, *extra):
    args = ([inp] if isinstance(inp, str) else list(inp)) + ["--out", out, "--map", mp] + list(extra)
    return sm.main(args)


def _read_all(root):
    out = {}
    for dp, _dn, fn in os.walk(root):
        for name in fn:
            p = os.path.join(dp, name)
            with open(p, "rb") as f:
                out[os.path.relpath(p, root).replace(os.sep, "/")] = f.read()
    return out


def _blob(root):
    """모든 파일 이름과 내용을 한 문자열로 (실제 값이 어디에도 없는지 검사용)."""
    return "\n".join(k + "\n" + v.decode("utf-8", "replace") for k, v in sorted(_read_all(root).items()))


def _json(root, rel):
    with open(os.path.join(root, *rel.split("/")), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def env(tmp_path):
    inp = str(tmp_path / "in")
    _mirror(inp)
    return inp, str(tmp_path / "out"), str(tmp_path / "m.json")


def test_real_values_are_gone_and_replacements_are_valid_and_consistent(env, capsys):
    inp, out, mp = env
    assert _run(inp, out, mp) == 0
    blob = _blob(out)
    for real in REAL_IPS + REAL_NAMES:
        assert real not in blob, "누출: 실제 값이 사본에 남음 (%d자)" % len(real)
    nic = _json(out, "h1/redfish/v1/Managers/1/EthernetInterfaces/1/index.json")
    v4 = nic["IPv4Addresses"][0]
    addr, gw = ipaddress.ip_address(v4["Address"]), ipaddress.ip_address(v4["Gateway"])
    assert addr.is_private and gw.is_private and v4["SubnetMask"] == "255.255.255.0"
    assert ipaddress.ip_network(v4["Address"] + "/24", strict=False) == ipaddress.ip_network(v4["Gateway"] + "/24", strict=False)
    assert nic["NameServers"][2] == "0.0.0.0"                                   # 미지정 주소는 그대로
    assert re.match(r"^host-[0-9a-f]{6}$", nic["HostName"])
    assert re.match(r"^host-[0-9a-f]{6}\.dom-[0-9a-f]{4}\.test$", nic["FQDN"])
    assert nic["FQDN"].split(".", 1)[0] == nic["HostName"]                      # FQDN 과 짧은 이름이 같은 가짜 이름
    ntp = _json(out, "h1/redfish/v1/Managers/1/NetworkProtocol/index.json")
    assert ntp["HostName"] == nic["HostName"] and ntp["NTP"]["NTPServers"][0].endswith(nic["FQDN"].split(".", 1)[1])
    assert nic["NameServers"][0].rsplit(".", 1)[0] == ntp["NTP"]["NTPServers"][1].rsplit(".", 1)[0]   # 같은 /24 -> 같은 가짜 /24
    man = _json(out, "h1/_manifest.json")
    assert man["host"] == v4["Address"] + ":443" and man["options"]["user"] == "svc"
    shown = capsys.readouterr().out
    for real in REAL_IPS + REAL_NAMES:
        assert real not in shown


def test_free_text_boundaries_and_escapes(env):
    inp, out, mp = env
    assert _run(inp, out, mp) == 0
    path = os.path.join(out, "h1", "redfish", "v1", "Logs", "Entries", "index.json")
    raw = open(path, encoding="utf-8").read()
    data = json.loads(raw)
    texts = [m.get("Message", "") for m in data["Members"]] + data["Members"][0]["MessageArgs"]
    ips = IP_RX.findall(chr(10).join(texts))
    assert "2.81.81.81" in ips                                                   # version 문맥의 버전은 보존
    ips = [x for x in ips if x != "2.81.81.81"]
    assert len(ips) == 5 and all(ipaddress.ip_address(x).is_private for x in ips)
    assert "10.20.30.41" not in raw and (chr(92) + "n") in raw                  # 이스케이프 바로 뒤의 주소도 바뀌고 이스케이프는 그대로
    assert ":443" in raw and "https://" in raw and "/redfish" in raw             # 포트와 URL 모양 유지

def test_versions_ids_masks_and_public_urls_are_preserved(env):
    inp, out, mp = env
    assert _run(inp, out, mp) == 0
    rel = "h1/redfish/v1/UpdateService/FirmwareInventory/Installed-25227-6.10.00.00__iDRAC.Embedded.1-1/index.json"
    assert _json(out, rel) == {"Id": "Installed-25227-6.10.00.00__iDRAC.Embedded.1-1", "Version": "6.10.00.00",
                               "FirmwareVersion": "2.81.81.81", "Name": "BMC Firmware 1.2.3.4", "SoftwareId": "3.4.5.6"}
    assert _json(out, "h1/redfish/v1/Registries/index.json")["PublicationUri"].startswith("https://redfish.dmtf.org/")
    sub = _json(out, "h1/redfish/v1/EventService/Subscriptions/1/index.json")
    assert sub["Destination"].startswith("https://host-") and sub["Destination"].endswith(".test:8443/events")


def test_ipv6_wwn_mac_and_times_are_distinguished(tmp_path):
    inp, out, mp = str(tmp_path / "in"), str(tmp_path / "out"), str(tmp_path / "m.json")
    _write(inp, "h/redfish/v1/index.json", {
        "ll": "fe80::1234:56ff:fe78:9abc%eth0", "gua": "2001:db8:aaaa:1::24", "lo": "::1", "mc": "ff02::1",
        "wwn": "20:00:00:25:b5:00:00:01", "mac": "aa:bb:cc:dd:ee:ff", "t": "2025-01-01T12:34:56Z", "clock": "12:34:56",
        "url": "https://[2001:db8:aaaa:1::24]:443/redfish"})
    assert _run(inp, out, mp) == 0
    d = _json(out, "h/redfish/v1/index.json")
    assert d["ll"].startswith("fe80::") and d["ll"].endswith("%eth0") and d["ll"] != "fe80::1234:56ff:fe78:9abc%eth0"
    assert d["gua"].startswith("fd") and ipaddress.IPv6Address(d["gua"]) and d["gua"] != "2001:db8:aaaa:1::24"
    assert d["lo"] == "::1" and d["mc"] == "ff02::1"
    assert d["wwn"] == "20:00:00:25:b5:00:00:01" and d["mac"] == "aa:bb:cc:dd:ee:ff"
    assert d["t"] == "2025-01-01T12:34:56Z" and d["clock"] == "12:34:56"
    assert d["url"] == "https://[%s]:443/redfish" % d["gua"] and "2001:db8" not in d["url"]


NL = chr(10)


def test_pem_is_redacted_binary_excluded_and_text_raw_processed(env):
    inp, out, mp = env
    assert _run(inp, out, mp) == 0
    cert = _json(out, "h1/redfish/v1/Certs/1/index.json")["CertificateString"]
    assert cert == NL.join(["-----BEGIN CERTIFICATE-----", "REDACTED", "-----END CERTIFICATE-----"])
    assert not os.path.exists(os.path.join(out, "h1", "redfish", "v1", "Bin", "raw.bin"))
    assert os.path.exists(os.path.join(out, "h1", "redfish", "v1", "Bin", "index.json"))      # 스텁은 남는다
    xml = open(os.path.join(out, "h1", "redfish", "v1", "$metadata", "raw.xml"), encoding="utf-8").read()
    assert "bmc-seoul-01" not in xml and "10.20.30.50" not in xml and "host-" in xml
    rep = _json(out, "_sanitize_report.json")
    assert rep["binary_excluded"] == 1 and rep["binary_list"][0]["file"].endswith("Bin/raw.bin") and rep["replaced"]["pem"] == 1
    out2 = out + "_kept"
    assert _run(inp, out2, mp + "2", "--keep-binary", "--keep-certs", "--no-verify") == 0
    assert _run(inp, out + "_certs", mp + "3", "--keep-certs") == 1                       # 인증서를 남기면 검사가 경고한다
    with open(os.path.join(out2, "h1", "redfish", "v1", "Bin", "raw.bin"), "rb") as f:
        assert f.read() == bytes(bytearray([0, 1, 2, 3, 0x31, 0x30, 0x2e, 0x31]))
    assert "MIIBabc" in _blob(out2)


def test_same_map_is_deterministic_new_map_differs_and_map_is_reused_across_batches(tmp_path, env):
    inp, out, mp = env
    assert _run(inp, out, mp) == 0
    out_b = str(tmp_path / "out_b")
    assert _run(inp, out_b, mp) == 0
    a, b = _read_all(out), _read_all(out_b)
    a.pop("_sanitize_report.json"), b.pop("_sanitize_report.json")
    assert a == b
    out_c = str(tmp_path / "out_c")
    assert _run(inp, out_c, str(tmp_path / "other_map.json")) == 0
    c = _read_all(out_c)
    c.pop("_sanitize_report.json")
    assert c != a
    inp2 = str(tmp_path / "in2")                                              # 다음 배치: 새 호스트, 같은 NTP/게이트웨이
    _mirror(inp2, host="h2", ip="11.65.23.99", name="bmc-busan-02")
    out_d = str(tmp_path / "out_d")
    assert _run(inp2, out_d, mp) == 0
    n1 = _json(out, "h1/redfish/v1/Managers/1/EthernetInterfaces/1/index.json")
    n2 = _json(out_d, "h2/redfish/v1/Managers/1/EthernetInterfaces/1/index.json")
    assert n1["IPv4Addresses"][0]["Gateway"] == n2["IPv4Addresses"][0]["Gateway"]
    assert n1["NameServers"] == n2["NameServers"] and n1["HostName"] != n2["HostName"]
    if os.name == "posix":
        assert os.stat(mp).st_mode & 0o077 == 0


def test_json_formatting_is_preserved(env):
    inp, out, mp = env
    assert _run(inp, out, mp) == 0
    bs = chr(92)
    blank = re.compile('"(?:[^"' + bs + bs + ']|' + bs + bs + '.)*"')
    for rel in ("h1/redfish/v1/Managers/1/EthernetInterfaces/1/index.json", "h1/redfish/v1/Logs/Entries/index.json",
                "h1/_manifest.json"):
        a = open(os.path.join(inp, *rel.split("/")), encoding="utf-8", newline="").read().split(NL)
        b = open(os.path.join(out, *rel.split("/")), encoding="utf-8", newline="").read().split(NL)
        assert len(a) == len(b)
        assert [blank.sub('""', x) for x in a] == [blank.sub('""', x) for x in b]


def test_file_and_folder_names_are_sanitized_and_fsmap_follows(tmp_path):
    inp, out, mp = str(tmp_path / "in"), str(tmp_path / "out"), str(tmp_path / "m.json")
    _mirror(inp)
    _write(inp, "h1/redfish/v1/Hosts/bmc-seoul-01/index.json", {"@odata.id": "/redfish/v1/Hosts/bmc-seoul-01", "Name": "n"})
    _write(inp, "h1/redfish/v1/Hosts/10.20.30.40/index.json", {"@odata.id": "/redfish/v1/Hosts/10.20.30.40"})
    _write(inp, "h1/_fsmap.json", {"/redfish/v1/Hosts/bmc-seoul-01": {"dir": "redfish/v1/Hosts/bmc-seoul-01"}})
    assert _run(inp, out, mp) == 0
    names = os.listdir(os.path.join(out, "h1", "redfish", "v1", "Hosts"))
    assert len(names) == 2 and all("bmc-seoul-01" not in n and "10.20.30.40" not in n for n in names)
    fsmap = _json(out, "h1/_fsmap.json")
    (req, ent), = fsmap.items()
    assert ent["dir"].rsplit("/", 1)[1] in names and req.rsplit("/", 1)[1] in names
    assert _json(out, "h1/redfish/v1/Hosts/" + ent["dir"].rsplit("/", 1)[1] + "/index.json")["Name"] == "n"


def test_multiple_inputs_with_same_named_host_dirs_do_not_overwrite_each_other(tmp_path):
    a, b = str(tmp_path / "famA"), str(tmp_path / "famB")
    _mirror(a, host="01", ip="11.65.23.24", name="bmc-seoul-01")
    _mirror(b, host="01", ip="11.65.23.99", name="bmc-busan-02")
    out, mp = str(tmp_path / "out"), str(tmp_path / "m.json")
    assert _run([a, b], out, mp) == 0
    assert sorted(os.listdir(out)) == ["_sanitize_report.json", "famA", "famB"]
    ha = _json(out, "famA/01/redfish/v1/Managers/1/NetworkProtocol/index.json")["HostName"]
    hb = _json(out, "famB/01/redfish/v1/Managers/1/NetworkProtocol/index.json")["HostName"]
    assert ha != hb
    san = sm.Sanitizer(sm.Mapper())
    san.build()
    san.sub_text = lambda text, key=None: "x"                                  # 서로 다른 원본이 같은 경로로 모이면 거부
    with pytest.raises(sm.SanitizeError):
        sm.sanitize([a], str(tmp_path / "out2"), san, write=False)


def test_verify_detects_planted_leaks_and_passes_a_clean_copy(env, capsys):
    inp, out, mp = env
    assert _run(inp, out, mp) == 0
    assert sm.main(["--verify", out, "--map", mp]) == 0
    capsys.readouterr()
    idx = os.path.join(out, "h1", "redfish", "v1", "index.json")
    doc = _json(out, "h1/redfish/v1/index.json")
    doc["Note"] = "see 11.65.23.24, bmc-seoul-01 and 11.65.77.9"
    with open(idx, "w", encoding="utf-8") as f:
        json.dump(doc, f)
    assert sm.main(["--verify", out, "--map", mp]) == 1
    shown = capsys.readouterr().out
    assert "leak_ip" in shown and "leak_host" in shown and "residual_ip" in shown and "Note" in shown
    for real in ("11.65.23.24", "bmc-seoul-01", "11.65.77.9"):
        assert real not in shown                                                # 검사 출력에도 실제 값은 없다


def test_guards_exit_codes_and_dry_run(tmp_path, env):
    inp, out, mp = env
    assert sm.main([inp, "--out", os.path.join(inp, "sub"), "--map", mp]) == 2                  # 사본이 입력 안
    assert sm.main([inp, "--out", out, "--map", os.path.join(out, "m.json")]) == 2              # 대응표가 사본 안
    assert sm.main([inp, "--map", mp]) == 2                                                     # --out 없음
    assert sm.main([str(tmp_path / "nothing"), "--out", out, "--map", mp]) == 2                 # 입력 폴더 없음
    assert not os.path.exists(out) and not os.path.exists(mp)
    assert sm.main([inp, "--dry-run", "--map", mp]) == 0
    assert not os.path.exists(out) and not os.path.exists(mp)                                   # 아무것도 쓰지 않는다
    assert _run(inp, out, mp) == 0
    assert _run(inp, out, mp) == 2                                                              # 비어 있지 않은 사본 폴더
    assert _run(out, str(tmp_path / "again"), mp) == 2                                          # 이미 처리한 사본 재처리


def test_warns_when_a_host_folder_name_ends_with_the_ip_last_octet(tmp_path, capsys):
    inp, out, mp = str(tmp_path / "in"), str(tmp_path / "out"), str(tmp_path / "m.json")
    _mirror(inp, host="box_24", ip="11.65.23.24")
    _mirror(inp, host="box_01", ip="11.65.23.31", name="bmc-busan-02")
    assert _run(inp, out, mp) == 0
    assert _json(out, "_sanitize_report.json")["folder_name_hints"] == 1         # box_24 만 (box_01 은 마지막 자리 31 과 다름)
    assert "WARN" in capsys.readouterr().out


def test_report_has_counts_but_no_real_values(env):
    inp, out, mp = env
    assert _run(inp, out, mp) == 0
    text = open(os.path.join(out, "_sanitize_report.json"), encoding="utf-8").read()
    for real in REAL_IPS + REAL_NAMES:
        assert real not in text
    rep = json.loads(text)
    assert rep["replaced"]["ipv4"] >= 8 and rep["replaced"]["hostname"] >= 5 and rep["replaced"]["ipv6"] == 2
    assert rep["other_identifiers_not_replaced"].get("mac") == 1 and rep["distinct"]["ipv4"] == 8
    assert rep["kept"]["v4_kept_versionkey"] >= 1 and rep["kept"]["v4_kept_mask"] == 1


def test_extra_host_extra_domain_and_protect_options(tmp_path):
    inp, mp = str(tmp_path / "in"), str(tmp_path / "m.json")
    _write(inp, "h/redfish/v1/index.json", {
        "Note": "contact 10.1.2.3 about secretapp01 and app1.internal.lan",
        "Info": "10.1.2.4", "HostName": "localhost", "Other": "bmc"})
    out = str(tmp_path / "o1")
    assert _run(inp, out, mp, "--extra-host", "secretapp01", "--extra-domain", "internal.lan") == 0
    d = _json(out, "h/redfish/v1/index.json")
    assert "secretapp01" not in d["Note"] and "internal.lan" not in d["Note"] and "10.1.2.3" not in d["Note"]
    assert d["HostName"] == "localhost" and d["Other"] == "bmc"                 # 흔한 단어는 배우지 않는다
    out2 = str(tmp_path / "o2")
    assert _run(inp, out2, str(tmp_path / "m2.json"), "--protect-key", "^Info$", "--protect-text", "contact ") == 0
    d2 = _json(out2, "h/redfish/v1/index.json")
    assert d2["Info"] == "10.1.2.4" and "10.1.2.3" in d2["Note"]                # 사용자가 보호한 값은 그대로
    assert sm.main(["--verify", out2, "--map", str(tmp_path / "m2.json"), "--protect-key", "^Info$",
                    "--protect-text", "contact "]) == 0


def test_public_hosts_and_stop_words_are_not_learned():
    m = sm.Mapper()
    for token in ("localhost", "bmc", "idrac", "abc", "1234", "redfish.dmtf.org", "support.hpe.com", "10.1.2.3", ""):
        assert m.learn_host(token) is False, token
    assert m.learn_host("bmc-seoul-01.corp.example.co.kr") is True
    assert "bmc-seoul-01" in m.names and "corp.example.co.kr" in m.dom
    assert m.map_name("bmc-seoul-01.corp.example.co.kr") == m.label("bmc-seoul-01") + "." + m.dom["corp.example.co.kr"]


def test_mapper_ipv4_is_injective_groups_subnets_and_keeps_special_values():
    m = sm.Mapper()
    reals = ["10.%d.%d.%d" % (b, c, d) for b in (1, 2) for c in range(0, 40) for d in (1, 2, 50, 254)]
    fakes = [m.ip4(x) for x in reals]
    assert len(set(fakes)) == len(reals)                                         # 서로 다른 실제 주소는 서로 다른 가짜 주소
    assert all(ipaddress.ip_address(x).is_private for x in fakes)
    by24 = {}
    for r, f in zip(reals, fakes):
        by24.setdefault(r.rsplit(".", 1)[0], set()).add(f.rsplit(".", 1)[0])
    assert all(len(v) == 1 for v in by24.values())                               # 같은 실제 /24 -> 같은 가짜 /24
    assert len(set(next(iter(v)) for v in by24.values())) == len(by24)          # 다른 /24 -> 다른 가짜 /24
    for keep in ("0.0.0.0", "255.255.255.255", "127.0.0.1", "169.254.0.2", "224.0.0.251", "255.255.252.0", "192.0.2.5"):
        assert m.ip4(keep) == keep
    assert m.ip4(".".join(["10", "1", "0", "0"])).endswith(".0")                 # 네트워크 주소의 .0 은 유지
    m2 = sm.Mapper()
    with pytest.raises(sm.SanitizeError):
        for i in range(1, 300):
            m2.ip4("%d.%d.1.1" % (20 + i // 256, i % 256))                       # /16 이 271개를 넘으면 정직하게 실패


def test_scan_strings_reports_the_key_of_each_value():
    text = '{"a": "x", "b": ["y", {"c": "z"}], "d": {"e": ["p", "q"]}, "f": "w"}'
    got = [(text[s:e], k, key) for s, e, k, key in sm.scan_strings(text)]
    assert got == [("a", True, "a"), ("x", False, "a"), ("b", True, "b"), ("y", False, "b"), ("c", True, "c"),
                   ("z", False, "c"), ("d", True, "d"), ("e", True, "e"), ("p", False, "e"), ("q", False, "e"),
                   ("f", True, "f"), ("w", False, "f")]


@pytest.mark.skipif(sys.version_info < (3, 8), reason="ast.parse(feature_version=) 는 Python 3.8+ 에만 있다")
def test_source_stays_python36_compatible():
    import ast
    src = open(os.path.join(PROBE, "sanitize_mirror.py"), encoding="utf-8").read()
    tree = ast.parse(src, feature_version=(3, 6))
    assert "from __future__ import annotations" not in src
    for banned in ("fromisoformat", "removeprefix", "removesuffix", "capture_output"):
        assert banned not in src, banned
    for node in ast.walk(tree):
        for a in (getattr(node, "annotation", None), getattr(node, "returns", None)):
            assert not isinstance(a, ast.Subscript)


def test_gather_on_a_sanitized_mirror_equals_the_mapped_gather_on_the_original(tmp_path):
    """게더링이 깨지지 않는다는 증거: 합성 CSUS 트리를 크롤 -> 치환 -> 게더링 재생했을 때,
    사본의 게더링 결과 = 원본의 게더링 결과에 같은 대응표를 적용한 것. 바뀐 필드는 IP/호스트 이름 값뿐이다."""
    if sys.version_info < (3, 7):
        pytest.skip("개발용 재생기(replay_full_mirror)는 Python 3.7+ 에서만 돈다")
    from pathlib import Path
    for extra in (os.path.join(REPO, "tests", "integration"), os.path.join(REPO, "redfish-gather", "library")):
        if extra not in sys.path:
            sys.path.insert(0, extra)
    import capture_mirror_fixture as cap
    import _serve_fixtures_as_redfish as srv
    import test_full_mirror_dryrun as crawl_tests
    res = srv.load(os.path.join(REPO, "tests", "fixtures", "redfish", "hpe_csus_3200"))
    nic = "/redfish/v1/Managers/RMC/EthernetInterfaces"
    res[nic] = {"@odata.id": nic, "Members": [{"@odata.id": nic + "/1"}], "Members@odata.count": 1, "Name": "nics"}
    res[nic + "/1"] = {
        "@odata.id": nic + "/1", "Id": "1", "Name": "Manager Ethernet Interface", "HostName": "rmc-seoul-01",
        "FQDN": "rmc-seoul-01.corp.example.co.kr", "MACAddress": "AA:BB:CC:00:11:22", "LinkStatus": "LinkUp",
        "IPv4Addresses": [{"Address": "11.65.23.24", "Gateway": "11.65.23.1", "SubnetMask": "255.255.255.0",
                           "AddressOrigin": "Static"}], "NameServers": ["11.65.1.10"]}
    mirror = str(tmp_path / "mirror")
    with crawl_tests._serve(res) as port:
        assert crawl_tests._crawl(port, mirror) == 0
    clean, mp = str(tmp_path / "clean"), str(tmp_path / "m.json")
    assert sm.main([mirror, "--out", clean, "--map", mp]) == 0
    layout = {"manager_layout": "rmc_primary", "firmware_scope": "complex_only"}
    _rec_o, gold_o, _s_o, vendor_o, status_o = cap.build(Path(mirror), **layout)
    _rec_s, gold_s, _s_s, vendor_s, status_s = cap.build(Path(clean) / os.path.basename(mirror), **layout)
    assert (vendor_o, status_o) == (vendor_s, status_s) and vendor_o == "hpe"
    mapper = sm.load_map(mp)
    san = sm.Sanitizer(mapper)
    san.build()

    def mapped(obj):
        return json.loads(san.rewrite_json(json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2)))

    assert mapped(gold_o) == gold_s                                              # 사본 결과 == 원본 결과를 같은 규칙으로 바꾼 것
    assert mapped(gold_o) != gold_o                                              # 그리고 실제로 바뀐 필드가 있다 (공허한 비교 아님)
    blob = json.dumps(gold_s, ensure_ascii=False)
    for real in REAL_IPS + REAL_NAMES:
        assert real not in blob
