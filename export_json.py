import os, sys, json
from dotenv import load_dotenv; load_dotenv()
from azure.data.tables import TableServiceClient
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recon.dedup import dedupe, enrich

tc = TableServiceClient.from_connection_string(
    os.getenv("AZURE_STORAGE_CONNECTION_STRING")).get_table_client(
    os.getenv("AZURE_TABLE", "summarylogs"))
rows = [dict(e) for e in tc.list_entities()]
clean = [enrich(r) for r in dedupe(rows, "latest")]

out = []
for r in sorted(clean, key=lambda x: (str(x["business_date"]), x["source_name"])):
    out.append({
        "date": str(r["business_date"]),
        "vendorId": r["vendorId"],
        "source": r["source_name"],
        "recordsPartner": r["TotalRecords_Partner"],
        "recordsSap": r["TotalRecords_SAP"],
        "amountPartner": r["TotalAmount_Partner"],
        "amountSap": r["TotalAmount_SAP"],
        "matched": r["M00_Matched"],
        "missingInSap": r["A01_MissingSAP"],
        "missingInPartner": r["A02_MissingPartner"],
        "sapAmountHigh": r["A03_SAPAmountHigh"],
        "partnerAmountHigh": r["A04_PartnerAmountHigh"],
        "duplicates": r["A05_Duplicate"],
        "dateDifferences": r["A07_DateDifference"],
        "anomalies": r["total_anomalies"],
        "balanceDifference": r["balance_difference"],
        "matchRatePct": r["match_rate_pct"], "status": r["status"],
        "runCount": r["run_count"],
        "figuresVariedAcrossRuns": bool(r.get("figures_varied_across_runs")),
        "summary": r.get("GeneralSummary", ""),
    })
json.dump(out, open("dashboard_data.json", "w"), indent=1)
print(f"{len(out)} vendor-days -> dashboard_data.json")
print("dates:", sorted({r['date'] for r in out}))
