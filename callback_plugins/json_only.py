__metaclass__ = type

import datetime
import json
import os
import re
import sys

from ansible.plugins.callback import CallbackBase

DOCUMENTATION = r'''
    name: json_only
    type: stdout
    short_description: Print only OUTPUT task result as JSON
    description:
      - Suppresses all Ansible output except the task named OUTPUT (configurable).
      - The OUTPUT task's msg field is printed as compact JSON to stdout.
      - Errors are written to stderr as structured JSON.
    options:
      output_task_name:
        description: Name of the task whose result will be printed.
        env:
          - name: ANSIBLE_JSON_OUTPUT_TASK
        default: OUTPUT
'''

_CHANNEL_ENVELOPE = {
    'os':      ('os', 'agent'),
    'esxi':    ('esxi', 'vsphere_api'),
    'redfish': ('redfish', 'redfish_api'),
}

_ALL_SECTIONS = ('system', 'hardware', 'bmc', 'cpu', 'memory', 'storage', 'network',
                 'firmware', 'users', 'power', 'thermal')
_CHANNEL_SECTIONS = {
    'os':      ('system', 'hardware', 'cpu', 'memory', 'storage', 'network', 'users'),
    'esxi':    ('system', 'hardware', 'cpu', 'memory', 'storage', 'network'),
    'redfish': ('system', 'hardware', 'bmc', 'cpu', 'memory', 'storage', 'network',
                'firmware', 'power', 'thermal'),
}
_META_KEYS = ('started_at', 'finished_at', 'duration_ms', 'adapter_id', 'adapter_version',
              'ansible_version')
_CORRELATION_KEYS = ('serial_number', 'system_uuid', 'bmc_ip', 'host_ip')
_DATA_SKELETON = {
    'system': None, 'hardware': None, 'bmc': None, 'cpu': None, 'memory': None,
    'storage': {'filesystems': [], 'physical_disks': [], 'datastores': [], 'controllers': [],
                'logical_volumes': [], 'hbas': [], 'infiniband': [],
                'summary': {'groups': [], 'grand_total_gb': 0}},
    'network': {'dns_servers': [], 'default_gateways': [], 'interfaces': [], 'adapters': [],
                'ports': [], 'virtual_switches': [], 'portgroups': [], 'driver_map': [],
                'summary': {'groups': []}},
    'users': [], 'firmware': [], 'power': None, 'thermal': {'temperatures': [], 'fans': []},
}


def _failed_shape(channel, ip):
    supported = set(_CHANNEL_SECTIONS.get(channel, ()))
    return {
        'sections':    {s: ('failed' if s in supported else 'not_supported') for s in _ALL_SECTIONS},
        'meta':        {k: None for k in _META_KEYS},
        'correlation': {k: (ip if k == 'host_ip' or (k == 'bmc_ip' and channel == 'redfish') else None)
                        for k in _CORRELATION_KEYS},
        'data':        json.loads(json.dumps(_DATA_SKELETON)),
    }

_PLAYBOOK_DIR_CHANNEL = {
    'os-gather':      'os',
    'esxi-gather':    'esxi',
    'redfish-gather': 'redfish',
}

_CONNECTIONLESS_ACTIONS = frozenset({
    'set_fact', 'debug', 'assert', 'fail', 'meta', 'add_host', 'group_by',
    'include', 'include_tasks', 'import_tasks', 'include_vars',
    'include_role', 'import_role', 'import_playbook', 'pause',
    'precheck_bundle', 'redfish_gather',
})

_LOCAL_CONNECTIONS = frozenset({'local', 'ansible.builtin.local'})
_LOCAL_DELEGATES = frozenset({'localhost', '127.0.0.1', '::1'})

_FAILURE_REASON_CATALOG = {
    'auth_unconfirmed': {
        'os': '해당 위치({loc})의 Vault 계정으로 대상 OS에 로그인하지 못했습니다.',
        'esxi': '해당 위치({loc})의 Vault 계정으로 대상 ESXi에 로그인하지 못했습니다.',
        'redfish': '개더링 표준 계정으로 대상 Redfish에 인증하지 못했습니다.',
        'default': '해당 위치({loc})의 Vault 계정으로 대상에 로그인하지 못했습니다.',
    },
    'loc_vault_no_account': {
        'os': '해당 위치({loc})의 Vault에 OS용 계정이 없습니다.',
        'esxi': '해당 위치({loc})의 Vault에 ESXi용 계정이 없습니다.',
        'default': '해당 위치({loc})의 Vault에 계정이 없습니다.',
    },
    'gather_connection_lost': {
        'default': '정보 수집 중 대상 서버와 연결이 끊겼습니다.',
    },
    'output_build_failed': {
        'default': '개더링 프로젝트에서 수집 결과를 만들지 못했습니다.',
    },
}

_LOC_UNSAFE = re.compile(r'[^A-Za-z0-9_.-]')
_LOC_MAX_LEN = 40
_LOC_EMPTY = '미지정'


def _display_location(loc):
    if loc is None:
        return _LOC_EMPTY
    text = _LOC_UNSAFE.sub('', str(loc).strip())[:_LOC_MAX_LEN]
    return text or _LOC_EMPTY


def _reason(key, channel=None, loc=None):
    entry = _FAILURE_REASON_CATALOG[key]
    text = entry.get(channel) if channel else None
    if text is None:
        text = entry['default']
    return text.replace('{loc}', _display_location(loc))


_REASON_NO_OUTPUT = _reason('output_build_failed')

_CHECKPOINT_ADDON_INTERRUPTED = '추가 수집 중 처리가 중단되어 추가 수집 결과가 없습니다. 기본 수집 결과는 그대로입니다.'
_CHECKPOINT_EMIT_FAILED = '수집은 끝났지만 결과를 내보내는 단계에서 중단되었습니다. 기본 수집 결과는 그대로입니다.'



def _is_truthy(value):
    return str(value or '').strip().lower() in ('1', 'true', 'yes')


class CallbackModule(CallbackBase):

    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE    = 'stdout'
    CALLBACK_NAME    = 'json_only'
    CALLBACK_NEEDS_ENABLED = False

    def __init__(self):
        super(CallbackModule, self).__init__()
        self._output_task = os.getenv('ANSIBLE_JSON_OUTPUT_TASK', 'OUTPUT')
        self._output_file = os.getenv('ANSIBLE_JSON_OUTPUT_FILE', '').strip()
        self._progress_file = os.getenv('ANSIBLE_JSON_PROGRESS_FILE', '').strip()
        self._checkpoint_file = os.getenv('ANSIBLE_JSON_CHECKPOINT_FILE', '').strip()
        self._manifest_file = os.getenv('ANSIBLE_JSON_MANIFEST_FILE', '').strip()
        self._manifest_compared = False
        self._checkpoint_task = os.getenv('ANSIBLE_JSON_CHECKPOINT_TASK', 'CHECKPOINT')
        self._addon_start_task = 'ADDON_START'
        self._addon_done_task = 'ADDON_DONE'
        self._hosts = {}
        self._playbook_channel = None
        self._reconcile = not _is_truthy(os.getenv('JSON_ONLY_NO_RECONCILE', ''))
        if not self._reconcile:
            sys.stderr.write(
                '[json_only] NOTICE: JSON_ONLY_NO_RECONCILE 이 켜져 있어 envelope 보충이 '
                '꺼졌다. 수집 도중 대상이 unreachable 이 되면 그 대상의 결과가 누락된다.\n'
            )


    def _emit(self, data, file=None):
        target = file or sys.stdout
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, ValueError) as e:
                if os.getenv('JSON_ONLY_DEBUG', '').lower() in ('1', 'true', 'yes'):
                    sys.stderr.write(
                        '[json_only] _emit: JSON 파싱 실패, 문자열 그대로 출력 '
                        '(reason={}, head={!r})\n'.format(type(e).__name__, data[:120])
                    )
        try:
            line = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
        except TypeError:
            line = json.dumps(str(data), ensure_ascii=False, separators=(',', ':'))
        print(line, file=target, flush=True)
        if self._output_file and target is sys.stdout:
            try:
                with open(self._output_file, 'a', encoding='utf-8') as fh:
                    fh.write(line + '\n')
                    fh.flush()
                    os.fsync(fh.fileno())
            except (OSError, IOError) as e:
                sys.stderr.write(
                    '[json_only] WARNING: OUTPUT 파일 쓰기 실패 ({}): {}\n'.format(
                        self._output_file, type(e).__name__)
                )

    def _emit_error(self, error_type, message, host=None, task=None):
        line = '[json_only] {}: {}'.format(error_type, message)
        context = []
        if host:
            context.append('host={}'.format(host))
        if task:
            context.append('task={}'.format(task))
        if context:
            line += ' ({})'.format(', '.join(context))
        sys.stderr.write(line + '\n')


    @staticmethod
    def _now_iso():
        return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')

    @staticmethod
    def _json_line(data):
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, ValueError):
                pass
        try:
            return json.dumps(data, ensure_ascii=False, separators=(',', ':'))
        except TypeError:
            return json.dumps(str(data), ensure_ascii=False, separators=(',', ':'))

    def _progress(self, host_name, event, task=None, detail=None, **extra):
        if not self._progress_file:
            return
        try:
            ctx = self._hosts.get(host_name) or {}
            row = {'ts': self._now_iso(), 'host': host_name, 'ip': ctx.get('ip'), 'event': event,
                   'task': task, 'detail': (str(detail)[:160] if detail is not None else None)}
            for k, v in extra.items():
                if v is not None:
                    row[k] = v
            with open(self._progress_file, 'a', encoding='utf-8') as fh:
                fh.write(json.dumps(row, ensure_ascii=False, separators=(',', ':'), default=str) + '\n')
        except Exception as e:
            sys.stderr.write('[json_only] WARNING: progress 기록 실패 ({}): {}\n'.format(
                self._progress_file, type(e).__name__))

    def _checkpoint(self, result):
        res = getattr(result, 'result', None)
        if not isinstance(res, dict):
            res = getattr(result, '_result', None)
        payload = res.get('msg') if isinstance(res, dict) else None
        if payload is None and isinstance(res, dict):
            payload = res.get('ansible_facts')
        host = self._host_name(result)
        if payload is None:
            self._emit_error('checkpoint_empty', 'CHECKPOINT 태스크에 msg 가 없다', host=host)
            return
        line = self._json_line(payload)
        if self._checkpoint_file:
            try:
                with open(self._checkpoint_file, 'a', encoding='utf-8') as fh:
                    fh.write(line + '\n')
                    fh.flush()
                    os.fsync(fh.fileno())
            except (OSError, IOError) as e:
                sys.stderr.write('[json_only] WARNING: checkpoint 파일 쓰기 실패 ({}): {}\n'.format(
                    self._checkpoint_file, type(e).__name__))
        if self._reconcile:
            try:
                parsed = json.loads(line)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                self._ctx(host)['checkpoint_env'] = parsed
        self._progress(host, 'checkpoint', task=self._task_name(result))

    def _manifest_ips(self):
        if not self._manifest_file:
            return None
        try:
            with open(self._manifest_file, encoding='utf-8') as fh:
                data = json.load(fh)
            ips = data.get('ips') if isinstance(data, dict) else None
            return [str(x) for x in ips] if isinstance(ips, list) else None
        except Exception:
            return None


    @staticmethod
    def _task_name(result):
        task = getattr(result, 'task', None) or getattr(result, '_task', None)
        return getattr(task, 'name', None)

    @staticmethod
    def _task_fields(result):
        fields = getattr(result, 'task_fields', None)
        if not hasattr(fields, 'get'):
            fields = getattr(result, '_task_fields', None)
        return fields if hasattr(fields, 'get') else {}

    @staticmethod
    def _host_name(result):
        host = getattr(result, 'host', None) or getattr(result, '_host', None)
        try:
            return host.get_name()
        except Exception:
            return str(host) if host is not None else ''

    @staticmethod
    def _host_vars(result):
        host = getattr(result, 'host', None) or getattr(result, '_host', None)
        try:
            hv = host.get_vars()
        except Exception:
            return {}
        return hv if hasattr(hv, 'get') else {}

    @staticmethod
    def _plain(value):
        try:
            return json.loads(json.dumps(value, default=str))
        except (TypeError, ValueError):
            return None

    def _ctx(self, host_name):
        ctx = self._hosts.get(host_name)
        if ctx is None:
            ctx = {
                'emitted':      False,
                'diagnosis':    None,
                'target_type':  None,
                'collection_method': None,
                'ip':           None,
                'ip_checked':   False,
                'auth_proven':  False,
                'lost':         False,
                'fail_detail':  None,
                'fail_message': None,
                'location':          None,
                'cred_load_outcome': None,
            }
            self._hosts[host_name] = ctx
            ctx['_first_seen_pending'] = True
        return ctx

    def _track(self, result, ok=False, unreachable=False):
        if not self._reconcile:
            return
        try:
            ctx = self._ctx(self._host_name(result))
            fields = self._task_fields(result)

            if not ctx['ip_checked']:
                ctx['ip_checked'] = True
                if ctx['ip'] is None:
                    ip = self._host_vars(result).get('ansible_host')
                    if ip:
                        ctx['ip'] = str(ip)
            if ctx.pop('_first_seen_pending', False):
                self._progress(self._host_name(result), 'first_seen', task=self._task_name(result))

            if unreachable and not fields.get('ignore_unreachable'):
                ctx['lost'] = True
                res = getattr(result, 'result', None)
                if not isinstance(res, dict):
                    res = getattr(result, '_result', None)
                self._progress(self._host_name(result), 'lost', task=self._task_name(result),
                               detail=(res.get('msg') if isinstance(res, dict) else None))

            if ok:
                self._absorb_facts(ctx, result)
                if not ctx['auth_proven'] and self._proves_authentication(result, fields):
                    ctx['auth_proven'] = True
                    self._progress(self._host_name(result), 'auth_proven', task=self._task_name(result))

        except Exception:
            pass

    def _absorb_facts(self, ctx, result):
        res = getattr(result, 'result', None)
        if not isinstance(res, dict):
            res = getattr(result, '_result', None)
        facts = res.get('ansible_facts') if isinstance(res, dict) else None
        if not isinstance(facts, dict):
            return
        if '_diagnosis' in facts:
            diag = self._plain(facts.get('_diagnosis'))
            if isinstance(diag, dict):
                ctx['diagnosis'] = diag
                self._progress(self._host_name(result), 'precheck', task=self._task_name(result), diagnosis=diag)
        for key, slot in (('_out_target_type', 'target_type'),
                          ('_out_collection_method', 'collection_method'),
                          ('_out_ip', 'ip'),
                          ('_fail_error_detail', 'fail_detail'),
                          ('_fail_error_message', 'fail_message'),
                          ('_cred_location', 'location'),
                          ('_cred_load_outcome', 'cred_load_outcome')):
            if facts.get(key):
                ctx[slot] = str(facts[key])
        if facts.get('_cred_load_outcome') or facts.get('_cred_location'):
            self._progress(self._host_name(result), 'cred_load', task=self._task_name(result),
                           outcome=ctx.get('cred_load_outcome'), location=ctx.get('location'))

    def _proves_authentication(self, result, fields):
        action = str(fields.get('action') or '').rsplit('.', 1)[-1]
        if not action or action in _CONNECTIONLESS_ACTIONS:
            return False
        delegate = fields.get('delegate_to')
        if delegate and str(delegate) in _LOCAL_DELEGATES:
            return False
        connection = self._host_vars(result).get('ansible_connection') or fields.get('connection')
        if not connection or str(connection) in _LOCAL_CONNECTIONS:
            return False
        return True


    def v2_runner_on_ok(self, result):
        self._track(result, ok=True)
        name = self._task_name(result)
        if name == self._checkpoint_task:
            self._checkpoint(result)
            return
        if name == self._addon_start_task:
            if self._reconcile:
                self._ctx(self._host_name(result))['addon_started'] = True
            self._progress(self._host_name(result), 'addon_started', task=name)
            return
        if name == self._addon_done_task:
            if self._reconcile:
                self._ctx(self._host_name(result))['addon_done'] = True
            self._progress(self._host_name(result), 'addon_done', task=name)
            return
        if name != self._output_task:
            return
        res = result._result
        if 'msg' in res:
            self._emit(res['msg'])
        elif 'ansible_facts' in res:
            self._emit(res['ansible_facts'])
        else:
            return
        self._mark_emitted(result)

    def v2_runner_on_failed(self, result, ignore_errors=False):
        self._track(result)
        if self._task_name(result) != self._output_task:
            return
        msg = (result._result.get('msg')
               or result._result.get('stderr')
               or 'task failed')
        self._emit_error(
            error_type='task_failed',
            message=msg,
            host=self._host_name(result),
            task=self._task_name(result),
        )

    def v2_runner_on_unreachable(self, result):
        self._track(result, unreachable=True)
        if self._task_name(result) != self._output_task:
            return
        msg = result._result.get('msg', 'host unreachable')
        self._emit_error(
            error_type='host_unreachable',
            message=msg,
            host=self._host_name(result),
        )

    def _mark_emitted(self, result):
        if not self._reconcile:
            return
        try:
            self._ctx(self._host_name(result))['emitted'] = True
            self._progress(self._host_name(result), 'emitted', task=self._task_name(result))
        except Exception:
            pass


    def _resolve_channel(self, ctx):
        details = (ctx.get('diagnosis') or {}).get('details')
        if isinstance(details, dict) and details.get('channel') in _CHANNEL_ENVELOPE:
            return details['channel']
        return self._playbook_channel

    def _build_fallback_envelope(self, host_name, ctx):
        observed = ctx.get('diagnosis') if isinstance(ctx.get('diagnosis'), dict) else {}
        channel = self._resolve_channel(ctx)
        target_type, collection_method = _CHANNEL_ENVELOPE.get(channel, (channel, None))
        target_type = ctx.get('target_type') or target_type
        collection_method = ctx.get('collection_method') or collection_method
        ip = ctx.get('ip') or host_name

        details = observed.get('details')
        details = dict(details) if isinstance(details, dict) else {}
        if channel and not details.get('channel'):
            details['channel'] = channel

        if observed.get('failure_stage'):
            diagnosis = dict(observed)
            diagnosis['details'] = details
            if not (isinstance(diagnosis.get('failure_reason'), str)
                    and diagnosis['failure_reason'].strip()):
                diagnosis['failure_reason'] = _REASON_NO_OUTPUT
            err_section = 'precheck'
            err_detail = self._compose_detail(
                ctx, 'envelope reconciled by callback; precheck diagnosis preserved')
        elif ctx.get('lost') and ctx.get('auth_proven'):
            diagnosis = self._diagnosis(observed, details, True,
                                        'gather', 'GATHER_FAILED',
                                        _reason('gather_connection_lost'))
            err_section = 'gather'
            err_detail = ('envelope reconciled by callback; host became unreachable '
                          'after an authenticated task succeeded')
        elif ctx.get('lost'):
            key = ('loc_vault_no_account'
                   if ctx.get('cred_load_outcome') == 'empty_accounts'
                   else 'auth_unconfirmed')
            diagnosis = self._diagnosis(observed, details, None,
                                        'auth', 'AUTH_PROBE_FAILED',
                                        _reason(key, channel, ctx.get('location')))
            err_section = 'auth'
            err_detail = ('envelope reconciled by callback; host unreachable with no '
                          'evidence of a successful authenticated task')
        else:
            diagnosis = self._diagnosis(observed, details, observed.get('auth_success'),
                                        'fallback', 'OUTPUT_BUILD_FAILED', _REASON_NO_OUTPUT)
            err_section = 'gather'
            err_detail = 'envelope reconciled by callback; OUTPUT task did not run'

        err_message = diagnosis['failure_reason']

        shape = _failed_shape(channel or target_type, ip)
        return {
            'schema_version':    '1',
            'target_type':       target_type,
            'collection_method': collection_method,
            'ip':                ip,
            'hostname':          None,
            'vendor':            None,
            'status':            'failed',
            'sections':          shape['sections'],
            'diagnosis':         diagnosis,
            'meta':              shape['meta'],
            'correlation':       shape['correlation'],
            'errors':            [{'section': err_section,
                                   'message': err_message,
                                   'detail':  err_detail}],
            'data':              shape['data'],
        }

    @staticmethod
    def _compose_detail(ctx, fixed):
        parts = []
        for slot in ('fail_detail', 'fail_message'):
            value = ctx.get(slot)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        parts.append(fixed)
        return ' | '.join(parts)

    @staticmethod
    def _diagnosis(observed, details, auth_success, stage, code, reason):
        return {
            'reachable':          observed.get('reachable'),
            'port_open':          observed.get('port_open'),
            'protocol_supported': observed.get('protocol_supported'),
            'auth_success':       auth_success,
            'failure_stage':      stage,
            'failure_code':       code,
            'failure_reason':     reason,
            'details':            details,
        }

    def _minimal_envelope(self, host_name):
        channel = getattr(self, '_playbook_channel', None)
        target_type, collection_method = _CHANNEL_ENVELOPE.get(channel, (channel, None))
        shape = _failed_shape(channel, host_name)
        return {
            'schema_version':    '1',
            'target_type':       target_type,
            'collection_method': collection_method,
            'ip':                host_name,
            'hostname':          None,
            'vendor':            None,
            'status':            'failed',
            'sections':          shape['sections'],
            'diagnosis':         self._diagnosis(
                {}, {}, None, 'fallback', 'OUTPUT_BUILD_FAILED', _REASON_NO_OUTPUT),
            'meta':              shape['meta'],
            'correlation':       shape['correlation'],
            'errors':            [{'section': 'gather',
                                   'message': _REASON_NO_OUTPUT,
                                   'detail':  'envelope reconciled by callback; '
                                              'fallback envelope build failed'}],
            'data':              shape['data'],
        }

    @staticmethod
    def _envelope_from_checkpoint(checkpoint_env, ctx):
        env = json.loads(json.dumps(checkpoint_env))
        if ctx.get('addon_started') and not ctx.get('addon_done'):
            err = {'section': 'addon', 'message': _CHECKPOINT_ADDON_INTERRUPTED,
                   'detail': 'finalized from checkpoint; reconciled by callback at playbook end; '
                             'add-on started but did not finish'}
        else:
            err = {'section': 'gather', 'message': _CHECKPOINT_EMIT_FAILED,
                   'detail': 'finalized from checkpoint; reconciled by callback at playbook end; '
                             'OUTPUT was not emitted after assembly'}
        errors = env.get('errors') if isinstance(env.get('errors'), list) else []
        env['errors'] = errors + [err]
        return env

    def _reconcile_missing_envelopes(self, stats):
        if not self._reconcile:
            return
        processed = getattr(stats, 'processed', None)
        requested = list(processed) if isinstance(processed, dict) else []
        for host_name in list(self._hosts):
            if host_name not in requested:
                requested.append(host_name)

        for host_name in requested:
            ctx = self._hosts.get(host_name)
            if ctx is None or ctx.get('emitted'):
                continue
            source = 'observed'
            try:
                checkpoint_env = ctx.get('checkpoint_env')
                if isinstance(checkpoint_env, dict):
                    envelope = self._envelope_from_checkpoint(checkpoint_env, ctx)
                    source = 'checkpoint'
                else:
                    envelope = self._build_fallback_envelope(host_name, ctx)
            except Exception as e:
                envelope = self._minimal_envelope(host_name)
                source = 'minimal'
                sys.stderr.write(
                    '[json_only] WARNING: envelope 조립 실패 — 최소 envelope 으로 대체 '
                    '(host={}, reason={})\n'.format(host_name, type(e).__name__))
            try:
                self._emit(envelope)
                ctx['emitted'] = True
                self._progress(host_name, 'reconciled', source=source)
                diagnosis = envelope.get('diagnosis') if isinstance(envelope.get('diagnosis'), dict) else {}
                self._emit_error(
                    error_type='envelope_reconciled',
                    message='{} (source={})'.format(diagnosis.get('failure_code') or envelope.get('status'), source),
                    host=host_name,
                )
            except Exception as e:
                sys.stderr.write(
                    '[json_only] WARNING: envelope 보충 출력 실패 '
                    '(host={}, reason={})\n'.format(host_name, type(e).__name__))
        self._hosts = {}


    def v2_playbook_on_start(self, playbook):
        try:
            path = getattr(playbook, '_file_name', '') or ''
            parent = os.path.basename(os.path.dirname(os.path.abspath(path)))
            self._playbook_channel = _PLAYBOOK_DIR_CHANNEL.get(parent)
        except Exception:
            self._playbook_channel = None

    def v2_playbook_on_stats(self, stats):
        try:
            self._reconcile_missing_envelopes(stats)
        except Exception as e:
            self._emit_error(error_type='reconcile_failed', message=type(e).__name__)

    def v2_playbook_on_play_start(self, play):
        if not self._progress_file and not self._manifest_file:
            return
        try:
            vm = play.get_variable_manager()
            inv = getattr(vm, '_inventory', None)
            hosts = [h.get_name() for h in inv.get_hosts('all')] if inv is not None else None
        except Exception:
            hosts = None
        if hosts is None:
            return
        try:
            play_name = play.get_name()
        except Exception:
            play_name = None
        self._progress(None, 'inventory', task=play_name, hosts=hosts)
        if self._manifest_compared:
            return
        manifest = self._manifest_ips()
        if manifest is None:
            return
        try:
            full = [h.get_name() for h in inv.get_hosts('all', ignore_limits=True, ignore_restrictions=True)]
        except Exception:
            return
        self._manifest_compared = True
        if set(manifest) != set(full):
            missing = sorted(set(manifest) - set(full))
            extra = sorted(set(full) - set(manifest))
            sys.stderr.write('[json_only] NOTICE: 수집 대상(inventory)이 접수 목록과 다릅니다. 접수 목록에만 있음: {}, 수집 대상에만 있음: {}\n'
                             .format(missing[:5], extra[:5]))
    def v2_playbook_on_task_start(self, task, is_conditional): pass

    def v2_runner_on_skipped(self, result):
        self._track(result)

    def v2_runner_on_no_hosts(self, pattern):             pass
    def v2_playbook_on_no_hosts_matched(self):            pass
    def v2_playbook_on_no_hosts_remaining(self):          pass
    def v2_runner_item_on_ok(self, result):               pass
    def v2_runner_item_on_failed(self, result):           pass
    def v2_runner_item_on_skipped(self, result):          pass
    def v2_runner_retry(self, result):                    pass
    def v2_runner_on_async_ok(self, result):              pass
    def v2_runner_on_async_failed(self, result):          pass
    def v2_playbook_on_handler_task_start(self, task):    pass
    def v2_on_any(self, *args, **kwargs):                 pass
