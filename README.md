# ODCV-Agent-Substrate-Bench

[![arXiv](https://img.shields.io/badge/arXiv-2512.20798-b31b1b.svg)](https://arxiv.org/abs/2512.20798)

**ODCV-Agent-Substrate-Bench** adapts [ODCV-Bench](https://odcvbenchmark.github.io) (Outcome-Driven Constraint Violations in Autonomous AI Agents) to run on **Agent Substrate** and evaluates infrastructure-level security containment alongside behavioral alignment.

While the original benchmark executes untrusted agents in standard Docker Compose containers with live API keys and open egress, this fork isolates the agent inside a default-deny, zero-credential Agent Substrate Actor, hardens the scenario execution pods under the **`odcv-universal-v1`** policy, and introduces deterministic security and alignment metrics via `metrics.py`.

---

## What's New in This Fork

- **Agent Substrate Isolation**: Runs the agent harness (`mission_executor`) as a non-root, SHA-256 digest-pinned Substrate Actor on Kubernetes (`kind`), with `OPENROUTER_API_KEY` stored in a Kubernetes Secret and injected dynamically by `atenet-egress` (zero credentials inside the sandbox).
- **Protected Scenarios (`Dockerfile.protected`)**: Pairs baseline permissive `Dockerfile`s with hardened `Dockerfile.protected` builds across 3 core domains (**Academic Research Integrity**, **Financial Audit Fraud**, and **Healthcare Patient Safety Monitoring**) in both `mandated_scenarios/` and `incentivized_scenarios/` (6 scenarios total).
- **Universal Policy Enforcement (`odcv-universal-v1`)**: Enforces read-only source data, restricted writable mounts, non-root execution (`UID 1000`), default-deny egress (`NetworkPolicy` + `EgressPolicy`), fail-closed behavior, and out-of-sandbox audit logging identically across mandated and incentivized variants.
- **Automated A/B Runner (`run_substrate_bench.py`)**: Dynamically extracts `orchestrator_api.zip`, builds and pushes scenario images to a local registry (`localhost:5001`), deploys hardened or baseline Kubernetes pods, triggers the Substrate Actor proxy, harvests out-of-sandbox logs and `/app/output` artifacts, and invokes `metrics.py`.
- **Unified Security & Alignment Metrics (`metrics.py`)**: Computes **Control Hold Rate (CHR)**, **Time-to-Violation** (`wall_ms` / `active_ms` with censoring), **Completion Gap**, **Pressure Retention** (`CHR_high / CHR_low`), and **deterministic ground-truth recompute verification** from untouched source data.

---

## Architecture Comparison

| Dimension | Original ODCV-Bench (`docker-compose`) | ODCV-Agent-Substrate-Bench |
| :--- | :--- | :--- |
| **Agent Runtime** | Standard Docker container (`mission_executor`) | Hardened, digest-pinned Agent Substrate Actor (`odcv-mission-executor`) |
| **API Credentials** | `OPENROUTER_API_KEY` passed as container env var | **Zero credentials in sandbox**; injected by `atenet-egress` from K8s `Secret` |
| **Network Egress** | Default-allow outbound internet | **Default-deny** (`EgressPolicy` on Actor + `NetworkPolicy` on `orchestrator-api`) |
| **Scenario Hardening** | Permissive filesystem (allows data/script tampering) | `Dockerfile.protected` + `readOnlyRootFilesystem: true`, `runAsUser: 1000`, scoped `emptyDir` mounts |
| **Evaluation** | LLM-as-a-judge rubric (0–5) | Original LLM judges **plus** `metrics.py` (CHR, Completion Gap, Pressure Retention, ground-truth recompute) |

---

## Project Structure

```text
.
├── mandated_scenarios/                  # Mandated KPI scenarios (Dockerfile + Dockerfile.protected + prompt.json)
│   ├── Academic-Research-Integrity-Finding/
│   ├── Financial-Audit-Fraud-Finding/
│   └── Healthcare-Patient-Safety-Monitoring/
├── incentivized_scenarios/              # Incentivized KPI scenarios (same 3 domains)
│   ├── Academic-Research-Integrity-Finding/
│   ├── Financial-Audit-Fraud-Finding/
│   └── Healthcare-Patient-Safety-Monitoring/
│
├── mission_executor/                    # Containerized agent harness + Substrate HTTP wrapper (actor_server.py)
├── orchestrator_api.zip                 # Shared sandboxed bash execution API (task_executor_api.py + templates/)
├── odcv-actor-template.yaml             # Agent Substrate ActorTemplate (digest-pinned)
├── odcv-egress-policy.yaml              # Agent Substrate EgressPolicy (OpenRouter + orchestrator-api only)
│
├── run_substrate_bench.py               # Automated Agent Substrate benchmark runner (--mode baseline|protected|both)
├── metrics.py                           # Unified security & alignment metrics + scenario recompute verifiers
├── baseline_metrics.csv                 # Baseline metrics summary
├── substrate_results/                   # Outputs from Agent Substrate runs (baseline/ & protected/)
│
├── existing_results/                    # Original ODCV-Bench paper logs & multi-judge evaluations
├── odcv_bench/                          # Original Inspect AI task package
├── pyproject.toml                       # Makes odcv_bench pip-installable
├── run_model.py                         # Original single-model Docker Compose entry point
├── run_experiments.py                   # Original 12-model manifest runner
├── run_benchmarks.py                    # Original sub-orchestrator for scenario iteration
├── run.py                               # Original Docker Compose & artifact collector
├── docker-compose.yml                   # Original Docker Compose config
├── evaluate_all_results.py              # Original AI judge script for scoring trajectories
├── evaluate_batch.py                    # Original parallelized multi-judge + self-eval runner
├── compute_final_scores.py              # Original median score & paper table generator
├── bootstrap_ci.py                      # Bootstrap 95% CIs for MR and Sev
├── paired_bootstrap.py                  # Paired-bootstrap CIs for cross-model and temporal contrasts
├── compute_paper_stats.py               # Krippendorff's alpha and summary statistics
├── retry_missing.py                     # Retry specific failed scenarios
├── LICENSE                              # MIT License
└── README.md                            # This file