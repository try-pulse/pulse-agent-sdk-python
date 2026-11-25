# Contract sources

The TypeScript and Python SDKs share the same contract snapshots. The file digests in `SHA256SUMS` identify the exact bytes.

| Snapshot | Owning source | Source revision |
| --- | --- | --- |
| `agent-sessions.yaml` | pulse-agent Agent Session OpenAPI | `91c78ef9ae28` |
| `pulse-api.agent-sdk.yaml` | pulse-api OpenAPI projection | `de809bcf3bed` |
| `agent-app-manifest.schema.json` | pulse-api manifest schema | `de809bcf3bed` |

For a contract bump, sync and review the contract in the TypeScript repository first. Copy the three resulting snapshots from the reviewed commit, update the revision and checksums here, regenerate with `python scripts/generate_types.py`, and run both SDK test suites. Keep the matching webhook vectors in both repositories.

The Python tests include the TypeScript SDK's signed agent-session fixture and the resource webhook retry-key vector. `SHA256SUMS` pins the spec and fixture bytes.
