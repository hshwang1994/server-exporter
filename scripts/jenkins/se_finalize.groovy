
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
    ]
}

@NonCPS
String seJsonString(Object value) {
    return groovy.json.JsonOutput.toJson(value == null ? '' : value.toString())
}

@NonCPS
Map seReconcileRaw(String manifestJson, String outputText, String checkpointText, Map canon, String outcome) {
    def slurper  = new groovy.json.JsonSlurper()
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
            dropped << [file: 'output', line: lineNo, reason: 'shape/ip gate', ip: (obj instanceof Map ? obj.ip?.toString() : null)]; continue
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
            data: new groovy.json.JsonSlurper().parseText(groovy.json.JsonOutput.toJson(canon.skeleton)),
        ]
        lines << groovy.json.JsonOutput.toJson(env); synthetic++
    }
    return [lines: lines, report: [accepted: ips.size(), kept: fromOutput + fromCheckpoint, filled: synthetic,
                                   by_origin: [output: fromOutput, checkpoint: fromCheckpoint, synthetic: synthetic],
                                   dropped: dropped, conflicts: conflicts, layer: 'b']]
}

return this
