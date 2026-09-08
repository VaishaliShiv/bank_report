"""The date-addressed report API.

The contract these tests protect: raw runs are returned verbatim and every one
is flagged authoritative or superseded. A financial control that silently drops
rows is not auditable.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api.routes_report import serialise_run, summarise, serialise_source, _pct
from recon.dedup import dedupe, enrich

def run(upload, rowkey, amt_sap=843880.43, matched=634, dup=3):
    return {"PartitionKey": f"100002_{upload}", "RowKey": rowkey,
            "vendorId": "100002", "uploadDate": upload, "GeneratedDate": upload,
            "source_name": "Harbour Commercial Bank",
            "TotalRecords_Partner": 638, "TotalRecords_SAP": 638,
            "TotalAmount_Partner": 847110.43, "TotalAmount_SAP": amt_sap,
            "M00_Matched": matched, "A01_MissingSAP": 1, "A02_MissingPartner": 0,
            "A03_SAPAmountHigh": 0, "A04_PartnerAmountHigh": 0,
            "A05_Duplicate": dup, "A07_DateDifference": 0,
            "GeneralSummary": "Action required on the missing-in-SAP item."}

R1 = run("10-03-2025-093734", "aaaa1")
R3 = run("10-03-2025-153458", "aaaa3")

def test_run_keeps_every_stored_column():
    d = serialise_run(R1, "aaaa3")
    for k in ("partitionKey","rowKey","vendorId","uploadDate","generatedDate",
              "sourceName","totalRecordsPartner","totalRecordsSap",
              "totalAmountPartner","totalAmountSap","m00Matched","generalSummary",
              "missingInSap","missingInPartner","sapAmountHigh",
              "partnerAmountHigh","duplicates","dateDifferences"):
        assert k in d, k
    assert d["totalAmountPartner"] == 847110.43
    assert d["duplicates"] == 3

def test_run_adds_what_the_table_does_not_store():
    d = serialise_run(R3, "aaaa3")
    assert d["balanceDifference"] == 3230.00
    assert d["totalAnomalies"] == 4
    assert d["matchRatePct"] == 99.37
    assert d["anomalyRatePct"] == 0.63
    assert d["status"] == "Not reconciled"
    assert d["businessDate"] == "2025-03-10"
    assert d["uploadDateTime"] == "2025-03-10T15:34:58"

def test_superseded_run_names_its_winner():
    loser = serialise_run(R1, "aaaa3")
    assert loser["isAuthoritative"] is False
    assert loser["supersededBy"] == "aaaa3"

def test_authoritative_run_has_no_supersededby():
    winner = serialise_run(R3, "aaaa3")
    assert winner["isAuthoritative"] is True
    assert winner["supersededBy"] is None

def test_exposure_declared_but_null():
    # the narrative cites an exposure figure that is persisted nowhere upstream
    assert serialise_run(R1, "aaaa3")["exposure"] is None
    assert serialise_source(enrich(dedupe([R1, R3])[0]))["exposure"] is None

def test_summary_totals_come_from_deduplicated_rows():
    rows = [enrich(r) for r in dedupe([R1, R3])]
    s = summarise(rows)
    assert s["sources"] == {"total": 1, "reconciled": 0, "notReconciled": 1}
    assert s["records"]["partner"] == 638          # not 1276
    assert s["amount"]["partner"] == 847110.43     # not doubled
    assert s["amount"]["difference"] == 3230.00
    assert s["anomalies"]["byType"]["duplicates"] == 3
    assert s["rates"]["sourceCompletionPct"] == 0.0

def test_reconciled_source_reports_clean():
    clean = run("11-03-2025-090000", "bbbb1", amt_sap=847110.43, matched=638, dup=0)
    clean["A01_MissingSAP"] = 0
    s = summarise([enrich(r) for r in dedupe([clean])])
    assert s["sources"]["reconciled"] == 1
    assert s["rates"]["valueReconciledPct"] == 100.0

def test_source_carries_provenance():
    src = serialise_source(enrich(dedupe([R1, R3])[0]))
    assert src["provenance"]["rowKey"] == "aaaa3"
    assert src["runs"] == {"count": 2, "superseded": 1, "figuresVariedAcrossRuns": False}
    assert src["assessment"].startswith("Action required")

def test_pct_handles_zero_denominator():
    assert _pct(5, 0) is None
    assert _pct(1, 4) == 25.0
