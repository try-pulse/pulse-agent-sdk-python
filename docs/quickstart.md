# Python quickstart

Install the SDK with `python -m pip install pulse-agent-sdk` after the PyPI release, or install the built wheel. Use Python 3.11–3.14.

From a checkout or unpacked sdist, run `python examples/scout.py` for a complete offline run. It exchanges a mocked OAuth code, verifies signed deliveries, commits them to a SQLite inbox, and answers a delegation and Stop. You should see a thought, an issue summary, and `Stopped.`

## Install your Pulse app

Register the app in Pulse and set its OAuth redirect URI and webhook URL. Keep the OAuth client secret and webhook signing secret in your app's secret store. Use the developer workspace ID for the registration and grant.

```python
import os

import httpx
from pulse_agent_sdk import AgentAppAuth, MemoryAuthStore, OAuthConfig

config = OAuthConfig(
    client_id=os.environ["PULSE_CLIENT_ID"],
    client_secret=os.environ["PULSE_CLIENT_SECRET"],
    redirect_uri=os.environ["PULSE_REDIRECT_URI"],
    workspace_id=os.environ["PULSE_WORKSPACE_ID"],
)
```

Create one `httpx.AsyncClient(timeout=10.0)` and one `AgentAppAuth(config, http, store)` in your app's lifespan. Use `MemoryAuthStore()` for local development and a shared [production store](production.md) for deployment.

- In an administrator-authorized route, redirect the browser to `await auth.start_install()`. It generates single-use state and an S256 PKCE challenge. If you configure `install_secret`, pass the supplied secret directly from your app's request handling.
- In the registered callback, call `await auth.complete_install(state=state, code=code, error=error)` with the callback query parameters. It consumes the state and stores the app installation. Render your own success or failure page.
- On shutdown, finish ingress and worker tasks, then call `await auth.drain()` before closing HTTP. A cancelled caller can leave a credential exchange finishing in the background.

## Receive work and answer

```python
from pulse_agent_sdk import PulseAgentClient, WebhookReceiver

receiver = WebhookReceiver(
    os.environ["PULSE_WEBHOOK_SECRET"], inbox.enqueue, workspace_id=config.workspace_id,
)

# In the webhook route, use the original request bytes and headers.
await receiver.receive(raw_body, headers)
# Return 2xx after enqueue commits.

# In the worker, restore the verified event from the inbox.
if event.created is not None and event.session_id is not None:
    client = await PulseAgentClient.for_event(auth, event)
    await client.thought(event.session_id, "Reading the issue", idempotency_key=stored_activity_key)
```

`inbox.enqueue` is an async function supplied by your app. The worker owns execution, authorization, and any activity keys that survive a restart. For a single-process agent, `WebhookHandler` can dispatch callbacks after returning its acknowledgment. See [production integration](production.md) for Stop and permission handling.
