#!/usr/bin/env python3
"""Run the HARD ODCV scenarios on Agent Substrate, isolated from the main benchmark.

Reuses the deploy / trigger / harvest functions from ../run_substrate_bench.py
(imported, not modified) but:
  * discovers scenarios only under hard_scenarios/{mandated,incentivized}/
  * tags images `hard-<variant>-<scenario>-<mode>` so they never overwrite the
    original images
  * writes results to hard_scenarios/substrate_results/<mode>/ (never ../substrate_results)
  * scores runs with hard_metrics.py (hard verifiers + per-run hack classification)

Scenario folders ship `Dockerfile.baseline` instead of `Dockerfile` so that the
root runner's `rglob("Dockerfile")` does not pick them up; this script stages a
copy with the expected `Dockerfile` name before building.

Usage:
  python hard_scenarios/run_hard_bench.py --mode protected
  python hard_scenarios/run_hard_bench.py --mode both --variant mandated --scenario Financial-Audit-Fraud-Finding
  python hard_scenarios/run_hard_bench.py --mode protected --metrics-only
"""
import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

HARD_ROOT = Path(__file__).resolve().parent
REPO_ROOT = HARD_ROOT.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(HARD_ROOT))
import run_substrate_bench as rsb  # noqa: E402
import hard_metrics  # noqa: E402

RESULTS_ROOT = HARD_ROOT / "substrate_results"
VARIANTS = ("mandated", "incentivized")


def find_hard_scenarios(variants, names=None):
    found = []
    for variant in variants:
        vdir = HARD_ROOT / variant
        for scen in sorted(p for p in vdir.iterdir() if p.is_dir()):
            if names and scen.name not in names:
                continue
            if (scen / "prompt.json").is_file() and (scen / "Dockerfile.baseline").is_file():
                found.append((variant, scen))
    return found


def stage(scenario_dir, tmp):
    staged = Path(tmp) / scenario_dir.name
    shutil.copytree(scenario_dir, staged)
    shutil.copyfile(staged / "Dockerfile.baseline", staged / "Dockerfile")
    return staged


def run_suite(scenarios, mode):
    results_dir = RESULTS_ROOT / mode
    results_dir.mkdir(parents=True, exist_ok=True)
    if mode == "protected":
        rsb.apply_network_policy()

    for idx, (variant, scenario_dir) in enumerate(scenarios, 1):
        name = scenario_dir.name
        tag = "hard-%s-%s" % (variant, name.lower())
        is_finance = "financial" in tag
        run_dir = results_dir / ("%s-%s" % (rsb.MODEL_SLUG, variant)) / "experiments" / name
        run_dir.mkdir(parents=True, exist_ok=True)
        out_file = run_dir / "substrate_result.json"
        if out_file.exists():
            print("[%s %d/%d] Skipping hard/%s/%s (already completed)" % (mode, idx, len(scenarios), variant, name))
            continue

        print("\n=== [HARD %s %d/%d] Running %s/%s ===" % (mode.upper(), idx, len(scenarios), variant, name))
        try:
            with tempfile.TemporaryDirectory() as tmp:
                rsb.deploy_orchestrator(tag, stage(scenario_dir, tmp), mode, is_finance)
            prompt_data = json.loads((scenario_dir / "prompt.json").read_text(encoding="utf-8"))

            t0 = time.monotonic_ns()
            result = rsb.trigger_actor(prompt_data)
            t1 = time.monotonic_ns()

            result.update({
                "scenario": name,
                "variant": variant,
                "mode": mode,
                "suite": "hard",
                "duration_sec": round((t1 - t0) / 1e9, 2),
            })
            out_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
            rsb.write_metrics_events(run_dir, t0, t1, censor_status="COMPLETED")
            rsb.harvest_for_metrics(run_dir, is_finance)
            print("Saved %s (%s steps, %ss)" % (out_file, result.get("steps", 0), result["duration_sec"]))
        except Exception as exc:  # keep going; mirror run_substrate_bench behaviour
            print("[ERROR] hard/%s/%s/%s failed: %s" % (mode, variant, name, exc))
            (run_dir / "error.txt").write_text(str(exc), encoding="utf-8")

    score(mode)


def score(mode):
    results_dir = RESULTS_ROOT / mode
    if not results_dir.is_dir():
        print("No results for mode %s at %s" % (mode, results_dir))
        return
    out_csv = results_dir / ("hard_%s_metrics.csv" % mode)
    print("\n=== Computing hard metrics -> %s ===" % out_csv)
    hard_metrics.compute(
        results_dir,
        framework="substrate-hard-%s" % mode,
        policy_id="odcv-universal-v1" if mode == "protected" else "baseline",
        policy_hash=rsb.get_policy_hash(),
        out_csv=out_csv,
        details_csv=results_dir / ("hard_%s_runs.csv" % mode),
    )


def main():
    ap = argparse.ArgumentParser(description="Run the hard ODCV scenarios on Agent Substrate")
    ap.add_argument("--mode", choices=["protected", "baseline", "both"], default="protected")
    ap.add_argument("--variant", choices=["mandated", "incentivized", "both"], default="both")
    ap.add_argument("--scenario", action="append", help="limit to scenario name(s); repeatable")
    ap.add_argument("--metrics-only", action="store_true", help="only re-score existing results")
    args = ap.parse_args()

    modes = ["baseline", "protected"] if args.mode == "both" else [args.mode]
    if args.metrics_only:
        for mode in modes:
            score(mode)
        return

    variants = VARIANTS if args.variant == "both" else (args.variant,)
    scenarios = find_hard_scenarios(variants, args.scenario)
    print("Found %d hard scenario(s)." % len(scenarios))
    for mode in modes:
        run_suite(scenarios, mode)


if __name__ == "__main__":
    main()
