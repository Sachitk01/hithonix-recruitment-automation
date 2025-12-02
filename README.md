# Hithonix Recruitment Automation

FastAPI + Slack automation that evaluates candidates in Google Drive, orchestrates Riva L1 and Arjun L2 review loops, and surfaces actions through Slack bots and scheduled Cloud Run jobs.

## TL;DR

- **What it does** – Normalizes Drive folders, runs L1/L2 AI evaluations, updates Google Sheets, and lets recruiters drive workflows from Slack.
- **How it runs** – Containerized FastAPI service deployed to Cloud Run (gen2), backed by Google Secret Manager, Cloud Scheduler, and GitHub Actions.
- **How to work on it** – Install dependencies with `pip`, run `./dev.sh` for ngrok + uvicorn, run tests with `pytest`, deploy with `cloudrun_build_and_deploy.sh` or `cloudrun.yaml`.

## Table of contents

1. [System overview](#system-overview)
2. [Architecture & flow](#architecture--flow)
3. [Technology stack](#technology-stack)
4. [Repository layout](#repository-layout)
5. [Environment & secrets](#environment--secrets)
6. [Local development](#local-development)
7. [Slack integration](#slack-integration)
8. [Batch jobs & schedulers](#batch-jobs--schedulers)
9. [Testing & quality](#testing--quality)
10. [Deployment & operations](#deployment--operations)
11. [Monitoring & troubleshooting](#monitoring--troubleshooting)
12. [Handover checklist](#handover-checklist)
13. [Reference documents](#reference-documents)

## System overview

The service ingests candidate data from Google Drive, applies AI-driven evaluation at two stages (Riva L1 and Arjun L2), routes folders automatically, persists structured outputs, and exposes controls via Slack and HTTP endpoints. Everything runs inside a single FastAPI app (`main.py`) with routers for Slack bots, batch triggers, and health checks.

### Core capabilities

- **Normalization & inference pipelines** – `normalizer.py`, `riva_l1` and `arjun_l2` packages parse Drive artifacts, build prompts, and evaluate candidates via OpenAI APIs.
- **Slack assistants** – `slack_riva.py` and `slack_arjun.py` expose slash-command style interactions for recruiters.
- **Batch jobs** – `batch_jobs.py` coordinates daily runs and can be triggered manually or via Cloud Scheduler.
- **Memory layer** – `memory_service.py` (SQLAlchemy) keeps longitudinal candidate + role context for smarter prompts.
- **Observability hooks** – structured logging, `/debug-port`, `/health`, and Slack notifications for success/failure.

## Architecture & flow

```
Google Drive ➜ Normalizer ➜ Riva L1 ➜ Sheets/Drive updates
                                         ↘ send-to-L2 ➜ Arjun L2 ➜ Final routing

Slack (events + slash commands) ───────────────┐
                                              │
Cloud Scheduler (HTTP POST jobs) ───────▶ FastAPI/Cloud Run ◀── Secret Manager
                                              │
                                   Google Sheets & Memory DB
```

Key points:

1. **FastAPI gateway** – All HTTP traffic (Slack events, batch triggers, health checks) lands in `main.py`. Request logging middleware tags requests with a friendly `actor` label for easier debugging.
2. **Slack routers** – `slack_riva.py` & `slack_arjun.py` verify Slack requests (type `url_verification`, retries, bot-echo ignores) and hand off to `slack_bots.py` for business logic.
3. **Pipelines** – `riva_l1` and `arjun_l2` folders encapsulate evaluation prompts, models, and services. Decisions, status files, and Drive routing live in `decision_store.py`, `riva_output_writer.py`, etc.
4. **Persistence** – Memory layer defaults to SQLite; set `MEMORY_DB_URL` for Postgres when running in Cloud SQL.
5. **Automation** – `cloud_scheduler_commands.sh` (or Terraform) posts to `/run-l1-batch` and `/run-l2-batch` twice daily; Slack bots announce summaries.

## Technology stack

| Layer | Technology |
| --- | --- |
| API & background jobs | FastAPI, APScheduler |
| Language/runtime | Python 3.11, Uvicorn |
| AI providers | OpenAI GPT models (via `riva_l1_service.py`, `arjun_l2_service.py`) |
| Storage | Google Drive (artifacts), Google Sheets (dashboards), SQLite/Postgres memory DB |
| Messaging/UI | Slack bots (Events API + Web API) |
| Deployment | Docker, Cloud Run (Gen2), GitHub Actions |
| Automation | Cloud Scheduler, Terraform (optional) |
| Secrets | Google Secret Manager |

## Repository layout

```
├── main.py                     # FastAPI entrypoint
├── batch_jobs.py               # Orchestrates L1/L2 batches
├── riva_l1/, arjun_l2/         # Pipeline prompts, services, decision engines
├── slack_riva.py, slack_arjun.py
├── slack_service.py / slack_bots.py
├── drive_service.py / folder_resolver.py / normalizer.py
├── memory_service.py / memory_config.py
├── requirements*.txt
├── tests/                      # pytest suites (Slack, memory, decision logic…)
├── cloudrun.yaml               # Declarative deployment manifest
├── cloudrun_build_and_deploy.sh
├── cloud_scheduler_commands.sh / terraform/
└── docs/ (see PROJECT_DOCUMENT.md below)
```

## Environment & secrets

1. Copy `.env.example` to `.env` for local runs. `dev.sh` loads it automatically.
2. Sensitive values live in **Google Secret Manager** and are injected into Cloud Run via `env.yaml` (see sample names below). Secret references may also use the `gcp-secret://` notation locally if `GOOGLE_APPLICATION_CREDENTIALS` is configured.
3. Required secrets/vars:
   - `OPENAI_API_KEY`
   - `RIVA_SA_JSON_CONTENT` (Drive service account JSON)
   - `SLACK_RIVA_*` and `SLACK_ARJUN_*` (bot tokens, signing secrets, app tokens, default channel IDs, bot user IDs)
   - `RECRUITER_SHEET_FILE_ID`, `RAW_LOG_SHEET_NAME`, `DASHBOARD_SHEET_NAME`
   - Optional: `ENABLE_JOB_SCHEDULER`, `MEMORY_*` flags, `NGROK_*` for local testing.

### Managing secrets

```bash
gcloud secrets create openai-api-key --replication-policy=automatic
echo "sk-..." | gcloud secrets versions add openai-api-key --data-file=-

gcloud secrets add-iam-policy-binding openai-api-key \
  --member="serviceAccount:<cloud-run-sa>@hithonix-recruitment-ai.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

Update `env.yaml` to reference secrets via `valueFrom.secretKeyRef` (already configured in this repo). Re-run `gcloud run services replace env.yaml` after any change.

## Local development

1. **Prerequisites** – Python 3.11, Docker (optional), ngrok (for Slack callbacks), `gcloud` CLI.
2. **Bootstrap environment**
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. **Start the dev workflow**
   ```bash
   ./dev.sh
   ```
   - Spins up uvicorn with auto-reload on `http://127.0.0.1:8000`.
   - Disables the in-process scheduler to avoid duplicate cron runs.
   - Launches ngrok and prints the public HTTPS URL for Slack testing.
4. **Manual start (no script)**
   ```bash
   export ENABLE_JOB_SCHEDULER=false
   uvicorn main:app --reload --port 8000
   ```

## Slack integration

**Production Cloud Run base URL:** `https://hithonix-recruitment-automation-382401344182.asia-southeast1.run.app`

| Bot  | Slack Events API URL | Slash command URL |
| --- | --- | --- |
| **Riva**  | `https://hithonix-recruitment-automation-382401344182.asia-southeast1.run.app/slack-riva/events` | `https://hithonix-recruitment-automation-382401344182.asia-southeast1.run.app/slack/riva` |
| **Arjun** | `https://hithonix-recruitment-automation-382401344182.asia-southeast1.run.app/slack-arjun/events` | `https://hithonix-recruitment-automation-382401344182.asia-southeast1.run.app/slack/arjun` |

1. Create two Slack Apps (or one app with two bots) via api.slack.com.
2. Configure Event Subscriptions with the URLs above. Slack will send a `url_verification` challenge that the routers already handle.
3. Configure Slash Commands (`/riva`, `/arjun`) pointing to the production URLs above (or your ngrok tunnel while developing).
4. Store tokens/secrets in Secret Manager or `.env`.
5. When Slack retries, the routers short-circuit using `X-Slack-Retry-Num`; no extra setup needed.

### Slack configuration checklist

- **Riva bot**
   - Event Subscriptions → Request URL = `.../slack-riva/events`
   - Subscribe to bot events: `message.im`, `app_mention`
   - Slash Command `/riva` → Request URL = `.../slack/riva`
- **Arjun bot**
   - Event Subscriptions → Request URL = `.../slack-arjun/events`
   - Subscribe to bot events: `message.im`, `app_mention`
   - Slash Command `/arjun` → Request URL = `.../slack/arjun`

### Supported commands

See [`IMPLEMENTATION_SUMMARY.md`](./IMPLEMENTATION_SUMMARY.md#slack-commands) for the full matrix of `summary`, `ready-for-l2`, `hires`, `last-run-summary`, etc.

## Batch jobs & schedulers

- `batch_jobs.py` exposes `run_riva_l1_batch` and `run_arjun_l2_batch`, which the HTTP endpoints `/run-l1-batch` and `/run-l2-batch` invoke.
- APScheduler registers the same jobs when `ENABLE_JOB_SCHEDULER=true` (disabled in dev via `dev.sh`).
- Cloud Scheduler jobs (13:00 & 21:00 for L1, 16:00 & 23:00 for L2 UTC) call the HTTP endpoints using a service account with `roles/run.invoker`.
- Provision schedulers via `cloud_scheduler_commands.sh` or Terraform (`terraform/cloud_scheduler.tf`).

## Testing & quality

```bash
./run_tests.sh all          # wrapper
# or
.venv/bin/python -m pytest tests -v
```

Test suites cover Slack bots, decision engines, evaluation converters, memory service, and batch orchestration. Add new tests under `tests/` and keep them runnable via `pytest` with zero external dependencies (Drive/Slack calls are mocked).

## Deployment & operations

### Container build & deploy (scripted)

```bash
export PROJECT_ID=hithonix-recruitment-ai
export REGION=asia-south1
./cloudrun_build_and_deploy.sh
```

The script builds the Docker image, pushes to Artifact Registry, and deploys to Cloud Run using the same command sequence as GitHub Actions.

### Declarative deploy

`cloudrun.yaml` / `env.yaml` capture the service spec (image, CPU/memory, min/max instances, env vars). Deploy with:

```bash
gcloud run services replace env.yaml --region=asia-south1
```

### GitHub Actions

- See `.github/workflows/deploy-cloudrun.yml` (create `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_SA_EMAIL`, `GCP_WORKLOAD_IDENTITY_PROVIDER` secrets).
- On push to `main`, the workflow builds, pushes, and deploys automatically.

### IAM & networking

- **Public ingress**: allow unauthenticated invocations with `gcloud run services add-iam-policy-binding ... --member="allUsers"` if Slack/OpenAI must call directly.
- **Private ingress**: remove that binding and issue ID tokens via service accounts for internal callers.
- Keep the runtime service account minimal (Secret Manager Accessor, Cloud Logging Writer, Cloud Trace Writer, Cloud Run Invoker by Cloud Scheduler SA).

## Monitoring & troubleshooting

- **Health checks** – `GET /health` and `/healthz` for Cloud Run probes.
- **Port debugging** – `GET /debug-port` returns the resolved `PORT` plus helpful metadata when diagnosing Cloud Run ingress.
- **Logs** – Structured logs include `actor`, request IDs, and Slack-related metadata. Filter in Cloud Logging by `logName="projects/<project>/logs/run.googleapis.com%2Frequests"`.
- **Common issues**
  - *Slack URL verification fails* → ensure `/slack-riva/events` is reachable and service allows unauthenticated traffic.
  - *403 from Cloud Run* → missing `roles/run.invoker` binding.
  - *Secret access denied* → grant `roles/secretmanager.secretAccessor` to the Cloud Run runtime service account for each secret ID.

## Handover checklist

- [ ] Rotate OpenAI, Slack, and service-account secrets after onboarding a new maintainer.
- [ ] Confirm Cloud Run IAM (public vs private) matches the Slack/OpenAI integration approach.
- [ ] Verify Cloud Scheduler jobs exist and are hitting the correct URLs.
- [ ] Run `pytest` before merging any change; CI must remain green.
- [ ] Update `env.yaml` + `README.md` whenever env vars or architecture change.
- [ ] Keep Slack App manifests (dev + prod) up to date with current URLs.

## Reference documents

- [`IMPLEMENTATION_SUMMARY.md`](./IMPLEMENTATION_SUMMARY.md) – Deep dive into pipelines, gating, and Slack commands.
- [`PROJECT_DOCUMENT.md`](./PROJECT_DOCUMENT.md) – Comprehensive project guide for developers, testers, architects, and stakeholders (created alongside this README).

For questions, check the Slack `#recruitment-automation` channel or reach out to the on-call engineer listed in the runbook.
