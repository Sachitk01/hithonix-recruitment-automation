# Hithonix Recruitment Automation – Project Handbook

_Last updated: 2025-12-02_

This document is the single source of truth for engineers, QA, architects, and stakeholders who need to understand, operate, and extend the recruitment automation platform. Pair it with `README.md` for quick-start instructions.

## 1. Audience & objectives

| Persona | What they need |
| --- | --- |
| **Engineering / DevOps** | How the system is structured, how to run tests, deploy, and debug. |
| **QA & Automation** | Where the test suites live, environments to validate, expected inputs/outputs. |
| **Architects** | End-to-end flow, integration points, security posture, SLAs. |
| **Management / Stakeholders** | Business context, release cadence, known risks, and ownership. |

## 2. Executive summary

- Automates candidate triage by orchestrating Riva L1 and Arjun L2 AI reviews on Google Drive artifacts.
- Exposes Slack bots so recruiters can trigger summaries, manual reviews, and batch metrics without leaving Slack.
- Runs fully serverless on Cloud Run (gen2) with Cloud Scheduler triggers, Google Secret Manager, and Artifact Registry.
- Built with FastAPI + Python 3.11, leveraging OpenAI for reasoning and SQLAlchemy for optional persistence.

## 3. High-level architecture

```
Cron (Cloud Scheduler) ──▶ POST /run-l1-batch, /run-l2-batch
Slack Events & Commands ─▶ POST /slack/riva, /slack/arjun, /slack-riva/events, /slack-arjun/events
Manual callers / APIs ───▶ GET /health, /debug-port, POST batch endpoints
                                   │
                                   ▼
                         FastAPI (main.py) on Cloud Run
                                   │
   ┌───────────────┬───────────────┬───────────────┬───────────────┐
   │Drive services │Riva L1 engine │Arjun L2 engine│Slack services │
   └───────────────┴───────────────┴───────────────┴───────────────┘
             │                 │                 │
             ▼                 ▼                 ▼
    Google Drive & Sheets   Memory DB (SQLite/Postgres)   Slack Web API
```

**Key data flows**
1. **Drive ➜ Normalizer**: Candidate folders are normalized (`normalization_report.json`).
2. **Riva L1**: Applies gating, calls OpenAI via `RivaL1Service`, writes `l1_result.json` & status, routes to L2.
3. **Arjun L2**: Re-evaluates promoted folders, produces `l2_result.json`, updates Sheets & Drive destinations.
4. **Slack bots**: Surface summaries, metrics, and manual reviews; handle slash commands and event subscriptions.
5. **Schedulers**: Twice-daily Cloud Scheduler jobs hit `/run-l1-batch` and `/run-l2-batch` to keep pipelines fresh.

## 4. Component breakdown

| Component | Location | Notes |
| --- | --- | --- |
| FastAPI app | `main.py` | Configures middleware, Slack routers, batch endpoints, health checks, scheduler lifecycle. |
| Slack bots | `slack_riva.py`, `slack_arjun.py`, `slack_bots.py`, `slack_service.py` | Validate Slack signatures, map commands to bot behavior, send replies via Web API. |
| Riva L1 pipeline | `riva_l1/` (decision engine, prompts, services) | Normalizes artifacts, enforces L1 gating, moves folders. |
| Arjun L2 pipeline | `arjun_l2/` | Consumes L1 outputs, produces final recommendations, updates Google Sheets + Drive. |
| Memory layer | `memory_service.py`, `memory_config.py` | Optional SQLAlchemy persistence for candidate/role context. SQLite by default. |
| Batch orchestration | `batch_jobs.py`, `manual_review_triggers.py` | Expose Python + HTTP entry points for scheduled or manual runs. |
| Infrastructure scripts | `cloudrun_build_and_deploy.sh`, `cloudrun.yaml`, `cloud_scheduler_commands.sh`, `terraform/` | Deployment + IaC. |
| Tests | `tests/` and root `test_*.py` | Pytest suites for Slack, decision engines, memory, batches. |

## 5. Environments & URLs

| Environment | Base URL | Notes |
| --- | --- | --- |
| **Local dev** | `http://127.0.0.1:8000` + ngrok tunnel | Run via `./dev.sh`. Scheduler disabled, Slack hits ngrok URL. |
| **Production (Cloud Run)** | `https://hithonix-recruitment-automation-382401344182.asia-southeast1.run.app` | Deployed in `asia-south1` Artifact Registry & `asia-southeast1` Cloud Run. Public ingress allowed for Slack/OpenAI. |

### Slack endpoints

| Bot | Events API URL | Slash command URL |
| --- | --- | --- |
| **Riva** | `https://hithonix-recruitment-automation-382401344182.asia-southeast1.run.app/slack-riva/events` | `https://hithonix-recruitment-automation-382401344182.asia-southeast1.run.app/slack/riva` |
| **Arjun** | `https://hithonix-recruitment-automation-382401344182.asia-southeast1.run.app/slack-arjun/events` | `https://hithonix-recruitment-automation-382401344182.asia-southeast1.run.app/slack/arjun` |

### Slack configuration checklist

1. **Create apps** – Separate Slack apps (or bot configurations) for Riva and Arjun.
2. **Event Subscriptions** – Enable, set the Request URLs above, and subscribe to `message.im` + `app_mention` for each bot. URL verification is auto-handled.
3. **Slash commands** – Create `/riva` pointing to `.../slack/riva` and `/arjun` pointing to `.../slack/arjun`.
4. **Tokens & secrets** – Rotate bot tokens and signing secrets via Secret Manager; redeploy Cloud Run afterward.
5. **Verification** – After deploys, re-check Slack dashboards for a green status on Event Subscriptions and slash commands.

## 6. Configuration & secrets

| Variable | Purpose | Where stored |
| --- | --- | --- |
| `OPENAI_API_KEY` | OpenAI access for both pipelines | Secret Manager `openai-api-key` |
| `RIVA_SA_JSON_CONTENT` | Drive service account JSON blob | Secret Manager `riva-sa-json-content` |
| `SLACK_RIVA_BOT_TOKEN`, `SLACK_RIVA_SIGNING_SECRET`, `SLACK_RIVA_APP_TOKEN`, `SLACK_RIVA_APP_ID`, `SLACK_RIVA_BOT_USER_ID`, `SLACK_RIVA_DEFAULT_CHANNEL_ID` | Riva bot auth | Secret Manager (one per value) |
| `SLACK_ARJUN_*` equivalents | Arjun bot auth | Secret Manager |
| `RECRUITER_SHEET_FILE_ID`, `RAW_LOG_SHEET_NAME`, `DASHBOARD_SHEET_NAME` | Sheets integration | Secret Manager / env |
| `ENABLE_JOB_SCHEDULER` | Toggle APScheduler | Env var |
| `MEMORY_ENABLED`, `MEMORY_DB_URL` | Memory persistence | Env var |

### Secret access
- Cloud Run runtime service account must have `roles/secretmanager.secretAccessor` for every secret listed above.
- Cloud Scheduler service account requires `roles/run.invoker` to call the HTTP endpoints.

## 7. Development workflow

1. Clone repo and run `python3 -m venv .venv && source .venv/bin/activate`.
2. Install dependencies: `pip install -r requirements.txt`.
3. Copy `.env.example` ➜ `.env`, populate necessary keys for local runs.
4. Start dev stack: `./dev.sh` (brings up uvicorn + ngrok, disables scheduler).
5. Update Slack App manifest with printed ngrok URL for `POST /slack/riva` and `/slack/arjun`.
6. Make code changes (see lint/test section below).
7. Run tests via `pytest` before submitting PRs.

Branching guidelines are conventional `main` + feature branches. CI (GitHub Actions) deploys on push to `main`.

## 8. Testing strategy

| Layer | Command | Coverage |
| --- | --- | --- |
| Unit / integration | `./run_tests.sh all` or `pytest tests -v` | Slack bots, decision engines, memory service, batch jobs. |
| Manual | Slack workflows via ngrok, Drive/Sheets smoke tests | Validate real integrations before releases. |
| Scheduled | Cloud Scheduler logs, Slack summary notifications | Monitor production runs twice daily. |

Add new tests under `tests/`. Use dependency injection/mocking for external services (Slack, Drive, OpenAI) to keep tests deterministic.

## 9. Deployment runbook

### Automated (GitHub Actions)
1. Push to `main`.
2. Workflow builds Docker image, pushes to Artifact Registry, calls `gcloud run deploy` using Workload Identity Federation.
3. Observability: track workflow logs in GitHub and Cloud Build/Run logs.

### Manual CLI
```bash
export PROJECT_ID=hithonix-recruitment-ai
export REGION=asia-south1
./cloudrun_build_and_deploy.sh   # builds + deploys
# or declaratively
gcloud run services replace env.yaml --region=asia-south1
```

### Post-deploy checklist
- Confirm `/health` passes.
- Hit `/debug-port` to verify Cloud Run injected `PORT` correctly.
- Re-run Slack Event Subscription verification if the URL changed.
- Inspect Cloud Run logs for errors during first batch run.

## 10. Operations & support

### Monitoring
- **Cloud Logging**: filter by `resource.type="cloud_run_revision"` & service name.
- **Slack**: batch summaries posted automatically after scheduled jobs.
- **Custom endpoints**: `/health`, `/healthz`, `/debug-port` for quick triage.

### Common procedures

| Task | Steps |
| --- | --- |
| Rotate secrets | Update Secret Manager value ➜ redeploy Cloud Run (`services replace`). |
| Re-run failed batch | `curl -X POST https://<service>/run-l1-batch` (or `/run-l2-batch`). |
| Update Slack URLs | Change Event Subscription + slash command URLs to new ngrok/Cloud Run endpoint. |
| Allow/deny unauthenticated access | `gcloud run services add/remove-iam-policy-binding ... --member="allUsers" --role="roles/run.invoker"`. |
| Inspect memory DB locally | Connect to `sqlite:///./talent_memory.db` (default) or configured Postgres URL. |

### Incident response
1. Check Cloud Logging for stack traces (`request_logging` logger).
2. Verify Google Drive + Sheets APIs are reachable (service-account creds current?).
3. Use `/debug-port` or `GET /health` to ensure container is running.
4. If Slack bots stop responding, check Event Subscriptions (challenge, retries, signing secret) and token scopes.

## 11. Security posture

- **Transport**: Cloud Run currently allows unauthenticated requests (requirement for Slack/OpenAI). If this changes, add a proxy layer or require ID tokens.
- **Secrets**: All sensitive values stored in Secret Manager and injected via `env.yaml`; never commit plaintext secrets.
- **Service accounts**: Runtime SA needs `secretAccessor`, `logging.logWriter`, and optional `trace.writer`. Scheduler SA only needs `run.invoker`.
- **Slack verification**: Signing secret enforced by routers; URL verification is handled automatically.

## 12. Handover & onboarding checklist

1. Rotate OpenAI + Slack secrets once new owners take control.
2. Grant relevant engineers access to Google Cloud project, Artifact Registry, and Slack App workspace.
3. Walk through local dev setup (`./dev.sh`, ngrok, Slack manifest update).
4. Review Cloud Scheduler jobs and ensure they point to the current Cloud Run URL.
5. Review Terraform/IaC if you plan to manage schedulers declaratively.
6. Document any pending Drive/Sheets structural changes in `docs/` or `IMPLEMENTATION_SUMMARY.md`.

## 13. Known gaps & backlog

- Cloud Run currently deployed in `asia-southeast1`; Artifact Registry image resides in `asia-south1`. Consider consolidating regions for latency/cost.
- Memory layer uses SQLite in production by default—migrate to managed Postgres for HA if memory insights become critical.
- GitHub Actions workflow references `.github/workflows/deploy-cloudrun.yml`; ensure secrets stay synchronized when rotating service accounts.
- Slack proxy/service-account approach is recommended if the service must be private again.

## 14. Contacts & ownership

- **Primary owner**: Recruitment Automation team (`#recruitment-automation` Slack channel).
- **Escalation**: Infra on-call engineer via `#platform-oncall`.
- **Service accounts**: `hithonix-recruitment-automation@hithonix-recruitment-ai.iam.gserviceaccount.com` (runtime) and `382401344182-compute@developer.gserviceaccount.com` (default).

---
Maintain this document alongside `README.md` whenever architecture, endpoints, or deployment processes change. Contributions welcome via PRs.
