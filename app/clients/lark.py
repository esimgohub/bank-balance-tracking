import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class LarkClient:
    def __init__(
        self,
        token_url: str,
        message_url: str,
        app_id: str,
        app_secret: str,
        chat_id: str,
        timeout_seconds: float,
    ) -> None:
        self.token_url = token_url
        self.message_url = message_url
        self.app_id = app_id
        self.app_secret = app_secret
        self.chat_id = chat_id
        self.timeout_seconds = timeout_seconds

    def _validate_config(self) -> None:
        missing = []
        if not self.app_id:
            missing.append("LARK_APP_ID")
        if not self.app_secret:
            missing.append("LARK_APP_SECRET")
        if not self.chat_id:
            missing.append("LARK_CHAT_ID")
        if missing:
            raise ValueError(f"Missing required Lark configuration: {', '.join(missing)}")

    async def get_tenant_access_token(self) -> str:
        self._validate_config()
        payload = {"app_id": self.app_id, "app_secret": self.app_secret}
        headers = {"Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(self.token_url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        token = data.get("tenant_access_token") if isinstance(data, dict) else None
        if not token:
            raise ValueError("Lark token response missing tenant_access_token")

        logger.info("Obtained Lark tenant access token")
        return token

    async def send_text_message(self, token: str, text: str) -> dict[str, Any]:
        self._validate_config()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        payload = {
            "chat_id": self.chat_id,
            "msg_type": "text",
            "content": {"text": text},
        }

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(self.message_url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        # Lark APIs may return HTTP 200 with an error code in body; treat non-success as failure.
        if isinstance(data, dict):
            code = data.get("code")
            if code not in (None, 0):
                raise ValueError(f"Lark send message returned error code {code}: {data.get('msg')}")

        logger.info("Sent Lark message successfully")
        return data if isinstance(data, dict) else {"raw": data}
