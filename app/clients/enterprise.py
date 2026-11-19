import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class EnterpriseBalanceClient:
    def __init__(self, url: str, timeout_seconds: float) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds

    async def fetch(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(self.url)
            response.raise_for_status()
            data = response.json()

        if not isinstance(data, dict):
            raise ValueError("Enterprise balance response is not a JSON object")

        enterprise = data.get("enterprise")
        if not isinstance(enterprise, dict):
            raise ValueError("Enterprise balance response missing 'enterprise' object")

        # Validate expected fields are present (values may still be normalized later).
        if "text" not in enterprise or "totalAmount" not in enterprise:
            raise ValueError("Enterprise balance response missing required fields: enterprise.text and/or enterprise.totalAmount")

        logger.info("Fetched enterprise balance data successfully")
        return data
