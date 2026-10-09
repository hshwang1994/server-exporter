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

# ── envelope 보충용 상수 ────────────────────────────────────────────────────
# 채널 → (target_type, collection_method). 정본은 각 site.yml 의 OUTPUT meta 다
#   os-gather/site.yml:321-322 / esxi-gather/site.yml / redfish-gather/site.yml.
_CHANNEL_ENVELOPE = {
    'os':      ('os', 'agent'),
    'esxi':    ('esxi', 'vsphere_api'),
    'redfish': ('redfish', 'redfish_api'),
}

# ── 실패 envelope shape 정본 복제 (2026-10-03, Plan §7-7 / N2) ───────────────────────
# 콜백이 보충하는 envelope 은 rescue 경로(common/tasks/normalize/build_failed_output.yml)·site.yml always
# 와 **같은 모양**이어야 한다 — 호출자가 실패 종류에 따라 다른 모양을 보지 않는다. hostname 은 IP 로
# 대체하지 않는다(null — 2026-09-03 B-01). 아래는 정본의 수동 복제이며 tests/unit/test_json_only_fallback_shape.py
# 가 drift 를 잡는다.
#   sections    : schema 11 섹션 — 채널 지원 섹션(common/vars/supported_sections.yml channel_sections)은 failed, 나머지 not_supported
#   meta        : common/tasks/normalize/build_meta.yml 의 6 키 (값 null)
#   correlation : common/tasks/normalize/build_correlation.yml 의 4 키 (host_ip 만 채움; redfish 는 bmc_ip 도 IP)
#   data        : common/tasks/normalize/init_fragments.yml 의 _merged_data 뼈대
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
    """실패 envelope 의 sections / meta / correlation / data — 정본과 같은 모양, 호출마다 새 객체."""
    supported = set(_CHANNEL_SECTIONS.get(channel, ()))
    return {
        'sections':    {s: ('failed' if s in supported else 'not_supported') for s in _ALL_SECTIONS},
        'meta':        {k: None for k in _META_KEYS},
        'correlation': {k: (ip if k == 'host_ip' or (k == 'bmc_ip' and channel == 'redfish') else None)
                        for k in _CORRELATION_KEYS},
        'data':        json.loads(json.dumps(_DATA_SKELETON)),
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
# 이 파일은 문구를 **새로 정의하지 않는다.** 정본은 common/vars/failure_reasons.yml 의
# `_fr_catalog` 이고, 여기에는 envelope 보충 경로가 내는 키만 글자 그대로 복제한다.
# 콜백 플러그인은 Ansible 이 자체 로더로 올리므로 정본을 import 할 수 없다.
# drift 는 테스트가 막는다 (tests/e2e/test_errors_message_contract.py).
#
# 2026-09-21: 문장을 (키, 채널) 로 고른다. 종전에는 "연결이 끊겼다" 와 "인증을 못 했다" 가
#   채널 구분 없이 한 문장씩이었다. 채널을 모르면 default 문장을 쓴다.
#   `{loc}` 는 관측한 실행 위치(_cred_location)로 채운다 — 없으면 '미지정'.
_FAILURE_REASON_CATALOG = {
    # 대상 연결이 끊겼고, 그 전에 인증에 성공했다는 증거가 없다.
    'auth_unconfirmed': {
        'os': '해당 위치({loc})의 Vault 계정으로 대상 OS에 로그인하지 못했습니다.',
        'esxi': '해당 위치({loc})의 Vault 계정으로 대상 ESXi에 로그인하지 못했습니다.',
        'redfish': '개더링 표준 계정으로 대상 Redfish에 인증하지 못했습니다.',
        'default': '해당 위치({loc})의 Vault 계정으로 대상에 로그인하지 못했습니다.',
    },
    # 위와 같지만 Vault 에 계정이 0개였다 (계정 없이 접속을 시도했다).
    'loc_vault_no_account': {
        'os': '해당 위치({loc})의 Vault에 OS용 계정이 없습니다.',
        'esxi': '해당 위치({loc})의 Vault에 ESXi용 계정이 없습니다.',
        'default': '해당 위치({loc})의 Vault에 계정이 없습니다.',
    },
    # 인증된 작업이 성공한 뒤 대상이 unreachable 이 됐다.
    'gather_connection_lost': {
        'default': '정보 수집 중 대상 서버와 연결이 끊겼습니다.',
    },
    # 결과 객체 자체를 만들지 못했다. site.yml 3종 always 블록 fallback 과 **같은 문장**이다.
    'output_build_failed': {
        'default': '개더링 프로젝트에서 수집 결과를 만들지 못했습니다.',
    },
}

# {loc} 표시값 규칙 — filter_plugins/failure_reason.py display_location() 과 같아야 한다
# (tests/unit/test_failure_reason_filter.py 가 두 구현의 결과를 대조한다).
_LOC_UNSAFE = re.compile(r'[^A-Za-z0-9_.-]')
_LOC_MAX_LEN = 40
_LOC_EMPTY = '미지정'


def _display_location(loc):
    if loc is None:
        return _LOC_EMPTY
    text = _LOC_UNSAFE.sub('', str(loc).strip())[:_LOC_MAX_LEN]
    return text or _LOC_EMPTY


def _reason(key, channel=None, loc=None):
    """보충 경로 전용 문장 선택. 채널 문장이 없으면 default."""
    entry = _FAILURE_REASON_CATALOG[key]
    text = entry.get(channel) if channel else None
    if text is None:
        text = entry['default']
    return text.replace('{loc}', _display_location(loc))


_REASON_NO_OUTPUT = _reason('output_build_failed')

# CHECKPOINT(Add-on 전 조립본)로 보충할 때 붙이는 오류 1건의 문장 (2026-10-05 F01).
# scripts/finalize_gather_output.py 의 ADDON_INTERRUPTED · EMIT_FAILED 와 글자까지 같다 — 같은 상황을 콜백이 만나든
# Layer A 가 만나든 사용자는 같은 문장을 본다. drift 는 tests/unit/test_callback_envelope_reconcile.py 가 막는다.
_CHECKPOINT_ADDON_INTERRUPTED = '추가 수집 중 처리가 중단되어 추가 수집 결과가 없습니다. 기본 수집 결과는 그대로입니다.'
_CHECKPOINT_EMIT_FAILED = '수집은 끝났지만 결과를 내보내는 단계에서 중단되었습니다. 기본 수집 결과는 그대로입니다.'

# 복제 이유 (YAML 런타임 로드를 채택하지 않은 근거, 2026-08-12)
# ---------------------------------------------------------------
# 정본 YAML 을 import 시점에 읽어 오면 파일 부재 / 권한 / 파싱 오류 어느 하나에도
# 모듈 import 가 터진다. stdout_callback 은 import 실패 시 플러그인 자체가 올라가지 않고,
# 그러면 **모든 대상의 envelope 이 stdout 에 하나도 나가지 않는다**(Portal 수신 전량 파손).
# 즉 문구 동기화라는 작은 이득을 위해 출력 경로 전체를 단일 장애점으로 만드는 교환이다.
# 그래서 값은 복제하고, 정본과의 drift 는 테스트가 막는다
# (tests/unit/test_callback_envelope_reconcile.py::TestCanonicalReasonsDoNotDrift).


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
        # 2026-10-03 (Plan §6-1 D4/D8): 강제 종료 뒤에는 on_stats 가 돌지 않으므로 host 전이를 **파일 이벤트**로 남긴다.
        #   progress   : host 당 append JSONL (first_seen / precheck / cred_load / auth_proven / checkpoint / addon_started /
        #                addon_done / emitted / lost) — 전체 snapshot 재기록 없음(H²×T 비용 회피), 줄은 짧다.
        #   checkpoint : `CHECKPOINT` 태스크(Add-on 전 조립본 envelope)를 host 당 1줄 append (flush+fsync).
        #   manifest   : Jenkins 가 쓴 접수 집합 — 실행마다 한 번, play 범위로 좁히기 전의 전체 inventory 와 대조해 다르면 stderr 로 알린다
        #                (대조용, 정본은 manifest).
        #   Layer A(scripts/finalize_gather_output.py)가 이 파일들로 누락 envelope 을 보충한다.
        self._progress_file = os.getenv('ANSIBLE_JSON_PROGRESS_FILE', '').strip()
        self._checkpoint_file = os.getenv('ANSIBLE_JSON_CHECKPOINT_FILE', '').strip()
        self._manifest_file = os.getenv('ANSIBLE_JSON_MANIFEST_FILE', '').strip()
        self._manifest_compared = False
        self._checkpoint_task = os.getenv('ANSIBLE_JSON_CHECKPOINT_TASK', 'CHECKPOINT')
        self._addon_start_task = 'ADDON_START'
        self._addon_done_task = 'ADDON_DONE'
        # envelope 보충 상태 — 호스트명 → 관측 컨텍스트
        self._hosts = {}
        self._playbook_channel = None
        self._reconcile = not _is_truthy(os.getenv('JSON_ONLY_NO_RECONCILE', ''))
        if not self._reconcile:
            # 비상 스위치가 켜지면 envelope 소실 방지 장치가 통째로 꺼진다. 그 사실이
            # 아무 데도 안 남으면 "대상 2개를 넣었는데 결과가 1개" 를 나중에 코드가 아니라
            # 추측으로 찾게 된다. stdout(호출자가 파싱하는 면)은 건드리지 않고
            # stderr 로만 1줄 남긴다 — envelope 개수/내용에 영향 0.
            sys.stderr.write(
                '[json_only] NOTICE: JSON_ONLY_NO_RECONCILE 이 켜져 있어 envelope 보충이 '
                '꺼졌다. 수집 도중 대상이 unreachable 이 되면 그 대상의 결과가 누락된다.\n'
            )

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
                    fh.flush()
                    os.fsync(fh.fileno())     # 강제 종료 직전의 줄도 디스크에 남긴다 (D4)
            except (OSError, IOError) as e:
                # 파일 쓰기 실패: stdout 은 정상이라 callback 흐름은 유지하되, 파일 소비자(다운스트림)
                # 가 빈 결과를 받는 silent data-loss 를 stderr 로 가시화 (Round 15 observability).
                # stderr 는 stdout JSON 과 분리되어 호출자 파싱에 영향 없음.
                sys.stderr.write(
                    '[json_only] WARNING: OUTPUT 파일 쓰기 실패 ({}): {}\n'.format(
                        self._output_file, type(e).__name__)
                )

    def _emit_error(self, error_type, message, host=None, task=None):
        """진단을 stderr 에 **평문 한 줄**로 남긴다.

        2026-08-12: 종전에는 이 함수가 stderr 로 `message` 키를 가진 JSON 을 냈다.
        메인 `Jenkinsfile` 은 호출자가 console log 를 **라인 단위로 파싱**하는 전제로
        동작하는데(Jenkinsfile:245-246), stdout envelope 과 키 이름이 겹치는 JSON 이
        같은 로그에 섞이면 진단 줄이 결과 envelope 으로 오인될 수 있다.
        그래서 이 파일이 이미 쓰던 `[json_only] ...` 평문 형식으로 통일한다.
        stdout 에 나가는 것은 오직 envelope JSON 뿐이라는 성질을 유지하기 위함이다.
        """
        line = '[json_only] {}: {}'.format(error_type, message)
        context = []
        if host:
            context.append('host={}'.format(host))
        if task:
            context.append('task={}'.format(task))
        if context:
            line += ' ({})'.format(', '.join(context))
        sys.stderr.write(line + '\n')

    # ── 진행 이벤트 / checkpoint 파일 (Layer A 입력) ───────────────────────────

    @staticmethod
    def _now_iso():
        return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')

    @staticmethod
    def _json_line(data):
        """_emit 과 같은 변환 — 문자열은 JSON 으로 파싱 시도, 실패하면 문자열 그대로."""
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
        """host 전이 이벤트 1줄 append. 실패해도 본 흐름을 막지 않는다. detail 은 160자로 자른다."""
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
        except Exception as e:                              # noqa: BLE001
            sys.stderr.write('[json_only] WARNING: progress 기록 실패 ({}): {}\n'.format(
                self._progress_file, type(e).__name__))

    def _checkpoint(self, result):
        """CHECKPOINT 태스크의 msg(조립된 envelope)를 checkpoint 파일에 append (flush+fsync) + progress.

        2026-10-05 (F01): 같은 envelope 을 host 컨텍스트에도 둔다. 플레이북이 정상 종료했는데 OUTPUT 이 나가지 않은 host
        (OUTPUT 태스크 실패 · 기록 실패)를 on_stats 가 보충할 때, 기본 실패 envelope 대신 이 조립본을 쓴다 — 종전에는
        보충 줄이 OUTPUT 출처로 Layer A/B 에서 CHECKPOINT 보다 우선해 이미 수집한 값을 가렸다.
        """
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
        except Exception:                                   # noqa: BLE001
            return None

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
                # 관측된 **기술 근거** (사용자 문장 아님 — errors[].detail 로만 나간다).
                #   fail_detail  : precheck 가 포트별로 실제 관측한 원본 오류
                #   fail_message : rescue 가 남긴 실패 태스크/예외 요약
                'fail_detail':  None,
                'fail_message': None,
                # 2026-09-21: 보충 문장에 필요한 관측값 (Secret 아님).
                #   location          : 실행 위치 (문장의 {loc})
                #   cred_load_outcome : Vault 적재 결과 (empty_accounts 면 '계정 없음' 문장)
                'location':          None,
                'cred_load_outcome': None,
            }
            self._hosts[host_name] = ctx
            ctx['_first_seen_pending'] = True     # ip 를 확정한 뒤 _track 이 first_seen 을 기록한다 (Phase 5 실측: 여기서 쓰면 ip 가 null)
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

            # ip 는 첫 이벤트 전에 확정한다 — 뒤의 progress 줄(precheck/lost/…)이 ip 를 싣기 위해서다.
            if not ctx['ip_checked']:
                ctx['ip_checked'] = True
                if ctx['ip'] is None:
                    ip = self._host_vars(result).get('ansible_host')
                    if ip:
                        ctx['ip'] = str(ip)
            if ctx.pop('_first_seen_pending', False):
                self._progress(self._host_name(result), 'first_seen', task=self._task_name(result))

            if unreachable and not fields.get('ignore_unreachable'):
                # ignore_unreachable=true 인 태스크(자격 probe 등)는 호스트를 잃지 않는다.
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
                # precheck 진단은 Layer A 가 (1) 분기(진단 보존)에 쓴다 — 이 이벤트만 dict 를 싣는다.
                self._progress(self._host_name(result), 'precheck', task=self._task_name(result), diagnosis=diag)
        for key, slot in (('_out_target_type', 'target_type'),
                          ('_out_collection_method', 'collection_method'),
                          ('_out_ip', 'ip'),
                          # precheck / rescue 가 남긴 기술 근거. 정상 경로에서는
                          # build_failed_output.yml:64-74 가 errors[].detail 로 싣는데,
                          # 보충 경로는 그 태스크를 못 거치므로 여기서 직접 붙든다.
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
            self._progress(self._host_name(result), 'emitted', task=self._task_name(result))
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
            # precheck 가 포트별로 실제 관측한 오류를 앞에 둔다. 고정 문자열만 남기면
            # "어느 포트에서 무엇을 봤는가" 라는 유일한 1차 증거가 사라진다.
            err_detail = self._compose_detail(
                ctx, 'envelope reconciled by callback; precheck diagnosis preserved')
        elif ctx.get('lost') and ctx.get('auth_proven'):
            # (2) 인증 통과 후 수집 도중 연결 끊김
            diagnosis = self._diagnosis(observed, details, True,
                                        'gather', 'GATHER_FAILED',
                                        _reason('gather_connection_lost'))
            err_section = 'gather'
            err_detail = ('envelope reconciled by callback; host became unreachable '
                          'after an authenticated task succeeded')
        elif ctx.get('lost'):
            # (3) 접속 자체를 확인하지 못함. Vault 에 계정이 0개였으면(계정 없이 시도) 그 사실을
            #     알린다 — 관리자가 할 일이 대상 계정 점검이 아니라 Vault 계정 배치다.
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
            # (4) OUTPUT 이 실행되지 않음
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
            'hostname':          None,           # IP 로 대체하지 않는다 (2026-09-03 B-01 / 2026-10-03 N2)
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
        """관측된 기술 근거 + 콜백이 덧붙이는 고정 문자열 → errors[].detail 문자열.

        결합 규칙(' | ')은 정상 경로인 `build_failed_output.yml:64-74` 와 같다.
        사용자 문장은 message 에만, 기술 근거는 detail 에만 둔다.
        """
        parts = []
        for slot in ('fail_detail', 'fail_message'):
            value = ctx.get(slot)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        parts.append(fixed)
        return ' | '.join(parts)

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

    def _minimal_envelope(self, host_name):
        """조립이 실패했을 때의 최후 수단 envelope.

        관측값 해석을 전부 포기하고 분기 (4) 값으로 고정한다
        (fallback / OUTPUT_BUILD_FAILED / `_REASON_NO_OUTPUT`). "결과 객체를 만들지
        못했다" 는 상황 그 자체이므로 의미가 맞다. 13 필드의 **순서와 구성은 정본과 같다**
        (rule 13 R5 / build_output.yml).
        """
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
        """CHECKPOINT 조립본으로 보충 — status · sections · diagnosis · data 는 그대로, 원인 오류 1건만 붙인다.

        Layer A 의 envelope_from_checkpoint 와 같은 규칙이다(문장 · section 같음). detail 은 'finalized from checkpoint;'
        로 시작해 출처를 남긴다. 진짜 최종 failed OUTPUT 은 이 경로에 오지 않는다(emitted 가 이미 true).
        """
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
        """플레이북 종료 시점에 envelope 을 하나도 내지 못한 호스트를 보충한다.

        CHECKPOINT 조립본이 있으면 그것으로(이미 수집한 값 보존), 없으면 관측 사실로 만든 실패 envelope 으로 보충한다.
        """
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
            # ── per-host 격리 ────────────────────────────────────────────────
            # 종전에는 이 루프 전체가 v2_playbook_on_stats 의 try 하나에만 감싸여 있어,
            # 첫 호스트 처리 중 예외가 나면 **남은 미방출 호스트 전부**가 envelope 을
            # 잃었다 (보충 장치가 오히려 대량 소실 지점이 된다). 호스트 하나의 실패는
            # 그 호스트로 가둔다. 바깥 try 는 2중 방어로 그대로 둔다.
            source = 'observed'
            try:
                checkpoint_env = ctx.get('checkpoint_env')
                if isinstance(checkpoint_env, dict):
                    envelope = self._envelope_from_checkpoint(checkpoint_env, ctx)
                    source = 'checkpoint'
                else:
                    envelope = self._build_fallback_envelope(host_name, ctx)
            except Exception as e:                          # noqa: BLE001
                envelope = self._minimal_envelope(host_name)
                source = 'minimal'
                sys.stderr.write(
                    '[json_only] WARNING: envelope 조립 실패 — 최소 envelope 으로 대체 '
                    '(host={}, reason={})\n'.format(host_name, type(e).__name__))
            try:
                self._emit(envelope)
                ctx['emitted'] = True
                self._progress(host_name, 'reconciled', source=source)
                # 관측 가시성 — stdout JSON 과 분리된 stderr 로만 남긴다.
                diagnosis = envelope.get('diagnosis') if isinstance(envelope.get('diagnosis'), dict) else {}
                self._emit_error(
                    error_type='envelope_reconciled',
                    message='{} (source={})'.format(diagnosis.get('failure_code') or envelope.get('status'), source),
                    host=host_name,
                )
            except Exception as e:                          # noqa: BLE001
                sys.stderr.write(
                    '[json_only] WARNING: envelope 보충 출력 실패 '
                    '(host={}, reason={})\n'.format(host_name, type(e).__name__))
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

    def v2_playbook_on_play_start(self, play):
        """play 의 inventory host 를 1회 기록한다 (manifest 대조용 — 정본은 Jenkins 가 쓴 gather_manifest.json)."""
        if not self._progress_file and not self._manifest_file:
            return
        try:
            vm = play.get_variable_manager()
            inv = getattr(vm, '_inventory', None)
            hosts = [h.get_name() for h in inv.get_hosts('all')] if inv is not None else None
        except Exception:                                   # noqa: BLE001
            hosts = None
        if hosts is None:
            return
        try:
            play_name = play.get_name()
        except Exception:                                   # noqa: BLE001
            play_name = None
        self._progress(None, 'inventory', task=play_name, hosts=hosts)
        # 접수 목록 대조는 실행마다 한 번, play 범위로 좁히기 전의 전체 inventory 로 한다. Ansible 은 play 를 시작할 때 inventory 를 그 play 의
        #   대상으로 좁히고(restrict_to_hosts), 이어서 하는 시도는 --limit 로 남은 대상만 돈다 — os-gather 의 linux · windows play 가 접수 목록의
        #   일부만 보는 것은 정상이다(2026-10-09 main #359 · #360: 정상 배치에서 play 마다 오경보). 위 진행 기록은 종전대로 play 범위다.
        if self._manifest_compared:
            return
        manifest = self._manifest_ips()
        if manifest is None:
            return
        try:
            full = [h.get_name() for h in inv.get_hosts('all', ignore_limits=True, ignore_restrictions=True)]
        except Exception:                                   # noqa: BLE001
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
