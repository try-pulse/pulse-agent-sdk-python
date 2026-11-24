# Changelog

## 0.1.0

First public Python SDK release for Pulse Agent Apps.

- Async OAuth installation with S256 PKCE, shared refresh locking, revocation handling, and credential-operation draining.
- Signed webhook verification, post-ack callbacks, durable inbox intake and restart-safe event restoration, scoped deduplication, Stop signals, and permission events.
- Typed Agent Sessions, activities, signals, issue operations and pagination generated from pinned OpenAPI, with typed failures and bounded retries.
- Python 3.11–3.14 CI, wheel and source distribution checks, a deterministic Scout example, and PyPI Trusted Publishing.
