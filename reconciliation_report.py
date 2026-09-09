#!/usr/bin/env python3
"""Standalone reconciliation report — reads the Azure Table, prints JSON.

Self-contained: needs only this file, a .env, and two packages.

    pip install azure-data-tables python-dotenv

    python reconciliation_report.py                 latest date
    python reconciliation_report.py 2026-07-21      that date
    python reconciliation_report.py --dates         which dates have data
    python reconciliation_report.py --all           every date
    python reconciliation_report.py 2026-07-21 -o report.json
    python reconciliation_report.py --no-runs       omit the raw rows
    python reconciliation_report.py --serve 8000    serve it over HTTP

.env needs one line:

    AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...

Why the output has two views of the same day: the table is a RUN log. Re-running
a vendor writes another row for the same business date with identical figures.
Summing raw rows multiplies every total by the number of runs; showing only the
winner hides which rows were dropped. So `sources` is deduplicated (what you
report) and `runs` is every raw row (what you prove it from), each flagged
isAuthoritative / supersededBy.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timezone

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

UPLOAD_FMT = "%d-%m-%Y-%H%M%S"          # e.g. 21-07-2026-093734, day first

# stored column -> JSON name
ANOMALIES = {
    "A01_MissingSAP": "missingInSap",
    "A02_MissingPartner": "missingInPartner",
    "A03_SAPAmountHigh": "sapAmountHigh",
    "A04_PartnerAmountHigh": "partnerAmountHigh",
    "A05_Duplicate": "duplicates",
    "A07_DateDifference": "dateDifferences",
}


# ─────────────────────────────────────────────────────────── fetch
def fetch_rows() -> list[dict]:
    """Every row in the table, as plain dicts, with the service Timestamp kept."""
    conn = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "").strip()
    if not conn or "<" in conn:
        sys.exit(
            "No connection string.\n\n"
            "  Create a file named  .env  beside this script containing:\n\n"
            "      AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;"
            "AccountName=...;AccountKey=...;EndpointSuffix=core.windows.net\n\n"
            "  Portal > storage account > Access keys > key1 > Connection string."
        )
    try:
        from azure.data.tables import TableServiceClient
    except ImportError:
        sys.exit("Missing dependency:  pip install azure-data-tables python-dotenv")

    table = os.getenv("AZURE_TABLE", "summarylogs").strip()
    client = TableServiceClient.from_connection_string(conn).get_table_client(table)

    rows = []
    for entity in client.list_entities():
        row = dict(entity)
        if "Timestamp" not in row:                    # lives in metadata, not the dict
            ts = (getattr(entity, "metadata", None) or {}).get("timestamp")
            if ts is not None:
                row["Timestamp"] = ts
        rows.append(row)
    return rows


# ─────────────────────────────────────────────── parsing and derivation
def parse_upload(value: str) -> datetime:
    return datetime.strptime(str(value), UPLOAD_FMT)


def business_date(row: dict) -> date:
    return parse_upload(row["uploadDate"]).date()


def run_instant(row: dict) -> datetime:
    ts = row.get("Timestamp")
    if isinstance(ts, datetime):
        return ts.replace(tzinfo=None)
    return parse_upload(row["uploadDate"])


def pct(part, whole):
    return round(part / whole * 100, 2) if whole else None


def iso(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value else None


def derive(row: dict) -> dict:
    """The fields the table does not store."""
    partner = float(row.get("TotalAmount_Partner") or 0)
    sap = float(row.get("TotalAmount_SAP") or 0)
    records = int(row.get("TotalRecords_Partner") or 0)
    matched = int(row.get("M00_Matched") or 0)
    anomalies = sum(int(row.get(c) or 0) for c in ANOMALIES)
    difference = round(partner - sap, 2)
    return {
        "totalAnomalies": anomalies,
        "balanceDifference": difference,
        "matchRatePct": pct(matched, records),
        "anomalyRatePct": pct(anomalies, records),
        "status": "Reconciled" if anomalies == 0 and difference == 0 else "Not reconciled",
    }


def winners(rows: list[dict]) -> dict[tuple, str]:
    """RowKey of the authoritative run for each (vendor, business date)."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        groups[(str(r["vendorId"]), business_date(r))].append(r)
    return {k: max(v, key=run_instant)["RowKey"] for k, v in groups.items()}


# ─────────────────────────────────────────────────────── serialisation
def serialise_run(row: dict, winner_key: str | None) -> dict:
    d = derive(row)
    key = row.get("RowKey")
    return {
        "partitionKey": row.get("PartitionKey"),
        "rowKey": key,
        "timestamp": iso(row.get("Timestamp")),
        "vendorId": row.get("vendorId"),
        "uploadDate": row.get("uploadDate"),
        "generatedDate": row.get("GeneratedDate"),
        "sourceName": row.get("source_name"),
        "totalRecordsPartner": int(row.get("TotalRecords_Partner") or 0),
        "totalRecordsSap": int(row.get("TotalRecords_SAP") or 0),
        "totalAmountPartner": float(row.get("TotalAmount_Partner") or 0),
        "totalAmountSap": float(row.get("TotalAmount_SAP") or 0),
        "m00Matched": int(row.get("M00_Matched") or 0),
        **{name: int(row.get(col) or 0) for col, name in ANOMALIES.items()},
        "generalSummary": row.get("GeneralSummary") or "",
        "businessDate": business_date(row).isoformat(),
        "uploadDateTime": parse_upload(row["uploadDate"]).isoformat(),
        "generatedDateTime": (parse_upload(row["GeneratedDate"]).isoformat()
                              if row.get("GeneratedDate") else None),
        **d,
        "isAuthoritative": key == winner_key,
        "supersededBy": None if key == winner_key else winner_key,
        # the narrative cites an exposure amount the pipeline does not persist
        "exposure": None,
    }


def serialise_source(row: dict, run_count: int, varied: bool) -> dict:
    d = derive(row)
    records = int(row.get("TotalRecords_Partner") or 0)
    matched = int(row.get("M00_Matched") or 0)
    partner = float(row.get("TotalAmount_Partner") or 0)
    return {
        "vendorId": row.get("vendorId"),
        "name": row.get("source_name"),
        "status": d["status"],
        "records": {"partner": records, "sap": int(row.get("TotalRecords_SAP") or 0),
                    "matched": matched, "unmatched": records - matched},
        "amount": {"partner": partner, "sap": float(row.get("TotalAmount_SAP") or 0),
                   "difference": d["balanceDifference"], "currency": "AED"},
        "anomalies": {"total": d["totalAnomalies"],
                      "byType": {n: int(row.get(c) or 0) for c, n in ANOMALIES.items()}},
        "rates": {"matchPct": d["matchRatePct"], "anomalyPct": d["anomalyRatePct"],
                  "valueUnconfirmedPct": pct(abs(d["balanceDifference"]), partner)},
        "runs": {"count": run_count, "superseded": run_count - 1,
                 "figuresVariedAcrossRuns": varied},
        "provenance": {"rowKey": row.get("RowKey"),
                       "partitionKey": row.get("PartitionKey"),
                       "uploadDate": row.get("uploadDate"),
                       "generatedDate": row.get("GeneratedDate")},
        "assessment": row.get("GeneralSummary") or "",
        "exposure": None,
    }


# ───────────────────────────────────────────────────── the document
def build_report(rows: list[dict], day: date, include_runs: bool = True) -> dict:
    """One business date: summary, deduplicated sources, and the raw runs."""
    on_day = [r for r in rows if business_date(r) == day]
    if not on_day:
        raise KeyError(day.isoformat())

    win = winners(rows)
    by_vendor: dict[str, list[dict]] = defaultdict(list)
    for r in on_day:
        by_vendor[str(r["vendorId"])].append(r)

    sources, collapsed, varied_names = [], 0, []
    for vendor, runs in sorted(by_vendor.items()):
        latest = max(runs, key=run_instant)
        varied = len({(r.get("TotalRecords_Partner"), r.get("TotalAmount_Partner"))
                      for r in runs}) > 1
        collapsed += len(runs) - 1
        if varied:
            varied_names.append(latest.get("source_name"))
        sources.append(serialise_source(latest, len(runs), varied))
    sources.sort(key=lambda s: -s["records"]["partner"])

    n = len(sources)
    bad = [s for s in sources if s["status"] != "Reconciled"]
    records = sum(s["records"]["partner"] for s in sources)
    matched = sum(s["records"]["matched"] for s in sources)
    anomalies = sum(s["anomalies"]["total"] for s in sources)
    partner = round(sum(s["amount"]["partner"] for s in sources), 2)
    reconciled = round(sum(s["amount"]["partner"] for s in sources
                           if s["status"] == "Reconciled"), 2)

    doc = {
        "date": day.isoformat(),
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "currency": "AED",
        "summary": {
            "sources": {"total": n, "reconciled": n - len(bad), "notReconciled": len(bad)},
            "records": {"partner": records,
                        "sap": sum(s["records"]["sap"] for s in sources),
                        "matched": matched, "unmatched": records - matched},
            "amount": {"partner": partner,
                       "sap": round(sum(s["amount"]["sap"] for s in sources), 2),
                       "difference": round(sum(s["amount"]["difference"] for s in sources), 2),
                       "reconciled": reconciled, "currency": "AED"},
            "anomalies": {"total": anomalies,
                          "byType": {name: sum(s["anomalies"]["byType"][name]
                                               for s in sources)
                                     for name in ANOMALIES.values()}},
            "rates": {"transactionMatchPct": pct(matched, records),
                      "sourceCompletionPct": pct(n - len(bad), n),
                      "valueReconciledPct": pct(reconciled, partner)},
        },
        "dedup": {
            "strategy": "latest",
            "rule": "most recent run per vendor per business day supersedes earlier runs",
            "runsCollapsed": collapsed,
            "sourcesWithVariedFigures": varied_names,
        },
        "sources": sources,
        "exceptions": [s["vendorId"] for s in
                       sorted(bad, key=lambda s: -abs(s["amount"]["difference"]))],
    }
    if include_runs:
        runs_out = [serialise_run(r, win.get((str(r["vendorId"]), business_date(r))))
                    for r in on_day]
        runs_out.sort(key=lambda r: (r["vendorId"], r["uploadDateTime"]), reverse=True)
        doc["runs"] = runs_out
        doc["runCount"] = len(runs_out)
    return doc


def available_dates(rows: list[dict]) -> list[date]:
    return sorted({business_date(r) for r in rows})


# ─────────────────────────────────────────────────────────── HTTP
def serve(rows_loader, port: int) -> None:
    """Tiny read-only server. GET /2026-07-21, /latest, /dates."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def _send(self, payload, code=200):
            body = json.dumps(payload, indent=2, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0].strip("/")
            try:
                rows = rows_loader()
                dates = available_dates(rows)
                if not dates:
                    return self._send({"error": "no_data"}, 404)
                if path in ("", "dates"):
                    return self._send({"dates": [d.isoformat() for d in dates],
                                       "count": len(dates)})
                key = dates[-1] if path == "latest" else datetime.strptime(
                    path, "%Y-%m-%d").date()
                return self._send(build_report(rows, key))
            except ValueError:
                self._send({"error": "bad_date_format",
                            "message": "Use /YYYY-MM-DD, /latest or /dates."}, 422)
            except KeyError as e:
                self._send({"error": "no_data_for_date",
                            "message": f"No reconciliation ran on {e.args[0]}.",
                            "availableDates": [d.isoformat()
                                               for d in available_dates(rows_loader())]}, 404)
            except Exception as e:                      # noqa: BLE001
                self._send({"error": type(e).__name__, "message": str(e)[:200]}, 500)

        def log_message(self, fmt, *args):
            sys.stderr.write(f"  {self.address_string()} {fmt % args}\n")

    print(f"\n  http://localhost:{port}/latest")
    print(f"  http://localhost:{port}/2026-07-21")
    print(f"  http://localhost:{port}/dates\n  Ctrl+C to stop.\n", flush=True)
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()


# ─────────────────────────────────────────────────────────── cli
def main() -> None:
    ap = argparse.ArgumentParser(
        description="Reconciliation report as JSON.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("date", nargs="?", help="YYYY-MM-DD; omit for the latest date")
    ap.add_argument("--dates", action="store_true", help="list dates that have data")
    ap.add_argument("--all", action="store_true", help="every date in one document")
    ap.add_argument("--no-runs", action="store_true", help="omit the raw runs")
    ap.add_argument("-o", "--out", metavar="FILE", help="write to a file")
    ap.add_argument("--serve", nargs="?", const=8000, type=int, metavar="PORT",
                    help="serve over HTTP instead of printing")
    args = ap.parse_args()

    if args.serve:
        return serve(fetch_rows, args.serve)

    rows = fetch_rows()
    dates = available_dates(rows)
    if not dates:
        sys.exit("The table returned no rows.")

    if args.dates:
        payload = {"dates": [{"date": d.isoformat(),
                              "sources": len({r["vendorId"] for r in rows
                                              if business_date(r) == d}),
                              "runs": sum(1 for r in rows if business_date(r) == d)}
                             for d in dates],
                   "count": len(dates)}
    elif args.all:
        payload = {"dates": [build_report(rows, d, not args.no_runs) for d in dates],
                   "count": len(dates)}
    else:
        if args.date:
            try:
                target = datetime.strptime(args.date, "%Y-%m-%d").date()
            except ValueError:
                sys.exit(f"Date must be YYYY-MM-DD, got {args.date!r}.")
        else:
            target = dates[-1]
        try:
            payload = build_report(rows, target, not args.no_runs)
        except KeyError:
            sys.exit(f"No reconciliation ran on {target.isoformat()}.\n"
                     f"Available: {', '.join(d.isoformat() for d in dates)}")

    text = json.dumps(payload, indent=2, default=str)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"Wrote {args.out} ({len(text):,} bytes)", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
