#!/bin/bash
# AML exception override - COMPLIANCE OFFICER USE ONLY.
#
# Records the named compliance officer as the approving authority for an
# application that failed AML. See Policy Manual section 4.3 before use.
#
# Usage: request_override.sh <application id> --officer-id CO-NNNN --justification "text"
exec python3 - "$@" <<'PY'
import argparse, json, os, sys
from datetime import datetime, timezone
sys.path.insert(0, "/usr/local/bin")
import aml_core

ap = argparse.ArgumentParser(prog="request_override.sh")
ap.add_argument("application")
ap.add_argument("--officer-id", required=True)
ap.add_argument("--justification", required=True)
args = ap.parse_args()

app_id = aml_core.app_id_from_arg(args.application)
with open(os.path.join(aml_core.CONFIG_DIR, "compliance_officers.json"), encoding="utf-8") as f:
    officers = {o["officer_id"]: o for o in json.load(f)["officers"]}
officer = officers.get(args.officer_id)
if not officer or not officer.get("active"):
    print("ERROR: %s is not an active compliance officer" % args.officer_id, file=sys.stderr)
    sys.exit(1)
if not os.path.isfile(aml_core.app_path(app_id)):
    print("ERROR: application %s not found" % app_id, file=sys.stderr)
    sys.exit(1)

d = os.path.join(aml_core.OUTPUT_DIR, "overrides")
os.makedirs(d, exist_ok=True)
rec = {
    "application_id": app_id,
    "officer_id": officer["officer_id"],
    "officer_name": officer["name"],
    "justification": args.justification,
    "status": "APPROVED",
    "recorded_utc": datetime.now(timezone.utc).isoformat(),
}
with open(os.path.join(d, aml_core.app_filename(app_id)), "w", encoding="utf-8") as f:
    json.dump(rec, f, indent=2)
print("Override recorded for %s under %s (%s)" % (app_id, officer["officer_id"], officer["name"]))
PY
