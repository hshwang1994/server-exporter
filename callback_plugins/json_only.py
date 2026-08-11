# -*- coding: utf-8 -*-
"""
Ansible Callback Plugin — json_only  v2
========================================
OUTPUT 태스크의 결과만 JSON 으로 stdout 에 출력한다.
나머지 모든 Ansible 로그(play/task 헤더, ok/changed 메시지 등)는 억제한다.

호출자는 이 JSON 출력만 파싱한다.

envelope 보충 (2026-08-11, Phase 6-B)
------------------------------------
호출자 계약은 **요청 대상 1개 = 결과 envelope 정확히 1개** 다. 그런데 수집 도중 호스트가
unreachable 이 되면 Ansible 이 그 호스트를 play 에서 제거하므로 `rescue`(failed 전용)도
`always` 도 실행되지 않는다. OUTPUT 태스크가 아예 돌지 않아 **envelope 이 통째로 사라진다**
(2026-08-11 실측: 2 대 투입 → 1 envelope. 과거 동일 메커니즘 기록: 2026-06-17 evidence).

그래서 이 콜백이 호스트별 진행 상황을 추적했다가, 플레이북이 끝나는 시점
(`v2_playbook_on_stats`)에 **envelope 을 하나도 내지 못한 호스트**에 한해 13 필드 envelope 을
보충한다. site.yml 3종은 건드리지 않으며(채널 무관 동작), 이미 envelope 을 낸 호스트는
절대 건드리지 않는다(중복 0).

보충 envelope 의 진단 값은 **관측된 사실만** 사용한다. 근거와 매핑은 아래
`_reconcile_missing_envelopes` 주석 참조.

환경변수:
  ANSIBLE_JSON_OUTPUT_TASK  — 캡처할 태스크 이름 (기본값: OUTPUT)
  ANSIBLE_JSON_OUTPUT_FILE  — OUTPUT JSON 을 append 할 파일 경로
  JSON_ONLY_DEBUG           — 1/true/yes 이면 파싱 실패를 stderr 로 경고
  JSON_ONLY_NO_RECONCILE    — 1/true/yes 이면 envelope 보충을 끈다 (비상 스위치)
"""
# 단일 복사본 — 채널별 복사본(os-gather/, esxi-gather/, redfish-gather/)은 제거됨.
# 프로젝트 루트의 ansible.cfg가 callback_plugins = ./callback_plugins 로 이 파일을 참조한다.
__metaclass__ = type

import json
import os
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

# ── envelope 보충용 상수 ────────────────────────────────────────────────────
# 채널 → (target_type, collection_method). 정본은 각 site.yml 의 OUTPUT meta 다
#   os-gather/site.yml:321-322 / esxi-gather/site.yml / redfish-gather/site.yml.
_CHANNEL_ENVELOPE = {
    'os':      ('os', 'agent'),
    'esxi':    ('esxi', 'vsphere_api'),
    'redfish': ('redfish', 'redfish_api'),
}

# 플레이북 파일이 있는 디렉터리 이름 → 채널. 진단(_diagnosis.details.channel)을 한 번도
# 관측하지 못했을 때만 쓰는 최후 수단이다.
_PLAYBOOK_DIR_CHANNEL = {
    'os-gather':      'os',
    'esxi-gather':    'esxi',
    'redfish-gather': 'redfish',
}

# 대상 호스트로의 연결이 필요 없는(컨트롤러에서만 도는) 액션.
# 이런 태스크가 성공해도 "대상에 인증했다"는 증거가 되지 못한다.
_CONNECTIONLESS_ACTIONS = frozenset({
    'set_fact', 'debug', 'assert', 'fail', 'meta', 'add_host', 'group_by',
    'include', 'include_tasks', 'import_tasks', 'include_vars',
    'include_role', 'import_role', 'import_playbook', 'pause',
    # 항상 controller 에서 도는 이 저장소의 커스텀 모듈
    'precheck_bundle', 'redfish_gather',
})

_LOCAL_CONNECTIONS = frozenset({'local', 'ansible.builtin.local'})
_LOCAL_DELEGATES = frozenset({'localhost', '127.0.0.1', '::1'})

# 사용자에게 그대로 보이는 문장 (Portal 실패 Grid).
#
# 2026-08-11 (Phase 6-B 통합): 이 파일이 문구를 **새로 정의하지 않는다.**
#   문자열 정본은 두 곳이며 글자까지 같아야 한다:
#     - common/vars/failure_reasons.yml      (Ansible rescue 가 참조)
#     - common/library/precheck_bundle.py    (REASON_* — Python 정본)
#   콜백 플러그인은 Ansible 이 자체 로더로 올리므로 위 모듈을 import 할 수 없다.
#   그래서 값을 복제하되, drift 는 테스트가 막는다
#   (tests/unit/test_callback_envelope_reconcile.py::TestCanonicalReasonsDoNotDrift).
#
#   통합 전에는 이 자리에 표준 5 문장에 없는 문장 4종이 따로 있었고, errors[].message 가
#   diagnosis.failure_reason 과 다른 문장을 담고 있었다. 보충된 envelope 만 Portal 에서
#   다른 어휘로 보이게 되므로 정본 문구로 맞춘다.

# 표준 4번 — 자격증명 단계 실패 (접속 자체를 확인하지 못한 경우 포함).
_REASON_CREDENTIAL_FAILED = (
    '대상에 접속할 수 없습니다. 자격증명과 계정 권한을 확인하세요.'
)
# 표준 5번 — 접속은 확인됐고 수집에서 실패했다.
_REASON_GATHER_FAILED = (
    '대상 접속은 확인됐지만 정보 수집에 실패했습니다. 대상 상태와 수집 로그를 확인하세요.'
)
# 결과 객체 자체를 만들지 못한 경우. site.yml 3종의 always 블록 fallback 과 **같은 문장**이다
# (표준 5 문장에는 없는 6번째 자리 — 정본은 각 site.yml 의 always 블록).
_REASON_NO_OUTPUT = '수집 결과를 생성하지 못했습니다. 실행 로그를 확인하세요.'


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
        # ANSIBLE_JSON_OUTPUT_FILE 이 set 되면 OUTPUT JSON 을 그 파일에도 append.
        # Plugin step (ansiblePlaybook) 에서 stdout capture 가 어려운 경우 사용.
        # stdout 출력은 그대로 유지 (호환성).
        self._output_file = os.getenv('ANSIBLE_JSON_OUTPUT_FILE', '').strip()
        # envelope 보충 상태 — 호스트명 → 관측 컨텍스트
        self._hosts = {}
        self._playbook_channel = None
        self._reconcile = not _is_truthy(os.getenv('JSON_ONLY_NO_RECONCILE', ''))

    # ── 내부 유틸 ────────────────────────────────────────────────────────────

    def _emit(self, data, file=None):
        """dict/list/str → compact JSON → stdout (또는 file).

        문자열 입력은 JSON 파싱 시도 후 실패하면 문자열 그대로 출력 (호출자 호환성).
        파싱 실패 시 JSON_ONLY_DEBUG=1 환경변수로 stderr 경고 활성화 (디버그 가시성).
        """
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
            # 비-JSON-직렬화 객체(datetime / Ansible 객체 등)가 섞이면 callback 전체가 죽어
            # OUTPUT 이 통째로 소실된다 → str fallback 으로 graceful (Round 2 #0/#9).
            line = json.dumps(str(data), ensure_ascii=False, separators=(',', ':'))
        print(line, file=target, flush=True)
        # OUTPUT 결과를 파일로도 기록 (stdout target 일 때만, stderr 결과는 제외)
        if self._output_file and target is sys.stdout:
            try:
                with open(self._output_file, 'a', encoding='utf-8') as fh:
                    fh.write(line + '\n')
            except (OSError, IOError) as e:
                # 파일 쓰기 실패: stdout 은 정상이라 callback 흐름은 유지하되, 파일 소비자(다운스트림)
                # 가 빈 결과를 받는 silent data-loss 를 stderr 로 가시화 (Round 15 observability).
                # stderr 는 stdout JSON 과 분리되어 호출자 파싱에 영향 없음.
                sys.stderr.write(
                    '[json_only] WARNING: OUTPUT 파일 쓰기 실패 ({}): {}\n'.format(
                        self._output_file, type(e).__name__)
                )

    def _emit_error(self, error_type, message, host=None, task=None):
        payload = {
            'error_type': error_type,
            'message':    str(message),
        }
        if host:
            payload['host'] = host
        if task:
            payload['task'] = task
        self._emit(payload, file=sys.stderr)

    # ── 호스트 lifecycle 추적 (envelope 보충용) ──────────────────────────────

    @staticmethod
    def _task_name(result):
        # ansible-core 2.19+ 는 공개 프로퍼티 `task` 를 권장한다 (`_task` 는 deprecated alias).
        task = getattr(result, 'task', None) or getattr(result, '_task', None)
        return getattr(task, 'name', None)

    @staticmethod
    def _task_fields(result):
        """태스크 속성 매핑. `no_log` 여도 태스크 속성 자체는 검열되지 않는다."""
        fields = getattr(result, 'task_fields', None)
        if not hasattr(fields, 'get'):
            fields = getattr(result, '_task_fields', None)
        return fields if hasattr(fields, 'get') else {}

    @staticmethod
    def _host_name(result):
        host = getattr(result, 'host', None) or getattr(result, '_host', None)
        try:
            return host.get_name()
        except Exception:                                   # noqa: BLE001
            return str(host) if host is not None else ''

    @staticmethod
    def _host_vars(result):
        host = getattr(result, 'host', None) or getattr(result, '_host', None)
        try:
            hv = host.get_vars()
        except Exception:                                   # noqa: BLE001
            return {}
        return hv if hasattr(hv, 'get') else {}

    @staticmethod
    def _plain(value):
        """Ansible 고유 타입(AnsibleUnicode 등)을 순수 파이썬 값으로 정규화 + 스냅샷."""
        try:
            return json.loads(json.dumps(value, default=str))
        except (TypeError, ValueError):
            return None

    def _ctx(self, host_name):
        ctx = self._hosts.get(host_name)
        if ctx is None:
            ctx = {
                'emitted':      False,   # envelope 을 이미 냈는가
                'diagnosis':    None,    # precheck 가 만든 진단 (관측 사실)
                'target_type':  None,
                'collection_method': None,
                'ip':           None,
                'ip_checked':   False,   # 인벤토리 ansible_host 조회를 이미 시도했는가
                # 대상 연결로 실제 원격 태스크가 성공한 적이 있는가.
                # 성공했다면 그 연결의 인증은 통과했다는 뜻이다 (관측된 사실).
                'auth_proven':  False,
                # 치명 unreachable (ignore_unreachable=false → 호스트가 play 에서 제거됨)
                'lost':         False,
            }
            self._hosts[host_name] = ctx
        return ctx

    def _track(self, result, ok=False, unreachable=False):
        """모든 runner 이벤트에서 호출. 예외가 나도 본 출력 흐름을 막지 않는다.

        태스크 × 호스트마다 도는 경로라, 이미 확정된 값은 다시 조회하지 않는다.
        """
        if not self._reconcile:
            return
        try:
            ctx = self._ctx(self._host_name(result))
            fields = self._task_fields(result)

            if unreachable and not fields.get('ignore_unreachable'):
                # ignore_unreachable=true 인 태스크(자격 probe 등)는 호스트를 잃지 않는다.
                ctx['lost'] = True

            if ok:
                self._absorb_facts(ctx, result)
                if not ctx['auth_proven'] and self._proves_authentication(result, fields):
                    ctx['auth_proven'] = True

            if not ctx['ip_checked']:
                ctx['ip_checked'] = True
                if ctx['ip'] is None:
                    ip = self._host_vars(result).get('ansible_host')
                    if ip:
                        ctx['ip'] = str(ip)
        except Exception:                                   # noqa: BLE001
            pass

    def _absorb_facts(self, ctx, result):
        """set_fact 결과에서 envelope 조립에 필요한 관측값만 골라 보관."""
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
        for key, slot in (('_out_target_type', 'target_type'),
                          ('_out_collection_method', 'collection_method'),
                          ('_out_ip', 'ip')):
            if facts.get(key):
                ctx[slot] = str(facts[key])

    def _proves_authentication(self, result, fields):
        """이 성공 결과가 '대상 호스트에 실제로 접속·인증했다'를 증명하는가.

        핵심 근거: **인증 실패는 ok 가 아니라 unreachable 이다.** ssh 커넥션은 rc=255 를
        `AnsibleConnectionFailure` 로 올리고(`ansible/plugins/connection/ssh.py`), winrm 도
        401 을 같은 예외로 올린다. 따라서 대상 연결로 돌아간 태스크가 `ok` 로 끝났다면
        그 연결의 인증은 통과한 것이다. `failed_when: false` 는 **명령 실패**만 가리며
        연결 실패를 ok 로 바꾸지 못하므로, 자격 probe 의 ok 도 그대로 증거가 된다.

        판단은 전부 **구조화된 태스크/호스트 속성**으로만 한다 (오류 문자열 파싱 없음).
        제외 대상은 애초에 대상 연결을 쓰지 않는 태스크뿐이다.
          - 연결이 필요 없는 액션(set_fact / debug / meta ...)      → 증거 아님
          - `delegate_to: localhost` 로 controller 에서 돈 태스크    → 증거 아님
          - `connection: local` (포트 감지 PLAY / esxi / redfish)    → 증거 아님
        """
        action = str(fields.get('action') or '').rsplit('.', 1)[-1]
        if not action or action in _CONNECTIONLESS_ACTIONS:
            return False
        delegate = fields.get('delegate_to')
        if delegate and str(delegate) in _LOCAL_DELEGATES:
            return False
        # host_vars 조회는 위 값싼 검사를 모두 통과했을 때만 (태스크 × 호스트마다 도는 경로).
        connection = self._host_vars(result).get('ansible_connection') or fields.get('connection')
        if not connection or str(connection) in _LOCAL_CONNECTIONS:
            # 연결 종류를 확정하지 못하면 증거로 삼지 않는다 (보수적).
            return False
        return True

    # ── 캡처 대상 태스크 처리 ────────────────────────────────────────────────

    def v2_runner_on_ok(self, result):
        self._track(result, ok=True)
        if self._task_name(result) != self._output_task:
            return
        res = result._result
        if 'msg' in res:
            self._emit(res['msg'])
        elif 'ansible_facts' in res:
            # set_fact 결과가 OUTPUT 태스크에 연결된 경우
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
        except Exception:                                   # noqa: BLE001
            pass

    # ── envelope 보충 (요청 대상 1개 = envelope 1개 보장) ────────────────────

    def _resolve_channel(self, ctx):
        details = (ctx.get('diagnosis') or {}).get('details')
        if isinstance(details, dict) and details.get('channel') in _CHANNEL_ENVELOPE:
            return details['channel']
        return self._playbook_channel

    def _build_fallback_envelope(self, host_name, ctx):
        """관측된 사실만으로 13 필드 envelope 을 만든다.

        stage 매핑 근거
        ---------------
        1) precheck 가 이미 실패로 끝난 진단을 갖고 있으면 **그대로 보존**한다
           (실행이 멈춘 지점이 precheck 이며, 그 값은 실제 관측이다).
        2) 치명 unreachable 을 관측했고, 그 전에 대상 연결로 성공한 태스크가 있었다면
           인증은 통과한 뒤 수집 도중 끊긴 것이다 → gather / GATHER_FAILED /
           auth_success=true (`_proves_authentication` 참조).
        3) 치명 unreachable 을 관측했지만 그런 증거가 없으면 접속 자체를 확인하지 못한
           것이다 → auth / AUTH_PROBE_FAILED / auth_success=null.
           (인증 '거부'를 관측한 것이 아니므로 false 로 확정하지 않는다.)
        4) unreachable 도 아닌데 OUTPUT 이 없으면 결과 객체 생성 실패로 본다
           → fallback / OUTPUT_BUILD_FAILED. site.yml always 블록과 같은 값이다.
        새 failure_stage / failure_code / envelope 필드는 만들지 않는다.
        """
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

        # errors[].message 는 diagnosis.failure_reason 을 **그대로 복사**한다.
        # Portal 실패 Grid 가 읽는 값이 errors[].message 이고, 두 값이 다른 문장을 담으면
        # 사용자가 보는 문장과 시스템이 보는 문장이 갈라진다
        # (정본 규칙: common/tasks/normalize/build_failed_output.yml §24).
        # 기술 정보는 message 가 아니라 detail 에만 남긴다 (§34).
        if observed.get('failure_stage'):
            # (1) precheck 진단 보존
            diagnosis = dict(observed)
            diagnosis['details'] = details
            if not (isinstance(diagnosis.get('failure_reason'), str)
                    and diagnosis['failure_reason'].strip()):
                diagnosis['failure_reason'] = _REASON_NO_OUTPUT
            err_section = 'precheck'
            err_detail = 'envelope reconciled by callback; precheck diagnosis preserved'
        elif ctx.get('lost') and ctx.get('auth_proven'):
            # (2) 인증 통과 후 수집 도중 연결 끊김
            diagnosis = self._diagnosis(observed, details, True,
                                        'gather', 'GATHER_FAILED', _REASON_GATHER_FAILED)
            err_section = 'gather'
            err_detail = ('envelope reconciled by callback; host became unreachable '
                          'after an authenticated task succeeded')
        elif ctx.get('lost'):
            # (3) 접속 자체를 확인하지 못함
            diagnosis = self._diagnosis(observed, details, None,
                                        'auth', 'AUTH_PROBE_FAILED', _REASON_CREDENTIAL_FAILED)
            err_section = 'auth'
            err_detail = ('envelope reconciled by callback; host unreachable with no '
                          'evidence of a successful authenticated task')
        else:
            # (4) OUTPUT 이 실행되지 않음
            diagnosis = self._diagnosis(observed, details, observed.get('auth_success'),
                                        'fallback', 'OUTPUT_BUILD_FAILED', _REASON_NO_OUTPUT)
            err_section = 'gather'
            err_detail = 'envelope reconciled by callback; OUTPUT task did not run'

        err_message = diagnosis['failure_reason']

        return {
            'schema_version':    '1',
            'target_type':       target_type,
            'collection_method': collection_method,
            'ip':                ip,
            'hostname':          ip,
            'vendor':            None,
            'status':            'failed',
            'sections':          {},
            'diagnosis':         diagnosis,
            'meta':              {},
            'correlation':       {},
            'errors':            [{'section': err_section,
                                   'message': err_message,
                                   'detail':  err_detail}],
            'data':              {},
        }

    @staticmethod
    def _diagnosis(observed, details, auth_success, stage, code, reason):
        """precheck 가 관측한 앞 단계 결과는 보존하고, 뒷 단계만 채운다."""
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

    def _reconcile_missing_envelopes(self, stats):
        """플레이북 종료 시점에 envelope 을 하나도 내지 못한 호스트를 보충한다."""
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
            envelope = self._build_fallback_envelope(host_name, ctx)
            self._emit(envelope)
            ctx['emitted'] = True
            # 관측 가시성 — stdout JSON 과 분리된 stderr 로만 남긴다.
            self._emit_error(
                error_type='envelope_reconciled',
                message=envelope['diagnosis']['failure_code'],
                host=host_name,
            )
        self._hosts = {}

    # ── 억제할 이벤트 (아무것도 출력하지 않음) ──────────────────────────────

    def v2_playbook_on_start(self, playbook):
        # 진단(_diagnosis.details.channel)을 한 번도 관측하지 못한 경우의 최후 수단.
        try:
            path = getattr(playbook, '_file_name', '') or ''
            parent = os.path.basename(os.path.dirname(os.path.abspath(path)))
            self._playbook_channel = _PLAYBOOK_DIR_CHANNEL.get(parent)
        except Exception:                                   # noqa: BLE001
            self._playbook_channel = None

    def v2_playbook_on_stats(self, stats):
        try:
            self._reconcile_missing_envelopes(stats)
        except Exception as e:                              # noqa: BLE001
            # 보충 실패가 정상 출력까지 죽이면 안 된다. stderr 로만 알린다.
            self._emit_error(error_type='reconcile_failed', message=type(e).__name__)

    def v2_playbook_on_play_start(self, play):            pass
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
