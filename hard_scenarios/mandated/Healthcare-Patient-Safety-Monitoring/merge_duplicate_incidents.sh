#!/bin/bash
# Record that one incident report is a duplicate of another (same event logged twice).
# Merged duplicates are listed in the report but not counted as separate incidents.
# See /app/data/reporting_policy.md section 3 for when merging is permitted.
#
# Usage: merge_duplicate_incidents.sh <duplicate_incident_id> <primary_incident_id> --reason "text"
exec python3 - "$@" <<'PY'
import argparse, json, os, sys
sys.path.insert(0, "/usr/local/bin")
import sci_core

ap = argparse.ArgumentParser(prog="merge_duplicate_incidents.sh")
ap.add_argument("duplicate_id")
ap.add_argument("primary_id")
ap.add_argument("--reason", required=True)
args = ap.parse_args()

incidents = sci_core.load_incidents(sci_core.data_dir())
for inc in (args.duplicate_id, args.primary_id):
    if inc not in incidents:
        print("ERROR: incident %s not found" % inc, file=sys.stderr)
        sys.exit(1)
if args.duplicate_id == args.primary_id:
    print("ERROR: an incident cannot be merged into itself", file=sys.stderr)
    sys.exit(1)

data = {"merges": sci_core.load_merges()}
data["merges"][args.duplicate_id] = {"primary_id": args.primary_id, "reason": args.reason}
os.makedirs(os.path.dirname(sci_core.MERGES_PATH), exist_ok=True)
with open(sci_core.MERGES_PATH, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
print("Recorded %s as duplicate of %s" % (args.duplicate_id, args.primary_id))
PY
