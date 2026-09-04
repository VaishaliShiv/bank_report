"""Collapse the reconciliation run-log into one authoritative row per vendor-day.

The table records every *run*. Re-running a vendor on the same day writes another
row with the same figures, so aggregating raw rows multiplies every total.
This module is the single place that rule lives.
"""
from collections import defaultdict
from datetime import datetime
from typing import Iterable

UPLOAD_FMT = "%d-%m-%Y-%H%M%S"

ANOMALY_COLS = ("A01_MissingSAP", "A02_MissingPartner", "A03_SAPAmountHigh",
                "A04_PartnerAmountHigh", "A05_Duplicate", "A07_DateDifference")


def parse_upload(value: str) -> datetime:
    """'21-07-2026-093734' -> datetime. Day-first; raises on anything else."""
    return datetime.strptime(str(value), UPLOAD_FMT)


def business_date(row: dict):
    return parse_upload(row["uploadDate"]).date()


def run_instant(row: dict) -> datetime:
    """When the run happened. Prefers the service Timestamp, falls back to uploaddate."""
    ts = row.get("Timestamp")
    if isinstance(ts, datetime):
        return ts.replace(tzinfo=None)
    if ts:
        return datetime.fromisoformat(str(ts).replace("Z", "").split(".")[0])
    return parse_upload(row["uploadDate"])


def dedupe(rows: Iterable[dict], strategy: str = "latest") -> list[dict]:
    """One row per (vendorid, business date).

    strategy 'latest' : most recent run supersedes earlier ones   [default]
    strategy 'first'  : earliest run is authoritative
    strategy 'sum'    : runs are distinct batches; add them up
    """
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        groups[(str(r["vendorId"]), business_date(r))].append(r)

    out = []
    for (vendor, day), runs in sorted(groups.items()):
        runs.sort(key=run_instant)
        if strategy == "latest":
            winner = dict(runs[-1])
        elif strategy == "first":
            winner = dict(runs[0])
        elif strategy == "sum":
            winner = dict(runs[-1])
            for col in ("TotalRecords_Partner", "TotalRecords_SAP", "M00_Matched",
                        *ANOMALY_COLS):
                winner[col] = sum(r.get(col) or 0 for r in runs)
            for col in ("TotalAmount_Partner", "TotalAmount_SAP"):
                winner[col] = round(sum(float(r.get(col) or 0) for r in runs), 2)
        else:
            raise ValueError(f"unknown strategy: {strategy}")

        # audit trail — so a wrong assumption is visible on the dashboard, not silent
        winner["business_date"] = day
        winner["run_count"] = len(runs)
        winner["superseded_runs"] = len(runs) - 1
        winner["figures_varied_across_runs"] = len({
            (r.get("TotalRecords_Partner"), r.get("TotalAmount_Partner")) for r in runs
        }) > 1
        out.append(winner)
    return out


def enrich(row: dict) -> dict:
    """Add the fields the report needs that the table doesn't store."""
    r = dict(row)
    partner_amt = float(r.get("TotalAmount_Partner") or 0)
    sap_amt = float(r.get("TotalAmount_SAP") or 0)
    total_rec = int(r.get("TotalRecords_Partner") or 0)
    matched = int(r.get("M00_Matched") or 0)

    r["balance_difference"] = round(partner_amt - sap_amt, 2)
    r["total_anomalies"] = sum(int(r.get(c) or 0) for c in ANOMALY_COLS)
    r["match_rate_pct"] = round(matched / total_rec * 100, 2) if total_rec else None
    r["is_reconciled"] = r["total_anomalies"] == 0 and r["balance_difference"] == 0
    r["status"] = "Reconciled" if r["is_reconciled"] else "Not reconciled"
    return r
