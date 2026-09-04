"""Read-only probe of the Azure Table / Cosmos Table API reconciliation log.

Run:  python3 discover_table.py                # list tables + profile
      python3 discover_table.py --table NAME   # profile one table
Only lists and queries. Never prints the connection string or account key.
"""
import argparse, os, re, sys
from collections import Counter, defaultdict
from datetime import datetime

try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass

CONN = (os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        or os.getenv("COSMOS_CONNECTION_STRING") or "").strip()
if not CONN:
    sys.exit("No AZURE_STORAGE_CONNECTION_STRING in .env\n"
             "  cp .env.example .env   then paste your connection string in.")

from azure.data.tables import TableServiceClient  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--table", default=(os.getenv("AZURE_TABLE") or os.getenv("COSMOS_TABLE") or "").strip())
ap.add_argument("--limit", type=int, default=500, help="rows to profile")
args = ap.parse_args()

acct = re.search(r"AccountName=([^;]+)", CONN)
print(f"Account : {acct.group(1)[:3] + '***' if acct else '***'}\n")

svc = TableServiceClient.from_connection_string(CONN)
tables = [t.name for t in svc.list_tables()]
print(f"Tables ({len(tables)}): {', '.join(tables)}\n")

targets = [args.table] if args.table else tables

def parse_dt(s):
    for fmt in ("%d-%m-%Y-%H%M%S", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(s), fmt)
        except (ValueError, TypeError):
            pass
    return None

for name in targets:
    print("=" * 72); print(f"TABLE: {name}"); print("=" * 72)
    tc = svc.get_table_client(name)
    rows = []
    for i, e in enumerate(tc.list_entities()):
        rows.append(e)
        if i + 1 >= args.limit:
            break
    if not rows:
        print("  (empty)\n"); continue
    print(f"  profiled {len(rows)} rows"
          f"{' (capped — table is larger)' if len(rows) == args.limit else ''}\n")

    fields = defaultdict(lambda: {"t": Counter(), "null": 0, "eg": None})
    for r in rows:
        for k, v in r.items():
            f = fields[k]
            if v is None or v == "":
                f["null"] += 1; f["t"]["empty"] += 1
            else:
                f["t"][type(v).__name__] += 1
                if f["eg"] is None: f["eg"] = v
    print("  COLUMNS")
    for k, f in sorted(fields.items()):
        eg = repr(f["eg"]); eg = eg[:52] + "..." if len(eg) > 55 else eg
        warn = f"  [{f['null']} empty]" if f["null"] else ""
        print(f"    {k:<26} {'/'.join(f['t']):<14} {eg}{warn}")

    # ---- the things that actually decide the design ----
    print("\n  DUPLICATE-RUN CHECK  (vendorid + business date)")
    runs = defaultdict(list)
    for r in rows:
        d = parse_dt(r.get("uploadDate"))
        key = (str(r.get("vendorId")), d.date().isoformat() if d else "UNPARSED")
        runs[key].append(r)
    multi = {k: v for k, v in runs.items() if len(v) > 1}
    print(f"    unique vendor-days : {len(runs)}")
    print(f"    with >1 run        : {len(multi)}")
    if multi:
        print("    worst offenders:")
        for k, v in sorted(multi.items(), key=lambda x: -len(x[1]))[:5]:
            amts = {r.get("TotalAmount_Partner") for r in v}
            same = "identical figures" if len(amts) == 1 else f"*** {len(amts)} DIFFERENT amounts ***"
            print(f"      {k[0]} on {k[1]}: {len(v)} runs — {same}")

    print("\n  DATE COVERAGE")
    dates = sorted({parse_dt(r.get("uploadDate")).date() for r in rows
                    if parse_dt(r.get("uploadDate"))})
    bad = sum(1 for r in rows if not parse_dt(r.get("uploadDate")))
    if dates:
        print(f"    {dates[0]} → {dates[-1]}   ({len(dates)} distinct days)")
    if bad:
        print(f"    *** {bad} rows failed dd-MM-yyyy-HHmmss parsing ***")

    print("\n  VENDORS")
    vs = Counter((str(r.get("vendorId")), r.get("source_name")) for r in rows)
    for (vid, nm), n in sorted(vs.items()):
        print(f"    {vid:<10} {str(nm)[:44]:<46} {n} runs")

    print("\n  ANOMALY CODES SEEN")
    codes = [c for c in fields if re.match(r"^A\d\d_|^M00", c)]
    for c in sorted(codes):
        tot = sum(r.get(c) or 0 for r in rows)
        hits = sum(1 for r in rows if (r.get(c) or 0) > 0)
        print(f"    {c:<24} total={tot:<10,} rows_with_hits={hits}")
    print()

# ---- blobs: the anomaly line-item detail may live here ----
try:
    from azure.storage.blob import BlobServiceClient
    print("=" * 72); print("BLOB CONTAINERS"); print("=" * 72)
    bsc = BlobServiceClient.from_connection_string(CONN)
    for c in bsc.list_containers():
        bc = bsc.get_container_client(c.name)
        blobs = []
        for i, b in enumerate(bc.list_blobs()):
            blobs.append(b)
            if i >= 7: break
        print(f"\n  {c.name}  ({len(blobs)}{'+' if len(blobs) > 7 else ''} blobs)")
        for b in blobs:
            print(f"     {b.name}  ({b.size:,} bytes)")
except ImportError:
    print("\n(azure-storage-blob not installed — skipping blob scan)")
except Exception as e:
    print(f"\n(blob scan failed: {type(e).__name__})")
