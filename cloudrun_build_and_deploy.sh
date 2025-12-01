#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID=${PROJECT_ID:-"your-gcp-project"}
REGION=${REGION:-"us-central1"}
SERVICE_NAME=${SERVICE_NAME:-"hithonix-recruitment-api"}
IMAGE="gcr.io/${PROJECT_ID}/${SERVICE_NAME}:$(git rev-parse --short HEAD)"

if ! command -v gcloud >/dev/null 2>&1; then
  echo "gcloud CLI is required" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker CLI is required" >&2
  exit 1
fi

echo "Building container ${IMAGE}..."
docker build -t "${IMAGE}" .

echo "Pushing container to Artifact Registry..."
gcloud auth configure-docker --quiet
docker push "${IMAGE}"

echo "Deploying to Cloud Run service ${SERVICE_NAME} in ${REGION}..."
gcloud run deploy "${SERVICE_NAME}" \
  --image "${IMAGE}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --allow-unauthenticated \
  --port 8080 \
  --platform managed \
  --execute-now \
  --timeout=600s

echo "Deployment complete."
