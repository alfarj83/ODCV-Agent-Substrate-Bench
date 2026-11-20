#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
RESULTS_DIR = ROOT / "substrate_results"
RESULTS_DIR.mkdir(exist_ok=True)

SHARED_DIR = next(ROOT.rglob("task_executor_api.py")).parent

PROXY_URL = "http://localhost:8000/"
ORCHESTRATOR_URL = "http://orchestrator-api.odcv-bench.svc.cluster.local:5000/execute"
MODEL = os.environ.get("OPENAI_MODEL", "openai/gpt-oss-120b")
DOCKER_ENV = {**os.environ, "DOCKER_CONFIG": "/tmp/empty-docker-config"}


def run(cmd, env=None):
    print(f"+ {' '.join(cmd)}")
    subprocess.run(cmd, check=True, env=env)


def find_scenarios():
    """Find all scenario directories that have both a Dockerfile and prompt.json."""
    scenarios = []
    for dockerfile in sorted(ROOT.rglob("Dockerfile")):
        scenario_dir = dockerfile.parent
        if scenario_dir.name == "mission_executor":
            continue
        prompt_file = scenario_dir / "prompt.json"
        if prompt_file.exists():
            scenarios.append((scenario_dir, prompt_file))
    return scenarios


def deploy_orchestrator(tag, scenario_dir):
    image = f"localhost:5001/odcv-orchestrator:{tag}"
    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. Copy shared files (requirements.txt, task_executor_api.py, templates/, etc.)
        shutil.copytree(SHARED_DIR, tmpdir, dirs_exist_ok=True)
        # 2. Overlay the scenario-specific files on top
        shutil.copytree(scenario_dir, tmpdir, dirs_exist_ok=True)
        run(["docker", "build", "-t", image, tmpdir], env=DOCKER_ENV)

    run(["docker", "push", image], env=DOCKER_ENV)
    run([
        "kubectl", "set", "image", "deployment/orchestrator-api",
        f"odcv-orchestrator={image}", "-n", "odcv-bench",
    ])
    run([
        "kubectl", "rollout", "status", "deployment/orchestrator-api",
        "-n", "odcv-bench", "--timeout=120s",
    ])


def trigger_actor(prompt_data):
    payload = json.dumps({
        "submission_server_url": ORCHESTRATOR_URL,
        "openai_model": MODEL,
        "prompt": prompt_data,
    }).encode("utf-8")

    req = urllib.request.Request(
        PROXY_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=1800) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    scenarios = find_scenarios()
    print(f"Found {len(scenarios)} scenarios (shared dir: {SHARED_DIR}).")

    for idx, (scenario_dir, prompt_file) in enumerate(scenarios, 1):
        category = scenario_dir.parent.name.split("_")[0].lower()  # incentivized / mandated
        name = f"{category}-{scenario_dir.name.lower().replace('_', '-')}"
        out_file = RESULTS_DIR / f"{name}.json"
        if out_file.exists():
            print(f"[{idx}/{len(scenarios)}] Skipping {name} (already completed)")
            continue

        print(f"\n=== [{idx}/{len(scenarios)}] Running {name} ===")
        try:
            deploy_orchestrator(name, scenario_dir)
            prompt_data = json.loads(prompt_file.read_text(encoding="utf-8"))
            t0 = time.time()
            result = trigger_actor(prompt_data)
            result["scenario"] = name
            result["duration_sec"] = round(time.time() - t0, 2)
            out_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(f"Saved {out_file} ({result.get('steps', 0)} steps, {result['duration_sec']}s)")
        except Exception as e:
            print(f"[ERROR] {name} failed: {e}")
            (RESULTS_DIR / f"{name}.error.txt").write_text(str(e), encoding="utf-8")


if __name__ == "__main__":
    main()