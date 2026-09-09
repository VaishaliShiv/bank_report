#!/usr/bin/env bash
# ============================================================================
#  Deploy to Azure App Service - the fewest steps to a running API.
#
#    az login
#    ./deploy/deploy_appservice.sh
#
#  No Docker, no registry. Azure installs requirements.txt and runs the app.
#  Prefer deploy.sh (Container Apps) if the service will sit idle most of the
#  day: it scales to zero, where App Service bills continuously.
# ============================================================================
set -euo pipefail

RG="${RG:-rg-payment-reconciliation}"
LOCATION="${LOCATION:-uaenorth}"
APP="${APP:-recon-api}"
SKU="${SKU:-B1}"
STORAGE="${STORAGE:?Set STORAGE to your storage account name}"
ENVIRONMENT="${ENVIRONMENT:-dev}"

cd "$(dirname "$0")/.."

echo "==> deploying $APP from $(pwd)"
az webapp up --name "$APP" --resource-group "$RG" --location "$LOCATION" \
  --runtime "PYTHON:3.12" --sku "$SKU" -o none

echo "==> startup command"
az webapp config set --name "$APP" --resource-group "$RG" \
  --startup-file "gunicorn -w 2 -k uvicorn.workers.UvicornWorker --timeout 120 api.main:app" \
  -o none

HOST="https://$APP.azurewebsites.net"
API_KEY="${API_KEY:-$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')}"

echo "==> app settings"
az webapp config appsettings set --name "$APP" --resource-group "$RG" --settings \
  ENVIRONMENT="$ENVIRONMENT" \
  AZURE_STORAGE_ACCOUNT="$STORAGE" \
  AZURE_TABLE=summarylogs \
  API_KEY="$API_KEY" \
  CORS_ORIGINS="$HOST" \
  DEDUP_STRATEGY=latest \
  SCM_DO_BUILD_DURING_DEPLOYMENT=true \
  -o none

echo "==> managed identity + table read access"
az webapp identity assign --name "$APP" --resource-group "$RG" -o none
PRINCIPAL=$(az webapp identity show --name "$APP" --resource-group "$RG" \
            --query principalId -o tsv)
SCOPE=$(az storage account list --query "[?name=='$STORAGE'].id" -o tsv)
az role assignment create --assignee "$PRINCIPAL" \
  --role "Storage Table Data Reader" --scope "$SCOPE" -o none 2>/dev/null \
  || echo "    (already assigned, or you lack permission - see README)"

cat <<EOF

============================================================
  Deployed.

  $HOST/readyz
  $HOST/api/v1/report/latest

  API key   $API_KEY
            Send as the x-api-key header.

  Check it:
    curl $HOST/readyz
    -> {"status":"ready","vendorDays":N,"auth":"managed-identity"}
============================================================
EOF
