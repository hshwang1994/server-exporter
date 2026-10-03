#!/usr/bin/env python3
"""finalize_gather_output.py — Layer A finalizer: 요청 대상 1개 = 결과 envelope 1개 (2026-10-03, Plan §6-4 D3).

Gather stage 의 post{always} 에서 Agent 위에서 돈다. ansible-playbook 이 어떻게 끝났든(완료 · timeout INT · 준비 실패)
접수 manifest 의 모든 IP 에 대해 envelope 을 정확히 하나씩 가진 `gather_final.jsonl` 과 처리 보고 `gather_finalize_report.json`
을 만든다. Ansible 콜백(json_only)이 `on_stats` 에서 하던 보충은 강제 종료 뒤에는 돌지 않으므로, 그 자리를 **파일 증거**로 메운다.

입력 (workspace 안, 모두 선택이지만 manifest 는 필수)
  gather_manifest.json    Jenkins Validate 가 만든 접수 집합 {schema, build, channel, request, ips[]}
  gather_output.json      json_only 가 OUTPUT 태스크마다 append 한 envelope JSONL
  gather_checkpoint.jsonl json_only 가 CHECKPOINT(Add-on 전 조립본) 태스크마다 append 한 envelope JSONL
  gather_progress.jsonl   host 당 전이 이벤트 JSONL — {ts, host, ip, event, task, detail, diagnosis?, outcome?, location?}
                          event ∈ first_seen | precheck | cred_load | auth_proven | checkpoint | addon_started | addon_done | emitted | lost
  gather_rc.txt           ansible-playbook(또는 timeout) 의 rc

출력
  gather_final.jsonl          접수 순서대로 host 당 1줄 (OUTPUT 줄은 원문 그대로, 보충분만 새로 직렬화)
  gather_finalize_report.json accepted/kept/by_origin/filled/dropped/conflicts/truncated_tail/corrupt_lines/outcome/rc/exit_code

종료 코드: 0 정상 · 2 입력 손상이 있었으나 처리함(절단/손상 줄 드롭·보충) · 3 도구 실패(manifest 없음 · 쓰기 실패 등 — Layer B 가 raw 로 진행)

문장·shape 는 **정본 파일을 읽어** 쓴다(복제 없음): common/vars/failure_reasons.yml(_fr_catalog), common/vars/supported_sections.yml,
common/tasks/normalize/init_fragments.yml(_merged_data) · build_meta.yml · build_correlation.yml. 새 failure_stage/failure_code 는 만들지 않는다.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - Agent venv 에는 PyYAML 이 있다(ansible 의존성)
    yaml = None

ALL_SECTIONS = ('system', 'hardware', 'bmc', 'cpu', 'memory', 'storage', 'network',
                'firmware', 'users', 'power', 'thermal')
SECTION_VALUES = {'success', 'failed', 'not_supported'}
STATUS_VALUES = {'success', 'partial', 'failed'}
ENVELOPE_KEYS = ('schema_version', 'target_type', 'collection_method', 'ip', 'hostname', 'vendor', 'status',
                 'sections', 'diagnosis', 'meta', 'correlation', 'errors', 'data')
DIAGNOSIS_KEYS = ('reachable', 'port_open', 'protocol_supported', 'auth_success',
                  'failure_stage', 'failure_code', 'failure_reason', 'details')
CHANNEL_METHOD = {'os': 'agent', 'esxi': 'vsphere_api', 'redfish': 'redfish_api'}
MAX_CORRUPT_PREVIEW = 120

EXIT_OK, EXIT_DAMAGE, EXIT_TOOL = 0, 2, 3


class ToolFailure(Exception):
    pass


# ───────────────────────── 정본 로딩 ─────────────────────────

def _set_fact_value(tasks, var):
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        sf = t.get('ansible.builtin.set_fact') or t.get('set_fact') or {}
        if var in sf:
            return sf[var]
    raise ToolFailure(f'set_fact {var} 를 찾지 못함')


class Canon:
    """정본 YAML 에서 읽은 문장 · shape. 한 번 읽어 재사용."""

    def __init__(self, repo_root: Path):
        if yaml is None:
            raise ToolFailure('PyYAML 이 없다')
        root = Path(repo_root)
        try:
            fr = yaml.safe_load((root / 'common/vars/failure_reasons.yml').read_text(encoding='utf-8'))
            ss = yaml.safe_load((root / 'common/vars/supported_sections.yml').read_text(encoding='utf-8'))
            init = yaml.safe_load((root / 'common/tasks/normalize/init_fragments.yml').read_text(encoding='utf-8'))
            meta = yaml.safe_load((root / 'common/tasks/normalize/build_meta.yml').read_text(encoding='utf-8'))
            corr = yaml.safe_load((root / 'common/tasks/normalize/build_correlation.yml').read_text(encoding='utf-8'))
        except OSError as e:
            raise ToolFailure(f'정본 파일 읽기 실패: {e}') from e
        self.catalog = fr.get('_fr_catalog') or {}
        self.channel_sections = {k: list(v) for k, v in (ss.get('channel_sections') or {}).items()}
        self.all_sections = list(ss.get('all_sections') or ALL_SECTIONS)
        self.skeleton = _set_fact_value(init, '_merged_data')
        self.meta_keys = list(_set_fact_value(meta, '_meta'))
        self.corr_keys = list(_set_fact_value(corr, '_correlation'))

    def reason(self, key, channel=None, loc=None):
        entry = self.catalog.get(key) or {}
        text = entry.get(channel) if channel else None
        text = text or entry.get('default') or ''
        return str(text).replace('{loc}', str(loc) if loc else '미지정')

    def shape(self, channel, ip):
        supported = set(self.channel_sections.get(channel, ()))
        return {
            'sections': {s: ('failed' if s in supported else 'not_supported') for s in self.all_sections},
            'meta': {k: None for k in self.meta_keys},
            'correlation': {k: (ip if k == 'host_ip' or (k == 'bmc_ip' and channel == 'redfish') else None)
                            for k in self.corr_keys},
            'data': copy.deepcopy(self.skeleton),
        }


# ───────────────────────── 입력 파싱 ─────────────────────────

def read_jsonl(path: Path, report: dict, label: str):
    """JSONL → [(index, text, obj)]. 마지막 줄 절단(개행 없음 + 파싱 불가) 과 손상 줄은 report 에 남기고 건너뛴다."""
    rows = []
    if not path.is_file():
        return rows
    try:
        raw = path.read_text(encoding='utf-8', errors='replace')
    except OSError as e:
        raise ToolFailure(f'{label} 읽기 실패: {e}') from e
    if not raw:
        return rows
    lines = raw.split('\n')
    trailing_newline = raw.endswith('\n')
    if trailing_newline:
        lines = lines[:-1]
    for idx, line in enumerate(lines):
        text = line.strip()
        if not text:
            continue
        try:
            obj = json.loads(text)
        except ValueError:
            is_last = (idx == len(lines) - 1) and not trailing_newline
            (report['truncated_tail'] if is_last else report['corrupt_lines']).append(
                {'file': label, 'line': idx + 1, 'preview': text[:MAX_CORRUPT_PREVIEW]})
            continue
        rows.append((idx + 1, text, obj))
    return rows


def shape_gate(obj, channel, accepted):
    """최소 shape 검사 (전체 schema validator 가 아님). 통과하면 None, 아니면 사유 문자열."""
    if not isinstance(obj, dict):
        return 'not an object'
    if tuple(obj.keys()) != ENVELOPE_KEYS and set(obj.keys()) != set(ENVELOPE_KEYS):
        return f'keys != 13 envelope keys ({len(obj)})'
    if str(obj.get('schema_version')) != '1':
        return 'schema_version != "1"'
    if obj.get('target_type') != channel:
        return f'target_type {obj.get("target_type")!r} != channel {channel!r}'
    if obj.get('ip') not in accepted:
        return f'ip {obj.get("ip")!r} not in accepted manifest'
    if obj.get('status') not in STATUS_VALUES:
        return f'status {obj.get("status")!r}'
    sections = obj.get('sections')
    if not isinstance(sections, dict) or set(sections) != set(ALL_SECTIONS) \
            or not set(sections.values()) <= SECTION_VALUES:
        return 'sections shape'
    diag = obj.get('diagnosis')
    if not isinstance(diag, dict) or set(diag) != set(DIAGNOSIS_KEYS):
        return 'diagnosis shape'
    if not isinstance(obj.get('errors'), list) or not isinstance(obj.get('data'), dict):
        return 'errors/data type'
    return None


def load_progress(path: Path, report: dict):
    """progress 이벤트 → host 별 관측 컨텍스트 (ip 기준; ip 가 없으면 host 이름)."""
    ctx = {}
    for _, _, ev in read_jsonl(path, report, 'progress'):
        if not isinstance(ev, dict):
            continue
        key = ev.get('ip') or ev.get('host')
        if not key:
            continue
        c = ctx.setdefault(key, {'events': [], 'diagnosis': None, 'auth_proven': False, 'lost': False,
                                 'checkpoint': False, 'addon_started': False, 'addon_done': False,
                                 'emitted': False, 'cred_load_outcome': None, 'location': None,
                                 'fail_detail': None, 'last_task': None})
        name = ev.get('event')
        c['events'].append(name)
        if ev.get('task'):
            c['last_task'] = ev.get('task')
        if name == 'precheck' and isinstance(ev.get('diagnosis'), dict):
            c['diagnosis'] = ev['diagnosis']
        elif name == 'auth_proven':
            c['auth_proven'] = True
        elif name == 'lost':
            c['lost'] = True
            if ev.get('detail'):
                c['fail_detail'] = str(ev['detail'])
        elif name == 'checkpoint':
            c['checkpoint'] = True
        elif name == 'addon_started':
            c['addon_started'] = True
        elif name == 'addon_done':
            c['addon_done'] = True
        elif name == 'emitted':
            c['emitted'] = True
        elif name == 'cred_load':
            c['cred_load_outcome'] = ev.get('outcome')
            if ev.get('location'):
                c['location'] = ev.get('location')
        if ev.get('location') and not c['location']:
            c['location'] = ev.get('location')
    return ctx


# ───────────────────────── envelope 조립 ─────────────────────────

def _diagnosis(observed, details, auth_success, stage, code, reason):
    observed = observed if isinstance(observed, dict) else {}
    return {
        'reachable': observed.get('reachable'),
        'port_open': observed.get('port_open'),
        'protocol_supported': observed.get('protocol_supported'),
        'auth_success': auth_success,
        'failure_stage': stage,
        'failure_code': code,
        'failure_reason': reason,
        'details': details,
    }


def synthetic_envelope(canon: Canon, channel, ip, ctx, outcome):
    """OUTPUT 도 CHECKPOINT 도 없는 host 의 envelope — 관측된 사실만으로 단계를 정한다 (json_only 와 같은 4 분기 + outcome)."""
    ctx = ctx or {}
    observed = ctx.get('diagnosis') if isinstance(ctx.get('diagnosis'), dict) else {}
    details = dict(observed.get('details') or {}) if isinstance(observed.get('details'), dict) else {}
    details.setdefault('channel', channel)
    details['finalizer'] = 'layer_a'
    details['outcome'] = outcome
    if ctx.get('last_task'):
        details['last_task'] = ctx['last_task']
    tech = []
    if ctx.get('fail_detail'):
        tech.append(str(ctx['fail_detail']))
    tech.append(f'outcome={outcome}')
    if ctx.get('last_task'):
        tech.append(f'last_task={ctx["last_task"]}')

    if observed.get('failure_stage'):
        # (1) precheck 가 이미 실패로 끝났다 — 그 진단을 그대로 보존한다.
        diag = dict(observed)
        diag['details'] = details
        if not (isinstance(diag.get('failure_reason'), str) and diag['failure_reason'].strip()):
            diag['failure_reason'] = canon.reason('output_build_failed')
        section = 'precheck'
        tech.append('envelope finalized by Layer A; precheck diagnosis preserved')
    elif ctx.get('auth_proven'):
        # (2) 인증 통과 뒤 멈췄다 (연결 끊김 또는 timeout/INT 중단) — gather 단계, auth_success true.
        key = 'gather_connection_lost' if ctx.get('lost') else 'gather_after_auth'
        diag = _diagnosis(observed, details, True, 'gather', 'GATHER_FAILED',
                          canon.reason(key, channel, ctx.get('location')))
        section = 'gather'
        tech.append('envelope finalized by Layer A; authenticated task succeeded before the run stopped')
    elif ctx.get('lost'):
        # (3) 접속 자체를 확인하지 못했다 — json_only 분기 3 과 같다 (2026-08-11 Phase 6-B 계약).
        key = 'loc_vault_no_account' if ctx.get('cred_load_outcome') == 'empty_accounts' else 'auth_unconfirmed'
        diag = _diagnosis(observed, details, None, 'auth', 'AUTH_PROBE_FAILED',
                          canon.reason(key, channel, ctx.get('location')))
        section = 'auth'
        tech.append('envelope finalized by Layer A; host unreachable with no evidence of an authenticated task')
    else:
        # (4) OUTPUT 이 실행되지 않았다 — 결과 객체 생성 실패.
        diag = _diagnosis(observed, details, observed.get('auth_success'), 'fallback', 'OUTPUT_BUILD_FAILED',
                          canon.reason('output_build_failed'))
        section = 'gather'
        tech.append('envelope finalized by Layer A; OUTPUT task did not run')

    shape = canon.shape(channel, ip)
    return {
        'schema_version': '1',
        'target_type': channel,
        'collection_method': CHANNEL_METHOD.get(channel),
        'ip': ip,
        'hostname': None,
        'vendor': None,
        'status': 'failed',
        'sections': shape['sections'],
        'diagnosis': diag,
        'meta': shape['meta'],
        'correlation': shape['correlation'],
        'errors': [{'section': section, 'message': diag['failure_reason'], 'detail': ' | '.join(tech)}],
        'data': shape['data'],
    }


ADDON_INTERRUPTED = '추가 수집 중 처리가 중단되어 추가 수집 결과가 없습니다. 기본 수집 결과는 그대로입니다.'
EMIT_FAILED = '수집은 끝났지만 결과를 내보내는 단계에서 중단되었습니다. 기본 수집 결과는 그대로입니다.'


def envelope_from_checkpoint(cp_obj, ctx, outcome):
    """CHECKPOINT(Add-on 전 조립본)로 복원 — status/sections/diagnosis 는 그대로, 원인별 오류 1건만 붙인다 (D8)."""
    env = json.loads(json.dumps(cp_obj))
    ctx = ctx or {}
    if ctx.get('addon_started') and not ctx.get('addon_done'):
        err = {'section': 'addon', 'message': ADDON_INTERRUPTED,
               'detail': f'finalized from checkpoint; add-on started but did not finish; outcome={outcome}'}
    else:
        err = {'section': 'gather', 'message': EMIT_FAILED,
               'detail': f'finalized from checkpoint; output emit failed after assembly/addon; outcome={outcome}'}
    errors = env.get('errors') if isinstance(env.get('errors'), list) else []
    env['errors'] = errors + [err]
    return env


# ───────────────────────── 메인 ─────────────────────────

def finalize(workspace: Path, repo_root: Path, outcome: str, names: dict) -> tuple[int, dict]:
    report = {'accepted': 0, 'kept': 0, 'filled': 0, 'dropped': [], 'conflicts': [], 'truncated_tail': [],
              'corrupt_lines': [], 'by_origin': {'output': 0, 'checkpoint': 0, 'synthetic': 0},
              'outcome': outcome, 'rc': None, 'exit_code': EXIT_OK, 'layer': 'a'}
    canon = Canon(repo_root)

    manifest_path = workspace / names['manifest']
    if not manifest_path.is_file():
        raise ToolFailure(f'manifest 없음: {manifest_path}')
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise ToolFailure(f'manifest 파싱 실패: {e}') from e
    channel = manifest.get('channel')
    accepted = [str(ip) for ip in (manifest.get('ips') or [])]
    if channel not in CHANNEL_METHOD or not accepted:
        raise ToolFailure(f'manifest 내용 불량: channel={channel!r} ips={len(accepted)}')
    report['accepted'] = len(accepted)
    report['channel'] = channel
    report['build'] = manifest.get('build')

    rc_path = workspace / names['rc']
    if rc_path.is_file():
        try:
            report['rc'] = int(rc_path.read_text(encoding='utf-8').strip() or -1)
        except (OSError, ValueError):
            report['rc'] = None

    accepted_set = set(accepted)
    chosen = {}      # ip → (origin, text, obj)

    # OUTPUT 줄 — 같은 ip 가 여럿이면 뒤 줄 우선, 내용이 다르면 conflicts 에 둘 다 올린다.
    outputs = {}
    for line_no, text, obj in read_jsonl(workspace / names['output'], report, 'output'):
        why = shape_gate(obj, channel, accepted_set)
        if why:
            report['dropped'].append({'file': 'output', 'line': line_no, 'reason': why,
                                      'ip': obj.get('ip') if isinstance(obj, dict) else None})
            continue
        ip = obj['ip']
        if ip in outputs and outputs[ip][1] != text:
            report['conflicts'].append({'ip': ip, 'lines': [outputs[ip][0], line_no], 'chosen': line_no})
        outputs[ip] = (line_no, text, obj)
    for ip, (line_no, text, obj) in outputs.items():
        chosen[ip] = ('output', text, obj)

    # CHECKPOINT 줄 — OUTPUT 이 없는 ip 에만 쓴다.
    checkpoints = {}
    for line_no, text, obj in read_jsonl(workspace / names['checkpoint'], report, 'checkpoint'):
        why = shape_gate(obj, channel, accepted_set)
        if why:
            report['dropped'].append({'file': 'checkpoint', 'line': line_no, 'reason': why,
                                      'ip': obj.get('ip') if isinstance(obj, dict) else None})
            continue
        checkpoints[obj['ip']] = obj

    progress = load_progress(workspace / names['progress'], report)

    final_lines = []
    for ip in accepted:
        if ip in chosen:
            origin, text, _ = chosen[ip]
            final_lines.append(text)
            report['by_origin']['output'] += 1
            continue
        ctx = progress.get(ip)
        if ip in checkpoints:
            env = envelope_from_checkpoint(checkpoints[ip], ctx, outcome)
            report['by_origin']['checkpoint'] += 1
        else:
            env = synthetic_envelope(canon, channel, ip, ctx, outcome)
            report['by_origin']['synthetic'] += 1
            report['filled'] += 1
        final_lines.append(json.dumps(env, ensure_ascii=False, separators=(',', ':')))
    report['kept'] = report['by_origin']['output'] + report['by_origin']['checkpoint']

    if report['kept'] + report['filled'] != report['accepted']:
        raise ToolFailure('invariant kept+filled == accepted 위반')

    damaged = bool(report['truncated_tail'] or report['corrupt_lines'] or report['dropped'] or report['conflicts'])
    report['exit_code'] = EXIT_DAMAGE if damaged else EXIT_OK

    try:
        (workspace / names['final']).write_text('\n'.join(final_lines) + '\n', encoding='utf-8')
        (workspace / names['report']).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    except OSError as e:
        raise ToolFailure(f'출력 쓰기 실패: {e}') from e
    return report['exit_code'], report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--workspace', required=True)
    ap.add_argument('--repo-root', required=True, help='정본 YAML 을 읽을 저장소 루트 (Jenkins WORKSPACE)')
    ap.add_argument('--outcome', default='completed',
                    help='ansible 실행 결과 분류: completed | timeout | prep_failed | not_started_budget | interrupted_unknown ...')
    ap.add_argument('--manifest', default='gather_manifest.json')
    ap.add_argument('--output', default='gather_output.json')
    ap.add_argument('--checkpoint', default='gather_checkpoint.jsonl')
    ap.add_argument('--progress', default='gather_progress.jsonl')
    ap.add_argument('--rc', default='gather_rc.txt')
    ap.add_argument('--final', default='gather_final.jsonl')
    ap.add_argument('--report', default='gather_finalize_report.json')
    a = ap.parse_args(argv)
    names = {k: getattr(a, k) for k in ('manifest', 'output', 'checkpoint', 'progress', 'rc', 'final', 'report')}
    workspace = Path(a.workspace)
    try:
        code, report = finalize(workspace, Path(a.repo_root), a.outcome, names)
    except ToolFailure as e:
        sys.stderr.write(f'[finalize] tool failure: {e}\n')
        try:
            (workspace / a.report).write_text(json.dumps(
                {'layer': 'a', 'exit_code': EXIT_TOOL, 'error': str(e), 'outcome': a.outcome},
                ensure_ascii=False, indent=2), encoding='utf-8')
        except OSError:
            pass
        return EXIT_TOOL
    except Exception as e:  # noqa: BLE001 - 어떤 예외도 Layer B 가 알 수 있게 3 으로 끝낸다
        sys.stderr.write(f'[finalize] unexpected: {type(e).__name__}: {e}\n')
        return EXIT_TOOL
    sys.stderr.write('[finalize] accepted=%d kept=%d filled=%d dropped=%d conflicts=%d outcome=%s exit=%d\n' % (
        report['accepted'], report['kept'], report['filled'], len(report['dropped']),
        len(report['conflicts']), report['outcome'], code))
    return code


if __name__ == '__main__':
    sys.exit(main())
