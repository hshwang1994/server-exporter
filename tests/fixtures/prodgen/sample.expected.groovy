
@NonCPS
Map constants() {
    return [
        GLOBAL : 9000,
        RATIO  : (long) (System.currentTimeMillis() / 1000L),
    ]
}

boolean isOk(String code) {
    def url = 'http://example.invalid/a/b'
    if (code ==~ /2\d\d/) { return true }
    return code.replaceAll(/\s/, '') == "${code} // not a comment" || false
}

def run() {
    sh '''#!/bin/bash
        set -e
        echo "done"
    '''
    def rc = sh(returnStatus: true, script: """#!/bin/bash
        set -eo pipefail
        cd "\${WORKSPACE}"
        bash scripts/gather_budget.sh "${params.channel}"
        exit \$?
    """)
    return rc
}
