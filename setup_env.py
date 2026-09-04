"""Interactive setup: writes a correct .env and tests the connection.

    python setup_env.py

Avoids hand-editing .env, which is where most setup goes wrong - a hidden
.txt extension, a stray quote, or the value pasted into .env.example.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(HERE, ".env")

print()
print("=" * 62)
print("  Payment Reconciliation - setup")
print("=" * 62)
print()
print("  Paste your Azure Storage connection string and press Enter.")
print()
print("  Get it from: Portal > your storage account > Access keys")
print("               > key1 > Connection string > Show > copy")
print()
print("  It starts with:  DefaultEndpointsProtocol=https;AccountName=...")
print("  Right-click pastes in Command Prompt.")
print()

raw = input("  Connection string: ").strip().strip('"').strip("'")

if not raw:
    sys.exit("\n  Nothing entered. Run this again when you have the string.\n")

if "AccountName=" not in raw or "AccountKey=" not in raw:
    print("\n  That does not look like a connection string.")
    print("  It must contain both AccountName= and AccountKey=.")
    print("  You may have copied just the key instead of the whole string.\n")
    sys.exit(1)

acct = re.search(r"AccountName=([^;]+)", raw)
table = input(f"  Table name [summarylogs]: ").strip() or "summarylogs"

if os.path.exists(ENV):
    if input("\n  .env already exists. Overwrite? [y/N]: ").strip().lower() != "y":
        sys.exit("\n  Left it alone.\n")

with open(ENV, "w", encoding="utf-8", newline="\n") as f:
    f.write("# Written by setup_env.py. Never commit this file.\n")
    f.write("ENVIRONMENT=local\n")
    f.write(f"AZURE_TABLE={table}\n")
    f.write(f"AZURE_STORAGE_CONNECTION_STRING={raw}\n")
    f.write("AZURE_STORAGE_ACCOUNT=\nAPI_KEY=\nCORS_ORIGINS=\n")
    f.write("CACHE_TTL_SECONDS=60\nDEDUP_STRATEGY=latest\n")

print(f"\n  Wrote {ENV}")
print(f"  Account: {acct.group(1)[:4] + '***' if acct else '***'}   Table: {table}")

print("\n  Testing the connection...\n")
try:
    from dotenv import load_dotenv
    load_dotenv(ENV, override=True)
    from azure.data.tables import TableServiceClient
    svc = TableServiceClient.from_connection_string(raw)
    names = [t.name for t in svc.list_tables()]
    print(f"  Connected. {len(names)} table(s): {', '.join(names)}")
    if table not in names:
        print(f"\n  Warning: '{table}' is not in that list.")
        print("  Re-run and enter one of the names above.")
        sys.exit(1)
    n = sum(1 for _ in svc.get_table_client(table).list_entities())
    print(f"  '{table}' holds {n} rows.")
except Exception as e:
    print(f"  Connection failed: {type(e).__name__}")
    print(f"  {str(e)[:180]}")
    print("\n  The .env file is written. Common causes:")
    print("    - the key was copied incompletely")
    print("    - an Azure firewall rule blocks your IP (try the VPN)")
    sys.exit(1)

print("\n" + "=" * 62)
print("  Ready. Now run:   run_api.bat")
print("  Then open:        http://localhost:8000")
print("=" * 62 + "\n")
