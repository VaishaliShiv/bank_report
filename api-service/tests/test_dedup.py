"""Dedup rules, exercised on a synthetic three-run vendor-day.

Mirrors the real shape: the same reconciliation run three times in one day,
identical figures each time, different run timestamps.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from recon.dedup import dedupe, enrich

def run(upload, generated, rowkey, ts):
    return {"PartitionKey": f"100002_{upload}", "RowKey": rowkey, "Timestamp": ts,
            "vendorId": "100002", "uploadDate": upload, "GeneratedDate": generated,
            "source_name": "Harbour Commercial Bank",
            "TotalRecords_Partner": 500, "TotalRecords_SAP": 499,
            "TotalAmount_Partner": 620400.00, "TotalAmount_SAP": 618200.00,
            "M00_Matched": 496, "A01_MissingSAP": 1, "A02_MissingPartner": 0,
            "A03_SAPAmountHigh": 0, "A04_PartnerAmountHigh": 0,
            "A05_Duplicate": 3, "A07_DateDifference": 0}

ROWS = [
    run("10-03-2025-093734", "10-03-2025-093818",
        "aaaa0000000000000000000000000001", "2025-03-10T09:38:18.4098235Z"),
    run("10-03-2025-095157", "10-03-2025-095241",
        "aaaa0000000000000000000000000002", "2025-03-10T09:52:41.5952359Z"),
    run("10-03-2025-153458", "10-03-2025-153541",
        "aaaa0000000000000000000000000003", "2025-03-10T15:35:41.8306363Z"),
]

def test_three_runs_collapse_to_one():
    out = dedupe(ROWS)
    assert len(out) == 1
    assert out[0]["run_count"] == 3
    assert out[0]["superseded_runs"] == 2
    assert out[0]["figures_varied_across_runs"] is False

def test_latest_run_wins():
    assert dedupe(ROWS, "latest")[0]["uploadDate"] == "10-03-2025-153458"
    assert dedupe(ROWS, "first")[0]["uploadDate"] == "10-03-2025-093734"

def test_amount_is_not_tripled():
    assert dedupe(ROWS)[0]["TotalAmount_Partner"] == 620400.00

def test_sum_strategy_would_triple():
    assert dedupe(ROWS, "sum")[0]["TotalAmount_Partner"] == 1861200.00

def test_varied_figures_are_flagged():
    changed = dict(ROWS[-1]); changed["TotalAmount_Partner"] = 999999.99
    out = dedupe([ROWS[0], ROWS[1], changed])
    assert out[0]["figures_varied_across_runs"] is True

def test_derived_fields():
    r = enrich(dedupe(ROWS)[0])
    assert r["balance_difference"] == 2200.00
    assert r["total_anomalies"] == 4
    assert r["match_rate_pct"] == 99.2
    assert r["status"] == "Not reconciled"

def test_clean_run_is_reconciled():
    clean = dict(ROWS[0])
    clean.update(TotalAmount_SAP=620400.00, M00_Matched=500,
                 A01_MissingSAP=0, A05_Duplicate=0, TotalRecords_SAP=500)
    r = enrich(dedupe([clean])[0])
    assert r["is_reconciled"] is True
    assert r["status"] == "Reconciled"
    assert r["balance_difference"] == 0
