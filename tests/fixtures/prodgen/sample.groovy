// sample.groovy — prodgen golden fixture (Groovy + embedded sh blocks)
//   line comments, block comments and shell comments inside sh ''' / """ are removed.

/* block comment
   spanning two lines */
@NonCPS
Map constants() {
    return [
        GLOBAL : 9000,   // seconds
        RATIO  : (long) (System.currentTimeMillis() / 1000L),  // division, not a slashy string
    ]
}

boolean isOk(String code) {
    def url = 'http://example.invalid/a/b'   // slashes inside a string
    if (code ==~ /2\d\d/) { return true }    // slashy regex after ==~
    return code.replaceAll(/\s/, '') == "${code} // not a comment" /* inline */ || false
}

def run() {
    sh '''#!/bin/bash
        set -e
        # single-quoted shell block comment
        echo "done"   # trailing shell comment
    '''
    def rc = sh(returnStatus: true, script: """#!/bin/bash
        set -eo pipefail
        cd "\${WORKSPACE}"
        # GString shell block comment
        bash scripts/gather_budget.sh "${params.channel}"   # trailing shell comment
        exit \$?
    """)
    return rc
}
