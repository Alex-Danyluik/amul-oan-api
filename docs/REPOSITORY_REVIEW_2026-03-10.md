# Repository Review Notes

Date: 2026-03-10

Scope: whole-repository review focused on strange implementations, dead code, and unused segments.

## Telemetry Status

Telemetry was not wired into the request flow when this review was written, and the unused telemetry modules were removed during cleanup on 2026-03-10.

Removed:
- `app/tasks/telemetry.py`
- `helpers/telemetry.py`

Reason:
- No active request-path invocation existed.
- The implementation had broken event-construction code and added dead maintenance surface.

## Findings

### 1. Broken telemetry event construction

Files:
- [helpers/telemetry.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/helpers/telemetry.py#L124)
- [helpers/telemetry.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/helpers/telemetry.py#L174)

Notes:
- `TelemetryEvent.mid` uses a field validator that treats the field value as a dict.
- In practice, `mid` is not auto-generated correctly.
- `create_event()` also advertises `Dict` support but later assumes `.model_dump()` exists on the payload.

Status:
- Removed during cleanup.

Impact:
- Before removal, telemetry was not only unwired, it was also fragile if re-enabled.

### 2. Development auth is not actually optional

Files:
- [app/auth/jwt_auth.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/app/auth/jwt_auth.py#L16)
- [app/auth/jwt_auth.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/app/auth/jwt_auth.py#L59)

Notes:
- `OptionalOAuth2PasswordBearer` returns `None` in development when no token is provided.
- `get_current_user()` still requires the JWT public key and still attempts decode flow.

Impact:
- The comments/docstring suggest relaxed development auth, but the implementation still blocks requests without proper JWT setup.

### 3. Auth router includes token-minting endpoints with no real credential validation

Files:
- [app/routers/auth.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/app/routers/auth.py#L176)
- [app/routers/auth.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/app/routers/auth.py#L289)

Notes:
- `/auth/login` issues JWTs without password validation.
- `/auth/demo` also issues JWTs freely.
- JWT lifetime is long-lived by default.

Impact:
- Safe only if tightly constrained to internal/demo environments.
- Risky if exposed in production.

### 4. Suggestions endpoint behavior does not match its docstring

Files:
- [app/routers/suggestions.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/app/routers/suggestions.py#L9)
- [app/services/chat.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/app/services/chat.py#L316)

Notes:
- The endpoint says it triggers async suggestion generation on cache miss.
- It currently only returns cached suggestions or `[]`.
- Suggestion creation is only triggered from the chat flow after moderation.

Impact:
- The endpoint contract is misleading.

### 5. CORS defaults are inconsistent for browser credentialed requests

Files:
- [app/config.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/app/config.py#L26)
- [main.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/main.py#L39)

Notes:
- `allowed_origins=["*"]` with `allow_credentials=True` is a problematic combination.

Impact:
- Browser clients using credentials may fail unexpectedly.

### 6. Legacy translation module is disconnected and appears stale

Files:
- [helpers/translation.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/helpers/translation.py)
- [app/services/translation.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/app/services/translation.py)

Notes:
- Active translation flow uses `app/services/translation.py`.
- `helpers/translation.py` has no active in-repo runtime call path.
- It references a missing asset: `assets/word_mapping_reduced_1000.json`.

Impact:
- Strong sign of abandoned legacy code.

### 7. Many agent tool modules exist but are unreachable

Files:
- [agents/tools/__init__.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/agents/tools/__init__.py)
- [agents/tools/animal.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/agents/tools/animal.py)
- [agents/tools/cvcc.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/agents/tools/cvcc.py)
- [agents/tools/farmer.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/agents/tools/farmer.py)
- [agents/tools/search.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/agents/tools/search.py)
- [agents/tools/terms.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/agents/tools/terms.py)

Notes:
- Only `search_documents` is registered in the active tool list.
- Other tools are present but commented out or not wired into the agent.

Impact:
- Large surface area with unclear ownership and likely drift.

### 8. Response schemas are present but unused

Files:
- [app/models/responses.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/app/models/responses.py)

Notes:
- The routers mostly return raw `JSONResponse` or stream responses directly.
- These response models are not used as the API contract.

Impact:
- Docs and code can diverge silently.

### 9. Moderation-history helpers appear unused

Files:
- [app/utils.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/app/utils.py#L55)
- [app/utils.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/app/utils.py#L66)
- [app/utils.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/app/utils.py#L70)

Notes:
- Moderation-specific cache/history utilities are defined but have no active runtime call path.

Impact:
- More dead helper surface to maintain.

### 10. Sensitive request data is logged at info level

Files:
- [app/auth/jwt_auth.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/app/auth/jwt_auth.py#L89)
- [app/routers/chat.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/app/routers/chat.py#L27)
- [app/services/chat.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/app/services/chat.py#L218)

Notes:
- Decoded JWT payloads, user info, and full user queries are logged.

Impact:
- Potential PII leakage into logs and telemetry systems.

### 11. Webview endpoint does sequential FCM validation across configured Firebase apps

Files:
- [app/routers/auth.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/app/routers/auth.py#L261)
- [app/auth/fcm_auth.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/app/auth/fcm_auth.py#L93)
- [app/auth/fcm_auth.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/app/auth/fcm_auth.py#L135)

Notes:
- `/auth/webview-url` depends on `require_fcm_token()`.
- `require_fcm_token()` calls `verify_fcm_token()` in a thread.
- `verify_fcm_token()` tries `messaging.send(..., dry_run=True)` against each configured Firebase app one by one until one succeeds.
- There is no short-term cache for previously validated tokens.

Impact:
- The endpoint pays external network latency on every request.
- With multiple service accounts configured, requests may perform multiple Firebase validations serially.
- This is likely acceptable at low volume, but it is unnecessarily slow for a URL-minting endpoint and will add avoidable tail latency.

Suggested direction:
- Cache successful validations for a short TTL.
- Remember the last successful Firebase app per token and try it first.
- If production only uses one Firebase project, remove the fallback loop.

### 12. Unused helper functions remain in active modules

Files:
- [helpers/transcription.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/helpers/transcription.py#L38)
- [helpers/transcription.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/helpers/transcription.py#L47)
- [helpers/transcription.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/helpers/transcription.py#L268)
- [helpers/tts.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/helpers/tts.py#L18)
- [helpers/utils.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/helpers/utils.py#L85)
- [helpers/utils.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/helpers/utils.py#L97)
- [helpers/utils.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/helpers/utils.py#L169)

Notes:
- Several sync or fallback helpers are present with no active in-repo call path.

Impact:
- Not immediately dangerous, but they make the codebase noisier and harder to reason about.

### 13. Small file-local dead imports

Files:
- [app/routers/chat.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/app/routers/chat.py#L6)
- [app/tasks/suggestions.py](/Users/kanavdwevedi/repositories/OAN/amul/amul-api-integration/amul-oan-api/app/tasks/suggestions.py#L5)

Notes:
- `create_suggestions` is imported in the router and never used there.
- `BackgroundTasks` is imported in the suggestions task module and never used.

## Suggested Cleanup Order

1. Fix or remove telemetry before trying to wire it in.
2. Gate or remove demo auth endpoints outside development.
3. Make development auth behavior match its documentation.
4. Correct suggestions endpoint docs or behavior.
5. Remove or archive disconnected legacy modules.
6. Reduce sensitive logging.
