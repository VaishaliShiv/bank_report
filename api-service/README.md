# Payment Reconciliation API

Deployable JSON service over an Azure Table of partner-vs-SAP reconciliation
runs. Self-contained: `api/` + `recon/` + `requirements.txt` is everything the
deployment needs.

## Run locally

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt      # Windows: .venv\Scripts\pip
cp .env.example .env                           # then paste your connection string
.venv/bin/uvicorn api.main:app --port 8000
```

`GET /` returns the endpoint list. If the repo is checked out whole, the
dashboard in `../web` is served at `/` instead — that folder is excluded from
the deployed image, so production stays a pure API.

## Endpoints

| | |
|---|---|
| `/healthz` · `/readyz` | liveness; readiness proves the table is reachable |
| `/api/v1/dates` | dates with source and run counts |
| `/api/v1/report/latest` | most recent date |
| `/api/v1/report/{date}` | full document (`?runs=false` omits raw rows) |
| `/api/v1/report/{date}/sources` | deduplicated sources only |
| `/api/v1/report/{date}/runs` | raw rows (`?vendorId=`, `?authoritativeOnly=`) |
| `/api/report/excel?date=` | the same document as a three-sheet workbook |

The response carries two views of the same day. `sources` is deduplicated —
what you report. `runs` is every raw table row — what you prove it from, each
flagged `isAuthoritative` / `supersededBy`.

The table is a run log: re-running a vendor writes another row for the same
business date. Summing raw rows multiplies every total by the number of runs.

## Deploy

**Container Apps** — scales to zero, near-free when idle:

```
az login
./deploy/deploy.sh
```

**App Service** — fewest moving parts, bills continuously (~$13/mo on B1):

```
az login
STORAGE=<your-storage-account> ./deploy/deploy_appservice.sh
```

Both assign a managed identity and grant `Storage Table Data Reader`, so the
deployed service holds no storage key at all.

`deploy/README.md` has the details, including what to do if the role assignment
fails because you lack `User Access Administrator`.

## Configuration

| | Local | Deployed |
|---|---|---|
| `ENVIRONMENT` | `local` | `dev` / `test` / `prod` |
| Storage credential | connection string | `AZURE_STORAGE_ACCOUNT` + managed identity |
| `API_KEY` | optional | **mandatory**, ≥24 chars |
| `CORS_ORIGINS` | relaxed | **mandatory**, `*` refused |
| `/docs` | on | off |

`api/config.py` enforces this at startup. A deployment missing `API_KEY` or
`CORS_ORIGINS` **fails to boot** rather than serving reconciliation data
unauthenticated.

## Tests

```
.venv/bin/pytest tests/ -q
```
