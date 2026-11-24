"""Pulse Agent App OAuth and rotating installation credentials."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import math
import secrets
import time
from collections.abc import Callable, Coroutine, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field, replace
from typing import Any, Protocol, TypeVar
from urllib.parse import urlencode, urlsplit
from weakref import WeakValueDictionary

import httpx

from .errors import InstallationRevokedError, InstallSecretError, OAuthError

DEFAULT_BASE_URL = "https://api.trypulse.tech/api/v1"
DEFAULT_APP_SCOPES = ("read", "write", "app:assignable", "app:mentionable")
_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class OAuthConfig:
    client_id: str
    client_secret: str = field(repr=False)
    redirect_uri: str = field(repr=False)
    workspace_id: str
    base_url: str = DEFAULT_BASE_URL

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (
            self.client_id, self.client_secret, self.redirect_uri, self.workspace_id,
        )):
            raise ValueError("Pulse client credentials, redirect URI and workspace are required")
        if ":" in self.client_id:
            raise ValueError("Pulse client ID must not contain a colon")
        _validate_url(self.base_url, "Pulse base URL", allow_query=False)
        _validate_url(self.redirect_uri, "Pulse redirect URI", allow_query=True)
        object.__setattr__(self, "base_url", self.base_url.rstrip("/"))


def _validate_url(value: str, label: str, *, allow_query: bool) -> None:
    message = f"{label} must be HTTPS or loopback HTTP, without credentials or fragments"
    try:
        url = urlsplit(value)
        port = url.port
    except ValueError:
        raise ValueError(message) from None
    loopback = url.hostname in {"localhost", "127.0.0.1", "::1"}
    secure = url.scheme == "https" or (url.scheme == "http" and loopback)
    if (
        not secure or not url.hostname or port == 0 or url.username is not None
        or "#" in value or (not allow_query and "?" in value)
        or any(char.isspace() or ord(char) < 32 or char == "\\" for char in value)
    ):
        raise ValueError(message)


@dataclass(frozen=True, slots=True)
class InstallationTokens:
    installation_id: str
    workspace_id: str
    app_user_id: str
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_at: float  # Unix seconds.
    scope: str = ""


@dataclass(frozen=True, slots=True)
class PendingInstall:
    code_verifier: str = field(repr=False)
    expires_at: float


class AuthStore(Protocol):
    """Persistence port. Token writes and OAuth-state consumption must be atomic."""

    def lock_installation(self, installation_id: str) -> AbstractAsyncContextManager[None]:
        """Serialize token exchange, persistence and removal across all workers."""
        ...

    async def get_tokens(self, installation_id: str) -> InstallationTokens | None: ...

    async def put_tokens(self, tokens: InstallationTokens) -> None: ...

    async def delete_tokens(self, installation_id: str) -> None: ...

    async def put_state(self, state: str, pending: PendingInstall) -> None: ...

    async def consume_state(self, state: str) -> PendingInstall | None: ...


class MemoryAuthStore:
    """Process-local storage for fixtures and single-process examples."""

    def __init__(self, *, now: Callable[[], float] = time.time) -> None:
        self._now = now
        self._tokens: dict[str, InstallationTokens] = {}
        self._states: dict[str, PendingInstall] = {}
        self._locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

    def lock_installation(self, installation_id: str) -> asyncio.Lock:
        return self._locks.setdefault(installation_id, asyncio.Lock())

    async def get_tokens(self, installation_id: str) -> InstallationTokens | None:
        return self._tokens.get(installation_id)

    async def put_tokens(self, tokens: InstallationTokens) -> None:
        self._tokens[tokens.installation_id] = tokens

    async def delete_tokens(self, installation_id: str) -> None:
        self._tokens.pop(installation_id, None)

    async def put_state(self, state: str, pending: PendingInstall) -> None:
        now = self._now()
        self._states = {key: item for key, item in self._states.items() if item.expires_at > now}
        self._states[state] = pending

    async def consume_state(self, state: str) -> PendingInstall | None:
        return self._states.pop(state, None)


class AgentAppAuth:
    """An app registration backed by an application-owned HTTP client and store."""

    def __init__(
        self,
        config: OAuthConfig,
        http: httpx.AsyncClient,
        store: AuthStore,
        *,
        now: Callable[[], float] = time.time,
        refresh_window: float = 300,
        state_ttl: float = 600,
        install_secret: str | None = None,
    ) -> None:
        if not math.isfinite(refresh_window) or refresh_window < 0 or not math.isfinite(state_ttl) or state_ttl <= 0:
            raise ValueError("OAuth timing options must be finite and nonnegative, with a positive state TTL")
        if install_secret is not None and not install_secret.strip():
            raise ValueError("Install secret must be nonempty")
        self.config = config
        self.http = http
        self.store = store
        self._now = now
        self._refresh_window = refresh_window
        self._state_ttl = state_ttl
        self._install_secret = install_secret
        self._credential_tasks: set[asyncio.Task[Any]] = set()
        self._refreshing: dict[InstallationTokens, asyncio.Task[InstallationTokens]] = {}

    async def start_install(
        self, provided_secret: str | None = None, *, scopes: Sequence[str] = DEFAULT_APP_SCOPES,
    ) -> str:
        """Start an install after the calling application has authorized the requester."""
        if self._install_secret is not None and (
            not provided_secret
            or not secrets.compare_digest(provided_secret.encode(), self._install_secret.encode())
        ):
            raise InstallSecretError()
        if not scopes or isinstance(scopes, str) or any(not scope.strip() for scope in scopes):
            raise ValueError("At least one app scope is required")
        verifier = secrets.token_urlsafe(32)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(24)
        await self.store.put_state(state, PendingInstall(verifier, self._now() + self._state_ttl))
        query = urlencode({
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "response_type": "code",
            "actor": "app",
            "scope": ",".join(scopes),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })
        return f"{self.config.base_url}/oauth/authorize?{query}"

    async def complete_install(
        self, *, state: str | None, code: str | None, error: str | None = None,
    ) -> InstallationTokens:
        if not state:
            raise OAuthError(400, "invalid_state")
        pending = await self.store.consume_state(state)
        if pending is None or pending.expires_at <= self._now():
            raise OAuthError(400, "invalid_state")
        if error:
            raise OAuthError(400, "install_declined")
        if not code:
            raise OAuthError(400, "invalid_request")
        return await asyncio.shield(self._start(self._install(code, pending)))

    async def _install(self, code: str, pending: PendingInstall) -> InstallationTokens:
        payload = await self._exchange({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.config.redirect_uri,
            "code_verifier": pending.code_verifier,
        })
        record = self._record(payload)
        async with self.store.lock_installation(record.installation_id):
            await self.store.put_tokens(record)
        return record

    async def get_access_token(self, installation_id: str, *, rejected_token: str | None = None) -> str:
        record = await self._record_for_installation(installation_id)
        if self._usable(record, rejected_token):
            return record.access_token

        # Pulse can rotate the token before we receive the response. A cancelled API
        # call must still let this task finish persisting the new credential pair.
        task = self._refreshing.get(record)
        if task is None:
            task = self._start(self._refresh(record, rejected_token))
            self._refreshing[record] = task
            task.add_done_callback(lambda _: self._refreshing.pop(record, None))
        refreshed = await asyncio.shield(task)
        return refreshed.access_token

    async def drain(self) -> None:
        """Wait for outstanding credential operations before closing the HTTP client."""
        while self._credential_tasks:
            await asyncio.wait(tuple(self._credential_tasks))

    async def forget_installation(self, installation_id: str) -> None:
        """Discard the local grant following an authenticated uninstall event."""
        async with self.store.lock_installation(installation_id):
            record = await self.store.get_tokens(installation_id)
            if record is not None and record.workspace_id == self.config.workspace_id:
                await self.store.delete_tokens(installation_id)

    async def expire_access_token(self, installation_id: str) -> None:
        """Force the next call to rotate credentials while keeping the refresh token."""
        async with self.store.lock_installation(installation_id):
            record = await self.store.get_tokens(installation_id)
            if record is not None and record.workspace_id == self.config.workspace_id:
                await self.store.put_tokens(replace(record, expires_at=0))

    async def _forget_rejected_token(self, installation_id: str, rejected_token: str) -> bool:
        async with self.store.lock_installation(installation_id):
            record = await self.store.get_tokens(installation_id)
            if (
                record is not None and record.workspace_id == self.config.workspace_id
                and record.access_token == rejected_token
            ):
                await self.store.delete_tokens(installation_id)
                return True
            return False

    async def installation(self, installation_id: str) -> InstallationTokens:
        """Get the stored installation identity and token record for this workspace."""
        return await self._record_for_installation(installation_id)

    async def revoke_token(self, token: str, *, token_type_hint: str | None = None) -> None:
        """Call Pulse's OAuth revocation endpoint for a token held by this app."""
        form = {"client_id": self.config.client_id, "token": token}
        if token_type_hint is not None:
            form["token_type_hint"] = token_type_hint
        try:
            response = await self.http.request(
                "POST",
                f"{self.config.base_url}/oauth/revoke",
                data=form,
                auth=None,
                follow_redirects=False,
            )
        except httpx.RequestError:
            raise OAuthError(0, "transport_error") from None
        if not response.is_success:
            raise OAuthError(response.status_code, "revoke_failed")

    def _start(self, operation: Coroutine[Any, Any, _T]) -> asyncio.Task[_T]:
        task = asyncio.create_task(operation)
        self._credential_tasks.add(task)
        task.add_done_callback(self._finished)
        return task

    def _finished(self, task: asyncio.Task[Any]) -> None:
        self._credential_tasks.discard(task)
        if not task.cancelled():
            task.exception()

    async def _record_for_installation(self, installation_id: str) -> InstallationTokens:
        record = await self.store.get_tokens(installation_id)
        if record is None or record.workspace_id != self.config.workspace_id or record.installation_id != installation_id:
            raise InstallationRevokedError(installation_id)
        return record

    def _usable(self, record: InstallationTokens, rejected_token: str | None) -> bool:
        if rejected_token is not None:
            return record.access_token != rejected_token and record.expires_at > self._now()
        return record.expires_at - self._now() > self._refresh_window

    async def _refresh(
        self, observed: InstallationTokens, rejected_token: str | None,
    ) -> InstallationTokens:
        installation_id = observed.installation_id
        async with self.store.lock_installation(installation_id):
            record = await self._record_for_installation(installation_id)
            if self._usable(record, rejected_token) or (record != observed and record.expires_at > self._now()):
                return record
            try:
                payload = await self._exchange({"grant_type": "refresh_token", "refresh_token": record.refresh_token})
            except OAuthError as exc:
                if exc.code != "invalid_grant":
                    raise
                await self.store.delete_tokens(installation_id)
                raise InstallationRevokedError(installation_id) from exc
            rotated = self._record(payload, previous=record)
            await self.store.put_tokens(rotated)
            return rotated

    async def _exchange(self, form: dict[str, str]) -> dict[str, Any]:
        try:
            response = await self.http.post(
                f"{self.config.base_url}/oauth/token",
                data=form,
                auth=httpx.BasicAuth(self.config.client_id, self.config.client_secret),
                headers={"Accept": "application/json"},
                follow_redirects=False,
            )
        except httpx.RequestError:
            raise OAuthError(0, "transport_error") from None
        try:
            payload = response.json()
        except (ValueError, RecursionError):
            payload = None
        if not response.is_success:
            error = payload.get("error") if isinstance(payload, dict) else None
            code = (
                error if (
                    isinstance(error, str) and len(error) <= 64 and error.isascii() and error.isidentifier()
                    and error != self.config.client_secret and error not in form.values()
                )
                else "oauth_error"
            )
            raise OAuthError(response.status_code, code)
        if not isinstance(payload, dict):
            raise OAuthError(response.status_code, "invalid_response")
        return payload

    def _record(self, payload: dict[str, Any], previous: InstallationTokens | None = None) -> InstallationTokens:
        def require_text(field: str, fallback: str = "") -> str:
            value = payload.get(field, fallback)
            if not isinstance(value, str) or not value.strip():
                raise OAuthError(200, "invalid_response")
            return value

        installation_id = require_text("installation_id")
        workspace_id = require_text("workspace_id")
        app_user_id = require_text("app_user_id")
        if payload.get("actor") != "app" or workspace_id != self.config.workspace_id:
            raise OAuthError(200, "installation_mismatch")
        if previous and (previous.installation_id != installation_id or previous.app_user_id != app_user_id):
            raise OAuthError(200, "installation_mismatch")
        expires_in = payload.get("expires_in")
        if type(expires_in) is not int or not 0 < expires_in <= 2**53 - 1:
            raise OAuthError(200, "invalid_response")
        access_token = require_text("access_token")
        refresh_token = require_text("refresh_token")
        if require_text("token_type").lower() != "bearer" or (previous and refresh_token == previous.refresh_token):
            raise OAuthError(200, "invalid_response")
        if not access_token.isascii() or not access_token.isprintable() or " " in access_token:
            raise OAuthError(200, "invalid_response")
        scope = payload.get("scope", previous.scope if previous else "")
        if not isinstance(scope, str):
            raise OAuthError(200, "invalid_response")
        return InstallationTokens(
            installation_id=installation_id,
            workspace_id=workspace_id,
            app_user_id=app_user_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=self._now() + expires_in,
            scope=scope,
        )
