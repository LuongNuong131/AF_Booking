# Authentication and authorization — Prompt 3

The backend implements the four auth endpoints from Prompt 1B. There is no registration route and no booking API. Existing SQLAlchemy models/migration are reused; no database migration is needed for this step.

## Files

- `app/api/v1/auth.py`: JSON auth endpoints.
- `app/core/deps.py`: `get_current_user`, `require_roles`, `get_db_session`, and `get_auth_service`.
- `app/core/security.py`: Argon2 verification/hashing, JWT signing and strict validation.
- `app/services/auth.py`: atomic session/password changes, cache invalidation, account activation helpers.
- `app/services/session_cache.py`: bounded, short-lived user/session snapshots without password hashes.
- `app/services/login_limiter.py`: bounded per-IP/account login lockouts.
- `app/services/audit.py`: audit writes that participate in the caller's transaction.
- `app/services/session_events.py`: injectable `session.force_logout` transport interface; WebSocket runtime remains a placeholder.
- `app/core/request_context.py`: response/request correlation IDs and safe completion logs.
- `app/schemas/auth.py`: the authoritative wire schemas; frontend types are generated with the existing generator.

Paths above are relative to `backend`. The API/error details are recorded in [api-contract.md](api-contract.md).

## Configuration and startup

Use Python 3.12 and run from `backend`. Install the locked dependencies, configure your development database and secrets in the ignored `.env` file or protected process environment, then migrate and seed:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.txt
# Populate DATABASE_URL, JWT_SECRET_KEY, ADMIN_USERNAME and ADMIN_PASSWORD securely.
.venv/bin/alembic upgrade head
.venv/bin/python -m app.scripts.seed
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --no-access-log
```

`JWT_SECRET_KEY` must be an independently generated random secret of at least 32 characters. There is no built-in signing key, password, or automatically enabled demo account. On an existing database, seed preserves an active Admin's stored password; changing `ADMIN_PASSWORD` does not rotate that password. New passwords must have 12–1024 characters. Spaces are preserved in passwords; they are not trimmed or normalized.

Render's Blueprint generates its signing secret with `generateValue: true`. For an existing service, add a strong secret securely in Render settings. Do not put it in `VITE_*`, source control, logs, or chat. Rotating the signing secret invalidates all existing JWTs. A network-proxy credential placeholder is not a usable local JWT signing secret.

| Variable | Default / purpose |
| --- | --- |
| `JWT_SECRET_KEY` | Required for auth; no default |
| `JWT_EXPIRE_MINUTES` | 720 (12 hours) |
| `JWT_ISSUER` | `booking-tracker` |
| `JWT_AUDIENCE` | `booking-tracker-web` |
| `AUTH_CACHE_TTL_SECONDS` | 12; permitted range 10–15 |
| `AUTH_CACHE_MAX_ENTRIES` | 1000 |
| `LOGIN_MAX_FAILURES` | 5 |
| `LOGIN_LOCKOUT_SECONDS` | 300 |
| `AUTH_HASH_CONCURRENCY` | 2; expensive Argon2 work runs off the event loop |
| `DB_LOCK_WAIT_TIMEOUT_SECONDS` | 5 |
| `DB_QUERY_TIMEOUT_MS` | 5000 for auth transactions |
| `DB_POOL_TIMEOUT_SECONDS` | 5, also bounding auth lock acquisition |
| `REQUEST_TIMEOUT_SECONDS` | 8 |
| `WS_SEND_TIMEOUT_SECONDS` | 5 for the injectable revocation callback |

`GET /health` is process liveness and never reads the database. `/api/v1/health` remains an alias. `/api/v1/ready` checks database connectivity. A successful health/readiness probe does not validate a signing key, seeded account, or password. Missing auth configuration fails closed with `503 SERVICE_BUSY`; it does not create an insecure fallback key.

## API behavior

| Endpoint | Request | Success |
| --- | --- | --- |
| `POST /api/v1/auth/login` | `{username,password}` | `{access_token,user,token_type:"bearer",expires_in}` |
| `GET /api/v1/auth/me` | Bearer token | Public user object |
| `POST /api/v1/auth/logout` | Bearer token | `{message:"Signed out."}` |
| `POST /api/v1/auth/change-password` | Bearer token and `{old_password,new_password}` | `{message:"Password changed. Please sign in again."}` |

Public user fields are `id`, `username`, `full_name`, `role`, `is_active`, and `settings` (JSON or null). Password hashes and `current_session_id` are never returned. Auth responses, including errors, carry `Cache-Control: no-store`.

JWTs use HS256 with an explicitly allowed algorithm and required `sub`, `role`, `sid`, `iat`, `exp`, `iss`, and `aud` claims. `sub` is the user ID as a string; `sid` is a UUID. Expired, malformed, unsigned, wrong-audience/issuer, or incorrectly signed tokens return `401 UNAUTHORIZED`. There is no refresh-token flow in this prompt.

Every successful login replaces `users.current_session_id` with a new UUID. Active users with a mismatched or cleared SID receive `401 SESSION_REPLACED`. Inactive/deleted users receive `401 UNAUTHORIZED`. Unknown usernames, wrong passwords, and disabled login attempts use the same generic login error. Role authorization always uses the current database/cache user role, not the JWT role claim alone.

Changing a password verifies the old value, stores a new Argon2id hash, and clears the session. The client must discard the token and sign in again. A wrong old password, an unchanged new password, or invalid new-password input returns `422 VALIDATION_ERROR`; other request errors keep the common envelope. Successful logout also revokes the current SID.

Credential verification occurs outside database row locks. Mutations then lock and re-read the user to check the authoritative SID, active flag, and password hash. An old request cannot clear a newer login or change its password. Concurrent successful logins have last-committed-session-wins semantics. Session changes and their audit rows commit atomically; an audit failure rolls back the session mutation.

## Login rate limiting and proxy IPs

The first five failed credential attempts in a five-minute window return the generic 401. The fifth starts a five-minute lockout; subsequent attempts return `429 RATE_LIMITED` with `Retry-After`. A success clears that pair's failures. Requests for the same pair are serialized so concurrent wrong passwords cannot bypass the threshold.

The pair uses the ASGI client IP and, for a known account, the stored username selected through the database's unique index. This coalesces all case/accent aliases recognized by MySQL/TiDB collation. Unknown names are normalized for limiting. A throttled request can still perform the indexed account lookup, but does not run Argon2 or append another credential-failure audit row. The limiter retains at most 10,000 pairs and rejects new pairs if full rather than evicting active lockouts. HTTP completion logs still record throttled requests.

The application does not trust an arbitrary `X-Forwarded-For` header itself. Configure Uvicorn's trusted proxy addresses (`FORWARDED_ALLOW_IPS`) for the actual deployment proxy if needed; do not trust client-supplied forwarding headers indiscriminately. Keep one backend process/instance while rate limits and cache invalidation are in memory. A restart clears lockouts; multiple workers/instances require shared coordination before scaling.

## Reusable dependencies and revocation hooks

Future routers use dependencies instead of reimplementing authorization:

```python
from typing import Annotated
from fastapi import Depends
from app.core.deps import get_current_user, require_roles
from app.services.session_cache import CurrentUser

Agent = Annotated[CurrentUser, Depends(get_current_user)]
Reviewer = Annotated[CurrentUser, Depends(require_roles("admin", "qc"))]
```

`get_db_session` supplies a fresh async session for future router/service work; the caller owns its transaction. Auth checks use independent short transactions and return an immutable snapshot rather than a live ORM user.

For Prompt 5, obtain `AuthService` with `get_auth_service` and call:

```python
await auth.kick_session(user_id, actor_id=admin.id, context=audit_context)
await auth.set_user_active(user_id, False, actor_id=admin.id, context=audit_context)
```

These are internal helpers, not public admin endpoints; the future caller must enforce Admin authorization. Both invalidate the in-process cache as part of their mutation. `set_user_active` also clears an existing session on disable. Re-enabling an account does not restore its old SID.

Cache entries expire after 12 seconds. Reads and mutations for a user share bounded locks, preventing an in-flight read from repopulating stale cache data after invalidation. Login/logout/password/kick/disable invalidate on success, failure, and cancellation/uncertain commit. Future role/profile changes must use the same `auth.mutation(user_id)` boundary or call `auth.invalidate_user(user_id)` after commit. Out-of-process/direct-SQL changes can remain cached until TTL and are not a substitute for these helpers.

Inject a `SessionEvents` implementation with `create_app(settings, session_events=...)`. The callback `force_logout(user_id, old_session_id, reason)` represents the reserved `session.force_logout` event and always targets the old session. It runs after commit with a bounded send deadline. Transport failure cannot undo revocation. The default implementation is deliberately a no-op placeholder; no WebSocket frame format or runtime is added in this prompt.

## Audit and request IDs

Audit actions are `login_success`, `login_failed`, `logout`, `password_changed`, `session_replaced`, `session_kicked`, `user_disabled`, and `user_enabled`. Session replacement is recorded once at revocation time, not on every subsequent rejected old-token request. Records contain actor/target IDs, client IP when valid, and a correlation request ID; credential values, hashes, and access tokens are not audit metadata.

Failed logins have no authenticated actor (`user_id` is null); a known attempted account remains the target entity, and the submitted username is retained in metadata.

Every HTTP response includes `X-Request-ID`. A supplied 1–64 character ID containing only letters, digits, `.`, `_`, or `-` is reused; otherwise a UUID is generated. Completion logs include that ID, method, path, status, and elapsed time. Query strings, headers, and bodies are not logged by this middleware. Recommended Uvicorn commands disable its separate access log so the request logs have the safe correlated format. CORS exposes `X-Request-ID` and `Retry-After` to permitted browser origins.

## Curl smoke test

The following examples run against your own local server. Read credentials interactively, keep them out of shell history, and use HTTPS for hosted deployments. Responses containing JWTs are captured rather than printed.

```sh
export BOOKING_API=http://127.0.0.1:8000
read -r -p 'Username: ' BOOKING_USERNAME
read -r -s -p 'Password: ' BOOKING_PASSWORD
export BOOKING_USERNAME BOOKING_PASSWORD
BOOKING_AUTH_RESPONSE=$(python3 -c 'import json,os; print(json.dumps({"username":os.environ["BOOKING_USERNAME"],"password":os.environ["BOOKING_PASSWORD"]}))' |
  curl --fail-with-body --silent --show-error --max-time 15 \
    "$BOOKING_API/api/v1/auth/login" -H 'Content-Type: application/json' --data-binary @-)
BOOKING_TOKEN=$(printf '%s' "$BOOKING_AUTH_RESPONSE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
unset BOOKING_PASSWORD BOOKING_AUTH_RESPONSE

curl --fail-with-body --max-time 10 "$BOOKING_API/health"
curl --fail-with-body --max-time 10 "$BOOKING_API/api/v1/auth/me" \
  -H "Authorization: Bearer $BOOKING_TOKEN" -H 'X-Request-ID: curl-auth-check'
curl --fail-with-body --max-time 10 -X POST "$BOOKING_API/api/v1/auth/logout" \
  -H "Authorization: Bearer $BOOKING_TOKEN"
unset BOOKING_TOKEN
```

For password change, capture a fresh login token, then send this body through stdin:

```sh
read -r -s -p 'Old password: ' BOOKING_OLD_PASSWORD
read -r -s -p 'New password: ' BOOKING_NEW_PASSWORD
export BOOKING_OLD_PASSWORD BOOKING_NEW_PASSWORD
python3 -c 'import json,os; print(json.dumps({"old_password":os.environ["BOOKING_OLD_PASSWORD"],"new_password":os.environ["BOOKING_NEW_PASSWORD"]}))' |
  curl --fail-with-body --silent --show-error --max-time 15 \
    "$BOOKING_API/api/v1/auth/change-password" -H 'Content-Type: application/json' \
    -H "Authorization: Bearer $BOOKING_TOKEN" --data-binary @-
unset BOOKING_OLD_PASSWORD BOOKING_NEW_PASSWORD BOOKING_TOKEN
```

## Tests

```sh
# From backend; normal unit tests do not require a database.
.venv/bin/python -m pytest -q
# Docker suites use new isolated TLS databases and remove their own containers.
.venv/bin/python tests/run_schema_checks.py --engine mysql --suite auth --report /tmp/auth-mysql.xml
.venv/bin/python tests/run_schema_checks.py --engine tidb --suite auth --report /tmp/auth-tidb.xml
```

Integration tests verify correct/incorrect/unknown/disabled login, warmed-cache revocation, ACLs, misleading token roles, logout races, password changes and their races, lockout expiry/collation aliases, cache query counts/TTL, audit metadata, concurrent logins, transport failures, and audit rollback. Unit tests cover JWT expiry/signature/claims/algorithm rejection, bounded limiter behavior, hashing cancellation, request IDs, no registration route, and DB-free root health. Database suites are skipped in the ordinary unit run and run separately in CI for both MySQL and TiDB.
