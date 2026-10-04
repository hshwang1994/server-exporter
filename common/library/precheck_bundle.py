#!/usr/bin/python3
# -*- coding: utf-8 -*-

__metaclass__ = type


from ansible.module_utils.basic import AnsibleModule
import base64
import http.client
import json
import math
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


CHANNEL_DEFAULT_PORTS = {
    "redfish": [443],
    "os": [5986, 5985, 22],
    "esxi": [443],
}

FAILURE_REASON_CATALOG = {
    "ip_invalid": {
        "default": "대상 IP가 올바르지 않습니다. 개더링 대상 IP를 확인하세요.",
    },
    "target_unreachable": {
        "default": "대상 서버가 응답하지 않습니다. 서버 전원 상태와 네트워크 연결을 확인하세요.",
    },
    "port_silent": {
        "default": "대상 서버와 통신은 되지만 관리 포트에 연결할 수 없습니다. "
                   "방화벽과 접속 설정을 확인하세요.",
    },
    "port_refused": {
        "os": "OS 접속이 거부되었습니다. 대상 서버의 OS 원격 접속 설정과 방화벽을 확인하세요.",
        "esxi": "ESXi 접속이 거부되었습니다. 대상 서버의 ESXi 접속 설정과 방화벽을 확인하세요.",
        "redfish": "Redfish 접속이 거부되었습니다. "
                   "대상 장비의 Redfish 접속 설정과 방화벽을 확인하세요.",
        "default": "관리 포트 접속이 거부되었습니다. 대상의 접속 설정과 방화벽을 확인하세요.",
    },
    "protocol_unconfirmed": {
        "os": "접속한 대상에서 OS 원격 접속 응답을 확인하지 못했습니다. "
              "대상 종류와 OS 원격 접속 설정을 확인하세요.",
        "esxi": "접속한 대상에서 ESXi 응답을 확인하지 못했습니다. "
                "대상 종류와 ESXi 서비스 상태를 확인하세요.",
        "redfish": "접속한 대상에서 Redfish 응답을 확인하지 못했습니다. "
                   "대상 종류와 Redfish 서비스 설정을 확인하세요.",
        "default": "접속한 대상에서 필요한 응답을 확인하지 못했습니다. "
                   "대상 종류와 접속 설정을 확인하세요.",
    },
    "auth_unconfirmed": {
        "os": "해당 위치({loc})의 Vault 계정으로 대상 OS에 로그인하지 못했습니다.",
        "esxi": "해당 위치({loc})의 Vault 계정으로 대상 ESXi에 로그인하지 못했습니다.",
        "redfish": "개더링 표준 계정으로 대상 Redfish에 인증하지 못했습니다.",
        "default": "해당 위치({loc})의 Vault 계정으로 대상에 로그인하지 못했습니다.",
    },
}

PRECHECK_REASON_KEYS = {
    "DNS_RESOLUTION_FAILED":  "ip_invalid",
    "TARGET_UNREACHABLE":     "target_unreachable",
    "TCP_CONNECT_FAILED":     "port_silent",
    "TCP_CONNECTION_REFUSED": "port_refused",
    "PROTOCOL_CHECK_FAILED":  "protocol_unconfirmed",
    "AUTH_PROBE_FAILED":      "auth_unconfirmed",
}

_LOC_UNKNOWN = "미지정"


def reason_for_failure(failure_code, channel=None):
    entry = FAILURE_REASON_CATALOG[
        PRECHECK_REASON_KEYS.get(failure_code, "target_unreachable")]
    text = entry.get(channel) if channel else None
    if text is None:
        text = entry["default"]
    return text.replace("{loc}", _LOC_UNKNOWN)


TCP_FAIL_DNS = "dns"
TCP_FAIL_REFUSED = "refused"
TCP_FAIL_TIMEOUT = "timeout"
TCP_FAIL_OTHER = "other"


def tcp_check_ex(host, port, timeout):
    last_err = "주소 해석 실패"
    last_kind = TCP_FAIL_OTHER
    try:
        addr_infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        return False, "DNS 해석 실패: {0}".format(e), TCP_FAIL_DNS
    for family, socktype, proto, _canon, sockaddr in addr_infos:
        sock = None
        try:
            sock = socket.socket(family, socktype, proto)
            sock.settimeout(timeout)
            sock.connect(sockaddr)
            return True, None, None
        except socket.timeout:
            last_err = "연결 시간 초과 (timeout={0}s)".format(timeout)
            last_kind = TCP_FAIL_TIMEOUT
        except ConnectionRefusedError:
            last_err = "연결 거부됨 (port={0})".format(port)
            last_kind = TCP_FAIL_REFUSED
        except OSError as e:
            last_err = str(e)
            last_kind = TCP_FAIL_OTHER
        finally:
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass
    return False, last_err, last_kind


def tcp_check(host, port, timeout):
    ok, err, _kind = tcp_check_ex(host, port, timeout)
    return ok, err


_ICMP_DEFAULT_TIMEOUT = 1.0
_ICMP_SPAWN_MARGIN = 1.0


def _icmp_command(host, timeout):
    millis = max(1, int(timeout * 1000))
    secs = max(1, int(math.ceil(timeout)))
    if sys.platform.startswith("win"):
        return ["ping", "-n", "1", "-w", str(millis), host]
    if sys.platform == "darwin":
        return ["ping", "-c", "1", "-n", "-W", str(millis), "-t", str(secs), host]
    return ["ping", "-c", "1", "-n", "-W", str(secs), "-w", str(secs), host]


def icmp_check(host, timeout=_ICMP_DEFAULT_TIMEOUT):
    try:
        proc = subprocess.run(
            _icmp_command(host, timeout),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout + _ICMP_SPAWN_MARGIN,
        )
    except FileNotFoundError:
        return False, "icmp: 확인 불가 (ping 명령 없음)"
    except subprocess.TimeoutExpired:
        return False, "icmp: 응답 없음 (timeout={0}s)".format(timeout)
    except OSError as e:
        return False, "icmp: 확인 불가 ({0})".format(e)

    if proc.returncode != 0:
        return False, "icmp: 응답 없음 (rc={0})".format(proc.returncode)
    if sys.platform.startswith("win"):
        stdout = (proc.stdout or b"").lower()
        if b"ttl=" not in stdout:
            return False, "icmp: 응답 없음 (Echo Reply 아님)"
    return True, "icmp: Echo Reply 확인"


_WAIT_FOR_CONNECT_TIMEOUT = 5.0
_WAIT_FOR_SLEEP = 1.0


def _dominant_kind(kinds):
    if TCP_FAIL_DNS in kinds:
        return TCP_FAIL_DNS
    if TCP_FAIL_REFUSED in kinds:
        return TCP_FAIL_REFUSED
    if TCP_FAIL_TIMEOUT in kinds:
        return TCP_FAIL_TIMEOUT
    return TCP_FAIL_OTHER


def tcp_check_budget(host, port, budget, poll_interval,
                     connect_timeout=_WAIT_FOR_CONNECT_TIMEOUT):
    if not poll_interval or poll_interval <= 0:
        return tcp_check_ex(host, port, budget)

    deadline = time.monotonic() + budget
    errs = []
    kinds = []
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        ok, err, kind = tcp_check_ex(
            host, port, min(connect_timeout, math.ceil(remaining)))
        if ok:
            return True, None, None
        errs.append(err)
        kinds.append(kind)
        if deadline - time.monotonic() <= 0:
            break
        time.sleep(poll_interval)

    if not kinds:
        return tcp_check_ex(host, port, budget)
    kind = _dominant_kind(kinds)
    err = next((e for e, k in zip(reversed(errs), reversed(kinds)) if k == kind), errs[-1])
    return False, err, kind


def _build_ssl_context(verify):
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        if hasattr(ssl, 'OP_LEGACY_SERVER_CONNECT'):
            ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
        try:
            ctx.set_ciphers('DEFAULT@SECLEVEL=0')
        except ssl.SSLError:
            pass
    return ctx


def _basic_auth_header(auth):
    if not auth:
        return None
    credentials = base64.b64encode(
        "{0}:{1}".format(auth[0], auth[1]).encode()
    ).decode()
    return "Basic " + credentials


def _collect_headers(msg):
    out = {}
    if msg is None:
        return out
    try:
        names = {k.lower() for k in msg.keys()}
    except Exception:
        return out
    for name in names:
        try:
            values = msg.get_all(name) or []
        except Exception:
            values = []
        out[name] = ", ".join(str(v) for v in values)
    return out


def http_get(url, timeout, verify=False, auth=None):
    ctx = _build_ssl_context(verify)
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/json")
    auth_header = _basic_auth_header(auth)
    if auth_header:
        req.add_header("Authorization", auth_header)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            status = resp.getcode()
            headers = _collect_headers(getattr(resp, "headers", None))
        try:
            json_body = json.loads(body)
        except (ValueError, json.JSONDecodeError):
            json_body = None
        return True, None, {
            "status_code": status, "json": json_body, "headers": headers,
        }
    except urllib.error.HTTPError as e:
        return False, "HTTP {0}".format(e.code), {
            "status_code": e.code,
            "json": None,
            "headers": _collect_headers(getattr(e, "headers", None)),
        }
    except socket.timeout:
        return False, "요청 시간 초과 (timeout={0}s)".format(timeout), None
    except urllib.error.URLError as e:
        return False, "연결 실패: {0}".format(str(e.reason)[:200]), None
    except (ssl.SSLError, OSError) as e:
        return False, str(e)[:200], None


_SSH_ID_MAX_LINES = 8
_SSH_ID_MAX_BYTES = 2048
_SSH_ID_PREFIXES = ("SSH-2.0-", "SSH-1.99-")


def _read_ssh_identification(sock, deadline):
    buf = b""
    lines = 0
    while len(buf) < _SSH_ID_MAX_BYTES and lines < _SSH_ID_MAX_LINES:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        sock.settimeout(remaining)
        chunk = sock.recv(256)
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            raw, buf = buf.split(b"\n", 1)
            lines += 1
            line = raw.decode("utf-8", errors="replace").strip()
            if line.startswith(_SSH_ID_PREFIXES):
                return line
            if line.startswith("SSH-"):
                return line
            if lines >= _SSH_ID_MAX_LINES:
                return None
    return None


def ssh_banner_check(host, port, timeout):
    last_err = "주소 해석 실패"
    try:
        addr_infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        return False, "DNS 해석 실패: {0}".format(e), None
    for family, socktype, proto, _canon, sockaddr in addr_infos:
        sock = None
        try:
            deadline = time.monotonic() + timeout
            sock = socket.socket(family, socktype, proto)
            sock.settimeout(timeout)
            sock.connect(sockaddr)
            ident = _read_ssh_identification(sock, deadline)
            if ident is None:
                last_err = "SSH identification 미수신"
            elif ident.startswith(_SSH_ID_PREFIXES):
                return True, None, {}
            else:
                last_err = "지원하지 않는 SSH protoversion: {0}".format(ident[:40])
        except Exception as e:
            last_err = str(e)[:120]
        finally:
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass
    return False, last_err, None


_SERVICE_ROOT_TYPE_PREFIX = "#ServiceRoot."
_SERVICE_ROOT_ODATA_IDS = frozenset({"/redfish/v1", "/redfish/v1/"})


def parse_service_root(json_data):
    if not isinstance(json_data, dict):
        return False, None, "본문이 JSON object 가 아님 ({0})".format(
            type(json_data).__name__)

    odata_type = json_data.get("@odata.type")
    if not isinstance(odata_type, str) or not odata_type.startswith(_SERVICE_ROOT_TYPE_PREFIX):
        return False, None, "ServiceRoot 리소스가 아님 (@odata.type={0})".format(
            str(odata_type)[:48] if odata_type is not None else "없음")

    odata_id = json_data.get("@odata.id")
    if not isinstance(odata_id, str) or odata_id not in _SERVICE_ROOT_ODATA_IDS:
        return False, None, "ServiceRoot URI 불일치 (@odata.id={0})".format(
            str(odata_id)[:48] if odata_id is not None else "없음")

    version = json_data.get("RedfishVersion")
    if not isinstance(version, str) or not version.strip():
        return False, None, "RedfishVersion 없음"

    systems = json_data.get("Systems")
    facts = {
        "redfish_version": version,
        "product": json_data.get("Product"),
        "systems_uri": systems.get("@odata.id") if isinstance(systems, dict) else None,
    }
    return True, facts, "ServiceRoot 확인"


def probe_redfish(host, port, timeout, verify=False):
    import time as _time
    url = "https://{0}:{1}/redfish/v1/".format(host, port)

    last_err = None
    for attempt in (1, 2):
        ok, err, payload = http_get(url, timeout, verify=verify)

        if ok:
            is_root, facts, why = parse_service_root(
                payload.get("json") if payload else None)
            if is_root:
                if attempt > 1:
                    facts["retry_count"] = attempt - 1
                return True, None, facts
            return False, "Redfish ServiceRoot 아님 (HTTP {0}, {1})".format(
                (payload or {}).get("status_code"), why), None

        if payload is not None:
            return False, "Redfish ServiceRoot 응답 아님 (HTTP {0})".format(
                payload.get("status_code")), None

        last_err = err
        if attempt == 1:
            _time.sleep(1)

    return False, last_err, None


WINRM_ENDPOINT_PATH = "/wsman"

_SOAP_ENVELOPE_NS = "http://www.w3.org/2003/05/soap-envelope"

_WSMID_NAMESPACES = frozenset({
    "http://schemas.dmtf.org/wbem/wsman/identity/1/wsmanidentity.xsd",
    "https://schemas.dmtf.org/wbem/wsman/identity/1/wsmanidentity.xsd",
    "http://schemas.dmtf.org/wbem/wsman/identity/1/wsmanidentity",
    "https://schemas.dmtf.org/wbem/wsman/identity/1/wsmanidentity",
})

_WSMAN_PROTOCOL_PREFIXES = (
    "http://schemas.dmtf.org/wbem/wsman/1/wsman",
    "https://schemas.dmtf.org/wbem/wsman/1/wsman",
)

_WINRM_VENDOR_MARKER = "microsoft"

_IDENTIFY_REQUEST = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"'
    ' xmlns:wsmid="http://schemas.dmtf.org/wbem/wsman/identity/1/wsmanidentity.xsd">'
    "<s:Header/><s:Body><wsmid:Identify/></s:Body></s:Envelope>"
).encode("utf-8")

_IDENTIFY_MAX_BYTES = 65536

_SOAP12_CONTENT_TYPE = "application/soap+xml;charset=UTF-8"


def http_post_soap(url, body, timeout, verify=False, extra_headers=None,
                   content_type=_SOAP12_CONTENT_TYPE, max_bytes=_IDENTIFY_MAX_BYTES):
    parts = urllib.parse.urlsplit(url)
    host, port = parts.hostname, parts.port
    path = parts.path or "/"
    if parts.query:
        path = "{0}?{1}".format(path, parts.query)
    headers = {"Content-Type": content_type}
    headers.update(extra_headers or {})

    conn = None
    try:
        if parts.scheme == "https":
            conn = http.client.HTTPSConnection(
                host, port or 443, timeout=timeout, context=_build_ssl_context(verify)
            )
        else:
            conn = http.client.HTTPConnection(host, port or 80, timeout=timeout)
        conn.request("POST", path, body=body, headers=headers)
        resp = conn.getresponse()
        raw = resp.read(max_bytes)
        status = resp.status
        if 200 <= status < 300:
            return True, None, {"status_code": status, "body": raw}
        return False, "HTTP {0}".format(status), {"status_code": status, "body": raw}
    except socket.timeout:
        return False, "요청 시간 초과 (timeout={0}s)".format(timeout), None
    except (ssl.SSLError, http.client.HTTPException, OSError) as e:
        return False, "연결 실패: {0}".format(str(e)[:200]), None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def parse_identify_response(raw):
    if not raw:
        return False, None, "응답 본문 없음"
    if len(raw) > _IDENTIFY_MAX_BYTES:
        return False, None, "응답 본문이 상한을 초과"
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        return False, None, "XML 파싱 실패: {0}".format(str(e)[:80])

    identify = None
    for elem in root.iter():
        if not isinstance(elem.tag, str) or not elem.tag.startswith("{"):
            continue
        ns, _sep, local = elem.tag[1:].partition("}")
        if local == "IdentifyResponse" and ns in _WSMID_NAMESPACES:
            identify = elem
            break
    if identify is None:
        return False, None, "IdentifyResponse 없음 (WS-Management 네임스페이스 불일치)"

    fields = {}
    for child in identify:
        if not isinstance(child.tag, str) or not child.tag.startswith("{"):
            continue
        ns, _sep, local = child.tag[1:].partition("}")
        if ns in _WSMID_NAMESPACES:
            fields[local] = (child.text or "").strip()

    protocol = fields.get("ProtocolVersion", "")
    if not protocol.startswith(_WSMAN_PROTOCOL_PREFIXES):
        return False, None, "ProtocolVersion 이 WS-Management 가 아님: {0}".format(
            protocol[:60] or "없음")

    vendor = fields.get("ProductVendor")
    if vendor is None:
        return False, None, "ProductVendor 없음"
    return True, vendor, "IdentifyResponse 확인"


def probe_os(host, port, timeout):
    if port == 22:
        return ssh_banner_check(host, port, timeout)
    if port in (5985, 5986):
        scheme = "https" if port == 5986 else "http"
        url = "{0}://{1}:{2}{3}".format(scheme, host, port, WINRM_ENDPOINT_PATH)
        ok, err, payload = http_post_soap(
            url, _IDENTIFY_REQUEST, timeout, verify=False,
            extra_headers={"WSMANIDENTIFY": "unauthenticated"},
        )
        if payload is None:
            return False, err or "WinRM endpoint 응답 없음", None

        is_wsman, vendor, why = parse_identify_response(payload.get("body"))
        if not is_wsman:
            return False, "WS-Management IdentifyResponse 아님 (HTTP {0}, {1})".format(
                payload.get("status_code"), why), None
        if _WINRM_VENDOR_MARKER not in (vendor or "").lower():
            return False, "WS-Management 는 응답하나 Windows WinRM 이 아님 (vendor={0})".format(
                (vendor or "미제공")[:40]), None
        return True, None, {}
    return False, "지원하지 않는 OS 포트: {0}".format(port), None


_VIM25_NS = "urn:vim25"
_VSPHERE_FAULT_NAMESPACES = frozenset({"urn:vim25", "urn:internalvim25"})
_SOAP11_ENVELOPE_NS = "http://schemas.xmlsoap.org/soap/envelope/"
_SOAP11_CONTENT_TYPE = "text/xml; charset=UTF-8"
_VSPHERE_API_VERSION = "6.0"
_SERVICE_CONTENT_RESPONSE = "RetrieveServiceContentResponse"
_SERVICE_CONTENT_MAX_BYTES = 262144

_RETRIEVE_SERVICE_CONTENT_REQUEST = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<soapenv:Envelope'
    ' xmlns:soapenc="http://schemas.xmlsoap.org/soap/encoding/"'
    ' xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"'
    ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
    ' xmlns:xsd="http://www.w3.org/2001/XMLSchema">\n'
    "<soapenv:Body>"
    '<RetrieveServiceContent xmlns="urn:vim25">'
    '<_this versionId="{0}" type="ServiceInstance">ServiceInstance</_this>'
    "</RetrieveServiceContent>"
    "</soapenv:Body>\n"
    "</soapenv:Envelope>"
).format(_VSPHERE_API_VERSION).encode("utf-8")


def _vim_child(parent, local):
    found = parent.find("{{{0}}}{1}".format(_VIM25_NS, local))
    if found is None:
        found = parent.find(local)
    return found


def _vim_text(parent, local):
    node = _vim_child(parent, local)
    if node is None or node.text is None:
        return None
    text = node.text.strip()
    return text or None


def _vim25_fault_local_name(fault):
    for elem in fault.iter():
        tag = elem.tag
        if not isinstance(tag, str) or not tag.startswith("{"):
            continue
        ns, _sep, local = tag[1:].partition("}")
        if ns in _VSPHERE_FAULT_NAMESPACES and local:
            return local
    return None


def parse_service_content(raw):
    if not raw:
        return False, None, "응답 본문 없음"
    if len(raw) > _SERVICE_CONTENT_MAX_BYTES:
        return False, None, "응답 본문이 상한을 초과"
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        return False, None, "XML 파싱 실패: {0}".format(str(e)[:80])

    if root.tag != "{{{0}}}Envelope".format(_SOAP11_ENVELOPE_NS):
        return False, None, "SOAP 1.1 Envelope 아님 (root={0})".format(str(root.tag)[:60])

    response = root.find(".//{{{0}}}{1}".format(_VIM25_NS, _SERVICE_CONTENT_RESPONSE))
    if response is not None:
        return _parse_service_content_returnval(response)

    fault = root.find(".//{{{0}}}Fault".format(_SOAP11_ENVELOPE_NS))
    if fault is not None:
        name = _vim25_fault_local_name(fault)
        if name:
            return True, {"evidence": "vim25_fault", "fault": name}, "vim25 Fault"
        return False, None, "vSphere 고유 구조가 없는 일반 SOAP Fault"

    return False, None, "{0} 없음".format(_SERVICE_CONTENT_RESPONSE)


def _parse_service_content_returnval(response):
    returnval = _vim_child(response, "returnval")
    if returnval is None:
        return False, None, "returnval 없음"
    about = _vim_child(returnval, "about")
    if about is None:
        return False, None, "ServiceContent.about 없음"
    api_type = _vim_text(about, "apiType")
    if not api_type:
        return False, None, "about.apiType 없음"
    api_version = _vim_text(about, "apiVersion")
    if not api_version:
        return False, None, "about.apiVersion 없음"
    return True, {
        "evidence": "service_content",
        "api_type": api_type,
        "api_version": api_version,
        "product_line_id": _vim_text(about, "productLineId"),
        "version": _vim_text(about, "version"),
    }, "ServiceContent 확인"


def probe_esxi(host, port, timeout, verify=False):
    url = "https://{0}:{1}/sdk".format(host, port)
    ok, err, payload = http_post_soap(
        url, _RETRIEVE_SERVICE_CONTENT_REQUEST, timeout, verify=verify,
        content_type=_SOAP11_CONTENT_TYPE,
        extra_headers={
            "SOAPAction": '"urn:vim25/{0}"'.format(_VSPHERE_API_VERSION),
        },
        max_bytes=_SERVICE_CONTENT_MAX_BYTES,
    )
    raw = (payload or {}).get("body")
    status = (payload or {}).get("status_code")
    if not raw:
        return False, err or "vSphere API endpoint 응답 없음", None

    is_vsphere, _probe, why = parse_service_content(raw)
    if not is_vsphere:
        detail = "vSphere ServiceContent 응답 아님 ({0})".format(why)
        if status is not None:
            detail = "{0} [HTTP {1}]".format(detail, status)
        return False, detail, None

    facts = {"vsphere_endpoint": url}
    if status is not None and status != 200:
        facts["root_status_code"] = status
    return True, None, facts


def _init_result(channel, ports):
    result = {
        "changed": False,
        "reachable": False,
        "port_open": False,
        "protocol_supported": False,
        "auth_success": None,
        "failure_stage": None,
        "failure_code": None,
        "failure_reason": None,
        "detail": None,
        "checked_ports": ports,
        "selected_port": None,
        "probe_facts": {},
    }
    if channel == "os":
        result["detected_os"] = None
        result["detected_port"] = None
        result["winrm_scheme"] = None
    return result


def _check_ports(host, ports, timeout_port, poll_interval=0.0):
    any_response = False
    target_port_open = False
    open_port = None
    port_errors = []
    kinds = []
    probed = []
    for port in ports:
        probed.append(port)
        ok, err, kind = tcp_check_budget(host, port, timeout_port, poll_interval)
        if ok:
            any_response = True
            target_port_open = True
            open_port = port
            break
        if kind == TCP_FAIL_REFUSED:
            any_response = True
        kinds.append(kind)
        port_errors.append("port={0}: {1}".format(port, err))
    return any_response, target_port_open, open_port, port_errors, kinds, probed


def _tcp_failure_code(kinds):
    if TCP_FAIL_DNS in kinds:
        return "DNS_RESOLUTION_FAILED"
    if TCP_FAIL_REFUSED in kinds:
        return "TCP_CONNECTION_REFUSED"
    return "TARGET_UNREACHABLE"


def _resolve_reachability(module, host, kinds):
    code = _tcp_failure_code(kinds)
    if code == "DNS_RESOLUTION_FAILED":
        return False, "reachable", code, None
    if code == "TCP_CONNECTION_REFUSED":
        return True, "port", code, None
    if not module.params.get("icmp_probe", True):
        return False, "reachable", code, None

    replied, note = icmp_check(
        host, module.params.get("timeout_icmp", _ICMP_DEFAULT_TIMEOUT))
    if replied:
        return True, "port", "TCP_CONNECT_FAILED", note
    return False, "reachable", "TARGET_UNREACHABLE", note


def _join_detail(port_errors, icmp_note=None):
    parts = list(port_errors)
    if icmp_note:
        parts.append(icmp_note)
    return "; ".join(parts)


def _search_os_candidates(host, ports, timeout_port, poll_interval, timeout_proto):
    selected = None
    probed = []
    tcp_open_ports = []
    tcp_errors = []
    tcp_kinds = []
    proto_errors = []

    for port in ports:
        probed.append(port)
        ok, err, kind = tcp_check_budget(host, port, timeout_port, poll_interval)
        if not ok:
            tcp_kinds.append(kind)
            tcp_errors.append("port={0}: {1}".format(port, err))
            continue

        tcp_open_ports.append(port)
        p_ok, p_err, _facts = probe_os(host, port, timeout_proto)
        if p_ok:
            selected = port
            break
        proto_errors.append("port={0}: {1}".format(port, p_err))

    return selected, probed, tcp_open_ports, tcp_errors, tcp_kinds, proto_errors


def _detect_os_from_port(open_port):
    if open_port == 22:
        return "linux", None
    if open_port in (5985, 5986):
        return "windows", "https" if open_port == 5986 else "http"
    return None, None


def _probe_protocol(channel, host, open_port, timeout_proto, verify_ssl):
    if channel == "redfish":
        return probe_redfish(host, open_port, timeout_proto, verify=verify_ssl)
    if channel == "os":
        return probe_os(host, open_port, timeout_proto)
    if channel == "esxi":
        return probe_esxi(host, open_port, timeout_proto, verify=verify_ssl)
    return False, "알 수 없는 채널: {0}".format(channel), None


def _try_redfish_auth(host, open_port, username, password, timeout_auth, verify_ssl, result):
    url = "https://{0}:{1}/redfish/v1/Systems".format(host, open_port)
    ok, err, payload = http_get(
        url, timeout_auth, verify=verify_ssl, auth=(username, password)
    )
    if not ok:
        status = (payload or {}).get("status_code")
        rejected = status == 401
        result["auth_success"] = False if rejected else None
        result["failure_stage"] = "auth"
        result["failure_code"] = "AUTH_PROBE_FAILED"
        result["failure_reason"] = reason_for_failure(result["failure_code"], "redfish")
        result["detail"] = err
        return False
    result["auth_success"] = True
    json_data = payload.get("json") if payload else None
    if isinstance(json_data, dict):
        members = json_data.get("Members", [])
        if members and isinstance(members[0], dict):
            result["probe_facts"]["first_system_uri"] = members[0].get("@odata.id", "")
    return True


def _run_os_candidate_flow(module, result, host, ports, verify_ssl):
    (selected, probed, tcp_open_ports, tcp_errors, tcp_kinds,
     proto_errors) = _search_os_candidates(
        host, ports,
        module.params["timeout_port"],
        module.params["port_poll_interval"],
        module.params["timeout_protocol"],
    )
    result["checked_ports"] = probed or ports
    result["protocol_checked"] = True

    if selected is not None:
        os_type, scheme = _detect_os_from_port(selected)
        result["reachable"] = True
        result["port_open"] = True
        result["protocol_supported"] = True
        result["selected_port"] = selected
        result["detected_os"] = os_type
        result["winrm_scheme"] = scheme
        result["detected_port"] = selected
        module.exit_json(**result)

    if tcp_open_ports:
        result["reachable"] = True
        result["port_open"] = True
        result["protocol_supported"] = False
        result["failure_stage"] = "protocol"
        result["failure_code"] = "PROTOCOL_CHECK_FAILED"
        result["failure_reason"] = reason_for_failure(result["failure_code"], "os")
        result["detail"] = "; ".join(proto_errors + tcp_errors)
        module.exit_json(**result)

    icmp_note = None
    if TCP_FAIL_REFUSED in tcp_kinds:
        result["reachable"] = True
        result["failure_stage"] = "port"
        result["failure_code"] = "TCP_CONNECTION_REFUSED"
    else:
        reachable, stage, code, icmp_note = _resolve_reachability(
            module, host, tcp_kinds)
        result["reachable"] = reachable
        result["failure_stage"] = stage
        result["failure_code"] = code
    result["failure_reason"] = reason_for_failure(result["failure_code"], "os")
    result["detail"] = _join_detail(tcp_errors, icmp_note)
    module.exit_json(**result)


def run_module():
    module = AnsibleModule(
        argument_spec=dict(
            host=dict(type="str", required=True),
            channel=dict(
                type="str", required=True, choices=["redfish", "os", "esxi"]
            ),
            ports=dict(type="list", elements="int", default=[]),
            timeout_port=dict(type="float", default=3.0),
            timeout_protocol=dict(type="float", default=15.0),
            timeout_auth=dict(type="float", default=8.0),
            username=dict(type="str", required=False, no_log=True),
            password=dict(type="str", required=False, no_log=True),
            verify_ssl=dict(type="bool", default=False),
            probe_protocol=dict(type="bool", default=True),
            port_poll_interval=dict(type="float", default=0.0),
            icmp_probe=dict(type="bool", default=True),
            timeout_icmp=dict(type="float", default=_ICMP_DEFAULT_TIMEOUT),
        ),
        supports_check_mode=True,
    )

    host = module.params["host"]
    channel = module.params["channel"]
    ports = module.params["ports"] or CHANNEL_DEFAULT_PORTS.get(channel, [])
    verify_ssl = module.params["verify_ssl"]
    result = _init_result(channel, ports)

    if channel == "os" and module.params["probe_protocol"]:
        _run_os_candidate_flow(module, result, host, ports, verify_ssl)
        return

    any_response, target_port_open, open_port, port_errors, port_kinds, probed = _check_ports(
        host, ports, module.params["timeout_port"],
        poll_interval=module.params["port_poll_interval"],
    )
    result["checked_ports"] = probed or ports
    if not any_response:
        reachable, stage, code, icmp_note = _resolve_reachability(
            module, host, port_kinds)
        result["reachable"] = reachable
        result["failure_stage"] = stage
        result["failure_code"] = code
        result["failure_reason"] = reason_for_failure(code, channel)
        result["detail"] = _join_detail(port_errors, icmp_note)
        module.exit_json(**result)
    if not target_port_open:
        result["reachable"] = True
        result["failure_stage"] = "port"
        result["failure_code"] = "TCP_CONNECTION_REFUSED"
        result["failure_reason"] = reason_for_failure(result["failure_code"], channel)
        result["detail"] = "; ".join(port_errors)
        module.exit_json(**result)

    result["reachable"] = True
    result["port_open"] = True
    result["selected_port"] = open_port

    if channel == "os":
        os_type, scheme = _detect_os_from_port(open_port)
        result["detected_os"] = os_type
        result["winrm_scheme"] = scheme
        result["detected_port"] = open_port

    if not module.params["probe_protocol"]:
        result["protocol_checked"] = False
        module.exit_json(**result)

    result["protocol_checked"] = True
    ok, err, facts = _probe_protocol(
        channel, host, open_port, module.params["timeout_protocol"], verify_ssl
    )
    if not ok:
        result["failure_stage"] = "protocol"
        result["failure_code"] = "PROTOCOL_CHECK_FAILED"
        result["failure_reason"] = reason_for_failure(result["failure_code"], channel)
        result["detail"] = err
        module.exit_json(**result)
    result["protocol_supported"] = True
    if facts:
        result["probe_facts"].update(facts)

    username = module.params.get("username")
    password = module.params.get("password")
    if username and password and channel == "redfish":
        if not _try_redfish_auth(
            host, open_port, username, password,
            module.params["timeout_auth"], verify_ssl, result
        ):
            module.exit_json(**result)

    module.exit_json(**result)


def main():
    run_module()


if __name__ == "__main__":
    main()
