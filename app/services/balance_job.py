import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from app.clients.enterprise import EnterpriseBalanceClient
from app.clients.lark import LarkClient
from app.config import Settings
from app.services.message_builder import build_balance_message

logger = logging.getLogger(__name__)

# Process-local reservation flag: set/released synchronously in the event loop to
# atomically prevent overlapping/duplicate accepted runs.
_job_reserved = False


def is_job_running() -> bool:
    return _job_reserved


def try_reserve_job_slot() -> bool:
    """Atomically reserve the single job slot. Returns False if already reserved/running."""
    global _job_reserved
    if _job_reserved:
        return False
    _job_reserved = True
    return True


def release_job_slot() -> None:
    global _job_reserved
    _job_reserved = False


@dataclass
class JobResult:
    run_id: str
    trigger: str
    started_at: str
    finished_at: str
    status: str  # success | failed
    bidv_enabled: bool
    message_sent: bool
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "trigger": self.trigger,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "bidv_enabled": self.bidv_enabled,
            "message_sent": self.message_sent,
            "error": self.error,
        }


async def run_balance_job(settings: Settings, trigger: str) -> JobResult:
    run_id = str(uuid.uuid4())
    started = datetime.now(timezone.utc)
    logger.info("Starting balance job run_id=%s trigger=%s bidv_enabled=%s", run_id, trigger, settings.bidv_enabled)

    message_sent = False
    error: Optional[str] = None
    status = "failed"

    try:
        # MB integration intentionally skipped/disabled (out of scope).
        if settings.bidv_enabled:
            # Intentionally not implemented: BIDV endpoint access/contract/concurrency to be resolved later.
            raise NotImplementedError(
                "BIDV fetching is enabled in config but not implemented yet (endpoint access pending). "
                "Set BIDV_ENABLED=false to run in the approved degraded mode."
            )

        enterprise_client = EnterpriseBalanceClient(
            url=settings.enterprise_balance_url,
            timeout_seconds=settings.enterprise_timeout_seconds or settings.http_timeout_seconds,
        )
        enterprise_data = await enterprise_client.fetch()
        enterprise = enterprise_data.get("enterprise", {}) if isinstance(enterprise_data, dict) else {}
        enterprise_text = enterprise.get("text")
        enterprise_total = enterprise.get("totalAmount")

        message = build_balance_message(
            enterprise_text=enterprise_text,
            enterprise_total=enterprise_total,
            bidv_enabled=False,
            bidv_skip_disclosure=settings.bidv_skip_disclosure,
        )

        lark_client = LarkClient(
            token_url=settings.lark_token_url,
            message_url=settings.lark_message_url,
            app_id=settings.lark_app_id,
            app_secret=settings.lark_app_secret,
            chat_id=settings.lark_chat_id,
            timeout_seconds=settings.http_timeout_seconds,
        )
        token = await lark_client.get_tenant_access_token()
        await lark_client.send_text_message(token=token, text=message)
        message_sent = True
        status = "success"
        logger.info("Balance job completed successfully run_id=%s trigger=%s", run_id, trigger)

    except Exception as exc:  # noqa: BLE001 - top-level job boundary; log and report failure
        # No automatic retries (per current decision). Ambiguous Lark send outcomes (e.g. timeout)
        # are treated as failures without resend to avoid duplicate notifications.
        error = f"{type(exc).__name__}: {exc}"
        status = "failed"
        logger.exception("Balance job failed run_id=%s trigger=%s error=%s", run_id, trigger, error)

    finished = datetime.now(timezone.utc)
    return JobResult(
        run_id=run_id,
        trigger=trigger,
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
        status=status,
        bidv_enabled=settings.bidv_enabled,
        message_sent=message_sent,
        error=error,
    )


async def run_balance_job_exclusive(settings: Settings, trigger: str) -> JobResult:
    """Run the balance job using a previously reserved process-local slot.

    Callers must reserve the slot via try_reserve_job_slot() before scheduling/awaiting this.
    """
    try:
        return await run_balance_job(settings, trigger)
    finally:
        release_job_slot()
