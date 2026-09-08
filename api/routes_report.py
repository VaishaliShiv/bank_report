"""Date-addressed reconciliation report.

Two views of the same day, deliberately both present:

  sources  - deduplicated, one row per vendor. What you report.
  runs     - every row in the table, verbatim. What you prove it from.

The table is a run log: re-running a vendor writes another row for the same
business day. Reporting the raw rows double-counts; reporting only the winner
hides which rows were dropped. A financial control needs both, so every raw run
carries isAuthoritative / supersededBy.
"""
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Query

from api import store
from recon.dedup import ANOMALY_COLS, business_date, parse_upload

router = APIRouter(prefix="/api/v1", tags=["report"])

ANOMALY_JSON = {
    "A01_MissingSAP": "missingInSap",
    "A02_MissingPartner": "missingInPartner",
    "A03_SAPAmountHigh": "sapAmountHigh",
    "A04_PartnerAmountHigh": "partnerAmountHigh",
    "A05_Duplicate": "duplicates",
    "A07_DateDifference": "dateDifferences",
}


def _iso(value) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value else None


def _pct(part, whole):
    return round(part / whole * 100, 2) if whole else None


def _day_or_422(value: str) -> date:
    try:
        return store.parse_day(value)
    except ValueError:
        raise HTTPException(422, {
            "error": "bad_date_format",
            "message": f"Date must be YYYY-MM-DD, got {value!r}.",
        })


def _require_data(day: date) -> list[dict]:
    rows = store.rows_for(day)
    if not rows:
        raise HTTPException(404, {
            "error": "no_data_for_date",
            "message": f"No reconciliation ran on {day.isoformat()}.",
            "availableDates": store.available_dates(),
        })
    return rows


# --------------------------------------------------------------------------
#  raw runs — every row, every column, exactly as stored
# --------------------------------------------------------------------------
def serialise_run(raw: dict, winner_key: str | None) -> dict:
    """One table row, verbatim, plus the fields the table does not store."""
    partner_amt = float(raw.get("TotalAmount_Partner") or 0)
    sap_amt = float(raw.get("TotalAmount_SAP") or 0)
    records = int(raw.get("TotalRecords_Partner") or 0)
    matched = int(raw.get("M00_Matched") or 0)
    anomalies = sum(int(raw.get(c) or 0) for c in ANOMALY_COLS)
    difference = round(partner_amt - sap_amt, 2)
    row_key = raw.get("RowKey")

    return {
        # --- stored, verbatim ---
        "partitionKey": raw.get("PartitionKey"),
        "rowKey": row_key,
        "timestamp": _iso(raw.get("Timestamp")),
        "vendorId": raw.get("vendorId"),
        "uploadDate": raw.get("uploadDate"),
        "generatedDate": raw.get("GeneratedDate"),
        "sourceName": raw.get("source_name"),
        "totalRecordsPartner": records,
        "totalRecordsSap": int(raw.get("TotalRecords_SAP") or 0),
        "totalAmountPartner": partner_amt,
        "totalAmountSap": sap_amt,
        "m00Matched": matched,
        **{ANOMALY_JSON[c]: int(raw.get(c) or 0) for c in ANOMALY_COLS},
        "generalSummary": raw.get("GeneralSummary") or "",

        # --- parsed from the dd-MM-yyyy-HHmmss strings ---
        "businessDate": business_date(raw).isoformat(),
        "uploadDateTime": parse_upload(raw["uploadDate"]).isoformat(),
        "generatedDateTime": (parse_upload(raw["GeneratedDate"]).isoformat()
                              if raw.get("GeneratedDate") else None),

        # --- computed; the table stores none of these ---
        "totalAnomalies": anomalies,
        "balanceDifference": difference,
        "matchRatePct": _pct(matched, records),
        "anomalyRatePct": _pct(anomalies, records),
        "status": "Reconciled" if anomalies == 0 and difference == 0 else "Not reconciled",

        # --- which run won, and which this one lost to ---
        "isAuthoritative": row_key == winner_key,
        "supersededBy": None if row_key == winner_key else winner_key,

        # declared so consumers can rely on the shape; the anomaly line-item
        # detail the narrative cites is not persisted anywhere upstream
        "exposure": None,
    }


def runs_for(day: date) -> list[dict]:
    """Every raw run on this date, newest first, each flagged against its winner."""
    winners = {r["vendorId"]: r.get("RowKey") for r in store.rows_for(day)}
    raw = [r for r in store.raw_rows() if business_date(r) == day]
    out = [serialise_run(r, winners.get(str(r.get("vendorId")))) for r in raw]
    out.sort(key=lambda r: (r["vendorId"], r["uploadDateTime"]), reverse=True)
    return out


# --------------------------------------------------------------------------
#  deduplicated per-source view
# --------------------------------------------------------------------------
def serialise_source(r: dict) -> dict:
    records = r["TotalRecords_Partner"]
    return {
        "vendorId": r["vendorId"],
        "name": r["source_name"],
        "status": r["status"],
        "records": {"partner": records, "sap": r["TotalRecords_SAP"],
                    "matched": r["M00_Matched"], "unmatched": records - r["M00_Matched"]},
        "amount": {"partner": r["TotalAmount_Partner"], "sap": r["TotalAmount_SAP"],
                   "difference": r["balance_difference"], "currency": "AED"},
        "anomalies": {"total": r["total_anomalies"],
                      "byType": {ANOMALY_JSON[c]: r[c] for c in ANOMALY_COLS}},
        "rates": {"matchPct": r["match_rate_pct"],
                  "anomalyPct": _pct(r["total_anomalies"], records),
                  "valueUnconfirmedPct": _pct(abs(r["balance_difference"]),
                                              r["TotalAmount_Partner"])},
        "runs": {"count": r["run_count"], "superseded": r["superseded_runs"],
                 "figuresVariedAcrossRuns": bool(r.get("figures_varied_across_runs"))},
        "provenance": {"rowKey": r.get("RowKey"), "partitionKey": r.get("PartitionKey"),
                       "uploadDate": r.get("uploadDate"),
                       "generatedDate": r.get("GeneratedDate")},
        "assessment": r.get("GeneralSummary") or "",
        "exposure": None,
    }


def summarise(rows: list[dict]) -> dict:
    bad = [r for r in rows if not r["is_reconciled"]]
    records = sum(r["TotalRecords_Partner"] for r in rows)
    matched = sum(r["M00_Matched"] for r in rows)
    anomalies = sum(r["total_anomalies"] for r in rows)
    partner = round(sum(r["TotalAmount_Partner"] for r in rows), 2)
    reconciled = round(sum(r["TotalAmount_Partner"] for r in rows if r["is_reconciled"]), 2)
    return {
        "sources": {"total": len(rows), "reconciled": len(rows) - len(bad),
                    "notReconciled": len(bad)},
        "records": {"partner": records, "sap": sum(r["TotalRecords_SAP"] for r in rows),
                    "matched": matched, "unmatched": records - matched},
        "amount": {"partner": partner,
                   "sap": round(sum(r["TotalAmount_SAP"] for r in rows), 2),
                   "difference": round(sum(r["balance_difference"] for r in rows), 2),
                   "reconciled": reconciled, "currency": "AED"},
        "anomalies": {"total": anomalies,
                      "byType": {ANOMALY_JSON[c]: sum(r[c] for r in rows)
                                 for c in ANOMALY_COLS}},
        "rates": {"transactionMatchPct": _pct(matched, records),
                  "sourceCompletionPct": _pct(len(rows) - len(bad), len(rows)),
                  "valueReconciledPct": _pct(reconciled, partner)},
    }


# --------------------------------------------------------------------------
#  endpoints
# --------------------------------------------------------------------------
@router.get("/dates")
def dates():
    """Every business date that has data, with how many sources and runs each."""
    raw = store.raw_rows()
    out = []
    for d in store.available_dates():
        day = store.parse_day(d)
        out.append({
            "date": d,
            "sources": len(store.rows_for(day)),
            "runs": sum(1 for r in raw if business_date(r) == day),
        })
    return {"dates": out, "count": len(out),
            "earliest": out[0]["date"] if out else None,
            "latest": out[-1]["date"] if out else None}


@router.get("/report/latest")
def latest(runs: bool = Query(True, description="include every raw run")):
    ds = store.available_dates()
    if not ds:
        raise HTTPException(404, {"error": "no_data",
                                  "message": "The table returned no rows."})
    return report(ds[-1], runs)


@router.get("/report/{report_date}")
def report(report_date: str, runs: bool = Query(True, description="include every raw run")):
    """One business date: headline summary, deduplicated sources, and - unless
    runs=false - every raw table row for that date, flagged authoritative or
    superseded."""
    day = _day_or_422(report_date)
    rows = _require_data(day)
    doc = {
        "date": day.isoformat(),
        "generatedAt": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "currency": "AED",
        "summary": summarise(rows),
        "dedup": {
            "strategy": "latest",
            "rule": "most recent run per vendor per business day supersedes earlier runs",
            "runsCollapsed": sum(r["superseded_runs"] for r in rows),
            "sourcesWithVariedFigures": [r["source_name"] for r in rows
                                         if r.get("figures_varied_across_runs")],
        },
        "sources": [serialise_source(r) for r in
                    sorted(rows, key=lambda x: -x["TotalRecords_Partner"])],
        "exceptions": [r["vendorId"] for r in
                       sorted((x for x in rows if not x["is_reconciled"]),
                              key=lambda x: -abs(x["balance_difference"]))],
    }
    if runs:
        doc["runs"] = runs_for(day)
        doc["runCount"] = len(doc["runs"])
    return doc


@router.get("/report/{report_date}/sources")
def sources(report_date: str):
    """Deduplicated sources only - one row per vendor."""
    day = _day_or_422(report_date)
    rows = _require_data(day)
    return {"date": day.isoformat(),
            "sources": [serialise_source(r) for r in
                        sorted(rows, key=lambda x: -x["TotalRecords_Partner"])]}


@router.get("/report/{report_date}/runs")
def runs_endpoint(report_date: str,
                  vendor_id: str | None = Query(None, alias="vendorId"),
                  authoritative_only: bool = Query(False, alias="authoritativeOnly")):
    """Every raw table row for this date, all columns, exactly as stored."""
    day = _day_or_422(report_date)
    _require_data(day)
    out = runs_for(day)
    if vendor_id:
        out = [r for r in out if r["vendorId"] == vendor_id]
    if authoritative_only:
        out = [r for r in out if r["isAuthoritative"]]
    return {"date": day.isoformat(), "count": len(out), "runs": out}
