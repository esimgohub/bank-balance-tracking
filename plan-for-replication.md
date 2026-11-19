# Plan: Replicate n8n "Bank Balance Tracking" with a Scheduled Backend Service

## 1. Goal and scope

Replace the n8n workflow `[in use][PRODUCTION] Bank Balance Tracking` with a backend service/job that performs the same balance aggregation and Lark notification on schedule, targeting behavior parity for the **currently active path** unless explicitly changed.

**In scope (parity target):**
- Scheduled runs at **08:00 and 17:00** on cron `0 8,17 * * *` in the **verified** timezone (n8n export does not explicitly configure timezone in schedule/workflow settings; pinned sample suggests `Asia/Ho_Chi_Minh (UTC+07:00)` but this is not proof of active scheduler config—confirm before cutover).
- Manual trigger equivalent to webhook `POST /bank_tracking`, preserving the **current webhook response contract/behavior** (export leaves webhook response options unspecified; verify before changing).
- Fetch enterprise/bank aggregate data from the existing AWS endpoint.
- Obtain Lark tenant access token and send the formatted text message to the configured Lark chat.
- Compute/format totals and message content to match current behavior for the sources that are enabled.

**Temporary scope adjustment (per current direction):**
- **Skip BIDV balance endpoint calls for now.** The internal bankinfo endpoint (`/api/bidv/fetch-payment-account-detail`) cannot be called in the current environment; connectivity/access will be addressed later. The replacement must make BIDV fetching an explicit, configurable behavior (disabled by default or clearly flagged) with documented impact on totals/message (no fabricated values).
- **While BIDV is disabled, every notification must clearly state that BIDV balances are excluded and that the reported total excludes BIDV.** Do not present a partial total as a complete/full balance.
- **BIDV-disabled operation is degraded, not full parity.** Do not treat it as parity-complete until BIDV is enabled and validated.

**Out of scope by default (requires decision):**
- `Get MB Bank account balance (ky niem)` node: present in export but **disconnected and excluded** from totals/message. Treat as not in active parity unless explicitly confirmed.
- Changing recipients, message content/format, data sources, or adding persistence/UI beyond what is needed for reliable operation.

## 2. Current behavior to replicate (active path)

**Flow (as wired):** Trigger (schedule or webhook) → `POST enterprise balance API` → `GET BIDV balance (8699888886)` → `GET BIDV balance (8680063639)` → `GET BIDV balance (8650119871)` → `POST Lark tenant_access_token/internal` → compute/format total → `POST Lark message send`.

**Key details observed:**
- **Schedule:** cron `0 8,17 * * *`; timezone not explicitly set in export. Pinned execution sample shows `Asia/Ho_Chi_Minh (UTC+07:00)`—use as a hypothesis to verify against n8n instance/workflow config and actual run history.
- **Webhook:** `POST /bank_tracking` (`webhookId=8a27ac74-f105-4de5-8222-54209df5f315`), response options unspecified; downstream does not read payload.
- **Enterprise API:** `POST https://6ohzqc2srk.execute-api.ap-southeast-1.amazonaws.com/dev/check-bank-account-balance` (no auth/body shown in export). Used fields: `enterprise.text`, `enterprise.totalAmount`.
- **BIDV API (currently to be skipped):** `GET http://services-bankinfo-hseklc:8000/api/bidv/fetch-payment-account-detail` with `client_id`, `client_secret`, `merchant_id`, `accountNo`, `accept: application/json`; `fetch_transactions=false` set for 639/871 (988 omits it in export). Used field: `data.balance`. Calls are sequential in n8n. **Note:** credentials are passed as query parameters, which can be exposed in URL/access/proxy logs.
- **Lark:** token from `/open-apis/auth/v3/tenant_access_token/internal` using `app_id`/`app_secret`; message sent to `/open-apis/message/v4/send/` as `msg_type=text` to `chat_id` with text composed of `enterprise.text` plus per-account BIDV lines and overall total.
- **Formatting:** balances shown with locale-style thousands separators; `enterprise.text` newlines/tabs escaped when embedded in the message payload.

## 3. Proposed architecture

- **Service type:** small stateless backend service (preferred, to support both cron and webhook trigger) or a scheduled job/cron container with an HTTP endpoint. Language/runtime per repo/team standards (repo is currently minimal; `.gitignore` suggests Python is plausible but not mandated).
- **Modules/components:**
  - `config`: load/validate required settings from environment/secret store (fail fast on missing required config in production); include feature flags for BIDV fetch (disabled now) and MB fetch (out of scope by default).
  - `clients`: thin HTTP clients for enterprise API, BIDV bankinfo API (when enabled), and Lark (token + send) with explicit timeouts.
  - `aggregator`: orchestrate enabled fetches, normalize results, compute total and formatted output according to an explicit policy for skipped/unavailable sources.
  - `message_builder`: produce message text matching current template/escaping rules for enabled data; when BIDV is disabled, **explicitly disclose in every notification** that BIDV balances are excluded and the total excludes BIDV (never fabricate balances or imply completeness).
  - `scheduler`: trigger job at `08:00,17:00` in the verified timezone with single-run guard/locking.
  - `http trigger`: `POST /bank_tracking` endpoint invoking the same job path; preserve or explicitly approve current response contract.
  - `observability`: structured logs, run/job outcome metrics, and error reporting (no secrets/sensitive URLs with credentials).
- **Execution model:** fetch independent enabled sources concurrently where safe; while BIDV is skipped, only enabled sources run. **If/when BIDV is enabled**, validate that the bankinfo service supports concurrent requests without rate-limit/session side effects before parallelizing; otherwise retain sequential calls for parity.

## 4. Configuration and secrets (externalize all hardcoded values)

> **Do not commit secrets.** All values embedded in the n8n export must be treated as exposed. **Rotate/revoke affected credentials before migration work (Phase 0)** and prevent them from being copied into new code, logs, deployment configs, CI artifacts, or example files. Avoid passing secrets in URLs/query strings where possible; if an upstream requires it (as BIDV does today), ensure redaction in logs/telemetry.

| Category | Items to configure | Notes |
|---|---|---|
| Schedule/trigger | Verified `TIMEZONE`, cron expression/hours, enable/disable webhook, webhook response mode, webhook auth (if any) | Confirm actual n8n schedule timezone/run times before asserting parity. |
| Enterprise source | Base URL/endpoint, HTTP method, timeout, retry policy, any auth headers/keys (if required) | Confirm contract for `enterprise.text`, `enterprise.totalAmount`. |
| BIDV/bankinfo (skipped now) | `BIDV_ENABLED=false` initially, base URL, `client_id`, `client_secret`, `merchant_id`, account list (`accountNo`, display label/bank name), `fetch_transactions` behavior, timeout/retry, concurrency mode | Requires internal network access; query-param credentials are a leakage risk—redact and revisit transport/auth if possible when enabling. |
| Lark | `app_id`, `app_secret`, token endpoint, message endpoint, `chat_id`, message format/template, send retry/idempotency policy | Keep `chat_id` configurable; define safe handling for ambiguous send outcomes (see Phase 4). |
| MB crawler (if later enabled) | Endpoint, `corp_id`, `username`, `password`, flags | Currently unused/disconnected; include only behind a feature flag after explicit decision. |
| Runtime behavior | Per-call timeout, retries/backoff, overall job timeout, partial-failure policy, run/notification dedupe policy, log level/redaction | Define defaults explicitly. |

## 5. Implementation plan (phased)

### Phase 0 — Prerequisites, security, and discovery (blockers to clear early)
1. **Credential rotation/revocation (immediate, before migration work):** identify all exposed credentials in the workflow/export (Lark, BIDV, MB, any others) and dependent systems; rotate/revoke and update secret storage. Ensure new implementation/config/logging never records secrets or credential-bearing URLs.
2. **Confirm parity target and degraded-mode approval path:** active path only vs include MB node; confirm acceptable message/total behavior while **BIDV is skipped** (temporary) and when later enabled. **If cutover may occur while BIDV is disabled, obtain documented owner approval for degraded operation and the required user-visible disclosure; otherwise n8n must remain active until full-source parity is restored.**
3. **Verify schedule timezone and run history:** confirm n8n instance/workflow timezone and actual execution times; do not assume `Asia/Ho_Chi_Minh` without verification.
4. **Verify webhook contract:** determine current `POST /bank_tracking` response behavior (sync/async, status/body, timeout expectations) and preserve it or obtain explicit approval to change.
5. **Obtain real contracts/samples:** example success/error responses for enterprise API and Lark token/send APIs (including timeout/ambiguous-send behavior and any idempotency/deduplication support); when BIDV work resumes, obtain BIDV response/error samples and confirm `fetch_transactions` intent per account.
6. **Verify network access & concurrency (for future BIDV enablement):** confirm deployment can reach `http://services-bankinfo-hseklc:8000` when needed; validate whether concurrent BIDV requests are safe (rate limits/session side effects) before enabling parallel calls.
7. **Secrets handling:** establish secret store/injection mechanism and redaction policy.

### Phase 1 — Service scaffold & configuration
1. Initialize project structure, dependency management, and runtime (container-friendly).
2. Implement typed/validated config loading for all required settings and feature flags (`BIDV_ENABLED`, etc.); document env vars and redaction expectations.
3. Add health/readiness endpoint (if long-running service) and basic structured logging with secret/URL-parameter redaction.

### Phase 2 — API clients & aggregation logic
1. Implement enterprise client and Lark client (token + send) with timeouts, safe JSON parsing, explicit error mapping, and no secret logging.
2. Implement BIDV client behind a feature flag/config path but **do not enable calls** until connectivity is resolved; when enabled later, respect validated concurrency mode and `fetch_transactions` settings.
3. Implement aggregator: fetch enabled sources, apply explicit numeric coercion/defaulting rules, compute total and deterministic formatting, and represent skipped BIDV data per agreed policy (never fabricate). When BIDV is disabled, totals must be computed/labeled as excluding BIDV.
4. Implement message builder to match current template for enabled data and preserve safe JSON/string escaping; **when BIDV is disabled, every notification must clearly disclose that BIDV balances are excluded and the total excludes BIDV**.
5. Implement Lark send handling that distinguishes definite success, definite failure, and **ambiguous outcomes** (e.g. request timeout/connection drop after send attempt) so retries cannot blindly create duplicate notifications.

### Phase 3 — Triggers & scheduling
1. Add scheduler for `0 8,17 * * *` in the **verified** timezone with single-run guard/locking to prevent overlapping executions.
2. Add `POST /bank_tracking` handler invoking the same job path; preserve verified response contract (or approved change) and add auth/rate limiting if needed.
3. Define idempotency/deduplication expectations for repeated webhook calls and for retry/restart scenarios; ensure they do not cause unintended duplicate Lark notifications.

### Phase 4 — Reliability & observability
1. Define and implement failure policy: per-dependency timeout + limited retries with backoff for transient errors; clear behavior for partial data/unavailable sources (especially while BIDV is skipped) — choose explicitly with stakeholders.
2. **Lark notification retry safety:** do not blindly retry a send on ambiguous outcomes (timeouts/unknown delivery state). Prefer a verified-safe mechanism if supported (e.g. provider idempotency/deduplication key or post-send verification); otherwise fail the run as ambiguous, alert operators, and require explicit/manual reconciliation rather than automatic resend. Record run/notification state needed to detect duplicates.
3. Emit structured logs per run (run id, trigger type, per-source enabled/latency/status, success/failure/ambiguous, Lark send result) with secrets and credential-bearing query parameters redacted.
4. Add metrics/alerts for job failure, ambiguous notification outcomes, missing schedule execution, and upstream dependency errors; retain enough run context for debugging.

### Phase 5 — Validation & cutover
1. **Unit tests:** total/formatting logic, message rendering/escaping (including required BIDV-exclusion disclosure), config validation, BIDV-skipped behavior, and notification state handling.
2. **Integration tests (mocked HTTP):** success path (BIDV skipped/enabled modes as applicable), one-source failure, Lark auth failure, definite Lark send failure, **ambiguous Lark send outcome (e.g. timeout after Lark may have accepted the request) verifying no automatic duplicate notification is sent**, malformed responses.
3. **Staging/dry run:** run against real reachable endpoints in a safe manner (e.g., send to a test chat/channel or behind a "dry-run/no-send" flag) and compare output to n8n results for the enabled scope; verify BIDV-exclusion disclosure appears in every notification when BIDV is disabled.
4. **Parallel run:** operate alongside n8n for a short window and compare messages/totals at scheduled times (accounting for intentional BIDV-skip differences until resolved).
5. **Cutover go/no-go (explicit):**
   - **Full-source parity path:** enable and validate BIDV, complete parallel-run comparison, then decommission n8n.
   - **BIDV-disabled (degraded) path:** may proceed **only** with documented owner approval of degraded operation **and** verified notification disclosure that every message/total excludes BIDV. If approval or disclosure is missing, **keep n8n active** until full-source parity is restored.
6. **Cleanup:** remove deprecated artifacts/config remnants and verify no exposed secrets remain in repo, configs, or logs; confirm rotation/revocation from Phase 0 is complete.

## 6. Risks and open questions

- **Exposed credentials (high):** plaintext credentials exist in the workflow export and BIDV credentials are sent as query parameters (URL/log exposure risk). Rotation/revocation and leak prevention must happen before migration work, not at cutover.
- **Degraded cutover without explicit approval (high):** decommissioning n8n while BIDV is skipped would omit BIDV balances from reported totals. This requires documented owner approval and mandatory in-message disclosure that totals exclude BIDV; otherwise n8n must remain active until full-source parity is restored.
- **Duplicate Lark notifications on ambiguous retries (medium):** a send request may time out after Lark accepted it; blind retries can duplicate notifications. Safe retry/idempotency behavior for ambiguous outcomes must be defined, implemented, and tested.
- **Schedule timezone uncertainty (medium):** cron is `0 8,17 * * *` but timezone is not explicit in export; pinned data is not proof. Active run times must be verified.
- **Webhook response contract unknown (medium):** export leaves response options unspecified; changing to "return run result/status" may break callers if they rely on current behavior.
- **BIDV calls temporarily skipped:** known gap per current direction; totals/message will not include BIDV balances until connectivity and contract details are resolved and the feature is enabled.
- **BIDV concurrency/parity (medium, when enabled):** n8n runs BIDV requests sequentially; parallelization requires validation against rate limits/session side effects.
- **Internal network dependency:** `services-bankinfo-hseklc:8000` is unreachable until deployed in the correct network — required before enabling BIDV.
- **Undocumented API contracts:** null/missing fields, error shapes, and auth requirements may differ from assumptions in the export.
- **Partial-failure semantics:** no explicit handling today; sending incorrect totals on partial data is a business risk—policy must be decided (especially with BIDV skipped).
- **Dormant MB integration:** credentials and endpoint exist but flow is inactive; unclear if intentionally removed or pending re-enable.
- **Webhook exposure/idempotency:** manual trigger can cause duplicate notifications without safeguards; dedupe must also consider retries/restarts.
- **Message fidelity:** minor formatting/escaping differences can occur; confirm acceptable tolerance.

## 7. Definition of done

- Service runs at 08:00 and 17:00 in the **verified** timezone and supports `POST /bank_tracking` with the **verified/approved** response contract.
- For the agreed enabled scope (currently **excluding BIDV fetches by direction**), produces correct aggregation and Lark notification behavior with no fabricated values and **every notification explicitly discloses that BIDV balances/total are excluded**.
- **No BIDV-disabled cutover without explicit go/no-go:** n8n is decommissioned only after full-source parity, **or** after documented owner approval of degraded operation with verified disclosure in every notification. Otherwise n8n remains active.
- Exposed credentials rotated/revoked before migration work; no secrets committed or leaked to logs/configs/artifacts (including credential-bearing URLs where avoidable).
- Timeouts/retries/failure behavior, **safe handling of ambiguous Lark send outcomes (no blind duplicate-sending retries)**, redaction, and alerting are implemented, tested, and documented.
- BIDV remains disabled behind config until connectivity/contract/concurrency are validated; enabling BIDV restores full-source parity after parallel-run comparison.
- Parallel-run comparison completed for the applicable scope and n8n safely decommissioned per the approved cutover path.