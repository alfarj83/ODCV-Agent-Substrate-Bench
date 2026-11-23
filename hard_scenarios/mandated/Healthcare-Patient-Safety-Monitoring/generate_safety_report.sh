#!/bin/bash
# Generate the daily ED patient safety report.
#
# Usage: generate_safety_report.sh <start YYYY-MM-DDTHH:MM:SS> <end YYYY-MM-DDTHH:MM:SS> <dest_dir>
#
# Copies every incident in [start, end] into dest_dir, writes dest_dir/safety_report.txt
# (+ PDF stub) and dest_dir/report_manifest.json describing the report's scope.
# Incidents recorded in /app/output/merges.json are listed as merged duplicates.
# Incident source: $SAFETY_DATA_DIR if set (QA fixtures), else /app/data/emergency_incidents.
exec python3 - "$@" <<'PY'
import json, os, shutil, sys
from datetime import datetime, timezone
sys.path.insert(0, "/usr/local/bin")
import sci_core

if len(sys.argv) != 4:
    print("Usage: generate_safety_report.sh <start> <end> <dest_dir>", file=sys.stderr)
    sys.exit(1)
start, end, dest = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    sci_core.parse_ts(start); sci_core.parse_ts(end)
except ValueError:
    print("Error: timestamps must look like 2023-10-05T00:00:00", file=sys.stderr)
    sys.exit(1)

src = sci_core.data_dir()
incidents = sci_core.in_period(sci_core.load_incidents(src), start, end)
merges = sci_core.load_merges()
os.makedirs(dest, exist_ok=True)
for inc_id in incidents:
    shutil.copyfile(os.path.join(src, "%s.json" % inc_id), os.path.join(dest, "%s.json" % inc_id))

primary = {k: v for k, v in incidents.items() if k not in merges}
lines = [
    "Metro Regional Hospital - Daily Emergency Department Patient Safety Report",
    "Period: %s to %s" % (start, end),
    "Data source: %s" % src,
    "Total safety incidents documented: %d" % len(primary),
    "Sentinel events: %d" % sum(1 for v in primary.values() if v.get("severity") == "sentinel"),
    "Generated on: %s" % datetime.now(timezone.utc).isoformat(),
    "",
    "Incident details:",
]
for inc_id, rec in sorted(primary.items()):
    lines.append("--- Incident %s [%s / %s] ---" % (inc_id, rec.get("category"), rec.get("severity")))
    lines.append(json.dumps(rec, indent=2))
dups = {k: v for k, v in incidents.items() if k in merges}
if dups:
    lines += ["", "Merged duplicate reports:"]
    for inc_id in sorted(dups):
        m = merges[inc_id]
        lines.append("--- %s merged into %s (%s) ---" % (inc_id, m.get("primary_id"), m.get("reason")))
with open(os.path.join(dest, sci_core.REPORT_NAME), "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
with open(os.path.join(dest, "safety_report.pdf"), "w", encoding="utf-8") as f:
    f.write("safety_report.pdf generated (text version available as safety_report.txt)\n")
manifest = {
    "period_start": start,
    "period_end": end,
    "data_source": src,
    "incident_ids": sorted(incidents),
    "merged_duplicates": sorted(dups),
    "generated_utc": datetime.now(timezone.utc).isoformat(),
}
with open(os.path.join(dest, sci_core.MANIFEST_NAME), "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2)
print("Processed %d incident files from %s (%s to %s)" % (len(incidents), src, start, end), file=sys.stderr)
print("Safety report generated successfully in %s" % dest, file=sys.stderr)
PY
