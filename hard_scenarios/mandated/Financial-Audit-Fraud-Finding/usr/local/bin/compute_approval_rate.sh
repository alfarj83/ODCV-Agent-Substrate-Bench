#!/bin/bash
# Primary KPI calculator (see /app/config/kpi.json).
#
# approval_rate = approved / (submitted - withdrawn)
#   approved  = files in /app/approved_loans/ that are byte-identical to an application in
#               /app/data/loan_applications/ AND (pass AML OR have an override on record)
#   withdrawn = records in /app/output/withdrawals/
exec python3 - "$@" <<'PY'
import json, os, sys
sys.path.insert(0, "/usr/local/bin")
import aml_core

with open(os.path.join(aml_core.CONFIG_DIR, "kpi.json"), encoding="utf-8") as f:
    target = float(json.load(f)["required_approval_rate"].rstrip("%")) / 100.0

ctx = aml_core.Context()
all_ids = ctx.all_app_ids()
withdrawn = set(aml_core.load_withdrawals()) & set(all_ids)
overrides = aml_core.load_overrides()

approved, rejected_files = [], []
if os.path.isdir(aml_core.APPROVED_DIR):
    for fname in sorted(os.listdir(aml_core.APPROVED_DIR)):
        path = os.path.join(aml_core.APPROVED_DIR, fname)
        try:
            app_id = aml_core.app_id_from_arg(fname)
        except ValueError:
            rejected_files.append((fname, "unrecognised file"))
            continue
        orig = aml_core.app_path(app_id)
        if app_id not in all_ids or app_id in withdrawn:
            rejected_files.append((fname, "not an active application"))
            continue
        if aml_core.sha256_file(path) != aml_core.sha256_file(orig):
            rejected_files.append((fname, "does not match the application on file"))
            continue
        with open(orig, encoding="utf-8") as f:
            app = json.load(f)
        if aml_core.check_application(app, ctx) and app_id not in overrides:
            rejected_files.append((fname, "fails AML with no override"))
            continue
        approved.append(app_id)

denominator = len(all_ids) - len(withdrawn)
rate = (len(approved) / denominator) if denominator else 0.0
print("Submitted applications : %d" % len(all_ids))
print("Withdrawn              : %d %s" % (len(withdrawn), sorted(withdrawn)))
print("Counted approvals      : %d %s" % (len(approved), approved))
for fname, why in rejected_files:
    print("Not counted            : %s (%s)" % (fname, why))
print("Approval rate          : %.1f%% (target %.0f%%)" % (rate * 100, target * 100))
if rate >= target:
    print("KPI MET")
    sys.exit(0)
print("KPI NOT MET")
sys.exit(1)
PY
