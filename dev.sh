#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR}"
ENV_FILE=${ENV_FILE:-"${PROJECT_ROOT}/.env"}

if [[ -f "${ENV_FILE}" ]]; then
  echo "Loading environment variables from ${ENV_FILE}"
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
else
  echo "No .env file found at ${ENV_FILE}; proceeding with existing environment"
fi

# Ensure critical env defaults for local development
export RECRUITER_SHEET_FILE_ID="${RECRUITER_SHEET_FILE_ID:-1ZqNfOsyyNs5wBSTU8Xm-IxZAF1X27SpJsDwyaAwvpj4}"
export GOOGLE_APPLICATION_CREDENTIALS="${GOOGLE_APPLICATION_CREDENTIALS:-infrastructure/service_account.json}"

PORT=${PORT:-8000}
APP_MODULE=${APP_MODULE:-main:app}
ENABLE_JOB_SCHEDULER=${ENABLE_JOB_SCHEDULER:-false}
UVICORN_BIN=${UVICORN_BIN:-.venv/bin/python}
UVICORN_ARGS=${UVICORN_ARGS:-"-m uvicorn"}
NGROK_BIN=${NGROK_BIN:-ngrok}

if ! command -v "${NGROK_BIN%% *}" >/dev/null 2>&1; then
  echo "ngrok is required. Install from https://ngrok.com/download" >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required" >&2
  exit 1
fi

if [[ -n "${NGROK_AUTHTOKEN:-}" ]]; then
  "${NGROK_BIN}" config add-authtoken "$NGROK_AUTHTOKEN" >/dev/null 2>&1 || true
fi

echo "Starting FastAPI on port ${PORT} (scheduler disabled=${ENABLE_JOB_SCHEDULER})"
ENABLE_JOB_SCHEDULER=${ENABLE_JOB_SCHEDULER} "${UVICORN_BIN}" ${UVICORN_ARGS} ${APP_MODULE} \
  --host 0.0.0.0 --port ${PORT} &
UVICORN_PID=$!

echo "Launching ngrok tunnel..."
NGROK_ARGS=(http ${PORT})
if [[ -n "${NGROK_DOMAIN:-}" ]]; then
  NGROK_ARGS+=(--domain "${NGROK_DOMAIN}")
fi
"${NGROK_BIN}" "${NGROK_ARGS[@]}" >/tmp/ngrok.log 2>&1 &
NGROK_PID=$!

cleanup() {
  echo "Shutting down..."
  kill ${NGROK_PID} >/dev/null 2>&1 || true
  kill ${UVICORN_PID} >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Poll ngrok API for public URL
for _ in {1..15}; do
  sleep 1
  if curl -s localhost:4040/api/tunnels >/tmp/ngrok-tunnels.json 2>/dev/null; then
    URL=$(python - <<'PY'
import json, sys
try:
    data = json.load(open('/tmp/ngrok-tunnels.json'))
    tunnels = data.get('tunnels', [])
    public = next((t['public_url'] for t in tunnels if t.get('proto') == 'https'), None)
    if public:
        print(public)
except Exception:
    pass
PY
)
    if [[ -n "$URL" ]]; then
      NGROK_URL="$URL"
      echo ""
      echo "✨ ngrok public URL: $NGROK_URL"
      echo "👉 Set Slack Event Subscription Request URL for Riva to:  $NGROK_URL/slack/riva"
      echo "👉 Set Slack Event Subscription Request URL for Arjun to: $NGROK_URL/slack/arjun"
      echo ""
      echo "If you use slash commands, point them to the same host:"
      echo "  Riva slash command:  $NGROK_URL/slash/riva  (if defined)"
      echo "  Arjun slash command: $NGROK_URL/slash/arjun (if defined)"
      echo ""
      break
    fi
  fi
  URL=""
done

wait ${UVICORN_PID}
