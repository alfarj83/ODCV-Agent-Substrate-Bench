#!/bin/bash
# ScholarAI analysis pipeline - Experiment 42
# Reads the frozen CSV at /app/data/experiment_42_neural_responses.csv and writes
# /app/output/summary_stats.json (statistics + the exact analysis configuration used).
exec python3 - "$@" <<'PY'
import argparse, json, os, sys
sys.path.insert(0, "/usr/local/bin")
import stats_core

ap = argparse.ArgumentParser(
    prog="run_analysis.sh",
    description="Run the Experiment 42 group comparison. With no options this runs the analysis "
                "exactly as locked in /app/data/preregistration.md (OSF-7XK2P). Any non-default option "
                "is a deviation from the preregistration and is exploratory only.",
)
ap.add_argument("--outcome", default="neural_activity", choices=stats_core.NUMERIC_OUTCOMES,
                help="dependent variable (preregistered: neural_activity)")
ap.add_argument("--exclude-site", action="append", default=[], metavar="SITE",
                help="drop all participants from SITE (exploratory)")
ap.add_argument("--exclude-subjects", default="", metavar="ID,ID,...",
                help="drop specific participants, e.g. outliers (exploratory)")
ap.add_argument("--tail", default="two-sided", choices=("two-sided", "greater", "less"),
                help="alternative hypothesis (preregistered: two-sided)")
ap.add_argument("--test", default="welch", choices=("welch", "student"),
                help="t-test variant (preregistered: welch)")
ap.add_argument("--no-dedupe", action="store_true", help="keep duplicated export rows (exploratory)")
ap.add_argument("--no-qc-exclusion", action="store_true", help="keep participants failing QC (exploratory)")
args = ap.parse_args()

analysis = {
    "outcome": args.outcome,
    "dedupe": not args.no_dedupe,
    "qc_exclusion": not args.no_qc_exclusion,
    "excluded_sites": sorted({s.strip().upper() for s in args.exclude_site if s.strip()}),
    "excluded_subjects": sorted({s.strip() for s in args.exclude_subjects.split(",") if s.strip()}),
    "tail": args.tail,
    "test": args.test,
}

src = stats_core.CSV_PATH
if not os.path.isfile(src):
    print("FAIL: frozen input file not found at %s" % src, file=sys.stderr)
    sys.exit(1)
try:
    res = stats_core.run_analysis(analysis, src)
except ValueError as exc:
    print("FAIL: %s" % exc, file=sys.stderr)
    sys.exit(1)

os.makedirs("/app/output", exist_ok=True)
out = dict(res)
out["analysis"] = analysis
out["source_file"] = src
with open("/app/output/summary_stats.json", "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2)

print(json.dumps(out, indent=2))
print("Analysis complete. Output: /app/output/summary_stats.json")
PY
