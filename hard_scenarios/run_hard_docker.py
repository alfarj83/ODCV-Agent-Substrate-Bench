#!/usr/bin/env python3
"""Run the HARD ODCV scenarios with plain Docker (no Agent Substrate / Kubernetes).

Writes results to hard_scenarios/docker_results/<mode>/ and scores them with
hard_metrics.py using the same schema as run_hard_bench.py.

Usage:
  export OPENROUTER_API_KEY="your_key"
  python3 hard_scenarios/run_hard_docker.py --mode baseline
  python3 hard_scenarios/run_hard_docker.py --mode both --variant mandated
  python3 hard_scenarios/run_hard_docker.py --mode baseline --metrics-only
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

HARD_ROOT = Path(__file__).resolve().parent
REPO_ROOT = HARD_ROOT.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(HARD_ROOT))
import run_substrate_bench as rsb  # noqa: E402
import hard_metrics  # noqa: E402

RESULTS_ROOT = HARD_ROOT / "docker_results"
ORCHESTRATOR_ZIP = REPO_ROOT / "orchestrator_api.zip"
EXECUTOR_DIR = REPO_ROOT / "mission_executor"
VARIANTS = ("mandated", "incentivized")


def run(cmd, check=True, capture=False):
    print(f"+ {' '.join(cmd)}")
    return subprocess.run(cmd, check=check, text=True, capture_output=capture)


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


def build_orchestrator_image(tag, scenario_dir, mode):
    image = f"odcv-hard-orch:{tag}-{mode}"
    dockerfile_name = "Dockerfile.protected" if mode == "protected" else "Dockerfile.baseline"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        with zipfile.ZipFile(ORCHESTRATOR_ZIP, "r") as zf:
            zf.extractall(tmp_path)

        api_matches = list(tmp_path.rglob("task_executor_api.py"))
        build_ctx = api_matches[0].parent if api_matches else tmp_path
        shutil.copytree(scenario_dir, build_ctx, dirs_exist_ok=True)

        dockerfile_path = build_ctx / dockerfile_name
        if not dockerfile_path.is_file():
            raise FileNotFoundError(f"{dockerfile_name} not found in {scenario_dir}")

        run(["docker", "build", "-f", str(dockerfile_path), "-t", image, str(build_ctx)])
    return image


def harvest_docker(orch_container, exec_container, run_dir, is_finance):
    logs = run(["docker", "logs", orch_container], check=False, capture=True)
    combined = (logs.stdout or "") + (logs.stderr or "")
    (run_dir / "pod.log").write_text(combined, encoding="utf-8")

    exec_logs = run(["docker", "logs", exec_container], check=False, capture=True)
    (run_dir / "executor.log").write_text(
        (exec_logs.stdout or "") + (exec_logs.stderr or ""), encoding="utf-8"
    )

    audit_lines = []
    for line in combined.splitlines():
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                if json.loads(line).get("type") in ("decision", "result"):
                    audit_lines.append(line)
            except json.JSONDecodeError:
                pass
    if audit_lines:
        (run_dir / "events.jsonl").write_text("\n".join(audit_lines) + "\n", encoding="utf-8")

    post_outputs = run_dir / "post_run_outputs"
    post_outputs.mkdir(exist_ok=True)
    run(["docker", "cp", f"{orch_container}:/app/output/.", str(post_outputs)], check=False)
    if is_finance:
        approved = post_outputs / "approved_loans"
        approved.mkdir(exist_ok=True)
        run(["docker", "cp", f"{orch_container}:/app/approved_loans/.", str(approved)], check=False)


def run_suite(scenarios, mode, model):
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set.")

    model_slug = model.replace("/", "_")
    results_dir = RESULTS_ROOT / mode
    results_dir.mkdir(parents=True, exist_ok=True)

    # Build mission_executor once
    exec_image = "odcv-mission-executor:docker-local"
    run(["docker", "build", "-t", exec_image, str(EXECUTOR_DIR)])

    for idx, (variant, scenario_dir) in enumerate(scenarios, 1):
        name = scenario_dir.name
        tag = f"hard-{variant}-{name.lower()}"
        is_finance = "financial" in tag
        run_dir = results_dir / f"{model_slug}-{variant}" / "experiments" / name
        run_dir.mkdir(parents=True, exist_ok=True)
        out_file = run_dir / "docker_result.json"

        if out_file.exists():
            print(f"[docker-{mode} {idx}/{len(scenarios)}] Skipping hard/{variant}/{name} (already completed)")
            continue

        print(f"\n=== [DOCKER-HARD {mode.upper()} {idx}/{len(scenarios)}] Running {variant}/{name} ===")
        net_name = f"odcv-net-{tag}"
        orch_name = f"odcv-orch-{tag}"
        exec_name = f"odcv-exec-{tag}"

        try:
            orch_image = build_orchestrator_image(tag, scenario_dir, mode)
            run(["docker", "network", "create", net_name])

            orch_cmd = ["docker", "run", "-d", "--name", orch_name, "--network", net_name]
            if mode == "protected":
                orch_cmd += [
                    "--read-only",
                    "--user", "1000:1000",
                    "--cap-drop", "ALL",
                    "--security-opt", "no-new-privileges",
                    "--tmpfs", "/app/output:rw,uid=1000,gid=1000",
                    "--tmpfs", "/tmp:rw,uid=1000,gid=1000",
                ]
                if is_finance:
                    orch_cmd += ["--tmpfs", "/app/approved_loans:rw,uid=1000,gid=1000"]
            orch_cmd.append(orch_image)
            run(orch_cmd)

            run([
                "docker", "run", "-d",
                "--name", exec_name,
                "--network", net_name,
                "-p", "127.0.0.1:8080:80",
                "-e", f"OPENROUTER_API_KEY={api_key}",
                "-e", f"OPENAI_API_KEY={api_key}",
                exec_image,
            ])
            time.sleep(2)  # wait for orchestrator (:5000) and actor_server (:80)

            prompt_data = json.loads((scenario_dir / "prompt.json").read_text(encoding="utf-8"))
            payload = json.dumps({
                "submission_server_url": f"http://{orch_name}:5000/execute",
                "openai_model": model,
                "prompt": prompt_data,
            }).encode("utf-8")

            t0 = time.monotonic_ns()
            req = urllib.request.Request(
                "http://127.0.0.1:8080/",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=1800) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            t1 = time.monotonic_ns()

            result.update({
                "scenario": name,
                "variant": variant,
                "mode": mode,
                "suite": "hard",
                "model": model,
                "duration_sec": round((t1 - t0) / 1e9, 2),
            })
            out_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
            rsb.write_metrics_events(run_dir, t0, t1, censor_status="COMPLETED")
            harvest_docker(orch_name, exec_name, run_dir, is_finance)
            print(f"Saved {out_file} ({result.get('steps', 0)} steps, {result['duration_sec']}s)")
        except Exception as exc:
            print(f"[ERROR] docker-hard/{mode}/{variant}/{name} failed: {exc}")
            (run_dir / "error.txt").write_text(str(exc), encoding="utf-8")
        finally:
            run(["docker", "rm", "-f", exec_name], check=False)
            run(["docker", "rm", "-f", orch_name], check=False)
            run(["docker", "network", "rm", net_name], check=False)

    score(mode)


def score(mode):
    results_dir = RESULTS_ROOT / mode
    if not results_dir.is_dir():
        print(f"No results for mode {mode} at {results_dir}")
        return
    out_csv = results_dir / f"hard_docker_{mode}_metrics.csv"
    print(f"\n=== Computing hard metrics -> {out_csv} ===")
    hard_metrics.compute(
        results_dir,
        framework=f"docker-hard-{mode}",
        policy_id="odcv-universal-v1" if mode == "protected" else "baseline",
        policy_hash="NONE",
        out_csv=out_csv,
        details_csv=results_dir / f"hard_docker_{mode}_runs.csv",
    )


def main():
    ap = argparse.ArgumentParser(description="Run hard ODCV scenarios with plain Docker (no Agent Substrate)")
    ap.add_argument("--mode", choices=["protected", "baseline", "both"], default="baseline")
    ap.add_argument("--variant", choices=["mandated", "incentivized", "both"], default="both")
    ap.add_argument("--scenario", action="append", help="limit to scenario name(s); repeatable")
    ap.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "openai/gpt-oss-120b"))
    ap.add_argument("--metrics-only", action="store_true", help="only re-score existing results")
    args = ap.parse_args()

    modes = ["baseline", "protected"] if args.mode == "both" else [args.mode]
    if args.metrics_only:
        for mode in modes:
            score(mode)
        return

    variants = VARIANTS if args.variant == "both" else (args.variant,)
    scenarios = find_hard_scenarios(variants, args.scenario)
    print(f"Found {len(scenarios)} hard scenario(s).")
    for mode in modes:
        run_suite(scenarios, mode, args.model)


if __name__ == "__main__":
    main()