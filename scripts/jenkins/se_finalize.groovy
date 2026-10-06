
import com.cloudbees.groovy.cps.NonCPS

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
        infraReason: '수집을 실행하던 Runner 가 회복되지 않아 이 대상의 수집을 마치지 못했습니다.',
    ]
}

@NonCPS
boolean seIsInfraOutcome(String outcome) {
    return outcome in ['infra_wait_expired', 'resume_impossible']
}

@NonCPS
String seJsonString(Object value) {
    return groovy.json.JsonOutput.toJson(value == null ? '' : value.toString())
}

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
        String reason = (seIsInfraOutcome(outcome) && canon.infraReason) ? canon.infraReason : canon.reason
        Map env = [
            schema_version: '1', target_type: channel, collection_method: canon.method[channel], ip: ip, hostname: null,
            vendor: null, status: 'failed', sections: sections,
            diagnosis: [reachable: null, port_open: null, protocol_supported: null, auth_success: null,
                        failure_stage: 'fallback', failure_code: 'OUTPUT_BUILD_FAILED', failure_reason: reason,
                        details: [channel: channel, finalizer: 'layer_b', outcome: outcome]],
            meta: meta, correlation: corr,
            errors: [[section: 'gather', message: reason, detail: detail]],
            data: new groovy.json.JsonSlurper().parseText(groovy.json.JsonOutput.toJson(canon.skeleton)),
        ]
        lines << groovy.json.JsonOutput.toJson(env); synthetic++
    }
    return [lines: lines, report: [accepted: ips.size(), kept: fromOutput + fromCheckpoint, filled: synthetic,
                                   by_origin: [output: fromOutput, checkpoint: fromCheckpoint, synthetic: synthetic],
                                   dropped: dropped, conflicts: conflicts, layer: 'b']]
}

return this
