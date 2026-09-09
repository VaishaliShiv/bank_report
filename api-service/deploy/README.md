# Deploying to Azure

The same code runs locally and in Azure. Only environment variables change.

| | Local | Azure |
|---|---|---|
| `ENVIRONMENT` | `local` | `dev` / `test` / `prod` |
| Storage credential | connection string in `.env` | **managed identity** (no key) |
| `API_KEY` | optional | **mandatory**, ≥24 chars |
| `CORS_ORIGINS` | relaxed | **mandatory**, exact origins, `*` refused |
| `/docs` | on | off |

`api/config.py` enforces this **at startup**. A deployment missing `API_KEY` or
`CORS_ORIGINS` **fails to boot** rather than quietly serving reconciliation data
to the internet. That's deliberate — an unauthenticated finance API that starts
fine is worse than one that refuses to.

---

## Deploy

```bash
az login
./deploy/deploy.sh
```

Builds from source in Azure — no local Docker needed. Takes ~5 minutes first run.

Override any default with env vars:

```bash
RG=rg-recon-prod ENVIRONMENT=prod LOCATION=uaenorth \
CORS_ORIGINS=https://recon.example.com ./deploy/deploy.sh
```

Re-running updates in place and **reuses the existing API key**, so existing callers keep
working after a redeploy.

## What it creates

1. Resource group + Container Apps environment
2. The app, built from source, external ingress on 8000
3. `API_KEY` as a **secret** (not a plain env var)
4. A **system-assigned managed identity**
5. Role assignment: **Storage Table Data Reader** on the storage account

Step 5 is the one that matters. The deployed API holds **no storage key at all** —
it authenticates as itself. Nothing to rotate, nothing to leak in app settings.

### If the role assignment fails

The script prints a warning and continues. You need `Owner` or `User Access
Administrator` on the storage account. Ask whoever has it to run:

```bash
az role assignment create \
  --assignee <principalId printed by the script> \
  --role "Storage Table Data Reader" \
  --scope /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/your-storage-account
```

Until then `/readyz` returns 503 — which is correct, not a bug. It's the app
saying it can't reach storage.

## Verify

```bash
curl https://<fqdn>/healthz
# {"status":"ok","environment":"dev"}

curl https://<fqdn>/readyz
# {"status":"ready","vendorDays":<n>,"auth":"managed-identity","dedup":"latest"}

curl -H "x-api-key: <key>" "https://<fqdn>/api/report?date=2026-07-21"
```

`"auth":"managed-identity"` confirms it is **not** using a connection string.

## Point the dashboard at it

The deployed URL serves the dashboard at `/`. Nothing to configure — the page
calls its own origin.

Send the API key as an `x-api-key` header for programmatic calls. The Excel
download link can carry `?token=<key>` instead, since a plain browser navigation
cannot set headers.

> A key in a query string is weaker than a header — it lands in server logs and
> browser history. For a deployment carrying real financial data, prefer putting
> the app behind Entra ID / App Proxy and dropping the shared key entirely.

## Cost

Container Apps scales to zero. At low volume with a 60s cache it idles
at essentially nothing and wakes on request. Expect a few dirhams a month, dominated
by the Container Apps environment rather than the app.

A cold start adds ~2–4s to the first request. If the download button feels slow
after an idle period, that's why — set `--min-replicas 1` to avoid it, which costs
more.

## Not deployed here

`run_api.bat` and the daily archive job. The dashboard doesn't need them.
When you want the daily `.xlsx` archive, that's a Container Apps **job** on a cron
schedule reusing `api/excel.py` — a separate piece, not a change to this one.
