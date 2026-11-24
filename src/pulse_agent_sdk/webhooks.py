"""Pulse Agent App webhook verification and intake."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, NoReturn, cast

from ._generated import AgentSession
from ._generated_api import (
    AgentSessionEventCreatedData,
    AgentSessionEventPromptedData,
    AppWebhookEnvelope,
    OAuthAppRevokedData,
    PermissionChangeData,
)
from .errors import WebhookError

_SIGNATURE = re.compile(r"[0-9a-f]{64}")
DEFAULT_TOLERANCE_MS = 60_000
DEFAULT_MAX_BODY_BYTES = 1024 * 1024
_RESOURCE_EVENTS = {"Issue", "Comment", "Project"}


@dataclass(frozen=True, slots=True)
class WebhookEvent:
    type: str
    action: str
    workspace_id: str
    installation_id: str | None
    app_user_id: str | None
    event_id: str | None
    payload: dict[str, Any] = field(repr=False)
    _resource_key: str | None = field(default=None, repr=False)

    @classmethod
    def from_verified_payload(cls, payload: Mapping[str, Any]) -> WebhookEvent:
        """Restore an event from trusted storage after a successful receive."""
        return _parse_event(dict(payload))

    @property
    def data(self) -> dict[str, Any]:
        return cast(dict[str, Any], self.payload["data"])

    @property
    def envelope(self) -> AppWebhookEnvelope:
        """The signed wire payload, with the fields described by the pinned schema."""
        return cast(AppWebhookEnvelope, self.payload)

    @property
    def created(self) -> AgentSessionEventCreatedData | None:
        if self.type == "AgentSessionEvent" and self.action == "created":
            return cast(AgentSessionEventCreatedData, self.data)
        return None

    @property
    def prompted(self) -> AgentSessionEventPromptedData | None:
        if self.type == "AgentSessionEvent" and self.action == "prompted":
            return cast(AgentSessionEventPromptedData, self.data)
        return None

    @property
    def session(self) -> AgentSession | None:
        if self.type == "AgentSessionEvent":
            return cast(AgentSession, self.data["agent_session"])
        return None

    @property
    def dedupe_key(self) -> tuple[str, str] | None:
        key = self.event_id or self._resource_key
        if self.installation_id is None or key is None:
            return None
        return self.installation_id, key

    @property
    def session_id(self) -> str | None:
        session = self.session
        return session["id"] if session is not None else None

    @property
    def is_stop(self) -> bool:
        prompted = self.prompted
        return prompted is not None and prompted["agent_activity"].get("signal") == "stop"

    @property
    def is_revoked(self) -> bool:
        return self.type == "OAuthApp" and self.action == "revoked"

    @property
    def is_permission_change(self) -> bool:
        return self.type == "PermissionChange" and self.action == "teamAccessChanged"

    @property
    def permission_change(self) -> PermissionChangeData | None:
        return cast(PermissionChangeData, self.data) if self.is_permission_change else None

    @property
    def revocation(self) -> OAuthAppRevokedData | None:
        return cast(OAuthAppRevokedData, self.data) if self.is_revoked else None


def _text(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise WebhookError(400, "invalid_event")
    return value


def _object(mapping: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = mapping.get(key)
    if not isinstance(value, dict):
        raise WebhookError(400, "invalid_event")
    return value


def _resource_key(payload: dict[str, Any]) -> str:
    # Resource webhooks may omit event_id. Pulse changes only the attempt
    # timestamp when retrying. Derive a key from the other signed fields.
    occurrence = {key: value for key, value in payload.items() if key != "webhook_timestamp"}
    canonical = _canonical_json(occurrence).encode("utf-8", errors="backslashreplace")
    return f"body:{hashlib.sha256(canonical).hexdigest()}"


def _canonical_json(value: object) -> str:
    """Match the TypeScript SDK's sorted JSON.stringify occurrence key."""
    if isinstance(value, dict):
        keys = sorted(value, key=lambda key: key.encode("utf-16-be", errors="surrogatepass"))
        fields = (f"{_canonical_json(key)}:{_canonical_json(value[key])}" for key in keys)
        return "{" + ",".join(fields) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_canonical_json(item) for item in value) + "]"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            number = float(value)
        except OverflowError:
            return "null"
        if not math.isfinite(number):
            return "null"
        if number == 0:
            return "0"
        if 1e-6 <= abs(number) < 1e21:
            fixed = format(Decimal(repr(number)), "f")
            return fixed.rstrip("0").rstrip(".") if "." in fixed else fixed
        mantissa, exponent = repr(number).split("e")
        return f"{mantissa.removesuffix('.0')}e{int(exponent):+d}"
    return json.dumps(value, ensure_ascii=False)


def _invalid_constant(_: str) -> NoReturn:
    raise ValueError("Invalid JSON constant")


def verify_webhook(
    raw_body: bytes,
    headers: Mapping[str, str],
    secret: str,
    *,
    now_ms: Callable[[], int] | None = None,
    tolerance_ms: int = DEFAULT_TOLERANCE_MS,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
) -> WebhookEvent:
    """Verify the raw bytes and the signed timestamp before returning the parsed event."""
    payload = _verify_payload(raw_body, headers, secret, now_ms, tolerance_ms, max_body_bytes)
    return _parse_event(payload)


def _verify_payload(
    raw_body: bytes,
    headers: Mapping[str, str],
    secret: str,
    now_ms: Callable[[], int] | None,
    tolerance_ms: int,
    max_body_bytes: int,
) -> dict[str, Any]:
    if (
        not secret or type(tolerance_ms) is not int or tolerance_ms < 0
        or type(max_body_bytes) is not int or max_body_bytes <= 0
    ):
        raise ValueError("A webhook secret and valid verification limits are required")
    if len(raw_body) > max_body_bytes:
        raise WebhookError(413, "body_too_large")
    signatures = [value.strip() for name, value in headers.items() if name.lower() == "pulse-signature"]
    if not signatures or signatures == [""]:
        raise WebhookError(401, "missing_signature")
    if len(signatures) != 1 or not _SIGNATURE.fullmatch(signatures[0]):
        raise WebhookError(401, "bad_signature")
    expected = hmac.digest(secret.encode(), raw_body, "sha256")
    if not hmac.compare_digest(expected, bytes.fromhex(signatures[0])):
        raise WebhookError(401, "bad_signature")
    try:
        payload = json.loads(raw_body.decode("utf-8"), parse_constant=_invalid_constant)
    except (ValueError, RecursionError):
        raise WebhookError(400, "invalid_json") from None
    if not isinstance(payload, dict):
        raise WebhookError(400, "invalid_timestamp")
    timestamp = payload.get("webhook_timestamp")
    if (
        not isinstance(timestamp, (int, float)) or isinstance(timestamp, bool)
        or abs(timestamp) > 2**53 - 1 or timestamp % 1
    ):
        raise WebhookError(400, "invalid_timestamp")
    now = now_ms() if now_ms else time.time_ns() // 1_000_000
    if abs(now - timestamp) > tolerance_ms:
        raise WebhookError(401, "stale_timestamp")
    return payload


def _parse_event(payload: dict[str, Any]) -> WebhookEvent:
    event_type = _text(payload, "type")
    action = _text(payload, "action")
    workspace_id = _text(payload, "workspace_id")
    data = _object(payload, "data")
    if event_type == "Ping":
        return WebhookEvent(event_type, action, workspace_id, None, None, None, payload)
    installation_id = _text(payload, "installation_id")
    app_user_id = _text(payload, "app_user_id")
    if event_type == "AgentSessionEvent":
        _text(_object(data, "agent_session"), "id")
        if action == "prompted":
            _object(data, "agent_activity")
    elif (event_type, action) == ("PermissionChange", "teamAccessChanged"):
        if data.get("installation_id") != installation_id or type(data.get("all_teams")) is not bool:
            raise WebhookError(400, "invalid_event")
        for field in ("team_ids", "added_team_ids", "removed_team_ids"):
            teams = data.get(field)
            if not isinstance(teams, list) or any(not isinstance(team, str) or not team.strip() for team in teams):
                raise WebhookError(400, "invalid_event")
    elif (event_type, action) == ("OAuthApp", "revoked"):
        if data.get("installation_id") != installation_id:
            raise WebhookError(400, "invalid_event")
        _text(data, "app_id")
    resource_without_id = event_type in _RESOURCE_EVENTS and "event_id" not in data
    try:
        resource_key = _resource_key(payload) if resource_without_id else None
    except RecursionError:
        raise WebhookError(400, "invalid_event") from None
    return WebhookEvent(
        type=event_type,
        action=action,
        workspace_id=workspace_id,
        installation_id=installation_id,
        app_user_id=app_user_id,
        event_id=None if resource_without_id else _text(data, "event_id"),
        payload=payload,
        _resource_key=resource_key,
    )


class WebhookReceiver:
    """Return only after enqueue commits, so a successful HTTP reply can acknowledge delivery."""

    def __init__(
        self,
        secret: str,
        enqueue: Callable[[WebhookEvent], Awaitable[None]],
        *,
        workspace_id: str,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        now_ms: Callable[[], int] | None = None,
        tolerance_ms: int = DEFAULT_TOLERANCE_MS,
    ) -> None:
        if (
            not secret or not workspace_id.strip() or type(max_body_bytes) is not int or max_body_bytes <= 0
            or type(tolerance_ms) is not int or tolerance_ms < 0
        ):
            raise ValueError("A Pulse webhook secret, workspace and valid verification limits are required")
        self._secret = secret
        self._enqueue = enqueue
        self._workspace_id = workspace_id
        self._max_body_bytes = max_body_bytes
        self._now_ms = now_ms
        self._tolerance_ms = tolerance_ms

    async def receive(self, raw_body: bytes, headers: Mapping[str, str]) -> WebhookEvent:
        """Enqueue idempotently using the event's dedupe key. Ping requires no enqueue."""
        event = verify_webhook(
            raw_body,
            headers,
            self._secret,
            max_body_bytes=self._max_body_bytes,
            now_ms=self._now_ms,
            tolerance_ms=self._tolerance_ms,
        )
        if event.workspace_id != self._workspace_id:
            raise WebhookError(403, "wrong_workspace")
        if event.dedupe_key is not None:
            await self._enqueue(event)
        return event
