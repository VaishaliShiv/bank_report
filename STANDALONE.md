# Standalone report

Two files: `reconciliation_report.py` and `.env`. Nothing else from this repo.

## Setup

```
pip install azure-data-tables python-dotenv
```

Create `.env` beside the script:

```
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...;EndpointSuffix=core.windows.net
AZURE_TABLE=summarylogs
```

`AZURE_TABLE` is optional — it defaults to `summarylogs`.

## Use

```
python reconciliation_report.py                  latest date, JSON to stdout
python reconciliation_report.py 2026-07-21       one date
python reconciliation_report.py --dates          which dates have data
python reconciliation_report.py --all            every date in one document
python reconciliation_report.py --no-runs        omit the raw rows (~2.3x smaller)
python reconciliation_report.py 2026-07-21 -o report.json
python reconciliation_report.py --serve 8000     serve over HTTP
```

Serving exposes `/dates`, `/latest` and `/YYYY-MM-DD`.

Piping works — the JSON goes to stdout, progress and errors to stderr:

```
python reconciliation_report.py 2026-07-21 | jq .summary
```

## Output

| Block | |
|---|---|
| `summary` | counts, amounts, anomalies by type, three rates |
| `dedup` | the rule applied and how many runs it collapsed |
| `sources` | one entry per vendor, deduplicated — **what you report** |
| `runs` | every raw table row — **what you prove it from** |
| `exceptions` | vendor IDs needing action, worst difference first |

Every raw run carries `isAuthoritative` and `supersededBy`.

## Why both views

The table is a **run log**. Re-running a vendor writes another row for the same
business date carrying identical figures. Summing raw rows multiplies every
total by the number of runs — one date in the sample data has 14 runs of a
single vendor. Showing only the winner hides which rows were dropped, which
makes the report unauditable.

So both are present, and each raw run names the row that superseded it.

## Same numbers as the API

This script and `/api/v1/report/{date}` produce byte-identical documents apart
from `generatedAt`. It reimplements the logic rather than importing it, so the
file stays standalone — the trade-off is that a change to the dedup rule must be
made in both places.

## Errors

Missing `.env` prints what to create and where to get the string. An unknown
date lists the dates that exist. A malformed date says what format is expected.
