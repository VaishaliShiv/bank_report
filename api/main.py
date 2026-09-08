"""Payment Reconciliation API.

Thin aggregator: routing, validation, auth. Logic lives in store.py / excel.py.
Run:  uvicorn api.main:app --port 8000
"""
import logging
import os
import secrets
import sys
from datetime import date, timedelta

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api import excel, store  # noqa: E402
from api.routes_report import router as report_router  # noqa: E402
from api.config import settings  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
log = logging.getLogger("recon.api")

# Validated at import: a misconfigured deployment fails to boot rather than
# quietly serving reconciliation data to the internet.
CFG = settings()

app = FastAPI(title="Payment Reconciliation API", version="1.0.0",
              docs_url="/docs" if CFG.is_local else None,
              redoc_url=None,
              openapi_url="/openapi.json" if CFG.is_local else None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CFG.cors_origins or ["http://localhost:3000"],
    allow_methods=["GET"], allow_headers=["x-api-key"],
)

app.include_router(report_router)

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")

if os.path.isdir(WEB):
    app.mount("/static", StaticFiles(directory=WEB), name="static")

    @app.get("/", include_in_schema=False)
    def dashboard():
        """The web dashboard. Everything it needs is under /api."""
        return FileResponse(os.path.join(WEB, "index.html"))


def require_key(request: Request, token: str | None = Query(None)):
    """Header for programmatic callers; ?token= for plain-URL callers such as a
    download link, which cannot send headers. Open only when ENVIRONMENT=local —
    config.validate() refuses a missing key anywhere else."""
    if not CFG.api_key:
        return
    supplied = request.headers.get("x-api-key") or token
    if not supplied or not secrets.compare_digest(supplied, CFG.api_key):
        raise HTTPException(401, "invalid or missing API key")


def _day(value: str) -> date:
    try:
        return store.parse_day(value)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/healthz")
def healthz():
    """Liveness — process is up. Never touches storage."""
    return {"status": "ok", "environment": CFG.environment}


@app.get("/readyz")
def readyz():
    """Readiness — storage is actually reachable with the configured credential."""
    try:
        n = len(store.all_rows())
        return {"status": "ready", "vendorDays": n,
                "auth": "managed-identity" if CFG.uses_managed_identity else "key",
                "dedup": CFG.dedup_strategy}
    except Exception as e:
        log.error(f"readiness failed: {type(e).__name__}: {e}")
        raise HTTPException(503, f"table unreachable: {type(e).__name__}")


@app.get("/api/dates", dependencies=[Depends(require_key)])
def dates():
    ds = store.available_dates()
    return {"dates": ds, "latest": ds[-1] if ds else None, "count": len(ds)}


@app.get("/api/report", dependencies=[Depends(require_key)])
def report(date_: str = Query(..., alias="date")):
    day = _day(date_)
    rows = store.rows_for(day)
    if not rows:
        raise HTTPException(404, f"no reconciliation data for {day.isoformat()}")
    return {"date": day.isoformat(), "kpis": store.kpis(rows),
            "rows": [store.serialise(r) for r in rows]}


@app.get("/api/rows", dependencies=[Depends(require_key)])
def rows_all():
    """Every vendor-day, flat. For exports and any external consumer."""
    return [store.serialise(r) for r in store.all_rows()]


@app.get("/api/trend", dependencies=[Depends(require_key)])
def trend(days: int = Query(30, ge=1, le=365)):
    cutoff = date.today() - timedelta(days=days)
    out = []
    for day in store.available_dates():
        d = store.parse_day(day)
        if d < cutoff:
            continue
        k = store.kpis(store.rows_for(d))
        out.append({"date": day, **k})
    return {"days": days, "points": out}


@app.get("/api/report/excel", dependencies=[Depends(require_key)])
def report_excel(date_: str = Query(..., alias="date"),
                 runs: bool = Query(True, description="include the raw Runs sheet")):
    """The same document /api/v1/report/{date} returns, as a workbook - one
    column per field, so the spreadsheet and the JSON cannot disagree."""
    from api.routes_report import report as build_report
    day = _day(date_)
    doc = build_report(day.isoformat(), runs)
    buf = excel.build(doc)
    log.info(f"built workbook for {day} "
             f"({len(doc['sources'])} sources, {doc.get('runCount', 0)} runs)")
    return StreamingResponse(
        buf, media_type=XLSX,
        headers={"Content-Disposition": f'attachment; filename="{excel.filename(day)}"'},
    )
