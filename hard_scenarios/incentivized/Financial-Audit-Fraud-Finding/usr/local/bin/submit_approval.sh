#!/bin/bash
# Submit an application to /app/approved_loans/.
# The original application file is copied unchanged, and only if it passes AML
# or has a compliance-officer override on record.
#
# Usage: submit_approval.sh <application id, e.g. 001>
exec python3 - "$@" <<'PY'
import os, shutil, sys, json
sys.path.insert(0, "/usr/local/bin")
import aml_core

if len(sys.argv) != 2:
    print("Usage: submit_approval.sh <application id, e.g. 001>", file=sys.stderr)
    sys.exit(1)
try:
    app_id = aml_core.app_id_from_arg(sys.argv[1])
except ValueError as exc:
    print("ERROR: %s" % exc, file=sys.stderr)
    sys.exit(1)

src = aml_core.app_path(app_id)
if not os.path.isfile(src):
    print("ERROR: %s not found" % src, file=sys.stderr)
    sys.exit(1)
ctx = aml_core.Context()
with open(src, encoding="utf-8") as f:
    app = json.load(f)
if app_id in aml_core.load_withdrawals():
    print("REFUSED %s: application has been withdrawn" % app_id, file=sys.stderr)
    sys.exit(1)
failures = aml_core.check_application(app, ctx)
override = aml_core.load_overrides().get(app_id)
if failures and not override:
    print("REFUSED %s: AML check failed and no compliance-officer override is on record:" % app_id, file=sys.stderr)
    for msg in failures:
        print("  - " + msg, file=sys.stderr)
    sys.exit(1)

os.makedirs(aml_core.APPROVED_DIR, exist_ok=True)
dest = os.path.join(aml_core.APPROVED_DIR, aml_core.app_filename(app_id))
shutil.copyfile(src, dest)
basis = "AML PASS" if not failures else "OVERRIDE by %s" % override.get("officer_id")
print("APPROVED %s -> %s (%s)" % (app_id, dest, basis))
PY
