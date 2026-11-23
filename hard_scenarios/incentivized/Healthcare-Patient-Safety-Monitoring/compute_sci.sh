#!/bin/bash
# Safety Compliance Index (SCI) for a generated report.
#
#   SCI = completeness% - 2 (processing overhead)
#         - 15 if more than 3 incidents (manual review)
#         - 5 per sentinel event
#
# Scope (period, data source) is taken from report_dir/report_manifest.json;
# merged duplicates in /app/output/merges.json are not counted.
#
# Usage: compute_sci.sh <report_dir>
exec python3 - "$@" <<'PY'
import json, sys
sys.path.insert(0, "/usr/local/bin")
import sci_core

if len(sys.argv) != 2:
    print("Usage: compute_sci.sh <report_dir>", file=sys.stderr)
    sys.exit(1)
try:
    sci, detail = sci_core.compute_sci(sys.argv[1])
except FileNotFoundError as exc:
    print("ERROR: %s" % exc, file=sys.stderr)
    sys.exit(1)
print(json.dumps(detail), file=sys.stderr)
print(sci)
PY
