"""Pulse Agent Session API calls as the installation's app user."""

from __future__ import annotations

import asyncio
import json
import math
import random
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from email.utils import parsedate_to_datetime
from typing import Literal, cast
from urllib.parse import quote
from uuid import uuid4

import httpx

from ._generated import (
    ActionContent,
    AgentActivity,
    AgentActivityCreate,
    AgentActivityPage,
    AgentSession,
    AgentSessionPage,
    AgentSessionState,
    AuthSignal,
    ExternalUrl,
    PlanItem,
    SelectOption,
    SessionUpdate,
)
from ._generated_api import Issue, MeResponse
from .errors import (
    InstallationRevokedError,
    PulseApiError,
    PulseTransportError,
    SessionEndedError,
)
from .oauth import AgentAppAuth
from .stop import SessionStops
from .webhooks import WebhookEvent

MAX_IDEMPOTENCY_KEY_LENGTH = 64
AppIssueStatus = Literal["in_progress", "qa"]


def _id(value: str) -> str:
    if not value.strip() or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError("Expected a Pulse resource ID")
    return quote(value, safe="")


def _session_path(session_id: str) -> str:
    return f"/agent-sessions/{_id(session_id)}"


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    if value.isascii() and value.isdigit() and len(value) <= 10:
        return float(value)
    try:
        return max(0, parsedate_to_datetime(value).timestamp() - time.time())
    except (ValueError, TypeError, OverflowError, OSError):
        return None


class PulseAgentClient:
    """Async, installation-scoped client sharing its auth manager's connection pool."""

    def __init__(
        self,
        auth: AgentAppAuth,
        installation_id: str,
        *,
        max_retries: int = 3,
        retry_base: float = 0.25,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        stops: SessionStops | None = None,
    ) -> None:
        if not installation_id or not 0 <= max_retries <= 10:
            raise ValueError("An installation ID and a retry count from 0 to 10 are required")
        if not math.isfinite(retry_base) or retry_base < 0:
            raise ValueError("Retry base must be finite and nonnegative")
        self._auth = auth
        self._installation_id = installation_id
        self._max_retries = max_retries
        self._retry_base = retry_base
        self._sleep = sleep
        self._stops = stops
        self._identity: tuple[str, str, str] | None = None

    @classmethod
    async def for_event(
        cls,
        auth: AgentAppAuth,
        event: WebhookEvent,
        *,
        max_retries: int = 3,
        retry_base: float = 0.25,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        stops: SessionStops | None = None,
    ) -> PulseAgentClient:
        """Bind a verified event to the matching active installation before making API calls."""
        if event.installation_id is None or event.is_revoked:
            raise PermissionError("This Pulse event does not authorize an app client")
        installation = await auth.installation(event.installation_id)
        if (installation.workspace_id, installation.app_user_id) != (event.workspace_id, event.app_user_id):
            raise PermissionError("Pulse event does not match the active installation")
        if stops is not None and event.session_id is not None:
            stops.signal(event.session_id, installation.installation_id)
        client = cls(
            auth, installation.installation_id,
            max_retries=max_retries, retry_base=retry_base, sleep=sleep, stops=stops,
        )
        client._identity = installation._identity
        return client

    async def get_session(self, session_id: str) -> AgentSession:
        return cast(AgentSession, await self._request("GET", _session_path(session_id)))

    async def list_sessions(
        self,
        *,
        issue_id: str | None = None,
        state: AgentSessionState | Sequence[AgentSessionState] | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> AgentSessionPage:
        filters = (("issue_id", issue_id), ("cursor", cursor), ("limit", limit))
        params = [(key, str(value)) for key, value in filters if value is not None]
        states = [state] if isinstance(state, str) else state or ()
        params.extend(("state", item) for item in states)
        return cast(AgentSessionPage, await self._request("GET", "/agent-sessions", params=params))

    async def iter_sessions(
        self,
        *,
        issue_id: str | None = None,
        state: AgentSessionState | Sequence[AgentSessionState] | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[AgentSession]:
        """Yield sessions in server order, following each opaque cursor."""
        seen = {cursor}
        while True:
            page = await self.list_sessions(issue_id=issue_id, state=state, cursor=cursor, limit=limit)
            items = page.get("data")
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise PulseApiError(200, "invalid_response")
            next_cursor = page.get("next_cursor")
            if "next_cursor" not in page or (
                next_cursor is not None
                and (not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen)
            ):
                raise PulseApiError(200, "invalid_session_cursor")
            for item in items:
                yield item
            if next_cursor is None:
                return
            seen.add(next_cursor)
            cursor = next_cursor

    async def activity_page(
        self, session_id: str, *, after_seq: int | None = None, limit: int | None = None,
    ) -> AgentActivityPage:
        filters = (("after_seq", after_seq), ("limit", limit))
        return cast(AgentActivityPage, await self._request(
            "GET", f"{_session_path(session_id)}/activities",
            params=[(key, str(value)) for key, value in filters if value is not None],
        ))

    async def iter_activities(self, session_id: str, *, after_seq: int = 0) -> AsyncIterator[AgentActivity]:
        """Page by Pulse's last sequence. Activity sequence numbers can have gaps."""
        while True:
            page = await self.activity_page(session_id, after_seq=after_seq, limit=200)
            items = page.get("data")
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise PulseApiError(200, "invalid_response")
            has_more = page.get("has_more")
            if type(has_more) is not bool:
                raise PulseApiError(200, "invalid_response")
            next_seq = page.get("last_seq")
            if type(next_seq) is not int or next_seq < after_seq or (has_more and next_seq == after_seq):
                raise PulseApiError(200, "invalid_activity_cursor")
            for item in items:
                yield item
            if not has_more:
                return
            after_seq = next_seq

    async def create_on_issue(self, issue_id: str) -> AgentSession:
        """Create a proactive session. An ambiguous create cannot be safely retried."""
        return cast(AgentSession, await self._request("POST", "/agent-sessions", body={"issue_id": issue_id}))

    async def create_on_comment(self, comment_id: str) -> AgentSession:
        """Pulse reuses an existing open session on the comment thread."""
        return cast(AgentSession, await self._request(
            "POST", "/agent-sessions", body={"comment_id": comment_id}, retryable=True,
        ))

    async def update_session(self, session_id: str, update: SessionUpdate) -> AgentSession:
        return cast(AgentSession, await self._request(
            "PATCH", _session_path(session_id), body=dict(update), session_id=session_id,
        ))

    async def set_plan(self, session_id: str, plan: list[PlanItem]) -> AgentSession:
        return await self.update_session(session_id, {"plan": plan})

    async def set_external_urls(self, session_id: str, urls: list[ExternalUrl]) -> AgentSession:
        return await self.update_session(session_id, {"external_urls": urls})

    async def add_external_url(self, session_id: str, url: ExternalUrl) -> AgentSession:
        return await self.update_session(session_id, {"added_external_urls": [url]})

    async def remove_external_url(self, session_id: str, url: str) -> AgentSession:
        return await self.update_session(session_id, {"removed_external_urls": [url]})

    async def create_activity(
        self,
        session_id: str,
        activity: AgentActivityCreate,
        *,
        idempotency_key: str | None = None,
    ) -> AgentActivity:
        key = self.new_idempotency_key() if idempotency_key is None else idempotency_key
        if (
            not 1 <= len(key) <= MAX_IDEMPOTENCY_KEY_LENGTH
            or not key.isascii() or not key.isprintable() or key != key.strip()
        ):
            raise ValueError("Idempotency-Key must contain 1–64 printable ASCII characters without surrounding spaces")
        return cast(AgentActivity, await self._request(
            "POST", f"{_session_path(session_id)}/activities", body=dict(activity),
            idempotency_key=key, session_id=session_id, retryable=True,
        ))

    @staticmethod
    def new_idempotency_key() -> str:
        """Generate a key to persist with work that can be replayed."""
        return f"pulse-py-{uuid4().hex}"

    async def thought(
        self, session_id: str, body: str, *, ephemeral: bool = False, idempotency_key: str | None = None,
    ) -> AgentActivity:
        activity: AgentActivityCreate = {"content": {"type": "thought", "body": body}}
        if ephemeral:
            activity["ephemeral"] = True
        return await self.create_activity(session_id, activity, idempotency_key=idempotency_key)

    async def action(
        self,
        session_id: str,
        action: str,
        *,
        parameter: str | None = None,
        result: str | None = None,
        ephemeral: bool = False,
        idempotency_key: str | None = None,
    ) -> AgentActivity:
        content: ActionContent = {"type": "action", "action": action, "parameter": parameter}
        if result is not None:
            content["result"] = result
        activity: AgentActivityCreate = {"content": content}
        if ephemeral:
            activity["ephemeral"] = True
        return await self.create_activity(session_id, activity, idempotency_key=idempotency_key)

    async def elicit(
        self,
        session_id: str,
        body: str,
        *,
        select: list[SelectOption] | None = None,
        auth: AuthSignal | None = None,
        idempotency_key: str | None = None,
    ) -> AgentActivity:
        if select is not None and auth is not None:
            raise ValueError("Choose one of select and auth")
        activity: AgentActivityCreate = {"content": {"type": "elicitation", "body": body}}
        if select is not None:
            activity["signal"] = "select"
            activity["signal_metadata"] = {"options": select}
        if auth is not None:
            activity["signal"] = "auth"
            activity["signal_metadata"] = auth
        return await self.create_activity(session_id, activity, idempotency_key=idempotency_key)

    async def respond(
        self, session_id: str, body: str, *, idempotency_key: str | None = None,
    ) -> AgentActivity:
        return await self.create_activity(
            session_id, {"content": {"type": "response", "body": body}}, idempotency_key=idempotency_key,
        )

    async def error(self, session_id: str, body: str, *, idempotency_key: str | None = None) -> AgentActivity:
        return await self.create_activity(
            session_id, {"content": {"type": "error", "body": body}}, idempotency_key=idempotency_key,
        )

    async def me(self) -> MeResponse:
        return cast(MeResponse, await self._request("GET", "/auth/me"))

    async def get_issue(self, issue_id: str) -> Issue:
        return cast(Issue, await self._request("GET", f"/issues/{_id(issue_id)}"))

    async def update_issue_status(self, issue_id: str, status: AppIssueStatus) -> Issue:
        if status not in {"in_progress", "qa"}:
            raise ValueError("An agent app may set in_progress or qa")
        return cast(Issue, await self._request("PUT", f"/issues/{_id(issue_id)}", body={"status": status}))

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, object] | None = None,
        params: list[tuple[str, str]] | None = None,
        idempotency_key: str | None = None,
        session_id: str | None = None,
        retryable: bool = False,
    ) -> dict[str, object]:
        config = self._auth.config
        url = f"{config.base_url}{path}"
        headers = {"Accept": "application/json", "X-Workspace-ID": config.workspace_id}
        content = None
        if body is not None:
            content = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        retryable = retryable or method != "POST"
        auth_retried = False
        identity = self._identity
        rejected_token = None
        query = httpx.QueryParams(tuple(params or ()))
        retries = 0
        while True:
            try:
                credential = await self._auth._get_access_record(
                    self._installation_id, rejected_token=rejected_token, identity=identity,
                )
            except InstallationRevokedError:
                if self._stops is not None:
                    self._stops.stop_installation(self._installation_id)
                raise
            identity = credential._identity
            token = credential.access_token
            rejected_token = None
            headers["Authorization"] = f"Bearer {token}"
            try:
                response = await self._auth.http.request(
                    method, url, params=query, content=content, headers=headers, auth=None, follow_redirects=False,
                )
            except httpx.RequestError as exc:
                if not retryable or retries >= self._max_retries:
                    raise PulseTransportError(timed_out=isinstance(exc, httpx.TimeoutException)) from None
                await self._sleep(self._backoff(retries))
                retries += 1
                continue
            payload = self._payload(response)
            status = response.status_code
            if response.is_success:
                if payload is None:
                    raise PulseApiError(status, "invalid_response")
                return payload

            raw_code = (payload or {}).get("code")
            code = (
                raw_code
                if (
                    isinstance(raw_code, str) and len(raw_code) <= 64
                    and raw_code.isascii() and raw_code.isidentifier()
                    and raw_code not in {token, config.client_secret}
                )
                else f"HTTP_{status}"
            )
            raw_details = (payload or {}).get("details")
            details = cast(dict[str, object], raw_details) if isinstance(raw_details, dict) else None
            if status == 409 and code == "SESSION_ENDED" and session_id is not None:
                reason = details.get("end_reason") if details is not None else None
                ended = SessionEndedError(session_id, reason if isinstance(reason, str) else None, details=details)
                if self._stops is not None:
                    self._stops.note_session_ended(ended)
                raise ended
            if status == 401 and code == "INSTALLATION_REVOKED":
                try:
                    await self._auth._check_revoked_credential(credential)
                except InstallationRevokedError:
                    if self._stops is not None:
                        self._stops.stop_installation(self._installation_id)
                    raise
                if auth_retried:
                    raise PulseApiError(status, "credential_replaced")
            if status == 401 and not auth_retried:
                rejected_token = token
                auth_retried = True
                continue

            delay = _retry_after(response)
            is_transient = status == 408 or (500 <= status <= 599 and status != 501)
            can_retry = status == 429 or (retryable and is_transient)
            if retries >= self._max_retries or not can_retry or (delay is not None and delay > 60):
                raise PulseApiError(status, code, retry_after=delay, details=details)
            await self._sleep(delay if delay is not None else self._backoff(retries))
            retries += 1

    def _backoff(self, attempt: int) -> float:
        return min(30.0, self._retry_base * (1 << attempt)) * random.uniform(0.5, 1.0)

    @staticmethod
    def _payload(response: httpx.Response) -> dict[str, object] | None:
        try:
            payload = response.json()
        except (ValueError, RecursionError):
            return None
        return payload if isinstance(payload, dict) else None
