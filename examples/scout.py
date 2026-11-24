"""Run a small, deterministic Scout against mocked Pulse endpoints."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlsplit

import httpx

from pulse_agent_sdk import (
    AgentAppAuth,
    MemoryAuthStore,
    OAuthConfig,
    PulseAgentClient,
    WebhookEvent,
    WebhookReceiver,
)

NOW = 1_790_327_523
SECRET = "mock-webhook-secret"
WORKSPACE = "demo"


class Inbox:
    def __init__(self, database: sqlite3.Connection) -> None:
        self.db = database
        self.db.execute(
            "CREATE TABLE inbox (id INTEGER PRIMARY KEY, installation TEXT, occurrence TEXT, "
            "payload TEXT, processed INTEGER DEFAULT 0, UNIQUE(installation, occurrence))"
        )

    async def enqueue(self, event: WebhookEvent) -> None:
        key = event.dedupe_key
        assert key is not None
        with self.db:
            self.db.execute(
                "INSERT INTO inbox (installation, occurrence, payload) VALUES (?, ?, ?) "
                "ON CONFLICT(installation, occurrence) DO NOTHING",
                (*key, json.dumps(event.payload)),
            )

    async def drain(self, auth: AgentAppAuth) -> None:
        rows = self.db.execute("SELECT id, payload FROM inbox WHERE processed = 0 ORDER BY id").fetchall()
        for row_id, payload in rows:
            await answer(auth, WebhookEvent.from_verified_payload(json.loads(payload)))
            with self.db:
                self.db.execute("UPDATE inbox SET processed = 1 WHERE id = ?", (row_id,))


async def answer(auth: AgentAppAuth, event: WebhookEvent) -> None:
    if event.is_revoked and event.installation_id is not None:
        await auth.forget_installation(event.installation_id)
        return
    session = event.session
    if session is None:
        return
    client = await PulseAgentClient.for_event(auth, event)
    session_id = session["id"]

    def activity_key(step: str) -> str:
        occurrence = json.dumps((event.dedupe_key, step), separators=(",", ":"))
        return hashlib.sha256(occurrence.encode()).hexdigest()

    if event.is_stop:
        # This demo processes serially. A real worker must cancel and fence existing work first.
        await client.respond(session_id, "Stopped.", idempotency_key=activity_key("stop"))
    elif event.created is not None and (issue := session["issue"]) is not None:
        await client.thought(session_id, "Reading the issue.", idempotency_key=activity_key("start"))
        await client.set_plan(session_id, [{"content": "Summarize the issue", "status": "inProgress"}])
        details = await client.get_issue(issue["id"])
        message = f"Reviewed **{issue['identifier']}** ({details['title']})."
        await client.set_plan(session_id, [{"content": "Summarize the issue", "status": "completed"}])
        await client.respond(session_id, message, idempotency_key=activity_key("summary"))


def delivery(action: str, occurrence: str) -> tuple[bytes, dict[str, str]]:
    data = {
        "event_id": occurrence,
        "agent_session": {
            "id": "session",
            "issue": {"id": "issue", "identifier": "DEMO-1"},
        },
    }
    if action == "prompted":
        data["agent_activity"] = {"signal": "stop"}
    payload = {
        "type": "AgentSessionEvent", "action": action, "workspace_id": WORKSPACE,
        "installation_id": "installation", "app_user_id": "scout",
        "webhook_timestamp": NOW * 1000, "data": data,
    }
    raw = json.dumps(payload).encode()
    return raw, {"Pulse-Signature": hmac.digest(SECRET.encode(), raw, "sha256").hex()}


async def main() -> None:
    messages: list[str] = []
    activities: dict[str, dict[str, str]] = {}

    def pulse(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1")
        if path == "/oauth/token":
            form = parse_qs(request.content.decode())
            assert form["grant_type"] == ["authorization_code"] and len(form["code_verifier"][0]) == 43
            return httpx.Response(200, json={
                "token_type": "Bearer", "actor": "app", "access_token": "mock-access",
                "refresh_token": "mock-refresh", "expires_in": 3600, "workspace_id": WORKSPACE,
                "app_user_id": "scout", "installation_id": "installation",
            })
        assert request.headers["Authorization"] == "Bearer mock-access"
        assert request.headers["X-Workspace-ID"] == WORKSPACE
        if path == "/issues/issue":
            return httpx.Response(200, json={"id": "issue", "title": "Check the webhook inbox"})
        if path == "/agent-sessions/session" and request.method == "PATCH":
            return httpx.Response(200, json={"id": "session", **json.loads(request.content)})
        assert path == "/agent-sessions/session/activities"
        key = request.headers["Idempotency-Key"]
        if key not in activities:
            content = json.loads(request.content)["content"]
            messages.append(content["body"])
            activities[key] = {"id": f"activity-{len(messages)}"}
        return httpx.Response(201, json=activities[key])

    async with httpx.AsyncClient(transport=httpx.MockTransport(pulse)) as http:
        with TemporaryDirectory() as directory, closing(sqlite3.connect(Path(directory) / "inbox.db")) as db:
            config = OAuthConfig("scout", "mock-client-secret", "https://scout.example/callback", WORKSPACE)
            store = MemoryAuthStore(now=lambda: NOW)
            auth = AgentAppAuth(config, http, store, now=lambda: NOW)
            install_url = await auth.start_install()
            state = parse_qs(urlsplit(install_url).query)["state"][0]
            await auth.complete_install(state=state, code="mock-code")

            inbox = Inbox(db)
            receiver = WebhookReceiver(SECRET, inbox.enqueue, workspace_id=WORKSPACE, now_ms=lambda: NOW * 1000)
            for action, occurrence in (("created", "created-1"), ("created", "created-1"), ("prompted", "stop-1")):
                await receiver.receive(*delivery(action, occurrence))
            assert db.execute("SELECT COUNT(*) FROM inbox").fetchone() == (2,)
            await inbox.drain(auth)
            await auth.drain()
    assert messages == ["Reading the issue.", "Reviewed **DEMO-1** (Check the webhook inbox).", "Stopped."]
    print("\n".join(messages))


if __name__ == "__main__":
    asyncio.run(main())
