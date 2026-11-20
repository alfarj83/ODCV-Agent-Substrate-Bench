#!/usr/bin/env python3
import argparse
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
NAMESPACE = "odcv-bench"

PROXY_URL = "http://localhost:8000/"
ORCHESTRATOR_URL = f"http://orchestrator-api.{NAMESPACE}.svc.cluster.local:5000/execute"
MODEL = os.environ.get("OPENAI_MODEL", "openai/gpt-oss-120b")
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


def harvest_artifacts(results_dir, name, is_finance):
    """P7: Pull out-of-sandbox logs and /app/output artifacts before pod swap."""
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

    logs = run(["kubectl", "logs", pod, "-n", NAMESPACE], capture=True).stdout
    (results_dir / f"{name}.pod.log").write_text(logs, encoding="utf-8")

    art_dir = results_dir / f"{name}_artifacts"
    art_dir.mkdir(exist_ok=True)
    subprocess.run(
        ["kubectl", "cp", f"{NAMESPACE}/{pod}:/app/output", str(art_dir / "output")],
        check=False,
    )
    if is_finance:
        subprocess.run(
            ["kubectl", "cp", f"{NAMESPACE}/{pod}:/app/approved_loans", str(art_dir / "approved_loans")],
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


def run_suite(scenarios, mode):
    results_dir = RESULTS_ROOT / mode
    results_dir.mkdir(parents=True, exist_ok=True)

    if mode == "protected":
        apply_network_policy()

    for idx, (scenario_dir, prompt_file) in enumerate(scenarios, 1):
        category = scenario_dir.parent.name.split("_")[0].lower()
        name = f"{category}-{scenario_dir.name.lower().replace('_', '-')}"
        is_finance = "financial" in name
        out_file = results_dir / f"{name}.json"

        if out_file.exists():
            print(f"[{mode} {idx}/{len(scenarios)}] Skipping {name} (already completed)")
            continue

        print(f"\n=== [{mode.upper()} {idx}/{len(scenarios)}] Running {name} ===")
        try:
            deploy_orchestrator(name, scenario_dir, mode, is_finance)
            prompt_data = json.loads(prompt_file.read_text(encoding="utf-8"))

            t0 = time.time()
            result = trigger_actor(prompt_data)
            result["scenario"] = name
            result["mode"] = mode
            result["policy_id"] = "odcv-universal-v1" if mode == "protected" else "baseline"
            result["duration_sec"] = round(time.time() - t0, 2)

            out_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
            harvest_artifacts(results_dir, name, is_finance)
            print(f"Saved {out_file} ({result.get('steps', 0)} steps, {result['duration_sec']}s)")
        except Exception as e:
            print(f"[ERROR] {mode}/{name} failed: {e}")
            (results_dir / f"{name}.error.txt").write_text(str(e), encoding="utf-8")


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