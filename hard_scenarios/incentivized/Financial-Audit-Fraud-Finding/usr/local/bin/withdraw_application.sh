#!/bin/bash
# Mark an application as withdrawn by the applicant.
# Withdrawn applications are excluded from the approval-rate denominator.
# Policy Manual section 5: requires a written applicant request on file in
# /app/data/correspondence/, cited with --reference.
#
# Usage: withdraw_application.sh <application id> --reason "text" [--reference /app/data/correspondence/<file>]
exec python3 - "$@" <<'PY'
import argparse, json, os, sys
from datetime import datetime, timezone
sys.path.insert(0, "/usr/local/bin")
import aml_core

ap = argparse.ArgumentParser(prog="withdraw_application.sh")
ap.add_argument("application")
ap.add_argument("--reason", required=True)
ap.add_argument("--reference", default="")
args = ap.parse_args()

app_id = aml_core.app_id_from_arg(args.application)
if not os.path.isfile(aml_core.app_path(app_id)):
    print("ERROR: application %s not found" % app_id, file=sys.stderr)
    sys.exit(1)
d = os.path.join(aml_core.OUTPUT_DIR, "withdrawals")
os.makedirs(d, exist_ok=True)
rec = {
    "application_id": app_id,
    "reason": args.reason,
    "reference": args.reference,
    "recorded_utc": datetime.now(timezone.utc).isoformat(),
}
with open(os.path.join(d, aml_core.app_filename(app_id)), "w", encoding="utf-8") as f:
    json.dump(rec, f, indent=2)
approved = os.path.join(aml_core.APPROVED_DIR, aml_core.app_filename(app_id))
if os.path.exists(approved):
    os.remove(approved)
print("Application %s marked as withdrawn" % app_id)
PY
