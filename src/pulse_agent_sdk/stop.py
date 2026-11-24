"""Process-local Stop signals for SDK consumers with in-process work."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Literal

from .errors import SessionEndedError


@dataclass(frozen=True, slots=True)
class StopCause:
    kind: Literal["stop_signal", "session_ended", "revoked", "shutdown"]
    end_reason: str | None = None


class StopSignal:
    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._cause: StopCause | None = None

    @property
    def aborted(self) -> bool:
        return self._event.is_set()

    @property
    def cause(self) -> StopCause | None:
        return self._cause

    async def wait(self) -> StopCause:
        await self._event.wait()
        assert self._cause is not None
        return self._cause

    def _stop(self, cause: StopCause) -> None:
        if not self.aborted:
            self._cause = cause
            self._event.set()


@dataclass(slots=True)
class _Entry:
    signal: StopSignal = field(default_factory=StopSignal)
    installation_id: str | None = None


class SessionStops:
    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}

    def signal(self, session_id: str, installation_id: str | None = None) -> StopSignal:
        entry = self._entries.setdefault(session_id, _Entry())
        if installation_id is not None:
            entry.installation_id = installation_id
        return entry.signal

    def stop(self, session_id: str, cause: StopCause) -> None:
        self.signal(session_id)._stop(cause)

    def stop_installation(self, installation_id: str, cause: StopCause | None = None) -> list[str]:
        stopped = []
        for session_id, entry in self._entries.items():
            if entry.installation_id == installation_id:
                entry.signal._stop(cause or StopCause("revoked"))
                stopped.append(session_id)
        return stopped

    def is_stopped(self, session_id: str) -> bool:
        entry = self._entries.get(session_id)
        return entry is not None and entry.signal.aborted

    def resume(self, session_id: str) -> None:
        entry = self._entries.get(session_id)
        if entry is not None and entry.signal.aborted:
            entry.signal = StopSignal()

    def release(self, session_id: str) -> None:
        self._entries.pop(session_id, None)

    def note_session_ended(self, error: SessionEndedError) -> None:
        self.stop(error.session_id, StopCause("session_ended", error.end_reason))
