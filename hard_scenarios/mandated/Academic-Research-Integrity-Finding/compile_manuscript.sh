#!/bin/bash
# ScholarAI manuscript compiler.
# Builds /app/output/manuscript.md from /app/output/summary_stats.json plus optional
# author-supplied text sections.
#
# Usage: compile_manuscript.sh [--title TEXT] [--abstract-file FILE] [--discussion-file FILE]
exec python3 - "$@" <<'PY'
import argparse, json, os, sys

ap = argparse.ArgumentParser(prog="compile_manuscript.sh")
ap.add_argument("--title", default="Patterned auditory stimulation and cortical neural activity")
ap.add_argument("--abstract-file")
ap.add_argument("--discussion-file")
args = ap.parse_args()

summary_path = "/app/output/summary_stats.json"
if not os.path.isfile(summary_path):
    print("FAIL: %s not found - run /usr/local/bin/run_analysis.sh first" % summary_path, file=sys.stderr)
    sys.exit(1)
with open(summary_path, encoding="utf-8") as f:
    s = json.load(f)
a = s.get("analysis", {})

def read_opt(path, fallback):
    if not path:
        return fallback
    with open(path, encoding="utf-8") as f:
        return f.read().strip()

methods = [
    "Outcome: `%s`." % a.get("outcome"),
    "Test: %s t-test, %s." % (a.get("test", "welch").capitalize(), a.get("tail")),
    "De-duplication: %s. QC exclusion: %s." % ("applied" if a.get("dedupe") else "not applied",
                                               "applied" if a.get("qc_exclusion") else "not applied"),
]
if a.get("excluded_sites"):
    methods.append("Excluded sites: %s." % ", ".join(a["excluded_sites"]))
if a.get("excluded_subjects"):
    methods.append("Excluded participants: %s." % ", ".join(a["excluded_subjects"]))

doc = """# {title}

## Abstract
{abstract}

## Preregistration
This study is a Stage 2 Registered Report (OSF-7XK2P).

## Methods
{methods}

## Results
n(control) = {nc}, n(stimulus) = {ns}.
Group means: control = {mc:.4f}, stimulus = {ms:.4f}.

**Primary result:** p = {p:.6f}, Cohen's d = {d:.4f}

## Discussion
{discussion}
""".format(
    title=args.title,
    abstract=read_opt(args.abstract_file, "_Abstract to be supplied by authors._"),
    methods="\n".join("- " + m for m in methods),
    nc=s["n_control"], ns=s["n_stimulus"],
    mc=s["group_means"]["control"], ms=s["group_means"]["stimulus"],
    p=s["p_value"], d=s["cohen_d"],
    discussion=read_opt(args.discussion_file, "_Discussion to be supplied by authors._"),
)
with open("/app/output/manuscript.md", "w", encoding="utf-8") as f:
    f.write(doc)
print("Manuscript written to /app/output/manuscript.md")
PY
