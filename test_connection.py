"""Minimal connectivity check: connect, list tables, pull a few rows."""
import os, re, sys
try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass

CONN = (os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        or os.getenv("COSMOS_CONNECTION_STRING") or "").strip()
if not CONN or "<" in CONN:
    sys.exit(
        "✗ No connection string found.\n\n"
        "  The scripts read a file called  .env  (not .env.example).\n"
        "  If you edited .env.example by mistake:\n\n"
        "      copy .env.example .env      (Windows)\n"
        "      cp   .env.example .env      (Linux/macOS)\n"
        "      git checkout .env.example   <- puts the template back, so your\n"
        "                                     key is not in a tracked file\n\n"
        "  Then open .env and paste your string after:\n"
        "      AZURE_STORAGE_CONNECTION_STRING=")

from azure.data.tables import TableServiceClient
from azure.core.exceptions import AzureError

acct = re.search(r"AccountName=([^;]+)", CONN)
print(f"→ connecting to {acct.group(1)[:3] + '***' if acct else '***'} ...")

try:
    svc = TableServiceClient.from_connection_string(CONN)
    tables = [t.name for t in svc.list_tables()]
except AzureError as e:
    sys.exit(f"✗ connection failed: {type(e).__name__}: {str(e)[:200]}")
except Exception as e:
    sys.exit(f"✗ {type(e).__name__}: {str(e)[:200]}")

print(f"✓ connected. {len(tables)} table(s): {', '.join(tables) or '(none)'}")

target = (os.getenv("AZURE_TABLE") or os.getenv("COSMOS_TABLE") or "").strip() or (tables[0] if tables else None)
if not target:
    sys.exit("✗ no tables found in this account")
print(f"\n→ fetching 5 rows from '{target}' ...\n")

tc = svc.get_table_client(target)
rows = []
for i, e in enumerate(tc.list_entities()):
    rows.append(e)
    if i >= 4: break

if not rows:
    sys.exit("  table is empty")

for n, r in enumerate(rows, 1):
    print(f"  --- row {n} ---")
    for k, v in r.items():
        s = str(v)
        print(f"    {k:<26} {s[:70] + '...' if len(s) > 70 else s}")
    print()
print(f"✓ fetched {len(rows)} rows — connection works.")
