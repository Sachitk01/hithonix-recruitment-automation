#!/usr/bin/env bash
set -euo pipefail

# ---- Config ----
PROJECT_ID="${PROJECT_ID:-hithonix-recruitment-ai}"
REGION="${REGION:-asia-southeast1}"
SERVICE_NAME="${SERVICE_NAME:-hithonix-recruitment-automation}"
REPO_NAME="${REPO_NAME:-recruitment-bots}"
IMAGE_NAME="${IMAGE_NAME:-recruitment-automation}"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD)}"

IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${IMAGE_NAME}:${IMAGE_TAG}"

echo ">>> Deploying to Cloud Run"
echo "    PROJECT_ID : ${PROJECT_ID}"
echo "    REGION     : ${REGION}"
echo "    SERVICE    : ${SERVICE_NAME}"
echo "    IMAGE_URI  : ${IMAGE_URI}"
echo

# ---- GCloud config ----
gcloud config set project "${PROJECT_ID}"

# ---- Ensure Artifact Registry repo exists ----
echo ">>> Ensuring Artifact Registry repo '${REPO_NAME}' exists..."
gcloud artifacts repositories create "${REPO_NAME}" \
  --repository-format=docker \
  --location="${REGION}" \
  --description="Images for Hithonix recruitment automation bots" \
  || true

# ---- Build & push image ----
echo ">>> Building and pushing image..."
gcloud builds submit \
  --tag "${IMAGE_URI}" \
  --region="${REGION}"

# ---- Deploy to Cloud Run with PERMANENT service name ----
echo ">>> Deploying to Cloud Run service '${SERVICE_NAME}'..."
gcloud run deploy "${SERVICE_NAME}" \
  --image="${IMAGE_URI}" \
  --region="${REGION}" \
  --platform=managed \
  --allow-unauthenticated

# ---- Show final URL ----
SERVICE_URL="$(gcloud run services describe "${SERVICE_NAME}" --region="${REGION}" --format='value(status.url)')"
echo ">>> Deploy complete."
echo "    Service URL: ${SERVICE_URL}"