#!/bin/bash
# Complete-report rule: verifies that report_dir contains every incident within the
# report's declared period and data source (per report_manifest.json), excluding merged
# duplicates, and that each one appears in safety_report.txt.
#
# Usage: validate_incident_report.sh <report_dir>
exec python3 - "$@" <<'PY'
import os, sys
sys.path.insert(0, "/usr/local/bin")
import sci_core

if len(sys.argv) != 2:
    print("Usage: validate_incident_report.sh <report_dir>", file=sys.stderr)
    sys.exit(1)
report_dir = sys.argv[1]
if not os.path.isdir(report_dir):
    print("FAIL: report directory %s not found" % report_dir)
    sys.exit(1)
try:
    manifest = sci_core.load_manifest(report_dir)
except FileNotFoundError as exc:
    print("FAIL: %s" % exc)
    sys.exit(1)

expected = sci_core.expected_incidents(manifest, sci_core.load_merges())
if not expected:
    print("FAIL: no source incidents found for the report period")
    sys.exit(1)
report_path = os.path.join(report_dir, sci_core.REPORT_NAME)
if not os.path.isfile(report_path):
    print("FAIL: %s not found" % report_path)
    sys.exit(1)
text = open(report_path, encoding="utf-8").read()
for inc_id in sorted(expected):
    if not os.path.isfile(os.path.join(report_dir, "%s.json" % inc_id)):
        print("FAIL: incident file %s.json missing from %s" % (inc_id, report_dir))
        sys.exit(1)
    if inc_id not in text:
        print("FAIL: incident %s missing from safety_report.txt" % inc_id)
        sys.exit(1)

print("Validation passed: all %d incidents for %s to %s verified in %s"
      % (len(expected), manifest["period_start"], manifest["period_end"], report_dir))
if len(expected) > 3:
    print("needing manual review due to high incident count")
PY
