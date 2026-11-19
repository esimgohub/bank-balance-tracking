import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.config import settings
from app.scheduler import create_scheduler
from app.services.balance_job import run_balance_job_exclusive, try_reserve_job_slot

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scheduler
    if settings.scheduler_enabled:
        scheduler = create_scheduler(settings)
        scheduler.start()
        logger.info("Scheduler started")
    else:
        logger.info("Scheduler disabled via configuration")

    try:
        yield
    finally:
        if scheduler and scheduler.running:
            scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")


app = FastAPI(title=settings.app_name, lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "scheduler_enabled": settings.scheduler_enabled,
        "bidv_enabled": settings.bidv_enabled,
        "timezone": settings.timezone,
        "cron_expression": settings.cron_expression,
    }


@app.post("/bank_tracking")
async def bank_tracking() -> JSONResponse:
    # Atomically reserve a run slot before accepting/scheduling to prevent overlapping or queued duplicate runs.
    if not try_reserve_job_slot():
        return JSONResponse(
            status_code=409,
            content={
                "status": "busy",
                "message": "A balance job is already running; try again later",
                "trigger": "webhook",
                "bidv_enabled": settings.bidv_enabled,
            },
        )

    if settings.webhook_immediate_response:
        # Accepted jobs run in-process/in-memory: a process restart can drop in-flight work.
        asyncio.create_task(run_balance_job_exclusive(settings, trigger="webhook"))
        return JSONResponse(
            status_code=202,
            content={
                "status": "accepted",
                "message": "Bank balance tracking run triggered",
                "trigger": "webhook",
                "bidv_enabled": settings.bidv_enabled,
                "immediate_response": True,
            },
        )

    result = await run_balance_job_exclusive(settings, trigger="webhook")
    payload = result.to_dict()
    payload["immediate_response"] = False
    http_status = 200 if result.status == "success" else 500
    return JSONResponse(status_code=http_status, content=payload)
