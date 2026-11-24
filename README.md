# Pulse Agent SDK for Python

Build a Pulse Agent App with Python 3.11–3.14. The SDK handles OAuth installation, signed webhooks, Agent Sessions, and activities through an async `httpx` client.

## Install

```bash
python -m pip install pulse-agent-sdk
```

For an unpublished build, install the supplied wheel or run `python -m pip install .` from the source checkout.

## Get started

- [Python quickstart](https://github.com/try-pulse/pulse-agent-sdk-python/blob/main/docs/quickstart.md) covers installation, webhook intake, and sending an activity.
- [Scout example](https://github.com/try-pulse/pulse-agent-sdk-python/blob/main/examples/scout.py) runs OAuth, signed deliveries, deduplication, and Stop entirely offline.
- [Production integration](https://github.com/try-pulse/pulse-agent-sdk-python/blob/main/docs/production.md) covers durable storage, access changes, cancellation, and retries.

From a checkout or unpacked source distribution, run `python examples/scout.py` after installing the package. It needs no credentials or model.

## Development

```bash
python -m pip install -e '.[dev]'
make -j3 check
```

`make test` runs the mocked suite by itself. On systems without Make, run `python -m pytest`, `python -m ruff check src tests scripts examples`, `python -m mypy`, and `python scripts/generate_types.py --check`. The release toolchain is available separately with `.[release]`.

See [CONTRIBUTING.md](https://github.com/try-pulse/pulse-agent-sdk-python/blob/main/CONTRIBUTING.md) for pull requests and [SECURITY.md](https://github.com/try-pulse/pulse-agent-sdk-python/blob/main/SECURITY.md) for private reporting.

The [pinned contracts](https://github.com/try-pulse/pulse-agent-sdk-python/blob/main/specs/SOURCES.md) come from the [TypeScript SDK](https://github.com/try-pulse/pulse-agent-sdk). The [parity audit](https://github.com/try-pulse/pulse-agent-sdk-python/blob/main/docs/protocol-parity.md) records wire behavior and implementation differences.
