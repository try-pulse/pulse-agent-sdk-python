# Changelog

## 0.1.3

Refresh the Pulse API types for issue messaging intake, team moves, issue type and blocking relationships.

## 0.1.2

- Deliver distinct prompts in callback mode even when they arrive out of order or share a timestamp.
- Use signed occurrence times to enforce Stop across delayed deliveries and reopened runs. A delayed Stop fences older work while leaving newer runs active.
- Retain callback session ordering for 24 hours of idle time and return a retryable HTTP 503 for new sessions at capacity.
- Retry an API call once when Pulse refuses an obsolete credential and a replacement exists under the same installation identity.
- Settle terminal SQLite inbox rows in the Scout example and retain transient failures for retry.

## 0.1.1

First PyPI release. Updates Trusted Publishing to support core metadata 2.5 and
validates distributions in CI with the same Twine and packaging versions as the publisher.

## 0.1.0

Initial GitHub beta for Pulse Agent Apps.

- Async OAuth installation with S256 PKCE, shared refresh locking, revocation handling, and credential-operation draining.
- Signed webhook verification, post-ack callbacks, durable inbox intake and restart-safe event restoration, scoped deduplication, Stop signals, and permission events.
- Typed Agent Sessions, activities, signals, issue operations and pagination generated from pinned OpenAPI, with typed failures and bounded retries.
- Python 3.11–3.14 CI, wheel and source distribution checks, a deterministic Scout example, and PyPI Trusted Publishing.
