# main.py

from dotenv import load_dotenv
load_dotenv()

import logging
import os
from datetime import datetime
from typing import Dict, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
import time
import uuid

from batch_jobs import run_arjun_l2_batch, run_riva_l1_batch
from slack_service import SlackClient, SlackNotifier
from slack_riva import router as riva_router
from slack_arjun import router as arjun_router


slack_logger = logging.getLogger("slack")


# Request Logging Middleware
request_logger = logging.getLogger("request_logging")

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        start_time = time.time()
        
        # Extract actor from path
        actor = "API"
        if "/slack/riva" in request.url.path:
            actor = "Riva"
        elif "/slack/arjun" in request.url.path:
            actor = "Arjun"
        elif "/run-l1-batch" in request.url.path:
            actor = "Riva"
        elif "/run-l2-batch" in request.url.path:
            actor = "Arjun"
        
        # Process request
        response = await call_next(request)
        
        # Calculate latency
        latency_ms = (time.time() - start_time) * 1000
        
        # Log request details
        request_logger.info(
            "request_completed",
            extra={
                "request_id": request_id,
                "endpoint": request.url.path,
                "method": request.method,
                "actor": actor,
                "status_code": response.status_code,
                "latency_ms": round(latency_ms, 2),
            }
        )
        
        return response


app = FastAPI()
app.add_middleware(RequestLoggingMiddleware)
app.include_router(riva_router, tags=["riva"])
app.include_router(arjun_router, tags=["arjun"])


def _load_slack_config(prefix: str) -> Dict[str, Optional[str]]:
    return {
        "bot_token": os.getenv(f"{prefix}_BOT_TOKEN"),
        "signing_secret": os.getenv(f"{prefix}_SIGNING_SECRET"),
        "default_channel": os.getenv(f"{prefix}_DEFAULT_CHANNEL_ID"),
    }


SLACK_RIVA_CONFIG = _load_slack_config("SLACK_RIVA")
SLACK_ARJUN_CONFIG = _load_slack_config("SLACK_ARJUN")
SLACK_RIVA_BOT_USER_ID = os.getenv("SLACK_RIVA_BOT_USER_ID")
SLACK_ARJUN_BOT_USER_ID = os.getenv("SLACK_ARJUN_BOT_USER_ID")

for bot_name, config in (("riva", SLACK_RIVA_CONFIG), ("arjun", SLACK_ARJUN_CONFIG)):
    if not config["bot_token"]:
        slack_logger.error("slack_bot_token_missing_startup", extra={"bot": bot_name})
    if not config["signing_secret"]:
        slack_logger.warning("slack_signing_secret_missing", extra={"bot": bot_name})
    if not config["default_channel"]:
        slack_logger.warning("slack_default_channel_missing", extra={"bot": bot_name})

riva_slack_client = SlackClient(
    name="riva",
    bot_token=SLACK_RIVA_CONFIG["bot_token"],
    default_channel=SLACK_RIVA_CONFIG["default_channel"],
    signing_secret=SLACK_RIVA_CONFIG["signing_secret"],
)
arjun_slack_client = SlackClient(
    name="arjun",
    bot_token=SLACK_ARJUN_CONFIG["bot_token"],
    default_channel=SLACK_ARJUN_CONFIG["default_channel"],
    signing_secret=SLACK_ARJUN_CONFIG["signing_secret"],
)

slack_notifier = SlackNotifier(riva_client=riva_slack_client, arjun_client=arjun_slack_client)
# ------------------------------------------------------------------
# Scheduler setup
# ------------------------------------------------------------------
scheduler_logger = logging.getLogger("batch_scheduler")
scheduler_timezone = datetime.now().astimezone().tzinfo
scheduler = AsyncIOScheduler(timezone=scheduler_timezone)
ENABLE_JOB_SCHEDULER = os.getenv("ENABLE_JOB_SCHEDULER", "false").lower() == "true"


def execute_riva_l1_batch():
    return run_riva_l1_batch(slack_notifier)


def execute_arjun_l2_batch():
    return run_arjun_l2_batch(slack_notifier)


def riva_l1_daily_job():
    job_corr = "riva_l1_daily_job"
    try:
        summary = execute_riva_l1_batch()
        scheduler_logger.info(
            "riva_l1_daily_job_complete",
            extra={"correlation_id": job_corr, **summary.to_logging_dict()},
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        scheduler_logger.exception(
            "riva_l1_daily_job_failed",
            extra={"correlation_id": job_corr, "error": str(exc)},
        )


def arjun_l2_daily_job():
    job_corr = "arjun_l2_daily_job"
    try:
        summary = execute_arjun_l2_batch()
        scheduler_logger.info(
            "arjun_l2_daily_job_complete",
            extra={"correlation_id": job_corr, **summary.to_logging_dict()},
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        scheduler_logger.exception(
            "arjun_l2_daily_job_failed",
            extra={"correlation_id": job_corr, "error": str(exc)},
        )


def _register_scheduler_jobs() -> None:
    if not ENABLE_JOB_SCHEDULER:
        scheduler_logger.info("[Scheduler] ENABLE_JOB_SCHEDULER is false; skipping job registration.")
        return

    try:
        scheduler.add_job(
            riva_l1_daily_job,
            CronTrigger(hour="13,21", minute=0, timezone=scheduler_timezone),
            id="riva_l1_daily_job",
            name="riva_l1_daily_job",
            replace_existing=True,
        )
        scheduler.add_job(
            arjun_l2_daily_job,
            CronTrigger(hour="16,23", minute=0, timezone=scheduler_timezone),
            id="arjun_l2_daily_job",
            name="arjun_l2_daily_job",
            replace_existing=True,
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        scheduler_logger.error(
            "[Scheduler] Failed to register jobs; disabling scheduler for this run.",
            exc_info=True,
            extra={"error": str(exc)},
        )
        return


@app.on_event("startup")
async def start_scheduler() -> None:  # pragma: no cover - FastAPI lifecycle
    if not ENABLE_JOB_SCHEDULER:
        scheduler_logger.info("[Scheduler] ENABLE_JOB_SCHEDULER is false; skipping startup.")
        return

    _register_scheduler_jobs()
    if not scheduler.running:
        scheduler.start()
        scheduler_logger.info("job_scheduler_started", extra={"correlation_id": "scheduler"})


@app.on_event("shutdown")
async def stop_scheduler() -> None:  # pragma: no cover - FastAPI lifecycle
    if scheduler.running:
        scheduler.shutdown()


# ------------------------------------------------------------------
# Health check
# ------------------------------------------------------------------
def _healthy_response():
    return {"status": "ok"}


@app.get("/health")
def health():
    return _healthy_response()


@app.get("/healthz")
def healthz():
    return _healthy_response()


# ------------------------------------------------------------------
# Port debugging endpoint
# ------------------------------------------------------------------
@app.get("/debug-port")
def debug_port():
    env_port = os.getenv("PORT")
    fallback_port = "8080"
    resolved_port = env_port or fallback_port
    return {
        "env_port": env_port,
        "fallback_port": fallback_port,
        "resolved_port": resolved_port,
        "uvicorn_command": "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}",
        "host": "0.0.0.0",
    }


# ------------------------------------------------------------------
# Slack test endpoint
# ------------------------------------------------------------------
@app.get("/slack-test")
def slack_test():
    slack_notifier.send_test_message()
    return {"status": "Slack test message sent"}


# ------------------------------------------------------------------
# Riva L1 Batch
# ------------------------------------------------------------------
@app.post("/run-l1-batch")
def run_l1_batch():
    return execute_riva_l1_batch()


# ------------------------------------------------------------------
# Arjun L2 Batch
# ------------------------------------------------------------------
@app.post("/run-l2-batch")
def run_l2_batch():
    return execute_arjun_l2_batch()
