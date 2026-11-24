"""SDK errors with machine-readable codes."""

from __future__ import annotations

from collections.abc import Mapping


class PulseApiError(Exception):
    """A failed Pulse request. Error details can contain application data."""

    def __init__(
        self,
        status: int,
        code: str,
        *,
        retry_after: float | None = None,
        details: Mapping[str, object] | None = None,
    ) -> None:
        self.status = status
        self.code = code
        self.retry_after = retry_after
        self.details = details
        super().__init__(f"Pulse API returned {status} ({code})")


class PulseTransportError(PulseApiError):
    """A request failed before an HTTP response was available."""

    def __init__(self, *, timed_out: bool) -> None:
        self.timed_out = timed_out
        super().__init__(0, "transport_error")


class OAuthError(PulseApiError):
    """Pulse's OAuth endpoint or the local installation flow refused a request."""


class InstallSecretError(OAuthError):
    def __init__(self) -> None:
        super().__init__(403, "invalid_install_secret")


class InstallationRevokedError(Exception):
    def __init__(self, installation_id: str) -> None:
        self.installation_id = installation_id
        super().__init__("Pulse app installation needs authorization")


class SessionEndedError(PulseApiError):
    def __init__(
        self, session_id: str, end_reason: str | None = None, *, details: Mapping[str, object] | None = None,
    ) -> None:
        self.session_id = session_id
        self.end_reason = end_reason
        super().__init__(409, "SESSION_ENDED", details=details)


class WebhookError(Exception):
    def __init__(self, status: int, code: str) -> None:
        self.status = status
        self.code = code
        super().__init__(f"Pulse webhook refused ({code})")
