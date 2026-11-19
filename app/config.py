from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "bank-balance-tracking"
    log_level: str = "INFO"
    timezone: str = "Asia/Ho_Chi_Minh"
    cron_expression: str = "0 8,17 * * *"
    scheduler_enabled: bool = True
    webhook_immediate_response: bool = True

    # Feature flags / scope
    bidv_enabled: bool = False
    bidv_skip_disclosure: str = (
        "NOTICE: BIDV balances (8699888886, 8680063639, 8650119871) are temporarily excluded. "
        "The total below DOES NOT include BIDV accounts."
    )

    # Enterprise balance source
    enterprise_balance_url: str = (
        "https://6ohzqc2srk.execute-api.ap-southeast-1.amazonaws.com/dev/check-bank-account-balance"
    )
    enterprise_timeout_seconds: float = 30.0

    # Lark
    lark_token_url: str = "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal"
    lark_message_url: str = "https://open.larksuite.com/open-apis/message/v4/send/"
    lark_app_id: str = ""
    lark_app_secret: str = ""
    lark_chat_id: str = ""

    # HTTP behavior (no automatic retries per current decision)
    http_timeout_seconds: float = 30.0


settings = Settings()
