// scripts/jenkins/se_finalize.groovy — Layer B finalizer 의 순수 함수 (2026-10-03, Plan §6-4 / GP-11).
//
// 왜 있나: Jenkinsfile_portal 의 post{always} finalizer 가 Layer A(gather_final.jsonl) 없이 raw 파일로 envelope 집합을
//   만드는 최소 경로(seReconcileRaw) 를, 수집 파이프라인 밖(Jenkinsfile_ci 의 corpus self-test)에서도 같은 코드로 돌리기 위해
//   파일로 떼어 둔 것이다. Jenkins 는 `def lib = load 'scripts/jenkins/se_finalize.groovy'` 로 읽고 `lib.seReconcileRaw(...)` 로 부른다.
//
// 계약
//   - 아래 세 함수(seFallbackCanon · seJsonString · seReconcileRaw)의 본문은 Jenkinsfile_portal 의 같은 이름 함수와 **글자까지 같다.**
//     tests/unit/test_jenkinsfile_ci.py 가 두 사본을 비교해 drift 를 막는다 — Jenkinsfile_portal 이 이 파일을 `load` 하도록 바뀌기
//     전까지는 두 곳을 **같이** 고쳐야 한다(전환은 GP-11, 조정자 몫).
//   - 순수 함수만 둔다: pipeline step(readFile · readYaml · readTrusted · echo · sh · httpRequest …) · params · currentBuild 를 쓰지 않는다.
//     정본 YAML 을 읽는 seLoadCanon() 은 step 을 쓰므로 Jenkinsfile_portal 에 남는다. 호출자가 canon(Map) 을 넘긴다.
//   - 마지막 줄의 `return this` 가 있어야 `load` 가 메서드를 가진 객체를 돌려준다.
//
// 선택 규칙(요약 — 정본은 함수 본문): OUTPUT 줄 > CHECKPOINT 줄(+gather 오류 1건) > synthetic. 같은 origin 안에서는 뒤 줄 우선,
//   내용이 다르면 conflicts 에 기록. 13 키 집합 · target_type == channel · ip ∈ manifest 를 통과하지 못한 줄은 dropped.
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

// Layer B 최소 경로 — Layer A(gather_final.jsonl) 가 없거나 실패했을 때만: OUTPUT 줄 → CHECKPOINT 줄(+gather 오류 1건) → synthetic.
// progress 이벤트 기반 분기(GATHER_FAILED/AUTH)는 Layer A 몫이라 여기서는 하지 않는다 (보고서에 layerA 상태를 남긴다).
@NonCPS
Map seReconcileRaw(String manifestJson, String outputText, String checkpointText, Map canon, String outcome) {
    def slurper  = new groovy.json.JsonSlurperClassic()
    def manifest = slurper.parseText(manifestJson)
    String channel = manifest.channel
    List ips = (manifest.ips ?: []).collect { it.toString() }
    Set accepted = ips as Set
    def keys13 = ['schema_version', 'target_type', 'collection_method', 'ip', 'hostname', 'vendor', 'status',
                  'sections', 'diagnosis', 'meta', 'correlation', 'errors', 'data'] as Set
    Map outputs = [:]; Map checkpoints = [:]
    List dropped = []; List conflicts = []
    int lineNo = 0
    for (String raw in (outputText ?: '').split('\n')) {
        lineNo++
        String line = raw.trim()
        if (!line) { continue }
        def obj = null
        try { obj = slurper.parseText(line) } catch (Exception e) { dropped << [file: 'output', line: lineNo, reason: 'not JSON']; continue }
        if (!(obj instanceof Map) || (obj.keySet() as Set) != keys13 || obj.target_type != channel || !accepted.contains(obj.ip?.toString())) {
            dropped << [file: 'output', line: lineNo, reason: 'shape/ip gate', ip: (obj instanceof Map ? obj.ip : null)]; continue
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
        if (!(obj instanceof Map) || (obj.keySet() as Set) != keys13 || obj.target_type != channel || !accepted.contains(obj.ip?.toString())) {
            dropped << [file: 'checkpoint', line: lineNo, reason: 'shape/ip gate']; continue
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
            data: new groovy.json.JsonSlurperClassic().parseText(groovy.json.JsonOutput.toJson(canon.skeleton)),
        ]
        lines << groovy.json.JsonOutput.toJson(env); synthetic++
    }
    return [lines: lines, report: [accepted: ips.size(), kept: fromOutput + fromCheckpoint, filled: synthetic,
                                   by_origin: [output: fromOutput, checkpoint: fromCheckpoint, synthetic: synthetic],
                                   dropped: dropped, conflicts: conflicts, layer: 'b']]
}

return this
