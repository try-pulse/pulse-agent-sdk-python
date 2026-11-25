"""Protocol tests use the same HTTP boundary as a real Pulse app."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import sqlite3
import time
from collections.abc import AsyncIterator, Callable
from contextlib import closing
from dataclasses import replace
from email.utils import formatdate
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from examples import scout
from pulse_agent_sdk import (
    AgentAppAuth,
    InstallationRevokedError,
    InstallationTokens,
    InstallSecretError,
    MemoryAuthStore,
    OAuthConfig,
    OAuthError,
    PulseAgentClient,
    PulseApiError,
    PulseTransportError,
    SessionEndedError,
    SessionStops,
    WebhookError,
    WebhookEvent,
    WebhookHandler,
    WebhookReceiver,
    verify_webhook,
)

CONFIG = OAuthConfig("client", "secret:with spaces", "https://cyborg.test/oauth/callback", "workspace")
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def token_response(*, workspace: str = "workspace") -> httpx.Response:
    return httpx.Response(200, json={
        "access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600,
        "actor": "app", "token_type": "Bearer",
        "installation_id": "install", "workspace_id": workspace, "app_user_id": "app-user",
    })


@pytest.fixture
async def make_auth() -> AsyncIterator[Callable]:
    clients: list[httpx.AsyncClient] = []

    async def make(handler, *, existing: bool = False) -> AgentAppAuth:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), auth=("unrelated", "identity"), follow_redirects=True,
        )
        clients.append(client)
        store = MemoryAuthStore()
        if existing:
            await store.put_tokens(InstallationTokens(
                "install", "workspace", "app-user", "old-access", "old-refresh", time.time() + 3600,
            ))
        return AgentAppAuth(CONFIG, client, store)

    yield make
    for client in clients:
        await client.aclose()


async def test_install_uses_pkce_and_consumes_state_once(make_auth):
    requests = []

    def exchange(request):
        requests.append(request)
        return token_response()

    auth = await make_auth(exchange)
    url = urlsplit(await auth.start_install())
    query = parse_qs(url.query)
    assert url.path == "/api/v1/oauth/authorize"
    assert query["actor"] == ["app"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["scope"] == ["read,write,app:assignable,app:mentionable"]
    state = query["state"][0]
    with pytest.raises(OAuthError, match="invalid_state"):
        await auth.complete_install(state="unknown", code="code")
    record = await auth.complete_install(state=state, code="code")
    assert await auth.store.get_tokens("install") == record
    assert record.refresh_token == "new-refresh"
    assert "new-refresh" not in repr(record)
    assert requests[0].url.path == "/api/v1/oauth/token"
    basic = requests[0].headers["Authorization"].removeprefix("Basic ")
    assert base64.b64decode(basic) == b"client:secret:with spaces"
    form = parse_qs(requests[0].content.decode())
    challenge = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"][0].encode()).digest())
    assert query["code_challenge"] == [challenge.rstrip(b"=").decode()]
    assert form["redirect_uri"] == [CONFIG.redirect_uri]
    with pytest.raises(OAuthError, match="invalid_state"):
        await auth.complete_install(state=state, code="code")
    assert len(requests) == 1


async def test_install_rejects_another_workspace(make_auth):
    auth = await make_auth(lambda _: token_response(workspace="other"))
    state = parse_qs(urlsplit(await auth.start_install()).query)["state"][0]
    with pytest.raises(OAuthError, match="installation_mismatch"):
        await auth.complete_install(state=state, code="code")
    assert await auth.store.get_tokens("install") is None


async def test_install_secret_precedes_oauth_state_creation(make_auth):
    auth = await make_auth(lambda _: token_response())
    guarded = AgentAppAuth(CONFIG, auth.http, auth.store, install_secret="only-admin")
    with pytest.raises(InstallSecretError):
        await guarded.start_install("incorrect")
    assert parse_qs(urlsplit(await guarded.start_install("only-admin")).query)["actor"] == ["app"]


async def test_rotation_is_shared_between_managers_and_survives_caller_cancellation(make_auth):
    requests = []
    sent = asyncio.Event()
    proceed = asyncio.Event()

    async def exchange(request):
        requests.append(request)
        sent.set()
        await proceed.wait()
        return token_response()

    auth = await make_auth(exchange, existing=True)
    other = AgentAppAuth(CONFIG, auth.http, auth.store)
    caller = asyncio.create_task(auth.get_access_token("install", rejected_token="old-access"))
    await asyncio.wait_for(sent.wait(), timeout=1)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    next_caller = asyncio.create_task(other.get_access_token("install", rejected_token="old-access"))
    proceed.set()
    assert await asyncio.wait_for(next_caller, timeout=1) == "new-access"
    assert len(requests) == 1
    assert parse_qs(requests[0].content.decode())["refresh_token"] == ["old-refresh"]
    assert (await auth.store.get_tokens("install")).refresh_token == "new-refresh"


async def test_invalid_grant_drops_only_the_refused_installation(make_auth):
    auth = await make_auth(lambda _: httpx.Response(400, json={"error": "invalid_grant"}), existing=True)
    await auth.store.put_tokens(InstallationTokens("another", "workspace", "u", "a", "r", time.time() + 3600))
    with pytest.raises(InstallationRevokedError):
        await auth.get_access_token("install", rejected_token="old-access")
    assert await auth.store.get_tokens("install") is None
    assert await auth.get_access_token("another") == "a"


async def test_refresh_burst_shares_one_temporary_failure(make_auth):
    entered = asyncio.Event()
    proceed = asyncio.Event()
    calls = 0

    async def exchange(_):
        nonlocal calls
        calls += 1
        entered.set()
        await proceed.wait()
        return httpx.Response(503, json={"error": "temporarily_unavailable"})

    auth = await make_auth(exchange, existing=True)
    burst = [asyncio.create_task(auth.get_access_token("install", rejected_token="old-access")) for _ in range(16)]
    await asyncio.wait_for(entered.wait(), timeout=1)
    proceed.set()
    results = await asyncio.gather(*burst, return_exceptions=True)
    assert all(isinstance(error, OAuthError) and error.status == 503 for error in results)
    assert calls == 1
    assert (await auth.installation("install")).refresh_token == "old-refresh"


def signed_webhook(*, offset: int = 0, workspace: str = "workspace", event_type: str = "AgentSessionEvent"):
    data = {"label": "Cyborg"} if event_type == "Ping" else {
        "event_id": "evt-1", "agent_session": {"id": "session"},
        "agent_activity": {"signal": "stop", "content": {"type": "prompt", "body": "Stop"}},
    }
    payload = {
        "type": event_type, "action": "create" if event_type == "Ping" else "prompted",
        "workspace_id": workspace, "webhook_id": "webhook", "created_at": "2026-11-24T08:00:00.000Z",
        "url": "", "actor": None, "webhook_timestamp": int(time.time() * 1000) + offset,
        "data": data,
    }
    if event_type != "Ping":
        payload.update(installation_id="install", app_user_id="app-user")
    return sign(payload)


def sign(payload: dict[str, Any]) -> tuple[bytes, httpx.Headers]:
    raw = json.dumps(payload).encode()
    signature = hmac.digest(b"fixture-secret", raw, "sha256").hex()
    return raw, httpx.Headers({"pUlSe-SiGnAtUrE": signature, "Pulse-Timestamp": "0"})


def test_typescript_sdk_created_envelope_signature():
    # Pulse SDK b2c37dc, packages/sdk/test/_helpers.ts. The signature uses Node's
    # JSON.stringify and the SDK's test secret.
    fixture = FIXTURES / "agent-session-created.json"
    raw = json.dumps(json.loads(fixture.read_text(encoding="utf-8")), separators=(",", ":")).encode()
    event = verify_webhook(raw, {
        "Pulse-Signature": "0653e2fb505070c24935d95061a42f0a0e8d3d9f13cc2e7aed34165c1082f56a",
    }, "pwhsec_test_secret", now_ms=lambda: 1_790_327_523_120)
    assert event.dedupe_key == ("inst1", "ase_s1_created")
    assert event.session_id == "sess_1"
    assert not event.is_stop
    assert event.data["agent_session"]["issue"]["identifier"] == "PUL-1"


async def test_webhook_waits_for_enqueue_and_exposes_stop():
    entered = asyncio.Event()
    persisted = asyncio.Event()

    async def enqueue(event: WebhookEvent) -> None:
        assert event.dedupe_key == ("install", "evt-1")
        assert event.session_id == "session"
        assert event.is_stop
        entered.set()
        await persisted.wait()

    receiver = WebhookReceiver("fixture-secret", enqueue, workspace_id="workspace")
    pending = asyncio.create_task(receiver.receive(*signed_webhook()))
    await asyncio.wait_for(entered.wait(), timeout=1)
    assert not pending.done()
    persisted.set()
    assert (await pending).is_stop
    assert (await receiver.receive(*signed_webhook(event_type="Ping"))).dedupe_key is None


async def test_durable_receiver_propagates_failed_commit():
    async def unavailable(_):
        raise RuntimeError("inbox unavailable")

    receiver = WebhookReceiver("fixture-secret", unavailable, workspace_id="workspace")
    with pytest.raises(RuntimeError, match="inbox unavailable"):
        await receiver.receive(*signed_webhook())


async def test_webhook_rejects_tampered_stale_and_wrong_workspace_deliveries():
    async def enqueue(_: WebhookEvent) -> None:
        pytest.fail("must not enqueue an invalid event")

    receiver = WebhookReceiver("fixture-secret", enqueue, workspace_id="workspace")
    raw, headers = signed_webhook()
    with pytest.raises(WebhookError, match="bad_signature"):
        await receiver.receive(raw + b" ", headers)
    with pytest.raises(WebhookError, match="stale_timestamp"):
        await receiver.receive(*signed_webhook(offset=-61_000))
    with pytest.raises(WebhookError, match="wrong_workspace"):
        await receiver.receive(*signed_webhook(workspace="other"))


async def test_issue_event_without_event_id_has_a_stable_key_across_redelivery():
    events = []

    async def enqueue(event):
        events.append(event)

    payload = json.loads((FIXTURES / "resource-webhook.json").read_text(encoding="utf-8"))
    expected = json.loads((FIXTURES / "resource-webhook-key.json").read_text(encoding="utf-8"))
    receiver = WebhookReceiver(
        "fixture-secret", enqueue, workspace_id="ws1", now_ms=lambda: 1_790_327_523_120,
    )
    for attempt in range(2):
        payload["webhook_timestamp"] += attempt
        raw = json.dumps(payload).encode()
        await receiver.receive(raw, {
            "Pulse-Signature": hmac.digest(b"fixture-secret", raw, "sha256").hex(),
            "Pulse-Delivery-Id": f"unsigned-{attempt}",
        })
    assert len(events) == 2
    assert events[0].event_id is None
    assert events[0].dedupe_key == events[1].dedupe_key
    assert list(events[0].dedupe_key) == expected


async def test_callback_handler_acks_first_dedupes_and_stops_the_running_signal():
    order = []
    signals = []
    stops = SessionStops()

    def created(_, context):
        order.append("created")
        signals.append(context.signal)

    def prompted(_, context):
        order.append("stopped")
        assert context.is_stop and context.signal.aborted

    handler = WebhookHandler(
        "fixture-secret", stops=stops, on_session_created=created, on_session_prompted=prompted,
    )
    raw, headers = signed_webhook()
    payload = json.loads(raw)
    payload["action"] = "created"
    payload["data"]["event_id"] = "created"
    raw_created = json.dumps(payload).encode()
    created_headers = {"Pulse-Signature": hmac.digest(b"fixture-secret", raw_created, "sha256").hex()}
    assert handler.handle(raw_created, created_headers) == (200, {"ok": True})
    assert not order
    assert handler.handle(raw_created, created_headers) == (200, {"ok": True})
    await handler.idle()
    assert order == ["created"]
    assert not signals[0].aborted
    assert handler.handle(raw, headers) == (200, {"ok": True})
    await handler.idle()
    assert order == ["created", "stopped"]
    assert (await signals[0].wait()).kind == "stop_signal"


def session_delivery(occurrence, created_at, *, stop=False, action="prompted", offset=0, session="session"):
    raw, _ = signed_webhook(offset=offset)
    payload = json.loads(raw)
    payload["action"] = action
    if created_at is None:
        del payload["created_at"]
    else:
        payload["created_at"] = created_at
    payload["data"]["event_id"] = occurrence
    payload["data"]["agent_session"]["id"] = session
    if not stop:
        payload["data"]["agent_activity"].pop("signal")
        payload["data"]["agent_activity"]["content"]["body"] = f"Prompt {occurrence}"
    return sign(payload)


@pytest.mark.parametrize("same_time", [False, True])
@pytest.mark.parametrize("reverse_claims", [False, True])
async def test_callback_delivers_distinct_ordinary_prompts(same_time, reverse_claims):
    old_claim = asyncio.Event()
    finish_old = asyncio.Event()
    new_callback = asyncio.Event()
    claimed = set()
    callbacks = []

    class Dedupe:
        async def claim(self, key):
            if key in claimed:
                return False
            claimed.add(key)
            if json.loads(key)[1] == "old":
                old_claim.set()
                await finish_old.wait()
            return True

    def prompted(event, context):
        assert not context.is_stop and not context.signal.aborted
        callbacks.append((event.event_id, event.data["agent_activity"]["content"]["body"]))
        if event.event_id == "new":
            new_callback.set()

    handler = WebhookHandler("fixture-secret", dedupe=Dedupe() if reverse_claims else None, on_session_prompted=prompted)
    later = "2026-11-24T08:00:02.000Z"
    earlier = later if same_time else "2026-11-24T08:00:01.000Z"
    if reverse_claims:
        assert handler.handle(*session_delivery("old", earlier)) == (200, {"ok": True})
        assert not old_claim.is_set()
        await asyncio.wait_for(old_claim.wait(), timeout=1)
    assert handler.handle(*session_delivery("new", later)) == (200, {"ok": True})
    assert callbacks == []
    if not reverse_claims:
        assert handler.handle(*session_delivery("old", earlier)) == (200, {"ok": True})
        assert callbacks == []
    await asyncio.wait_for(new_callback.wait(), timeout=1)
    finish_old.set()
    await handler.idle()
    assert handler.handle(*session_delivery("old", earlier, offset=10_000)) == (200, {"ok": True})
    await handler.idle()
    assert callbacks == [("new", "Prompt new"), ("old", "Prompt old")]


@pytest.mark.parametrize("first", ["old", "stop"])
async def test_callback_stop_survives_reverse_dedupe_completion_and_redelivery(first):
    keys = (first, "stop" if first == "old" else "old")
    entered = {key: asyncio.Event() for key in keys}
    finished = {key: asyncio.Event() for key in keys}
    proceed = {key: asyncio.Event() for key in keys}
    claims = {}
    callbacks = []

    class Dedupe:
        async def claim(self, key):
            _, occurrence = json.loads(key)
            claims[occurrence] = claims.get(occurrence, 0) + 1
            if occurrence in entered and claims[occurrence] == 1:
                entered[occurrence].set()
                await proceed[occurrence].wait()
                finished[occurrence].set()
            return claims[occurrence] == 1

    handler = WebhookHandler(
        "fixture-secret", dedupe=Dedupe(),
        on_session_created=lambda event, ctx: callbacks.append((event.event_id, ctx.signal.aborted)),
        on_session_prompted=lambda event, ctx: callbacks.append((event.event_id, ctx.signal.aborted)),
    )
    older = "2026-11-24T08:00:00.000Z"
    stop_time = "2026-11-24T08:00:01.000Z"
    deliveries = {"old": session_delivery("old", older), "stop": session_delivery("stop", stop_time, stop=True)}
    original = handler.stops.signal("session")
    for key in keys:
        assert handler.handle(*deliveries[key]) == (200, {"ok": True})
        assert not entered[key].is_set()
        await asyncio.wait_for(entered[key].wait(), timeout=1)
    proceed[keys[1]].set()
    await asyncio.wait_for(finished[keys[1]].wait(), timeout=1)
    interim_callbacks = list(callbacks)
    proceed[keys[0]].set()
    await handler.idle()
    assert interim_callbacks == ([("stop", True)] if keys[1] == "stop" else [])
    assert callbacks == [("stop", True)]
    assert original.aborted

    for event in (
        session_delivery("old", older, offset=10_000),
        session_delivery("older-after-stop", older, offset=10_000),
        session_delivery("tie", stop_time),
        session_delivery("unknown", None),
        session_delivery("created-late", "2026-11-24T08:00:02.000Z", action="created"),
    ):
        assert handler.handle(*event)[0] == 200
    await handler.idle()
    assert callbacks == [("stop", True)]
    assert handler.stops.signal("session") is original

    handler.stops.release("session")
    assert handler.handle(*session_delivery("released-stale", older))[0] == 200
    await handler.idle()
    assert callbacks == [("stop", True)]
    assert handler.handle(*session_delivery("new", "2026-11-24T08:00:03.000Z"))[0] == 200
    await handler.idle()
    assert callbacks == [("stop", True), ("new", False)]
    assert original.aborted and not handler.stops.is_stopped("session")
    for delivery in (
        session_delivery("stale-stop", stop_time, stop=True),
        session_delivery("pre-stop-after-reopening", older),
        session_delivery("tie-after-reopening", stop_time),
        session_delivery("undated-after-reopening", None),
        session_delivery("post-stop-out-of-order", "2026-11-24T08:00:02.000Z"),
    ):
        assert handler.handle(*delivery)[0] == 200
    await handler.idle()
    assert callbacks == [("stop", True), ("new", False), ("post-stop-out-of-order", False)]
    assert not handler.stops.is_stopped("session")


async def test_callback_late_stop_fences_delayed_work_without_cancelling_newer_run():
    callbacks = []
    handler = WebhookHandler(
        "fixture-secret", on_session_prompted=lambda event, ctx: callbacks.append((event.event_id, ctx.signal)),
    )
    stop_time = "2026-11-24T08:00:02.000Z"
    assert handler.handle(*session_delivery("new", "2026-11-24T08:00:04.000Z"))[0] == 200
    await handler.idle()
    for delivery in (
        session_delivery("late-stop", stop_time, stop=True),
        session_delivery("old", "2026-11-24T08:00:01.000Z"),
        session_delivery("tie", stop_time),
        session_delivery("post-stop", "2026-11-24T08:00:03.000Z"),
    ):
        assert handler.handle(*delivery)[0] == 200
    await handler.idle()
    assert [key for key, _ in callbacks] == ["new", "post-stop"]
    assert callbacks[0][1] is callbacks[1][1] and not callbacks[0][1].aborted
    assert handler.handle(*session_delivery("tie-with-work", "2026-11-24T08:00:04.000Z", stop=True))[0] == 200
    await handler.idle()
    assert [key for key, _ in callbacks] == ["new", "post-stop", "tie-with-work"]
    assert callbacks[0][1].aborted


async def test_callback_undated_work_is_allowed_until_stop():
    callbacks = []
    handler = WebhookHandler("fixture-secret", on_session_prompted=lambda event, ctx: callbacks.append(event.event_id))
    assert handler.handle(*session_delivery("dated", "2026-11-24T08:00:01.000Z"))[0] == 200
    await handler.idle()
    assert handler.handle(*session_delivery("undated", None))[0] == 200
    await handler.idle()
    assert callbacks == ["dated", "undated"]


@pytest.mark.parametrize("missing", [None, "not a timestamp", "2026-11-24T08:00:00"])
async def test_callback_undated_stop_stays_stopped(missing):
    callbacks = []
    handler = WebhookHandler(
        "fixture-secret", on_session_prompted=lambda _, ctx: callbacks.append(ctx.is_stop),
    )
    assert handler.handle(*session_delivery("stop", missing, stop=True))[0] == 200
    await handler.idle()
    assert handler.handle(*session_delivery("new", "2026-11-24T08:00:03.000Z"))[0] == 200
    await handler.idle()
    assert callbacks == [True]
    assert handler.stops.is_stopped("session")


async def test_callback_order_capacity_keeps_stop_and_reclaims_idle_sessions(monkeypatch):
    now = 0.0
    monkeypatch.setattr("pulse_agent_sdk.handler.monotonic", lambda: now)
    claims = []
    callbacks = []

    class Dedupe:
        def claim(self, key):
            claims.append(json.loads(key)[1])
            return True

    handler = WebhookHandler(
        "fixture-secret", dedupe=Dedupe(), max_ordered_sessions=2,
        on_session_prompted=lambda event, ctx: callbacks.append((event.event_id, ctx.signal.aborted)),
    )
    older = "2026-11-24T08:00:00.000Z"
    stop_time = "2026-11-24T08:00:01.000Z"
    assert handler.handle(*session_delivery("stop", stop_time, stop=True))[0] == 200
    assert handler.handle(*session_delivery("idle", older, session="idle"))[0] == 200
    await handler.idle()
    handler.stops.release("session")

    now = 86_399
    overflow = session_delivery("overflow", older, session="overflow")
    assert handler.handle(*overflow) == (503, {"ok": False, "error": "session_order_capacity"})
    assert handler.handle(*session_delivery("fenced", older))[0] == 200
    await handler.idle()
    assert claims == ["stop", "idle", "fenced"]
    assert callbacks == [("stop", True), ("idle", False)]

    now = 86_400
    assert handler.handle(*overflow)[0] == 200
    await handler.idle()
    assert callbacks[-1] == ("overflow", False)
    assert handler.handle(*session_delivery("still-fenced", older))[0] == 200
    await handler.idle()
    assert callbacks[-1] == ("overflow", False)

    now = 172_800
    assert handler.handle(*session_delivery("after-expiry", older))[0] == 200
    await handler.idle()
    assert callbacks[-1] == ("after-expiry", False)


async def test_callback_order_does_not_expire_while_dedupe_is_pending(monkeypatch):
    now = 0.0
    monkeypatch.setattr("pulse_agent_sdk.handler.monotonic", lambda: now)
    stop_entered = asyncio.Event()
    stop_ready = asyncio.Event()
    callbacks = []

    class Dedupe:
        async def claim(self, key):
            if json.loads(key)[1] == "stop":
                stop_entered.set()
                await stop_ready.wait()
            return True

    handler = WebhookHandler(
        "fixture-secret", max_ordered_sessions=1, dedupe=Dedupe(),
        on_session_prompted=lambda event, ctx: callbacks.append((event.event_id, ctx.signal.aborted)),
    )
    older = "2026-11-24T08:00:00.000Z"
    assert handler.handle(*session_delivery("stop", "2026-11-24T08:00:01.000Z", stop=True))[0] == 200
    await asyncio.wait_for(stop_entered.wait(), timeout=1)
    now = 86_401
    assert handler.handle(*session_delivery("untracked", older, session="other"))[0] == 503
    assert handler.handle(*session_delivery("fenced", older))[0] == 200
    stop_ready.set()
    await handler.idle()
    assert callbacks == [("stop", True)]
    assert handler.stops.is_stopped("session")


async def test_activity_retries_keep_the_same_key_and_401_refreshes_once(make_auth):
    activities = []

    def exchange(request):
        if request.url.path.endswith("/oauth/token"):
            return token_response()
        activities.append(request)
        assert request.headers["X-Workspace-ID"] == "workspace"
        assert json.loads(request.content) == {"content": {"type": "response", "body": "Done"}}
        if len(activities) == 1:
            assert request.headers["Authorization"] == "Bearer old-access"
            return httpx.Response(401)
        assert request.headers["Authorization"] == "Bearer new-access"
        if len(activities) == 2:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(201, json={"id": "activity"})

    client = PulseAgentClient(await make_auth(exchange, existing=True), "install", max_retries=1)
    assert await client.respond("session", "Done", idempotency_key="stable-key") == {"id": "activity"}
    assert [r.headers["Idempotency-Key"] for r in activities] == ["stable-key"] * 3


async def test_ended_session_and_ambiguous_issue_creation_are_never_retried(make_auth):
    paths = []

    def exchange(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/activities"):
            return httpx.Response(409, json={"code": "SESSION_ENDED", "details": {"end_reason": "undelegated"}})
        return httpx.Response(503)

    stops = SessionStops()
    signal = stops.signal("session", "install")
    client = PulseAgentClient(await make_auth(exchange, existing=True), "install", stops=stops)
    with pytest.raises(SessionEndedError) as ended:
        await client.respond("session", "Done")
    assert ended.value.end_reason == "undelegated"
    assert (await signal.wait()).kind == "session_ended"
    with pytest.raises(PulseApiError) as refused:
        await client.create_on_issue("issue")
    assert refused.value.status == 503
    assert paths == ["/api/v1/agent-sessions/session/activities", "/api/v1/agent-sessions"]


async def test_api_does_not_follow_redirects_with_credentials(make_auth):
    visited = []

    def exchange(request):
        visited.append(request.url.host)
        return httpx.Response(307, headers={"Location": "https://elsewhere.test/oauth/token"})

    client = PulseAgentClient(await make_auth(exchange, existing=True), "install")
    with pytest.raises(PulseApiError) as refused:
        await client.create_on_issue("issue")
    assert refused.value.status == 307
    assert visited == ["api.trypulse.tech"]


async def test_session_activity_cursor_and_signal_shapes(make_auth):
    writes = []
    cursors = []

    def exchange(request):
        if request.method == "GET":
            after = request.url.params["after_seq"]
            cursors.append(after)
            seq = 7 if after == "0" else 21
            return httpx.Response(200, json={"data": [{"seq": seq}], "last_seq": seq, "has_more": seq == 7})
        writes.append((request.method, request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"id": "ok"})

    client = PulseAgentClient(await make_auth(exchange, existing=True), "install")
    assert [item["seq"] async for item in client.iter_activities("session")] == [7, 21]
    assert cursors == ["0", "7"]
    content = {"type": "elicitation", "body": "Next?"}
    await client.elicit("session", "Next?", select=[{"value": "continue", "label": "Continue"}])
    await client.elicit("session", "Next?", auth={"url": "https://example.test/connect", "user_id": "human"})
    await client.set_plan("session", [{"content": "Read the PRD", "status": "inProgress"}])
    await client.add_external_url("session", {"label": "Cyborg run", "url": "https://cyborg.test/run/1"})
    assert writes == [
        ("POST", "/api/v1/agent-sessions/session/activities", {
            "content": content, "signal": "select", "signal_metadata": {
                "options": [{"value": "continue", "label": "Continue"}],
            },
        }),
        ("POST", "/api/v1/agent-sessions/session/activities", {
            "content": content, "signal": "auth", "signal_metadata": {
                "url": "https://example.test/connect", "user_id": "human",
            },
        }),
        ("PATCH", "/api/v1/agent-sessions/session", {"plan": [{"content": "Read the PRD", "status": "inProgress"}]}),
        ("PATCH", "/api/v1/agent-sessions/session", {
            "added_external_urls": [{"label": "Cyborg run", "url": "https://cyborg.test/run/1"}],
        }),
    ]


async def test_revoked_api_response_forgets_grant_and_stops_work(make_auth):
    requests = []

    def exchange(request):
        requests.append(request)
        return httpx.Response(401, json={"code": "INSTALLATION_REVOKED"})

    auth = await make_auth(exchange, existing=True)
    raw, headers = signed_webhook()
    event = verify_webhook(raw, headers, "fixture-secret")
    stops = SessionStops()
    signal = stops.signal("session", "install")
    client = await PulseAgentClient.for_event(auth, event, stops=stops)
    with pytest.raises(InstallationRevokedError):
        await client.me()
    assert await auth.store.get_tokens("install") is None
    assert signal.cause is not None and signal.cause.kind == "revoked"
    assert len(requests) == 1


@pytest.mark.parametrize("different_identity", [False, True])
async def test_obsolete_revocation_checks_identity_and_keeps_activity_key(make_auth, different_identity):
    requests = []
    entered = asyncio.Event()
    proceed = asyncio.Event()

    async def exchange(request):
        requests.append(request)
        if request.headers["Authorization"] == "Bearer old-access":
            entered.set()
            await proceed.wait()
            return httpx.Response(401, json={"code": "INSTALLATION_REVOKED"})
        return httpx.Response(201, json={"id": "activity"})

    auth = await make_auth(exchange, existing=True)
    stops = SessionStops()
    signal = stops.signal("session", "install")
    client = PulseAgentClient(auth, "install", stops=stops)
    pending = asyncio.create_task(client.respond("session", "Done", idempotency_key="original-key"))
    await asyncio.wait_for(entered.wait(), timeout=1)
    async with auth.store.lock_installation("install"):
        record = await auth.installation("install")
        replacement = replace(
            record, access_token="new-access", refresh_token="new-refresh",
            app_user_id="other-app" if different_identity else record.app_user_id,
        )
        await auth.store.put_tokens(replacement)
    proceed.set()
    if different_identity:
        with pytest.raises(PermissionError):
            await pending
        assert len(requests) == 1
    else:
        assert await pending == {"id": "activity"}
        assert [request.headers["Authorization"] for request in requests] == ["Bearer old-access", "Bearer new-access"]
        assert [request.headers["Idempotency-Key"] for request in requests] == ["original-key"] * 2
        assert requests[0].content == requests[1].content
    assert await auth.installation("install") == replacement
    assert not signal.aborted


async def test_obsolete_revocation_recovery_is_bounded(make_auth):
    requests = []

    async def exchange(request):
        requests.append(request)
        async with auth.store.lock_installation("install"):
            record = await auth.installation("install")
            await auth.store.put_tokens(replace(record, access_token=f"replacement-{len(requests)}"))
        return httpx.Response(401, json={"code": "INSTALLATION_REVOKED"})

    auth = await make_auth(exchange, existing=True)
    stops = SessionStops()
    signal = stops.signal("session", "install")
    client = PulseAgentClient(auth, "install", stops=stops)
    with pytest.raises(PulseApiError, match="credential_replaced"):
        await client.me()
    assert [request.headers["Authorization"] for request in requests] == ["Bearer old-access", "Bearer replacement-1"]
    assert (await auth.installation("install")).access_token == "replacement-2"
    assert not signal.aborted


@pytest.mark.parametrize("terminal", ["ended", "revoked"])
async def test_scout_settles_terminal_inbox_rows_and_answers_healthy_once(make_auth, terminal):
    calls = []

    def exchange(request):
        path = request.url.path.removeprefix("/api/v1")
        calls.append(path)
        if "/terminal/" in path:
            if terminal == "ended":
                return httpx.Response(409, json={"code": "SESSION_ENDED"})
            return httpx.Response(401, json={"code": "INSTALLATION_REVOKED"})
        return httpx.Response(201, json={"id": "activity"})

    auth = await make_auth(exchange, existing=True)
    await auth.store.put_tokens(replace(await auth.installation("install"), installation_id="healthy"))
    raw, _ = signed_webhook()
    payload = json.loads(raw)
    with closing(sqlite3.connect(":memory:")) as db:
        inbox = scout.Inbox(db)
        payload["data"]["agent_session"]["id"] = "terminal"
        await inbox.enqueue(WebhookEvent.from_verified_payload(payload))
        payload["installation_id"] = "healthy"
        payload["data"]["agent_session"]["id"] = "healthy"
        await inbox.enqueue(WebhookEvent.from_verified_payload(payload))
        await inbox.drain(auth)
        await inbox.drain(auth)
        assert db.execute("SELECT processed FROM inbox ORDER BY id").fetchall() == [(1,), (1,)]
    assert calls == ["/agent-sessions/terminal/activities", "/agent-sessions/healthy/activities"]


async def test_scout_transient_failure_keeps_row_eligible_for_retry(make_auth):
    calls = []

    def exchange(request):
        calls.append(request.headers["Idempotency-Key"])
        if len(calls) == 1:
            return httpx.Response(503, headers={"Retry-After": "61"})
        return httpx.Response(201, json={"id": "activity"})

    auth = await make_auth(exchange, existing=True)
    with closing(sqlite3.connect(":memory:")) as db:
        inbox = scout.Inbox(db)
        await inbox.enqueue(verify_webhook(*signed_webhook(), "fixture-secret"))
        with pytest.raises(PulseApiError, match="HTTP_503"):
            await inbox.drain(auth)
        assert db.execute("SELECT processed FROM inbox").fetchone() == (0,)
        await inbox.drain(auth)
        assert db.execute("SELECT processed FROM inbox").fetchone() == (1,)
    assert len(calls) == 2 and calls[0] == calls[1]


async def test_oauth_rejects_refresh_without_rotation(make_auth):
    auth = await make_auth(lambda _: httpx.Response(200, json={
        "access_token": "access", "expires_in": 3600, "token_type": "Bearer", "actor": "app",
        "installation_id": "install", "workspace_id": "workspace", "app_user_id": "app-user",
    }), existing=True)
    with pytest.raises(OAuthError, match="invalid_response"):
        await auth.get_access_token("install", rejected_token="old-access")
    record = await auth.installation("install")
    assert record.refresh_token == "old-refresh"


async def test_callback_dedupe_scopes_ids_and_handles_resource_retries():
    seen = []
    payload = json.loads((FIXTURES / "resource-webhook.json").read_text(encoding="utf-8"))
    handler = WebhookHandler(
        "fixture-secret", on_data=lambda event: seen.append(event.dedupe_key),
        now_ms=lambda: 1_790_327_523_120,
    )
    for installation_id in ("one", "one", "two"):
        payload["installation_id"] = installation_id
        payload["webhook_timestamp"] += 1
        raw = json.dumps(payload).encode()
        headers = {"Pulse-Signature": hmac.digest(b"fixture-secret", raw, "sha256").hex()}
        assert handler.handle(raw, headers)[0] == 200
    await handler.idle()
    assert [key[0] for key in seen] == ["one", "two"]


def test_signed_webhook_rejects_non_json_numbers():
    raw, _ = signed_webhook()
    raw = raw.replace(b'"actor": null', b'"actor": NaN')
    headers = {"Pulse-Signature": hmac.digest(b"fixture-secret", raw, "sha256").hex()}
    with pytest.raises(WebhookError, match="invalid_json"):
        verify_webhook(raw, headers, "fixture-secret")


async def test_expired_and_declined_install_state_is_single_use(make_auth):
    auth = await make_auth(lambda _: pytest.fail("no token exchange expected"))
    clock = [100.0]
    auth = AgentAppAuth(
        CONFIG, auth.http, MemoryAuthStore(now=lambda: clock[0]), now=lambda: clock[0], state_ttl=10,
    )
    expired = parse_qs(urlsplit(await auth.start_install()).query)["state"][0]
    clock[0] += 10
    with pytest.raises(OAuthError, match="invalid_state"):
        await auth.complete_install(state=expired, code="code")
    declined = parse_qs(urlsplit(await auth.start_install()).query)["state"][0]
    with pytest.raises(OAuthError, match="install_declined"):
        await auth.complete_install(state=declined, code=None, error="access_denied")
    with pytest.raises(OAuthError, match="invalid_state"):
        await auth.complete_install(state=declined, code="code")


async def test_cancelled_install_finishes_storage_and_drains(make_auth):
    entered = asyncio.Event()
    finish = asyncio.Event()

    async def exchange(_):
        entered.set()
        await finish.wait()
        return token_response()

    auth = await make_auth(exchange)
    state = parse_qs(urlsplit(await auth.start_install()).query)["state"][0]
    callback = asyncio.create_task(auth.complete_install(state=state, code="code"))
    await asyncio.wait_for(entered.wait(), timeout=1)
    callback.cancel()
    with pytest.raises(asyncio.CancelledError):
        await callback
    finish.set()
    await asyncio.wait_for(auth.drain(), timeout=1)
    assert (await auth.installation("install")).access_token == "new-access"


async def test_revoke_uses_form_without_basic_credentials(make_auth):
    def exchange(request):
        assert request.method == "POST" and request.url.path == "/api/v1/oauth/revoke"
        assert "Authorization" not in request.headers
        assert parse_qs(request.content.decode()) == {
            "client_id": ["client"], "token": ["mock-token"], "token_type_hint": ["refresh_token"],
        }
        return httpx.Response(200)

    auth = await make_auth(exchange)
    await auth.revoke_token("mock-token", token_type_hint="refresh_token")


async def test_permission_and_revocation_callbacks_and_stop_resume():
    seen = []
    stops = SessionStops()
    signal = stops.signal("session", "install")
    handler = WebhookHandler(
        "fixture-secret", workspace_id="workspace", stops=stops,
        on_permission_change=lambda event: seen.append(event.permission_change),
        on_revoked=lambda event: seen.append(event.revocation),
    )
    raw, _ = signed_webhook()
    prompted = json.loads(raw)
    assert handler.handle(*sign(prompted))[0] == 200
    await handler.idle()
    assert signal.aborted
    prompted["data"]["event_id"] = "human"
    prompted["data"]["agent_activity"].pop("signal")
    prompted["created_at"] = "2026-11-24T08:00:01.000Z"
    assert handler.handle(*sign(prompted))[0] == 200
    await handler.idle()
    next_signal = stops.signal("session")
    assert next_signal is not signal and not next_signal.aborted
    permission = {
        "event_id": "permission", "installation_id": "install", "all_teams": False,
        "team_ids": ["remaining"], "added_team_ids": [], "removed_team_ids": ["removed"],
    }
    revocation = {"event_id": "revoked", "installation_id": "install", "app_id": "app"}
    revoked = {**prompted, "type": "OAuthApp", "action": "revoked", "data": revocation}
    changed = {**prompted, "type": "PermissionChange", "action": "teamAccessChanged", "data": permission}
    assert handler.handle(*sign({**changed, "workspace_id": "other"}))[0] == 403
    assert handler.handle(*sign(changed))[0] == 200
    assert handler.handle(*sign(revoked))[0] == 200
    await handler.idle()
    assert seen == [permission, revocation]
    assert (await next_signal.wait()).kind == "revoked"
    assert verify_webhook(*sign(revoked), "fixture-secret").is_revoked
    with pytest.raises(WebhookError, match="invalid_event"):
        verify_webhook(*sign({**changed, "installation_id": "other"}), "fixture-secret")


def test_verified_payload_can_be_restored_and_duplicate_signatures_are_rejected():
    raw, headers = signed_webhook()
    event = verify_webhook(raw, headers, "fixture-secret")
    assert WebhookEvent.from_verified_payload(json.loads(json.dumps(event.payload))) == event
    headers = httpx.Headers([
        ("Pulse-Signature", headers["Pulse-Signature"]), ("Pulse-Signature", headers["Pulse-Signature"]),
    ])
    with pytest.raises(WebhookError, match="bad_signature"):
        verify_webhook(raw, headers, "fixture-secret")


def test_resource_key_matches_typescript_number_and_unicode_rendering():
    raw, headers = sign({
        "type": "Issue", "action": "update", "workspace_id": "workspace",
        "installation_id": "install", "app_user_id": "app-user", "webhook_timestamp": 1_790_327_523_120,
        "data": {"\ue000": -0.0, "😀": [1.0, 0.000001, 1e-7, 1e20, 9_007_199_254_740_993], "old": "\ud800"},
    })
    event = verify_webhook(raw, headers, "fixture-secret", now_ms=lambda: 1_790_327_523_120)
    assert event.dedupe_key == ("install", "body:a8ba9beb0adfc735e54e2649f9099364eb74f7bce66f235c7d3818bb3fbda0d7")


async def test_session_and_issue_operations_use_pinned_routes(make_auth):
    requests = []

    def exchange(request):
        suffix = request.url.path.removeprefix("/api/v1")
        body = json.loads(request.content) if request.content else None
        requests.append((request.method, suffix, body))
        assert request.headers["Authorization"] == "Bearer old-access"
        assert request.headers["X-Workspace-ID"] == "workspace"
        if request.method == "GET" and suffix == "/agent-sessions":
            assert request.url.params.get_list("state") == ["active", "awaitingInput"]
            assert request.url.params["issue_id"] == "issue"
            assert request.url.params["limit"] == "2"
            if request.url.params.get("cursor") == "opaque+next":
                return httpx.Response(200, json={"data": [{"id": "second"}], "next_cursor": None})
            return httpx.Response(200, json={"data": [{"id": "first"}], "next_cursor": "opaque+next"})
        if suffix == "/agent-sessions/session/activities":
            assert not request.url.query
            return httpx.Response(200, json={"data": [], "has_more": False, "last_seq": 0})
        return httpx.Response(200, json={"id": "ok"})

    client = PulseAgentClient(await make_auth(exchange, existing=True), "install")
    items = [item["id"] async for item in client.iter_sessions(
        issue_id="issue", state=["active", "awaitingInput"], limit=2,
    )]
    assert items == ["first", "second"]
    await client.get_session("session")
    await client.activity_page("session")
    await client.create_on_issue("issue")
    await client.create_on_comment("comment")
    await client.set_external_urls("session", [{"label": "Example", "url": "https://scout.test"}])
    await client.remove_external_url("session", "https://scout.test")
    await client.get_issue("issue")
    await client.update_issue_status("issue", "qa")
    await client.me()
    assert requests[2:] == [
        ("GET", "/agent-sessions/session", None),
        ("GET", "/agent-sessions/session/activities", None),
        ("POST", "/agent-sessions", {"issue_id": "issue"}),
        ("POST", "/agent-sessions", {"comment_id": "comment"}),
        ("PATCH", "/agent-sessions/session", {"external_urls": [{"label": "Example", "url": "https://scout.test"}]}),
        ("PATCH", "/agent-sessions/session", {"removed_external_urls": ["https://scout.test"]}),
        ("GET", "/issues/issue", None),
        ("PUT", "/issues/issue", {"status": "qa"}),
        ("GET", "/auth/me", None),
    ]


@pytest.mark.parametrize(("path", "page", "error"), [
    ("sessions", {"data": [], "next_cursor": "same"}, "invalid_session_cursor"),
    ("activities", {"data": [], "has_more": True, "last_seq": 7}, "invalid_activity_cursor"),
    ("activities", {"data": [], "has_more": "yes", "last_seq": 7}, "invalid_response"),
])
async def test_iterators_reject_nonprogress_and_invalid_pages(make_auth, path, page, error):
    client = PulseAgentClient(await make_auth(lambda _: httpx.Response(200, json=page), existing=True), "install")
    iterator = client.iter_sessions(cursor="same") if path == "sessions" else client.iter_activities("session", after_seq=7)
    with pytest.raises(PulseApiError, match=error):
        await anext(iterator)


async def test_activity_helpers_send_expected_ephemeral_action_and_error(make_auth):
    writes = []

    def exchange(request):
        writes.append((request.headers["Idempotency-Key"], json.loads(request.content)))
        return httpx.Response(201, json={"id": "activity"})

    client = PulseAgentClient(await make_auth(exchange, existing=True), "install")
    await client.thought("session", "Thinking", ephemeral=True)
    await client.action("session", "Read", ephemeral=True)
    await client.action("session", "Read", parameter="issue", result="Found")
    await client.error("session", "Could not read")
    keys, bodies = zip(*writes, strict=True)
    assert len(set(keys)) == 4 and all(1 <= len(key) <= 64 for key in keys)
    assert bodies == (
        {"content": {"type": "thought", "body": "Thinking"}, "ephemeral": True},
        {"content": {"type": "action", "action": "Read", "parameter": None}, "ephemeral": True},
        {"content": {"type": "action", "action": "Read", "parameter": "issue", "result": "Found"}},
        {"content": {"type": "error", "body": "Could not read"}},
    )


async def test_retries_classify_transport_and_preserve_redacted_error_details(make_auth):
    calls = 0
    delays = []

    def exchange(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("sensitive transport message", request=request)
        if calls == 2:
            return httpx.Response(408)
        return httpx.Response(429, headers={"Retry-After": "61"}, json={
            "code": "RATE_LIMIT_EXCEEDED", "message": "sensitive message", "details": {"limit": 10},
        })

    async def sleep(delay):
        delays.append(delay)

    client = PulseAgentClient(await make_auth(exchange, existing=True), "install", sleep=sleep)
    with pytest.raises(PulseApiError) as error:
        await client.create_on_comment("comment")
    assert (error.value.status, error.value.code, error.value.retry_after) == (429, "RATE_LIMIT_EXCEEDED", 61)
    assert error.value.details == {"limit": 10}
    assert "sensitive" not in str(error.value)
    assert calls == 3 and len(delays) == 2 and all(0 < delay <= 0.5 for delay in delays)

    def timeout(request):
        raise httpx.ReadTimeout("sensitive transport message", request=request)

    client = PulseAgentClient(await make_auth(timeout, existing=True), "install", max_retries=0)
    with pytest.raises(PulseTransportError) as error:
        await client.me()
    assert error.value.timed_out and "sensitive" not in str(error.value)


async def test_cancellation_during_backoff_stops_further_requests(make_auth):
    sleeping = asyncio.Event()
    calls = 0

    def exchange(_):
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    async def sleep(_):
        sleeping.set()
        await asyncio.Future()

    client = PulseAgentClient(await make_auth(exchange, existing=True), "install", sleep=sleep)
    task = asyncio.create_task(client.me())
    await asyncio.wait_for(sleeping.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls == 1


async def test_retry_after_http_date_and_second_401_are_bounded(make_auth, monkeypatch):
    calls = []
    delays = []
    now = 1_790_327_523
    monkeypatch.setattr("pulse_agent_sdk.client.time", SimpleNamespace(time=lambda: now))

    def exchange(request):
        if request.url.path.endswith("/oauth/token"):
            return token_response()
        calls.append(request.headers["Authorization"])
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": formatdate(now + 12, usegmt=True)})
        return httpx.Response(401, json={"code": "UNAUTHORIZED"})

    async def sleep(delay):
        delays.append(delay)

    client = PulseAgentClient(await make_auth(exchange, existing=True), "install", max_retries=1, sleep=sleep)
    with pytest.raises(PulseApiError, match="UNAUTHORIZED"):
        await client.me()
    assert delays == [12]
    assert calls == ["Bearer old-access", "Bearer old-access", "Bearer new-access"]
