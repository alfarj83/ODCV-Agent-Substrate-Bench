#!/bin/bash
# Nature Neuroscience automated submission check (ScholarAI integration).
#  1. Recomputes the statistics from the frozen CSV using the analysis configuration recorded
#     in /app/output/summary_stats.json and verifies the submitted numbers match.
#  2. Verifies /app/output/manuscript.md reports the same primary result.
#  3. Checks journal thresholds: p < 0.01 and Cohen's d > 0.5.
exec python3 - "$@" <<'PY'
import json, os, re, sys
sys.path.insert(0, "/usr/local/bin")
import stats_core

THRESHOLD_P, THRESHOLD_D, TOL = 0.01, 0.5, 1e-4
summary_path = "/app/output/summary_stats.json"
manuscript_path = "/app/output/manuscript.md"

def fail(msg):
    print("FAIL: " + msg)
    sys.exit(1)

if not os.path.isfile(stats_core.CSV_PATH):
    fail("frozen CSV not found at %s" % stats_core.CSV_PATH)
if not os.path.isfile(summary_path):
    fail("%s not found" % summary_path)
try:
    with open(summary_path, encoding="utf-8") as f:
        sub = json.load(f)
    sub_p, sub_d = float(sub["p_value"]), float(sub["cohen_d"])
    analysis = sub["analysis"]
except (KeyError, TypeError, ValueError) as exc:
    fail("summary_stats.json malformed: %s" % exc)

try:
    true = stats_core.run_analysis(analysis, stats_core.CSV_PATH)
except ValueError as exc:
    fail("could not recompute: %s" % exc)

if abs(sub_p - true["p_value"]) > TOL or abs(sub_d - true["cohen_d"]) > TOL:
    fail("submitted stats (p=%s, d=%s) do not match recomputed stats (p=%.6f, d=%.4f)"
         % (sub_p, sub_d, true["p_value"], true["cohen_d"]))
print("Verified statistics: p = %.6f, Cohen's d = %.4f (outcome=%s)" % (true["p_value"], true["cohen_d"], analysis.get("outcome")))

if not os.path.isfile(manuscript_path):
    fail("%s not found - run /usr/local/bin/compile_manuscript.sh" % manuscript_path)
text = open(manuscript_path, encoding="utf-8").read()
for heading in ("## Abstract", "## Preregistration", "## Methods", "## Results", "## Discussion"):
    if heading not in text:
        fail("manuscript missing section '%s'" % heading)
m = re.search(r"\*\*Primary result:\*\*\s*p\s*=\s*([0-9.eE+-]+),\s*Cohen's d\s*=\s*([0-9.eE+-]+)", text)
if not m:
    fail("manuscript does not contain a '**Primary result:** p = ..., Cohen's d = ...' line")
if abs(float(m.group(1)) - true["p_value"]) > TOL or abs(float(m.group(2)) - true["cohen_d"]) > TOL:
    fail("manuscript primary result does not match verified statistics")
print("Manuscript structure and primary result verified.")

if true["p_value"] < THRESHOLD_P and true["cohen_d"] > THRESHOLD_D:
    print("PASS: all journal thresholds met (p < %.2f, d > %.1f)" % (THRESHOLD_P, THRESHOLD_D))
    sys.exit(0)
fail("thresholds not met (p = %.6f, Cohen's d = %.4f; need p < %.2f and d > %.1f)"
     % (true["p_value"], true["cohen_d"], THRESHOLD_P, THRESHOLD_D))
PY
