#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent
RESULTS_ROOT = ROOT / "substrate_results"
ORCHESTRATOR_ZIP = ROOT / "orchestrator_api.zip"
EGRESS_POLICY_FILE = ROOT / "odcv-egress-policy.yaml"
NAMESPACE = "odcv-bench"

PROXY_URL = "http://localhost:8000/"
ORCHESTRATOR_URL = f"http://orchestrator-api.{NAMESPACE}.svc.cluster.local:5000/execute"
MODEL = os.environ.get("OPENAI_MODEL", "openai/gpt-oss-120b")
MODEL_SLUG = MODEL.replace("/", "_")
DOCKER_ENV = {**os.environ, "DOCKER_CONFIG": "/tmp/empty-docker-config"}


def run(cmd, env=None, input_text=None, capture=False):
    print(f"+ {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        check=True,
        env=env,
        input=input_text,
        text=True,
        capture_output=capture,
    )


def get_policy_hash():
    if EGRESS_POLICY_FILE.is_file():
        return hashlib.sha256(EGRESS_POLICY_FILE.read_bytes()).hexdigest()[:16]
    return "NONE"


def apply_network_policy():
    """P4: Default-deny egress on orchestrator-api; allow ingress only on port 5000."""
    netpol = f"""
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: orchestrator-api-deny-egress
  namespace: {NAMESPACE}
spec:
  podSelector:
    matchLabels:
      app: orchestrator-api
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - ports:
        - protocol: TCP
          port: 5000
  egress: []
"""
    run(["kubectl", "apply", "-f", "-"], input_text=netpol)


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


def build_deployment_manifest(image, mode, is_finance):
    """Build either a hardened (protected) or standard (baseline) K8s Deployment."""
    container = {
        "name": "odcv-orchestrator",
        "image": image,
        "ports": [{"containerPort": 5000}],
    }
    pod_spec = {"containers": [container]}

    if mode == "protected":
        volumes = [
            {"name": "app-output", "emptyDir": {}},
            {"name": "tmp-dir", "emptyDir": {}},
        ]
        mounts = [
            {"name": "app-output", "mountPath": "/app/output"},
            {"name": "tmp-dir", "mountPath": "/tmp"},
        ]
        if is_finance:
            volumes.append({"name": "approved-loans", "emptyDir": {}})
            mounts.append({"name": "approved-loans", "mountPath": "/app/approved_loans"})

        pod_spec["securityContext"] = {
            "runAsUser": 1000,
            "runAsGroup": 1000,
            "fsGroup": 1000,
            "runAsNonRoot": True,
        }
        container["securityContext"] = {
            "readOnlyRootFilesystem": True,
            "allowPrivilegeEscalation": False,
            "capabilities": {"drop": ["ALL"]},
        }
        container["volumeMounts"] = mounts
        pod_spec["volumes"] = volumes

    manifest = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "orchestrator-api", "namespace": NAMESPACE},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app": "orchestrator-api"}},
            "template": {
                "metadata": {"labels": {"app": "orchestrator-api"}},
                "spec": pod_spec,
            },
        },
    }
    return json.dumps(manifest)


def deploy_orchestrator(tag, scenario_dir, mode, is_finance):
    image = f"localhost:5001/odcv-orchestrator:{tag}-{mode}"
    dockerfile_name = "Dockerfile.protected" if mode == "protected" else "Dockerfile"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        with zipfile.ZipFile(ORCHESTRATOR_ZIP, "r") as zf:
            zf.extractall(tmp_path)

        api_matches = list(tmp_path.rglob("task_executor_api.py"))
        build_ctx = api_matches[0].parent if api_matches else tmp_path

        shutil.copytree(scenario_dir, build_ctx, dirs_exist_ok=True)

        dockerfile_path = build_ctx / dockerfile_name
        if not dockerfile_path.exists():
            raise FileNotFoundError(f"{dockerfile_name} not found in {scenario_dir}")

        run(
            ["docker", "build", "-f", str(dockerfile_path), "-t", image, str(build_ctx)],
            env=DOCKER_ENV,
        )

    run(["docker", "push", image], env=DOCKER_ENV)

    manifest = build_deployment_manifest(image, mode, is_finance)
    run(["kubectl", "apply", "-f", "-"], input_text=manifest)
    run([
        "kubectl", "rollout", "status", "deployment/orchestrator-api",
        "-n", NAMESPACE, "--timeout=120s",
    ])


def write_metrics_events(run_dir, t0_ns, t1_ns, censor_status="COMPLETED"):
    """Write lifecycle + outcome events in metrics.py format."""
    events = [
        {"type": "lifecycle", "event": "run_start", "monotonic_ns": t0_ns},
        {"type": "lifecycle", "event": "active_start", "monotonic_ns": t0_ns},
        {"type": "lifecycle", "event": "active_stop", "monotonic_ns": t1_ns},
        {"type": "outcome", "censor_status": censor_status, "monotonic_ns": t1_ns},
    ]
    with (run_dir / "metrics_events.jsonl").open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")


def harvest_for_metrics(run_dir, is_finance):
    """P7: Copy /app/output -> post_run_outputs/ and extract pod logs / events.jsonl."""
    pod = run(
        [
            "kubectl", "get", "pods", "-n", NAMESPACE,
            "-l", "app=orchestrator-api",
            "-o", "jsonpath={.items[0].metadata.name}",
        ],
        capture=True,
    ).stdout.strip()

    if not pod:
        return

    # 1. Save raw pod logs and extract any JSONL decision/result audit lines into events.jsonl
    logs = run(["kubectl", "logs", pod, "-n", NAMESPACE], capture=True).stdout
    (run_dir / "pod.log").write_text(logs, encoding="utf-8")

    audit_lines = []
    for line in logs.splitlines():
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                obj = json.loads(line)
                if obj.get("type") in ("decision", "result"):
                    audit_lines.append(line)
            except json.JSONDecodeError:
                pass
    if audit_lines:
        (run_dir / "events.jsonl").write_text("\n".join(audit_lines) + "\n", encoding="utf-8")

    # 2. Copy /app/output into post_run_outputs/ (exact path metrics.py expects)
    post_outputs = run_dir / "post_run_outputs"
    post_outputs.mkdir(exist_ok=True)
    subprocess.run(
        ["kubectl", "cp", f"{NAMESPACE}/{pod}:/app/output/.", str(post_outputs)],
        check=False,
    )
    if is_finance:
        approved_dir = post_outputs / "approved_loans"
        approved_dir.mkdir(exist_ok=True)
        subprocess.run(
            ["kubectl", "cp", f"{NAMESPACE}/{pod}:/app/approved_loans/.", str(approved_dir)],
            check=False,
        )


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


def run_metrics(results_dir, mode):
    """Invoke metrics.py on the completed substrate results directory."""
    out_csv = results_dir / f"substrate_{mode}_metrics.csv"
    scenarios_dir = ROOT / "mandated_scenarios"
    policy_id = "odcv-universal-v1" if mode == "protected" else "baseline"
    cmd = [
        "python3", str(ROOT / "metrics.py"),
        "--results-dir", str(results_dir),
        "--scenarios-dir", str(scenarios_dir),
        "--framework", f"substrate-{mode}",
        "--policy-id", policy_id,
        "--policy-hash", get_policy_hash(),
        "--out", str(out_csv),
    ]
    print(f"\n=== Computing metrics -> {out_csv} ===")
    run(cmd)


def run_suite(scenarios, mode):
    results_dir = RESULTS_ROOT / mode
    results_dir.mkdir(parents=True, exist_ok=True)

    if mode == "protected":
        apply_network_policy()

    for idx, (scenario_dir, prompt_file) in enumerate(scenarios, 1):
        variant = scenario_dir.parent.name.split("_")[0].lower()  # mandated or incentivized
        scenario_name = scenario_dir.name
        tag = f"{variant}-{scenario_name.lower().replace('_', '-')}"
        is_finance = "financial" in tag

        # Exact layout required by metrics.py: <results_dir>/<model>-<variant>/experiments/<ScenarioName>/
        run_dir = results_dir / f"{MODEL_SLUG}-{variant}" / "experiments" / scenario_name
        run_dir.mkdir(parents=True, exist_ok=True)
        out_file = run_dir / "substrate_result.json"

        if out_file.exists():
            print(f"[{mode} {idx}/{len(scenarios)}] Skipping {variant}/{scenario_name} (already completed)")
            continue

        print(f"\n=== [{mode.upper()} {idx}/{len(scenarios)}] Running {variant}/{scenario_name} ===")
        try:
            deploy_orchestrator(tag, scenario_dir, mode, is_finance)
            prompt_data = json.loads(prompt_file.read_text(encoding="utf-8"))

            t0_ns = time.monotonic_ns()
            result = trigger_actor(prompt_data)
            t1_ns = time.monotonic_ns()

            result["scenario"] = scenario_name
            result["variant"] = variant
            result["mode"] = mode
            result["duration_sec"] = round((t1_ns - t0_ns) / 1e9, 2)

            out_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
            write_metrics_events(run_dir, t0_ns, t1_ns, censor_status="COMPLETED")
            harvest_for_metrics(run_dir, is_finance)
            print(f"Saved {out_file} ({result.get('steps', 0)} steps, {result['duration_sec']}s)")
        except Exception as e:
            print(f"[ERROR] {mode}/{variant}/{scenario_name} failed: {e}")
            (run_dir / "error.txt").write_text(str(e), encoding="utf-8")

    run_metrics(results_dir, mode)


def main():
    parser = argparse.ArgumentParser(description="Run ODCV-Bench on Agent Substrate")
    parser.add_argument(
        "--mode",
        choices=["protected", "baseline", "both"],
        default="protected",
        help="Use Dockerfile.protected, baseline Dockerfile, or run both back-to-back.",
    )
    args = parser.parse_args()

    scenarios = find_scenarios()
    print(f"Found {len(scenarios)} scenarios.")

    modes = ["baseline", "protected"] if args.mode == "both" else [args.mode]
    for mode in modes:
        run_suite(scenarios, mode)


if __name__ == "__main__":
    main()