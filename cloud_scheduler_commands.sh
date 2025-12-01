#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID=${PROJECT_ID:-"your-gcp-project"}
REGION=${REGION:-"us-central1"}
SERVICE_URL=${SERVICE_URL:-"https://hithonix-recruitment-api-<hash>-uc.a.run.app"}
OIDC_SERVICE_ACCOUNT=${OIDC_SERVICE_ACCOUNT:-"scheduler-invoker@${PROJECT_ID}.iam.gserviceaccount.com"}

create_job() {
  local job_name=$1
  local schedule=$2
  local endpoint=$3
  gcloud scheduler jobs create http "$job_name" \
    --project "$PROJECT_ID" \
    --location "$REGION" \
    --schedule "$schedule" \
    --time-zone "UTC" \
    --http-method POST \
    --uri "${SERVICE_URL}${endpoint}" \
    --oidc-service-account-email "$OIDC_SERVICE_ACCOUNT" \
    --oidc-token-audience "$SERVICE_URL"
}

echo "Creating Riva L1 jobs..."
create_job "riva-l1-1300" "0 13 * * *" "/run-l1-batch"
create_job "riva-l1-2100" "0 21 * * *" "/run-l1-batch"

echo "Creating Arjun L2 jobs..."
create_job "arjun-l2-1600" "0 16 * * *" "/run-l2-batch"
create_job "arjun-l2-2300" "0 23 * * *" "/run-l2-batch"

echo "All scheduler jobs configured."
