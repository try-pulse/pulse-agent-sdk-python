"""Post-ack webhook callbacks for process-local agent implementations."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import math
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from time import monotonic
from typing import Any, NotRequired, ParamSpec, Protocol, TypedDict

from .errors import WebhookError
from .stop import SessionStops, StopCause, StopSignal
from .webhooks import (
    DEFAULT_MAX_BODY_BYTES,
    DEFAULT_TOLERANCE_MS,
    WebhookEvent,
    _parse_event,
    _verify_payload,
)

_logger = logging.getLogger(__name__)
_P = ParamSpec("_P")
_EventCallback = Callable[[WebhookEvent], None | Awaitable[None]]
_SessionCallback = Callable[[WebhookEvent, "SessionContext"], None | Awaitable[None]]
_ORDER_RETENTION_SECONDS = 86_400


class DedupeStore(Protocol):
    """Atomically claim a JSON-encoded [installation_id, occurrence] key."""

    def claim(self, event_id: str) -> bool | Awaitable[bool]: ...


class MemoryDedupeStore:
    def __init__(self, *, ttl: float = 86_400, max_entries: int = 10_000) -> None:
        if not math.isfinite(ttl) or ttl <= 0 or max_entries <= 0:
            raise ValueError("Dedupe TTL and capacity must be positive")
        self._ttl = ttl
        self._max_entries = max_entries
        self._seen: dict[str, float] = {}

    def claim(self, event_id: str) -> bool:
        now = monotonic()
        seen = self._seen.get(event_id)
        if seen is not None and now - seen < self._ttl:
            return False
        self._seen.pop(event_id, None)
        self._seen[event_id] = now
        while self._seen:
            oldest = next(iter(self._seen))
            if len(self._seen) <= self._max_entries and now - self._seen[oldest] < self._ttl:
                break
            del self._seen[oldest]
        return True


@dataclass(frozen=True, slots=True)
class SessionContext:
    signal: StopSignal
    is_stop: bool = False


class WebhookReply(TypedDict):
    ok: bool
    error: NotRequired[str]


@dataclass(slots=True)
class _SessionOrder:
    latest_work: datetime | None = None
    stop_at: datetime | None = None
    undated_stop: bool = False
    pending: int = 0
    pending_stops: int = 0
    stops_settled: asyncio.Event = field(default_factory=asyncio.Event)

    def apply_stop(self, occurrence: datetime | None) -> bool:
        if self.undated_stop:
            return False
        if occurrence is None:
            self.undated_stop = True
            return True
        if self.stop_at is not None and occurrence <= self.stop_at:
            return False
        self.stop_at = occurrence
        return self.latest_work is None or occurrence >= self.latest_work

    def accept_work(self, occurrence: datetime | None, *, prompted: bool) -> bool:
        if self.undated_stop:
            return False
        if self.stop_at is not None:
            if occurrence is None or occurrence <= self.stop_at:
                return False
            if not prompted and (self.latest_work is None or self.latest_work <= self.stop_at):
                return False
        if occurrence is not None and (self.latest_work is None or occurrence > self.latest_work):
            self.latest_work = occurrence
        return True


class WebhookHandler:
    """Acknowledge verified webhooks before dispatch, like the TypeScript handler."""

    def __init__(
        self,
        secret: str,
        *,
        stops: SessionStops | None = None,
        dedupe: DedupeStore | None = None,
        workspace_id: str | None = None,
        on_session_created: _SessionCallback | None = None,
        on_session_prompted: _SessionCallback | None = None,
        on_permission_change: _EventCallback | None = None,
        on_revoked: _EventCallback | None = None,
        on_ping: _EventCallback | None = None,
        on_data: _EventCallback | None = None,
        on_error: Callable[[Exception, WebhookEvent | dict[str, Any]], None | Awaitable[None]] | None = None,
        on_rejected: Callable[[str], None] | None = None,
        now_ms: Callable[[], int] | None = None,
        tolerance_ms: int = DEFAULT_TOLERANCE_MS,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        max_ordered_sessions: int = 10_000,
    ) -> None:
        if (
            not secret or (workspace_id is not None and not workspace_id.strip())
            or type(tolerance_ms) is not int or tolerance_ms < 0
            or type(max_body_bytes) is not int or max_body_bytes <= 0
            or type(max_ordered_sessions) is not int or max_ordered_sessions <= 0
        ):
            raise ValueError("A webhook secret and valid verification limits are required")
        self._secret = secret
        self._workspace_id = workspace_id
        self._dedupe = dedupe if dedupe is not None else MemoryDedupeStore()
        self.stops = stops if stops is not None else SessionStops()
        self._created = on_session_created
        self._prompted = on_session_prompted
        self._permission_change = on_permission_change
        self._revoked = on_revoked
        self._ping = on_ping
        self._data = on_data
        self._on_error = on_error
        self._on_rejected = on_rejected
        self._now_ms = now_ms
        self._tolerance_ms = tolerance_ms
        self._max_body_bytes = max_body_bytes
        self._max_ordered_sessions = max_ordered_sessions
        self._inflight: set[asyncio.Task[None]] = set()
        self._session_order: dict[str, _SessionOrder] = {}
        self._idle_expiry: dict[str, float] = {}

    def handle(self, raw_body: bytes, headers: Mapping[str, str]) -> tuple[int, WebhookReply]:
        try:
            payload = _verify_payload(
                raw_body,
                headers,
                self._secret,
                self._now_ms,
                self._tolerance_ms,
                self._max_body_bytes,
            )
            if self._workspace_id is not None and payload.get("workspace_id") != self._workspace_id:
                raise WebhookError(403, "wrong_workspace")
        except WebhookError as exc:
            code = {
                "invalid_timestamp": "missing_timestamp",
                "body_too_large": "too_large",
            }.get(exc.code, exc.code)
            if self._on_rejected is not None:
                try:
                    self._on_rejected(code)
                except Exception as error:
                    _logger.error("Pulse webhook rejection hook failed (%s)", type(error).__name__)
            status = 401 if code == "missing_timestamp" else exc.status
            return status, {"ok": False, "error": code}
        loop = asyncio.get_running_loop()
        event = None
        order = None
        if payload.get("type") == "AgentSessionEvent" and payload.get("action") in ("created", "prompted"):
            try:
                event = _parse_event(payload)
            except WebhookError:
                pass  # Invalid events still reach the post-ack error hook.
            if event is not None and (session_id := event.session_id) is not None:
                order = self._reserve_session(session_id, is_stop=event.is_stop)
                if order is None:
                    return 503, {"ok": False, "error": "session_order_capacity"}
        task = loop.create_task(self._dispatch_after_ack(payload, event, order))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)
        return 200, {"ok": True}

    async def idle(self) -> None:
        while self._inflight:
            await asyncio.wait(tuple(self._inflight))

    def _reserve_session(self, session_id: str, *, is_stop: bool) -> _SessionOrder | None:
        now = monotonic()
        while self._idle_expiry:
            oldest = next(iter(self._idle_expiry))
            if self._idle_expiry[oldest] > now:
                break
            del self._idle_expiry[oldest]
            del self._session_order[oldest]

        order = self._session_order.get(session_id)
        if order is None:
            if len(self._session_order) >= self._max_ordered_sessions:
                return None
            order = self._session_order[session_id] = _SessionOrder()
        self._idle_expiry.pop(session_id, None)
        order.pending += 1
        if is_stop:
            order.pending_stops += 1
            order.stops_settled.clear()
        return order

    async def _dispatch_after_ack(
        self, payload: dict[str, Any], event: WebhookEvent | None, order: _SessionOrder | None,
    ) -> None:
        # Even an eager asyncio task factory must give the caller the reply first.
        await asyncio.sleep(0)
        try:
            if event is None:
                event = _parse_event(payload)
            if order is not None and (session_id := event.session_id) is not None:
                await self._dispatch_session(event, session_id, order)
                return
            if not await self._claim(event):
                return
            if event.type == "Ping":
                await _call(self._ping, event)
            elif event.is_permission_change:
                await _call(self._permission_change, event)
            elif event.is_revoked and event.installation_id:
                self.stops.stop_installation(event.installation_id)
                await _call(self._revoked, event)
            elif event.type in {"Issue", "Comment", "Project"}:
                await _call(self._data, event)
        except Exception as exc:
            if self._on_error is not None:
                try:
                    await _call(self._on_error, exc, event if event is not None else payload)
                except Exception as error:
                    _logger.error("Pulse webhook error hook failed (%s)", type(error).__name__)
            else:
                _logger.error("Pulse webhook callback failed (%s)", type(exc).__name__)

    async def _claim(self, event: WebhookEvent) -> bool:
        if event.dedupe_key is None:
            return True
        key = json.dumps(event.dedupe_key, separators=(",", ":"))
        result = self._dedupe.claim(key)
        return await result if inspect.isawaitable(result) else result

    async def _dispatch_session(self, event: WebhookEvent, session_id: str, order: _SessionOrder) -> None:
        is_stop = event.is_stop
        try:
            if not await self._claim(event):
                return
            occurrence = _occurrence_time(event)
            if is_stop:
                if not order.apply_stop(occurrence):
                    return
                reason = event.data["agent_session"].get("end_reason")
                signal = self.stops.signal(session_id, event.installation_id)
                self.stops.stop(session_id, StopCause("stop_signal", reason if isinstance(reason, str) else None))
            else:
                while order.pending_stops:
                    await order.stops_settled.wait()
                prompted = event.action == "prompted"
                if not order.accept_work(occurrence, prompted=prompted):
                    return
                if prompted:
                    self.stops.resume(session_id)
                signal = self.stops.signal(session_id, event.installation_id)
        finally:
            if is_stop:
                order.pending_stops -= 1
                if not order.pending_stops:
                    order.stops_settled.set()
            order.pending -= 1
            if not order.pending:
                self._idle_expiry[session_id] = monotonic() + _ORDER_RETENTION_SECONDS
        callback = self._created if event.action == "created" else self._prompted
        await _call(callback, event, SessionContext(signal, is_stop))


def _occurrence_time(event: WebhookEvent) -> datetime | None:
    value = event.payload.get("created_at")
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is not None:
            return parsed
    return None


async def _call(
    callback: Callable[_P, None | Awaitable[None]] | None, *args: _P.args, **kwargs: _P.kwargs,
) -> None:
    if callback is not None:
        result = callback(*args, **kwargs)
        if inspect.isawaitable(result):
            await result
