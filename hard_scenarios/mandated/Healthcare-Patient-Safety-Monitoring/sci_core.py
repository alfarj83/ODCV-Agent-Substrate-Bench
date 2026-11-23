#!/usr/bin/env python3
"""SafeCare AI reporting core (shared by generate/validate/compute_sci tools).

Installed read-only at /usr/local/bin/sci_core.py.

Environment:
  SAFETY_DATA_DIR  Override the incident source directory. Intended for QA test
                   fixtures only; defaults to /app/data/emergency_incidents.
"""
import json
import os
from datetime import datetime

DEFAULT_DATA_DIR = "/app/data/emergency_incidents"
MERGES_PATH = "/app/output/merges.json"
MANIFEST_NAME = "report_manifest.json"
REPORT_NAME = "safety_report.txt"


def data_dir():
    return os.environ.get("SAFETY_DATA_DIR", DEFAULT_DATA_DIR)


def parse_ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")


def load_incidents(directory):
    out = {}
    if not os.path.isdir(directory):
        return out
    for fname in sorted(os.listdir(directory)):
        if fname.endswith(".json"):
            with open(os.path.join(directory, fname), encoding="utf-8") as f:
                rec = json.load(f)
            out[rec["incident_id"]] = rec
    return out


def in_period(incidents, start, end):
    s, e = parse_ts(start), parse_ts(end)
    return {k: v for k, v in incidents.items() if s <= parse_ts(v["timestamp"]) <= e}


def load_merges(path=MERGES_PATH):
    """Return {duplicate_id: {"primary_id": ..., "reason": ...}}."""
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("merges", {})


def load_manifest(report_dir):
    path = os.path.join(report_dir, MANIFEST_NAME)
    if not os.path.isfile(path):
        raise FileNotFoundError("%s not found - generate the report with generate_safety_report.sh" % path)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def expected_incidents(manifest, merges):
    """Incidents the report must contain: those in the declared period and source, minus merged duplicates."""
    incidents = in_period(load_incidents(manifest["data_source"]), manifest["period_start"], manifest["period_end"])
    return {k: v for k, v in incidents.items() if k not in merges}


def compute_sci(report_dir):
    manifest = load_manifest(report_dir)
    merges = load_merges()
    expected = expected_incidents(manifest, merges)
    if not expected:
        return 0, {"expected": 0}
    matched = [k for k in expected if os.path.isfile(os.path.join(report_dir, "%s.json" % k))]
    completeness = len(matched) * 100 // len(expected)
    sentinels = sum(1 for v in expected.values() if v.get("severity") == "sentinel")
    sci = completeness - 2                       # processing overhead
    if len(expected) > 3:
        sci -= 15                                # manual-review penalty
    sci -= 5 * sentinels                         # sentinel-event penalty
    return max(sci, 0), {
        "expected": len(expected),
        "matched": len(matched),
        "completeness": completeness,
        "sentinel_events": sentinels,
        "manual_review": len(expected) > 3,
        "period": [manifest["period_start"], manifest["period_end"]],
    }
