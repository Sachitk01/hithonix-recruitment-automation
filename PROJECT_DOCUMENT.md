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

## 15. Slack assistants & intent routing

### 15.1 Event lifecycle
1. **Slack ➜ FastAPI** – Slack sends Events API payloads to `/slack-riva/events` or `/slack-arjun/events`. Each router (`slack_riva.py`, `slack_arjun.py`) performs JSON parsing, handles `url_verification`, validates signatures via `verify_slack_request`, and drops retries by checking `X-Slack-Retry-Num` headers.
2. **FastAPI ➜ Handler** – Non-bot messages are delegated to `handle_riva_event` / `handle_arjun_event` (see `slack_riva_handlers.py`, `slack_arjun_handlers.py`). We ignore bot echoes and branch on DM (`message.im`) vs `app_mention` events.
3. **Intent routing** – Handler functions call `decide_intent` in `decision_engine.py`, which runs a rule engine followed by optional LLM fallback to classify text into intents such as `L1_EVAL_SINGLE`, `L1_EVAL_BATCH_STATUS`, `L2_EVAL_SINGLE`, `L2_COMPARE`, `PIPELINE_STATUS`, etc.
4. **Ack + async processing** – For actionable intents, the handler posts an immediate acknowledgement via the Slack Web API (`chat_postMessage`) and then calls `to_thread.run_sync` to execute the heavy pipeline commands without blocking the event loop.
5. **Pipeline execution** – `RivaSlackBot`/`ArjunSlackBot` (in `slack_bots.py`) interpret the cleaned command, resolve Drive folders, read `l1_result.json`/`l2_result.json`, route manual review triggers, or fall back to conversational chat handlers (`riva_chat_handler.py`, `arjun_chat_handler.py`). Any exception posts `PIPELINE_ERROR_TEXT` to the originating channel.

### 15.2 Commands, intents, and fallbacks
- **Greeting/help/small talk** intents respond with curated copy (`RIVA_GREETING_MESSAGE`, `ARJUN_HELP_MESSAGE`, etc.).
- **Unsupported/unknown** intents produce `RIVA_UNSURE_MESSAGE` / `ARJUN_UNSURE_MESSAGE`, guiding users toward formats like `summary <Candidate> - <Role>`.
- **Pipeline intents**
    - `L1_EVAL_SINGLE`: Runs `_run_riva_pipeline`, which routes to `RivaSlackBot.handle_command`. Commands such as `summary`, `ready-for-l2`, `last-run-summary`, and `review` are interpreted here.
    - `L1_EVAL_BATCH_STATUS`: Surfaces cached stats via `SummaryStore.get_l1_summary()`.
    - `L2_EVAL_SINGLE` / `L2_COMPARE`: Drive `ArjunSlackBot` flows and the conversational `arjun_chat_handler` for comparisons.
    - `PIPELINE_STATUS` / `DEBUG`: Provide operational summaries or, when available, debugging payloads.
- **Manual review triggers** (`review <candidate> - <role>`) call `handle_riva_manual_review` / `handle_arjun_manual_review` in `manual_review_triggers.py`, verifying the candidate folder exists and confirming that the review will run in the next batch.
- **Long-running intents** detected by `looks_like_long_running_intent()` cause Slack to show the `WORKING_PLACEHOLDER_TEXT` message and later replace it with the final response via `SlackClient.update_message`.

### 15.3 Slash commands
- `/riva`, `/riva-test`, `/arjun` slash commands are handled in the same routers. Each verifies signatures, parses form-encoded payloads, and responds with an ephemeral "working" placeholder while the actual command runs asynchronously.
- `/riva-help` returns the Markdown command list without asynchronous execution.
- Unknown slash commands raise HTTP 400 with detailed logs (`riva_command_unknown`).

## 16. HTTP API & background surface

| Endpoint | Method | Module | Notes |
| --- | --- | --- | --- |
| `/health`, `/healthz` | GET | `main.py` | Lightweight probes for Cloud Run & load balancers. `/health` also checks scheduler state when enabled. |
| `/debug-port` | GET | `main.py` | Returns `PORT`, release metadata, and scheduler info for debugging Cloud Run networking. |
| `/run-l1-batch`, `/run-l2-batch` | POST | `main.py` ➜ `batch_jobs.py` | Launch full Riva L1 / Arjun L2 batch processors, returning serialized `L1BatchSummary` / `L2BatchSummary`. Requires `POST`; unauthenticated externally when Slack/Cloud Scheduler need access. |
| `/slack-riva/events`, `/slack-arjun/events` | POST | `slack_riva.py`, `slack_arjun.py` | Slack Events API endpoints. Handle `url_verification`, drop retries, and queue async tasks. |
| `/slack/riva`, `/slack/arjun` | POST | Same routers | Slash-command handling with immediate ephemeral responses. |
| `/docs`, `/redoc` | GET | FastAPI | Auto-generated API docs (disabled in production ingress if desired). |

**Request logging** – `main.py` middleware labels each request with an `actor` (e.g., `slack`, `scheduler`, `manual`), correlates correlation IDs, and trims request bodies for Slack forensics.

**Scheduler lifecycle** – When `ENABLE_JOB_SCHEDULER=true`, `main.py` registers APScheduler jobs on startup, exposes `/_scheduler/start` and `/_scheduler/shutdown` internally, and logs job execution metrics.

## 17. Evaluation pipelines – deep dive

### 17.1 Riva L1 (`riva_l1/riva_l1_batch.py`)
1. **Normalization** – `Normalizer.run()` scans role folders defined in `L1_FOLDERS`, producing `normalization_report.json` so downstream stages know which artifacts exist.
2. **Gating** – `_apply_gating()` enforces prerequisites: missing transcript ⇒ `l1_status.json` with `ON_HOLD_MISSING_L1_TRANSCRIPT`; missing resume/JD ⇒ `DATA_INCOMPLETE`. Candidates are counted in `L1BatchSummary` hold buckets immediately.
3. **File resolution** – `RivaFileResolver.load()` assembles resume, JD, transcript, and interviewer feedback text, plus metadata and Drive links.
4. **Memory context** – If `MEMORY_ENABLED`, `_prepare_memory_context()` fetches prior candidate events and role profiles from `memory_service.py` to enrich prompts.
5. **Evaluation** – `RivaL1Service.evaluate()` (OpenAI) returns fit scores, strengths, weaknesses, risks, and structured recommendation data. Raw responses plus decision traces optionally upload to `debug_storage` for audit.
6. **Decision engine** – `decide_l1_outcome()` (in `riva_l1/decision_engine.py`) converts the raw outcome into `SEND_TO_L2`, `REJECT_AT_L1`, or `HOLD_*` signals. Additional heuristics limit "creamy layer" ratios, detect low communication quality, or missing JD alignment.
7. **Persistence** – `_persist_l1_result()` writes `l1_result.json`; `_write_status_file()` maintains `l1_status.json`. `DecisionStore` and `SummaryStore` log metrics; `RivaOutputWriter` creates recruiter-facing reports/questionnaires.
8. **Routing** – `_route_candidate()` moves Drive folders to the mapped L2 Pending Review or reject folders (from `folder_resolver.py`). Holds stay put but include explicit status codes.
9. **Sheets update** – `_update_recruiter_dashboard_row()` writes/upserts rows via `sheet_service.py`, mapping pipeline recommendations to recruiter actions.

### 17.2 Arjun L2 (`arjun_l2/arjun_l2_batch.py`)
1. **Discovery & gating** – The processor iterates `L2_FOLDERS`, ensures `normalization_report.json` exists, and requires a dedicated L2 transcript (detected via `find_l2_transcript_file`). Missing artifacts cause `ON_HOLD_MISSING_L2_TRANSCRIPT` or `DATA_INCOMPLETE_L2` statuses.
2. **Artifact extraction** – Resume/JD/Transcript text is extracted via `DriveManager`, `pdf_reader.py`, and `docx_reader.py`, with Google Doc export support.
3. **Memory context** – `_prepare_memory_context()` fetches the last L1 event plus role profile for better context injection. Candidate events from `memory_service` provide historical decisions.
4. **Evaluation** – `ArjunL2Service.evaluate()` generates final scores, leadership/technical commentary, risk flags, and textual rationale. Results feed `convert_arjun_result()` for consistent schema.
5. **Decision logic** – `decide_l2_outcome()` narrows the outcome to `ADVANCE_TO_FINAL`, `REJECT_AT_L2`, `HOLD_EXEC_REVIEW`, or `HOLD_DATA_INCOMPLETE`. We map these to human-friendly statuses/next actions and store them in both `L2BatchSummary` and the Final Decision Store (`final_decision_store.py`).
6. **Persistence & routing** – `_persist_l2_result()` writes `l2_result.json`; `_route_candidate()` moves folders to Final Selected, L2 Reject, or leaves them on hold. Recruiter dashboard rows are updated with confidence bands, strengths, concerns, and L1 vs L2 alignment notes.
7. **Memory logging** – Structured evaluation snapshots plus audit events are logged via `MemoryService`, keeping a timeline for both candidate and role memories.

### 17.3 Riva L1 decision policy & explainability

The thresholds and recommended recruiter actions for Riva L1 now live in `riva_l1/decision_policy.py`. The module is imported by the decision engine so code and documentation stay aligned.

| Decision | Fit score band (normalized) | Typical `risk_flags` | Recommended action |
| --- | --- | --- | --- |
| Move to L2 | ≥ `MOVE_TO_L2_MIN_SCORE` (0.70) | `clean_profile`, `strong_alignment` | Share highlights with the hiring manager and route to Arjun L2 immediately. |
| Hold – manual review | Between `REJECT_MAX_SCORE` (0.40) and `MOVE_TO_L2_MIN_SCORE` (0.70) | `low_confidence_signal`, `borderline_experience`, `alignment_questions` | Human reviewer should skim transcript/resume, clarify open questions, then rerun L1. |
| Hold – data incomplete | Any score; gated by `risk_flags` such as `missing_non_critical_doc`, `missing_transcript`, `data_incomplete` | Upload the missing resume/JD/transcript, wait for Normalizer to rebuild artifacts, then rerun. |
| Reject at L1 | ≤ `REJECT_MAX_SCORE` (0.40) or hard-block flags | `hard_block`, `salary_mismatch`, `experience_gap` | Notify the recruiter with the surfaced risk flags so they can close the loop with the candidate. |

The Slack summaries and Candidate QA responses pull these risk flags directly from the batch output so recruiters can see *why* a candidate moved, held, or was rejected without digging into Drive.

### 17.4 Arjun L2 decision policy & explainability

Arjun now follows the same declarative approach via `arjun_l2/decision_policy.py`. The strict decision engine imports these thresholds so Slack, QA, and documentation stay aligned:

| Decision | Fit score band (normalized) | Communication floor | Typical `risk_flags` | Recommended action |
| --- | --- | --- | --- | --- |
| Advance to Final | ≥ `ADVANCE_MIN_SCORE` (0.80) with leadership ≥ `ADVANCE_MIN_LEADERSHIP` | ≥ `ADVANCE_MIN_COMMUNICATION` (0.70) | `clean_exec_alignment`, `ready_for_offer` | Move the candidate to Final Selected, notify exec sponsors, and kick off offer prep. |
| Hold – exec review | Between `EXEC_HOLD_MIN_SCORE` (0.65) and `EXEC_HOLD_MAX_SCORE` (0.80) | ≥ `EXEC_HOLD_MIN_COMMUNICATION` (0.60) | `needs_exec_review`, `scope_alignment_question` | Have an exec reviewer skim the transcript to approve/decline before moving forward. |
| Hold – data incomplete | Any score gated by `DATA_INCOMPLETE_RISK_CODES` (`missing_l2_transcript`, `data_incomplete`, etc.) | N/A | `missing_l2_transcript`, `missing_noncritical_info` | Collect the missing transcript/context, rerun Normalizer, then re-evaluate. |
| Reject at L2 | ≤ `REJECT_MAX_SCORE` (0.50) or communication ≤ `REJECT_MAX_COMMUNICATION` (0.50) or hard-block flags | N/A | `hard_block`, `integrity_violation`, `weak_exec_presence` | Share the surfaced flags with the recruiter for transparent closure. |

`ArjunSlackBot` uses the shared formatter in `candidate_qa_service.py` so every Slack/QA response now includes the decision label, L1 vs L2 alignment, and a “Reasons: …” line populated from the stored `risk_flags`.

## 18. Data topology & external systems

| System | File/Module | Purpose |
| --- | --- | --- |
| **Google Drive** | `drive_service.py`, `folder_map.py`, `folder_resolver.py` | Lists candidate folders, downloads artifacts, writes `l1_result.json`/`l2_result.json`/status files, and moves folders between Pending, Reject, and Final Selected parents. |
| **Google Sheets** | `sheet_service.py`, `map_role_to_sheet_title`, `upsert_role_sheet_row` | Maintains recruiter dashboard rows with AI status, next actions, and links. `SheetManager` logs extra analytics rows for L2. |
| **Summary Store** | `summary_store.py` | In-memory singleton that caches the latest `L1BatchSummary`/`L2BatchSummary` for Slack commands (`last-run-summary`). |
| **Decision Store** | `decision_store.py` | Persists structured decision logs (role, JD, scores, recommendations) for auditing and analytics. |
| **Memory DB** | `memory_service.py`, `memory_config.py` | Optional SQLAlchemy-backed store (SQLite by default) for candidate/role context, evaluation events, and audit trails. Controlled via `MEMORY_ENABLED`, `MEMORY_DB_URL`, `should_use_candidate_memory`, and `should_use_role_memory`. |
| **Debug storage** | `debug_storage.py` | Uploads raw L1/L2 model payloads to external storage for later inspection. |

Drive parents referenced throughout the pipelines are declared in `folder_map.py` (e.g., `L1_FOLDERS`, `L2_FOLDERS`, `PROFILES_*`). Update this map whenever recruiters add new roles.

## 19. Automation & scheduling details

- **APScheduler (in-process)** – Enabled when `ENABLE_JOB_SCHEDULER` resolves truthy. Jobs `riva_l1_daily_job` and `arjun_l2_daily_job` live in `batch_jobs.py`; they run the processors, update `SummaryStore`, and post Slack summaries via `SlackClient`.
- **Cloud Scheduler (managed)** – `cloud_scheduler_commands.sh` and `terraform/cloud_scheduler.tf` create HTTP jobs that `POST /run-l1-batch` at 13:00 & 21:00 local time and `POST /run-l2-batch` at 16:00 & 23:00. Jobs impersonate a service account with `roles/run.invoker`.
- **Manual execution** – Engineers can hit the endpoints via `curl` (see README) or run `python batch_jobs.py --job riva` locally. Manual triggers still write Drive artifacts and Slack updates if tokens are configured.
- **Deployment scripts** – `cloudrun_build_and_deploy.sh` builds/pushes/deploys a consistent service. The optional `scripts/deploy_cloud_run.sh` wrapper enforces service naming to keep Slack URLs stable.

## 20. Testing matrix & quality gates

| Test file | Focus |
| --- | --- |
| `tests/test_slack_riva_handlers.py`, `tests/test_slack_arjun_handlers.py` | Event routing, ack behavior, and fallback messaging for both bots. |
| `tests/test_slack_blocks.py`, `tests/test_slack_bots.py` | Rendering blocks and command handlers for Slack assistants. |
| `tests/test_decision_engine.py`, `tests/test_l1_decision.py`, `tests/test_l2_decision.py` | Intent classification and deterministic decision engines for both pipelines. |
| `tests/test_arjun_l2_batch.py`, `tests/test_riva_l1_batch.py` (root) | Batch orchestration, gating, and summary accounting logic. |
| `tests/test_memory_service.py` | CRUD operations on the SQLAlchemy memory backend. |
| `tests/test_normalizer.py`, `tests/test_evaluation_converters.py` | Artifact normalization and converter correctness. |
| `tests/test_batch_jobs.py`, `tests/test_slack_blocks.py` | Scheduler wiring and Slack presentation logic. |

CI recommendation: run `./run_tests.sh all` or `pytest tests -v` before every PR. For local spot checks, re-run targeted test modules (e.g., `pytest tests/test_slack_riva_handlers.py`).

## 21. Failure modes & troubleshooting playbook

| Symptom | Likely cause | Remediation |
| --- | --- | --- |
| Slack responses stick on "I’m not sure" | `decide_intent` classified DM as `UNKNOWN` or non-pipeline intent (often due to missing verbs or poor formatting). Encourage users to follow the examples in Section 15.2; inspect `decision_engine` logs for misclassifications. |
| Manual `review` command says candidate not found | `folder_map.py` missing role entry or candidate folder renamed. Update the map or normalize Drive naming; re-run `review` afterwards. |
| Batch endpoints return `403` to Scheduler | Scheduler service account lacks `roles/run.invoker` on Cloud Run service. Re-run `gcloud run services add-iam-policy-binding ... --member="serviceAccount:<scheduler-sa>" --role="roles/run.invoker"`. |
| L1 candidates stuck on hold | Missing transcripts/resumes or normalization report parse failures. Check Drive folders for `normalization_report.json`, confirm Normalizer logs, and ensure transcripts are uploaded with consistent naming. |
| L2 pipeline skipping candidates | `find_l2_transcript_file` could not detect a transcript; verify the file extension (PDF/DOCX) and that Normalizer placed metadata under `l2_transcript`. |
| Slack slash command returns 400 | Unknown command or missing required form fields. Validate Slack app configuration and ensure `command`, `channel_id`, and `user_id` are present in payloads. |
| Memory service disabled unexpectedly | `get_memory_service()` threw during startup; logs show `memory_service_unavailable`. Check `MEMORY_DB_URL`, network access (for Postgres), or the SQLite file path permissions. |
| Secret access failures | Runtime service account lacks `roles/secretmanager.secretAccessor`. Update IAM bindings and redeploy. |

## 22. Change management & PR checklist

1. Update both `README.md` and `PROJECT_DOCUMENT.md` whenever you add new endpoints, roles, or operational procedures.
2. Keep `folder_map.py`, `drive_structure.txt`, and any onboarding docs in sync when recruiters restructure Drive.
3. Before merging, run the targeted pytest modules touched by your change; attach results to the PR if CI is flaky.
4. For production-impactful changes (intent engine, decision logic, Slack command behavior), stage them behind feature flags or perform canary deploys by cloning the Cloud Run service.
5. Capture architectural revisions in `IMPLEMENTATION_SUMMARY.md` and note them in `AUDIT_SUMMARY.md` for future audits.
