# Hithonix Recruitment Automation

FastAPI service orchestrating the Riva L1 and Arjun L2 pipelines for candidate screening, Drive normalization, Slack notifications, and scheduled batch runs.

## Architecture overview
1. **Normalizer ➜ Riva L1 ➜ Arjun L2**: Candidate folders in Drive are normalized, evaluated at L1 (Riva), then promoted to L2 (Arjun) for final decisions.
2. **Slack bots**: `@Riva` and `@Arjun` respond to slash commands for summaries, ready-for-L2 lists, hires, and historical stats.
3. **Schedulers**: Cron jobs trigger L1 twice daily (13:00 & 21:00) and L2 twice daily (16:00 & 23:00) via Cloud Scheduler hitting `/run-l1-batch` and `/run-l2-batch`.
4. **Cloud Run**: Production deployment is containerized and deployed via Cloud Run with healthchecks, secret hydration, and GitHub Actions automation.

## Environment configuration & secrets
1. Copy `.env.example` to `.env` for local development.
2. Any variable can be set to `gcp-secret://<secret-name>`; at runtime `main.py` exchanges it via Google Secret Manager when `GOOGLE_CLOUD_PROJECT` or `GCP_SECRET_PROJECT` is defined.
3. Recommended secret list:
   - `OPENAI_API_KEY`
   - `RIVA_SA_JSON_CONTENT` *(Drive service account)*
   - `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `SLACK_*_CHANNEL_ID`
   - `NGROK_AUTHTOKEN`
4. To store secrets:
   ```bash
   gcloud secrets create openai-api-key --replication-policy=automatic
   echo "sk-..." | gcloud secrets versions add openai-api-key --data-file=-
   ```
   Then set `OPENAI_API_KEY=gcp-secret://openai-api-key` in `.env` or Cloud Run variables.

## Talent Intelligence Memory Layer
- **Persistence**: `memory_service.py` uses SQLAlchemy (SQLite by default) to persist `CandidateProfile`, `CandidateEvent`, `RoleProfile`, and override logs. Tables auto-create on startup; switch to Postgres by setting `MEMORY_DB_URL`.
- **Config flags** (`.env`):
   - `MEMORY_ENABLED=true|false`
   - `MEMORY_SCOPE=candidate_only|role_only|full`
   - `MEMORY_DB_URL=sqlite:///./talent_memory.db`
- **Structured outputs**: `evaluation_models.py` + `evaluation_converters.py` validate every Riva L1 and Arjun L2 response before Sheets/Drive writes and memory persistence.
- **Runtime wiring**:
   - L1 pulls prior `CandidateProfile` + `RoleProfile` context into the LLM prompt, logs whether context was available, and appends `CandidateEvent` entries with hashed inputs/artifacts.
   - L2 loads the last L1 event + role rubric, computes `alignment_with_l1`, updates final candidate outcome, and persists its own events.
- **Safety**: When the DB is unreachable or memory is disabled, pipelines continue statelessly while logging the fallback.

## Running locally
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./dev.sh
```
- `dev.sh` automatically disables the scheduler, starts uvicorn, launches ngrok, and prints the public HTTPS URL for Slack slash commands.
- Ensure `NGROK_AUTHTOKEN` is set (or reserve a domain via `NGROK_DOMAIN`) for stable callbacks.

## Testing
```bash
./run_tests.sh all
```
> Uses pytest to execute Normalizer, Scheduler, Slack bot, and batch coverage.

## Deploying to Cloud Run
1. **Manual CLI**
   ```bash
   export PROJECT_ID=your-gcp-project
   export REGION=us-central1
   ./cloudrun_build_and_deploy.sh
   ```
2. **GitHub Actions** (`.github/workflows/deploy-cloudrun.yml`)
   - Configure repository secrets: `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_SA_EMAIL`, `GCP_WORKLOAD_IDENTITY_PROVIDER`.
   - On pushes to `main`, the workflow builds, pushes, and deploys the container to Cloud Run.
3. **Service manifest**: `cloudrun.yaml` documents resource settings, env vars, and Secret Manager bindings for declarative deployments.

## Slack integration
1. In Slack API dashboard create a Slack App with slash commands pointing to the ngrok / Cloud Run URL (`/slack/riva`, `/slack/arjun`).
2. Configure the bot token, signing secret, and channel IDs in Secret Manager or `.env`.
3. For testing, run `./dev.sh` and update command manifests with the fresh ngrok URL printed by the script.
4. Production Slack requests should target the Cloud Run URL (e.g., `https://hithonix...a.run.app/slack/riva`).

## Cloud Scheduler (cron) setup
- **One-off CLI**: `cloud_scheduler_commands.sh` issues four gcloud commands to create POST jobs hitting `/run-l1-batch` and `/run-l2-batch` at 13:00/21:00 and 16:00/23:00 UTC respectively.
- **Infrastructure as Code**: `terraform/cloud_scheduler.tf` provisions the same jobs. Provide `project_id`, `region`, `service_url`, and `invoker_service_account` variables.
- Grant the scheduler service account the *Cloud Run Invoker* role.

## Local Slack testing workflow
1. Run `./dev.sh` to launch uvicorn + ngrok.
2. Copy the printed `https://....ngrok.app` URL.
3. Update Slack slash command manifest and interactive components to point at `https://.../slack/riva` and `/slack/arjun`.
4. Exercise commands directly from Slack; logs stream in the terminal.

## Updating Slack manifests
- Keep a copy of your Slack App manifest (JSON/YAML) and update the Request URLs to either the ngrok URL (development) or Cloud Run URL (production).
- Recommended endpoints:
  - Slash Command `@Riva`: `POST /slack/riva`
  - Slash Command `@Arjun`: `POST /slack/arjun`
  - Optional interactivity: `POST /slack/riva`

## Manual batch triggers & healthchecks
- `POST /run-l1-batch` – trigger Riva L1 batch immediately (requires Drive + OpenAI credentials).
- `POST /run-l2-batch` – trigger Arjun L2 batch immediately.
- `GET /health` or `GET /healthz` – used by Cloud Run and load balancers for health verification.

## Additional references
- `IMPLEMENTATION_SUMMARY.md` – deep-dive on workflow, artifacts, Slack commands, cron timing, and env vars.
- `cloudrun.yaml`, `.github/workflows/deploy-cloudrun.yml`, `cloud_scheduler_commands.sh`, and `terraform/cloud_scheduler.tf` – infrastructure tooling.
