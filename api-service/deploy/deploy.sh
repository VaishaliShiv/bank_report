#!/usr/bin/env bash
# ============================================================================
#  Deploy the Payment Reconciliation API to Azure Container Apps.
#  Builds from source in Azure — no local Docker needed.
#
#    az login
#    ./deploy/deploy.sh
#
#  Re-run after code changes; it updates the existing app in place.
# ============================================================================
set -euo pipefail

RG="${RG:-rg-payment-reconciliation}"
LOCATION="${LOCATION:-uaenorth}"
ENV_NAME="${ENV_NAME:-cae-reconciliation}"
APP="${APP:-recon-api}"
STORAGE="${STORAGE:-your-storage-account}"
ENVIRONMENT="${ENVIRONMENT:-dev}"
CORS_ORIGINS="${CORS_ORIGINS:-https://recon.example.com}"

cd "$(dirname "$0")/.."

echo "==> resource group $RG ($LOCATION)"
az group create -n "$RG" -l "$LOCATION" -o none

echo "==> container apps environment $ENV_NAME"
az containerapp env show -n "$ENV_NAME" -g "$RG" -o none 2>/dev/null || \
  az containerapp env create -n "$ENV_NAME" -g "$RG" -l "$LOCATION" -o none

# API key: reuse the existing one on redeploy so existing callers keep working
EXISTING=$(az containerapp secret show -n "$APP" -g "$RG" --secret-name api-key \
             --query value -o tsv 2>/dev/null || true)
API_KEY="${API_KEY:-${EXISTING:-$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')}}"

echo "==> building and deploying $APP"
az containerapp up \
  --name "$APP" --resource-group "$RG" --environment "$ENV_NAME" \
  --source . --ingress external --target-port 8000 -o none

echo "==> secrets and environment"
az containerapp secret set -n "$APP" -g "$RG" \
  --secrets "api-key=$API_KEY" -o none

az containerapp update -n "$APP" -g "$RG" \
  --set-env-vars \
    "ENVIRONMENT=$ENVIRONMENT" \
    "AZURE_STORAGE_ACCOUNT=$STORAGE" \
    "AZURE_TABLE=summarylogs" \
    "CORS_ORIGINS=$CORS_ORIGINS" \
    "DEDUP_STRATEGY=latest" \
    "API_KEY=secretref:api-key" \
  -o none

echo "==> managed identity + table read access"
az containerapp identity assign -n "$APP" -g "$RG" --system-assigned -o none
PRINCIPAL=$(az containerapp identity show -n "$APP" -g "$RG" --query principalId -o tsv)
SCOPE=$(az storage account show -n "$STORAGE" -g "$RG" --query id -o tsv 2>/dev/null \
        || az storage account list --query "[?name=='$STORAGE'].id" -o tsv)

az role assignment create --assignee "$PRINCIPAL" \
  --role "Storage Table Data Reader" --scope "$SCOPE" -o none 2>/dev/null \
  || echo "    (role already assigned, or you lack permission — see README)"

FQDN=$(az containerapp show -n "$APP" -g "$RG" \
        --query properties.configuration.ingress.fqdn -o tsv)

cat <<EOF

============================================================
  Deployed.

  API host   https://$FQDN
  Health     https://$FQDN/healthz
  Ready      https://$FQDN/readyz

  API key    $API_KEY
             ^ store this. Needed as the x-api-key header.

  Next:
    1. curl https://$FQDN/readyz
       -> {"status":"ready","vendorDays":10,"auth":"managed-identity"}
    2. Open https://$FQDN in a browser
    3. Send the API key with requests as the x-api-key header
============================================================
EOF
