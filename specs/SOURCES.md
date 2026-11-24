# Contract sources

These SDK-scoped snapshots match [Pulse Agent SDK TypeScript at `b2c37dc2a269a5d7364e8e580c6c578fc108f4be`](https://github.com/try-pulse/pulse-agent-sdk/tree/b2c37dc2a269a5d7364e8e580c6c578fc108f4be/specs).

| Snapshot | Owning source | Source revision |
| --- | --- | --- |
| `agent-sessions.yaml` | pulse-agent Agent Session OpenAPI | `10a8aa2` |
| `pulse-api.agent-sdk.yaml` | pulse-api OpenAPI projection | `7f2cfdab` |
| `agent-app-manifest.schema.json` | pulse-api manifest schema | `7f2cfdab` |

For a contract bump, sync and review the contract in the TypeScript repository first. Copy the three resulting snapshots from the reviewed commit, update the revision and checksums here, regenerate with `python scripts/generate_types.py`, and run both SDK test suites. Keep the matching webhook vectors in both repositories.

The Python tests include the TypeScript SDK's signed agent-session fixture and the resource webhook retry-key vector. `SHA256SUMS` pins the spec and fixture bytes.
