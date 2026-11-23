#!/usr/bin/env python3
"""Shared statistics core for the ScholarAI analysis pipeline.

Installed read-only at /usr/local/bin/stats_core.py and imported by
run_analysis.sh, compile_manuscript.sh and validate_submission.sh.
Pure Python (3.9+) so it runs without numpy/scipy.
"""
import csv
import math

CSV_PATH = "/app/data/experiment_42_neural_responses.csv"
NUMERIC_OUTCOMES = ("neural_activity", "response_time")


# ---------------------------------------------------------------------------
# Student-t distribution via the regularized incomplete beta function
# ---------------------------------------------------------------------------
def _betacf(a, b, x, max_iter=300, eps=3e-14):
    fpmin = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _betai(a, b, x):
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def t_sf(t, df):
    """Upper-tail probability P(T > t) for Student's t with df degrees of freedom."""
    x = df / (df + t * t)
    tail = 0.5 * _betai(df / 2.0, 0.5, x)
    return tail if t >= 0 else 1.0 - tail


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_rows(path=CSV_PATH):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def select_rows(rows, dedupe=True, qc_exclusion=True, excluded_sites=(), excluded_subjects=()):
    excluded_sites = {s.strip().upper() for s in excluded_sites if s.strip()}
    excluded_subjects = {str(s).strip() for s in excluded_subjects if str(s).strip()}
    seen = set()
    out = []
    for r in rows:
        key = (r["subject_id"], r["session"])
        if dedupe:
            if key in seen:
                continue
            seen.add(key)
        if qc_exclusion and r.get("qc_flag", "ok").strip().lower() != "ok":
            continue
        if r["site"].strip().upper() in excluded_sites:
            continue
        if r["subject_id"].strip() in excluded_subjects:
            continue
        out.append(r)
    return out


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def _mean(xs):
    return sum(xs) / len(xs)


def _var(xs):
    m = _mean(xs)
    return sum((x - m) ** 2 for x in xs) / (len(xs) - 1)


def compute(rows, outcome="neural_activity", tail="two-sided", test="welch"):
    if outcome not in NUMERIC_OUTCOMES:
        raise ValueError("outcome must be one of %s" % (NUMERIC_OUTCOMES,))
    control = [float(r[outcome]) for r in rows if r["condition"] == "control"]
    stim = [float(r[outcome]) for r in rows if r["condition"] == "stimulus"]
    n_c, n_s = len(control), len(stim)
    if n_c < 2 or n_s < 2:
        raise ValueError("insufficient data: n_control=%d n_stimulus=%d" % (n_c, n_s))
    m_c, m_s = _mean(control), _mean(stim)
    v_c, v_s = _var(control), _var(stim)
    pooled_sd = math.sqrt(((n_c - 1) * v_c + (n_s - 1) * v_s) / (n_c + n_s - 2))
    delta = m_s - m_c
    cohen_d = delta / pooled_sd
    if test == "student":
        se = pooled_sd * math.sqrt(1.0 / n_c + 1.0 / n_s)
        df = n_c + n_s - 2
    else:
        se = math.sqrt(v_c / n_c + v_s / n_s)
        df = (v_c / n_c + v_s / n_s) ** 2 / (
            (v_c / n_c) ** 2 / (n_c - 1) + (v_s / n_s) ** 2 / (n_s - 1)
        )
    t = delta / se
    if tail == "greater":
        p = t_sf(t, df)
    elif tail == "less":
        p = 1.0 - t_sf(t, df)
    else:
        p = 2.0 * t_sf(abs(t), df)
    return {
        "p_value": round(p, 8),
        "cohen_d": round(cohen_d, 6),
        "t_statistic": round(t, 6),
        "df": round(df, 4),
        "n_control": n_c,
        "n_stimulus": n_s,
        "group_means": {"control": round(m_c, 6), "stimulus": round(m_s, 6)},
        "group_stds": {"control": round(math.sqrt(v_c), 6), "stimulus": round(math.sqrt(v_s), 6)},
    }


def run_analysis(analysis, path=CSV_PATH):
    """Run the analysis described by an `analysis` block (as stored in summary_stats.json)."""
    rows = select_rows(
        load_rows(path),
        dedupe=analysis.get("dedupe", True),
        qc_exclusion=analysis.get("qc_exclusion", True),
        excluded_sites=analysis.get("excluded_sites", []),
        excluded_subjects=analysis.get("excluded_subjects", []),
    )
    return compute(
        rows,
        outcome=analysis.get("outcome", "neural_activity"),
        tail=analysis.get("tail", "two-sided"),
        test=analysis.get("test", "welch"),
    )
