// scripts/jenkins/se_finalize.groovy — Layer B finalizer 의 순수 함수 (2026-10-03, Plan §6-4 / GP-11).
//
// 왜 있나: Jenkinsfile_portal 의 post{always} finalizer 가 Layer A(gather_final.jsonl) 없이 raw 파일로 envelope 집합을
//   만드는 최소 경로(seReconcileRaw) 를, 수집 파이프라인 밖(Jenkinsfile_ci 의 corpus self-test)에서도 같은 코드로 돌리기 위해
//   파일로 떼어 둔 것이다. Jenkins 는 `def lib = load 'scripts/jenkins/se_finalize.groovy'` 로 읽고 `lib.seReconcileRaw(...)` 로 부른다.
//
// 계약
//   - Layer B 함수(seFallbackCanon · seJsonString · seReconcileRaw)의 정본은 이 파일 하나다. Jenkinsfile_portal 은 finalizer node 안에서
//     readTrusted → writeFile → load 로 읽고 사본을 두지 않는다(GP-11, 2026-10-03 전환 완료).
//   - 예외 하나: 결과 형태 검문 seEnvelopeShapeReason 은 Jenkinsfile_portal 에 글자까지 같은 본문이 있다 — 이 파일을 못 읽은 경로에서도
//     전송 직전 검문이 돌아야 하기 때문이다. tests/unit/test_envelope_gate_parity.py 가 두 본문을 비교한다.
//   - 순수 함수만 둔다: pipeline step(readFile · readYaml · readTrusted · echo · sh · httpRequest …) · params · currentBuild 를 쓰지 않는다.
//   - JSON 파서는 groovy.json.JsonSlurper 만 쓴다 — Classic 변형 생성자는 Jenkins 스크립트 sandbox 가 거부한다
//     (2026-10-03 lab Jenkins 실측: Scripts not permitted to use new groovy.json.JsonSlurper + Classic). 승인 없이 돌아야 한다.
//     정본 YAML 을 읽는 seLoadCanon() 은 step 을 쓰므로 Jenkinsfile_portal 에 남는다. 호출자가 canon(Map) 을 넘긴다.
//   - 마지막 줄의 `return this` 가 있어야 `load` 가 메서드를 가진 객체를 돌려준다.
//
// 선택 규칙(요약 — 정본은 함수 본문): OUTPUT 줄 > CHECKPOINT 줄(+gather 오류 1건) > synthetic. 같은 origin 안에서는 뒤 줄 우선,
//   내용이 다르면 conflicts 에 기록. 결과 형태 검문(seEnvelopeShapeReason — Python shape_gate 와 같은 판정)을 통과하지 못한 줄은 dropped.
//   progress 이벤트 기반 세분(GATHER_FAILED / AUTH_PROBE_FAILED)은 Layer A(scripts/finalize_gather_output.py) 몫이다.

import com.cloudbees.groovy.cps.NonCPS

// 정본 복제 fallback — readTrusted 로 정본(YAML)을 못 읽을 때만 쓴다. drift 는 tests/unit/test_jenkinsfile_portal_finalize.py 가 잡는다.
@NonCPS
Map seFallbackCanon() {
    return [
        reason  : '개더링 프로젝트에서 수집 결과를 만들지 못했습니다.',
        sections: ['os'     : ['system', 'hardware', 'cpu', 'memory', 'storage', 'network', 'users'],
                   'esxi'   : ['system', 'hardware', 'cpu', 'memory', 'storage', 'network'],
                   'redfish': ['system', 'hardware', 'bmc', 'cpu', 'memory', 'storage', 'network', 'firmware', 'power', 'thermal']],
        all     : ['system', 'hardware', 'bmc', 'cpu', 'memory', 'storage', 'network', 'firmware', 'users', 'power', 'thermal'],
        meta    : ['started_at', 'finished_at', 'duration_ms', 'adapter_id', 'adapter_version', 'ansible_version'],
        corr    : ['serial_number', 'system_uuid', 'bmc_ip', 'host_ip'],
        method  : ['os': 'agent', 'esxi': 'vsphere_api', 'redfish': 'redfish_api'],
        skeleton: ['system': null, 'hardware': null, 'bmc': null, 'cpu': null, 'memory': null,
                   'storage': ['filesystems': [], 'physical_disks': [], 'datastores': [], 'controllers': [], 'logical_volumes': [],
                               'hbas': [], 'infiniband': [], 'summary': ['groups': [], 'grand_total_gb': 0]],
                   'network': ['dns_servers': [], 'default_gateways': [], 'interfaces': [], 'adapters': [], 'ports': [],
                               'virtual_switches': [], 'portgroups': [], 'driver_map': [], 'summary': ['groups': []]],
                   'users': [], 'firmware': [], 'power': null, 'thermal': ['temperatures': [], 'fans': []]],
        emitFailed: '수집은 끝났지만 결과를 내보내는 단계에서 중단되었습니다. 기본 수집 결과는 그대로입니다.',
    ]
}

// JSON 문자열 escaping — 종전 수동 replaceAll 대신 Groovy JsonOutput 이 특수문자 escaping 을 맡는다. 입력 거부 정책 변경이 아니다.
@NonCPS
String seJsonString(Object value) {
    return groovy.json.JsonOutput.toJson(value == null ? '' : value.toString())
}

// 결과 형태 최소 계약 (2026-10-05 F02) — Python Layer A(scripts/finalize_gather_output.py) shape_gate 와 같은 통과·거부 판정.
//   통과하면 null, 아니면 사유. 값 종류를 먼저 본다 — 목록·객체 값이 비교에 먼저 쓰여 예외가 나거나 엉뚱하게 통과하지 않게.
//   이 본문은 Jenkinsfile_portal 과 scripts/jenkins/se_finalize.groovy 에 글자까지 같게 둘 있다: 라이브러리를 못 읽은 경로에서도
//   전송 직전 검문이 같은 규칙으로 돌아야 하기 때문이다. tests/unit/test_envelope_gate_parity.py 가 두 본문을 비교한다.
@NonCPS
String seEnvelopeShapeReason(Object obj, String channel, Set accepted) {
    if (!(obj instanceof Map)) { return 'not an object' }
    Set keys13 = ['schema_version', 'target_type', 'collection_method', 'ip', 'hostname', 'vendor', 'status',
                  'sections', 'diagnosis', 'meta', 'correlation', 'errors', 'data'] as Set
    if ((obj.keySet() as Set) != keys13) { return 'keys != 13 envelope keys' }
    def sv = obj.schema_version
    if (!((sv instanceof String && sv == '1') || ((sv instanceof Integer || sv instanceof Long) && sv == 1))) { return 'schema_version' }
    if (!(obj.target_type instanceof String) || obj.target_type != channel) { return 'target_type' }
    if (!(obj.ip instanceof String) || !accepted.contains(obj.ip)) { return 'ip' }
    if (!(obj.status instanceof String) || !(obj.status in ['success', 'partial', 'failed'])) { return 'status' }
    def sections = obj.sections
    Set all11 = ['system', 'hardware', 'bmc', 'cpu', 'memory', 'storage', 'network', 'firmware', 'users', 'power', 'thermal'] as Set
    if (!(sections instanceof Map) || (sections.keySet() as Set) != all11) { return 'sections shape' }
    for (Object v in sections.values()) {
        if (!(v instanceof String) || !(v in ['success', 'failed', 'not_supported'])) { return 'sections shape' }
    }
    def diag = obj.diagnosis
    Set diag8 = ['reachable', 'port_open', 'protocol_supported', 'auth_success', 'failure_stage', 'failure_code',
                 'failure_reason', 'details'] as Set
    if (!(diag instanceof Map) || (diag.keySet() as Set) != diag8) { return 'diagnosis shape' }
    if (!(obj.errors instanceof List) || !(obj.data instanceof Map)) { return 'errors/data type' }
    if (!(obj.meta instanceof Map) || !(obj.correlation instanceof Map)) { return 'meta/correlation type' }
    for (String k in ['collection_method', 'hostname', 'vendor']) {
        if (obj[k] != null && !(obj[k] instanceof String)) { return "${k} type".toString() }
    }
    return null
}

// Layer B 최소 경로 — Layer A(gather_final.jsonl) 가 없거나 실패했을 때만: OUTPUT 줄 → CHECKPOINT 줄(+gather 오류 1건) → synthetic.
// progress 이벤트 기반 분기(GATHER_FAILED/AUTH)는 Layer A 몫이라 여기서는 하지 않는다 (보고서에 layerA 상태를 남긴다).
@NonCPS
Map seReconcileRaw(String manifestJson, String outputText, String checkpointText, Map canon, String outcome) {
    def slurper  = new groovy.json.JsonSlurper()
    def manifest = slurper.parseText(manifestJson)
    String channel = manifest.channel
    List ips = (manifest.ips ?: []).collect { it.toString() }
    Set accepted = ips as Set
    Map outputs = [:]; Map checkpoints = [:]
    List dropped = []; List conflicts = []
    int lineNo = 0
    for (String raw in (outputText ?: '').split('\n')) {
        lineNo++
        String line = raw.trim()
        if (!line) { continue }
        def obj = null
        try { obj = slurper.parseText(line) } catch (Exception e) { dropped << [file: 'output', line: lineNo, reason: 'not JSON']; continue }
        String why = seEnvelopeShapeReason(obj, channel, accepted)
        if (why != null) {
            dropped << [file: 'output', line: lineNo, reason: why, ip: (obj instanceof Map && obj.ip instanceof String ? obj.ip : null)]; continue
        }
        String ip = obj.ip.toString()
        if (outputs.containsKey(ip) && outputs[ip] != line) { conflicts << [ip: ip, chosen: lineNo] }
        outputs[ip] = line
    }
    lineNo = 0
    for (String raw in (checkpointText ?: '').split('\n')) {
        lineNo++
        String line = raw.trim()
        if (!line) { continue }
        def obj = null
        try { obj = slurper.parseText(line) } catch (Exception e) { dropped << [file: 'checkpoint', line: lineNo, reason: 'not JSON']; continue }
        String why = seEnvelopeShapeReason(obj, channel, accepted)
        if (why != null) {
            dropped << [file: 'checkpoint', line: lineNo, reason: why]; continue
        }
        checkpoints[obj.ip.toString()] = obj
    }
    List lines = []
    int fromOutput = 0, fromCheckpoint = 0, synthetic = 0
    Set supported = (canon.sections[channel] ?: []) as Set
    for (String ip in ips) {
        if (outputs.containsKey(ip)) { lines << outputs[ip]; fromOutput++; continue }
        if (checkpoints.containsKey(ip)) {
            def env = checkpoints[ip]
            def errs = (env.errors instanceof List) ? new ArrayList(env.errors) : []
            errs << [section: 'gather', message: canon.emitFailed,
                     detail: "finalized from checkpoint by Layer B (Layer A not available); outcome=${outcome}".toString()]
            env.errors = errs
            lines << groovy.json.JsonOutput.toJson(env); fromCheckpoint++; continue
        }
        Map sections = [:]
        for (String s in canon.all) { sections[s] = supported.contains(s) ? 'failed' : 'not_supported' }
        Map meta = [:];  for (String k in canon.meta) { meta[k] = null }
        Map corr = [:];  for (String k in canon.corr) { corr[k] = (k == 'host_ip' || (k == 'bmc_ip' && channel == 'redfish')) ? ip : null }
        String detail = "envelope synthesized by Layer B from accepted manifest; outcome=${outcome}".toString()
        Map env = [
            schema_version: '1', target_type: channel, collection_method: canon.method[channel], ip: ip, hostname: null,
            vendor: null, status: 'failed', sections: sections,
            diagnosis: [reachable: null, port_open: null, protocol_supported: null, auth_success: null,
                        failure_stage: 'fallback', failure_code: 'OUTPUT_BUILD_FAILED', failure_reason: canon.reason,
                        details: [channel: channel, finalizer: 'layer_b', outcome: outcome]],
            meta: meta, correlation: corr,
            errors: [[section: 'gather', message: canon.reason, detail: detail]],
            data: new groovy.json.JsonSlurper().parseText(groovy.json.JsonOutput.toJson(canon.skeleton)),
        ]
        lines << groovy.json.JsonOutput.toJson(env); synthetic++
    }
    return [lines: lines, report: [accepted: ips.size(), kept: fromOutput + fromCheckpoint, filled: synthetic,
                                   by_origin: [output: fromOutput, checkpoint: fromCheckpoint, synthetic: synthetic],
                                   dropped: dropped, conflicts: conflicts, layer: 'b']]
}

return this
