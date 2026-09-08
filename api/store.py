"""Azure Table access + the deduplicated view the API serves.

Single responsibility: turn the raw summarylogs run-log into clean vendor-day
rows. All reconciliation logic lives in recon.dedup; this only fetches and caches.
"""
import threading
import time
from datetime import date, datetime

from azure.data.tables import TableServiceClient

from api.config import settings
from recon.dedup import dedupe, enrich

_lock = threading.Lock()
_cache: dict = {"at": 0.0, "rows": None, "raw_at": 0.0, "raw": None}


def _client():
    """Connection string locally; managed identity in Azure — no key to rotate."""
    cfg = settings()
    if cfg.uses_managed_identity:
        from azure.identity import DefaultAzureCredential
        svc = TableServiceClient(endpoint=cfg.table_endpoint,
                                 credential=DefaultAzureCredential())
    else:
        svc = TableServiceClient.from_connection_string(cfg.connection_string)
    return svc.get_table_client(cfg.table_name)


def _fetch_raw() -> list[dict]:
    """Rows as plain dicts. The service Timestamp lives in entity metadata,
    which dict() drops, so lift it onto the row."""
    out = []
    for e in _client().list_entities():
        row = dict(e)
        if "Timestamp" not in row:
            meta = getattr(e, "metadata", None) or {}
            ts = meta.get("timestamp")
            if ts is not None:
                row["Timestamp"] = ts
        out.append(row)
    return out


def raw_rows(force: bool = False) -> list[dict]:
    """Every row in the table, exactly as stored - one per reconciliation RUN.

    This is the audit view: the deduplicated view drops rows, and a financial
    control needs to show which rows were dropped and why.
    """
    with _lock:
        fresh = _cache["raw"] is not None and time.time() - _cache["raw_at"] < settings().cache_ttl
        if fresh and not force:
            return _cache["raw"]
        rows = _fetch_raw()
        _cache.update(raw_at=time.time(), raw=rows)
        return rows


def all_rows(force: bool = False) -> list[dict]:
    """Every vendor-day, deduplicated and enriched. Cached for CACHE_TTL_SECONDS."""
    with _lock:
        cfg = settings()
        fresh = _cache["rows"] is not None and time.time() - _cache["at"] < cfg.cache_ttl
        if fresh and not force:
            return _cache["rows"]
        strategy = cfg.dedup_strategy
        rows = [enrich(r) for r in dedupe(_fetch_raw(), strategy)]
        rows.sort(key=lambda r: (r["business_date"], r["source_name"]))
        _cache.update(at=time.time(), rows=rows)
        return rows


def available_dates() -> list[str]:
    return sorted({r["business_date"].isoformat() for r in all_rows()})


def rows_for(day: date) -> list[dict]:
    return [r for r in all_rows() if r["business_date"] == day]


def kpis(rows: list[dict]) -> dict:
    """Headline figures. Everything here is summed, never inferred."""
    bad = [r for r in rows if not r["is_reconciled"]]
    records = sum(r["TotalRecords_Partner"] for r in rows)
    anomalies = sum(r["total_anomalies"] for r in rows)
    return {
        "sources": len(rows),
        "sourcesReconciled": len(rows) - len(bad),
        "sourcesNotReconciled": len(bad),
        "records": records,
        "recordsSap": sum(r["TotalRecords_SAP"] for r in rows),
        "matched": sum(r["M00_Matched"] for r in rows),
        "anomalies": anomalies,
        "valuePartner": round(sum(r["TotalAmount_Partner"] for r in rows), 2),
        "valueSap": round(sum(r["TotalAmount_SAP"] for r in rows), 2),
        "balanceDifference": round(sum(r["balance_difference"] for r in rows), 2),
        "anomalyRatePct": round(anomalies / records * 100, 2) if records else None,
        "rerunsCollapsed": sum(r["run_count"] - 1 for r in rows),
        "figuresVaried": [r["source_name"] for r in rows
                          if r.get("figures_varied_across_runs")],
    }


def serialise(r: dict) -> dict:
    """One vendor-day, flattened for JSON. Flat on purpose."""
    return {
        "date": r["business_date"].isoformat(),
        "vendorId": r["vendorId"],
        "source": r["source_name"],
        "status": r["status"],
        "recordsPartner": r["TotalRecords_Partner"],
        "recordsSap": r["TotalRecords_SAP"],
        "matched": r["M00_Matched"],
        "anomalies": r["total_anomalies"],
        "matchRatePct": r["match_rate_pct"],
        "amountPartner": r["TotalAmount_Partner"],
        "amountSap": r["TotalAmount_SAP"],
        "balanceDifference": r["balance_difference"],
        "missingInSap": r["A01_MissingSAP"],
        "missingInPartner": r["A02_MissingPartner"],
        "sapAmountHigh": r["A03_SAPAmountHigh"],
        "partnerAmountHigh": r["A04_PartnerAmountHigh"],
        "duplicates": r["A05_Duplicate"],
        "dateDifferences": r["A07_DateDifference"],
        "runCount": r["run_count"],
        "figuresVariedAcrossRuns": bool(r.get("figures_varied_across_runs")),
        "summary": r.get("GeneralSummary") or "",
    }


def parse_day(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"date must be YYYY-MM-DD, got {value!r}")
