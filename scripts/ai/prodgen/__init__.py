"""prodgen — production tree generator (Plan Phase 7a).

Reads a fixed git SHA from the object store only, emits a runtime-only tree with
explanatory comments removed, and verifies the result with fail-closed gates.
"""
GENERATOR_VERSION = "1.0.0"
RULES_VERSION = "2026.10.03"
PROVENANCE_FILE = ".production-provenance.json"
