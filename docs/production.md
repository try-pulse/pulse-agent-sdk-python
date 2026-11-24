# Production integration

## OAuth and HTTP lifecycle

- Keep the install route administrator-only. Bind the callback to the initiating browser session and consume OAuth state atomically with a short TTL. Protect and expire stored PKCE verifiers and keep registration and environment namespaces separate.
- Encrypt token records with a managed key. Implement `AuthStore.lock_installation` across all replicas for one installation, covering the refresh exchange and atomic write of both returned tokens. A lease must remain valid through the write. If a process dies during exchange, reauthorization may be required. Pulse rotates refresh tokens and the SDK leaves ambiguous OAuth exchanges to the operator or consumer.
- Give the SDK a dedicated HTTP client and configure its timeouts and TLS there. Reuse it across requests. During shutdown stop accepting deliveries, settle workers or `await handler.idle()`, then `await auth.drain()` before closing HTTP. Never log token records via serialization, signed bodies, Basic or Bearer headers, callback URLs, or raw error details.
- `revoke_token` calls Pulse's OAuth endpoint, which returns 200 even for unknown tokens. On a verified `OAuthApp/revoked` event, fence work for the installation and call `forget_installation`. A refresh with `invalid_grant` removes the stored grant. An API `401 INSTALLATION_REVOKED` removes the matching cached credential under the installation lock.

## Webhook inbox

Read raw bytes with an ingress size limit. Pass all headers to `WebhookReceiver.receive`, preserving duplicates where your framework permits it. It checks the raw-body HMAC, the signed timestamp, routing fields, and workspace. Return 2xx within five seconds once the inbox commits. Map `WebhookError.status` to the HTTP response and return a retryable 5xx when the inbox transaction fails. Ping is verified and acknowledged without an inbox row.

Put a unique constraint on `(installation_id, occurrence)` per app and environment. Insert atomically and retain the key beyond Pulse's last retry, at least 24 hours for ordinary delivery. Store the verified `event.payload` and its key from trusted ingress. Restore it with `WebhookEvent.from_verified_payload` from trusted storage only. In a worker, use a lease or transaction to claim work and fence stale runners. Persist a separate `idempotency_key` for each activity so worker retries and restarts can replay that step safely. `for_event` checks that the installation and event agree on workspace and app user. Apply your own policy and check current access before side effects.

`WebhookHandler` is for in-process callbacks. Pass `workspace_id`, and share `handler.stops` with `PulseAgentClient.for_event(..., stops=handler.stops)`. `handle` returns before dispatch, so use `on_error` for callback failures. A custom `DedupeStore` atomically claims a compact JSON string holding `[installation_id, occurrence]`. Callback dispatch can be lost on process exit. Use the inbox when work must survive restarts.

## Stop and access changes

- A `prompted` event with `agent_activity.signal == "stop"` is an explicit Stop, including undelegation. Prioritize it over queued work, cancel the running task, and fence any late writes. Send one final `response` or `error` with a stable key during the 60-second grace period. A normal human prompt can open a new run.
- A `SessionEndedError` is terminal for the current run. Stop and make no more writes. Uninstallation, team removal, and issue deletion can end a session immediately and have no grace period.
- `event.permission_change` gives the new team coverage and removed IDs. Invalidate cached authorization and fence work that lost access. Handle issue removals similarly when subscribed. The SDK leaves team-to-run mapping and cancellation policy with the worker. In callback mode a `StopSignal` wakes cooperative tasks, and the application calls `task.cancel()` where needed and releases entries with `SessionStops.release` after settlement.

## Retries

The SDK retries rate limits and honors `Retry-After` up to 60 seconds. Transport errors, 408s, and transient 5xx responses are retried for repeatable operations, including activity creates carrying a key. The initial delay is up to 250 ms with jitter. Proactive creation on an issue has no idempotency key on the wire, so reconcile an ambiguous outcome before issuing a second create. Use `PulseApiError.code`, `.status`, and `.retry_after` (seconds), `PulseTransportError.timed_out`, and the separate terminal `InstallationRevokedError` and `SessionEndedError`. Treat `.details` as sensitive application data.
