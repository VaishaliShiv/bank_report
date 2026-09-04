---
goal: Give finance a daily view of partner-vs-SAP payment reconciliation, with a downloadable per-date Excel report
domain: Finance / payment operations
audience: Finance and payment operations staff; PMs reviewing reconciliation health
status: building
---

# Payment Reconciliation

## Current state

Working locally, end to end.

- Reads a `summarylogs` Azure Table (partner-vs-SAP reconciliation runs)
- Deduplication implemented and tested — the table is a run log, not a daily summary
- Derived fields validated against the pipeline's own generated narrative: balance
  difference, anomaly count and reconciled status all agree with the prose
- Web dashboard: banner, KPI row, exception cards, charts, ledger, Excel download
- FastAPI service serving JSON, the dashboard, and a formatted two-sheet workbook
- 20 tests passing
- Azure deployment written but deliberately parked — running locally first

## Decisions

**Web dashboard over Power BI.** Power BI was the original plan, and the model was
built and verified in it. Two things decided against it: the manual report build
was slow and error-prone, and Power BI cannot lay out the exception cards — the
pipeline narrative, anomaly pills and severity stripe degrade to a wide table.
The web version also costs nothing per viewer. Trade-off accepted: changes now
need a developer rather than drag-and-drop.

**One API serves everything.** The dashboard, the JSON, and the Excel export all
read the same deduplicated rows, so the numbers cannot drift between them.

**No LLM call at render time.** The summary text is written once by the upstream
pipeline and stored. Regenerating on view would reword a financial control
document on every refresh. The cross-vendor banner is a deterministic template.

**Dedup strategy `latest`.** Re-run groups carry identical figures, so re-runs are
reprocessing rather than separate batches. Made configurable (`latest` / `first` /
`sum`) and surfaced on screen via `FiguresVaried`, in case that assumption breaks.

**Startup-time config validation.** Deploying without `API_KEY` or `CORS_ORIGINS`
fails to boot. An unauthenticated finance API that starts cleanly is worse than one
that refuses to.

## Open questions

1. Is there a **production** source? If the dev table is re-uploaded fixtures, the
   same figures repeat across dates and no trend view is worth building.
2. **Where is the anomaly line-item detail?** The generated summaries cite an
   exposure amount and a transaction reference that exist nowhere in storage. A
   control report quoting untraceable figures is a governance issue, not just a
   missing feature.
3. **Are `A02`, `A04`, `A07` ever non-zero?** They may be unimplemented rather than
   simply inactive.
4. `A06` is absent from the code sequence — deliberate?

## Next

- Deploy to Azure so colleagues can reach it (`deploy/README.md`)
- Daily archive job — a Container Apps cron job reusing `api/excel.py` — not built

## Lessons

The source looked like one row per vendor per day. It is a **run log**: every
re-run duplicates a vendor-day with identical figures. Loading it naively would
have produced a dashboard that was confidently wrong — by 3× on one source and 14×
on another. Profiling the real table before writing any query is what caught it.

## Note on sample data

Test fixtures use **synthetic** data with fictional institution names. Real
figures never enter the repository.
