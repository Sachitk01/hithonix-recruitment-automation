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

## Slack assistants & intent routing

### Event lifecycle
1. Slack hits `/slack-riva/events` or `/slack-arjun/events`. Routers (`slack_riva.py`, `slack_arjun.py`) parse JSON, handle `url_verification`, validate signatures (`verify_slack_request`), and drop retries via `X-Slack-Retry-Num` headers.
2. Events flow into `handle_riva_event` / `handle_arjun_event`; bot echoes are ignored while DM vs `app_mention` events follow different flows.
3. `decide_intent()` in `decision_engine.py` classifies messages via deterministic rules + optional LLM fallback, returning intents like `L1_EVAL_SINGLE`, `L2_EVAL_SINGLE`, `PIPELINE_STATUS`, `DEBUG`, etc.
4. Actionable intents post an immediate ack (Slack Web API `chat_postMessage`) and then spawn background work via `anyio.to_thread.run_sync`, keeping responses under Slack’s 3-second limit.
5. `RivaSlackBot` / `ArjunSlackBot` (`slack_bots.py`) perform Drive lookups, read `l1_result.json` / `l2_result.json`, trigger manual reviews, or hand off to conversational chat handlers. Exceptions send `PIPELINE_ERROR_TEXT` to the originating channel.

### Commands, intents, fallbacks
- Greeting/help/small-talk intents reply with curated copy (`RIVA_GREETING_MESSAGE`, `ARJUN_HELP_MESSAGE`).
- Unknown/unsupported intents receive `RIVA_UNSURE_MESSAGE` / `ARJUN_UNSURE_MESSAGE`, nudging toward `summary <Candidate> - <Role>` syntax.
- Pipeline intents:
   - `L1_EVAL_SINGLE` / `L1_EVAL_BATCH_STATUS` → `RivaSlackBot.handle_command` for `summary`, `ready-for-l2`, `last-run-summary`, `review`, etc.
   - `L2_EVAL_SINGLE` / `L2_COMPARE` → `ArjunSlackBot` including comparison-focused chat.
   - `PIPELINE_STATUS` / `DEBUG` → operational stats from `SummaryStore` or debug payload lookup.
- Manual review commands (`review <candidate> - <role>`) call `manual_review_triggers.py` to validate Drive folders and queue the next batch.
- Long-running intents (detected via `looks_like_long_running_intent`) post `WORKING_PLACEHOLDER_TEXT` then update the same message with the final response.

### Slash commands
- `/riva`, `/riva-test`, `/arjun` reuse the same routers. Each verifies signatures, parses fields, and responds with an ephemeral “working” message while the job runs async.
- `/riva-help` responds synchronously with the Markdown command list.
- Unknown slash commands return HTTP 400 and log `*_command_unknown` for diagnostics.

## HTTP endpoints & background surface

| Endpoint | Method | Owner | Notes |
| --- | --- | --- | --- |
| `/health`, `/healthz` | GET | `main.py` | Lightweight probes; `/health` also confirms scheduler state. |
| `/debug-port` | GET | `main.py` | Prints resolved `PORT`, release hash, and scheduler metadata (handy for Cloud Run debugging). |
| `/run-l1-batch`, `/run-l2-batch` | POST | `main.py` ➜ `batch_jobs.py` | Launch Riva L1 / Arjun L2 processors, returning JSON summaries and posting Slack updates if configured. |
| `/slack-riva/events`, `/slack-arjun/events` | POST | Slack routers | Event Subscription entry points with signature verification/retry handling. |
| `/slack/riva`, `/slack/arjun` | POST | Slack routers | Slash commands that respond immediately while work continues in background. |
| `/docs`, `/redoc` | GET | FastAPI | Auto-generated docs; useful locally. |

Logging middleware tags each request with an `actor` (`slack`, `scheduler`, `manual`), injects correlation IDs, and trims payloads for privacy-safe observability.

## Evaluation pipelines – deep dive

### Riva L1 (`riva_l1/riva_l1_batch.py`)
1. **Normalization** – `Normalizer.run()` scans all `L1_FOLDERS`, emitting `normalization_report.json`.
2. **Gating** – `_apply_gating()` enforces transcript + resume/JD presence, immediately marking missing artifacts as `ON_HOLD_MISSING_L1_TRANSCRIPT` or `DATA_INCOMPLETE`.
3. **File resolution** – `RivaFileResolver` assembles resume/JD/transcript/feedback text and metadata/links.
4. **Memory context** – `_prepare_memory_context()` (if `MEMORY_ENABLED`) enriches prompts with prior candidate events and role profiles via `memory_service.py`.
5. **Evaluation** – `RivaL1Service` (OpenAI) outputs fit scores, strengths, weaknesses, risk flags; raw payloads optionally upload to `debug_storage`.
6. **Decision engine** – `decide_l1_outcome()` maps results to `SEND_TO_L2`, `REJECT_AT_L1`, or `HOLD_*`, applying creamy-layer caps and risk heuristics.
7. **Persistence & routing** – `_persist_l1_result()` writes `l1_result.json`; `_write_status_file()` updates `l1_status.json`; `_route_candidate()` moves folders to L2 Pending Review or reject parents via `folder_resolver.py`.
8. **Reporting** – `DecisionStore`, `SummaryStore`, recruiter dashboards (`sheet_service.py`), and `RivaOutputWriter` keep stakeholders informed.

### Arjun L2 (`arjun_l2/arjun_l2_batch.py`)
1. **Discovery/gating** – Iterates `L2_FOLDERS`, requires `normalization_report.json`, and detects transcripts via `find_l2_transcript_file` (missing artifacts ⇒ `ON_HOLD_MISSING_L2_TRANSCRIPT`/`DATA_INCOMPLETE_L2`).
2. **Artifact extraction** – `DriveManager`, `pdf_reader.py`, `docx_reader.py`, and Google Doc export pull resume/JD/transcript text.
3. **Memory context** – `_prepare_memory_context()` loads the last L1 event plus role profile for richer prompts.
4. **Evaluation** – `ArjunL2Service` computes final score, leadership/technical commentary, risk flags, and rationale.
5. **Decision logic** – `decide_l2_outcome()` collapses results into `ADVANCE_TO_FINAL`, `REJECT_AT_L2`, `HOLD_EXEC_REVIEW`, or `HOLD_DATA_INCOMPLETE`, feeding dashboards and the Final Decision Store.
6. **Persistence & routing** – `_persist_l2_result()` writes `l2_result.json`; `_route_candidate()` moves folders to Final Selected / L2 Reject / hold; `_update_recruiter_dashboard_row()` syncs Sheets with confidence bands and next actions.
7. **Memory logging** – Candidate/role events and audit logs append to the memory DB for longitudinal insights.

## Data topology

| System | Module(s) | Purpose |
| --- | --- | --- |
| Google Drive | `drive_service.py`, `folder_map.py`, `folder_resolver.py` | List candidate folders, download artifacts, write `l1_result.json` / `l2_result.json`, and move folders between Pending/Reject/Final parents. |
| Google Sheets | `sheet_service.py`, `map_role_to_sheet_title`, `SheetManager` | Maintain recruiter dashboards and analytics logs. |
| SummaryStore | `summary_store.py` | Cache latest L1/L2 batch summaries for Slack commands. |
| DecisionStore | `decision_store.py` | Persist structured decision logs (scores, summaries, routing). |
| Memory DB | `memory_service.py`, `memory_config.py` | SQLAlchemy-backed store (SQLite default, Postgres via `MEMORY_DB_URL`) for candidate/role context and audit events. |
| Debug storage | `debug_storage.py` | Upload raw L1/L2 payloads for later inspection. |

Update `folder_map.py` whenever recruiters add roles or restructure Drive parents.

## Automation & scheduling

- `batch_jobs.py` exposes `run_riva_l1_batch` / `run_arjun_l2_batch`, which `/run-l1-batch` and `/run-l2-batch` invoke.
- APScheduler registers the same jobs when `ENABLE_JOB_SCHEDULER=true` (disabled in dev via `dev.sh`).
- Cloud Scheduler jobs (13:00 & 21:00 for L1, 16:00 & 23:00 for L2 UTC) call the HTTP endpoints with a service account that holds `roles/run.invoker`.
- Provision schedulers via `cloud_scheduler_commands.sh` or Terraform (`terraform/cloud_scheduler.tf`).

## Testing matrix

| Test module | Focus |
| --- | --- |
| `tests/test_slack_riva_handlers.py`, `tests/test_slack_arjun_handlers.py` | Event routing, ack behavior, fallback messaging. |
| `tests/test_slack_bots.py`, `tests/test_slack_blocks.py` | Command parsing and Slack block rendering. |
| `tests/test_decision_engine.py`, `tests/test_l1_decision.py`, `tests/test_l2_decision.py` | Intent classifier + deterministic decision logic. |
| `tests/test_arjun_l2_batch.py`, `tests/test_riva_l1_batch.py` | Batch orchestration, gating, summary accounting. |
| `tests/test_normalizer.py`, `tests/test_evaluation_converters.py` | Artifact normalization and schema conversion. |
| `tests/test_memory_service.py` | SQLAlchemy memory CRUD/hashing. |
| `tests/test_batch_jobs.py` | Scheduler glue + Slack summary posting. |

Run `./run_tests.sh all` or `pytest tests -v` before PRs; spot-run individual modules while iterating locally.

## Troubleshooting playbook

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Slack says “I’m not sure.” | Intent classified as `UNKNOWN` (formatting/verbs missing). | Follow suggested phrasing or inspect `decision_engine` logs. |
| Manual `review` can’t find candidate. | Role absent from `folder_map.py` or folder renamed. | Update the map / rename folder. |
| `/run-*` returns 403 to Scheduler. | Scheduler SA lacks `roles/run.invoker`. | Add IAM binding via `gcloud run services add-iam-policy-binding ...`. |
| Candidates stuck on hold. | Missing transcript/resume or failed normalization. | Check Drive for `normalization_report.json` + files. |
| L2 skipped candidates. | `find_l2_transcript_file` couldn’t detect transcript. | Ensure transcripts are PDF/DOCX/Google Docs referenced in normalization report. |
| Slash command returns 400. | Command unrecognized or missing `command`/`channel_id`/`user_id`. | Verify Slack payload + configuration. |
| Memory disabled at startup. | `get_memory_service()` failed (DB URL, permissions). | Fix `MEMORY_DB_URL` or fallback to SQLite. |
| Secret access errors. | Runtime SA missing `roles/secretmanager.secretAccessor`. | Grant role and redeploy. |

## Deployment & operations

### Deploy scripts

```bash
./scripts/deploy_cloud_run.sh
```

Keeps the Cloud Run service name stable so Slack URLs never change.

### Container build & deploy

```bash
export PROJECT_ID=hithonix-recruitment-ai
export REGION=asia-south1
./cloudrun_build_and_deploy.sh
```

Builds, pushes, and deploys the Docker image (same workflow as CI).

### Declarative deploy

```bash
gcloud run services replace env.yaml --region=asia-south1
```

`cloudrun.yaml` + `env.yaml` capture the service spec.

### GitHub Actions

- `.github/workflows/deploy-cloudrun.yml` needs secrets `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_SA_EMAIL`, `GCP_WORKLOAD_IDENTITY_PROVIDER`.
- Pushes to `main` automatically build, push, and deploy.

### IAM & networking

- **Public ingress**: grant `allUsers` the `roles/run.invoker` binding if Slack/OpenAI must call unauthenticated.
- **Private ingress**: remove that binding and issue ID tokens via service accounts.
- Runtime SA should keep only essential roles (Secret Manager Accessor, Logging Writer, Trace Writer). Scheduler SA only needs `run.invoker`.

### Monitoring

- `GET /health`, `/healthz` – readiness probes.
- `GET /debug-port` – prints resolved `PORT` and metadata.
- Logs include `actor`, request IDs, Slack metadata; filter via `logName="projects/<project>/logs/run.googleapis.com%2Frequests"`.

### Operations checklist

- Rotate OpenAI/Slack/service-account secrets regularly.
- Confirm Cloud Scheduler jobs hit the current Cloud Run URL after deploys.
- Keep Slack app manifests up to date when URLs change (ngrok, etc.).
- Update `env.yaml`, `README.md`, `PROJECT_DOCUMENT.md` whenever env vars or architecture shift.

## Change management

- Update `README.md`, `PROJECT_DOCUMENT.md`, and `IMPLEMENTATION_SUMMARY.md` when new endpoints, flows, or infrastructure land.
- Keep `folder_map.py`, `drive_structure.txt`, and onboarding docs synced with Drive reorganizations.
- Run impacted pytest modules before merging; attach logs when CI is flaky.
- Ship risky changes (intent engine, decision heuristics, Slack behavior) behind feature flags or via canary deploys.
- Record major architecture shifts in `AUDIT_SUMMARY.md` for future audits.

## Reference documents

- [`IMPLEMENTATION_SUMMARY.md`](./IMPLEMENTATION_SUMMARY.md) – Pipelines, gating, Slack command matrices.
- [`PROJECT_DOCUMENT.md`](./PROJECT_DOCUMENT.md) – Detailed handbook mirroring this README.

For questions, ping `#recruitment-automation` or the on-call engineer listed in the runbook.

## Testing & quality

```bash
./run_tests.sh all          # wrapper
# or
.venv/bin/python -m pytest tests -v
```

Test suites cover Slack bots, decision engines, evaluation converters, memory service, and batch orchestration. Add new tests under `tests/` and keep them runnable via `pytest` with zero external dependencies (Drive/Slack calls are mocked).
