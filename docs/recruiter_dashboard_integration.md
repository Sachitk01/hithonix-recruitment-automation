# Recruiter Dashboard Integration (Riva + Arjun → Google Sheets)

## Overview
The **Hithonix Recruitment Dashboard** (Spreadsheet ID: `1ZqNfOsyyNs5wBSTU8Xm-IxZAF1X27SpJsDwyaAwvpj4`) is the single source of truth for recruiters to track candidate progress across automation stages. Each role owns its own sheet tab (`IT Support`, `IT Admin`, `HR Support`) and every candidate appears exactly once per role, keyed by their Drive `candidate_folder_id`.

Each row contains the following ordered columns:

1. Candidate Name
2. Current Stage
3. AI Status
4. AI Recommendation Detail
5. Overall Confidence
6. Key Strengths (Bullets)
7. Key Concerns (Bullets)
8. L1 Outcome
9. L2 Outcome
10. Next Action
11. Owner
12. Feedback Report Link
13. Folder Link
14. Last Updated
15. Candidate Folder ID

## Automation Flow
### Riva L1 → Sheets
After Riva finalizes an L1 evaluation (reports + routing decision), `riva_l1_batch.py` now calls `sheet_service.upsert_role_sheet_row` to:
- Map the AI recommendation (`pass/reject/hold`) to recruiter-facing status, outcome, and next action.
- Translate confidence into `High/Medium/Low` and capture key strengths/concerns and the narrative summary.
- Record folder/feedback links plus the technical folder ID so rows can be updated idempotently.

### Arjun L2 → Sheets
Once Arjun completes L2 analysis and routing, `arjun_l2_batch.py` performs the same upsert:
- Recommendation buckets (`strong_yes/yes/lean_yes/lean_no/no`) become recruiter statuses, L2 outcomes, and default next steps.
- Confidence, strengths, concerns, and summaries are logged.
- If L1 history is present in memory, the stored L1 outcome is populated to help recruiters spot divergences.

Both stages write timestamps using UTC and only run when `RECRUITER_SHEET_FILE_ID` is configured, ensuring local runs don’t fail silently.

## Environment Variables
| Variable | Purpose |
| --- | --- |
| `RECRUITER_SHEET_FILE_ID` | Target Google Sheet for dashboard writes (defaults to the production ID above when not set). |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to the service account JSON with Drive/Sheets access (defaults to `infrastructure/service_account.json`). |

Ensure the service account email has edit permission on the dashboard spreadsheet.

## Helper Scripts
- `test_seed_recruiter_sheet.py`: Quickly seeds three fake candidates (IT Support/Admin/HR) to verify formatting or demo updates. Safe to run locally once credentials are configured.
- `check_recruiter_sheet_health.py`: Read-only monitor that validates each role tab exists, headers match the contract, and reports the current row count. Ideal for cron/CI to catch accidental schema drifts.

## Operational Tips
- Run the seeding script in a non-production sheet or after duplicating the dashboard; it overwrites rows sharing the same folder IDs.
- The health script exits with a non-zero status when headers are missing/mismatched, making it simple to wire into Cloud Scheduler, crontab, or CI alerts.
- If you introduce new role tabs, update `ROLE_SHEET_TITLE_MAP` inside `sheet_service.py` and the helper lists in both scripts to keep parity.
