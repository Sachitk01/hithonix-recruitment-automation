# Implementation Summary

## End-to-end flow
1. **L1 Pending Review → Normalizer** – Candidate folders inside each role’s L1 Pending Review parent are normalized into `normalization_report.json`, giving a consistent CandidateArtifacts manifest (resume, JD, transcripts, feedback, video, extras, booleans).
2. **Riva L1 Evaluation** – Riva consumes the normalized bundle, enforces L1 gating, and produces `l1_result.json` + `l1_status.json`. Candidates are routed either to **L2 Pending Review** (send-to-L2), **Profiles · L1 Rejected**, or kept on hold when evidence is missing.
3. **L2 Pending Review → Arjun L2** – Candidates moved to the L2 folders are re-read, gated again, and evaluated by Arjun. Outputs `l2_result.json` + `l2_status.json`, logs sheet rows, and routes folders onward.
4. **Final Routing** – Arjun moves hires to **Profiles · Final Selected**, rejects to **Profiles · L2 Rejected**, and leaves holds in place for recruiter review.

## Riva L1 responsibilities
- **Inputs**: `normalization_report.json`, raw resume/JD/transcript/feedback artifacts, prior Drive folder context.
- **Gating rules**:
  - Missing L1 transcript ⇒ status `ON_HOLD_MISSING_L1_TRANSCRIPT`.
  - Missing resume or JD ⇒ `DATA_INCOMPLETE_L1`.
  - Normalized report absent ⇒ marked data incomplete.
- **Evaluation**: Calls `RivaL1Service` (OpenAI-backed) to score fit, strengths, concerns, red flags, and final decision.
- **Outputs**:
  - `l1_result.json` (score, strengths, risks, recommendation) and `l1_status.json` (status + detail).
  - Writes detailed markdown/JSON artifacts through `RivaOutputWriter` and logs history via `DecisionStore`.
- **Routing**:
  - `SEND_TO_L2` ⇒ move folder to the mapped L2 Pending Review role.
  - `REJECT_AT_L1` ⇒ move to role-specific reject folder.
  - `HOLD` ⇒ stay in place with updated status detail.

## Arjun L2 responsibilities
- **Inputs**: Candidate folder inside an L2 role, `normalization_report.json`, optional `l1_result.json`, extracted resume/JD/L2 transcript text.
- **Gating rules**:
  - Missing L2 transcript ⇒ `ON_HOLD_MISSING_L2_TRANSCRIPT`.
  - Missing resume or JD ⇒ `DATA_INCOMPLETE_L2`.
  - Missing normalization report ⇒ data incomplete.
- **Evaluation**: `ArjunL2Service` scores candidates, generates L2 summaries, compares with L1 (IMPROVED / CONSISTENT / REGRESSED), and emits final recommendation (`HIRE`, `REJECT`, `HOLD`).
- **Outputs**:
  - `l2_result.json` (final score, summary, comparison, risk flags) + `l2_status.json`.
  - Appends outcomes to Google Sheet for analytics.
- **Routing**:
  - `HIRE` ⇒ move to role’s Final Selected folder.
  - `REJECT` ⇒ move to L2 Reject folder.
  - `HOLD` ⇒ remain in L2 Pending Review with updated status.

## Slack commands
| Bot | Command | Description |
| --- | --- | --- |
| **@Riva** | `summary <Candidate> - <Role>` | Show L1 status, score, strengths, risks, and next step. |
| | `ready-for-l2 <Role>` | List up to 10 candidates in the L2 folder whose `l1_result.json` says SEND_TO_L2. |
| | `last-run-summary` | Display cached metrics from the most recent Riva batch. |
| **@Arjun** | `summary <Candidate> - <Role>` | Show L2 recommendation, summary, L1 vs L2 comparison, risks, next action. |
| | `hires <Role>` | Summarize top 10 current hires (Final Selected + pending L2) with scores/comparisons. |
| | `last-run-summary` | Cached metrics from the latest Arjun batch. |

## Scheduled jobs
| Job | Cron (local timezone) | Description |
| --- | --- | --- |
| `riva_l1_daily_job` | 13:00 and 21:00 daily | Runs the full Riva L1 batch and posts Slack metrics. |
| `arjun_l2_daily_job` | 16:00 and 23:00 daily | Runs the Arjun L2 batch and posts Slack metrics. |

Schedulers are registered only when `ENABLE_JOB_SCHEDULER` evaluates to true (`1/true/yes/on`).

## Deployment environment variables
- `RIVA_SA_JSON` **or** `RIVA_SA_JSON_CONTENT`: Google Drive service-account credentials.
- `OPENAI_API_KEY`: Used by both Riva L1 and Arjun L2 services.
- `SLACK_BOT_TOKEN`: Token for posting notifications and replying to slash commands.
- `SLACK_DEFAULT_CHANNEL_ID`, `SLACK_L1_CHANNEL_ID`, `SLACK_L2_CHANNEL_ID`: Notification routing.
- `ENABLE_JOB_SCHEDULER`: Enable/disable APScheduler inside FastAPI (set to `false` locally to avoid duplicate cron runs).
- Suggested extras: `PORT`/`HOST` for your ASGI host, secrets for any Sheet integrations, and any proxy settings required by your infrastructure.

## How to…

### Run the full test suite
```bash
./run_tests.sh all
# or
.venv/bin/python -m pytest tests -v
```

### Run the API locally
```bash
export ENABLE_JOB_SCHEDULER=false  # optional: disable cron while developing
.venv/bin/python -m uvicorn main:app --reload --port 8000
```
- Omit the `ENABLE_JOB_SCHEDULER` override (or set it to `true`) to let the cron jobs run automatically on startup.
- FastAPI serves Slack endpoints (`/slack/riva`, `/slack/arjun`), batch triggers, and health checks once uvicorn is running.

### Trigger batches manually via HTTP
With the API running on `http://127.0.0.1:8000`:
```bash
curl -X POST http://127.0.0.1:8000/run-l1-batch
curl -X POST http://127.0.0.1:8000/run-l2-batch
```
Each endpoint returns the corresponding batch summary JSON and also pushes Slack notifications if tokens are configured.
