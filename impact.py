import os, sys
from dotenv import load_dotenv; load_dotenv()
from azure.data.tables import TableServiceClient
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recon.dedup import dedupe, enrich

CONN = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
tc = TableServiceClient.from_connection_string(CONN).get_table_client(
    os.getenv("AZURE_TABLE", "summarylogs"))
rows = [dict(e) for e in tc.list_entities()]

raw_amt = sum(float(r.get("TotalAmount_Partner") or 0) for r in rows)
raw_rec = sum(int(r.get("TotalRecords_Partner") or 0) for r in rows)
clean = [enrich(r) for r in dedupe(rows, "latest")]
c_amt = sum(r["TotalAmount_Partner"] for r in clean)
c_rec = sum(r["TotalRecords_Partner"] for r in clean)

print(f"{'':22} {'RAW (wrong)':>18} {'DEDUPED (correct)':>20}")
print(f"{'rows':22} {len(rows):>18,} {len(clean):>20,}")
print(f"{'records':22} {raw_rec:>18,} {c_rec:>20,}")
print(f"{'AED':22} {raw_amt:>18,.2f} {c_amt:>20,.2f}")
print(f"{'overstatement':22} {'':>18} {raw_amt - c_amt:>20,.2f}  ({raw_amt/c_amt:.1f}x)")

print(f"\n{'DATE':<12} {'VENDOR':<32} {'RECS':>7} {'AED':>15} {'ANOM':>5} {'RUNS':>5}  STATUS")
for r in sorted(clean, key=lambda x: (x["business_date"], x["source_name"])):
    flag = "!" if r["run_count"] > 1 else " "
    print(f"{str(r['business_date']):<12} {r['source_name'][:31]:<32} "
          f"{r['TotalRecords_Partner']:>7,} {r['TotalAmount_Partner']:>15,.2f} "
          f"{r['total_anomalies']:>5} {r['run_count']:>4}{flag} {r['status']}")

nr = [r for r in clean if not r["is_reconciled"]]
print(f"\nreconciled: {len(clean)-len(nr)}/{len(clean)} vendor-days")
print(f"total balance difference: AED {sum(r['balance_difference'] for r in clean):,.2f}")
