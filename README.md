# Payment Reconciliation

Web dashboard over a `summarylogs` Azure Table (partner-vs-SAP payment
reconciliation), with per-date Excel export.

> Test fixtures use **synthetic** data. Point the config at your own storage
> account to use real data.

## Run it

**First time, Windows** — double-click `setup.bat`. It creates the environment,
installs dependencies, asks for your connection string, writes `.env` for you,
and tests the connection. No file editing.

**After that** — double-click `run_api.bat`.

**Linux/macOS** — `python3 setup_env.py` once, then `./run_api.sh`.

Then open **http://localhost:8000**.

Needs a `.env` file with `AZURE_STORAGE_CONNECTION_STRING`:

    copy .env.example .env      # Windows  (cp on Linux/macOS)

Then paste your connection string into **`.env`** — not `.env.example`.
`.env` is gitignored; `.env.example` is tracked, so a key left there gets
committed.
Nothing else — no Docker, no Azure, no OpenAI key, no licence.


## API

`GET /api/v1/report/2026-07-21` returns one document for that date:

| Block | What |
|---|---|
| `summary` | headline counts, amounts, anomalies by type, three rates |
| `dedup` | which rule was applied and how many runs it collapsed |
| `sources` | one entry per vendor — deduplicated. **What you report.** |
| `runs` | every raw table row, all columns. **What you prove it from.** |
| `exceptions` | vendor IDs needing action, worst difference first |

Every raw run carries `isAuthoritative` and `supersededBy`, so a dropped row can
always be traced to the one that replaced it. The table is a run log; a control
report that silently discards rows is not auditable.

| Endpoint | |
|---|---|
| `/api/v1/dates` | dates with source and run counts |
| `/api/v1/report/latest` | most recent date |
| `/api/v1/report/{date}` | full document (`?runs=false` to omit raw rows) |
| `/api/v1/report/{date}/sources` | deduplicated sources only |
| `/api/v1/report/{date}/runs` | raw rows (`?vendorId=`, `?authoritativeOnly=`) |

`404` names the dates that do exist; `422` explains the date format.

`exposure` is declared on every source and run but is always `null` — the
narrative cites an exposure figure that the pipeline does not persist.

### Excel export

`GET /api/report/excel?date=2026-07-21` — the same document as a workbook, one
column per JSON field. The dashboard's download button calls it.

| Sheet | Contents |
|---|---|
| `Summary` | headline figures, one per row, plus the dedup note |
| `Sources` | deduplicated — 29 columns, one row per vendor |
| `Runs` | every raw table row — 30 columns, `Authoritative` and `Superseded by` first |

Add `?runs=false` to omit the Runs sheet.

Because the workbook is built from the report document rather than from the
table, a figure cannot differ between the JSON and the spreadsheet. A test
asserts every JSON field has a column, so adding a field to the API without
adding it to the export fails the build.

### Postman

Import `postman_collection.json` — 16 requests across health, report, raw runs,
dashboard endpoints and error cases. Set the `baseUrl` variable if the API is not
on `http://localhost:8000`.

## Layout

| Path | What |
|---|---|
| `web/` | **The dashboard.** Served at `/` by the API |
| `recon/dedup.py` | The dedup + derived-field rules. The heart of this repo. |
| `api/` | FastAPI: dashboard, JSON API, Excel export |
| `tests/` | 18 tests — dedup rules and config guards |
| `run_api.bat` / `.sh` | Local launchers |
| `deploy/`, `Dockerfile` | **Azure only. Not needed locally — ignore for now.** |

Diagnostics: `test_connection.py`, `discover_table.py`, `impact.py`.

## The one thing to know

`summarylogs` is a **run log, not a daily summary**. Re-running a vendor writes
another row for the same business day, carrying identical figures.

Aggregating raw rows therefore multiplies every total by the number of runs — a
vendor re-run fourteen times is counted fourteen times.

The API deduplicates to the **latest run per vendor per day**. If re-runs ever
disagree, the dashboard's re-run note turns into a warning rather than silently
picking one.

**Verify after connecting:** `/readyz` reports `vendorDays` — the row count after
dedup. It must be lower than the raw table count and equal to the number of
distinct vendor-day combinations. If it matches the raw count, dedup didn't apply
and every figure is wrong.

## Known gaps

- **No exposure figure.** The generated summaries cite an exposure amount and a
  transaction reference, but that line-item detail is persisted nowhere — the
  anomaly-detail blob container is empty. Not fixable here; the upstream pipeline
  must store it.
- **A trend view needs real history.** If the source is re-uploaded fixtures, the
  same figures repeat across dates and a trend chart is meaningless.
- **Some anomaly codes may never fire.** Check whether `A02`, `A04` and `A07` are
  genuinely always zero before giving them chart space.

## Tests

    python3 -m pytest tests/ -q
