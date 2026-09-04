# Payment Reconciliation

Web dashboard over a `summarylogs` Azure Table (partner-vs-SAP payment
reconciliation), with per-date Excel export.

> Test fixtures use **synthetic** data. Point the config at your own storage
> account to use real data.

## Run it

**Windows** — double-click `run_api.bat`
**Linux/macOS** — `./run_api.sh`

Then open **http://localhost:8000**.

Needs `.env` with `AZURE_STORAGE_CONNECTION_STRING` (copy `.env.example`).
Nothing else — no Docker, no Azure, no OpenAI key, no licence.


## Layout

| Path | What |
|---|---|
| `web/` | **The dashboard.** Served at `/` by the API |
| `recon/dedup.py` | The dedup + derived-field rules. The heart of this repo. |
| `api/` | FastAPI service behind the download button |
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
