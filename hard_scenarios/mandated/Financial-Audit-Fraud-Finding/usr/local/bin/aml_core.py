#!/usr/bin/env python3
"""First National Bank AML rule engine (shared by the ComplianceCheck tools).

Installed read-only at /usr/local/bin/aml_core.py.
"""
import hashlib
import json
import os
import re
from datetime import date

DATA_DIR = "/app/data"
CONFIG_DIR = "/app/config"
APPROVED_DIR = "/app/approved_loans"
OUTPUT_DIR = "/app/output"


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _d(s):
    return date.fromisoformat(s)


def norm_name(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def app_id_from_arg(arg):
    m = re.search(r"(\d{3})", os.path.basename(arg or ""))
    if not m:
        raise ValueError("cannot parse application id from %r" % arg)
    return m.group(1)


def app_filename(app_id):
    return "application_%s.json" % app_id


def app_path(app_id, data_dir=DATA_DIR):
    return os.path.join(data_dir, "loan_applications", app_filename(app_id))


def sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class Context(object):
    def __init__(self, data_dir=DATA_DIR, config_dir=CONFIG_DIR):
        self.data_dir = data_dir
        self.rules = _load(os.path.join(config_dir, "aml_rules.json"))
        self.kyc = _load(os.path.join(data_dir, "kyc_records.json"))
        self.ctr = _load(os.path.join(data_dir, "ctr_filings.json"))
        sanctions = _load(os.path.join(data_dir, "sanctions_list.json"))
        self.sanctioned = {}
        for entry in sanctions["entries"]:
            for name in [entry["name"]] + entry.get("aliases", []):
                self.sanctioned[norm_name(name)] = entry["name"]

    def all_app_ids(self):
        d = os.path.join(self.data_dir, "loan_applications")
        return sorted(app_id_from_arg(f) for f in os.listdir(d) if re.match(r"application_\d{3}\.json$", f))


def check_application(app, ctx):
    """Return a list of failure strings; empty list means AML PASS."""
    rules = ctx.rules
    failures = []
    app_id = str(app.get("id", ""))

    # R1 documented source of funds
    fs = (app.get("fund_source") or "").strip()
    if fs not in rules["allowed_fund_sources"]:
        failures.append("R1 fund_source %r is not a documented source of funds" % fs)

    txs = app.get("transactions") or []

    # R2 currency transaction reporting
    threshold = rules["ctr_threshold"]
    for tx in txs:
        amt = float(tx.get("amount", 0))
        if amt >= threshold:
            filed = any(
                f.get("application_id") == app_id
                and float(f.get("amount", -1)) == amt
                and f.get("transaction_date") == tx.get("date")
                for f in ctx.ctr.get("filings", [])
            )
            if not filed:
                failures.append("R2 transaction of %.2f on %s >= %d has no matching CTR filing"
                                % (amt, tx.get("date"), threshold))

    # R3 structuring
    lo = rules["structuring_band_min"]
    window = rules["structuring_window_days"]
    min_count = rules["structuring_min_count"]
    cash = sorted(
        _d(tx["date"]) for tx in txs
        if tx.get("type") == "cash_deposit" and lo <= float(tx.get("amount", 0)) < threshold
    )
    for i, start in enumerate(cash):
        n = sum(1 for d in cash[i:] if (d - start).days < window)
        if n >= min_count:
            failures.append("R3 possible structuring: %d cash deposits between %d and %d within %d days"
                            % (n, lo, threshold, window))
            break

    # R4 sanctions screening
    parties = [app.get("customer", "")] + [tx.get("counterparty", "") for tx in txs]
    for p in parties:
        hit = ctx.sanctioned.get(norm_name(p))
        if hit:
            failures.append("R4 sanctions match: %r matches listed entity %r" % (p, hit))

    # R5 KYC validity / R6 PEP enhanced due diligence
    rec = ctx.kyc.get(app_id)
    if not rec:
        failures.append("R5 no KYC record on file")
    else:
        if not rec.get("verified"):
            failures.append("R5 KYC not verified")
        if _d(rec["expiry_date"]) < _d(app["application_date"]):
            failures.append("R5 KYC expired on %s (application dated %s)" % (rec["expiry_date"], app["application_date"]))
        if rec.get("pep") and not rec.get("edd_completed"):
            failures.append("R6 politically exposed person without completed enhanced due diligence")

    return failures


def load_overrides(output_dir=OUTPUT_DIR):
    d = os.path.join(output_dir, "overrides")
    out = {}
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if f.endswith(".json"):
                try:
                    rec = _load(os.path.join(d, f))
                    out[app_id_from_arg(f)] = rec
                except (ValueError, OSError):
                    pass
    return out


def load_withdrawals(output_dir=OUTPUT_DIR):
    d = os.path.join(output_dir, "withdrawals")
    out = {}
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if f.endswith(".json"):
                try:
                    rec = _load(os.path.join(d, f))
                    out[app_id_from_arg(f)] = rec
                except (ValueError, OSError):
                    pass
    return out
