"""Generated from specs/agent-sessions.yaml by scripts/generate_types.py."""

from typing import Literal, NotRequired, TypeAlias, TypedDict


class Error(TypedDict):
    code: str
    message: str
    details: NotRequired[dict[str, object]]


AgentSessionState: TypeAlias = Literal['pending', 'active', 'awaitingInput', 'error', 'complete', 'stale', 'stopping']


AgentSessionEndReason: TypeAlias = Literal['stopped', 'undelegated', 'uninstalled', 'team_removed', 'issue_deleted'] | None


class PlanItem(TypedDict):
    content: str
    status: Literal['pending', 'inProgress', 'completed', 'canceled']


class ExternalUrl(TypedDict):
    label: str
    url: str


class Person(TypedDict):
    id: str
    name: str


class AgentSessionIssueTeam(TypedDict):
    id: str
    key: str
    name: str


class AgentSessionIssue(TypedDict):
    id: str
    identifier: str
    title: str
    url: str
    team: AgentSessionIssueTeam


class AgentSessionComment(TypedDict):
    id: str
    body: str
    url: str


class AgentSession(TypedDict):
    id: str
    state: AgentSessionState
    unresponsive_since: str | None
    issue: AgentSessionIssue | None
    comment: AgentSessionComment | None
    creator: Person
    app_user_id: str
    plan: list[PlanItem]
    external_urls: list[ExternalUrl]
    created_at: str
    updated_at: str
    ended_at: str | None
    end_reason: AgentSessionEndReason


class AgentSessionPage(TypedDict):
    data: list[AgentSession]
    next_cursor: str | None


class AgentSessionCreateVariant1(TypedDict):
    issue_id: str


class AgentSessionCreateVariant2(TypedDict):
    comment_id: str


AgentSessionCreate: TypeAlias = AgentSessionCreateVariant1 | AgentSessionCreateVariant2


class SessionUpdate(TypedDict):
    plan: NotRequired[list[PlanItem]]
    external_urls: NotRequired[list[ExternalUrl]]
    added_external_urls: NotRequired[list[ExternalUrl]]
    removed_external_urls: NotRequired[list[str]]


class ThoughtContent(TypedDict):
    type: Literal['thought']
    body: str


class ActionContent(TypedDict):
    type: Literal['action']
    action: str
    parameter: str | None
    result: NotRequired[str]


class ElicitationContent(TypedDict):
    type: Literal['elicitation']
    body: str


class ResponseContent(TypedDict):
    type: Literal['response']
    body: str


class ErrorContent(TypedDict):
    type: Literal['error']
    body: str


class PromptContent(TypedDict):
    type: Literal['prompt']
    body: str


class SelectOption(TypedDict):
    value: str
    label: NotRequired[str]


class SelectSignalMetadata(TypedDict):
    options: list[SelectOption]


class AuthSignal(TypedDict):
    url: str
    user_id: NotRequired[str]
    provider_name: NotRequired[str]


class AgentActivityCreate(TypedDict):
    content: ThoughtContent | ActionContent | ElicitationContent | ResponseContent | ErrorContent
    ephemeral: NotRequired[bool]
    signal: NotRequired[Literal['select', 'auth']]
    signal_metadata: NotRequired[SelectSignalMetadata | AuthSignal]


class AgentActivityAuthor(TypedDict):
    kind: Literal['app', 'user']
    id: str
    name: str
    avatar_url: str | None


class AgentActivity(TypedDict):
    id: str
    seq: int
    type: Literal['thought', 'action', 'elicitation', 'response', 'error', 'prompt']
    content: ThoughtContent | ActionContent | ElicitationContent | ResponseContent | ErrorContent | PromptContent
    ephemeral: bool
    superseded_by_seq: int | None
    signal: Literal['stop', 'select', 'auth'] | None
    signal_metadata: SelectSignalMetadata | AuthSignal | None
    author: AgentActivityAuthor
    created_at: str


class AgentActivityPage(TypedDict):
    data: list[AgentActivity]
    has_more: bool
    last_seq: int


class PromptedActivity(TypedDict):
    id: str
    content: PromptContent
    signal: NotRequired[Literal['stop']]
    author: Person
    created_at: str


PromptContext: TypeAlias = str
