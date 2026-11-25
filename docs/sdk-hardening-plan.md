# Python SDK follow-up to 0.1.1

The published 0.1.1 wheel is the baseline. This work covers three behaviors found during review. The pinned OpenAPI files govern the wire contract. The TypeScript checkout supplies comparison cases and stays read-only.

| Change | Acceptance test |
| --- | --- |
| Preserve Stop across out-of-order callback deliveries. Track the signed occurrence time per session across dedupe and callback scheduling. The attempt timestamp changes on redelivery. | An older prompt delivered after Stop cannot start work. Force two async dedupe claims to finish in reverse order and check both the signal and callback side effects. A genuinely later human prompt can reopen the run. Define and test conservative handling of timestamp ties, missing ordering information and signal release. Preserve immediate acknowledgment. |
| Distinguish an obsolete token rejection from a revoked installation. Inspect the current grant under the installation lock. Bound any recovery to the same installation identity and preserve the original activity key. | Hold a mocked request open, rotate its credential, then return `401 INSTALLATION_REVOKED` for the old token. The new grant survives and the consumer receives no false terminal outcome. A genuine revocation still clears the matching grant and stops work. Verify request counts and no replay under a different identity. |
| Settle terminal Scout inbox rows. Apply terminal outcomes to the affected work in the example's SQLite worker. | Put an ended session or revoked grant ahead of a healthy session. Drain twice and verify the healthy session responds once and the terminal row stays settled. A transient failure remains eligible for retry. |

## Verification and handoff

1. Add focused mocked regressions. Update the production guide and parity notes to describe the behavior actually implemented. Record which shared fixtures come from the TypeScript working tree until they have a committed source.
2. Run the repository checks on Python 3.11–3.14. Build into a fresh candidate directory, validate wheel and sdist metadata, install each in a clean environment and run the offline Scout example.
3. Record the candidate wheel's absolute path, version and SHA-256. Run the Cyborg consumer smoke in isolation against those exact bytes using the Cyborg checkout read-only. Distinguish any downstream pin assertion from a protocol failure. Keep the published artifacts intact.

The SDK owns protocol decisions. Each app owns durable storage, authorization and workflow cancellation. This is local candidate verification. Tagging, publishing and deployment require a separate release decision.

## Follow-up after testing 0.1.2rc1

Two distinct signed human prompts were acknowledged in reverse occurrence order. With no Stop between them, only the newer prompt reached the callback. The handler currently compares every event with the latest session timestamp and retains that record for the lifetime of the process.

1. Reproduce the loss through the public callback handler. Deliver two distinct prompts newer-first, then redeliver one of them. Expect two 200 acknowledgments for the original deliveries and exactly one callback per distinct prompt. Cover reversed asynchronous dedupe completion and distinct prompts with equal timestamps. Preserve prompt contents and the immediate acknowledgment contract.
2. Use the signed occurrence time to decide which side of a Stop an event belongs to. Preserve the Stop boundary after a later prompt reopens the session. Exercise delayed pre-Stop work, a delayed Stop following newer work, timestamp ties, undated deliveries, and signal release. A late Stop must not cancel a genuinely newer run.
3. Bound retained ordering state for a long-running handler. Keep enough history for the documented Pulse retry window, clean up expired records, and exercise idle sessions, capacity pressure and expiry using a controlled clock. Document the guarantee and any limits. Evicting an active Stop early must not silently restart fenced work.
4. Check the resource webhook fixtures against a committed TypeScript source if one is available. Record its revision and verify both bytes. If the vectors exist only in the TypeScript working tree, identify their immutable Python Git source and checksums, and leave the upstream provenance gap explicit.
5. Update the production and parity docs for the verified behavior. Repeat the SDK matrix, archive metadata checks, clean installs and offline Scout run. Build a distinct local `0.1.2rc2` under `dist/callback-ordering-rc2/`. After verification, place `SHA256SUMS` there with relative filenames for the final wheel and sdist. Cyborg uses this file to select and verify the corrected candidate. Keep RC1 available for comparison.
