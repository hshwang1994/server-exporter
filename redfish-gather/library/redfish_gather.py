#!/usr/bin/python3
# -*- coding: utf-8 -*-

__metaclass__ = type


import copy, datetime, json, os, re, socket, sys, time, traceback
import urllib.parse as _urlparse
import http.client as http_client

BYTES_PER_GB_DECIMAL = 1_000_000_000
BYTES_PER_MIB = 1048576
MIB_PER_GIB = 1024
MBPS_PER_GBPS = 1000.0
MAX_COLLECTION_MEMBERS = 1024


def _removeprefix(s, prefix):
    if s.startswith(prefix):
        return s[len(prefix):]
    return s


def _safe_int(x, default=None):
    if x is None:
        return default
    try:
        return int(x)
    except (ValueError, TypeError, OverflowError):
        return default


def _safe_round_int(x, default=None):
    if x is None:
        return default
    try:
        f = float(x)
    except (ValueError, TypeError, OverflowError):
        return default
    if f != f or f in (float('inf'), float('-inf')):
        return default
    return int(round(f))


def _safe_num(x, default=None):
    if isinstance(x, bool):
        return default
    try:
        f = float(x)
    except (ValueError, TypeError):
        return default
    if f != f or f in (float('inf'), float('-inf')):
        return default
    return int(x) if isinstance(x, int) else f


def _normalize_port_speed(pdata):
    cur_gbps = _safe(pdata, 'CurrentSpeedGbps')
    cur_gbps_num = _safe_num(cur_gbps)
    speed_mbps = _safe_int(_safe(pdata, 'CurrentLinkSpeedMbps'))
    if speed_mbps is None and cur_gbps_num:
        speed_mbps = _safe_int(round(cur_gbps_num * MBPS_PER_GBPS))
    if cur_gbps_num:
        speed_gbps = cur_gbps_num
    elif speed_mbps:
        speed_gbps = speed_mbps / MBPS_PER_GBPS
    else:
        speed_gbps = None
    return speed_gbps, speed_mbps


try:
    import urllib.request as urlreq
    import urllib.error as urlerr
    import ssl, base64
    HAS_URLLIB = True
except ImportError:
    HAS_URLLIB = False

from ansible.module_utils.basic import AnsibleModule



_CTX_CACHE = {}


def _ctx(verify_ssl):
    _cache_key = bool(verify_ssl)
    _cached = _CTX_CACHE.get(_cache_key)
    if _cached is not None:
        return _cached
    ctx = ssl.create_default_context()
    if hasattr(ssl, 'TLSVersion'):
        try:
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.maximum_version = ssl.TLSVersion.TLSv1_3
        except (ValueError, AttributeError):
            pass
    if not verify_ssl:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        if hasattr(ssl, 'OP_LEGACY_SERVER_CONNECT'):
            ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
        try:
            ctx.set_ciphers('DEFAULT@SECLEVEL=0')
        except ssl.SSLError:
            pass
    _CTX_CACHE[_cache_key] = ctx
    return ctx

def _auth(username, password):
    return 'Basic ' + base64.b64encode(f'{username}:{password}'.encode()).decode()


CONNECT_TIMEOUT_SEC = 60

if HAS_URLLIB:
    _STDLIB_URLOPEN = urlreq.urlopen

    class _SameOriginRedirect(urlreq.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            method = req.get_method()
            if method not in ('GET', 'HEAD'):
                raise urlerr.HTTPError(req.full_url, code, 'redirect not followed for %s' % method, headers, fp)
            target = _origin_of(newurl)
            if target is None or target != _origin_of(req.full_url):
                where = '%s://%s' % (target[0], target[1]) if target else 'unparsable location'
                raise urlerr.HTTPError(req.full_url, code, 'redirect blocked: different origin %s' % where, headers, fp)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    class _SplitTimeoutHTTPSConnection(http_client.HTTPSConnection):

        def connect(self):
            read_timeout = self.timeout
            if isinstance(read_timeout, (int, float)) and read_timeout > CONNECT_TIMEOUT_SEC:
                self.timeout = CONNECT_TIMEOUT_SEC
            try:
                super().connect()
            finally:
                self.timeout = read_timeout
            if self.sock is not None and isinstance(read_timeout, (int, float)):
                self.sock.settimeout(read_timeout)

    class _SplitTimeoutHTTPSHandler(urlreq.HTTPSHandler):
        def https_open(self, req):
            kw = {'context': self._context}
            if hasattr(self, '_check_hostname'):
                kw['check_hostname'] = self._check_hostname
            return self.do_open(_SplitTimeoutHTTPSConnection, req, **kw)
else:
    _STDLIB_URLOPEN = None

_OPENERS = {}


def _origin_of(url):
    try:
        parts = _urlparse.urlsplit(url)
        scheme = (parts.scheme or '').lower()
        port = parts.port or {'https': 443, 'http': 80}.get(scheme)
        return (scheme, (parts.hostname or '').lower(), port)
    except ValueError:
        return None


def _urlopen(req, verify_ssl, timeout):
    if urlreq.urlopen is not _STDLIB_URLOPEN:
        return urlreq.urlopen(req, context=_ctx(verify_ssl), timeout=timeout)
    key = bool(verify_ssl)
    opener = _OPENERS.get(key)
    if opener is None:
        opener = urlreq.build_opener(_SplitTimeoutHTTPSHandler(context=_ctx(verify_ssl)), _SameOriginRedirect())
        _OPENERS[key] = opener
    return opener.open(req, timeout=timeout)

_AUTH_OBSERVATION = {'first_status': None}


def _reset_auth_observation():
    _AUTH_OBSERVATION['first_status'] = None


def _record_auth_status(status):
    if _AUTH_OBSERVATION['first_status'] is None and isinstance(status, int) and status:
        _AUTH_OBSERVATION['first_status'] = status
        _evidence_auth_status(status)


def auth_evidence():
    return {'first_auth_status': _AUTH_OBSERVATION['first_status']}


_EVIDENCE = {'path': None, 'data': None, 'last_write': 0.0, 'dirty': False}
EVIDENCE_WRITE_INTERVAL = 5.0


def _utc_now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


def _evidence_reset():
    _EVIDENCE.update({'path': None, 'data': None, 'last_write': 0.0, 'dirty': False})


def _evidence_begin(attempt, bmc_ip, username):
    _evidence_reset()
    if not isinstance(attempt, dict):
        return
    ev_dir = str(attempt.get('evidence_dir') or '').strip()
    att_id = str(attempt.get('id') or '').strip()
    if not ev_dir or not att_id:
        return
    safe_id = re.sub(r'[^A-Za-z0-9._-]', '_', att_id)[:120]
    safe_ip = re.sub(r'[^A-Za-z0-9._:-]', '_', str(bmc_ip))[:64]
    _EVIDENCE['path'] = os.path.join(ev_dir, safe_ip, safe_id + '.json')
    _EVIDENCE['data'] = {
        'schema': 1,
        'build_id': str(attempt.get('build_id') or ''),
        'event_uuid': str(attempt.get('event_uuid') or ''),
        'ip': str(bmc_ip),
        'attempt_id': att_id,
        'label': (str(attempt.get('label')) if attempt.get('label') is not None else None),
        'role': (str(attempt.get('role')) if attempt.get('role') is not None else None),
        'auth_mode': 'credentialed' if username else 'anonymous',
        'first_auth_status': None,
        'first_auth_at': None,
        'started_at': _utc_now_iso(),
        'updated_at': None,
        'requests_sent': 0,
        'last_request': None,
    }
    _evidence_write(force=True)


def _evidence_write(force=False):
    path, data = _EVIDENCE['path'], _EVIDENCE['data']
    if not path or data is None:
        return
    now = time.monotonic()
    if not force and (now - _EVIDENCE['last_write']) < EVIDENCE_WRITE_INTERVAL:
        _EVIDENCE['dirty'] = True
        return
    data['updated_at'] = _utc_now_iso()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = '%s.tmp.%d' % (path, os.getpid())
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, ensure_ascii=False, separators=(',', ':'))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        _EVIDENCE['last_write'] = now
        _EVIDENCE['dirty'] = False
    except OSError:
        pass


def _evidence_request(path):
    data = _EVIDENCE['data']
    if data is None:
        return
    data['requests_sent'] = int(data.get('requests_sent') or 0) + 1
    data['last_request'] = str(path)[:200]
    _evidence_write()


def _evidence_auth_status(status):
    data = _EVIDENCE['data']
    if data is None or data.get('first_auth_status') is not None:
        return
    data['first_auth_status'] = status
    data['first_auth_at'] = _utc_now_iso()
    _evidence_write(force=True)


def _evidence_finish():
    if _EVIDENCE['data'] is not None and _EVIDENCE['dirty']:
        _evidence_write(force=True)


def evidence_state():
    return {'path': _EVIDENCE['path'], 'data': (dict(_EVIDENCE['data']) if _EVIDENCE['data'] else None)}


_RESPONSE_CACHE = {}
_CACHE = {'enabled': False, 'hits': 0, 'misses': 0, 'bytes': 0}
_LAST_BODY = {'bytes': 0}


class _BodyTooLarge(OSError):
    def __init__(self, status, size):
        super().__init__('HTTP %s: body too large (%d > %d bytes)' % (status, size, MAX_BODY_BYTES))
        self.status = status


def _reset_response_cache(enabled=False):
    _RESPONSE_CACHE.clear()
    _CACHE['enabled'] = bool(enabled)
    _CACHE['hits'] = 0
    _CACHE['misses'] = 0
    _CACHE['bytes'] = 0


def _invalidate_response_cache():
    _RESPONSE_CACHE.clear()
    _CACHE['bytes'] = 0


def cache_stats():
    return {'hits': _CACHE['hits'], 'misses': _CACHE['misses'], 'entries': len(_RESPONSE_CACHE), 'bytes': _CACHE['bytes']}


def _read_capped(resp):
    try:
        raw = resp.read(MAX_BODY_BYTES + 1)
    except TypeError:
        raw = resp.read()
    if len(raw) > MAX_BODY_BYTES:
        raise _BodyTooLarge(getattr(resp, 'status', 0), len(raw))
    return raw


_NOTICES = []


def _reset_notices():
    del _NOTICES[:]


def _notice(section, message):
    entry = {'section': section, 'message': str(message)}
    if entry not in _NOTICES:
        _NOTICES.append(entry)
    return entry


def notices():
    return list(_NOTICES)


def _get(bmc_ip, path, username, password, timeout, verify_ssl):
    key = (username, path)
    if _CACHE['enabled']:
        hit = _RESPONSE_CACHE.get(key)
        if hit is not None:
            _CACHE['hits'] += 1
            return hit[0], copy.deepcopy(hit[1]), hit[2]
        _CACHE['misses'] += 1
    _LAST_BODY['bytes'] = 0
    status, data, err = _get_impl(bmc_ip, path, username, password, timeout, verify_ssl)
    _record_auth_status(status)
    size = _LAST_BODY['bytes']
    if (_CACHE['enabled'] and status == 200 and not err and isinstance(data, dict)
            and len(_RESPONSE_CACHE) < MAX_CACHE_ENTRIES and _CACHE['bytes'] + size <= MAX_CACHE_BYTES):
        _RESPONSE_CACHE[key] = (status, copy.deepcopy(data), err)
        _CACHE['bytes'] += size
    return status, data, err


def _get_impl(bmc_ip, path, username, password, timeout, verify_ssl):
    _evidence_request(path)
    url = f'https://{bmc_ip}/redfish/v1/{path.lstrip("/")}'
    req = urlreq.Request(url, headers={
        'Authorization': _auth(username, password),
        'Accept': 'application/json',
        'OData-Version': '4.0',
    })
    try:
        with _urlopen(req, verify_ssl, timeout) as resp:
            raw = _read_capped(resp)
            _LAST_BODY['bytes'] = len(raw)
            try:
                data = json.loads(raw.decode('utf-8', errors='replace')) if raw else {}
                decode_err = None
            except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
                data, decode_err = {}, f'HTTP {resp.status}: body not JSON'
            return resp.status, data, decode_err
    except urlerr.HTTPError as e:
        try:    body = json.loads(e.read(MAX_BODY_BYTES + 1).decode('utf-8', errors='replace'))
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError): body = {}
        return e.code, body, f'HTTP {e.code}: {e.reason}'
    except urlerr.URLError as e:
        return 0, {}, f'URLError: {e.reason}'
    except _BodyTooLarge as e:
        return e.status, {}, str(e)
    except socket.timeout:
        return 0, {}, f'Timeout after {timeout}s'
    except (OSError, ValueError) as e:
        return 0, {}, f'Unexpected: {type(e).__name__}: {e}'

def _post(bmc_ip, path, body, username, password, timeout, verify_ssl):
    _evidence_request(path)
    url = f'https://{bmc_ip}/redfish/v1/{path.lstrip("/")}'
    try:
        payload = json.dumps(body).encode('utf-8')
    except TypeError:
        payload = json.dumps(str(body)).encode('utf-8')
    _invalidate_response_cache()
    req = urlreq.Request(url, data=payload, method='POST', headers={
        'Authorization': _auth(username, password),
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'OData-Version': '4.0',
    })
    try:
        with _urlopen(req, verify_ssl, timeout) as resp:
            raw = _read_capped(resp)
            try:
                data = json.loads(raw.decode('utf-8', errors='replace')) if raw else {}
            except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
                data = {}
            return resp.status, data, None
    except urlerr.HTTPError as e:
        try:    body_err = json.loads(e.read(MAX_BODY_BYTES + 1).decode('utf-8', errors='replace'))
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError): body_err = {}
        return e.code, body_err, f'HTTP {e.code}: {e.reason}'
    except urlerr.URLError as e:
        return 0, {}, f'URLError: {e.reason}'
    except _BodyTooLarge as e:
        return e.status, {}, str(e)
    except socket.timeout:
        return 0, {}, f'Timeout after {timeout}s'
    except (OSError, ValueError) as e:
        return 0, {}, f'Unexpected: {type(e).__name__}: {e}'

def _delete(bmc_ip, path, username, password, timeout, verify_ssl):
    _evidence_request(path)
    url = f'https://{bmc_ip}/redfish/v1/{path.lstrip("/")}'
    _invalidate_response_cache()
    req = urlreq.Request(url, method='DELETE', headers={
        'Authorization': _auth(username, password),
        'Accept': 'application/json',
        'OData-Version': '4.0',
    })
    try:
        with _urlopen(req, verify_ssl, timeout) as resp:
            return resp.status, {}, None
    except urlerr.HTTPError as e:
        try:    body_err = json.loads(e.read(MAX_BODY_BYTES + 1).decode('utf-8', errors='replace'))
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError): body_err = {}
        return e.code, body_err, f'HTTP {e.code}: {e.reason}'
    except urlerr.URLError as e:
        return 0, {}, f'URLError: {e.reason}'
    except _BodyTooLarge as e:
        return e.status, {}, str(e)
    except socket.timeout:
        return 0, {}, f'Timeout after {timeout}s'
    except (OSError, ValueError) as e:
        return 0, {}, f'Unexpected: {type(e).__name__}: {e}'


def _patch(bmc_ip, path, body, username, password, timeout, verify_ssl,
           extra_headers=None):
    _evidence_request(path)
    url = f'https://{bmc_ip}/redfish/v1/{path.lstrip("/")}'
    try:
        payload = json.dumps(body).encode('utf-8')
    except TypeError:
        payload = json.dumps(str(body)).encode('utf-8')
    headers = {
        'Authorization': _auth(username, password),
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'OData-Version': '4.0',
    }
    if extra_headers:
        headers.update({k: v for k, v in extra_headers.items() if v})
    _invalidate_response_cache()
    req = urlreq.Request(url, data=payload, method='PATCH', headers=headers)
    try:
        with _urlopen(req, verify_ssl, timeout) as resp:
            raw = _read_capped(resp)
            try:
                data = json.loads(raw.decode('utf-8', errors='replace')) if raw else {}
            except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
                data = {}
            return resp.status, data, None
    except urlerr.HTTPError as e:
        try:    body_err = json.loads(e.read(MAX_BODY_BYTES + 1).decode('utf-8', errors='replace'))
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError): body_err = {}
        return e.code, body_err, f'HTTP {e.code}: {e.reason}'
    except urlerr.URLError as e:
        return 0, {}, f'URLError: {e.reason}'
    except _BodyTooLarge as e:
        return e.status, {}, str(e)
    except socket.timeout:
        return 0, {}, f'Timeout after {timeout}s'
    except (OSError, ValueError) as e:
        return 0, {}, f'Unexpected: {type(e).__name__}: {e}'

def _p(uri):
    if not isinstance(uri, str):
        return '__invalid_odata_id__'
    result = _removeprefix(_removeprefix(uri.lstrip('/'), 'redfish/v1/'), 'redfish/v1').rstrip('/')
    return result if result else '__invalid_odata_id__'

def _safe(d, *keys, default=None):
    for k in keys:
        if not isinstance(d, dict): return default
        d = d.get(k, default)
        if d is None: return default
    return d

def _as_list(x):
    return x if isinstance(x, list) else []

def _dicts(x):
    return [e for e in x if isinstance(e, dict)] if isinstance(x, list) else []

def _str(x):
    return x if isinstance(x, str) else ''

_CODE_VENDOR_UNRESOLVED = 'vendor_unresolved'
_CODE_BIOS_NON_BLOCKING = 'bios_non_blocking'
_CODE_NON_BLOCKING_SUBRESOURCE = 'subresource_non_blocking'
MAX_COLLECTION_PAGES = 64
MAX_BODY_BYTES = 8 * 1024 * 1024
MAX_CACHE_ENTRIES = 512
MAX_CACHE_BYTES = 8 * 1024 * 1024


def _err(section, message, detail=None, code=None):
    entry = {'section': section, 'message': str(message), 'detail': detail}
    if code:
        entry['code'] = code
    return entry


MAX_EXTENDED_INFO_ITEMS = 3
MAX_EXTENDED_INFO_LEN = 300

ACCOUNT_DEFAULT_AUTH_BUDGET = 3


def account_auth_budget(policy):
    threshold = (policy or {}).get('lockout_threshold')
    if isinstance(threshold, int) and not isinstance(threshold, bool) and threshold > 0:
        return max(1, min(threshold - 1, ACCOUNT_DEFAULT_AUTH_BUDGET + 2))
    return ACCOUNT_DEFAULT_AUTH_BUDGET


ACCOUNT_VERIFY_DELAYS = (0, 1, 5)

ACCOUNT_VERIFY_MAX_TOTAL_SECONDS = 45


def account_verify_delays(policy):
    delays = list(ACCOUNT_VERIFY_DELAYS)
    penalty = 0
    for key in ('auth_failure_delay_seconds', 'lockout_duration'):
        value = (policy or {}).get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value > penalty:
            penalty = value
    if penalty <= 0:
        return tuple(delays)
    remaining = ACCOUNT_VERIFY_MAX_TOTAL_SECONDS - sum(delays)
    extra = min(penalty + 2, remaining)
    if extra > 0:
        delays.append(extra)
    return tuple(delays)


_READ_ONLY_PROP_RE = re.compile(
    r'property\s+([A-Za-z][A-Za-z0-9_]*)\s+is\s+a?\s*read[\s-]?only', re.IGNORECASE
)

_PROPERTY_ARG_MESSAGE_IDS = (
    'PropertyNotWritable',
    'PropertyReadOnly',
    'PropertyNotUpdatable',
    'PropertyUnknown',
)
_PROP_NAME_RE = re.compile(r'\A[A-Za-z][A-Za-z0-9_]*\Z')

REJECT_READ_ONLY = 'read_only'
REJECT_VALUE = 'value_rejected'
REJECT_POLICY = 'policy_rejected'

_REJECT_SEVERITIES = frozenset({'warning', 'critical', 'error'})

_RELATED_PROP_RE = re.compile(r'\A#?/(?:.*/)?([A-Za-z][A-Za-z0-9_]*)\Z')


def _related_property_names(item):
    names = []
    for ref in _as_list(item.get('RelatedProperties')):
        if not isinstance(ref, str):
            continue
        m = _RELATED_PROP_RE.match(ref.strip())
        if m:
            names.append(m.group(1))
        elif _PROP_NAME_RE.match(ref.strip()):
            names.append(ref.strip())
    return names


def write_rejections(body, requested=None):
    if not isinstance(body, dict):
        return []
    err = body.get('error')
    scope = err if isinstance(err, dict) else body
    found = []
    seen = set()

    def _add(prop, kind, msg_id, severity):
        key = (prop, kind)
        if key in seen:
            return
        seen.add(key)
        found.append({'property': prop, 'kind': kind,
                      'message_id': msg_id, 'severity': severity})

    for item in _dicts(scope.get('@Message.ExtendedInfo')):
        msg_id = item.get('MessageId') if isinstance(item.get('MessageId'), str) else None
        sev = item.get('MessageSeverity') or item.get('Severity')
        sev = sev.lower() if isinstance(sev, str) else None

        text = item.get('Message')
        if isinstance(text, str):
            m = _READ_ONLY_PROP_RE.search(text)
            if m and (requested is None or m.group(1) in requested):
                _add(m.group(1), REJECT_READ_ONLY, msg_id, sev)

        if msg_id and any(msg_id.endswith(s) for s in _PROPERTY_ARG_MESSAGE_IDS):
            for arg in _as_list(item.get('MessageArgs')):
                if isinstance(arg, str) and _PROP_NAME_RE.match(arg) \
                        and (requested is None or arg in requested):
                    _add(arg, REJECT_READ_ONLY, msg_id, sev)
            continue

        if sev in _REJECT_SEVERITIES:
            for prop in _related_property_names(item):
                if requested is not None and prop not in requested:
                    continue
                _add(prop, REJECT_POLICY, msg_id, sev)

    text = scope.get('message')
    if isinstance(text, str):
        m = _READ_ONLY_PROP_RE.search(text)
        if m:
            _add(m.group(1), REJECT_READ_ONLY, None, None)
    return found


def rejected_patch_properties(body):
    return {r['property'] for r in write_rejections(body)
            if r['kind'] == REJECT_READ_ONLY and r['property']}


def _extended_info(body, limit=MAX_EXTENDED_INFO_LEN):
    if not isinstance(body, dict):
        return None
    err = body.get('error')
    if not isinstance(err, dict):
        err = body
    parts = []

    def _push(v):
        if isinstance(v, str) and v.strip() and v.strip() not in parts:
            parts.append(v.strip())

    _push(err.get('code'))
    _push(err.get('message'))
    for item in _dicts(err.get('@Message.ExtendedInfo'))[:MAX_EXTENDED_INFO_ITEMS]:
        _push(item.get('Message') or item.get('MessageId'))
        _push(item.get('Resolution'))
    out = ' | '.join(parts).strip()
    return out[:limit] or None


def _nextlink_path(bmc_ip, current_path, link):
    if not isinstance(link, str) or not link.strip():
        return None
    base = 'https://%s/redfish/v1/%s' % (bmc_ip, _str(current_path).lstrip('/'))
    try:
        parts = _urlparse.urlsplit(_urlparse.urljoin(base, link.strip()))
    except ValueError:
        return None
    host = (parts.hostname or '').lower()
    if host != str(bmc_ip).lower().strip('[]'):
        return None
    if not parts.path.startswith('/redfish/v1'):
        return None
    rel = _p(parts.path)
    if rel == '__invalid_odata_id__':
        return None
    return rel + ('?' + parts.query if parts.query else '')


def _collection_members(bmc_ip, path, coll, username, password, timeout, verify_ssl,
                        section, errors):
    members = list(_dicts(_safe(coll, 'Members')))
    first_path = _str(path).split('?', 1)[0]
    seen = {_str(path)}
    cur, cur_path, pages, truncated = coll, _str(path), 1, False

    def _report(msg):
        if errors is not None:
            errors.append(_err(section, msg, code=_CODE_NON_BLOCKING_SUBRESOURCE))
        else:
            _notice(section, msg)

    while True:
        link = _safe(cur, 'Members@odata.nextLink')
        if not link:
            break
        nxt = _nextlink_path(bmc_ip, cur_path, link)
        if nxt is None:
            _report('%s: nextLink 를 따라갈 수 없음 (다른 origin 또는 형식 오류) — 앞 페이지까지 보존'
                    % first_path)
            truncated = True
            break
        if nxt in seen:
            _report('%s: nextLink 순환 감지 — 앞 페이지까지 보존' % first_path)
            truncated = True
            break
        if pages >= MAX_COLLECTION_PAGES or len(members) >= MAX_COLLECTION_MEMBERS:
            _report('%s: 페이지 %d / 멤버 %d 상한 도달 — 절단' % (first_path, pages, len(members)))
            truncated = True
            break
        st, nxt_coll, err = _get(bmc_ip, nxt, username, password, timeout, verify_ssl)
        if err or st != 200 or not isinstance(nxt_coll, dict):
            _report('%s: 다음 페이지 실패 (%s): %s — 앞 페이지까지 보존'
                    % (first_path, nxt, err or st))
            truncated = True
            break
        seen.add(nxt)
        pages += 1
        cur, cur_path = nxt_coll, nxt
        members.extend(_dicts(_safe(nxt_coll, 'Members')))

    declared = _safe(coll, 'Members@odata.count')
    if (not truncated and isinstance(declared, int) and not isinstance(declared, bool)
            and declared != len(members)):
        _notice(section, '%s: Members@odata.count %d != 수집 %d' % (first_path, declared, len(members)))
    return _capped(members, section, errors)


def _capped(seq, section=None, errors=None):
    seq = seq if isinstance(seq, list) else []
    if len(seq) > MAX_COLLECTION_MEMBERS:
        if section:
            text = (f'collection 멤버 {len(seq)} > 상한 {MAX_COLLECTION_MEMBERS} '
                    f'— 절단(DoS 방어)')
            if errors is not None:
                errors.append(_err(section, text))
            else:
                _notice(section, text)
        return seq[:MAX_COLLECTION_MEMBERS]
    return seq


_JEDEC_VENDORS = {
    "01": "AMD",
    "0B": "Intel",
    "1F": "Atmel",
    "2C": "Micron Technology",
    "98": "Kingston",
    "AD": "SK hynix",
    "B3": "IDT",
    "BA": "PNY Electronics",
    "CE": "Samsung",
    "04": "Fujitsu",
    "07": "Hitachi",
}


_VENDOR_NAME_NORMALIZATION = {
    "hynix": "SK hynix",
    "hynix semiconductor": "SK hynix",
    "sk hynix": "SK hynix",
    "skhynix": "SK hynix",
    "samsung electronics": "Samsung",
    "samsung electronic": "Samsung",
    "micron": "Micron Technology",
    "micron technology": "Micron Technology",
    "kingston technology": "Kingston",
}


def _canonical_vendor_name(name):
    if not name or not isinstance(name, str):
        return name
    return _VENDOR_NAME_NORMALIZATION.get(name.strip().lower(), name)


def _normalize_jedec(value):
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in ("unknown", "not specified", "none"):
        return None
    if s.lower().startswith("0x"):
        hp = s[2:].upper()
        if hp[:2] in _JEDEC_VENDORS:
            return _JEDEC_VENDORS[hp[:2]]
        return s
    if " " in s or any(c.isalpha() and c not in "ABCDEFabcdef" for c in s):
        return _canonical_vendor_name(s)
    if all(c in "0123456789ABCDEFabcdef" for c in s) and len(s) >= 2:
        for idx in (slice(2, 4), slice(0, 2)):
            byte = s[idx].upper() if len(s) >= idx.stop else None
            if byte and byte in _JEDEC_VENDORS:
                return _JEDEC_VENDORS[byte]
        return s
    return _canonical_vendor_name(s)


def _strip_or_none(value):
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    s = value.strip()
    return s or None



_FALLBACK_VENDOR_MAP = {
    'dell': 'dell', 'dell inc.': 'dell', 'dell emc': 'dell',
    'hpe': 'hpe', 'hewlett packard enterprise': 'hpe',
    'hewlett packard enterprise co.': 'hpe', 'hewlett-packard': 'hpe',
    'hp enterprise': 'hpe', 'hp': 'hpe',
    'lenovo': 'lenovo', 'lenovo group ltd.': 'lenovo',
    'lenovo group limited': 'lenovo', 'ibm': 'lenovo',
    'supermicro': 'supermicro', 'super micro computer, inc.': 'supermicro',
    'super micro computer': 'supermicro', 'smci': 'supermicro',
    'cisco': 'cisco', 'cisco systems inc': 'cisco',
    'cisco systems inc.': 'cisco', 'cisco systems, inc': 'cisco',
    'cisco systems, inc.': 'cisco', 'cisco systems': 'cisco',
    'huawei': 'huawei', 'huawei technologies co., ltd.': 'huawei',
    'huawei technologies': 'huawei',
    'inspur': 'inspur',
    'inspur information technology company limited': 'inspur',
    'inspur information': 'inspur', 'inspur systems': 'inspur',
    'fujitsu': 'fujitsu', 'fujitsu limited': 'fujitsu',
    'fujitsu technology solutions': 'fujitsu',
    'quanta': 'quanta', 'quanta computer': 'quanta',
    'quanta computer inc.': 'quanta',
    'quanta cloud technology': 'quanta', 'qct': 'quanta',
}
_BUILTIN_VENDOR_MAP = _FALLBACK_VENDOR_MAP

_BMC_PRODUCT_HINTS = {
    'idrac': 'dell', 'integrated dell': 'dell',
    'ilo': 'hpe', 'proliant': 'hpe',
    'xclarity': 'lenovo', 'thinksystem': 'lenovo',
    'xcc': 'lenovo', 'imm2': 'lenovo',
    'megarac': 'supermicro',
    'cimc': 'cisco', 'ucs': 'cisco',
    'ibmc': 'huawei', 'fusionserver': 'huawei',
    'isbmc': 'inspur',
    'irmc': 'fujitsu', 'primergy': 'fujitsu',
    'quantagrid': 'quanta', 'quantaplex': 'quanta',
    'superdome': 'hpe', 'superdome flex': 'hpe',
    'compute scale-up server': 'hpe', 'csus 3200': 'hpe',
}


def _load_vendor_aliases_file():
    import os
    try:
        import yaml
    except ImportError:
        return {}

    candidates = []
    explicit = os.environ.get('SE_VENDOR_ALIASES_PATH', '')
    if explicit:
        candidates.append(explicit)
    repo_root = os.environ.get('REPO_ROOT', '')
    if repo_root:
        candidates.append(os.path.join(repo_root, 'common', 'vars', 'vendor_aliases.yml'))
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.normpath(os.path.join(here, '..', '..', 'common', 'vars', 'vendor_aliases.yml')))
    except NameError:
        pass

    for path in candidates:
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
            mapping = {}
            for canonical, alias_list in data.get('vendor_aliases', {}).items():
                if not isinstance(canonical, str):
                    continue
                for alias in (alias_list if isinstance(alias_list, list) else []):
                    if isinstance(alias, str):
                        mapping[alias.strip().lower()] = canonical
            if mapping:
                return mapping
        except (IOError, OSError, yaml.YAMLError, AttributeError, TypeError):
            continue
    return {}

def _normalize_vendor_from_aliases(mfr_lower):
    if not mfr_lower:
        return 'unknown'

    aliases = _load_vendor_aliases_file()
    merged = {**_FALLBACK_VENDOR_MAP, **aliases}

    if mfr_lower in merged:
        return merged[mfr_lower]

    for key, canon in merged.items():
        if key and (key in mfr_lower or mfr_lower in key):
            return canon

    return 'unknown'



def _probe_realm_hint(bmc_ip, timeout, verify_ssl):
    import re
    _evidence_request('noauth:realm-probe')
    url = f'https://{bmc_ip}/redfish/v1/'
    req = urlreq.Request(url, headers={'Accept': 'application/json', 'OData-Version': '4.0'})
    realm_header = None
    try:
        with _urlopen(req, verify_ssl, timeout) as resp:
            return None
    except urlerr.HTTPError as e:
        if e.code in (401, 403):
            realm_header = e.headers.get('WWW-Authenticate') or ''
    except (urlerr.URLError, socket.timeout, OSError, ValueError):
        return None

    if not realm_header:
        return None

    m = re.search(r'realm\s*=\s*"([^"]+)"', realm_header, re.IGNORECASE)
    if not m:
        m = re.search(r"realm\s*=\s*'([^']+)'", realm_header, re.IGNORECASE)
    if not m:
        return None
    realm = m.group(1).lower().strip()

    aliases_yaml = _load_vendor_aliases_file()
    vm = {**_FALLBACK_VENDOR_MAP, **aliases_yaml}
    for alias, canon in vm.items():
        if alias and alias in realm:
            return canon
    for hint, canon in _BMC_PRODUCT_HINTS.items():
        if hint in realm:
            return canon
    return None


def _get_noauth(bmc_ip, path, timeout, verify_ssl):
    _evidence_request('noauth:' + str(path))
    url = f'https://{bmc_ip}/redfish/v1/{path.lstrip("/")}'
    req = urlreq.Request(url, headers={
        'Accept': 'application/json',
        'OData-Version': '4.0',
    })
    try:
        with _urlopen(req, verify_ssl, timeout) as resp:
            raw = _read_capped(resp)
            try:
                data = json.loads(raw.decode('utf-8', errors='replace')) if raw else {}
                decode_err = None
            except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
                data, decode_err = {}, f'HTTP {resp.status}: body not JSON'
            return resp.status, data, decode_err
    except urlerr.HTTPError as e:
        try:    body = json.loads(e.read(MAX_BODY_BYTES + 1).decode('utf-8', errors='replace'))
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError): body = {}
        return e.code, body, f'HTTP {e.code}: {e.reason}'
    except urlerr.URLError as e:
        return 0, {}, f'URLError: {e.reason}'
    except _BodyTooLarge as e:
        return e.status, {}, str(e)
    except socket.timeout:
        return 0, {}, f'Timeout after {timeout}s'
    except (OSError, ValueError) as e:
        return 0, {}, f'Unexpected: {type(e).__name__}: {e}'


def _detect_vendor_from_service_root(root):
    aliases_yaml = _load_vendor_aliases_file()
    vm = {**_FALLBACK_VENDOR_MAP, **aliases_yaml}

    oem = _safe(root, 'Oem')
    if isinstance(oem, dict):
        for key in oem:
            k = key.lower()
            if k in vm:
                return vm[k]
        for key in oem:
            k = key.lower()
            for alias, canon in vm.items():
                if not alias:
                    continue
                if k.startswith(alias + '_') or k.startswith(alias + '.'):
                    return canon

    vendor_field = _safe(root, 'Vendor')
    if vendor_field and isinstance(vendor_field, str):
        v = vendor_field.lower().strip()
        for cand in (v, v.rstrip('.').strip()):
            if cand in vm:
                return vm[cand]
        for alias, canonical in vm.items():
            if alias and alias in v:
                return canonical

    product = _safe(root, 'Product')
    if product and isinstance(product, str):
        p = product.lower()
        for alias, canonical in vm.items():
            if alias and alias in p:
                return canonical
        for hint, canon in _BMC_PRODUCT_HINTS.items():
            if hint in p:
                return canon

    name = _safe(root, 'Name')
    if name and isinstance(name, str):
        n = name.lower()
        for alias, canonical in vm.items():
            if alias and alias in n:
                return canonical
        for hint, canon in _BMC_PRODUCT_HINTS.items():
            if hint in n:
                return canon

    return None


def _fetch_service_root(bmc_ip, username, password, timeout, verify_ssl):
    errors = []
    st, root, err = _get_noauth(bmc_ip, '', timeout, verify_ssl)
    if err or st != 200:
        st, root, err = _get(bmc_ip, '', username, password, timeout, verify_ssl)
        if err or st != 200:
            errors.append(_err('vendor_detect', f'ServiceRoot 실패: {err or st}'))
            return None, errors
    if not isinstance(root, dict):
        errors.append(_err('vendor_detect', 'ServiceRoot JSON 이 object 아님'))
        return None, errors
    return root, errors


def _endpoint_with_fallback(bmc_ip, primary_path, fallback_path, username,
                            password, timeout, verify_ssl, section_name='generic'):
    errors = []
    st, data, err = _get(bmc_ip, primary_path, username, password, timeout, verify_ssl)

    if not err and st == 200:
        return data, errors, 'primary'

    if st == 404:
        st_fb, data_fb, err_fb = _get(bmc_ip, fallback_path, username, password,
                                      timeout, verify_ssl)
        if not err_fb and st_fb == 200:
            return data_fb, errors, 'fallback'
        if st_fb == 404:
            return {}, errors, 'not_supported'
        errors.append(_err(section_name,
                           f'fallback {fallback_path} 실패: {err_fb or st_fb}'))
        return {}, errors, 'failed'

    errors.append(_err(section_name, f'{primary_path} 실패: {err or st}'))
    return {}, errors, 'failed'


def _resolve_first_member_uri(bmc_ip, coll_uri, username, password, timeout, verify_ssl):
    if not coll_uri:
        return None, None, 'collection uri 없음'
    st, coll, err = _get(bmc_ip, _p(coll_uri), username, password, timeout, verify_ssl)
    if err or st != 200:
        return None, st, err or f'HTTP {st}'
    members = _safe(coll, 'Members') or []
    if not isinstance(members, list) or not members:
        return None, st, 'members 없음'
    return _safe(members[0], '@odata.id'), st, None


def _resolve_all_member_uris(bmc_ip, coll_uri, username, password, timeout, verify_ssl):
    if not coll_uri:
        return [], None, 'collection uri 없음'
    st, coll, err = _get(bmc_ip, _p(coll_uri), username, password, timeout, verify_ssl)
    if err or st != 200:
        return [], st, err or f'HTTP {st}'
    raw_members = _collection_members(bmc_ip, _p(coll_uri), coll, username, password, timeout,
                                      verify_ssl, 'multi_node', None)
    if not isinstance(raw_members, list):
        raw_members = []
    out = []
    for m in raw_members:
        uri = _safe(m, '@odata.id')
        if not uri or not isinstance(uri, str):
            continue
        mid = uri.rstrip('/').rsplit('/', 1)[-1] if '/' in uri else uri
        out.append({'uri': uri, 'id': mid})
    if not out:
        return [], st, 'members 없음'
    return out, st, None


def _resolve_system_chassis_uri(bmc_ip, system_uri, default_chassis_uri,
                                username, password, timeout, verify_ssl):
    if not system_uri:
        return default_chassis_uri
    st, data, err = _get(bmc_ip, _p(system_uri), username, password, timeout, verify_ssl)
    if err or st != 200 or not isinstance(data, dict):
        return default_chassis_uri
    for link in _dicts(_safe(data, 'Links', 'Chassis')):
        uri = _safe(link, '@odata.id')
        if uri and isinstance(uri, str):
            return uri
    return default_chassis_uri


def _classify_rmc_label(manager_uri, manager_id, manager_layout, is_first=True):
    if not manager_layout:
        return None
    lid = _str(manager_id).lower()
    luri = _str(manager_uri).lower()
    if 'rmc' in lid or 'rmc' in luri:
        return 'RMC'
    if 'pdhc' in lid or 'pdhc' in luri:
        return 'PDHC'
    if 'ilo' in lid or 'ilo' in luri:
        return 'iLO'
    if is_first and manager_layout in ('rmc_primary', 'rmc_primary_ilo_secondary'):
        return 'RMC'
    return None


def _classify_manager_role(manager_uri, manager_id, manager_layout, is_first=False):
    if not manager_layout:
        return None
    lid = _str(manager_id).lower()
    luri = _str(manager_uri).lower()
    if 'rmc' in lid or 'rmc' in luri:
        return 'primary'
    if manager_layout in ('rmc_primary', 'rmc_primary_ilo_secondary'):
        if 'pdhc' in lid or 'pdhc' in luri or 'ilo' in lid or 'ilo' in luri:
            return 'secondary'
        return 'primary' if is_first else 'secondary'
    return None


def _classify_chassis_kind(chassis_uri, chassis_id, chassis_data):
    lid = _str(chassis_id).lower()
    luri = _str(chassis_uri).lower()
    if 'base' in lid or 'base' in luri:
        return 'base'
    if 'expansion' in lid or 'expansion' in luri:
        return 'expansion'
    if 'compute' in lid or 'module' in lid or 'compute' in luri:
        return 'compute_module'
    if isinstance(chassis_data, dict):
        ctype = _str(_safe(chassis_data, 'ChassisType')).lower()
        if ctype == 'enclosure':
            return 'enclosure'
        if ctype in ('rackmount', 'card', 'blade', 'rackgroup', 'rack'):
            return ctype
    return None


def detect_vendor(bmc_ip, username, password, timeout, verify_ssl):
    root, errors = _fetch_service_root(bmc_ip, username, password, timeout, verify_ssl)
    if root is None:
        return 'unknown', None, None, None, errors, None

    vendor = _detect_vendor_from_service_root(root)
    if vendor is None:
        vendor = 'unknown'
        errors.append(_err('vendor_detect', 'ServiceRoot에서 벤더 식별 불가',
                           code=_CODE_VENDOR_UNRESOLVED))

    systems_uri  = _safe(root, 'Systems',  '@odata.id')
    if not systems_uri:
        errors.append(_err('vendor_detect', 'ServiceRoot 에 Systems 링크 없음'))
        return vendor, None, None, None, errors, root

    system_uri, st, serr = _resolve_first_member_uri(
        bmc_ip, systems_uri, username, password, timeout, verify_ssl
    )
    if not system_uri:
        errors.append(_err('vendor_detect', f'Systems 컬렉션 실패: {serr}'))
        return vendor, None, None, None, errors, root

    manager_uri, _, _ = _resolve_first_member_uri(
        bmc_ip, _safe(root, 'Managers', '@odata.id'),
        username, password, timeout, verify_ssl,
    )
    chassis_uri, _, _ = _resolve_first_member_uri(
        bmc_ip, _safe(root, 'Chassis', '@odata.id'),
        username, password, timeout, verify_ssl,
    )

    if vendor == 'unknown':
        for fb_uri, fb_label in (
            (chassis_uri, 'Chassis'),
            (manager_uri, 'Managers'),
            (system_uri, 'Systems'),
        ):
            if not fb_uri:
                continue
            fst, fdata, _ferr = _get(bmc_ip, _p(fb_uri), username, password, timeout, verify_ssl)
            if fst != 200 or not isinstance(fdata, dict):
                continue
            mfr = _safe(fdata, 'Manufacturer')
            if mfr and isinstance(mfr, str):
                fb_vendor = _normalize_vendor_from_aliases(mfr.strip().lower())
                if fb_vendor and fb_vendor != 'unknown':
                    vendor = fb_vendor
                    errors = [e for e in errors if e.get('code') != _CODE_VENDOR_UNRESOLVED]
                    _notice('vendor_detect',
                            f'{fb_label} Manufacturer fallback로 vendor={fb_vendor} 식별 (ServiceRoot 정보 부족)')
                    break

    if vendor == 'unknown':
        realm_vendor = _probe_realm_hint(bmc_ip, timeout, verify_ssl)
        if realm_vendor:
            vendor = realm_vendor
            errors = [e for e in errors if e.get('code') != _CODE_VENDOR_UNRESOLVED]
            _notice('vendor_detect',
                    f'WWW-Authenticate realm fallback로 vendor={realm_vendor} 식별 (ServiceRoot/Resources 본문 부족)')

    return vendor, system_uri, manager_uri, chassis_uri, errors, root


def _extract_probe_facts(root, vendor):
    if not isinstance(root, dict):
        return {}
    facts = {}
    if vendor == 'hpe':
        product = _safe(root, 'Product')
        if isinstance(product, str) and product.strip():
            facts['model_hint'] = product.strip()
        managers = (_safe(root, 'Oem', 'Hpe', 'Manager')
                    or _safe(root, 'Oem', 'Hp', 'Manager'))
        mgr0 = None
        if isinstance(managers, list) and managers and isinstance(managers[0], dict):
            mgr0 = managers[0]
        elif isinstance(managers, dict):
            mgr0 = managers
        if mgr0 is not None:
            fw_ver = _safe(mgr0, 'ManagerFirmwareVersion')
            if isinstance(fw_ver, str) and fw_ver.strip():
                facts['firmware_hint'] = fw_ver.strip()
            mgr_type = _safe(mgr0, 'ManagerType')
            if isinstance(mgr_type, str) and mgr_type.strip():
                facts['manager_type'] = mgr_type.strip()
    return facts




def _extract_oem_hpe(data):
    oem = _safe(data, 'Oem', 'Hpe') or _safe(data, 'Oem', 'Hp') or {}
    oem_type = _str(_safe(oem, '@odata.type'))
    if oem_type.startswith('#HpeH3Npar'):
        dcd = _safe(oem, 'DCD') or {}
        host_os = _safe(oem, 'HostOS') or {}
        return {
            'product_id':                   _safe(oem, 'ProductId'),
            'console_routing':              _safe(oem, 'ConsoleRouting'),
            'console_routing_current_boot': _safe(oem, 'ConsoleRoutingCurrentBoot'),
            'dcd_version':                  _safe(dcd, 'DCDVersion'),
            'host_os_name':                 _safe(host_os, 'OsName'),
            'host_os_version':              _safe(host_os, 'OsVersion'),
            'host_os_description':          _safe(host_os, 'OsSysDescription'),
        }
    ahs = _safe(oem, 'AggregateHealthStatus') or {}
    bios_oem = _safe(oem, 'Bios', 'Current') or {}
    return {
        '_bios_date':              _safe(bios_oem, 'Date'),
        'post_state':              _safe(oem, 'PostState'),
        'server_signature':        _safe(oem, 'ServerSignature'),
        'aggregate_server_health': _safe(ahs, 'AggregateServerHealth'),
        'fan_redundancy':          _safe(ahs, 'FanRedundancy'),
        'psu_redundancy':          _safe(ahs, 'PowerSupplyRedundancy'),
        'subsystem_health': {
            'fans':         _safe(ahs, 'Fans', 'Status', 'Health'),
            'memory':       _safe(ahs, 'Memory', 'Status', 'Health'),
            'network':      _safe(ahs, 'Network', 'Status', 'Health'),
            'power':        _safe(ahs, 'PowerSupplies', 'Status', 'Health'),
            'processors':   _safe(ahs, 'Processors', 'Status', 'Health'),
            'storage':      _safe(ahs, 'Storage', 'Status', 'Health'),
            'temperatures': _safe(ahs, 'Temperatures', 'Status', 'Health'),
        },
    }


def _extract_oem_dell(data):
    oem = _safe(data, 'Oem', 'Dell', 'DellSystem') or {}
    bios_date = _safe(oem, 'BIOSReleaseDate')
    return {
        '_bios_date':              bios_date,
        'lifecycle_version':       _safe(oem, 'LifecycleControllerVersion'),
        'bios_release_date':       bios_date,
        'current_rollup_status':   _safe(oem, 'CurrentRollupStatus'),
        'cpu_rollup_status':       _safe(oem, 'CPURollupStatus'),
        'fan_rollup_status':       _safe(oem, 'FanRollupStatus'),
        'battery_rollup_status':   _safe(oem, 'BatteryRollupStatus'),
        'intrusion_rollup_status': _safe(oem, 'IntrusionRollupStatus'),
        'storage_rollup_status':   _safe(oem, 'StorageRollupStatus'),
        'chassis_service_tag':     _safe(oem, 'ChassisServiceTag'),
        'express_service_code':    _safe(oem, 'ExpressServiceCode'),
        'estimated_exhaust_temp':  (_safe(oem, 'EstimatedExhaustTemperatureCelsius')
                                    if _safe(oem, 'EstimatedExhaustTemperatureCelsius') is not None
                                    else _safe(oem, 'EstimatedExhaustTemperatureCel')),
    }



def _resolve_serial_dell(service_root, refetch=None):
    invalid_values = ('NA', 'N/A', 'NONE', 'NOT SPECIFIED', 'TO BE FILLED BY O.E.M.',
                      'SYSTEM SERIAL NUMBER', '0', '00000000')

    def _pick(root):
        tag = _strip_or_none(_safe(root, 'Oem', 'Dell', 'ServiceTag'))
        if tag is None:
            return None, ('서버 대표 시리얼을 확인하지 못했습니다 — '
                          'ServiceRoot.Oem.Dell.ServiceTag 없음')
        if not isinstance(tag, str):
            return None, ('서버 대표 시리얼을 확인하지 못했습니다 — '
                          'ServiceRoot.Oem.Dell.ServiceTag 가 문자열이 아님')
        if tag.strip().upper() in invalid_values:
            return None, ('서버 대표 시리얼을 확인하지 못했습니다 — '
                          'ServiceRoot.Oem.Dell.ServiceTag 가 무효값(%r)' % tag)
        return tag, None

    tag, err = _pick(service_root)
    if err is not None and refetch is not None:
        tag, err = _pick(refetch())
    return tag, err


_SERIAL_RESOLVERS = {
    'dell': _resolve_serial_dell,
}


def _extract_oem_lenovo(data, chassis_data=None):
    sys_oem = _safe(data, 'Oem', 'Lenovo') or {}
    cha_oem = _safe(chassis_data or {}, 'Oem', 'Lenovo') or {} if chassis_data else {}
    product_name = (
        _safe(sys_oem, 'ProductName')
        or _safe(cha_oem, 'ProductName')
        or _safe(data, 'Model')
    )
    return {
        'product_name':         product_name,
        'system_status':        _safe(sys_oem, 'SystemStatus'),
        'fru_serial':           _safe(cha_oem, 'FruSerialNumber'),
        'machine_type':         _safe(cha_oem, 'MachineType'),
        'machine_level':        _safe(cha_oem, 'MachineLevel'),
        'product_id':           _safe(cha_oem, 'ProductId'),
        'system_id':            _safe(cha_oem, 'SystemId'),
        'health_summary':       _safe(sys_oem, 'HealthSummary'),
        'led_indicator':        _safe(cha_oem, 'LEDIndicators') or _safe(cha_oem, 'IndicatorLED'),
    }


def _extract_oem_supermicro(data):
    oem = _safe(data, 'Oem', 'Supermicro') or {}
    return {
        'board_id':   _safe(oem, 'BoardID'),
        'node_id':    _safe(oem, 'NodeID'),
    }


def _extract_oem_cisco(data, chassis_data=None):
    sys_oem = _safe(data, 'Oem', 'Cisco') or {}
    cha_oem = _safe(chassis_data or {}, 'Oem', 'Cisco') or {} if chassis_data else {}
    return {
        'board_serial':       _safe(sys_oem, 'BoardSerialNumber') or _safe(cha_oem, 'BoardSerialNumber'),
        'platform_name':      _safe(sys_oem, 'PlatformName') or _safe(cha_oem, 'PlatformName'),
        'asset_tag':          _safe(sys_oem, 'AssetTag') or _safe(cha_oem, 'AssetTag'),
        'description':        _safe(sys_oem, 'Description') or _safe(cha_oem, 'Description'),
        'locator_led':        _safe(sys_oem, 'LocatorLED') or _safe(cha_oem, 'LocatorLED'),
    }


def _hoist_oem_extras(oem_dict, target):
    if not isinstance(oem_dict, dict):
        return oem_dict
    cleaned = {}
    for k, v in oem_dict.items():
        if isinstance(k, str) and k.startswith('_'):
            field = k[1:]
            if field in target and v is not None:
                if field in ('bios_date', 'bios_release_date'):
                    target[field] = _normalize_bios_date(v)
                else:
                    target[field] = v
        else:
            cleaned[k] = v
    return cleaned


_ROLE_ID_NORMALIZATION_MATRIX = {
    'administrator': 'administrator',
    'admin':         'administrator',
    'supervisor':    'administrator',
    'operator':      'operator',
    'user':          'operator',
    'readonly':      'readonly',
    'read-only':     'readonly',
    'read_only':     'readonly',
    'commonuser':    'readonly',
    'callback':      'readonly',
    'none':          'none',
    'virtualmedia':  'custom',
}


def _normalize_role_id(raw_role):
    if raw_role is None:
        return None
    s = str(raw_role).strip().lower()
    if not s:
        return None
    return _ROLE_ID_NORMALIZATION_MATRIX.get(s, s)


def _normalize_dimm_label(raw_label):
    if raw_label is None:
        return None
    s = str(raw_label).strip()
    if not s:
        return None
    normalized = s.replace('_', ' ').replace('-', ' ')
    while '  ' in normalized:
        normalized = normalized.replace('  ', ' ')
    return normalized


def _normalize_link_status(value):
    if value is None:
        return 'unknown'
    s = str(value).strip().lower()
    if not s or s in ('none', 'unknown', 'null'):
        return 'unknown'
    if s in ('linkup', 'up', 'connected', 'enabled', 'active'):
        return 'up'
    if s in ('linkdown', 'down', 'nolink', 'disconnected', 'disabled',
             'inactive', 'offline', 'starting', 'training'):
        return 'down'
    return s


def _valid_iso_date(s):
    import datetime as _dt
    try:
        _dt.date(int(s[0:4]), int(s[5:7]), int(s[8:10]))
        return True
    except (ValueError, TypeError, IndexError):
        return False


def _normalize_bios_date(value):
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.upper() in ('N/A', 'NONE', 'NOT SPECIFIED'):
        return None
    import re as _re
    if _re.match(r'^\d{4}-\d{2}-\d{2}', s):
        cand = s[:10]
        return cand if _valid_iso_date(cand) else s
    m = _re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', s)
    if m:
        mm, dd, yyyy = m.group(1), m.group(2), m.group(3)
        try:
            if int(mm) > 12:
                mm, dd = dd, mm
        except ValueError:
            pass
        iso = f"{yyyy}-{int(mm):02d}-{int(dd):02d}"
        return iso if _valid_iso_date(iso) else s
    m = _re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', s)
    if m:
        iso = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        return iso if _valid_iso_date(iso) else s
    return s


_OEM_EXTRACTORS = {
    'hpe':        _extract_oem_hpe,
    'dell':       _extract_oem_dell,
    'lenovo':     _extract_oem_lenovo,
    'supermicro': _extract_oem_supermicro,
    'cisco':      _extract_oem_cisco,
}


_OEM_NAMESPACE_FALLBACK_CHAIN = (
    ('dell',       ('Dell',)),
    ('hpe',        ('Hpe', 'Hp')),
    ('lenovo',     ('Lenovo',)),
    ('cisco',      ('Cisco', 'Cisco_RackUnit')),
    ('supermicro', ('Supermicro',)),
    ('huawei',     ('Huawei',)),
    ('inspur',     ('Inspur', 'Inspur_System')),
    ('fujitsu',    ('ts_fujitsu', 'Fujitsu')),
    ('quanta',     ('Quanta_Computer_Inc', 'QCT')),
)


def _extract_oem_unified(data, expected_vendor=None):
    if not isinstance(data, dict):
        return {}, None, None
    oem_root = data.get('Oem')
    if not isinstance(oem_root, dict) or not oem_root:
        return {}, None, None
    chain = _OEM_NAMESPACE_FALLBACK_CHAIN
    if expected_vendor:
        chain = tuple((v, ns) for v, ns in chain if v == expected_vendor)
    for vendor_key, namespaces in chain:
        for ns in namespaces:
            value = oem_root.get(ns)
            if isinstance(value, dict) and value:
                return value, vendor_key, ns
    return {}, None, None


def gather_system(bmc_ip, system_uri, vendor, username, password, timeout, verify_ssl,
                  chassis_uri=None, product_hint=None, bios_link_out=None):
    st, data, err = _get(bmc_ip, _p(system_uri), username, password, timeout, verify_ssl)
    errors = []
    if err or st != 200:
        errors.append(_err('system', f'System 수집 실패: {err or st}'))
        return {}, errors

    if bios_link_out is not None:
        bios_link_out['retrieved'] = True
        bios_link_out['link'] = _safe(data, 'Bios', '@odata.id')

    chassis_data = None
    if chassis_uri:
        cst, cdata, _cerr = _get(bmc_ip, _p(chassis_uri), username, password, timeout, verify_ssl)
        if not _cerr and cst == 200:
            chassis_data = cdata

    hostname = _safe(data, 'HostName')
    if isinstance(hostname, str) and not hostname.strip():
        hostname = None

    led_state = _safe(data, 'IndicatorLED')
    if led_state is None:
        loc_active = _safe(data, 'LocationIndicatorActive')
        if loc_active is not None:
            led_state = 'Blinking' if loc_active else 'Off'

    mem_health = _safe(data, 'MemorySummary', 'Status', 'Health')
    if mem_health is None:
        mem_health = _safe(data, 'MemorySummary', 'Status', 'HealthRollup')

    tpm_modules = _safe(data, 'TrustedModules') or []
    tpm_summary = None
    if isinstance(tpm_modules, list) and tpm_modules:
        first_tpm = tpm_modules[0] if isinstance(tpm_modules[0], dict) else {}
        tpm_summary = {
            'interface_type':   _safe(first_tpm, 'InterfaceType'),
            'firmware_version': _safe(first_tpm, 'FirmwareVersion'),
            'state':            _safe(first_tpm, 'Status', 'State'),
        }

    def _ne(*keys):
        return _strip_or_none(_safe(data, *keys))

    result = {
        'manufacturer':   _ne('Manufacturer'),
        'model':          _ne('Model'),
        'serial':         _ne('SerialNumber'),
        'sku':            _ne('SKU'),
        'uuid':           _ne('UUID'),
        'hostname':       hostname,
        'power_state':    _safe(data, 'PowerState'),
        'health':         _safe(data, 'Status', 'Health'),
        'state':          _safe(data, 'Status', 'State'),
        'led_state':      led_state,
        'bios_version':   _ne('BiosVersion'),
        'bios_date':      None,
        'asset_tag':      _ne('AssetTag'),
        'system_type':    _safe(data, 'SystemType'),
        'part_number':    _ne('PartNumber'),
        'last_reset_time': _safe(data, 'LastResetTime'),
        'boot_progress':  _safe(data, 'BootProgress', 'LastState'),
        'tpm':            tpm_summary,
        'cpu_summary': {
            'count':  _safe_int(_safe(data, 'ProcessorSummary', 'Count')),
            'core_count':              _safe_int(_safe(data, 'ProcessorSummary', 'CoreCount')),
            'logical_processor_count': _safe_int(_safe(data, 'ProcessorSummary', 'LogicalProcessorCount')),
            'model':  _safe(data, 'ProcessorSummary', 'Model'),
            'health': (_safe(data, 'ProcessorSummary', 'Status', 'Health')
                       or _safe(data, 'ProcessorSummary', 'Status', 'HealthRollup')),
        },
        'memory_summary': {
            'total_gib': _safe_int(_safe(data, 'MemorySummary', 'TotalSystemMemoryGiB')),
            'health':    mem_health,
        },
        'oem': {},
    }

    extractor = _OEM_EXTRACTORS.get(vendor)
    if extractor is not None:
        if vendor in ('lenovo', 'cisco'):
            raw_oem = extractor(data, chassis_data=chassis_data)
        else:
            raw_oem = extractor(data)
        result['oem'] = _hoist_oem_extras(raw_oem, result)

    if result['model'] is None and product_hint:
        _ph = _strip_or_none(product_hint)
        if _ph is not None and isinstance(_ph, str):
            result['model'] = _ph
    if isinstance(chassis_data, dict):
        if result['manufacturer'] is None:
            _cm = _strip_or_none(_safe(chassis_data, 'Manufacturer'))
            if _cm is not None:
                result['manufacturer'] = _cm
        if result['model'] is None:
            _cmod = _strip_or_none(_safe(chassis_data, 'Model'))
            if _cmod is not None:
                result['model'] = _cmod


    return result, errors


_BIOS_ODATA_TYPE_PREFIX = '#Bios.'


def gather_bios(bmc_ip, bios_link, username, password, timeout, verify_ssl):
    out = {'current': {'attributes': None}}
    errors = []
    try:
        link_info = bios_link if isinstance(bios_link, dict) else {}
        if not link_info.get('retrieved'):
            _notice('bios', 'ComputerSystem 응답이 없어 BIOS Current Attributes 조회 안 함')
            return out, errors
        link = link_info.get('link')
        if not isinstance(link, str) or not link.strip():
            _notice('bios', 'ComputerSystem 에 Bios 링크가 없어 BIOS Current Attributes 조회 안 함')
            return out, errors

        st, data, err = _get(bmc_ip, _p(link), username, password, timeout, verify_ssl)
        if st == 404:
            _notice('bios', 'Bios 리소스 404, BIOS Current Attributes 미수집')
            return out, errors
        if err or st != 200:
            errors.append(_err('bios', 'BIOS Current Attributes 조회 실패',
                               err or f'HTTP {st}', code=_CODE_BIOS_NON_BLOCKING))
            return out, errors
        if not isinstance(data, dict):
            errors.append(_err('bios', 'BIOS 응답이 JSON 객체가 아님',
                               f'HTTP 200: body type {type(data).__name__}',
                               code=_CODE_BIOS_NON_BLOCKING))
            return out, errors

        odata_type = data.get('@odata.type')
        if odata_type is not None and not (
                isinstance(odata_type, str) and odata_type.startswith(_BIOS_ODATA_TYPE_PREFIX)):
            _notice('bios', '표준 Bios 리소스가 아님(@odata.type), BIOS Current Attributes 미수집')
            return out, errors

        if 'Attributes' not in data:
            errors.append(_err('bios', 'BIOS 응답에 Attributes 없음',
                               'HTTP 200: Attributes missing', code=_CODE_BIOS_NON_BLOCKING))
            return out, errors
        attributes = data['Attributes']
        if not isinstance(attributes, dict):
            errors.append(_err('bios', 'BIOS Attributes 가 객체가 아님',
                               f'HTTP 200: Attributes type {type(attributes).__name__}',
                               code=_CODE_BIOS_NON_BLOCKING))
            return out, errors

        if not attributes:
            _notice('bios', 'Bios.Attributes 가 비어 있음')
        out['current']['attributes'] = {key: attributes[key] for key in sorted(attributes)}
        return out, errors
    except Exception as e:
        sys.stderr.write(
            "[redfish_gather] bios 예외: %s\n%s\n" %
            (type(e).__name__, traceback.format_exc(limit=3))
        )
        return {'current': {'attributes': None}}, [_err(
            'bios', '예외 발생', "%s: %s" % (type(e).__name__, str(e)[:200]),
            code=_CODE_BIOS_NON_BLOCKING)]


def gather_bmc(bmc_ip, manager_uri, vendor, username, password, timeout, verify_ssl,
               manager_layout=None, is_first=True, manager_id=None):
    if not manager_uri:
        return {}, [_err('bmc', 'manager_uri 없음')]

    st, data, err = _get(bmc_ip, _p(manager_uri), username, password, timeout, verify_ssl)
    errors = []
    if err or st != 200:
        errors.append(_err('bmc', f'BMC 수집 실패: {err or st}'))
        return {}, errors

    bmc_names = {'dell': 'iDRAC', 'hpe': 'iLO', 'lenovo': 'XCC', 'supermicro': 'BMC',
                 'cisco': 'CIMC',
                 'huawei': 'iBMC', 'inspur': 'ISBMC', 'fujitsu': 'iRMC',
                 'quanta': 'BMC'}
    _mid = manager_id if manager_id is not None else _safe(data, 'Id')
    rmc_label = _classify_rmc_label(manager_uri, _mid, manager_layout, is_first)
    result = {
        'name':             rmc_label or bmc_names.get(vendor, 'BMC'),
        'firmware_version': _safe(data, 'FirmwareVersion'),
        'model':            _safe(data, 'Model'),
        'manager_type':     _safe(data, 'ManagerType'),
        'health':           _safe(data, 'Status', 'Health'),
        'state':            _safe(data, 'Status', 'State'),
        'power_state':      _safe(data, 'PowerState'),
        'uuid':             _safe(data, 'UUID'),
        'serial':           _strip_or_none(_safe(data, 'SerialNumber')),
        'part_number':      _strip_or_none(_safe(data, 'PartNumber')),
        'manufacturer':     _strip_or_none(_safe(data, 'Manufacturer')),
        'last_reset_time':  _safe(data, 'LastResetTime'),
        'timezone':         _safe(data, 'TimeZoneName'),
        'ip':               None,
        'mac_address':      None,
        'dns_name':         None,
        'network_hostname': None,
        'datetime':         _safe(data, 'DateTime'),
        'datetime_offset':  _safe(data, 'DateTimeLocalOffset'),
        'oem': {},
    }

    bmc_name_servers = []
    bmc_static_name_servers = []
    bmc_gateways = []
    nic_link = _safe(data, 'EthernetInterfaces', '@odata.id')
    if nic_link:
        nst, ncoll, nerr = _get(bmc_ip, _p(nic_link), username, password, timeout, verify_ssl)
        if not nerr and nst == 200:
            for nm in _collection_members(bmc_ip, _p(nic_link), ncoll, username, password, timeout,
                                          verify_ssl, 'bmc', None):
                nuri = _safe(nm, '@odata.id')
                if not nuri:
                    continue
                nst2, ndata, nerr2 = _get(bmc_ip, _p(nuri), username, password, timeout, verify_ssl)
                if nerr2 or nst2 != 200:
                    continue
                nic_first_ip = None
                for addr in _dicts(_safe(ndata, 'IPv4Addresses')):
                    ip = _safe(addr, 'Address')
                    if ip and isinstance(ip, str) and ip not in ('0.0.0.0', ''):
                        if nic_first_ip is None:
                            nic_first_ip = ip
                        gw = _safe(addr, 'Gateway')
                        if gw and isinstance(gw, str) and gw not in ('0.0.0.0', '') and gw not in bmc_gateways:
                            bmc_gateways.append(gw)
                _ns_placeholders = ('', '0.0.0.0', '::', '::0', '::1')
                for ns in _as_list(_safe(ndata, 'NameServers')):
                    if isinstance(ns, str) and ns and ns not in _ns_placeholders and ns not in bmc_name_servers:
                        bmc_name_servers.append(ns)
                for ns in _as_list(_safe(ndata, 'StaticNameServers')):
                    if isinstance(ns, str) and ns and ns not in _ns_placeholders and ns not in bmc_static_name_servers:
                        bmc_static_name_servers.append(ns)
                if nic_first_ip:
                    if not result['ip']:
                        result['ip'] = nic_first_ip
                    if not result['mac_address']:
                        _mac = _safe(ndata, 'MACAddress') or _safe(ndata, 'PermanentMACAddress')
                        result['mac_address'] = _mac.lower() if isinstance(_mac, str) else None
                    if not result['dns_name']:
                        result['dns_name'] = _safe(ndata, 'FQDN') or _safe(ndata, 'HostName')

    result['_network_meta'] = {
        'name_servers':        bmc_name_servers,
        'static_name_servers': bmc_static_name_servers,
        'ipv4_gateways':       bmc_gateways,
    }

    np_link = _safe(data, 'NetworkProtocol', '@odata.id')
    if np_link:
        npst, npdata, _nperr = _get(bmc_ip, _p(np_link), username, password, timeout, verify_ssl)
        if not _nperr and npst == 200 and isinstance(npdata, dict):
            result['network_hostname'] = (_strip_or_none(_safe(npdata, 'FQDN'))
                                          or _strip_or_none(_safe(npdata, 'HostName')))

    if vendor == 'hpe':
        oem = _safe(data, 'Oem', 'Hpe') or _safe(data, 'Oem', 'Hp') or {}
        result['oem'] = {
            'ilo_version': _safe(oem, 'Firmware', 'Current', 'VersionString'),
        }
    elif vendor == 'supermicro':
        oem = _safe(data, 'Oem', 'Supermicro') or {}
        result['oem'] = {'bmc_ip': _safe(oem, 'BMCIPv4Address')}
        if not result['ip'] and result['oem'].get('bmc_ip'):
            result['ip'] = result['oem']['bmc_ip']
    elif vendor == 'lenovo':
        oem = _safe(data, 'Oem', 'Lenovo') or {}
        result['oem'] = {'release_name': _safe(oem, 'release_name')}
    elif vendor == 'dell':
        oem_dell = _safe(data, 'Oem', 'Dell', 'DelliDRACCard') or {}
        result['oem'] = {
            'idrac_ipmi_version':            _safe(oem_dell, 'IPMIVersion'),
            'idrac_last_inventory_time':     _safe(oem_dell, 'LastSystemInventoryTime'),
            'idrac_last_update_time':        _safe(oem_dell, 'LastUpdateTime'),
            'idrac_url':                     _safe(oem_dell, 'URLString'),
        }

    return result, errors


def gather_processors(bmc_ip, system_uri, username, password, timeout, verify_ssl):
    path = _p(system_uri) + '/Processors'
    st, coll, err = _get(bmc_ip, path, username, password, timeout, verify_ssl)
    errors = []
    if err or st != 200:
        errors.append(_err('processors', f'Processor 컬렉션 실패: {err or st}'))
        return [], errors

    processors = []
    _absent = 0
    for member in _collection_members(bmc_ip, path, coll, username, password, timeout, verify_ssl,
                                      'processors', errors):
        uri = _safe(member, '@odata.id')
        if not uri: continue
        st, pdata, perr = _get(bmc_ip, _p(uri), username, password, timeout, verify_ssl)
        if perr or st != 200:
            errors.append(_err('processors', f'Processor {uri} 실패: {perr or st}', code=_CODE_NON_BLOCKING_SUBRESOURCE))
            continue
        if _safe(pdata, 'Status', 'State') in ('Absent', 'Disabled'):
            _absent += 1
            continue
        def _ne_p(*ks):
            return _strip_or_none(_safe(pdata, *ks))

        processors.append({
            'id':                _safe(pdata, 'Id'),
            'name':              _ne_p('Name'),
            'model':             _ne_p('Model'),
            'manufacturer':      _ne_p('Manufacturer'),
            'socket':            _safe(pdata, 'Socket'),
            'total_cores':       _safe_int(_safe(pdata, 'TotalCores')),
            'total_threads':     _safe_int(_safe(pdata, 'TotalThreads')),
            'speed_mhz':         _safe_int(_safe(pdata, 'MaxSpeedMHz')),
            'health':            _safe(pdata, 'Status', 'Health'),
            'processor_type':    _safe(pdata, 'ProcessorType'),
            'architecture':      _safe(pdata, 'ProcessorArchitecture'),
            'instruction_set':   _safe(pdata, 'InstructionSet'),
            'serial_number':     _ne_p('SerialNumber'),
            'part_number':       _ne_p('PartNumber'),
        })
    if not processors and _absent > 0:
        errors.append(_err('processors',
                           f'모든 CPU({_absent})가 Absent/Disabled (펌웨어 오류 또는 미장착 가능)'))
    return processors, errors


def gather_memory(bmc_ip, system_uri, username, password, timeout, verify_ssl):
    path = _p(system_uri) + '/Memory'
    st, coll, err = _get(bmc_ip, path, username, password, timeout, verify_ssl)
    errors = []
    if err or st != 200:
        errors.append(_err('memory', f'Memory 컬렉션 실패: {err or st}'))
        return {'total_mib': None, 'slots': []}, errors

    slots, total_mib, cap_unknown = [], 0, 0
    for member in _collection_members(bmc_ip, path, coll, username, password, timeout, verify_ssl,
                                      'memory', errors):
        uri = _safe(member, '@odata.id')
        if not uri: continue
        st, mdata, merr = _get(bmc_ip, _p(uri), username, password, timeout, verify_ssl)
        if merr or st != 200:
            errors.append(_err('memory', f'Memory {uri} 실패: {merr or st}', code=_CODE_NON_BLOCKING_SUBRESOURCE))
            continue
        if _safe(mdata, 'Status', 'State') == 'Absent':
            continue
        cap_int = _safe_int(_safe(mdata, 'CapacityMiB'))
        if cap_int is not None:
            total_mib += cap_int
        else:
            cap_unknown += 1
        _mloc_slot = _safe(mdata, 'MemoryLocation', 'Slot')
        slots.append({
            'id':              _safe(mdata, 'Id'),
            'name':            _strip_or_none(_safe(mdata, 'Name')),
            'locator':         (_safe(mdata, 'DeviceLocator')
                                or (str(_mloc_slot) if _mloc_slot else None)
                                or _safe(mdata, 'Location', 'PartLocation', 'ServiceLabel')
                                or (str(_mloc_slot) if _mloc_slot is not None else None)),
            'capacity_mb':     cap_int,
            'type':            _safe(mdata, 'MemoryDeviceType'),
            'base_module_type': _safe(mdata, 'BaseModuleType'),
            'speed_mhz':       _safe_int(_safe(mdata, 'OperatingSpeedMhz')),
            'manufacturer':    _normalize_jedec(_safe(mdata, 'Manufacturer')),
            'serial':          _strip_or_none(_safe(mdata, 'SerialNumber')),
            'part_number':     _strip_or_none(_safe(mdata, 'PartNumber')),
            'rank_count':      _safe_int(_safe(mdata, 'RankCount')),
            'data_width_bits': _safe_int(_safe(mdata, 'DataWidthBits')),
            'bus_width_bits':  _safe_int(_safe(mdata, 'BusWidthBits')),
            'error_correction': _safe(mdata, 'ErrorCorrection'),
            'health':          _safe(mdata, 'Status', 'Health'),
        })
    if slots and cap_unknown:
        if cap_unknown == len(slots):
            errors.append(_err('memory',
                               f'CapacityMiB 부재: 장착 DIMM {len(slots)}개 모두 용량 미확인 — 합계 미산출',
                               code=_CODE_NON_BLOCKING_SUBRESOURCE))
        else:
            _notice('memory', f'CapacityMiB 부재 DIMM {cap_unknown}/{len(slots)} — 합계 미산출(slot 은 보존)')
        total_mib = None
    return {'total_mib': total_mib, 'slots': slots}, errors


def _gather_simple_storage(bmc_ip, members, username, password, timeout, verify_ssl):
    controllers = []
    errors = []
    for member in members:
        uri = _safe(member, '@odata.id')
        if not uri:
            continue
        st, sdata, serr = _get(bmc_ip, _p(uri), username, password, timeout, verify_ssl)
        if serr or st != 200:
            errors.append(_err('storage', f'SimpleStorage {uri} 실패: {serr or st}', code=_CODE_NON_BLOCKING_SUBRESOURCE))
            continue
        drives = []
        for dev in _dicts(_safe(sdata, 'Devices')):
            cap_int = _safe_int(_safe(dev, 'CapacityBytes'))
            drives.append({
                'id':             None,
                'name':           _safe(dev, 'Name'),
                'model':          _safe(dev, 'Model'),
                'serial':         None,
                'manufacturer':   _safe(dev, 'Manufacturer'),
                'media_type':     None,
                'protocol':       None,
                'capacity_bytes': cap_int,
                'capacity_gb':    round(cap_int / BYTES_PER_GB_DECIMAL, 2) if cap_int is not None else None,
                'health':         _safe(dev, 'Status', 'Health'),
            })
        controllers.append({
            'id': _safe(sdata, 'Id'), 'name': _safe(sdata, 'Name'),
            'health': _safe(sdata, 'Status', 'Health'), 'drives': drives,
        })
    return controllers, errors


def _extract_storage_controller_info(sdata, bmc_ip, username, password, timeout, verify_ssl):
    errors = []
    inline_ctrls = _safe(sdata, 'StorageControllers') or []
    if isinstance(inline_ctrls, list) and inline_ctrls:
        c = inline_ctrls[0]
        return {
            'controller_name':         _safe(c, 'Name'),
            'controller_model':        _safe(c, 'Model'),
            'controller_firmware':     _safe(c, 'FirmwareVersion'),
            'controller_manufacturer': _safe(c, 'Manufacturer'),
            'controller_health':       _safe(c, 'Status', 'Health'),
        }, errors
    ctrl_link = _safe(sdata, 'Controllers', '@odata.id')
    if not ctrl_link:
        return {}, errors
    cst, ctrl_coll, cerr = _get(bmc_ip, _p(ctrl_link), username, password, timeout, verify_ssl)
    if cerr or cst != 200:
        errors.append(_err('storage',
                           f'Controllers 컬렉션 fetch 실패 ({ctrl_link}): {cerr or cst}',
                           detail={'status_code': cst}))
        return {'controller_fetch_status': cst}, errors
    ctrl_members = _safe(ctrl_coll, 'Members') or []
    if not isinstance(ctrl_members, list) or not ctrl_members:
        return {}, errors
    c_uri = _safe(ctrl_members[0], '@odata.id')
    if not c_uri:
        return {}, errors
    cst2, cdata, cerr2 = _get(bmc_ip, _p(c_uri), username, password, timeout, verify_ssl)
    if cerr2 or cst2 != 200:
        errors.append(_err('storage',
                           f'Controller fetch 실패 ({c_uri}): {cerr2 or cst2}',
                           detail={'status_code': cst2}))
        return {'controller_fetch_status': cst2}, errors
    return {
        'controller_name':         _safe(cdata, 'Name'),
        'controller_model':        _safe(cdata, 'Model'),
        'controller_firmware':     _safe(cdata, 'FirmwareVersion'),
        'controller_manufacturer': _safe(cdata, 'Manufacturer'),
        'controller_health':       _safe(cdata, 'Status', 'Health'),
    }, errors


def _extract_storage_drives(sdata, bmc_ip, username, password, timeout, verify_ssl):
    drives = []
    errors = []
    for d_member in _capped(_safe(sdata, 'Drives') or [], 'storage', errors):
        d_uri = _safe(d_member, '@odata.id')
        if not d_uri:
            continue
        dst, ddata, derr = _get(bmc_ip, _p(d_uri), username, password, timeout, verify_ssl)
        if derr or dst != 200:
            errors.append(_err('storage', f'Drive {d_uri} 실패: {derr or dst}', code=_CODE_NON_BLOCKING_SUBRESOURCE))
            continue
        drive_name = _str(_safe(ddata, 'Name'))
        cap_int = _safe_int(_safe(ddata, 'CapacityBytes'), default=0)
        if not cap_int:
            continue
        if 'empty' in drive_name.lower():
            continue
        life_pct = _safe(ddata, 'PredictedMediaLifeLeftPercent')
        if life_pct is not None:
            life_pct = _safe_int(life_pct)
        drives.append({
            'id':             _safe(ddata, 'Id'),
            'name':           _safe(ddata, 'Name'),
            'model':          _safe(ddata, 'Model'),
            'serial':         _safe(ddata, 'SerialNumber'),
            'manufacturer':   _safe(ddata, 'Manufacturer'),
            'media_type':     _safe(ddata, 'MediaType'),
            'protocol':       _safe(ddata, 'Protocol'),
            'capacity_bytes': cap_int,
            'capacity_gb':    round(cap_int / BYTES_PER_GB_DECIMAL, 2) if cap_int else None,
            'health':         _safe(ddata, 'Status', 'Health') or _safe(ddata, 'Status', 'HealthRollup'),
            'failure_predicted':      _safe(ddata, 'FailurePredicted'),
            'predicted_life_percent': life_pct,
        })
    return drives, errors


_VOLUMETYPE_RAID_MAP = {
    'NonRedundant': 'RAID0', 'Mirrored': 'RAID1',
    'StripedWithParity': 'RAID5', 'SpannedMirrors': 'RAID10',
    'SpannedStripesWithParity': 'RAID50',
}


def _extract_storage_volumes(sdata, controller_id, bmc_ip, username, password, timeout, verify_ssl):
    volumes = []
    errors = []
    vol_link = _safe(sdata, 'Volumes', '@odata.id')
    if not vol_link:
        return volumes, errors
    vst, vcoll, verr = _get(bmc_ip, _p(vol_link), username, password, timeout, verify_ssl)
    if verr or vst != 200:
        return volumes, errors
    _boot_vd_fqdd = _safe(sdata, 'Oem', 'Dell', 'DellController', 'BootVirtualDiskFQDD')
    if not (isinstance(_boot_vd_fqdd, str) and _boot_vd_fqdd.strip()):
        _boot_vd_fqdd = None
    for v_member in _collection_members(bmc_ip, _p(vol_link), vcoll, username, password, timeout,
                                        verify_ssl, 'storage', errors):
        v_uri = _safe(v_member, '@odata.id')
        if not v_uri:
            continue
        vst2, vdata, verr2 = _get(bmc_ip, _p(v_uri), username, password, timeout, verify_ssl)
        if verr2 or vst2 != 200:
            errors.append(_err('storage', f'Volume {v_uri} 실패: {verr2 or vst2}', code=_CODE_NON_BLOCKING_SUBRESOURCE))
            continue
        raid_type = _safe(vdata, 'RAIDType') or _VOLUMETYPE_RAID_MAP.get(_safe(vdata, 'VolumeType'))
        member_ids = [
            d_oid.rstrip('/').rsplit('/', 1)[-1]
            for d_link in _dicts(_safe(vdata, 'Links', 'Drives'))
            for d_oid in [_safe(d_link, '@odata.id')] if d_oid and isinstance(d_oid, str)
        ]
        vol_id = _safe(vdata, 'Id')
        if raid_type is None and len(member_ids) == 1 and member_ids[0] == vol_id:
            continue
        vcap_int = _safe_int(_safe(vdata, 'CapacityBytes'))
        v_name_raw = _safe(vdata, 'Name')
        v_name = v_name_raw.strip() if isinstance(v_name_raw, str) else v_name_raw
        if not v_name:
            if vol_id:
                v_name = f"Volume {vol_id}"
            elif raid_type:
                v_name = f"{raid_type} Volume"
            else:
                v_name = None
        std_boot = _safe(vdata, 'BootVolume')
        if std_boot is not None:
            boot_volume = bool(std_boot)
        elif _boot_vd_fqdd is not None and vol_id is not None:
            boot_volume = (vol_id == _boot_vd_fqdd)
        elif _safe(vdata, 'Oem', 'Dell'):
            boot_volume = _safe(vdata, 'Oem', 'Dell', 'DellVolume', 'BootVolumeSource') is not None
        else:
            boot_volume = None
        volumes.append({
            'id':               _safe(vdata, 'Id'),
            'name':             v_name,
            'controller_id':    controller_id,
            'member_drive_ids': member_ids,
            'raid_level':       raid_type,
            'total_mb':         (vcap_int // BYTES_PER_MIB) if vcap_int is not None else None,
            'health':           _safe(vdata, 'Status', 'Health') or _safe(vdata, 'Status', 'HealthRollup'),
            'state':            _safe(vdata, 'Status', 'State'),
            'boot_volume':      boot_volume,
        })
    return volumes, errors


def _gather_standard_storage(bmc_ip, members, username, password, timeout, verify_ssl):
    controllers = []
    volumes = []
    errors = []
    for member in members:
        uri = _safe(member, '@odata.id')
        if not uri:
            continue
        st, sdata, serr = _get(bmc_ip, _p(uri), username, password, timeout, verify_ssl)
        if serr or st != 200:
            errors.append(_err('storage', f'Storage {uri} 실패: {serr or st}', code=_CODE_NON_BLOCKING_SUBRESOURCE))
            continue
        ctrl_info, c_errs = _extract_storage_controller_info(sdata, bmc_ip, username, password, timeout, verify_ssl)
        errors.extend(c_errs)
        drives, d_errs = _extract_storage_drives(sdata, bmc_ip, username, password, timeout, verify_ssl)
        errors.extend(d_errs)
        ctrl_name = ctrl_info.get('controller_name') or _safe(sdata, 'Name')
        ctrl_entry = {
            'id':     _safe(sdata, 'Id'),
            'name':   ctrl_name,
            'health': _safe(sdata, 'Status', 'Health') or _safe(sdata, 'Status', 'HealthRollup'),
            'drives': drives,
        }
        ctrl_entry.update(ctrl_info)
        controllers.append(ctrl_entry)
        vols, v_errs = _extract_storage_volumes(sdata, _safe(sdata, 'Id'), bmc_ip, username, password, timeout, verify_ssl)
        volumes.extend(vols)
        errors.extend(v_errs)
    return controllers, volumes, errors


def _gather_smart_storage(bmc_ip, system_uri, username, password, timeout, verify_ssl):
    base = _p(system_uri) + '/SmartStorage'
    st, ss_root, err = _get(bmc_ip, base, username, password, timeout, verify_ssl)
    errors = []
    if err or st != 200:
        errors.append(_err('storage', f'SmartStorage 미지원: {err or st}'))
        return [], [], errors

    controllers = []
    for coll_key in ('ArrayControllers', 'HostBusAdapters'):
        coll_link = _safe(ss_root, coll_key, '@odata.id')
        if not coll_link:
            continue
        cst, coll, cerr = _get(bmc_ip, _p(coll_link), username, password, timeout, verify_ssl)
        if cerr or cst != 200:
            errors.append(_err('storage', f'SmartStorage.{coll_key} 실패: {cerr or cst}'))
            continue
        for member in _collection_members(bmc_ip, _p(coll_link), coll, username, password, timeout,
                                          verify_ssl, 'storage', errors):
            ctrl_uri = _safe(member, '@odata.id')
            if not ctrl_uri:
                continue
            ctrl_st, ctrl_data, ctrl_err = _get(bmc_ip, _p(ctrl_uri), username, password, timeout, verify_ssl)
            if ctrl_err or ctrl_st != 200:
                errors.append(_err('storage', f'SmartStorage controller {ctrl_uri} 실패: {ctrl_err or ctrl_st}', code=_CODE_NON_BLOCKING_SUBRESOURCE))
                continue
            drives = []
            pd_link = _safe(ctrl_data, 'PhysicalDrives', '@odata.id') or _safe(ctrl_data, 'Links', 'PhysicalDrives', '@odata.id')
            if pd_link:
                pst, pcoll, _perr = _get(bmc_ip, _p(pd_link), username, password, timeout, verify_ssl)
                if pst == 200:
                    for pd_m in _collection_members(bmc_ip, _p(pd_link), pcoll, username, password,
                                                    timeout, verify_ssl, 'storage', errors):
                        pd_uri = _safe(pd_m, '@odata.id')
                        if not pd_uri:
                            continue
                        pdst, pddata, _pderr = _get(bmc_ip, _p(pd_uri), username, password, timeout, verify_ssl)
                        if pdst != 200:
                            continue
                        cap_gb_field = _safe_int(_safe(pddata, 'CapacityGB'))
                        cap_mib_field = _safe_int(_safe(pddata, 'CapacityMiB'))
                        if cap_gb_field:
                            cap_bytes = cap_gb_field * BYTES_PER_GB_DECIMAL
                            capacity_gb = round(float(cap_gb_field), 2)
                        elif cap_mib_field:
                            cap_bytes = cap_mib_field * BYTES_PER_MIB
                            capacity_gb = round(cap_bytes / BYTES_PER_GB_DECIMAL, 2)
                        else:
                            cap_bytes = None
                            capacity_gb = None
                        drives.append({
                            'id':             _safe(pddata, 'Id'),
                            'name':           _safe(pddata, 'Model') or _safe(pddata, 'Name'),
                            'model':          _safe(pddata, 'Model'),
                            'serial':         _safe(pddata, 'SerialNumber'),
                            'manufacturer':   _safe(pddata, 'Manufacturer'),
                            'media_type':     _safe(pddata, 'MediaType'),
                            'protocol':       _safe(pddata, 'InterfaceType'),
                            'capacity_bytes': cap_bytes,
                            'capacity_gb':    capacity_gb,
                            'health':         _safe(pddata, 'Status', 'Health'),
                        })
            ctrl_id = _safe(ctrl_data, 'Id')
            controllers.append({
                'id':                      ctrl_id,
                'name':                    _safe(ctrl_data, 'Model') or _safe(ctrl_data, 'Name'),
                'health':                  _safe(ctrl_data, 'Status', 'Health'),
                'drives':                  drives,
                'controller_name':         _safe(ctrl_data, 'Model'),
                'controller_model':        _safe(ctrl_data, 'Model'),
                'controller_firmware':     _safe(ctrl_data, 'FirmwareVersion', 'Current', 'VersionString')
                                           or _safe(ctrl_data, 'FirmwareVersion'),
                'controller_manufacturer': _safe(ctrl_data, 'Manufacturer') or 'HPE',
                'controller_health':       _safe(ctrl_data, 'Status', 'Health'),
            })
    return controllers, [], errors


def gather_storage(bmc_ip, system_uri, username, password, timeout, verify_ssl):
    path = _p(system_uri) + '/Storage'
    st, coll, err = _get(bmc_ip, path, username, password, timeout, verify_ssl)
    errors = []

    use_simple = False
    if err or st != 200:
        simple_path = _p(system_uri) + '/SimpleStorage'
        st2, coll2, err2 = _get(bmc_ip, simple_path, username, password, timeout, verify_ssl)
        if not err2 and st2 == 200:
            use_simple = True
            coll = coll2
            _notice('storage', 'Storage 미지원, SimpleStorage fallback 사용')
        else:
            ctrls, vols, smart_errors = _gather_smart_storage(
                bmc_ip, system_uri, username, password, timeout, verify_ssl
            )
            if ctrls:
                _notice('storage', 'Storage/SimpleStorage 미지원, SmartStorage (HPE OEM legacy) fallback 사용')
                errors.extend(smart_errors)
                return {'controllers': ctrls, 'volumes': vols}, errors
            errors.append(_err('storage', f'Storage/SimpleStorage/SmartStorage 모두 실패: {err or st}'))
            return {'controllers': [], 'volumes': []}, errors

    members = _collection_members(bmc_ip, (simple_path if use_simple else path), coll, username,
                                  password, timeout, verify_ssl, 'storage', errors)
    if use_simple:
        controllers, sub_errors = _gather_simple_storage(bmc_ip, members, username, password, timeout, verify_ssl)
        errors.extend(sub_errors)
        if not controllers and not errors:
            errors.append(_err('storage',
                               'SimpleStorage 경로가 응답했지만 디스크 정보가 비어 있음'))
        return {'controllers': controllers, 'volumes': []}, errors
    controllers, volumes, sub_errors = _gather_standard_storage(bmc_ip, members, username, password, timeout, verify_ssl)
    errors.extend(sub_errors)
    return {'controllers': controllers, 'volumes': volumes}, errors


def gather_network(bmc_ip, system_uri, username, password, timeout, verify_ssl):
    path = _p(system_uri) + '/EthernetInterfaces'
    st, coll, err = _get(bmc_ip, path, username, password, timeout, verify_ssl)
    errors = []
    if err or st != 200:
        errors.append(_err('network', f'EthernetInterfaces 실패: {err or st}'))
        return [], errors

    nics = []
    for member in _collection_members(bmc_ip, path, coll, username, password, timeout, verify_ssl,
                                      'network', errors):
        uri = _safe(member, '@odata.id')
        if not uri: continue
        st, ndata, nerr = _get(bmc_ip, _p(uri), username, password, timeout, verify_ssl)
        if nerr or st != 200:
            errors.append(_err('network', f'NIC {uri} 실패: {nerr or st}', code=_CODE_NON_BLOCKING_SUBRESOURCE))
            continue
        ipv4_addrs = [
            {'address': a.get('Address'), 'subnet_mask': a.get('SubnetMask'),
             'gateway': a.get('Gateway'), 'address_origin': a.get('AddressOrigin')}
            for a in _dicts(_safe(ndata, 'IPv4Addresses'))
            if a.get('Address') not in (None, '0.0.0.0', '')
        ]
        _nmac = _safe(ndata, 'MACAddress')
        nics.append({
            'id': _safe(ndata, 'Id'), 'name': _safe(ndata, 'Name') or _safe(ndata, 'Id') or '',
            'mac': _nmac.lower() if isinstance(_nmac, str) else _nmac, 'speed_mbps': _safe_int(_safe(ndata, 'SpeedMbps')),
            'mtu': _safe_int(_safe(ndata, 'MTUSize')),
            'link_status': _normalize_link_status(_safe(ndata, 'LinkStatus')),
            'health': _safe(ndata, 'Status', 'Health'),
            'ipv4': ipv4_addrs,
        })
    return nics, errors


def _detect_nic_ocp_slot(adata):
    if not isinstance(adata, dict):
        return None
    loc = _safe(adata, 'Location', 'PartLocation') or {}
    service_label = _str(_safe(loc, 'ServiceLabel')).upper()
    location_type = _str(_safe(loc, 'LocationType')).lower()
    name = _str(_safe(adata, 'Name')).upper()
    if 'OCP' in service_label or 'OCP' in name:
        return 'ocp'
    hpe_oem = _safe(adata, 'Oem', 'Hpe') or {}
    if _safe(hpe_oem, 'Location', 'OCPSlot') or _safe(hpe_oem, 'OCPSlot'):
        return 'ocp'
    if location_type == 'slot':
        return 'pcie'
    return None


def _detect_nic_sriov_capable(adata):
    if not isinstance(adata, dict):
        return None
    if _safe(adata, 'SRIOV', 'SRIOVCapable') is True:
        return True
    dell_oem = _safe(adata, 'Oem', 'Dell') or {}
    dell_sriov = _safe(dell_oem, 'NICDeviceFunctions', 'SRIOVCapable')
    if dell_sriov is not None:
        return bool(dell_sriov)
    hpe_oem = _safe(adata, 'Oem', 'Hpe') or {}
    if _safe(hpe_oem, 'NetworkAdapter', 'SRIOVConfig'):
        return True
    return None


def _normalize_wwn(value):
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s or s in ('none', 'null', '0', '0x0'):
        return None
    s = _removeprefix(s, '0x')
    hexonly = ''.join(c for c in s if c in '0123456789abcdef')
    if len(hexonly) != 16:
        return str(value).strip().lower()
    if hexonly == '0' * 16:
        return None
    return ':'.join(hexonly[i:i + 2] for i in range(0, 16, 2))


def _classify_port_protocol(port_protocol, link_tech, ndf, pdata=None):
    pp = _str(port_protocol).strip().upper()
    lt = _str(link_tech).strip().lower()
    ndf_type = ''
    ndf_tech = ''
    ndf_wwpn = None
    if isinstance(ndf, dict):
        ndf_type = _str(ndf.get('func_type')).strip().lower()
        ndf_tech = _str(ndf.get('net_dev_tech')).strip().lower()
        ndf_wwpn = ndf.get('wwpn')
    if lt == 'infiniband' or ndf_tech == 'infiniband' or ndf_type == 'infiniband':
        return 'InfiniBand'
    if isinstance(pdata, dict) and isinstance(pdata.get('InfiniBand'), dict):
        return 'InfiniBand'
    if pp == 'FCOE' or ndf_type == 'fibrechanneloverethernet':
        return 'FCoE'
    if pp in ('FC', 'FCP', 'FIBRECHANNEL') or ndf_type == 'fibrechannel':
        return 'FibreChannel'
    if isinstance(pdata, dict) and isinstance(pdata.get('FibreChannel'), dict):
        return 'FibreChannel'
    if pp == 'ETHERNET' or lt == 'ethernet' or ndf_type == 'ethernet':
        return 'Ethernet'
    if isinstance(pdata, dict) and isinstance(pdata.get('Ethernet'), dict):
        return 'Ethernet'
    if ndf_wwpn:
        return 'FibreChannel'
    return None


def _fetch_ndf_index(bmc_ip, adata, username, password, timeout, verify_ssl, errors=None):
    ndfs = []
    ndf_link = _safe(adata, 'NetworkDeviceFunctions', '@odata.id')
    if not ndf_link:
        return ndfs
    if errors is None:
        errors = []
    st, coll, err = _get(bmc_ip, _p(ndf_link), username, password, timeout, verify_ssl)
    if err or st != 200:
        if st != 404:
            errors.append(_err('network_adapters',
                               f'NetworkDeviceFunctions {ndf_link} 실패: {err or st}',
                               code=_CODE_NON_BLOCKING_SUBRESOURCE))
        return ndfs
    for m in _collection_members(bmc_ip, _p(ndf_link), coll, username, password, timeout, verify_ssl,
                                 'network_adapters', errors):
        u = _safe(m, '@odata.id')
        if not u:
            continue
        s2, nd, e2 = _get(bmc_ip, _p(u), username, password, timeout, verify_ssl)
        if e2 or s2 != 200 or not isinstance(nd, dict):
            if s2 != 404:
                errors.append(_err('network_adapters',
                                   f'NetworkDeviceFunction {u} 실패: {e2 or s2}',
                                   code=_CODE_NON_BLOCKING_SUBRESOURCE))
            continue
        fc = _safe(nd, 'FibreChannel') or {}
        ib = _safe(nd, 'InfiniBand') or {}
        port_uri = (_safe(nd, 'Links', 'PhysicalPortAssignment', '@odata.id')
                    or _safe(nd, 'Links', 'PhysicalNetworkPortAssignment', '@odata.id'))
        ndfs.append({
            'id':           _safe(nd, 'Id'),
            'func_type':    _safe(nd, 'NetDevFuncType'),
            'net_dev_tech': _safe(nd, 'NetworkDeviceTechnology'),
            'wwpn':         _normalize_wwn(_safe(fc, 'WWPN') or _safe(fc, 'PermanentWWPN')),
            'wwnn':         _normalize_wwn(_safe(fc, 'WWNN') or _safe(fc, 'PermanentWWNN')),
            'fc_id':        _safe(fc, 'FibreChannelId'),
            'node_guid':    _safe(ib, 'NodeGUID') or _safe(ib, 'PermanentNodeGUID'),
            'port_guid':    _safe(ib, 'PortGUID') or _safe(ib, 'PermanentPortGUID'),
            'port_uri':     _p(port_uri) if port_uri else None,
        })
    return ndfs


def _make_fc_hba(adapter_id, adapter_info, port_id, cls, link_status, speed_gbps,
                 primary_addr, ndf):
    wwpn = ndf.get('wwpn') if isinstance(ndf, dict) else None
    wwnn = ndf.get('wwnn') if isinstance(ndf, dict) else None
    if not wwpn:
        cand = _normalize_wwn(primary_addr)
        if cand and len(cand.replace(':', '')) == 16:
            wwpn = cand
    return {
        'adapter_id':      adapter_id,
        'adapter_model':   adapter_info.get('model'),
        'port_id':         port_id,
        'wwpn':            wwpn,
        'wwnn':            wwnn,
        'model':           adapter_info.get('model'),
        'vendor':          adapter_info.get('manufacturer'),
        'driver':          None,
        'firmware':        adapter_info.get('firmware_version'),
        'link_status':     link_status,
        'link_speed_gbps': speed_gbps,
        'port_type':       cls,
        'source':          'redfish',
    }


def _make_ib_port(adapter_id, adapter_info, port_id, link_status, speed_gbps, pdata, ndf):
    node_guid = ndf.get('node_guid') if isinstance(ndf, dict) else None
    port_guid = ndf.get('port_guid') if isinstance(ndf, dict) else None
    if isinstance(pdata, dict):
        ib_raw = pdata.get('InfiniBand')
        ibobj = ib_raw if isinstance(ib_raw, dict) else {}
        if not node_guid:
            arr = _as_list(ibobj.get('AssociatedNodeGUIDs'))
            node_guid = arr[0] if arr else None
        if not port_guid:
            arr = _as_list(ibobj.get('AssociatedPortGUIDs'))
            port_guid = arr[0] if arr else None
    return {
        'adapter':       adapter_id,
        'adapter_model': adapter_info.get('model'),
        'port':          port_id,
        'node_guid':     node_guid,
        'port_guid':     port_guid,
        'link_status':   link_status,
        'rate':          None,
        'rate_gbps':     speed_gbps,
        'vendor':        adapter_info.get('manufacturer'),
        'firmware':      adapter_info.get('firmware_version'),
        'source':        'redfish',
    }


def gather_network_adapters_chassis(bmc_ip, chassis_uri, username, password, timeout,
                                    verify_ssl, system_uri=None):
    out = {'adapters': [], 'ports': [], 'fc_hbas': [], 'infiniband': []}
    errors = []
    if not chassis_uri and not system_uri:
        return out, errors

    candidates = []
    if chassis_uri:
        candidates.append(_p(chassis_uri) + '/NetworkAdapters')
    if system_uri:
        alt = _p(system_uri) + '/NetworkAdapters'
        if alt not in candidates:
            candidates.append(alt)

    coll, first_fail = None, None
    for base in candidates:
        st, data, err = _get(bmc_ip, base, username, password, timeout, verify_ssl)
        if not err and st == 200:
            coll = data
            break
        if first_fail is None:
            first_fail = (err or st, _extended_info(data))
    if coll is None:
        sig, ext = first_fail
        detail = 'tried: ' + ' / '.join(candidates)
        if ext:
            detail += ' | ' + ext
        errors.append(_err('network_adapters',
                           f'NetworkAdapters 미지원 또는 실패: {sig}', detail))
        return out, errors

    for member in _collection_members(bmc_ip, base, coll, username, password, timeout, verify_ssl,
                                      'network_adapters', errors):
        adp_uri = _safe(member, '@odata.id')
        if not adp_uri:
            continue
        st2, adata, aerr = _get(bmc_ip, _p(adp_uri), username, password, timeout, verify_ssl)
        if aerr or st2 != 200:
            errors.append(_err('network_adapters', f'NetworkAdapter {adp_uri} 실패: {aerr or st2}', code=_CODE_NON_BLOCKING_SUBRESOURCE))
            continue

        adapter_id = _safe(adata, 'Id')
        fw_ver = None
        ctrls = _safe(adata, 'Controllers', default=[]) or []
        if ctrls and isinstance(ctrls, list):
            fw_ver = _safe(ctrls[0], 'FirmwarePackageVersion')
            if not fw_ver:
                for _pd in _dicts(_safe(ctrls[0], 'Links', 'PCIeDevices')):
                    _pd_uri = _safe(_pd, '@odata.id')
                    if not _pd_uri:
                        continue
                    _ps, _pdata, _pe = _get(bmc_ip, _p(_pd_uri), username, password, timeout, verify_ssl)
                    if _ps == 200 and isinstance(_pdata, dict):
                        fw_ver = _safe(_pdata, 'FirmwareVersion')
                        if fw_ver:
                            break
        port_count = 0
        if ctrls and isinstance(ctrls, list):
            for _ctrl in ctrls:
                _caps = _safe(_ctrl, 'ControllerCapabilities') or {}
                port_count += _safe_int(_safe(_caps, 'NetworkPortCount'), default=0) or 0
        mfr = _str(_safe(adata, 'Manufacturer')).strip()
        model = _str(_safe(adata, 'Model')).strip()
        if port_count == 0 and not mfr and not model:
            continue
        adapter_info = {
            'id':               adapter_id,
            'name':             _safe(adata, 'Name'),
            'manufacturer':     mfr or None,
            'model':            model or None,
            'part_number':      _safe(adata, 'PartNumber') or None,
            'serial_number':    _safe(adata, 'SerialNumber') or None,
            'firmware_version': fw_ver or None,
            'mac':              None,
            'link_status':      'unknown',
            'speed_mbps':       None,
            'port_count':       port_count,
        }
        out['adapters'].append(adapter_info)
        adapter_idx = len(out['adapters']) - 1
        _ports_before = len(out['ports'])

        ndfs = _fetch_ndf_index(bmc_ip, adata, username, password, timeout, verify_ssl, errors)
        ndf_by_port = {n['port_uri']: i for i, n in enumerate(ndfs) if n.get('port_uri')}
        ndf_by_id = {n['id']: i for i, n in enumerate(ndfs) if n.get('id')}
        ndf_matched = set()
        port_ctx_by_id = {}

        ports_link = (_safe(adata, 'NetworkPorts', '@odata.id')
                      or _safe(adata, 'Ports', '@odata.id'))
        if ports_link:
            st3, pcoll, perr = _get(bmc_ip, _p(ports_link), username, password, timeout, verify_ssl)
            if perr or st3 != 200:
                errors.append(_err('network_adapters',
                                   f'Ports {ports_link} 실패: {perr or st3}', code=_CODE_NON_BLOCKING_SUBRESOURCE))
            else:
                for pmember in _collection_members(bmc_ip, _p(ports_link), pcoll, username, password,
                                                   timeout, verify_ssl, 'network_adapters', errors):
                    p_uri = _safe(pmember, '@odata.id')
                    if not p_uri:
                        continue
                    st4, pdata, perr2 = _get(bmc_ip, _p(p_uri), username, password, timeout, verify_ssl)
                    if perr2 or st4 != 200:
                        continue
                    speed_gbps, speed_mbps = _normalize_port_speed(pdata)
                    assoc = _safe(pdata, 'AssociatedNetworkAddresses', default=[]) or []
                    if not isinstance(assoc, list):
                        assoc = []
                    if not assoc:
                        eth_macs = _safe(pdata, 'Ethernet', 'AssociatedMACAddresses')
                        if isinstance(eth_macs, list) and eth_macs:
                            assoc = eth_macs
                        else:
                            fc_wwns = (_safe(pdata, 'FibreChannel', 'AssociatedWWNs')
                                       or _safe(pdata, 'FibreChannel', 'AssociatedWorldWideNames'))
                            if isinstance(fc_wwns, list) and fc_wwns:
                                assoc = fc_wwns
                    primary_addr = assoc[0] if assoc else None
                    if isinstance(primary_addr, str):
                        primary_addr = primary_addr.lower()
                    raw_port_type = _safe(pdata, 'PortType') or ''
                    port_protocol = _safe(pdata, 'PortProtocol')
                    link_tech = (_safe(pdata, 'LinkNetworkTechnology')
                                 or _safe(pdata, 'ActiveLinkTechnology'))
                    normalized_link = _normalize_link_status(_safe(pdata, 'LinkStatus'))
                    port_id = _safe(pdata, 'Id')
                    if port_id:
                        port_ctx_by_id[port_id] = (port_protocol, link_tech, pdata)

                    ndf_idx = ndf_by_port.get(_p(p_uri)) if p_uri else None
                    if ndf_idx is None and port_id:
                        ndf_idx = ndf_by_id.get(port_id)
                    ndf = ndfs[ndf_idx] if ndf_idx is not None else None
                    if ndf_idx is not None:
                        ndf_matched.add(ndf_idx)

                    cls = _classify_port_protocol(port_protocol, link_tech, ndf, pdata)

                    if cls in ('FibreChannel', 'FCoE') and isinstance(ndf, dict) and ndf.get('wwpn'):
                        primary_addr = ndf['wwpn']

                    port_info = {
                        'adapter_id':              adapter_id,
                        'adapter_model':           adapter_info['model'],
                        'port_id':                 port_id,
                        'name':                    _safe(pdata, 'Name'),
                        'physical_port_number':    _safe(pdata, 'PhysicalPortNumber'),
                        'link_status':             normalized_link,
                        'link_state':              _safe(pdata, 'LinkState'),
                        'current_link_speed_mbps': speed_mbps,
                        'port_type':               cls or (raw_port_type or None),
                        'health':                  _safe(pdata, 'Status', 'Health'),
                        'associated_address':      primary_addr,
                    }
                    out['ports'].append(port_info)
                    cur = out['adapters'][adapter_idx]
                    if cur.get('mac') is None and primary_addr and cls not in ('FibreChannel', 'FCoE', 'InfiniBand'):
                        cur['mac'] = primary_addr
                    if cur.get('link_status') == 'unknown' or (cur.get('link_status') != 'up' and normalized_link == 'up'):
                        cur['link_status'] = normalized_link
                    if cur.get('speed_mbps') is None and speed_mbps:
                        cur['speed_mbps'] = speed_mbps

                    if cls in ('FibreChannel', 'FCoE'):
                        out['fc_hbas'].append(_make_fc_hba(
                            adapter_id, adapter_info, port_id, cls,
                            normalized_link, speed_gbps, primary_addr, ndf))
                    elif cls == 'InfiniBand':
                        out['infiniband'].append(_make_ib_port(
                            adapter_id, adapter_info, port_id,
                            normalized_link, speed_gbps, pdata, ndf))

        for i, ndf in enumerate(ndfs):
            if i in ndf_matched:
                continue
            nid = _str(ndf.get('id'))
            parent = None
            for _pid, _ctx in port_ctx_by_id.items():
                if nid.startswith(_pid + '-'):
                    parent = _ctx
                    break
            if parent is not None:
                cls = _classify_port_protocol(parent[0], parent[1], ndf, parent[2])
            else:
                cls = _classify_port_protocol(None, None, ndf, None)
            if cls in ('FibreChannel', 'FCoE'):
                out['fc_hbas'].append(_make_fc_hba(
                    adapter_id, adapter_info, ndf.get('id'), cls,
                    'unknown', None, None, ndf))
            elif cls == 'InfiniBand':
                out['infiniband'].append(_make_ib_port(
                    adapter_id, adapter_info, ndf.get('id'),
                    'unknown', None, None, ndf))

        _ports_collected = len(out['ports']) - _ports_before
        if out['adapters'][adapter_idx].get('port_count') in (0, None) and _ports_collected > 0:
            out['adapters'][adapter_idx]['port_count'] = _ports_collected

    return out, errors


_FW_STATUS_PREFIXES = ('Installed-', 'Current-', 'Available-', 'Rollback-')


def _fw_dedup_key(fw_id):
    if not isinstance(fw_id, str):
        return fw_id
    for pref in _FW_STATUS_PREFIXES:
        if fw_id.startswith(pref):
            return fw_id[len(pref):]
    return fw_id


def _is_pending_fw_id(fw_id):
    return bool(isinstance(fw_id, str) and 'pending' in fw_id.lower())


def gather_firmware(bmc_ip, username, password, timeout, verify_ssl):
    path = 'UpdateService/FirmwareInventory'
    st, coll, err = _get(bmc_ip, path, username, password, timeout, verify_ssl)
    errors = []
    if err or st != 200:
        errors.append(_err('firmware', f'FirmwareInventory 실패: {err or st}'))
        return [], errors

    members = _collection_members(bmc_ip, path, coll, username, password, timeout, verify_ssl,
                                  'firmware', errors)

    groups, order = {}, []
    for member in members:
        member_uri = _safe(member, '@odata.id')
        tail = (member_uri.rstrip('/').split('/')[-1]
                if isinstance(member_uri, str) and member_uri else None)
        inline_id = _safe(member, 'Id')
        pre_id = inline_id if (isinstance(inline_id, str) and inline_id) else tail
        if isinstance(pre_id, str) and pre_id.startswith('Previous-'):
            continue
        key = _fw_dedup_key(pre_id) if pre_id is not None else id(member)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(member)

    fw_list = []
    seen_fw_keys = set()
    for key in order:
        chosen, last_fail = None, None
        for cand in groups[key][:2]:
            member_uri = _safe(cand, '@odata.id')
            cand_id = _safe(cand, 'Id') or member_uri
            need_detail = bool(member_uri) and (
                not _safe(cand, 'Name')
                or (_safe(cand, 'Version') is None and not _is_pending_fw_id(cand_id)))
            data = cand
            if need_detail:
                st2, fw_data, ferr = _get(bmc_ip, _p(member_uri), username, password, timeout, verify_ssl)
                if ferr or st2 != 200 or not isinstance(fw_data, dict):
                    last_fail = (member_uri, ferr or st2)
                    continue
                data = fw_data
            chosen = (data, member_uri)
            break
        if chosen is None:
            uri, why = last_fail or (None, 'unknown')
            errors.append(_err('firmware', f'FirmwareInventory 멤버 조회 실패: {uri}: {why}',
                               code=_CODE_NON_BLOCKING_SUBRESOURCE))
            continue
        member, member_uri = chosen
        fw_id = _safe(member, 'Id') or (member_uri.rstrip('/').split('/')[-1]
                                        if isinstance(member_uri, str) and member_uri else None)
        if fw_id and isinstance(fw_id, str) and fw_id.startswith('Previous-'):
            continue
        is_pending = _is_pending_fw_id(fw_id)
        ver = _safe(member, 'Version')
        if isinstance(ver, str) and ver.strip().upper() in ('N/A', 'NA', ''):
            if not is_pending:
                continue
            ver = None
        component = _safe(member, 'SoftwareId')
        if isinstance(component, str) and component.lower() == 'null':
            component = None
        post_key = _fw_dedup_key(fw_id)
        if post_key in seen_fw_keys:
            continue
        seen_fw_keys.add(post_key)
        fw_list.append({
            'id':         fw_id,
            'name':       _safe(member, 'Name'),
            'version':    ver,
            'updateable': _safe(member, 'Updateable'),
            'component':  component or fw_id,
            'pending':    is_pending,
        })
    return fw_list, errors


def _telemetry_total_power(bmc_ip, chassis_uri, username, password, timeout, verify_ssl):
    cid = _str(chassis_uri).rstrip('/').rsplit('/', 1)[-1] if chassis_uri else ''
    if not cid:
        return None
    st, coll, err = _get(bmc_ip, 'TelemetryService/MetricReports', username, password, timeout, verify_ssl)
    if err or st != 200:
        return None
    cid_l = cid.lower()
    for m in _collection_members(bmc_ip, 'TelemetryService/MetricReports', coll, username, password,
                                 timeout, verify_ssl, 'power', None):
        u = _safe(m, '@odata.id')
        if not u or not isinstance(u, str):
            continue
        ul = u.lower()
        if cid_l not in ul or 'totalpowerconsumed' not in ul:
            continue
        st2, rep, _e = _get(bmc_ip, _p(u), username, password, timeout, verify_ssl)
        if st2 != 200 or not isinstance(rep, dict):
            continue
        for mv in _dicts(_safe(rep, 'MetricValues')):
            if _str(_safe(mv, 'MetricId')).strip().lower() == 'totalpowerconsumedwatts':
                num = _safe_num(_safe(mv, 'MetricValue'))
                if num is not None:
                    return _safe_int(num)
    return None


def _gather_power_subsystem(bmc_ip, chassis_uri, username, password, timeout, verify_ssl):
    errors = []
    ps_path = _p(chassis_uri) + '/PowerSubsystem'
    st, ps_data, perr = _get(bmc_ip, ps_path, username, password, timeout, verify_ssl)
    if perr or st != 200:
        return {}, [_err('power', f'PowerSubsystem 미지원: {perr or st}')] if st != 404 else []

    psu_link = _safe(ps_data, 'PowerSupplies', '@odata.id')
    psus = []
    psu_input_total = 0
    psu_input_seen = False
    if psu_link:
        st_c, coll, _err_c = _get(bmc_ip, _p(psu_link), username, password, timeout, verify_ssl)
        if st_c == 200:
            for member in _collection_members(bmc_ip, _p(psu_link), coll, username, password, timeout,
                                              verify_ssl, 'power', errors):
                m_uri = _safe(member, '@odata.id')
                if not m_uri:
                    continue
                st_m, mdata, _err_m = _get(bmc_ip, _p(m_uri), username, password, timeout, verify_ssl)
                if st_m != 200:
                    continue
                psus.append({
                    'name':             _safe(mdata, 'Name'),
                    'model':            _safe(mdata, 'Model'),
                    'serial':           _safe(mdata, 'SerialNumber'),
                    'manufacturer':     _safe(mdata, 'Manufacturer'),
                    'part_number':      _safe(mdata, 'PartNumber'),
                    'power_capacity_w': _safe_int(_safe(mdata, 'PowerCapacityWatts')),
                    'firmware_version': _safe(mdata, 'FirmwareVersion') or _safe(mdata, 'Version'),
                    'health':           _safe(mdata, 'Status', 'Health'),
                    'state':            _safe(mdata, 'Status', 'State'),
                })
                metrics_link = _safe(mdata, 'Metrics', '@odata.id')
                if metrics_link:
                    st_mm, mm, _e_mm = _get(bmc_ip, _p(metrics_link), username, password, timeout, verify_ssl)
                    if st_mm == 200 and isinstance(mm, dict):
                        ipw = _safe_int(_safe(mm, 'InputPowerWatts', 'Reading'))
                        if ipw is not None:
                            psu_input_total += ipw
                            psu_input_seen = True

    pc_capacity = None
    psu_caps = [p['power_capacity_w'] for p in psus if p['power_capacity_w'] is not None]
    if psu_caps:
        pc_capacity = sum(psu_caps)
    power_control = {
        'power_consumed_watts':  None,
        'power_capacity_watts':  pc_capacity,
        'interval_in_min':       None,
        'min_consumed_watts':    None,
        'avg_consumed_watts':    None,
        'max_consumed_watts':    None,
    } if psus else None

    if power_control is not None:
        em_path = _p(chassis_uri) + '/EnvironmentMetrics'
        st_em, em_data, _err_em = _get(bmc_ip, em_path, username, password, timeout, verify_ssl)
        if st_em == 200 and isinstance(em_data, dict):
            pw = em_data.get('PowerWatts') if isinstance(em_data.get('PowerWatts'), dict) else None
            if pw:
                pc_consumed = _safe_int(pw.get('Reading'))
                pc_min = _safe_int(pw.get('ReadingRangeMin'))
                pc_max = _safe_int(pw.get('ReadingRangeMax'))
                if pc_consumed is not None:
                    power_control['power_consumed_watts'] = pc_consumed
                if pc_min is not None:
                    power_control['min_consumed_watts'] = pc_min
                if pc_max is not None:
                    power_control['max_consumed_watts'] = pc_max
        if power_control['power_consumed_watts'] is None:
            tpc = _telemetry_total_power(bmc_ip, chassis_uri, username, password, timeout, verify_ssl)
            if tpc is not None:
                power_control['power_consumed_watts'] = tpc
        if power_control['power_consumed_watts'] is None and psu_input_seen:
            power_control['power_consumed_watts'] = psu_input_total

    return {'power_supplies': psus, 'power_control': power_control}, errors


def _merge_power_dual(legacy_result, subsystem_result):
    legacy_psus = (legacy_result or {}).get('power_supplies') or []
    sub_psus = (subsystem_result or {}).get('power_supplies') or []

    seen = set()
    merged_psus = []
    for psu in legacy_psus + sub_psus:
        if not isinstance(psu, dict):
            continue
        _ps_serial = psu.get('serial') or ''
        if _ps_serial:
            key = ('serial', _ps_serial)
        else:
            key = ('name_model', psu.get('name') or '', psu.get('model') or '')
        if key in seen:
            continue
        seen.add(key)
        merged_psus.append(psu)

    pc = (legacy_result or {}).get('power_control') or (subsystem_result or {}).get('power_control')
    return {'power_supplies': merged_psus, 'power_control': pc}


def gather_power(bmc_ip, chassis_uri, username, password, timeout, verify_ssl):
    errors = []
    if not chassis_uri:
        errors.append(_err('power', 'chassis_uri 없음 (detect_vendor 에서 Chassis 미발견)'))
        return {}, errors

    power_path = _p(chassis_uri) + '/Power'
    st, pdata, perr = _get(bmc_ip, power_path, username, password, timeout, verify_ssl)

    if st == 404:
        return _gather_power_subsystem(bmc_ip, chassis_uri, username, password, timeout, verify_ssl)

    if perr or st != 200:
        errors.append(_err('power', f'Power 정보 실패: {perr or st}'))
        return {}, errors

    psus = []
    for psu in _dicts(_safe(pdata, 'PowerSupplies')):
        psu_capacity = _safe_int(_safe(psu, 'PowerCapacityWatts'))
        if psu_capacity is None:
            ranges = _safe(psu, 'InputRanges') or []
            if isinstance(ranges, list) and ranges and isinstance(ranges[0], dict):
                psu_capacity = _safe_int(ranges[0].get('OutputWattage'))
        psus.append({
            'name':             _safe(psu, 'Name'),
            'model':            _safe(psu, 'Model'),
            'serial':           _safe(psu, 'SerialNumber'),
            'manufacturer':     _safe(psu, 'Manufacturer'),
            'part_number':      _safe(psu, 'PartNumber'),
            'power_capacity_w': psu_capacity,
            'firmware_version': _safe(psu, 'FirmwareVersion'),
            'health':           _safe(psu, 'Status', 'Health'),
            'state':            _safe(psu, 'Status', 'State'),
        })

    pc_list = (pdata.get('PowerControl') if isinstance(pdata, dict) else None) or []
    pc0 = pc_list[0] if (isinstance(pc_list, list) and pc_list and isinstance(pc_list[0], dict)) else {}
    pm = pc0.get('PowerMetrics') or {}
    pc_capacity = _safe_int(_safe(pc0, 'PowerCapacityWatts'))
    if pc_capacity is None:
        psu_caps = [p['power_capacity_w'] for p in psus if p['power_capacity_w'] is not None]
        if psu_caps:
            pc_capacity = sum(psu_caps)
    power_control = {
        'power_consumed_watts':  _safe_int(_safe(pc0, 'PowerConsumedWatts')),
        'power_capacity_watts':  pc_capacity,
        'interval_in_min':       _safe(pm, 'IntervalInMin'),
        'min_consumed_watts':    _safe_int(_safe(pm, 'MinConsumedWatts')),
        'avg_consumed_watts':    _safe_int(_safe(pm, 'AverageConsumedWatts')),
        'max_consumed_watts':    _safe_int(_safe(pm, 'MaxConsumedWatts')),
    } if pc0 else None

    return {'power_supplies': psus, 'power_control': power_control}, errors


def gather_thermal(bmc_ip, chassis_uri, username, password, timeout, verify_ssl):
    errors = []
    if not chassis_uri:
        return {}, [_err('thermal', 'chassis_uri 없음')]

    thermal_path = _p(chassis_uri) + '/Thermal'
    st, tdata, terr = _get(bmc_ip, thermal_path, username, password, timeout, verify_ssl)

    if st == 404:
        return _gather_thermal_subsystem(bmc_ip, chassis_uri, username, password, timeout, verify_ssl)

    if terr or st != 200:
        return {}, [_err('thermal', f'Thermal 정보 실패: {terr or st}')]

    temps = []
    for t in _dicts(_safe(tdata, 'Temperatures')):
        temps.append({
            'name':             _safe(t, 'Name'),
            'reading_celsius':  _safe_round_int(_safe(t, 'ReadingCelsius')),
            'health':           _safe(t, 'Status', 'Health'),
            'state':            _safe(t, 'Status', 'State'),
            'upper_critical':   _safe_round_int(_safe(t, 'UpperThresholdCritical')),
            'physical_context': _safe(t, 'PhysicalContext'),
        })
    fans = []
    for f in _dicts(_safe(tdata, 'Fans')):
        reading = _safe(f, 'Reading')
        if reading is None:
            reading = _safe(f, 'ReadingRPM')
        fans.append({
            'name':          _safe(f, 'Name'),
            'reading':       _safe_int(reading),
            'reading_units': _safe(f, 'ReadingUnits'),
            'health':        _safe(f, 'Status', 'Health'),
            'state':         _safe(f, 'Status', 'State'),
        })
    return {'temperatures': temps, 'fans': fans}, errors


def _fan_rpm_from_sensors(bmc_ip, chassis_uri, fan_uris, username, password, timeout, verify_ssl):
    out = {}
    want = set(fan_uris or [])
    if not want:
        return out
    st, coll, err = _get(bmc_ip, _p(chassis_uri) + '/Sensors', username, password, timeout, verify_ssl)
    if err or st != 200:
        return out
    for m in _collection_members(bmc_ip, _p(chassis_uri) + '/Sensors', coll, username, password,
                                 timeout, verify_ssl, 'thermal', None):
        su = _safe(m, '@odata.id')
        if not su or not isinstance(su, str) or 'fan' not in su.lower():
            continue
        st2, sd, _e = _get(bmc_ip, _p(su), username, password, timeout, verify_ssl)
        if st2 != 200 or not isinstance(sd, dict):
            continue
        if _str(_safe(sd, 'ReadingType')).strip().lower() != 'rotational':
            continue
        reading = _safe_int(_safe(sd, 'Reading'))
        if reading is None:
            continue
        units = _safe(sd, 'ReadingUnits')
        for ri in _dicts(_safe(sd, 'RelatedItem')):
            ru = _safe(ri, '@odata.id')
            if ru and isinstance(ru, str):
                ru_p = _p(ru)
                if ru_p in want and ru_p not in out:
                    out[ru_p] = (reading, units)
    return out


def _gather_thermal_subsystem(bmc_ip, chassis_uri, username, password, timeout, verify_ssl):
    errors = []
    ts_path = _p(chassis_uri) + '/ThermalSubsystem'
    st, ts, terr = _get(bmc_ip, ts_path, username, password, timeout, verify_ssl)
    if terr or st != 200:
        return {}, ([] if st == 404 else [_err('thermal', f'ThermalSubsystem 미지원: {terr or st}')])

    temps = []
    tm_link = _safe(ts, 'ThermalMetrics', '@odata.id')
    if tm_link:
        mst, tm, _e = _get(bmc_ip, _p(tm_link), username, password, timeout, verify_ssl)
        if mst == 200:
            for tr in _dicts(_safe(tm, 'TemperatureReadingsCelsius')):
                temps.append({
                    'name':             _safe(tr, 'DeviceName') or _safe(tr, 'Name'),
                    'reading_celsius':  _safe_round_int(_safe(tr, 'Reading')),
                    'health':           _safe(tr, 'Status', 'Health'),
                    'state':            _safe(tr, 'Status', 'State'),
                    'upper_critical':   None,
                    'physical_context': _safe(tr, 'PhysicalContext'),
                })
    fans = []
    fan_uris = []
    fans_link = _safe(ts, 'Fans', '@odata.id')
    if fans_link:
        fst, fcoll, _e = _get(bmc_ip, _p(fans_link), username, password, timeout, verify_ssl)
        if fst == 200:
            for fm in _collection_members(bmc_ip, _p(fans_link), fcoll, username, password, timeout,
                                          verify_ssl, 'thermal', errors):
                furi = _safe(fm, '@odata.id')
                if not furi:
                    continue
                fst2, fdata, _e2 = _get(bmc_ip, _p(furi), username, password, timeout, verify_ssl)
                if fst2 != 200:
                    continue
                fans.append({
                    'name':          _safe(fdata, 'Name'),
                    'reading':       _safe_int(_safe(fdata, 'SpeedPercent', 'Reading')),
                    'reading_units': 'Percent' if _safe(fdata, 'SpeedPercent') else None,
                    'health':        _safe(fdata, 'Status', 'Health'),
                    'state':         _safe(fdata, 'Status', 'State'),
                })
                fan_uris.append(_p(furi))
    if fans and any(f['reading'] is None for f in fans):
        rpm_map = _fan_rpm_from_sensors(
            bmc_ip, chassis_uri, fan_uris, username, password, timeout, verify_ssl)
        if rpm_map:
            for i, f in enumerate(fans):
                if f['reading'] is None and i < len(fan_uris):
                    hit = rpm_map.get(fan_uris[i])
                    if hit:
                        f['reading'], f['reading_units'] = hit[0], hit[1]
    if not temps and not fans:
        return {}, errors
    return {'temperatures': temps, 'fans': fans}, errors


def gather_boot(bmc_ip, system_uri, username, password, timeout, verify_ssl):
    errors = []
    if not system_uri:
        return {}, [_err('boot', 'system_uri 없음')]
    st, sdata, serr = _get(bmc_ip, _p(system_uri), username, password, timeout, verify_ssl)
    if serr or st != 200:
        return {}, []
    boot = _safe(sdata, 'Boot')
    if not isinstance(boot, dict):
        return {}, errors
    boot_order = [b for b in _as_list(_safe(boot, 'BootOrder')) if isinstance(b, str)]
    return {
        'boot_order':                   boot_order,
        'boot_source_override_enabled': _safe(boot, 'BootSourceOverrideEnabled'),
        'boot_source_override_target':  _safe(boot, 'BootSourceOverrideTarget'),
        'boot_source_override_mode':    _safe(boot, 'BootSourceOverrideMode'),
        'boot_next':                    _safe(boot, 'BootNext'),
        'uefi_target':                  _safe(boot, 'UefiTargetBootSourceOverride'),
    }, errors



def _is_status_only_error(errs, codes):
    if not errs:
        return False
    for e in errs:
        if not isinstance(e, dict):
            return False
        detail = str(e.get('detail') or '')
        msg = str(e.get('message') or '')
        if any(('HTTP %s' % c) in detail or ('HTTP %s' % c) in msg for c in codes):
            continue
        if any(msg.endswith(': %s' % c) or msg.endswith(' %s' % c) for c in codes):
            continue
        return False
    return True


def _is_404_only_error(errs):
    return _is_status_only_error(errs, ('404',))





def _is_empty_result(val):
    if not val:
        return True
    if isinstance(val, dict):
        return all(not v for v in val.values())
    return False


def _make_section_runner(all_errors, collected, failed, unsupported=None):
    def _run(section, fn, *args):
        try:
            val, errs = fn(*args)
            if unsupported is not None and _is_404_only_error(errs) and _is_empty_result(val):
                unsupported.append(section)
                return val
            all_errors.extend(errs)
            collected.append(section)
            if errs:
                failed.append(section)
            return val
        except Exception as e:
            sys.stderr.write(
                "[redfish_gather] %s 예외: %s\n%s\n" %
                (section, type(e).__name__, traceback.format_exc(limit=3))
            )
            all_errors.append(_err(
                section, '예외 발생',
                "%s: %s" % (type(e).__name__, str(e)[:200])
            ))
            failed.append(section)
            return None
    return _run


def gather_manager_logs(bmc_ip, manager_uri, username, password, timeout, verify_ssl):
    errors = []
    if not manager_uri:
        return [], [_err('log_services', 'manager_uri 없음')]
    st, mdata, merr = _get(bmc_ip, _p(manager_uri), username, password, timeout, verify_ssl)
    if merr or st != 200:
        return [], []
    ls_link = _safe(mdata, 'LogServices', '@odata.id')
    if not ls_link:
        return [], errors
    cst, coll, cerr = _get(bmc_ip, _p(ls_link), username, password, timeout, verify_ssl)
    if cerr or cst != 200:
        return [], ([] if cst == 404 else [_err('log_services', f'LogServices 컬렉션 실패: {cerr or cst}')])
    out = []
    for m in _collection_members(bmc_ip, _p(ls_link), coll, username, password, timeout, verify_ssl,
                                 'log_services', errors):
        uri = _safe(m, '@odata.id')
        if not uri:
            continue
        lst, ld, _e = _get(bmc_ip, _p(uri), username, password, timeout, verify_ssl)
        if lst != 200 or not isinstance(ld, dict):
            continue
        out.append({
            'id':               _safe(ld, 'Id'),
            'name':             _safe(ld, 'Name'),
            'overwrite_policy': _safe(ld, 'OverWritePolicy'),
            'service_enabled':  _safe(ld, 'ServiceEnabled'),
            'log_entry_type':   _safe(ld, 'LogEntryType'),
            'date_time':        _safe(ld, 'DateTime'),
        })
    return out, errors


def gather_managers_multi(bmc_ip, managers_coll_uri, vendor, username, password,
                          timeout, verify_ssl, manager_layout=None):
    out = {'managers': [], 'errors': []}
    members, _st, err = _resolve_all_member_uris(
        bmc_ip, managers_coll_uri, username, password, timeout, verify_ssl
    )
    if err:
        out['errors'].append(_err('multi_node.managers',
            f'Managers 컬렉션 실패: {err}'))
        return out
    for idx, m in enumerate(_capped(members, 'multi_node.managers', out['errors'])):
        is_first = (idx == 0)
        bmc_data, bmc_errs = gather_bmc(
            bmc_ip, m['uri'], vendor,
            username, password, timeout, verify_ssl,
            manager_layout=manager_layout, is_first=is_first,
            manager_id=m['id'],
        )
        logs_data, logs_errs = gather_manager_logs(
            bmc_ip, m['uri'], username, password, timeout, verify_ssl)
        if isinstance(bmc_data, dict) and '_network_meta' in bmc_data:
            bmc_data = {k: v for k, v in bmc_data.items() if k != '_network_meta'}
        out['managers'].append({
            'id':           m['id'],
            'uri':          m['uri'],
            'role':         _classify_manager_role(m['uri'], m['id'], manager_layout, is_first),
            'bmc':          bmc_data,
            'log_services': logs_data,
        })
        out['errors'].extend(bmc_errs)
        out['errors'].extend(logs_errs)
    return out


def _summarize_partition_disks(physical_disks):
    groups, seen, total = [], {}, 0
    for d in (physical_disks or []):
        cap_mb = _safe_int(d.get('total_mb'), 0)
        cap_gb = cap_mb // MIB_PER_GIB if cap_mb else 0
        if cap_gb <= 0:
            continue
        mt, pr, md = d.get('media_type'), d.get('protocol'), d.get('model')
        key = '%s|%s|%s|%s' % (cap_gb, mt, pr, md)
        if key in seen:
            g = groups[seen[key]]
            g['quantity'] += 1
            g['group_total_gb'] = g['quantity'] * cap_gb
        else:
            seen[key] = len(groups)
            groups.append({'unit_capacity_gb': cap_gb, 'model': md, 'media_type': mt,
                           'protocol': pr, 'quantity': 1, 'group_total_gb': cap_gb})
        total += cap_gb
    return {'groups': groups, 'grand_total_gb': total}


def _normalize_storage_raw(raw):
    raw = raw if isinstance(raw, dict) else {}
    controllers_out, physical, seen = [], [], set()
    for ctrl in (raw.get('controllers') or []):
        if not isinstance(ctrl, dict):
            continue
        drives_out = []
        for drv in (ctrl.get('drives') or []):
            if not isinstance(drv, dict):
                continue
            cap = drv.get('capacity_bytes')
            tmb = int(cap // BYTES_PER_MIB) if isinstance(cap, (int, float)) else None
            drives_out.append({
                'device': drv.get('name'), 'model': drv.get('model'),
                'total_mb': tmb, 'media_type': drv.get('media_type'),
                'protocol': drv.get('protocol'), 'health': drv.get('health'),
            })
            key = '%s%s%s' % (drv.get('name') or '', drv.get('model') or '', drv.get('serial') or '')
            if key not in seen and (drv.get('name') or drv.get('model')):
                seen.add(key)
                physical.append({
                    'id': drv.get('id'), 'device': drv.get('name'), 'model': drv.get('model'),
                    'serial': drv.get('serial'), 'total_mb': tmb,
                    'media_type': drv.get('media_type'), 'protocol': drv.get('protocol'),
                    'health': drv.get('health'),
                    'failure_predicted': drv.get('failure_predicted'),
                    'predicted_life_percent': drv.get('predicted_life_percent'),
                })
        controllers_out.append({
            'id': ctrl.get('id'), 'name': ctrl.get('name'), 'health': ctrl.get('health'),
            'controller_model': ctrl.get('controller_model'),
            'controller_firmware': ctrl.get('controller_firmware'),
            'controller_manufacturer': ctrl.get('controller_manufacturer'),
            'controller_health': ctrl.get('controller_health'),
            'drives': drives_out,
        })
    logical = []
    for vol in (raw.get('volumes') or []):
        if not isinstance(vol, dict):
            continue
        logical.append({
            'id': vol.get('id'), 'name': vol.get('name'),
            'controller_id': vol.get('controller_id'),
            'member_drive_ids': vol.get('member_drive_ids') or [],
            'raid_level': vol.get('raid_level'), 'total_mb': vol.get('total_mb'),
            'health': vol.get('health'), 'state': vol.get('state'),
            'boot_volume': vol.get('boot_volume'),
        })
    return {
        'filesystems': [], 'physical_disks': physical, 'datastores': [],
        'controllers': controllers_out, 'logical_volumes': logical,
        'summary': _summarize_partition_disks(physical),
        'hbas': [], 'infiniband': [],
    }


def _normalize_network_raw(raw_nics):
    nics = raw_nics if isinstance(raw_nics, list) else []
    interfaces, gws = [], []
    for nic in nics:
        if not isinstance(nic, dict):
            continue
        addrs = []
        for a in _as_list(nic.get('ipv4')):
            addr = a.get('address') if isinstance(a, dict) else None
            if addr and addr not in ('0.0.0.0', ''):
                addrs.append({'family': 'ipv4', 'address': addr, 'prefix_length': None,
                              'subnet_mask': a.get('subnet_mask'), 'gateway': a.get('gateway'),
                              'origin': a.get('address_origin')})
        interfaces.append({
            'id': nic.get('id') or nic.get('name'), 'name': nic.get('name'),
            'kind': 'server_nic', 'mac': nic.get('mac'), 'mtu': nic.get('mtu'),
            'speed_mbps': nic.get('speed_mbps'),
            'link_status': _normalize_link_status(nic.get('link_status')),
            'is_primary': False, 'addresses': addrs,
        })
    for iface in interfaces:
        for a in iface['addresses']:
            if a.get('gateway') and a['gateway'] not in ('0.0.0.0', ''):
                e = {'family': a['family'], 'address': a['gateway']}
                if e not in gws:
                    gws.append(e)
    return {'dns_servers': [], 'default_gateways': gws, 'interfaces': interfaces,
            'adapters': [], 'ports': [], 'summary': {'groups': []}}


def _normalize_cpu_raw(procs):
    procs = procs if isinstance(procs, list) else []
    cpus = [p for p in procs if isinstance(p, dict)
            and (str(p.get('processor_type') or '').strip().upper() in ('CPU', 'CORE', ''))]
    cores = sum(_safe_int(p.get('total_cores'), 0) for p in cpus)
    threads = sum(_safe_int(p.get('total_threads'), 0) for p in cpus)
    models = [p.get('model') for p in cpus if p.get('model')]
    speeds = [p.get('speed_mhz') for p in cpus if p.get('speed_mhz')]
    archs = [p.get('architecture') for p in cpus if p.get('architecture')]
    isets = [p.get('instruction_set') for p in cpus if p.get('instruction_set')]
    groups, seen = [], {}
    for p in cpus:
        m = p.get('model') or 'unknown'
        tc = _safe_int(p.get('total_cores'), 0)
        if m in seen:
            g = groups[seen[m]]
            g['sockets'] += 1
            g['total_cores'] += tc
            g['cores_per_socket'] = g['total_cores'] // g['sockets']
        else:
            seen[m] = len(groups)
            groups.append({'model': m, 'manufacturer': p.get('manufacturer'),
                           'max_speed_mhz': p.get('speed_mhz'),
                           'architecture': p.get('architecture') or p.get('instruction_set'),
                           'sockets': 1, 'cores_per_socket': tc, 'total_cores': tc})
    return {
        'sockets': (len(cpus) or None),
        'cores_physical': (cores or None),
        'logical_threads': (threads or None),
        'model': (models[0] if models else None),
        'max_speed_mhz': (speeds[0] if speeds else None),
        'architecture': (archs[0] if archs else (isets[0] if isets else None)),
        'summary': {'groups': groups},
    }


def _normalize_memory_raw(raw_mem, raw_sys=None):
    raw_mem = raw_mem if isinstance(raw_mem, dict) else {}
    slots = raw_mem.get('slots') or []
    total_mib = raw_mem.get('total_mib')
    if not total_mib and isinstance(raw_sys, dict):
        _ms_gib = _safe_int(_safe(raw_sys, 'memory_summary', 'total_gib'))
        if _ms_gib:
            total_mib = _ms_gib * 1024
    groups, seen, total_gb = [], {}, 0
    for s in slots:
        if not isinstance(s, dict):
            continue
        cap_mb = _safe_int(s.get('capacity_mb') or s.get('capacity_mib'), 0)
        if cap_mb <= 0:
            continue
        cap_gb = cap_mb // MIB_PER_GIB
        t, sp = s.get('type'), s.get('speed_mhz')
        mfr, pn = s.get('manufacturer'), s.get('part_number')
        key = '%s|%s|%s|%s|%s' % (cap_gb, t, sp, mfr, pn)
        if key in seen:
            g = groups[seen[key]]
            g['quantity'] += 1
            g['group_total_gb'] = g['quantity'] * cap_gb
        else:
            seen[key] = len(groups)
            groups.append({'unit_capacity_gb': cap_gb, 'type': t, 'speed_mhz': sp,
                           'manufacturer': mfr, 'part_number': pn, 'quantity': 1,
                           'group_total_gb': cap_gb})
        total_gb += cap_gb
    return {
        'total_mb': total_mib, 'total_basis': 'physical_installed',
        'installed_mb': total_mib, 'visible_mb': None, 'free_mb': None,
        'slots': slots, 'summary': {'groups': groups, 'grand_total_gb': total_gb},
    }


def gather_systems_multi(bmc_ip, systems_coll_uri, vendor, username, password,
                         timeout, verify_ssl, chassis_uri=None, product_hint=None):
    out = {'partitions': [], 'errors': []}
    members, _st, err = _resolve_all_member_uris(
        bmc_ip, systems_coll_uri, username, password, timeout, verify_ssl
    )
    if err:
        out['errors'].append(_err('multi_node.partitions',
            f'Systems 컬렉션 실패: {err}'))
        return out
    creds = (username, password, timeout, verify_ssl)
    for m in _capped(members, 'multi_node.partitions', out['errors']):
        part_chassis = _resolve_system_chassis_uri(bmc_ip, m['uri'], chassis_uri, *creds)
        sys_data, sys_errs = gather_system(bmc_ip, m['uri'], vendor, *creds, part_chassis, product_hint)
        cpu_data, cpu_errs = gather_processors(bmc_ip, m['uri'], *creds)
        mem_data, mem_errs = gather_memory(bmc_ip, m['uri'], *creds)
        sto_data, sto_errs = gather_storage(bmc_ip, m['uri'], *creds)
        net_data, net_errs = gather_network(bmc_ip, m['uri'], *creds)
        boot_data, boot_errs = gather_boot(bmc_ip, m['uri'], *creds)
        out['partitions'].append({
            'id':         m['id'],
            'system_uri': m['uri'],
            'system':     sys_data,
            'cpu':        _normalize_cpu_raw(cpu_data),
            'memory':     _normalize_memory_raw(mem_data, sys_data),
            'storage':    _normalize_storage_raw(sto_data),
            'network':    _normalize_network_raw(net_data),
            'boot':       boot_data,
        })
        out['errors'].extend(sys_errs)
        out['errors'].extend(cpu_errs)
        out['errors'].extend(mem_errs)
        out['errors'].extend(sto_errs)
        out['errors'].extend(net_errs)
        out['errors'].extend(boot_errs)
    return out


def _extract_chassis_oem(cdata):
    oem = _safe(cdata, 'Oem', 'Hpe') or _safe(cdata, 'Oem', 'Hp') or {}
    oem_type = _str(_safe(oem, '@odata.type'))
    if oem_type.startswith('#HpeH3Chassis'):
        return {
            'oem_chassis_type':             _safe(oem, 'OemChassisType'),
            'physical_location':            _safe(oem, 'PhysicalLocationString'),
            'physloc':                      _safe(oem, 'Physloc'),
            'processors_compatibility_key': _safe(oem, 'ProcessorsCompatibilityKey'),
            'processors_compatible':        _safe(oem, 'ProcessorsCompatible'),
        }
    return {}


def gather_chassis_multi(bmc_ip, chassis_coll_uri, username, password,
                         timeout, verify_ssl):
    out = {'chassis': [], 'errors': []}
    members, _st, err = _resolve_all_member_uris(
        bmc_ip, chassis_coll_uri, username, password, timeout, verify_ssl
    )
    if err:
        out['errors'].append(_err('multi_node.chassis',
            f'Chassis 컬렉션 실패: {err}'))
        return out
    for m in _capped(members, 'multi_node.chassis', out['errors']):
        cst, cdata, cerr = _get(bmc_ip, _p(m['uri']),
                                username, password, timeout, verify_ssl)
        get_ok = (not cerr and cst == 200)
        if not get_ok:
            out['errors'].append(_err('multi_node.chassis',
                f"Chassis {m['id']} GET 실패: {cerr or cst}"))
        if not isinstance(cdata, dict):
            cdata = {}
        kind = _classify_chassis_kind(m['uri'], m['id'], cdata)
        if get_ok:
            pwr_data, pwr_errs = gather_power(bmc_ip, m['uri'],
                                              username, password, timeout, verify_ssl)
            thm_data, thm_errs = gather_thermal(bmc_ip, m['uri'],
                                                username, password, timeout, verify_ssl)
        else:
            pwr_data, pwr_errs, thm_data, thm_errs = {}, [], {}, []
        out['chassis'].append({
            'id':            m['id'],
            'uri':           m['uri'],
            'kind':          kind,
            'chassis_type':  _safe(cdata, 'ChassisType'),
            'manufacturer':  _safe(cdata, 'Manufacturer'),
            'model':         _safe(cdata, 'Model'),
            'serial_number': _safe(cdata, 'SerialNumber'),
            'part_number':   _safe(cdata, 'PartNumber'),
            'uuid':          _safe(cdata, 'UUID'),
            'asset_tag':     _strip_or_none(_safe(cdata, 'AssetTag')),
            'power_state':   _safe(cdata, 'PowerState'),
            'power':         pwr_data,
            'thermal':       thm_data,
            'oem':           _extract_chassis_oem(cdata),
        })
        out['errors'].extend(pwr_errs)
        out['errors'].extend(thm_errs)
    return out


def gather_composition_service(bmc_ip, service_root, username, password, timeout, verify_ssl):
    errors = []
    if not isinstance(service_root, dict):
        return None, errors
    comp_uri = _safe(service_root, 'CompositionService', '@odata.id')
    if not comp_uri:
        return None, errors
    st, comp, cerr = _get(bmc_ip, _p(comp_uri), username, password, timeout, verify_ssl)
    if cerr or st != 200:
        return None, ([] if st == 404 else
                      [_err('multi_node.composition', f'CompositionService 실패: {cerr or st}')])

    blocks = []
    rb_link = _safe(comp, 'ResourceBlocks', '@odata.id')
    if rb_link:
        rst, rcoll, rerr = _get(bmc_ip, _p(rb_link), username, password, timeout, verify_ssl)
        if rerr or rst != 200:
            if rst != 404:
                errors.append(_err('multi_node.composition',
                                   f'ResourceBlocks 컬렉션 실패: {rerr or rst}'))
        else:
            for m in _collection_members(bmc_ip, _p(rb_link), rcoll, username, password, timeout,
                                         verify_ssl, 'multi_node.composition', errors):
                uri = _safe(m, '@odata.id')
                if not uri:
                    continue
                bst, bd, _e = _get(bmc_ip, _p(uri), username, password, timeout, verify_ssl)
                if bst != 200 or not isinstance(bd, dict):
                    continue
                chassis_links = [
                    _safe(c, '@odata.id')
                    for c in _dicts(_safe(bd, 'Links', 'Chassis'))
                    if _safe(c, '@odata.id')
                ]
                systems_links = [
                    _safe(s, '@odata.id')
                    for s in _dicts(_safe(bd, 'Links', 'ComputerSystems'))
                    if _safe(s, '@odata.id')
                ]
                blocks.append({
                    'id':                   _safe(bd, 'Id'),
                    'name':                 _safe(bd, 'Name'),
                    'resource_block_types': [t for t in _as_list(_safe(bd, 'ResourceBlockType'))
                                             if isinstance(t, str)],
                    'state':                _safe(bd, 'Status', 'State'),
                    'health':               _safe(bd, 'Status', 'Health'),
                    'composition_state':    _safe(bd, 'CompositionStatus', 'CompositionState'),
                    'processor_count':      len(_dicts(_safe(bd, 'Processors'))),
                    'memory_count':         len(_dicts(_safe(bd, 'Memory'))),
                    'chassis':              chassis_links,
                    'computer_systems':     systems_links,
                })
    return {
        'enabled':              (bool(comp.get('ServiceEnabled', True)) if isinstance(comp, dict) else None),
        'state':                _safe(comp, 'Status', 'State'),
        'health':               _safe(comp, 'Status', 'Health'),
        'resource_block_count': len(blocks),
        'resource_blocks':      blocks,
    }, errors


def _gather_fabric_members(bmc_ip, coll_uri, username, password, timeout, verify_ssl, errors, kind):
    if not coll_uri:
        return []
    st, coll, cerr = _get(bmc_ip, _p(coll_uri), username, password, timeout, verify_ssl)
    if cerr or st != 200:
        return []
    out = []
    for m in _collection_members(bmc_ip, _p(coll_uri), coll, username, password, timeout, verify_ssl,
                                 f'multi_node.fabrics.{kind}', errors):
        uri = _safe(m, '@odata.id')
        if not uri:
            continue
        mst, md, _e = _get(bmc_ip, _p(uri), username, password, timeout, verify_ssl)
        if mst != 200 or not isinstance(md, dict):
            continue
        if kind == 'switch':
            out.append({
                'id':          _safe(md, 'Id'),
                'name':        _safe(md, 'Name'),
                'switch_type': _safe(md, 'SwitchType'),
                'state':       _safe(md, 'Status', 'State'),
                'health':      _safe(md, 'Status', 'Health'),
            })
        else:
            out.append({
                'id':                _safe(md, 'Id'),
                'name':              _safe(md, 'Name'),
                'endpoint_protocol': _safe(md, 'EndpointProtocol'),
                'state':             _safe(md, 'Status', 'State'),
                'health':            _safe(md, 'Status', 'Health'),
            })
    return out


def gather_fabrics(bmc_ip, service_root, username, password, timeout, verify_ssl):
    errors = []
    if not isinstance(service_root, dict):
        return None, errors
    fab_uri = _safe(service_root, 'Fabrics', '@odata.id')
    if not fab_uri:
        return None, errors
    st, fcoll, ferr = _get(bmc_ip, _p(fab_uri), username, password, timeout, verify_ssl)
    if ferr or st != 200:
        return None, ([] if st == 404 else
                      [_err('multi_node.fabrics', f'Fabrics 컬렉션 실패: {ferr or st}')])
    fabrics = []
    for m in _collection_members(bmc_ip, _p(fab_uri), fcoll, username, password, timeout, verify_ssl,
                                 'multi_node.fabrics', errors):
        furi = _safe(m, '@odata.id')
        if not furi:
            continue
        fst, fdata, _e = _get(bmc_ip, _p(furi), username, password, timeout, verify_ssl)
        if fst != 200 or not isinstance(fdata, dict):
            continue
        switches = _gather_fabric_members(
            bmc_ip, _safe(fdata, 'Switches', '@odata.id'),
            username, password, timeout, verify_ssl, errors, kind='switch')
        endpoints = _gather_fabric_members(
            bmc_ip, _safe(fdata, 'Endpoints', '@odata.id'),
            username, password, timeout, verify_ssl, errors, kind='endpoint')
        fabrics.append({
            'id':             _safe(fdata, 'Id'),
            'name':           _safe(fdata, 'Name'),
            'fabric_type':    _safe(fdata, 'FabricType'),
            'state':          _safe(fdata, 'Status', 'State'),
            'health':         _safe(fdata, 'Status', 'Health'),
            'switch_count':   len(switches),
            'endpoint_count': len(endpoints),
            'switches':       switches,
            'endpoints':      endpoints,
        })
    return fabrics, errors


def _collect_multi_node_topology(bmc_ip, vendor, service_root,
                                 username, password, timeout, verify_ssl,
                                 manager_layout=None):
    if not manager_layout:
        return None
    if not isinstance(service_root, dict):
        return None
    systems_uri  = _safe(service_root, 'Systems',  '@odata.id')
    managers_uri = _safe(service_root, 'Managers', '@odata.id')
    chassis_uri_coll = _safe(service_root, 'Chassis',  '@odata.id')

    sys_result = gather_systems_multi(
        bmc_ip, systems_uri, vendor, username, password, timeout, verify_ssl,
        product_hint=_safe(service_root, 'Product'),
    )
    mgr_result = gather_managers_multi(
        bmc_ip, managers_uri, vendor, username, password, timeout, verify_ssl,
        manager_layout=manager_layout,
    )
    chs_result = gather_chassis_multi(
        bmc_ip, chassis_uri_coll, username, password, timeout, verify_ssl,
    )
    composition, comp_errs = gather_composition_service(
        bmc_ip, service_root, username, password, timeout, verify_ssl,
    )
    fabrics, fab_errs = gather_fabrics(
        bmc_ip, service_root, username, password, timeout, verify_ssl,
    )

    partitions = sys_result.get('partitions') or []
    managers   = mgr_result.get('managers')   or []
    chassis    = chs_result.get('chassis')    or []

    representative = partitions[0].get('id') if partitions else None
    rb_count = composition.get('resource_block_count', 0) if isinstance(composition, dict) else 0
    return {
        'enabled': True,
        'layout':  manager_layout,
        'summary': {
            'partition_count':           len(partitions),
            'manager_count':             len(managers),
            'chassis_count':             len(chassis),
            'representative_partition':  representative,
            'resource_block_count':      rb_count,
            'fabric_count':              len(fabrics) if isinstance(fabrics, list) else 0,
        },
        'partitions': partitions,
        'managers':   managers,
        'chassis':    chassis,
        'composition': composition,
        'fabrics':     fabrics,
        'errors': (
            sys_result.get('errors', [])
            + mgr_result.get('errors', [])
            + chs_result.get('errors', [])
            + comp_errs
            + fab_errs
        ),
    }


def _collect_all_sections(bmc_ip, vendor, system_uri, manager_uri, chassis_uri,
                          username, password, timeout, verify_ssl,
                          all_errors, collected, failed, unsupported=None,
                          manager_layout=None, product_hint=None):
    _run = _make_section_runner(all_errors, collected, failed, unsupported)
    creds = (username, password, timeout, verify_ssl)
    eff_chassis_uri = _resolve_system_chassis_uri(
        bmc_ip, system_uri, chassis_uri, username, password, timeout, verify_ssl)
    bios_link = {}
    sections = {
        'system':            _run('system',     gather_system,     bmc_ip, system_uri, vendor, *creds, eff_chassis_uri, product_hint, bios_link),
        'bmc':               _run('bmc',        gather_bmc,        bmc_ip, manager_uri, vendor, *creds, manager_layout),
        'processors':        _run('processors', gather_processors, bmc_ip, system_uri,          *creds),
        'memory':            _run('memory',     gather_memory,     bmc_ip, system_uri,          *creds),
        'storage':           _run('storage',    gather_storage,    bmc_ip, system_uri,          *creds),
        'network':           _run('network',    gather_network,    bmc_ip, system_uri,          *creds),
        'firmware':          _run('firmware',   gather_firmware,   bmc_ip,                      *creds),
        'power':             _run('power',      gather_power,      bmc_ip, eff_chassis_uri,     *creds),
        'thermal':           _run('thermal',    gather_thermal,    bmc_ip, eff_chassis_uri,     *creds),
        'network_adapters':  _run('network_adapters',
                                   gather_network_adapters_chassis,
                                   bmc_ip, eff_chassis_uri, *creds, system_uri),
    }
    bios, bios_errors = gather_bios(bmc_ip, bios_link, *creds)
    all_errors.extend(bios_errors)
    sections['bios'] = bios
    return sections


def _compute_final_status(collected, failed, errors=None):
    clean = [s for s in collected if s not in failed]

    if errors:
        for e in errors:
            if not isinstance(e, dict):
                continue
            if e.get('code') in (_CODE_BIOS_NON_BLOCKING, _CODE_NON_BLOCKING_SUBRESOURCE):
                continue
            detail = str(e.get('detail') or '')
            msg = str(e.get('message') or '')
            if ('HTTP 401' in detail or 'HTTP 403' in detail
                    or 'HTTP 401' in msg or 'HTTP 403' in msg):
                return 'failed', clean
            if '401' in msg and 'auth' in msg.lower():
                return 'failed', clean

    if not clean:
        return 'failed', clean
    if failed:
        return 'partial', clean
    return 'success', clean





ENUM_COMPLETE = 'complete'
ENUM_INCOMPLETE = 'incomplete'
ENUM_FAILED = 'failed'

PRESENCE_PRESENT = 'present'
PRESENCE_ABSENT = 'absent'
PRESENCE_UNKNOWN = 'unknown'
PRESENCE_AMBIGUOUS = 'ambiguous'


def _get_response_etag(bmc_ip, path, username, password, timeout, verify_ssl):
    url = f'https://{bmc_ip}/redfish/v1/{path.lstrip("/")}'
    req = urlreq.Request(url, headers={
        'Authorization': _auth(username, password),
        'Accept': 'application/json',
        'OData-Version': '4.0',
    })
    try:
        with _urlopen(req, verify_ssl, timeout) as resp:
            _read_capped(resp)
            etag = resp.headers.get('ETag') if hasattr(resp, 'headers') else None
            _record_auth_status(resp.status)
            return etag or None
    except urlerr.HTTPError as e:
        _record_auth_status(e.code)
        return None
    except (urlerr.URLError, socket.timeout, OSError, ValueError):
        return None


def _patch_account(bmc_ip, path, body, username, password, timeout, verify_ssl,
                   headers=None):
    if headers:
        return _patch(bmc_ip, path, body, username, password, timeout, verify_ssl,
                      extra_headers=headers)
    return _patch(bmc_ip, path, body, username, password, timeout, verify_ssl)


def _account_policy_of(service):
    if not isinstance(service, dict):
        service = {}
    def _num(key):
        v = service.get(key)
        return v if isinstance(v, int) and not isinstance(v, bool) else None
    def _oem_num(key):
        oem = service.get('Oem')
        if not isinstance(oem, dict):
            return None
        for section in oem.values():
            if isinstance(section, dict):
                v = section.get(key)
                if isinstance(v, int) and not isinstance(v, bool):
                    return v
        return None
    supported = _safe(service, 'SupportedAccountTypes', default=None)

    def _auth_methods():
        oem = service.get('Oem')
        if not isinstance(oem, dict):
            return None
        for section in oem.values():
            if isinstance(section, dict) and isinstance(section.get('AuthMethods'), dict):
                return {k: v for k, v in section['AuthMethods'].items()
                        if isinstance(v, bool)}
        return None

    return {
        'service_enabled':        _safe(service, 'ServiceEnabled', default=None),
        'min_password_length':    _num('MinPasswordLength'),
        'max_password_length':    _num('MaxPasswordLength'),
        'lockout_threshold':      _num('AccountLockoutThreshold'),
        'lockout_duration':       _num('AccountLockoutDuration'),
        'lockout_counter_reset':  _num('AccountLockoutCounterResetAfter'),
        'auth_failure_delay_seconds': _oem_num('AuthFailureDelayTimeSeconds'),
        'auth_failures_before_delay': _oem_num('AuthFailuresBeforeDelay'),
        'supported_account_types': [s for s in _as_list(supported) if isinstance(s, str)] or None,
        'http_basic_auth': _str(_safe(service, 'HTTPBasicAuth', default='')) or None,
        'auth_methods':    _auth_methods(),
    }


def _account_login_interfaces(acc_data):
    oem = _safe(acc_data, 'Oem', default=None)
    if not isinstance(oem, dict):
        return None
    for section in oem.values():
        if not isinstance(section, dict):
            continue
        for key, value in section.items():
            if 'logininterface' not in key.replace('_', '').lower():
                continue
            items = [s for s in _as_list(value) if isinstance(s, str)]
            if items:
                return items
    return None


def _role_ids_from_collection(coll):
    ids = []
    for m in _dicts(_safe(coll, 'Members', default=[]) or []):
        uri = _safe(m, '@odata.id')
        if isinstance(uri, str) and uri:
            seg = uri.rstrip('/').rsplit('/', 1)[-1]
            if seg:
                ids.append(seg)
    return ids


def account_service_discover(bmc_ip, username, password, timeout, verify_ssl,
                             manager_uri=None, service_root=None):
    errors = []
    out = {
        'service_uri': None, 'accounts_uri': None, 'roles_uri': None,
        'service': None, 'policy': _account_policy_of(None), 'role_ids': [],
        'accounts': [], 'member_total': None, 'member_read': 0,
        'enumeration': ENUM_FAILED, 'manager': None, 'errors': errors,
        'auth_status': None,
        'service_root': None,
    }

    root = service_root if isinstance(service_root, dict) else None
    if root is None:
        code_r, root_data, _err_r = _get(bmc_ip, '', username, password, timeout, verify_ssl)
        root = root_data if code_r == 200 else None
    out['service_root'] = root
    svc_uri = _safe(root, 'AccountService', '@odata.id') if root else None
    out['service_uri'] = _p(svc_uri) if isinstance(svc_uri, str) and svc_uri else 'AccountService'

    code, service, err = _get(bmc_ip, out['service_uri'], username, password, timeout, verify_ssl)
    out['auth_status'] = code
    if code != 200 or err:
        errors.append(_err('account_service', 'GET AccountService 실패',
                           detail=err or f'HTTP {code}'))
        return out
    out['service'] = service
    out['policy'] = _account_policy_of(service)
    out['enumeration'] = ENUM_INCOMPLETE

    roles_link = _safe(service, 'Roles', '@odata.id')
    if isinstance(roles_link, str) and roles_link:
        out['roles_uri'] = _p(roles_link)
        code_ro, roles_coll, err_ro = _get(
            bmc_ip, out['roles_uri'], username, password, timeout, verify_ssl)
        if code_ro == 200 and not err_ro:
            out['role_ids'] = _role_ids_from_collection(roles_coll)

    accounts_link = _safe(service, 'Accounts', '@odata.id')
    if not accounts_link:
        errors.append(_err('account_service', 'AccountService.Accounts 링크 없음',
                           detail=str(service)[:200]))
        return out
    out['accounts_uri'] = _p(accounts_link)

    code, acc_coll, err = _get(bmc_ip, out['accounts_uri'], username, password, timeout, verify_ssl)
    if code != 200 or err:
        errors.append(_err('account_service', 'GET Accounts 컬렉션 실패',
                           detail=err or f'HTTP {code}'))
        return out

    members = _safe(acc_coll, 'Members', default=[]) or []
    if not isinstance(members, list):
        members = []
    declared = _safe(acc_coll, 'Members@odata.count', default=None)
    out['member_total'] = declared if isinstance(declared, int) and not isinstance(declared, bool) \
        else len(members)

    member_failures = 0
    capped = _capped(members, 'account_service', errors)
    truncated = len(capped) < len(members)
    for m in capped:
        slot_uri = _safe(m, '@odata.id')
        if not slot_uri:
            member_failures += 1
            continue
        code_a, acc_data, err_a = _get(bmc_ip, _p(slot_uri), username, password,
                                       timeout, verify_ssl)
        if code_a != 200 or err_a:
            errors.append(_err('account_service', f'GET {slot_uri} 실패',
                               detail=err_a or f'HTTP {code_a}'))
            member_failures += 1
            continue
        acct_types = _safe(acc_data, 'AccountTypes', default=None)
        out['accounts'].append({
            'slot_uri': slot_uri,
            'id':       _safe(acc_data, 'Id'),
            'username': _safe(acc_data, 'UserName', default=''),
            'role_id':  _safe(acc_data, 'RoleId',   default=''),
            'enabled':  bool(_safe(acc_data, 'Enabled', default=False)),
            'locked':   _safe(acc_data, 'Locked', default=None),
            'account_types': [s for s in _as_list(acct_types) if isinstance(s, str)]
                             if acct_types is not None else None,
            'password_change_required': _safe(acc_data, 'PasswordChangeRequired', default=None),
            'odata_type': _safe(acc_data, '@odata.type', default=''),
            'has_username_key': isinstance(acc_data, dict) and 'UserName' in acc_data,
            'host_bootstrap': _safe(acc_data, 'HostBootstrapAccount', default=None),
            'login_interfaces': _account_login_interfaces(acc_data),
        })
    out['member_read'] = len(out['accounts'])

    if member_failures == 0 and not truncated and out['member_read'] == out['member_total']:
        out['enumeration'] = ENUM_COMPLETE
    else:
        errors.append(_err(
            'account_service',
            '계정 목록을 완전히 읽지 못했습니다. 계정 부재를 확정할 수 없습니다.',
            detail=(f'members declared={out["member_total"]} read={out["member_read"]} '
                    f'failures={member_failures} truncated={truncated}'),
        ))

    if manager_uri:
        code_m, mgr, err_m = _get(bmc_ip, _p(manager_uri), username, password,
                                  timeout, verify_ssl)
        if code_m == 200 and not err_m:
            out['manager'] = {
                'firmware_version': _str(_safe(mgr, 'FirmwareVersion', default='')) or None,
                'model':            _str(_safe(mgr, 'Model', default='')) or None,
                'manager_type':     _str(_safe(mgr, 'ManagerType', default='')) or None,
            }
    return out


PRESENCE_PROTECTED_CONFLICT = 'protected_conflict'


def account_is_protected(account, family=None):
    if not isinstance(account, dict):
        return False
    return account.get('host_bootstrap') is True


def account_presence(discovery, target_username, family=None):
    accounts = (discovery or {}).get('accounts') or []
    matches = [a for a in accounts if (a.get('username') or '') == target_username]
    protected = [a for a in matches if account_is_protected(a, family)]
    if protected:
        return PRESENCE_PROTECTED_CONFLICT, protected
    if len(matches) > 1:
        return PRESENCE_AMBIGUOUS, matches
    if matches:
        return PRESENCE_PRESENT, matches
    if (discovery or {}).get('enumeration') != ENUM_COMPLETE:
        return PRESENCE_UNKNOWN, []
    return PRESENCE_ABSENT, []



_ACCOUNT_PROP_DEFAULTS = {
    'Password':               {'create': 'writable',    'repair': 'writable'},
    'RoleId':                 {'create': 'writable',    'repair': 'writable'},
    'Enabled':                {'create': 'writable',    'repair': 'writable'},
    'Locked':                 {'create': 'unsupported', 'repair': 'unverified'},
    'PasswordChangeRequired': {'create': 'unsupported', 'repair': 'unverified'},
    'AccountTypes':           {'create': 'unsupported', 'repair': 'unverified'},
}

PROP_UNVERIFIED = 'unverified'

_ACCOUNT_FAMILY_DEFAULTS = {
    'create_method':            'collection_post',
    'create_uri':               'accounts_collection',
    'needs_explicit_id':        False,
    'id_range':                 None,
    'role_map':                 {},
    'account_types':            None,
    'account_types_required':   None,
    'password_change_required': None,
    'oem_privileges_namespace': None,
    'reserved_slot_ids':        (),
    'if_match':                 {'create': False, 'repair': False},
    'write_success':            'generic',
    'evidence':                 'unverified',
    'isolated_write_patch':     False,
    'full_body_patch':          False,
    'props':                    {},
}

_ACCOUNT_FAMILIES = {
    'dell_slot_patch':          {'create_method': 'slot_patch',
                                 'reserved_slot_ids': ('1',), 'evidence': 'proven',
                                 'props': {
                                     'Locked': {'create': 'unsupported', 'repair': 'read_only'},
                                     'AccountTypes': {'create': 'unsupported',
                                                      'repair': 'verify_only'},
                                 }},
    'dell_idrac10_slot_patch':  {'create_method': 'slot_patch',
                                 'reserved_slot_ids': ('1', '2'), 'evidence': 'documented',
                                 'props': {
                                     'Locked': {'create': 'unsupported', 'repair': 'read_only'},
                                     'AccountTypes': {'create': 'unsupported',
                                                      'repair': 'verify_only'},
                                 }},
    'cisco_cimc_collection_post_id': {'needs_explicit_id': True,
                                      'id_range': (2, 16),
                                      'role_map': {'Administrator': 'admin',
                                                   'Operator': 'user',
                                                   'ReadOnly': 'readonly'},
                                      'evidence': 'proven'},
    'cisco_cimc3_instance_post': {'create_uri': 'account_instance',
                                  'needs_explicit_id': True,
                                  'id_range': (2, 16),
                                  'role_map': {'Administrator': 'admin',
                                               'Operator': 'user',
                                               'ReadOnly': 'readonly'},
                                  'evidence': 'documented'},
    'cisco_bmc_dynamic':        {'evidence': 'documented',
                                 'props': {
                                     'Locked': {'create': 'unsupported', 'repair': 'writable'},
                                     'PasswordChangeRequired': {'create': 'writable',
                                                                'repair': 'read_only'},
                                     'AccountTypes': {'create': 'unsupported',
                                                      'repair': 'verify_only'},
                                 }},
    'lenovo_purley_slot_patch': {'create_method': 'slot_patch',
                                 'evidence': 'documented',
                                 'props': {
                                     'Locked': {'create': 'unsupported', 'repair': 'read_only'},
                                     'PasswordChangeRequired': {'create': 'unsupported',
                                                                'repair': 'unsupported'},
                                 }},
    'lenovo_collection_post':   {'password_change_required': False,
                                 'evidence': 'documented',
                                 'props': {
                                     'PasswordChangeRequired': {'create': 'writable',
                                                                'repair': 'writable'},
                                 }},
    'lenovo_xcc2_accounttypes': {'password_change_required': False,
                                 'account_types': ('Redfish',),
                                 'account_types_required': ('Redfish',),
                                 'reserved_slot_ids': ('HostBootStrap',),
                                 'full_body_patch': True,
                                 'evidence': 'documented',
                                 'props': {
                                     'Locked': {'create': 'unsupported', 'repair': 'read_only'},
                                     'PasswordChangeRequired': {'create': 'writable',
                                                                'repair': 'writable'},
                                     'AccountTypes': {'create': 'writable', 'repair': 'writable'},
                                 }},
    'lenovo_xcc3_accounttypes': {'account_types': ('Redfish',),
                                 'account_types_required': ('Redfish',),
                                 'full_body_patch': True,
                                 'evidence': 'documented',
                                 'props': {
                                     'Locked': {'create': 'unsupported', 'repair': 'read_only'},
                                     'PasswordChangeRequired': {'create': 'unsupported',
                                                                'repair': 'unsupported'},
                                     'AccountTypes': {'create': 'writable', 'repair': 'writable'},
                                 }},
    'hpe_ilo4':                 {'oem_privileges_namespace': 'Hp',
                                 'evidence': 'documented',
                                 'props': {
                                     'Locked': {'create': 'unsupported', 'repair': 'unsupported'},
                                     'AccountTypes': {'create': 'unsupported',
                                                      'repair': 'unsupported'},
                                 }},
    'hpe_ilo5plus':             {'isolated_write_patch': True,
                                 'evidence': 'proven',
                                 'account_types_required': ('Redfish',),
                                 'props': {
                                     'Locked': {'create': 'unsupported', 'repair': 'unsupported'},
                                     'PasswordChangeRequired': {'create': 'unsupported',
                                                                'repair': 'read_only'},
                                     'AccountTypes': {'create': 'unsupported',
                                                      'repair': 'verify_only'},
                                 }},
    'supermicro_legacy':        {'evidence': 'documented'},
    'supermicro_split_account': {'account_types': ('Redfish',),
                                 'account_types_required': ('Redfish',),
                                 'evidence': 'documented',
                                 'props': {
                                     'AccountTypes': {'create': 'writable',
                                                      'repair': 'verify_only'},
                                 }},
    'inspur_m6':                {'if_match': {'create': False,
                                              'repair': True},
                                 'write_success': 'inspur_oem_status',
                                 'evidence': 'documented'},
    'huawei_ibmc':              {'evidence': 'documented',
                                 'props': {
                                     'Locked': {'create': 'unsupported', 'repair': 'writable'},
                                     'PasswordChangeRequired': {'create': 'unsupported',
                                                                'repair': 'unsupported'},
                                     'AccountTypes': {'create': 'unsupported',
                                                      'repair': 'unsupported'},
                                 }},
    'generic_collection_post':  {'evidence': 'unverified'},
    'qct_legacy_redfish':       {'evidence': 'unverified'},
    'qct_modern_redfish':       {'evidence': 'unverified'},
    'qct_inhouse_openbmc':      {'evidence': 'unverified'},
}


def account_family(family_id):
    rec = dict(_ACCOUNT_FAMILY_DEFAULTS)
    rec.update(_ACCOUNT_FAMILIES.get(family_id) or _ACCOUNT_FAMILIES['generic_collection_post'])
    rec['id'] = family_id if family_id in _ACCOUNT_FAMILIES else 'generic_collection_post'
    return rec


def account_prop_contract(family, prop, operation):
    declared = (family or {}).get('props') or {}
    entry = declared.get(prop)
    if isinstance(entry, dict) and operation in entry:
        return entry[operation]
    fallback = _ACCOUNT_PROP_DEFAULTS.get(prop) or {}
    return fallback.get(operation, PROP_UNVERIFIED)


def account_prop_writable(family, prop, operation):
    return account_prop_contract(family, prop, operation) == 'writable'


def account_if_match(family, operation):
    spec = (family or {}).get('if_match')
    if isinstance(spec, dict):
        return bool(spec.get(operation, False))
    return False


def _has_prepopulated_slots(accounts):
    empties = [a for a in accounts
               if a.get('has_username_key') and (a.get('username') or '') == '']
    return len(accounts) >= 8 and len(empties) >= 2


def _fw_at_least(firmware, major, minor):
    if not isinstance(firmware, str):
        return None
    nums = re.findall(r'\d+', firmware)
    if len(nums) < 2:
        return None
    try:
        return (int(nums[0]), int(nums[1])) >= (major, minor)
    except (TypeError, ValueError):
        return None


HPE_PATCH_ADVISORY = 'a00159600en_us'

ISOLATION_LIVE_PROVEN = 'live_proven'
ISOLATION_ADVISORY = 'advisory_derived'
ISOLATION_SAFETY = 'safety_strategy'

_ILO_FW_RE = re.compile(r'iLO\s*(\d+)', re.IGNORECASE)
_ILO_VER_RE = re.compile(r'v?(\d+)\.(\d+)')


def hpe_isolation_evidence(firmware, model=None):
    text = ' '.join(x for x in (firmware, model) if isinstance(x, str))
    gen_m = _ILO_FW_RE.search(text)
    gen = int(gen_m.group(1)) if gen_m else None
    ver_m = _ILO_VER_RE.search(firmware if isinstance(firmware, str) else '')
    ver = (int(ver_m.group(1)), int(ver_m.group(2))) if ver_m else None

    if gen == 6 and ver:
        if ver == (1, 73):
            return ISOLATION_LIVE_PROVEN, 'proven', HPE_PATCH_ADVISORY
        if ver == (1, 74):
            return ISOLATION_ADVISORY, 'documented', HPE_PATCH_ADVISORY
        return ISOLATION_SAFETY, 'documented', None
    if gen == 7 and ver:
        if ver in ((1, 19), (1, 20)):
            return ISOLATION_ADVISORY, 'documented', HPE_PATCH_ADVISORY
        return ISOLATION_SAFETY, 'documented', None
    return ISOLATION_SAFETY, 'documented', None


def resolve_account_family(vendor, discovery, adapter_id=None):
    d = discovery or {}
    accounts = d.get('accounts') or []
    roles = [r.lower() for r in (d.get('role_ids') or [])]
    mgr = d.get('manager') or {}
    firmware = mgr.get('firmware_version')
    hint = (adapter_id or '').lower()
    reasons = []
    v = (vendor or '').lower()

    if v == 'dell':
        mdl = (mgr.get('model') or '').lower()
        fw_match = re.match(r'\s*(\d+)\.', str(firmware or ''))
        fw_major = int(fw_match.group(1)) if fw_match else None
        if fw_major in (4, 5, 6, 7):
            gen10 = False
        elif fw_major == 1 or 'idrac10' in mdl:
            gen10 = True
        else:
            gen10 = 'idrac10' in hint
        reasons.append(
            f'vendor=dell fw_major={fw_major} model={mdl!r} '
            f'hint_idrac10={"idrac10" in hint} '
            f'prepopulated={_has_prepopulated_slots(accounts)} → idrac10={gen10}')
        return account_family('dell_idrac10_slot_patch' if gen10 else 'dell_slot_patch'), reasons

    if v == 'cisco':
        if 'admin' in roles and 'administrator' not in roles:
            reasons.append('roles={admin,...} → CIMC enum family')
            return account_family('cisco_cimc_collection_post_id'), reasons
        if 'administrator' in roles:
            reasons.append('roles contains Administrator → modern Cisco BMC family')
            return account_family('cisco_bmc_dynamic'), reasons
        observed = {(a.get('role_id') or '').lower() for a in accounts}
        if 'admin' in observed and 'administrator' not in observed:
            reasons.append('existing account RoleId=admin → CIMC enum family')
            return account_family('cisco_cimc_collection_post_id'), reasons
        if 'administrator' in observed:
            reasons.append('existing account RoleId=Administrator → modern Cisco BMC family')
            return account_family('cisco_bmc_dynamic'), reasons
        if 'cisco_bmc' in hint:
            reasons.append('adapter hint cisco_bmc')
            return account_family('cisco_bmc_dynamic'), reasons
        if 'cimc' in hint:
            fw_major = None
            m3 = re.match(r'\s*(\d+)\.', str(firmware or ''))
            if m3:
                fw_major = int(m3.group(1))
            if fw_major == 3:
                reasons.append('adapter hint cisco_cimc + firmware 3.x → Instance POST')
                return account_family('cisco_cimc3_instance_post'), reasons
            reasons.append('adapter hint cisco_cimc')
            return account_family('cisco_cimc_collection_post_id'), reasons
        reasons.append('cisco family evidence 부족 → generic 유지')
        return account_family('generic_collection_post'), reasons

    if v == 'lenovo':
        if 'imm2' in hint:
            reasons.append('IMM2 는 Redfish AccountService 근거 미확보 → generic 유지')
            return account_family('generic_collection_post'), reasons
        exposes_account_types = any(a.get('account_types') for a in accounts)
        has_bootstrap = any(a.get('host_bootstrap') is not None for a in accounts)
        if exposes_account_types or has_bootstrap or 'xcc3' in hint or 'xcc2' in hint:
            if 'xcc3' in hint:
                reasons.append('adapter hint xcc3 → PasswordChangeRequired 미지원 Family')
                return account_family('lenovo_xcc3_accounttypes'), reasons
            reasons.append(
                f'AccountTypes 관측={exposes_account_types} HostBootstrap 관측={has_bootstrap} '
                f'hint={hint!r} → AccountTypes 지원 XCC family')
            return account_family('lenovo_xcc2_accounttypes'), reasons
        not_purley_hint = any(k in hint for k in ('whitley', 'amd', 'xcc2', 'xcc3'))
        if _has_prepopulated_slots(accounts) and not not_purley_hint:
            reasons.append('pre-populated empty slots 관측 → XCC Purley slot PATCH')
            return account_family('lenovo_purley_slot_patch'), reasons
        reasons.append('dynamic members → Lenovo Collection POST')
        return account_family('lenovo_collection_post'), reasons

    if v == 'hpe':
        if 'csus' in hint or 'superdome' in hint:
            reasons.append('HPE RMC(CSUS/Superdome) — create payload 공식 근거 미확보 → generic 유지')
            return account_family('generic_collection_post'), reasons
        if 'ilo4' in hint:
            reasons.append('adapter hint ilo4 → Oem/Hp namespace')
            return account_family('hpe_ilo4'), reasons
        oem_keys = {k.lower() for k in (_safe(d.get('service'), 'Oem', default={}) or {}).keys()} \
            if isinstance(_safe(d.get('service'), 'Oem', default={}), dict) else set()
        if 'hp' in oem_keys and 'hpe' not in oem_keys:
            reasons.append('AccountService.Oem 에 Hp 만 존재 → iLO4 계열')
            return account_family('hpe_ilo4'), reasons
        fam = account_family('hpe_ilo5plus')
        basis, evidence, advisory = hpe_isolation_evidence(firmware, mgr.get('model'))
        fam['isolation_basis'] = basis
        fam['evidence'] = evidence
        fam['firmware_advisory'] = advisory
        reasons.append(
            f'iLO5+ (RoleId 기반) firmware={firmware!r} '
            f'isolation_basis={basis} evidence={evidence}'
            + (f' advisory={advisory}' if advisory else ''))
        return fam, reasons

    if v == 'supermicro':
        split = None
        gen_anchor = False
        if any(a.get('account_types') for a in accounts):
            split = True
            reasons.append('기존 계정이 AccountTypes 를 노출 → 계정 분리 세대')
        elif d.get('policy', {}).get('supported_account_types'):
            split = True
            reasons.append('AccountService.SupportedAccountTypes 존재 → 계정 분리 세대')
        elif 'x13' in hint or 'x14' in hint or 'ars' in hint:
            if 'x13' in hint:
                bound = (1, 5)
            elif 'x14' in hint:
                bound = (1, 2)
            else:
                bound = (1, 4)
            newer = _fw_at_least(firmware, *bound)
            split = bool(newer)
            gen_anchor = bool(newer is not None)
            reasons.append(
                f'adapter hint {hint} firmware={firmware} boundary={bound} split={split}')
        if split:
            fam = account_family('supermicro_split_account')
            if gen_anchor:
                fam['create_uri'] = 'account_service_root'
                fam['create_uri_basis'] = 'generation+firmware'
            else:
                fam['create_uri'] = 'accounts_collection'
                fam['create_uri_basis'] = 'unverified_single_strategy'
                fam['evidence'] = 'unverified'
            reasons.append(f'create_uri={fam["create_uri"]} basis={fam["create_uri_basis"]}')
            return fam, reasons
        if 'x9' in hint:
            reasons.append('X9 는 공식 Redfish AccountService 근거 미확보 → generic 유지')
            return account_family('generic_collection_post'), reasons
        reasons.append('Supermicro legacy/Reference Guide family')
        return account_family('supermicro_legacy'), reasons

    if v == 'inspur':
        oem = _safe(d.get('service'), 'Oem', 'Public', default=None)
        if isinstance(oem, dict) or 'm6' in hint or 'isbmc' in hint:
            reasons.append('Oem.Public 관측 또는 M6/ISBMC hint → Inspur M6 family')
            return account_family('inspur_m6'), reasons
        reasons.append('Inspur M5/M7 은 공식 계약 미확보 → generic 유지')
        return account_family('generic_collection_post'), reasons

    if v == 'quanta':
        if 'openbmc' in hint or 'xeon6' in hint or 's45z' in hint or 's25z' in hint:
            reasons.append('QCT Inhouse OpenBMC 계열 — upstream bmcweb 과 동일시하지 않는다')
            return account_family('qct_inhouse_openbmc'), reasons
        redfish_ver = _str(_safe(d.get('service_root'), 'RedfishVersion', default='')) \
            if isinstance(d.get('service_root'), dict) else ''
        if redfish_ver.startswith('1.1.'):
            reasons.append(f'QCT Legacy Redfish {redfish_ver}')
            return account_family('qct_legacy_redfish'), reasons
        if redfish_ver.startswith('1.11'):
            reasons.append(f'QCT Modern Redfish {redfish_ver}')
            return account_family('qct_modern_redfish'), reasons
        reasons.append('QCT Family 근거 부족 → generic 유지 (Account Write 계약 미확보)')
        return account_family('generic_collection_post'), reasons

    if v == 'huawei':
        reasons.append('Huawei iBMC Collection POST (공식 문서 근거)')
        return account_family('huawei_ibmc'), reasons

    reasons.append(f'vendor={vendor or "unknown"} — Family 근거 없음 → generic 유지')
    return account_family('generic_collection_post'), reasons


def choose_role_id(family, target_role, discovery):
    supported = [r for r in ((discovery or {}).get('role_ids') or []) if isinstance(r, str)]
    lower = {r.lower(): r for r in supported}
    if target_role in supported:
        return target_role
    mapped = (family.get('role_map') or {}).get(target_role)
    if mapped and mapped in supported:
        return mapped
    if target_role and target_role.lower() in lower:
        return lower[target_role.lower()]
    if mapped and mapped.lower() in lower:
        return lower[mapped.lower()]
    return mapped or target_role


def interpret_write_response(family, code, body, err, requested=None):
    if err or code not in (200, 201, 204):
        return False, (err or f'HTTP {code}')
    rejected = write_rejections(body, requested)
    if rejected:
        detail = ', '.join(
            '{0}={1}{2}'.format(r['property'] or '?', r['kind'],
                                f"({r['message_id']})" if r['message_id'] else '')
            for r in rejected)
        return False, f'rejected: {detail}'
    if family.get('write_success') == 'inspur_oem_status':
        status = _safe(body, 'Oem', 'Public', 'Status', default=None)
        if status is None:
            return True, 'vendor status absent'
        if status != 0:
            return False, f'Oem.Public.Status={status}'
    return True, None


def _create_target_uri(family, discovery, explicit_id=None):
    d = discovery or {}
    accounts_uri = d.get('accounts_uri') or 'AccountService/Accounts'
    kind = (family or {}).get('create_uri') or 'accounts_collection'
    if kind == 'account_service_root':
        return d.get('service_uri') or 'AccountService'
    if kind == 'account_instance':
        if explicit_id is None:
            return accounts_uri
        return f'{accounts_uri.rstrip("/")}/{explicit_id}'
    return accounts_uri


def _confirm_account_state(bmc_ip, slot_uri, target_username, family,
                           username, password, timeout, verify_ssl, out):
    if not slot_uri:
        return None, []
    code, data, err = _get(bmc_ip, _p(slot_uri), username, password, timeout, verify_ssl)
    if code != 200 or err:
        out['errors'].append(_err(
            'account_service', '쓰기 후 계정 상태를 다시 읽지 못했습니다.',
            detail=err or f'HTTP {code}',
        ))
        return None, []
    acct_types = _safe(data, 'AccountTypes', default=None)
    state = {
        'username':     _safe(data, 'UserName', default=''),
        'enabled':      _safe(data, 'Enabled', default=None),
        'role_id':      _safe(data, 'RoleId', default=''),
        'account_types': [s for s in _as_list(acct_types) if isinstance(s, str)]
                        if acct_types is not None else None,
        'password_change_required': _safe(data, 'PasswordChangeRequired', default=None),
    }
    out['post_write_state'] = state

    mismatches = []
    if isinstance(data, dict) and 'UserName' in data and state['username'] != target_username:
        mismatches.append(f'UserName={state["username"]!r}')
    if state['enabled'] is False:
        mismatches.append('Enabled=false')
    if state['password_change_required'] is True:
        mismatches.append('PasswordChangeRequired=true')
    want_types = set(family.get('account_types_required')
                     or family.get('account_types') or ())
    if want_types and state['account_types'] is not None \
            and not want_types.issubset(set(state['account_types'])):
        mismatches.append(f'AccountTypes={state["account_types"]}')
    if mismatches:
        out['errors'].append(_err(
            'account_service',
            '표준 계정을 만들었지만 상태가 기대와 다릅니다. 계정 설정을 확인하세요.',
            detail='post-write state mismatch: ' + ', '.join(mismatches),
        ))
    return (not mismatches), mismatches


def build_create_payload(family, target_username, target_password, role_id,
                         explicit_id=None):
    body = {'UserName': target_username}
    if account_prop_writable(family, 'Password', 'create'):
        body['Password'] = target_password
    if account_prop_writable(family, 'Enabled', 'create'):
        body['Enabled'] = True
    if account_prop_writable(family, 'RoleId', 'create'):
        body['RoleId'] = role_id
    if family.get('needs_explicit_id') and explicit_id is not None:
        body['Id'] = explicit_id
    if family.get('password_change_required') is False \
            and account_prop_writable(family, 'PasswordChangeRequired', 'create'):
        body['PasswordChangeRequired'] = False
    if family.get('account_types') and account_prop_writable(family, 'AccountTypes', 'create'):
        body['AccountTypes'] = list(family['account_types'])
    ns = family.get('oem_privileges_namespace')
    if ns:
        body['Oem'] = {ns: {'Privileges': {
            'LoginPriv': True, 'RemoteConsolePriv': True, 'UserConfigPriv': True,
            'VirtualMediaPriv': True, 'VirtualPowerAndResetPriv': True,
            'iLOConfigPriv': True}}}
    return body


def account_service_get(bmc_ip, username, password, timeout, verify_ssl):
    d = account_service_discover(bmc_ip, username, password, timeout, verify_ssl)
    return d['service'], d['accounts'], d['errors']


def account_service_find_user(accounts, target_username):
    for acc in accounts:
        if (acc.get('username') or '') == target_username:
            return acc
    return None


def account_service_find_all_users(accounts, target_username):
    return [acc for acc in accounts if (acc.get('username') or '') == target_username]


def account_service_find_empty_slot(accounts, skip_slot_ids=None):
    skip = set(skip_slot_ids or [])
    for acc in accounts:
        if ('' if acc.get('id') is None else str(acc.get('id'))) in skip:
            continue
        if not (acc.get('username') or ''):
            return acc
    return None


def account_service_find_all_empty_slots(accounts, skip_slot_ids=None):
    skip = set(skip_slot_ids or [])

    def _is_empty(a):
        if (a.get('username') or '') != '':
            return False
        if 'has_username_key' not in a:
            return True
        return bool(a.get('has_username_key')) and not a.get('enabled')

    empties = [
        a for a in accounts
        if ('' if a.get('id') is None else str(a.get('id'))) not in skip and _is_empty(a)
    ]
    def _key(a):
        try:
            return (0, int(a.get('id') or '0'))
        except (ValueError, TypeError):
            return (1, ('' if a.get('id') is None else str(a.get('id'))))
    empties.sort(key=_key)
    return empties


def account_service_provision(
    bmc_ip, vendor, current_username, current_password,
    target_username, target_password, target_role,
    timeout, verify_ssl, dryrun=True, allow_delete_recreate=False,
    adapter_id=None, manager_uri=None, service_root=None,
):
    out = {
        'recovered':       False,
        'method':          'noop',
        'slot_uri':        None,
        'dryrun':          bool(dryrun),
        'account_existed': False,
        'action':          'none',
        'verification':    'none',
        'presence':        PRESENCE_UNKNOWN,
        'family':          None,
        'create_method':   None,
        'evidence':        None,
        'family_reasons':  [],
        'policy':          None,
        'auth_budget':     {},
        'write_accepted':  None,
        'vendor_status':   None,
        'dryrun_reason':   None,
        'post_write_state': None,
        'auth_ok':         False,
        'auth_rejected':   False,
        'write_response_info': None,
        'write_http_status': None,
        'verify_resource':   None,
        'create_uri':        None,
        'create_uri_kind':   None,
        'create_uri_basis':  None,
        'policy_conflict':      None,
        'auth_budget_limit':    None,
        'auth_budget_exhausted': False,
        'role_id_unsupported':  False,
        'login_interfaces':     None,
        'write_rejections':     None,
        'errors':          [],
    }

    def _spend_auth(username):
        out['auth_budget'][username] = out['auth_budget'].get(username, 0) + 1

    verify_schedule = ACCOUNT_VERIFY_DELAYS
    auth_budget_limit = ACCOUNT_DEFAULT_AUTH_BUDGET

    def _verify_standard_credential():
        out['verify_resource'] = 'Systems'
        code_v, err_v = None, None
        for attempt, delay in enumerate(verify_schedule):
            if out['auth_budget'].get(target_username, 0) >= auth_budget_limit:
                out['auth_budget_exhausted'] = True
                out['errors'].append(_err(
                    'account_service',
                    '재인증 확인을 계정 잠금 한도 전에 중단했습니다. '
                    '장비의 계정 잠금 정책과 표준 계정 상태를 확인하세요.',
                    detail=(f'auth budget {auth_budget_limit} reached for standard account; '
                            f'verified attempts={attempt}'),
                ))
                return False, code_v, err_v, attempt
            if delay:
                time.sleep(delay)
            code_v, _, err_v = _get(bmc_ip, 'Systems', target_username, target_password,
                                    timeout, verify_ssl)
            if code_v == 200 and not err_v:
                return True, code_v, None, attempt + 1
            _spend_auth(target_username)
        return False, code_v, err_v, len(verify_schedule)

    discovery = account_service_discover(
        bmc_ip, current_username, current_password, timeout, verify_ssl,
        manager_uri=manager_uri, service_root=service_root,
    )
    acct_service = discovery['service']
    accounts = discovery['accounts']
    errs = discovery['errors']


    if _is_404_only_error(errs):
        out['method'] = 'not_supported'
        out['action'] = 'none'
        out['errors'].append(_err(
            'account_service',
            f'AccountService 미지원 (vendor={vendor}, HTTP 404)',
        ))
        return out

    out['auth_ok'] = acct_service is not None
    out['auth_rejected'] = (discovery.get('auth_status') == 401)
    if not out['auth_ok']:
        out['method'] = 'noop'
        out['action'] = 'none'
        out['errors'].extend(errs)
        out['errors'].append(_err(
            'account_service',
            '복구 계정으로 계정 관리 서비스에 접근하지 못해 표준 계정 정리를 시작하지 못했습니다.',
            detail='AccountService GET failed with recovery credential; no write attempted',
        ))
        return out

    out['errors'].extend(errs)

    policy = discovery.get('policy') or {}
    min_len, max_len = policy.get('min_password_length'), policy.get('max_password_length')
    pw_len = len(target_password or '')
    within = None
    if min_len is not None or max_len is not None:
        within = ((min_len is None or pw_len >= min_len)
                  and (max_len is None or pw_len <= max_len))
    out['policy'] = {
        'min_password_length': min_len,
        'max_password_length': max_len,
        'lockout_threshold':   policy.get('lockout_threshold'),
        'lockout_duration':    policy.get('lockout_duration'),
        'auth_failure_delay_seconds': policy.get('auth_failure_delay_seconds'),
        'supported_account_types': policy.get('supported_account_types'),
        'http_basic_auth': policy.get('http_basic_auth'),
        'auth_methods':    policy.get('auth_methods'),
        'within_declared_bounds': within,
    }
    verify_schedule = account_verify_delays(policy)
    out['verify_schedule_seconds'] = list(verify_schedule)
    auth_budget_limit = account_auth_budget(policy)
    out['auth_budget_limit'] = auth_budget_limit
    if isinstance(min_len, int) and isinstance(max_len, int) and min_len > max_len:
        out['policy_conflict'] = {'kind': 'declared_range_impossible',
                                  'min_password_length': min_len,
                                  'max_password_length': max_len}
        out['errors'].append(_err(
            'account_service',
            '장비가 선언한 비밀번호 길이 정책이 서로 모순됩니다. 장비 정책을 확인하세요.',
            detail=f'declared MinPasswordLength={min_len} > MaxPasswordLength={max_len}',
        ))
    elif within is False:
        out['policy_conflict'] = {'kind': 'password_outside_declared_range',
                                  'min_password_length': min_len,
                                  'max_password_length': max_len}
        out['errors'].append(_err(
            'account_service',
            '표준 계정 비밀번호가 장비가 선언한 길이 정책 범위를 벗어납니다. '
            '쓰기는 시도하되 거부될 수 있습니다.',
            detail=f'declared MinPasswordLength={min_len} MaxPasswordLength={max_len}',
        ))

    family, family_reasons = resolve_account_family(vendor, discovery, adapter_id)
    out['family']         = family['id']
    out['create_method']  = family['create_method']
    out['evidence']       = family['evidence']
    out['family_reasons'] = family_reasons
    out['isolation_basis']   = family.get('isolation_basis')
    out['firmware_advisory'] = family.get('firmware_advisory')
    role_id = choose_role_id(family, target_role, discovery)
    supported_roles = [r for r in (discovery.get('role_ids') or []) if isinstance(r, str)]
    if supported_roles and role_id not in supported_roles:
        out['role_id_unsupported'] = True
        out['errors'].append(_err(
            'account_service',
            '장비가 알려 준 권한 목록에 없는 권한 이름을 사용합니다. '
            '표준 계정의 권한 설정을 확인하세요.',
            detail=f'RoleId={role_id!r} not in device Roles {sorted(supported_roles)}',
        ))

    presence, matches = account_presence(discovery, target_username, family)
    out['presence'] = presence

    if presence == PRESENCE_PROTECTED_CONFLICT:
        out['method'] = 'noop'
        out['action'] = 'none'
        out['account_existed'] = True
        slot_ids = [('' if m.get('id') is None else str(m.get('id'))) for m in matches]
        out['errors'].append(_err(
            'account_service',
            '표준 계정 이름이 시스템 예약 계정과 겹쳐 자동 처리를 중단했습니다. '
            '표준 계정 이름 또는 해당 슬롯을 정리한 뒤 다시 시도하세요.',
            detail='protected accounts: ' + ', '.join(s for s in slot_ids if s),
        ))
        return out

    if presence == PRESENCE_AMBIGUOUS:
        slot_ids = [('' if m.get('id') is None else str(m.get('id'))) for m in matches]
        out['method']          = 'ambiguous'
        out['action']          = 'ambiguous'
        out['account_existed'] = True
        out['errors'].append(_err(
            'account_service',
            '동일한 사용자 이름이 여러 계정 슬롯에 존재해 자동 처리를 중단했습니다. '
            '중복 슬롯을 정리한 뒤 다시 시도하세요.',
            detail='duplicate slots: ' + ', '.join(s for s in slot_ids if s),
        ))
        return out

    if presence == PRESENCE_UNKNOWN:
        out['method'] = 'noop'
        out['action'] = 'none'
        out['errors'].append(_err(
            'account_service',
            '계정 목록을 완전히 확인하지 못해 표준 계정 생성을 시작하지 않았습니다. '
            '복구 계정의 사용자 관리 권한과 계정 관리 서비스 상태를 확인하세요.',
            detail=(f'enumeration={discovery.get("enumeration")} '
                    f'declared={discovery.get("member_total")} '
                    f'read={discovery.get("member_read")}; no write attempted'),
        ))
        return out

    existing = matches[0] if matches else None

    if existing:
        out['method']          = 'patch_existing'
        out['action']          = 'password_sync'
        out['account_existed'] = True
        out['slot_uri']        = existing.get('slot_uri')
        if existing.get('enabled') is False:
            out['errors'].append(_err(
                'account_service',
                '대상 계정이 비활성 상태입니다. 비밀번호 불일치가 아니라 계정 비활성이 원인일 수 있습니다.',
                detail=f'slot={existing.get("id")} Enabled=false',
            ))
        if existing.get('locked') is True:
            out['errors'].append(_err(
                'account_service',
                '대상 계정이 잠금 상태입니다. 비밀번호 불일치가 아니라 계정 잠금이 원인일 수 있습니다.',
                detail=f'slot={existing.get("id")} Locked=true',
            ))
        out['login_interfaces'] = existing.get('login_interfaces')
        if existing.get('login_interfaces') is not None \
                and not any(s.lower() == 'redfish' for s in existing['login_interfaces']):
            out['errors'].append(_err(
                'account_service',
                '대상 계정에 Redfish 접근이 허용되어 있지 않습니다. '
                '비밀번호 문제가 아니라 계정의 접근 인터페이스 설정 문제일 수 있습니다.',
                detail=('login interfaces='
                        + ','.join(existing['login_interfaces'])),
            ))
        if dryrun:
            out['verification'] = 'skipped'
            return out
        full_body = bool(family.get('full_body_patch'))
        body_full = {}
        if account_prop_writable(family, 'Password', 'repair'):
            body_full['Password'] = target_password
        if account_prop_writable(family, 'Enabled', 'repair') \
                and (full_body or existing.get('enabled') is not True):
            body_full['Enabled'] = True
        if account_prop_writable(family, 'RoleId', 'repair') \
                and (full_body or (existing.get('role_id') or '') != role_id):
            body_full['RoleId'] = role_id
        if family.get('account_types') and existing.get('account_types') is not None \
                and account_prop_writable(family, 'AccountTypes', 'repair'):
            want = set(family['account_types'])
            if not want.issubset(set(existing.get('account_types') or [])):
                body_full['AccountTypes'] = sorted(
                    set(existing.get('account_types') or []) | want)
        if existing.get('password_change_required') is True \
                and account_prop_writable(family, 'PasswordChangeRequired', 'repair'):
            body_full['PasswordChangeRequired'] = False
        if existing.get('locked') is True and account_prop_writable(family, 'Locked', 'repair'):
            body_full['Locked'] = False
        patch_headers = None
        if account_if_match(family, 'repair'):
            etag = _get_response_etag(bmc_ip, _p(existing['slot_uri']),
                                      current_username, current_password, timeout, verify_ssl)
            if etag:
                patch_headers = {'If-Match': etag}
        followup_body = {}
        if family.get('isolated_write_patch'):
            followup = {k: v for k, v in body_full.items() if k != 'Password'}
            if followup.get('Enabled') is True and existing.get('enabled') is True:
                followup.pop('Enabled', None)
            if 'RoleId' in followup and existing.get('role_id') == followup.get('RoleId'):
                followup.pop('RoleId', None)
            body_full = {'Password': target_password}
            followup_body = followup
            out['isolated_write'] = True
        code, patch_resp, err = _patch_account(
            bmc_ip, _p(existing['slot_uri']), body_full,
            current_username, current_password, timeout, verify_ssl, patch_headers,
        )
        if code == 412 and account_if_match(family, 'repair'):
            etag = _get_response_etag(bmc_ip, _p(existing['slot_uri']),
                                      current_username, current_password, timeout, verify_ssl)
            if etag:
                code, patch_resp, err = _patch_account(
                    bmc_ip, _p(existing['slot_uri']), body_full,
                    current_username, current_password, timeout, verify_ssl,
                    {'If-Match': etag},
                )
        out['write_response_info'] = _extended_info(patch_resp) or out.get('write_response_info')
        out['write_http_status'] = code
        accepted, reject_reason = interpret_write_response(
            family, code, patch_resp, err, requested=set(body_full))
        out['write_accepted'] = accepted
        out['vendor_status'] = reject_reason
        out['write_rejections'] = write_rejections(patch_resp, set(body_full))
        if not accepted:
            out['errors'].append(_err(
                'account_service',
                f'PATCH 기존 사용자 실패 (slot={existing.get("id")})',
                detail=' | '.join(x for x in (
                    reject_reason, out['write_response_info'],
                ) if x),
            ))
            return out
        if followup_body:
            f_code, f_resp, f_err = _patch_account(
                bmc_ip, _p(existing['slot_uri']), followup_body,
                current_username, current_password, timeout, verify_ssl, patch_headers,
            )
            f_ok, f_reason = interpret_write_response(family, f_code, f_resp, f_err)
            out['followup_properties'] = sorted(followup_body)
            out['followup_accepted'] = f_ok
            if not f_ok:
                out['errors'].append(_err(
                    'account_service',
                    '표준 계정 비밀번호는 적용됐지만 계정 속성(권한/활성) 동기화는 거부됐습니다.',
                    detail=' | '.join(x for x in (
                        f'properties={",".join(sorted(followup_body))}',
                        f_reason, _extended_info(f_resp),
                    ) if x),
                ))
        state_ok, _state_mismatch = _confirm_account_state(
            bmc_ip, existing.get('slot_uri'), target_username,
            family, current_username, current_password,
            timeout, verify_ssl, out)
        ok_v, verify_code, verify_err, attempts = _verify_standard_credential()
        out['verify_attempts'] = attempts
        if ok_v and state_ok is not False:
            out['recovered']    = True
            out['verification'] = 'verified'
            return out
        if ok_v:
            out['verification'] = 'state_mismatch'
            return out
        out['verification'] = 'failed'
        if not allow_delete_recreate:
            out['errors'].append(_err(
                'account_service',
                '기존 계정의 비밀번호를 맞춘 뒤 인증 확인에 실패했습니다. '
                '계정을 지우고 다시 만드는 자동 복구는 하지 않았습니다. 계정 상태를 확인하세요.',
                detail='; '.join(x for x in (
                    (verify_err or f'verify HTTP {verify_code}'),
                    f'slot={existing.get("id")}',
                    f'verify_attempts={out.get("verify_attempts")}',
                    (f'write_response={out["write_response_info"]}'
                     if out.get('write_response_info') else None),
                    'delete_recreate=disabled',
                ) if x),
            ))
            out['errors'].append(_err(
                'account_service',
                '비밀번호가 대상 장비의 암호 정책을 충족하지 못해 적용되지 않았을 수 있습니다. '
                '장비의 암호 정책과 등록된 비밀번호를 확인하세요.',
                detail=(
                    'write accepted but authentication with the new credential failed; '
                    'check BMC password strength policy (length / character classes / '
                    'password history) against the configured value'
                ),
            ))
            return out
        out['errors'].append(_err(
            'account_service',
            f'PATCH 200 후 verify {verify_code} (권한 cache 손상 의심) — '
            f'DELETE+POST 재생성 fallback 시도 (slot={existing.get("id")})',
            detail=verify_err or f'verify HTTP {verify_code}',
        ))
        if vendor == 'dell':
            out['errors'].append(_err(
                'account_service',
                'Dell iDRAC PATCH-only — DELETE+POST fallback 미지원 (수동 복구 필요)',
            ))
            return out
        del_code, _, del_err = _delete(
            bmc_ip, _p(existing['slot_uri']),
            current_username, current_password, timeout, verify_ssl,
        )
        if del_code not in (200, 204) or del_err:
            out['errors'].append(_err(
                'account_service',
                f'DELETE 실패 (slot={existing.get("id")}) — fallback 불가',
                detail=del_err or f'HTTP {del_code}',
            ))
            return out
        repost_id = (existing.get('id') or '2') if family.get('needs_explicit_id') else None
        body_post = build_create_payload(
            family, target_username, target_password, role_id,
            explicit_id=repost_id,
        )
        post_code, post_data, post_err = _post(
            bmc_ip, _create_target_uri(family, discovery, repost_id), body_post,
            current_username, current_password, timeout, verify_ssl,
        )
        out['write_http_status'] = post_code
        accepted_r, reason_r = interpret_write_response(family, post_code, post_data, post_err)
        out['write_accepted'] = accepted_r
        out['vendor_status'] = reason_r
        if accepted_r:
            auth_budget_limit += len(verify_schedule)
            out['auth_budget_limit'] = auth_budget_limit
            out['method']   = 'delete_repost'
            out['slot_uri'] = _str(_safe(post_data, '@odata.id')) or existing.get('slot_uri')
            state_ok_r, _mm_r = _confirm_account_state(
                bmc_ip, out['slot_uri'], target_username, family,
                current_username, current_password, timeout, verify_ssl, out)
            ok_r, vcode_r, verr_r, attempts_r = _verify_standard_credential()
            out['verify_attempts'] = attempts_r
            out['recovered']    = bool(ok_r) and state_ok_r is not False
            out['verification'] = ('verified' if out['recovered']
                                   else ('state_mismatch' if ok_r else 'failed'))
            if not ok_r:
                out['errors'].append(_err(
                    'account_service',
                    'DELETE+POST 재생성 후 표준 계정 인증에 실패했습니다.',
                    detail=verr_r or f'verify HTTP {vcode_r}',
                ))
        else:
            out['errors'].append(_err(
                'account_service',
                'DELETE+POST 재생성 실패',
                detail=reason_r or post_err or f'HTTP {post_code}',
            ))
        return out

    out['method'] = 'patch_empty_slot' if family['create_method'] == 'slot_patch' else 'post_new'
    out['action'] = 'create'

    chosen_slot = None
    explicit_id = None
    if family['create_method'] == 'slot_patch':
        protected_ids = {('' if a.get('id') is None else str(a.get('id')))
                         for a in accounts if account_is_protected(a, family)}
        empty_slots = account_service_find_all_empty_slots(
            accounts, skip_slot_ids=set(family['reserved_slot_ids']) | protected_ids,
        )
        if not empty_slots:
            out['errors'].append(_err(
                'account_service',
                '빈 계정 슬롯이 없어 표준 계정을 만들 수 없습니다. 사용하지 않는 계정을 정리하세요.',
                detail=f'family={family["id"]} reserved={sorted(family["reserved_slot_ids"])}',
            ))
            return out
        chosen_slot = empty_slots[0]
        out['slot_uri'] = chosen_slot.get('slot_uri')
    elif family['needs_explicit_id']:
        lo, hi = family['id_range'] or (2, 16)
        used_ids = {('' if a.get('id') is None else str(a.get('id'))) for a in accounts}
        used_ids |= {('' if a.get('id') is None else str(a.get('id')))
                     for a in accounts if account_is_protected(a, family)}
        used_ids |= set(family['reserved_slot_ids'] or ())
        for candidate_id in range(lo, hi):
            if str(candidate_id) not in used_ids:
                explicit_id = str(candidate_id)
                break
        if explicit_id is None:
            out['errors'].append(_err(
                'account_service',
                '사용 가능한 계정 번호가 없어 표준 계정을 만들 수 없습니다. 계정을 정리하세요.',
                detail=f'family={family["id"]} id_range={lo}-{hi - 1} used={sorted(used_ids)}',
            ))
            return out

    if dryrun:
        out['verification'] = 'skipped'
        return out

    if family['create_method'] == 'slot_patch':
        body = build_create_payload(family, target_username, target_password, role_id)
        code, patch_resp, err = _patch(
            bmc_ip, _p(chosen_slot['slot_uri']), body,
            current_username, current_password, timeout, verify_ssl,
        )
        out['write_response_info'] = _extended_info(patch_resp) or out['write_response_info']
        out['write_http_status'] = code
        accepted, reject_reason = interpret_write_response(family, code, patch_resp, err)
        out['write_accepted'] = accepted
        out['vendor_status'] = reject_reason
        if not accepted:
            out['verification'] = 'failed'
            out['errors'].append(_err(
                'account_service',
                f'빈 슬롯에 표준 계정을 만들지 못했습니다 (slot={chosen_slot.get("id")}).',
                detail=' | '.join(x for x in (
                    reject_reason, out['write_response_info']) if x),
            ))
            return out
        state_ok, _state_mismatch = _confirm_account_state(
            bmc_ip, chosen_slot.get('slot_uri'), target_username, family,
            current_username, current_password, timeout, verify_ssl, out)
        ok_v, verify_code, verify_err, attempts = _verify_standard_credential()
        out['verify_attempts'] = attempts
        if ok_v and state_ok is not False:
            out['recovered']    = True
            out['verification'] = 'verified'
            return out
        if ok_v:
            out['verification'] = 'state_mismatch'
            return out
        out['verification'] = 'failed'
        out['errors'].append(_err(
            'account_service',
            '표준 계정 생성은 수락됐지만 그 계정으로 인증되지 않았습니다. '
            '장비의 암호 정책과 등록된 비밀번호를 확인하세요.',
            detail=' | '.join(x for x in (
                (verify_err or f'verify HTTP {verify_code}'),
                f'slot={chosen_slot.get("id")}',
                'check BMC password strength policy (length / character classes / history)',
                out['write_response_info'],
            ) if x),
        ))
        cl_code, cl_resp, cl_err = _patch(
            bmc_ip, _p(chosen_slot['slot_uri']),
            {'UserName': '', 'Enabled': False, 'RoleId': 'None'},
            current_username, current_password, timeout, verify_ssl,
        )
        if cl_code not in (200, 204) or cl_err:
            out['errors'].append(_err(
                'account_service',
                '실패한 슬롯을 되돌리지 못했습니다. 해당 슬롯 상태를 확인하세요.',
                detail=' | '.join(x for x in (
                    cl_err or f'HTTP {cl_code}', _extended_info(cl_resp)) if x),
            ))
        return out

    accounts_uri = _create_target_uri(family, discovery, explicit_id)
    out['create_uri'] = accounts_uri
    out['create_uri_kind'] = family.get('create_uri')
    out['create_uri_basis'] = family.get('create_uri_basis')
    body_base = build_create_payload(family, target_username, target_password, role_id,
                                     explicit_id=explicit_id)
    code, resp_data, err = _post(
        bmc_ip, accounts_uri, body_base,
        current_username, current_password, timeout, verify_ssl,
    )
    out['write_http_status'] = code
    accepted, reject_reason = interpret_write_response(
        family, code, resp_data, err, requested=set(body_base))
    out['write_response_info'] = _extended_info(resp_data) or out['write_response_info']
    out['write_rejections'] = write_rejections(resp_data, set(body_base))


    out['write_accepted'] = accepted
    out['vendor_status'] = reject_reason
    if not accepted:
        out['verification'] = 'failed'
        out['errors'].append(_err(
            'account_service',
            '표준 계정 생성 요청이 거부됐습니다.',
            detail=' | '.join(x for x in (
                f'POST {accounts_uri}', f'family={family["id"]}',
                reject_reason, out['write_response_info']) if x),
        ))
        return out

    created_uri = _str(_safe(resp_data, '@odata.id')) or None
    if not created_uri:
        recheck = account_service_discover(bmc_ip, current_username, current_password,
                                           timeout, verify_ssl,
                                           service_root=discovery.get('service'))
        again = [a for a in (recheck.get('accounts') or [])
                 if (a.get('username') or '') == target_username]
        created_uri = again[0].get('slot_uri') if len(again) == 1 else None
    out['slot_uri'] = created_uri

    state_ok, _state_mismatch = _confirm_account_state(
        bmc_ip, created_uri, target_username, family,
        current_username, current_password, timeout, verify_ssl, out)
    ok_v, verify_code, verify_err, attempts = _verify_standard_credential()
    out['verify_attempts'] = attempts
    if ok_v and state_ok is not False:
        out['recovered']    = True
        out['verification'] = 'verified'
        return out
    if ok_v:
        out['verification'] = 'state_mismatch'
        return out
    out['verification'] = 'failed'
    out['errors'].append(_err(
        'account_service',
        '표준 계정을 만들었지만 그 계정으로 인증되지 않았습니다. '
        '장비의 암호 정책과 계정 상태를 확인하세요.',
        detail=' | '.join(x for x in (
            (verify_err or f'verify HTTP {verify_code}'),
            f'family={family["id"]}', out['write_response_info']) if x),
    ))
    return out


def main():
    module = AnsibleModule(
        argument_spec=dict(
            bmc_ip          = dict(type='str',  required=True),
            username        = dict(type='str',  required=True),
            password        = dict(type='str',  required=True, no_log=True),
            timeout         = dict(type='int',  default=30),
            verify_ssl      = dict(type='bool', default=False),
            mode            = dict(type='str',  default='gather',
                                   choices=['gather', 'account_provision', 'detect']),
            target_username = dict(type='str',  default=''),
            target_password = dict(type='str',  default='', no_log=True),
            target_role     = dict(type='str',  default='Administrator'),
            dryrun          = dict(type='bool', default=True),
            allow_delete_recreate = dict(type='bool', default=False),
            manager_layout  = dict(type='str',  default=None, required=False),
            adapter_id      = dict(type='str',  default=None, required=False),
            attempt         = dict(type='dict', default=None, required=False),
        ),
        supports_check_mode=True,
    )

    def _exit(**kw):
        _evidence_finish()
        module.exit_json(**kw)

    if not HAS_URLLIB:
        module.fail_json(msg='Python urllib 를 import 할 수 없습니다')

    _reset_auth_observation()
    _reset_notices()

    p = module.params
    bmc_ip, username, password = p['bmc_ip'], p['username'], p['password']
    timeout, verify_ssl = p['timeout'], p['verify_ssl']
    mode = p['mode']
    _evidence_begin(p.get('attempt'), bmc_ip, username)
    _reset_response_cache(enabled=(mode in ('gather', 'detect')))

    if mode == 'detect':
        vendor, system_uri, manager_uri, chassis_uri, det_errors, service_root = detect_vendor(
            bmc_ip, username, password, timeout, verify_ssl
        )
        probe_facts = _extract_probe_facts(service_root, vendor)
        data = {'system': None, 'bmc': None}
        if system_uri:
            st_s, sdata, _e_s = _get(bmc_ip, _p(system_uri), username, password, timeout, verify_ssl)
            if st_s == 200 and isinstance(sdata, dict):
                data['system'] = {'model': _strip_or_none(_safe(sdata, 'Model')),
                                  'manufacturer': _strip_or_none(_safe(sdata, 'Manufacturer'))}
        if manager_uri:
            st_m, mdata, _e_m = _get(bmc_ip, _p(manager_uri), username, password, timeout, verify_ssl)
            if st_m == 200 and isinstance(mdata, dict):
                data['bmc'] = {'firmware_version': _strip_or_none(_safe(mdata, 'FirmwareVersion')),
                               'model': _strip_or_none(_safe(mdata, 'Model'))}
        _exit(
            changed=False, mode='detect',
            status=('success' if isinstance(service_root, dict) and service_root else 'failed'),
            vendor=vendor, collected=[], failed_sections=[], unsupported_sections=[],
            errors=list(det_errors), data=data, probe_facts=probe_facts, multi_node=None,
            auth_evidence=auth_evidence(), notices=notices(),
            cache=cache_stats(),
        )
        return

    if mode == 'account_provision':
        target_username = p['target_username']
        target_password = p['target_password']
        target_role     = p['target_role']
        dryrun          = p['dryrun']

        if not target_username or not target_password:
            module.fail_json(
                msg='mode=account_provision 시 target_username/target_password 필수'
            )

        dryrun_reason = None
        if module.check_mode and not dryrun:
            dryrun_reason = 'check_mode'
        elif dryrun:
            dryrun_reason = 'parameter'
        dryrun = bool(dryrun) or bool(module.check_mode)

        vendor, _, mgr_uri, _, det_errors, svc_root = detect_vendor(
            bmc_ip, username, password, timeout, verify_ssl
        )
        result = account_service_provision(
            bmc_ip, vendor, username, password,
            target_username, target_password, target_role,
            timeout, verify_ssl, dryrun=dryrun,
            allow_delete_recreate=bool(p.get('allow_delete_recreate')),
            adapter_id=p.get('adapter_id'),
            manager_uri=mgr_uri,
            service_root=svc_root,
        )
        result['dryrun_reason'] = dryrun_reason
        result['errors'] = list(det_errors) + (result.get('errors') or [])
        _exit(
            changed=bool(result.get('recovered')),
            mode='account_provision',
            vendor=vendor,
            account_service=result,
            notices=notices(),
        )
        return

    all_errors, collected, failed, unsupported = [], [], [], []

    manager_layout = p.get('manager_layout') or None

    vendor, system_uri, manager_uri, chassis_uri, det_errors, service_root = detect_vendor(
        bmc_ip, username, password, timeout, verify_ssl
    )
    all_errors.extend(det_errors)

    probe_facts = _extract_probe_facts(service_root, vendor)

    if not system_uri:
        _exit(
            changed=False, status='failed', vendor=vendor,
            collected=[], failed_sections=['all'], unsupported_sections=[],
            errors=all_errors, data={}, probe_facts=probe_facts,
            multi_node=None, auth_evidence=auth_evidence(), notices=notices(),
        )

    _serial_resolver = _SERIAL_RESOLVERS.get(vendor)
    _forced_serial = None
    if _serial_resolver is not None:
        def _reauth_service_root():
            if not username:
                return None
            st_r, root_r, err_r = _get(bmc_ip, '', username, password, timeout, verify_ssl)
            if err_r or st_r != 200 or not isinstance(root_r, dict):
                return None
            return root_r

        _forced_serial, _serial_err = _serial_resolver(
            service_root, refetch=_reauth_service_root)
        if _serial_err is not None:
            all_errors.append(_err('system', _serial_err))
            _exit(
                changed=False, status='failed', vendor=vendor,
                collected=[], failed_sections=['all'], unsupported_sections=[],
                errors=all_errors, data={}, probe_facts=probe_facts,
                multi_node=None, auth_evidence=auth_evidence(), notices=notices(),
            )

    result_data = _collect_all_sections(
        bmc_ip, vendor, system_uri, manager_uri, chassis_uri,
        username, password, timeout, verify_ssl,
        all_errors, collected, failed, unsupported,
        manager_layout=manager_layout,
        product_hint=_safe(service_root, 'Product'),
    )

    if _serial_resolver is not None:
        _sys_section = result_data.get('system')
        if isinstance(_sys_section, dict) and _sys_section:
            _sys_section['serial'] = _forced_serial
        else:
            all_errors.append(_err(
                'system',
                '서버 대표 시리얼을 결과에 실을 수 없습니다 — system 섹션 수집 실패'))
            _exit(
                changed=False, status='failed', vendor=vendor,
                collected=[], failed_sections=['all'], unsupported_sections=[],
                errors=all_errors, data={}, probe_facts=probe_facts,
                multi_node=None, auth_evidence=auth_evidence(), notices=notices(),
            )

    multi_node = _collect_multi_node_topology(
        bmc_ip, vendor, service_root,
        username, password, timeout, verify_ssl,
        manager_layout=manager_layout,
    )
    if isinstance(multi_node, dict):
        all_errors.extend(multi_node.get('errors') or [])

    final_status, clean = _compute_final_status(collected, failed, all_errors)

    _exit(
        changed=False, status=final_status, vendor=vendor,
        collected=clean, failed_sections=list(set(failed)),
        unsupported_sections=list(set(unsupported)),
        errors=all_errors, data=result_data, probe_facts=probe_facts,
        multi_node=multi_node, auth_evidence=auth_evidence(), notices=notices(),
        cache=cache_stats(),
    )


if __name__ == '__main__':
    main()
