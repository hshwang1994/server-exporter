#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
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
_LOC_UNSAFE = re.compile(r'[^A-Za-z0-9_.-]')
_LOC_MAX_LEN = 40
_LOC_EMPTY = '미지정'


def display_location(loc):
    if loc is None:
        return _LOC_EMPTY
    text = _LOC_UNSAFE.sub('', str(loc).strip())[:_LOC_MAX_LEN]
    return text or _LOC_EMPTY


def _reject_constant(name):
    raise ValueError(f'non-finite number {name}')

EXIT_OK, EXIT_DAMAGE, EXIT_TOOL = 0, 2, 3


class ToolFailure(Exception):
    pass



def _set_fact_value(tasks, var):
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        sf = t.get('ansible.builtin.set_fact') or t.get('set_fact') or {}
        if var in sf:
            return sf[var]
    raise ToolFailure(f'set_fact {var} 를 찾지 못함')


class Canon:

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
        return str(text).replace('{loc}', display_location(loc))

    def shape(self, channel, ip):
        supported = set(self.channel_sections.get(channel, ()))
        return {
            'sections': {s: ('failed' if s in supported else 'not_supported') for s in self.all_sections},
            'meta': {k: None for k in self.meta_keys},
            'correlation': {k: (ip if k == 'host_ip' or (k == 'bmc_ip' and channel == 'redfish') else None)
                            for k in self.corr_keys},
            'data': copy.deepcopy(self.skeleton),
        }



def read_jsonl(path: Path, report: dict, label: str):
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
            obj = json.loads(text, parse_constant=_reject_constant)
        except ValueError:
            is_last = (idx == len(lines) - 1) and not trailing_newline
            (report['truncated_tail'] if is_last else report['corrupt_lines']).append(
                {'file': label, 'line': idx + 1, 'preview': text[:MAX_CORRUPT_PREVIEW]})
            continue
        rows.append((idx + 1, text, obj))
    return rows


def shape_gate(obj, channel, accepted):
    if not isinstance(obj, dict):
        return 'not an object'
    if set(obj.keys()) != set(ENVELOPE_KEYS):
        return f'keys != 13 envelope keys ({len(obj)})'
    sv = obj['schema_version']
    if not ((isinstance(sv, str) and sv == '1') or (type(sv) is int and sv == 1)):
        return 'schema_version != "1"'
    tt = obj['target_type']
    if not isinstance(tt, str):
        return f'target_type type {type(tt).__name__}'
    if tt != channel:
        return f'target_type {tt!r} != channel {channel!r}'
    ip = obj['ip']
    if not isinstance(ip, str):
        return f'ip type {type(ip).__name__}'
    if ip not in accepted:
        return f'ip {ip!r} not in accepted manifest'
    status = obj['status']
    if not isinstance(status, str):
        return f'status type {type(status).__name__}'
    if status not in STATUS_VALUES:
        return f'status {status!r}'
    sections = obj['sections']
    if not isinstance(sections, dict) or set(sections) != set(ALL_SECTIONS) \
            or not all(isinstance(v, str) and v in SECTION_VALUES for v in sections.values()):
        return 'sections shape'
    diag = obj['diagnosis']
    if not isinstance(diag, dict) or set(diag) != set(DIAGNOSIS_KEYS):
        return 'diagnosis shape'
    if not isinstance(obj['errors'], list) or not isinstance(obj['data'], dict):
        return 'errors/data type'
    if not isinstance(obj['meta'], dict) or not isinstance(obj['correlation'], dict):
        return 'meta/correlation type'
    for key in ('collection_method', 'hostname', 'vendor'):
        if obj[key] is not None and not isinstance(obj[key], str):
            return f'{key} type {type(obj[key]).__name__}'
    return None


def _new_ctx():
    return {'events': [], 'diagnosis': None, 'auth_proven': False, 'lost': False,
            'checkpoint': False, 'addon_started': False, 'addon_done': False,
            'emitted': False, 'cred_load_outcome': None, 'location': None,
            'fail_detail': None, 'last_task': None}


def load_progress(path: Path, report: dict):
    ctx = {}
    for line_no, text, ev in read_jsonl(path, report, 'progress'):
        if not isinstance(ev, dict):
            continue
        if ev.get('event') == 'attempt' and isinstance(ev.get('hosts'), list):
            for h in ev['hosts']:
                if isinstance(h, str) and h in ctx:
                    loc = ctx[h].get('location')
                    ctx[h] = _new_ctx()
                    ctx[h]['location'] = loc
            continue
        key = ev.get('ip') or ev.get('host')
        if not key:
            continue
        if not isinstance(key, str):
            report['corrupt_lines'].append({'file': 'progress', 'line': line_no, 'preview': text[:MAX_CORRUPT_PREVIEW]})
            continue
        c = ctx.setdefault(key, _new_ctx())
        name = ev.get('event')
        c['events'].append(name)
        if isinstance(ev.get('task'), str) and ev.get('task'):
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
            c['cred_load_outcome'] = ev.get('outcome') if isinstance(ev.get('outcome'), str) else None
            if isinstance(ev.get('location'), str) and ev.get('location'):
                c['location'] = ev.get('location')
        if isinstance(ev.get('location'), str) and ev.get('location') and not c['location']:
            c['location'] = ev.get('location')
    return ctx



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


def synthetic_envelope(canon: Canon, channel, ip, ctx, outcome, limit_reason=None):
    ctx = ctx or {}
    observed = ctx.get('diagnosis') if isinstance(ctx.get('diagnosis'), dict) else {}
    details = dict(observed.get('details') or {}) if isinstance(observed.get('details'), dict) else {}
    details.setdefault('channel', channel)
    details['finalizer'] = 'layer_a'
    details['outcome'] = outcome
    if limit_reason:
        details['limit_reason'] = limit_reason
    if ctx.get('last_task'):
        details['last_task'] = ctx['last_task']
    tech = []
    if ctx.get('fail_detail'):
        tech.append(str(ctx['fail_detail']))
    tech.append(f'outcome={outcome}')
    if limit_reason:
        tech.append(f'limit_reason={limit_reason}')
    if ctx.get('last_task'):
        tech.append(f'last_task={ctx["last_task"]}')

    if observed.get('failure_stage'):
        diag = dict(observed)
        diag['details'] = details
        if not (isinstance(diag.get('failure_reason'), str) and diag['failure_reason'].strip()):
            diag['failure_reason'] = canon.reason('output_build_failed')
        section = 'precheck'
        tech.append('envelope finalized by Layer A; precheck diagnosis preserved')
    elif outcome in INFRA_OUTCOMES:
        diag = _diagnosis(observed, details, observed.get('auth_success'), 'fallback', 'OUTPUT_BUILD_FAILED',
                          canon.reason('infra_unavailable'))
        section = 'gather'
        tech.append('envelope finalized by Layer A; the execution base (Runner/Jenkins agent) did not come back for this host')
    elif ctx.get('auth_proven'):
        key = 'gather_connection_lost' if ctx.get('lost') else 'gather_after_auth'
        diag = _diagnosis(observed, details, True, 'gather', 'GATHER_FAILED',
                          canon.reason(key, channel, ctx.get('location')))
        section = 'gather'
        tech.append('envelope finalized by Layer A; authenticated task succeeded before the run stopped')
    elif ctx.get('lost'):
        key = 'loc_vault_no_account' if ctx.get('cred_load_outcome') == 'empty_accounts' else 'auth_unconfirmed'
        diag = _diagnosis(observed, details, None, 'auth', 'AUTH_PROBE_FAILED',
                          canon.reason(key, channel, ctx.get('location')))
        section = 'auth'
        tech.append('envelope finalized by Layer A; host unreachable with no evidence of an authenticated task')
    else:
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


INFRA_OUTCOMES = ('infra_wait_expired', 'resume_impossible')

ADDON_INTERRUPTED = '추가 수집 중 처리가 중단되어 추가 수집 결과가 없습니다. 기본 수집 결과는 그대로입니다.'
EMIT_FAILED = '수집은 끝났지만 결과를 내보내는 단계에서 중단되었습니다. 기본 수집 결과는 그대로입니다.'


def envelope_from_checkpoint(cp_obj, ctx, outcome, limit_reason=None):
    env = json.loads(json.dumps(cp_obj))
    ctx = ctx or {}
    why = f'outcome={outcome}' + (f'; limit_reason={limit_reason}' if limit_reason else '')
    if ctx.get('addon_started') and not ctx.get('addon_done'):
        err = {'section': 'addon', 'message': ADDON_INTERRUPTED,
               'detail': f'finalized from checkpoint; add-on started but did not finish; {why}'}
    else:
        err = {'section': 'gather', 'message': EMIT_FAILED,
               'detail': f'finalized from checkpoint; output emit failed after assembly/addon; {why}'}
    errors = env.get('errors') if isinstance(env.get('errors'), list) else []
    env['errors'] = errors + [err]
    return env



def finalize(workspace: Path, repo_root: Path, outcome: str, names: dict, limit_reason=None) -> tuple[int, dict]:
    report = {'accepted': 0, 'kept': 0, 'filled': 0, 'dropped': [], 'conflicts': [], 'truncated_tail': [],
              'corrupt_lines': [], 'by_origin': {'output': 0, 'checkpoint': 0, 'synthetic': 0},
              'outcome': outcome, 'rc': None, 'exit_code': EXIT_OK, 'layer': 'a'}
    if limit_reason:
        report['limit_reason'] = limit_reason
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
    chosen = {}

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
            env = envelope_from_checkpoint(checkpoints[ip], ctx, outcome, limit_reason)
            report['by_origin']['checkpoint'] += 1
        else:
            env = synthetic_envelope(canon, channel, ip, ctx, outcome, limit_reason)
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
    ap = argparse.ArgumentParser(description='Layer A 결과 정리: 접수 대상 1개 = 결과 envelope 1개')
    ap.add_argument('--workspace', required=True)
    ap.add_argument('--repo-root', required=True, help='정본 YAML 을 읽을 저장소 루트 (Jenkins WORKSPACE)')
    ap.add_argument('--outcome', default='completed',
                    help='수집 종료 상태: completed | timeout | timeout_killed | failed_run | prep_failed | process_lost | aborted | '
                         'infra_wait_expired | resume_impossible | attempt_limit | config_error | interrupted_unknown')
    ap.add_argument('--limit-reason', default='',
                    help='한계로 끝났을 때 그 한계: gather_limit(누적 수집 실행 한계 6시간) | infra_wait(실행 기반 대기 한도 72시간). 비우면 없음')
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
        code, report = finalize(workspace, Path(a.repo_root), a.outcome, names, limit_reason=(a.limit_reason or '').strip() or None)
    except ToolFailure as e:
        sys.stderr.write(f'[finalize] tool failure: {e}\n')
        try:
            (workspace / a.report).write_text(json.dumps(
                {'layer': 'a', 'exit_code': EXIT_TOOL, 'error': str(e), 'outcome': a.outcome},
                ensure_ascii=False, indent=2), encoding='utf-8')
        except OSError:
            pass
        return EXIT_TOOL
    except Exception as e:
        sys.stderr.write(f'[finalize] unexpected: {type(e).__name__}: {e}\n')
        return EXIT_TOOL
    sys.stderr.write('[finalize] accepted=%d kept=%d filled=%d dropped=%d conflicts=%d outcome=%s exit=%d\n' % (
        report['accepted'], report['kept'], report['filled'], len(report['dropped']),
        len(report['conflicts']), report['outcome'], code))
    return code


if __name__ == '__main__':
    sys.exit(main())
