# Protocol parity

Audited against the TypeScript SDK at `b2c37dc` and the local working-tree receiver, client, and OAuth changes. The [pinned OpenAPI snapshots](../specs/SOURCES.md) govern the HTTP contract. The tests exercise mocked HTTP and replay the shared signed delivery and resource-key vectors.

Both resource vectors match the TypeScript working-tree files byte for byte at checkout revision `b2c37dc2a269a5d7364e8e580c6c578fc108f4be`. The files were untracked there, and no committed copy was found in the available TypeScript refs. Their immutable source is Python commit `3d542b41f8992cb185f0b1006f9675f30a1676b8`, verified against both working trees. A committed upstream TypeScript source remains unverified.

| Fixture | SHA-256 |
| --- | --- |
| `fixtures/resource-webhook.json` | `b930a61f22c9d74b1a4b822649bd5a6e402ef239abedcc2fc9e82b1e152bbf1b` |
| `fixtures/resource-webhook-key.json` | `08e23b302213fd30acf623507e658a323b92ad2dabdcc5245a0b320a573bcee0` |

`fixtures/agent-session-created.json` reproduces the signed example from the committed `packages/sdk/test/_helpers.ts` at `b2c37dc`.

| Wire operation or event | Python behavior and evidence |
| --- | --- |
| `GET /oauth/authorize` | `start_install` builds an `actor=app` URL with comma-separated scopes, single-use state and S256 PKCE. Tests check the challenge against the exchanged verifier. |
| `POST /oauth/token`, code grant | Sends form data and raw Basic credentials. Validates app identity, token type and workspace before saving. Tests cover mismatched workspace, expired or reused state, and cancelled callers. |
| `POST /oauth/token`, refresh grant | Atomically stores the rotated pair under the installation lock. Concurrent rejected-token callers reuse a winning refresh. Tests cover shared stores, caller cancellation, missing rotation, and `invalid_grant`. |
| `POST /oauth/revoke` | Sends `client_id` and `token` with an optional `token_type_hint`. A 200 is best effort per spec. |
| Webhook verification and dispatch | Lowercase hex HMAC over raw bytes, freshness from signed milliseconds, workspace scoping, Ping handling, callback acknowledgment before dispatch, and durable enqueue before acknowledgment. Dedupe uses an installation/event pair or a stable hash of signed resource fields. |
| `prompted`, `revoked`, `teamAccessChanged` | Distinct prompts reach callbacks across reversed deliveries and dedupe claims. The handler compares signed `created_at` with the retained Stop boundary across signal release and reopening. Stop wins ties, and delayed Stops fence stale work without cancelling newer runs. The [production guide](production.md#stop-and-access-changes) covers undated events, 24-hour ordering retention and retryable capacity limits. Revocation stops work for the installation. Permission callbacks expose team coverage and removed IDs for application fencing. |
| `GET /agent-sessions` | Repeated `state` parameters, issue filters, limit, and opaque `next_cursor`. `iter_sessions` rejects missing or repeated cursors. |
| `POST /agent-sessions` | Issue and comment helpers send exactly one target. The issue form skips ambiguous retries. The comment form retries using Pulse's reuse of open thread sessions. |
| `GET/PATCH /agent-sessions/{id}` | Reads the session and updates plan, replacement URLs, or incremental URL additions and removals. A write's `409 SESSION_ENDED` stops the run. |
| `GET /agent-sessions/{id}/activities` | Single-page requests use the server defaults when filters are omitted. Async iteration requests up to 200 rows and follows `last_seq` across gaps. Human prompts and superseded ephemeral entries remain in the returned history. |
| `POST /agent-sessions/{id}/activities` | One key per call, stable across retries. Helpers cover thought, nullable action parameter, response, error, and elicitation with `select` or `auth`. Ephemeral helpers cover thought and action. |
| `GET /auth/me`, `GET/PUT /issues/{id}` | Uses app Bearer auth and `X-Workspace-ID`. Issue status helper accepts `in_progress` and `qa`. Generated types describe the actual response objects. |
| HTTP failures | One authentication recovery for ordinary 401s or an obsolete token refusal under the same identity. `SESSION_ENDED` and a genuine installation revocation terminate the call. Transient retries are capped and expose typed failures and retry delays. |

## Exact contract differences

- The token endpoint description says refresh returns a **new** `refresh_token` every time, and app responses include `actor`, `installation_id`, `workspace_id`, and `app_user_id`. TypeScript's refresh fallback keeps the old token when the field is absent and carries forward identity without validating a returned identity. Python checks the app identity and requires a rotated token. The common token schema marks those app-only fields optional because it also covers user grants.
- TypeScript's `ActivityOptions` exposes `ephemeral` on `elicit`, but the helper silently ignores it. The spec restricts it to thought and action. Python applies that restriction at the helper surface. Pulse enforces field combinations on lower-level typed activity input.
- TypeScript's `ElicitOptions` and agent session filters behave similarly on the wire. Python iterates lazily and detects repeating cursors; TypeScript's activity collector stops when an empty page has `has_more` and has no cursor-progress guard. Python follows a valid advancing `last_seq` and surfaces malformed pages as a typed error.
- The envelope description broadly says to deduplicate on `data.event_id`. The referenced Issue, Comment, and Project schemas omit that field. The TypeScript durable receiver and Python both derive the fallback hash from signed fields, excluding the per-attempt `webhook_timestamp`. Python also uses that scoped key in callback mode. TypeScript callbacks claim only a bare `event_id`. Neither SDK uses unsigned delivery headers as identity.
- TypeScript's client branch throws on explicit API revocation. Python checks the refused credential under the installation lock. A matching refusal clears the grant. A same-identity replacement can recover the call once with the same activity key. Permission changes remain application callbacks in both SDKs.

## Python surface

The Python SDK uses async tasks for cancellation, `TypedDict` wire data, and a consumer-owned async HTTP pool and storage. Its client exposes the pinned operations and helpers. The TypeScript client additionally exposes a generic request method, a standalone token provider, framework-specific webhook adapters, and a local JSON token store. Python's `AuthStore` provides a shared locking contract; its in-package store is in memory. Typed response models preserve JSON keys and describe the pinned schema; runtime checks focus on identity, routing, response shape, and pagination.
