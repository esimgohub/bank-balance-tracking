# bank-balance-tracking

Service to replace the n8n workflow `[in use][PRODUCTION] Bank Balance Tracking.json` by fetching bank/enterprise balances and sending a summary to a Lark channel on schedule.

See `plan-for-replication.md` for migration scope, risks, and cutover requirements.

## Current implementation status

- **BIDV balance fetch is skipped intentionally** (`BIDV_ENABLED=false`) due to current endpoint access issues. When disabled, **every notification includes a disclosure** stating BIDV balances are excluded and the reported total excludes BIDV (no fabricated values).
- **MB crawler node is not implemented** (it was disconnected in the n8n workflow).
- **No automatic retries** are implemented (including ambiguous Lark send outcomes) to avoid duplicate notifications.
- **Trigger behavior:** `POST /bank_tracking` supports `WEBHOOK_IMMEDIATE_RESPONSE`:
  - `true` (default): returns **`202 Accepted`** immediately and runs the job in the background (in-process/in-memory).
  - `false`: waits for job completion and returns the run result.
- **Concurrency/delivery:** a process-local run slot is reserved atomically before accepting/scheduling a run, preventing overlapping or queued duplicate runs (concurrent trigger requests return **`409`** while a run is in progress). In immediate mode, accepted/in-flight work is in-memory and can be lost on process restart (no durable queue).
- **Exposure:** Docker Compose binds the API to `127.0.0.1:8000` by default. The webhook has no built-in authentication/rate limiting—do not expose it publicly without adding access controls (or placing it behind an authenticated/restricted proxy).
- Schedule defaults to `0 8,17 * * *` in `Asia/Ho_Chi_Minh` (configurable); verify actual n8n timezone/run times before cutover.

## Requirements

- Docker + Docker Compose

## Configuration

1. Edit `.env` (created with placeholders) and provide required values:
   - `LARK_APP_ID`, `LARK_APP_SECRET`, `LARK_CHAT_ID`
   - `ENTERPRISE_BALANCE_URL` (and any network access required)
   - schedule/timezone settings as needed

2. Do **not** commit secrets. Credentials found in the n8n export must be treated as exposed and rotated/revoked before migration/cutover as per the plan.

## Run with Docker Compose

```bash
docker compose up -d --build
```

The API will be available on `http://localhost:8000` (bound to localhost by default in `docker-compose.yml`). To allow remote access, change the port mapping and add appropriate authentication/rate limiting/network restrictions.

## Endpoints

- `GET /health` — service/config status (non-secret)
- `POST /bank_tracking` — trigger a balance run
  - `WEBHOOK_IMMEDIATE_RESPONSE=true` (default): returns `202 Accepted` and runs in background
  - `WEBHOOK_IMMEDIATE_RESPONSE=false`: returns run result after completion
  - returns `409 Conflict` if another run is already in progress
  - **unauthenticated** endpoint; keep it restricted to trusted callers/network

## Behavior notes (important)

- **Enterprise source:** fetched via `ENTERPRISE_BALANCE_URL` and expects `enterprise.text` and `enterprise.totalAmount` in the response.
- **Lark:** obtains tenant access token then sends a text message to `LARK_CHAT_ID`.
- **Partial failures:** enabled-source failures (e.g. enterprise fetch/parse failure, Lark auth/send failure) fail the run and no success notification is sent; check logs for details. Ambiguous send outcomes are treated as failures without auto-resend.
- **Before cutover:** confirm n8n schedule timezone/run history, webhook response contract expectations, real API contracts/samples, and obtain documented owner go/no-go if decommissioning n8n while BIDV remains disabled.
- **Future (BIDV):** enabling BIDV requires network access to the internal bankinfo service, contract/`fetch_transactions` validation, and concurrency/rate-limit validation before restoring full-source parity.
