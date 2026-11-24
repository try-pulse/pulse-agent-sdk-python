"""Generated from specs/pulse-api.agent-sdk.yaml by scripts/generate_types.py."""

from typing import Literal, NotRequired, TypeAlias, TypedDict

AgentAppScope: TypeAlias = Literal['read', 'write', 'issues:create', 'comments:create', 'app:assignable', 'app:mentionable']


AppWebhookAction: TypeAlias = Literal['created', 'prompted', 'teamAccessChanged', 'revoked', 'create', 'update', 'remove']


AppWebhookEventType: TypeAlias = Literal['AgentSessionEvent', 'PermissionChange', 'OAuthApp', 'Issue', 'Comment', 'Project', 'Ping']


class WebhookActorFields(TypedDict):
    id: str
    type: Literal['user', 'application', 'system']
    name: str


WebhookActor: TypeAlias = WebhookActorFields | None


AgentSessionState: TypeAlias = Literal['pending', 'active', 'awaitingInput', 'error', 'complete', 'stale', 'stopping']


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


class AgentSessionPerson(TypedDict):
    id: str
    name: str


class AgentSessionPlanItem(TypedDict):
    content: str
    status: Literal['pending', 'inProgress', 'completed', 'canceled']


class AgentSessionExternalUrl(TypedDict):
    label: str
    url: str


AgentSessionEndReason: TypeAlias = Literal['stopped', 'undelegated', 'uninstalled', 'team_removed', 'issue_deleted'] | None


class AgentSession(TypedDict):
    id: str
    state: AgentSessionState
    unresponsive_since: str | None
    issue: AgentSessionIssue | None
    comment: AgentSessionComment | None
    creator: AgentSessionPerson
    app_user_id: str
    plan: list[AgentSessionPlanItem]
    external_urls: list[AgentSessionExternalUrl]
    created_at: str
    updated_at: str
    ended_at: str | None
    end_reason: AgentSessionEndReason


class AgentSessionGuidance(TypedDict):
    origin: Literal['workspace', 'team']
    team_id: NotRequired[str]
    body: str


class AgentSessionEventCreatedData(TypedDict):
    event_id: str
    agent_session: AgentSession
    previous_comments: list[AgentSessionComment]
    guidance: list[AgentSessionGuidance]
    prompt_context: str


class PromptedActivityContent(TypedDict):
    type: Literal['prompt']
    body: str


class PromptedActivity(TypedDict):
    id: str
    content: PromptedActivityContent
    signal: NotRequired[Literal['stop']]
    author: AgentSessionPerson
    created_at: str


class AgentSessionEventPromptedData(TypedDict):
    event_id: str
    agent_session: AgentSession
    agent_activity: PromptedActivity


class PermissionChangeData(TypedDict):
    event_id: str
    installation_id: str
    all_teams: bool
    team_ids: list[str]
    added_team_ids: list[str]
    removed_team_ids: list[str]


class OAuthAppRevokedData(TypedDict):
    event_id: str
    installation_id: str
    app_id: str


WebhookTimestamp: TypeAlias = str


class WebhookIssueData(TypedDict):
    id: str
    code: str
    title: str
    description: str
    status: str
    priority: str
    type: str
    team_id: str | None
    project_id: str | None
    milestone_id: str | None
    cycle_id: str | None
    parent_id: str | None
    reporter_id: str | None
    assignee_id: str | None
    delegate_id: str | None
    delegation_revision: int
    label_ids: list[str]
    blocks_ids: list[str]
    blocked_by_ids: list[str]
    time_estimate: float | None
    due_date: WebhookTimestamp | None
    completed_at: WebhookTimestamp | None
    created_at: WebhookTimestamp
    updated_at: WebhookTimestamp


class WebhookCommentData(TypedDict):
    id: str
    text: str
    author_id: str | None
    target_type: Literal['issue', 'project']
    target_id: str
    parent_comment_id: str | None
    is_resolved: bool
    mentioned_user_ids: list[str]
    edited_at: WebhookTimestamp | None
    created_at: WebhookTimestamp
    updated_at: WebhookTimestamp


class WebhookProjectData(TypedDict):
    id: str
    title: str
    description: str
    status: str
    priority: str
    health_status: str | None
    owner_id: str | None
    lead_id: str | None
    member_ids: list[str]
    team_ids: list[str]
    initiative_id: str | None
    initiative_ids: list[str]
    label_ids: list[str]
    start_date: WebhookTimestamp | None
    target_date: WebhookTimestamp | None
    completed_at: WebhookTimestamp | None
    progress: float | None
    created_at: WebhookTimestamp
    updated_at: WebhookTimestamp


class AppWebhookPingData(TypedDict):
    webhook_id: str
    label: str


class AppWebhookEnvelope(TypedDict):
    action: AppWebhookAction
    type: AppWebhookEventType
    actor: WebhookActor
    created_at: str
    data: AgentSessionEventCreatedData | AgentSessionEventPromptedData | PermissionChangeData | OAuthAppRevokedData | WebhookIssueData | WebhookCommentData | WebhookProjectData | AppWebhookPingData
    updated_from: NotRequired[dict[str, object]]
    url: str
    workspace_id: str
    webhook_id: str
    webhook_timestamp: int
    installation_id: NotRequired[str]
    app_user_id: NotRequired[str]


ObjectId: TypeAlias = str


class Conflict(TypedDict):
    id: NotRequired[ObjectId]
    code: NotRequired[str]
    status: NotRequired[str]


class ApiErrorBody(TypedDict):
    code: str
    message: str
    details: NotRequired[dict[str, object]]
    conflict: NotRequired[Conflict]


IssueStatus: TypeAlias = Literal['backlog', 'todo', 'in_progress', 'qa', 'release', 'done']


IssuePriority: TypeAlias = Literal['no_priority', 'urgent', 'high', 'medium', 'low']


IssueType: TypeAlias = Literal['bug', 'feature', 'task', 'story']


DateTime: TypeAlias = str


LabelScope: TypeAlias = Literal['workspace', 'team']


LabelEntityType: TypeAlias = Literal['issue', 'project', 'request', 'initiative']


HexColor: TypeAlias = str


class LabelGroup(TypedDict):
    id: ObjectId
    scope: LabelScope
    team_id: NotRequired[ObjectId]
    entity_type: LabelEntityType
    name: str
    created_at: DateTime
    updated_at: DateTime


class CatalogLabel(TypedDict):
    id: ObjectId
    scope: LabelScope
    team_id: NotRequired[ObjectId]
    entity_type: LabelEntityType
    name: str
    color: HexColor
    description: NotRequired[str]
    group_id: NotRequired[ObjectId | None]
    group: NotRequired[LabelGroup | None]
    archived: bool
    archived_at: NotRequired[DateTime | None]
    created_at: DateTime
    updated_at: DateTime


class IssueProgress(TypedDict):
    total: NotRequired[int]
    done: NotRequired[int]
    updated_at: NotRequired[DateTime]


class IssueDevelopmentSummary(TypedDict):
    total: int
    pull_requests: int
    merge_requests: int
    commits: int
    branches: int
    primary_provider: NotRequired[Literal['github', 'gitlab']]
    primary_kind: NotRequired[Literal['pull_request', 'merge_request', 'commit', 'branch']]
    primary_label: NotRequired[str]
    primary_state: NotRequired[Literal['draft', 'open', 'closed', 'merged', 'unknown']]
    primary_draft: bool


class TeamBasic(TypedDict):
    id: ObjectId
    name: str
    icon_code: str
    icon_color: HexColor


ProjectStatus: TypeAlias = Literal['idea', 'discovery', 'proposal', 'accepted', 'ready', 'in_progress', 'paused', 'maintenance', 'completed', 'canceled']


class IssueProject(TypedDict):
    id: NotRequired[ObjectId]
    title: NotRequired[str]
    status: NotRequired[ProjectStatus]


class IssueCycle(TypedDict):
    id: NotRequired[ObjectId]
    name: NotRequired[str]
    status: NotRequired[Literal['planned', 'active', 'completed']]


class MilestoneStats(TypedDict):
    total_issues: NotRequired[int]
    started_issues: NotRequired[int]
    done_issues: NotRequired[int]
    total_points: NotRequired[int]
    started_points: NotRequired[int]
    done_points: NotRequired[int]
    estimated_issues: NotRequired[int]
    estimate_based: NotRequired[bool]
    progress: NotRequired[float]


class Milestone(TypedDict):
    id: ObjectId
    project_id: ObjectId
    name: str
    description: NotRequired[str]
    target_date: NotRequired[DateTime | None]
    sort_order: int
    main_doc_id: NotRequired[ObjectId | None]
    status: NotRequired[Literal['unstarted', 'in_progress', 'completed']]
    is_current: NotRequired[bool]
    stats: NotRequired[MilestoneStats | None]
    created_at: DateTime
    updated_at: DateTime


class CustomerCatalogValue(TypedDict):
    id: ObjectId
    workspace_id: NotRequired[str]
    kind: Literal['status', 'tier']
    name: str
    color: NotRequired[str]
    description: NotRequired[str]
    sort_order: int
    is_default: bool
    archived: bool
    archived_at: NotRequired[DateTime | None]
    created_by: NotRequired[str]
    created_at: DateTime
    updated_at: DateTime


class CustomerOwner(TypedDict):
    id: ObjectId
    display_name: NotRequired[str]
    email: NotRequired[str]
    avatar_url: NotRequired[str]
    active: bool


class Contact(TypedDict):
    id: ObjectId
    workspace_id: NotRequired[str]
    customer_id: ObjectId
    name: str
    email: str
    job_title: NotRequired[str]
    archived: bool
    archived_at: NotRequired[DateTime | None]
    created_by: ObjectId
    created_at: DateTime
    updated_at: DateTime
    customer: NotRequired['Customer | None']


class Customer(TypedDict):
    id: ObjectId
    workspace_id: NotRequired[str]
    name: str
    domains: NotRequired[list[str]]
    notes: NotRequired[str]
    icon_code: NotRequired[str]
    icon_color: NotRequired[str]
    status_id: NotRequired[ObjectId | None]
    status: NotRequired[CustomerCatalogValue | None]
    tier_id: NotRequired[ObjectId | None]
    tier: NotRequired[CustomerCatalogValue | None]
    annual_revenue: NotRequired[int | None]
    size: NotRequired[int | None]
    owner_id: NotRequired[ObjectId | None]
    owner: NotRequired[CustomerOwner | None]
    logo_url: NotRequired[str]
    request_count: NotRequired[int | None]
    merged_into_id: NotRequired[ObjectId | None]
    merged_at: NotRequired[DateTime | None]
    archived: bool
    archived_at: NotRequired[DateTime | None]
    created_by: ObjectId
    created_at: DateTime
    updated_at: DateTime
    contacts: NotRequired[list[Contact]]


class RequestRef(TypedDict):
    id: ObjectId
    code: str
    title: str
    status: str
    type: str
    priority: str


AgentKind: TypeAlias = Literal['deployment', 'personal', 'app']


class AvatarURLSet(TypedDict):
    xs: NotRequired[str]
    s: NotRequired[str]
    m: NotRequired[str]
    l: NotRequired[str]


class TeamMembership(TypedDict):
    team_id: ObjectId
    team_role: Literal['manager', 'member', 'viewer', 'qa']
    role_id: NotRequired[str]
    role_name: NotRequired[str]


class User(TypedDict):
    id: ObjectId
    email: str
    role: Literal['admin', 'user']
    first_name: NotRequired[str]
    last_name: NotRequired[str]
    job_title: NotRequired[str]
    display_name: NotRequired[str]
    is_agent: NotRequired[bool]
    user_kind: NotRequired[Literal['human', 'application']]
    agent_kind: NotRequired[AgentKind]
    avatar_url: NotRequired[str | None]
    avatar_urls: NotRequired[AvatarURLSet]
    avatar_status: NotRequired[Literal['pending', 'processing', 'processed'] | None]
    status: Literal['active', 'blocked', 'pending']
    team_memberships: list[TeamMembership]
    teams: NotRequired[list[TeamBasic] | None]
    created_at: DateTime
    updated_at: DateTime


KeyResultTargetType: TypeAlias = Literal['final_value', 'stepwise', 'cumulative', 'average_based', 'threshold_based', 'growth_rate', 'boolean']


KeyResultDirection: TypeAlias = Literal['increasing', 'decreasing']


KeyResultPeriodType: TypeAlias = Literal['weekly', 'monthly']


class StepTarget(TypedDict):
    period_start: DateTime
    period_end: DateTime
    target_value: float
    baseline: NotRequired[float | None]


KeyResultValueType: TypeAlias = Literal['number', 'percentage', 'currency', 'custom']


KeyResultStatus: TypeAlias = Literal['on_track', 'at_risk', 'off_track', 'completed']


class UserBasic(TypedDict):
    id: ObjectId
    email: str
    role: Literal['admin', 'user']
    status: Literal['active', 'blocked', 'pending']
    avatar_url: NotRequired[str | None]
    avatar_urls: NotRequired[AvatarURLSet]
    avatar_status: NotRequired[Literal['pending', 'processing', 'processed'] | None]
    team_memberships: list[TeamMembership]
    teams: NotRequired[list[TeamBasic] | None]
    created_at: NotRequired[DateTime]
    updated_at: NotRequired[DateTime]
    email_verified: NotRequired[bool]
    email_verified_at: NotRequired[DateTime | None]
    onboarding_completed: NotRequired[bool]
    onboarding_completed_at: NotRequired[DateTime | None]
    default_workspace_id: NotRequired[str | None]
    user_kind: NotRequired[Literal['human', 'application']]
    agent_kind: NotRequired[AgentKind]


class Metric(TypedDict):
    id: ObjectId
    name: str
    description: NotRequired[str | None]
    unit: str
    current_value: float
    last_updated_at: DateTime
    owner_id: NotRequired[ObjectId | None]
    team_id: NotRequired[ObjectId | None]
    owner: NotRequired[UserBasic | None]
    team: NotRequired[TeamBasic | None]
    linked_key_results_count: NotRequired[int]
    created_at: DateTime
    updated_at: DateTime


MeasurementSource: TypeAlias = Literal['manual', 'metric', 'daily_snapshot']


class KRMeasurement(TypedDict):
    id: ObjectId
    kr_id: ObjectId
    value: float
    recorded_at: DateTime
    period: NotRequired[str | None]
    recorded_by: ObjectId
    source: MeasurementSource
    notes: NotRequired[str | None]
    recorded_by_user: NotRequired[UserBasic | None]
    created_at: DateTime


InitiativeStatus: TypeAlias = Literal['proposed', 'planned', 'active', 'completed', 'canceled']


InitiativePriority: TypeAlias = Literal['no_priority', 'urgent', 'high', 'medium', 'low']


class InitiativeBasic(TypedDict):
    id: ObjectId
    title: str
    description: NotRequired[str | None]
    status: InitiativeStatus
    priority: InitiativePriority
    icon_code: str
    icon_color: HexColor
    progress: NotRequired[int]
    target_date: NotRequired[DateTime | None]


ContentType: TypeAlias = Literal['link', 'document', 'image', 'video']


class ContentBasic(TypedDict):
    id: ObjectId
    title: str
    description: NotRequired[str | None]
    type: ContentType
    url: NotRequired[str | None]
    access_url: NotRequired[str | None]
    direct_access_url: NotRequired[str | None]
    content_type: NotRequired[str | None]
    file_size: NotRequired[int | None]
    checksum: NotRequired[str | None]
    tags: NotRequired[list[str]]
    is_public: NotRequired[bool]
    icon_code: NotRequired[str | None]
    icon_color: NotRequired[str | None]
    version: NotRequired[int]
    is_current_version: NotRequired[bool]
    root_content_id: NotRequired[ObjectId | None]
    amended_at: NotRequired[DateTime | None]
    edit_session_id: NotRequired[str | None]
    created_at: NotRequired[DateTime]
    updated_at: NotRequired[DateTime]
    deleted_at: NotRequired[str | None]


class KeyResult(TypedDict):
    id: ObjectId
    objective_id: ObjectId
    title: str
    description: NotRequired[str]
    weight: int
    target_type: KeyResultTargetType
    direction: KeyResultDirection
    baseline: float
    target_value: float
    current_value: float
    min_threshold: NotRequired[float | None]
    period_type: NotRequired[KeyResultPeriodType | None]
    step_targets: NotRequired[list[StepTarget]]
    progress: float
    last_calculated_at: NotRequired[DateTime | None]
    value_type: KeyResultValueType
    value_unit: NotRequired[str | None]
    metric_id: NotRequired[ObjectId | None]
    owner_id: NotRequired[ObjectId | None]
    status: KeyResultStatus
    owner: NotRequired[UserBasic | None]
    metric: NotRequired[Metric | None]
    measurements: NotRequired[list[KRMeasurement]]
    measurement_count: NotRequired[int]
    initiatives: NotRequired[list[InitiativeBasic]]
    main_doc_id: NotRequired[ObjectId | None]
    main_doc: NotRequired[ContentBasic | None]
    content: NotRequired[list[ContentBasic]]
    created_at: NotRequired[DateTime]
    updated_at: NotRequired[DateTime]


ProjectPriority: TypeAlias = Literal['no_priority', 'urgent', 'high', 'medium', 'low']


ProjectHealthStatus: TypeAlias = Literal['on_track', 'off_track', 'at_risk']


class ProjectBasic(TypedDict):
    id: ObjectId
    title: str
    description: NotRequired[str | None]
    status: ProjectStatus
    priority: ProjectPriority
    health_status: NotRequired[ProjectHealthStatus | None]
    icon_code: str
    icon_color: HexColor
    start_date: NotRequired[DateTime]
    target_date: NotRequired[DateTime]
    completed_at: NotRequired[DateTime]
    progress: NotRequired[int]


class IssueBasic(TypedDict):
    id: ObjectId
    code: str
    title: str
    description: NotRequired[str | None]
    status: IssueStatus
    priority: IssuePriority
    type: IssueType


class GrantInfo(TypedDict):
    grant_id: NotRequired[str]
    permission: NotRequired[Literal['view', 'edit']]
    granted_at: NotRequired[str]
    granted_by_id: NotRequired[str]
    granted_by_name: NotRequired[str]
    granted_by_avatar_url: NotRequired[str]


class SLASummaryResponse(TypedDict):
    item_state: NotRequired[Literal['', 'active', 'at_risk', 'breached']]
    source: NotRequired[Literal['automatic', 'manual']]
    rule_id: NotRequired[str]
    rule_title: NotRequired[str]
    match_explanation: NotRequired[str]
    next_deadline_at: NotRequired[str]
    open_target_count: NotRequired[int]


class Request(TypedDict):
    id: ObjectId
    code: str
    title: str
    description: NotRequired[str]
    type: Literal['bug', 'feature', 'other']
    status: Literal['triage', 'pending', 'accepted', 'rejected', 'done', 'duplicate']
    team_id: ObjectId
    requester_id: ObjectId
    requester_team_id: NotRequired[ObjectId | None]
    key_result_ids: NotRequired[list[ObjectId]]
    project_ids: NotRequired[list[ObjectId]]
    issue_ids: NotRequired[list[ObjectId]]
    customer_id: NotRequired[ObjectId | None]
    contact_id: NotRequired[ObjectId | None]
    source: NotRequired[Literal['manual']]
    external_reference: NotRequired[str | None]
    customer: NotRequired[Customer | None]
    contact: NotRequired[Contact | None]
    reviewer_id: NotRequired[ObjectId | None]
    reviewed_at: NotRequired[DateTime | None]
    expected_completion_at: NotRequired[DateTime | None]
    duplicate_of_id: NotRequired[ObjectId | None]
    duplicate_ids: NotRequired[list[ObjectId]]
    duplicate_of: NotRequired[RequestRef | None]
    duplicates: NotRequired[list[RequestRef]]
    team: NotRequired[TeamBasic | None]
    requester: NotRequired[User | None]
    requester_team: NotRequired[TeamBasic | None]
    reviewer: NotRequired[User | None]
    key_results: NotRequired[list[KeyResult]]
    projects: NotRequired[list[ProjectBasic]]
    issues: NotRequired[list[IssueBasic]]
    label_ids: NotRequired[list[ObjectId]]
    labels: NotRequired[list[CatalogLabel]]
    main_doc_id: NotRequired[ObjectId | None]
    main_doc: NotRequired[ContentBasic | None]
    is_subscribed: NotRequired[bool]
    subscriber_count: NotRequired[int]
    grant_info: NotRequired[GrantInfo | None]
    sla: NotRequired[SLASummaryResponse | None]
    created_at: NotRequired[DateTime]
    updated_at: NotRequired[DateTime]


class IssueChildrenItem(TypedDict):
    id: ObjectId
    code: str
    title: str
    description: NotRequired[str | None]
    status: IssueStatus
    priority: IssuePriority
    type: IssueType
    assignee: NotRequired[UserBasic | None]


class IssueBlocksItem(TypedDict):
    id: ObjectId
    code: str
    title: str
    description: NotRequired[str | None]
    status: IssueStatus
    priority: IssuePriority
    type: IssueType
    assignee: NotRequired[UserBasic | None]


class IssueBlockedByItem(TypedDict):
    id: ObjectId
    code: str
    title: str
    description: NotRequired[str | None]
    status: IssueStatus
    priority: IssuePriority
    type: IssueType
    assignee: NotRequired[UserBasic | None]


ReleaseCommitSha: TypeAlias = str


ReleaseStageType: TypeAlias = Literal['planned', 'started', 'in_progress', 'released', 'canceled']


class ReleasePipelineSummaryResponse(TypedDict):
    id: ObjectId
    name: str


class ReleaseStageResponse(TypedDict):
    id: ObjectId
    pipeline_id: ObjectId
    name: str
    type: ReleaseStageType
    position: int
    is_frozen: bool
    created_at: DateTime
    updated_at: DateTime


class ReleaseResponse(TypedDict):
    id: ObjectId
    pipeline_id: ObjectId
    name: str
    version: NotRequired[str | None]
    commit_sha: NotRequired[ReleaseCommitSha | None]
    stage_id: ObjectId
    stage_type: NotRequired[ReleaseStageType]
    target_date: NotRequired[DateTime | None]
    released_at: NotRequired[DateTime | None]
    assignee_id: NotRequired[ObjectId | None]
    notes_document_id: NotRequired[ObjectId | None]
    notes_summary: NotRequired[str | None]
    pipeline: NotRequired[ReleasePipelineSummaryResponse | None]
    stage: NotRequired[ReleaseStageResponse | None]
    assignee: NotRequired[UserBasic | None]
    main_doc: NotRequired[ContentBasic | None]
    issue_count: int
    completed_issue_count: int
    open_issue_count: int
    created_at: DateTime
    updated_at: DateTime


class IssueAgentSessionResponse(TypedDict):
    state: Literal['pending', 'working', 'needs_input', 'finished', 'failed', 'canceled']
    session_id: NotRequired[str]
    revision: int
    attempt: int
    updated_at: DateTime


class IssueTimeInStatus(TypedDict):
    current_status: IssueStatus
    current_status_entered_at: DateTime
    calculated_at: DateTime
    status_durations_ms: dict[str, int]


class Issue(TypedDict):
    id: ObjectId
    code: str
    title: str
    description: NotRequired[str | None]
    status: IssueStatus
    priority: IssuePriority
    type: IssueType
    team_id: ObjectId
    project_id: NotRequired[ObjectId | None]
    milestone_id: NotRequired[ObjectId | None]
    cycle_id: NotRequired[ObjectId | None]
    request_ids: NotRequired[list[ObjectId]]
    reporter_id: ObjectId
    assignee_id: NotRequired[ObjectId | None]
    delegate_id: NotRequired[ObjectId | None]
    delegated_by: NotRequired[ObjectId | None]
    delegated_via_agent_id: NotRequired[ObjectId | None]
    delegation_grant_id: NotRequired[ObjectId | None]
    delegation_revision: NotRequired[int]
    parent_id: NotRequired[ObjectId | None]
    time_estimate: NotRequired[int | None]
    due_date: NotRequired[DateTime | None]
    completed_at: NotRequired[DateTime | None]
    blocks_ids: NotRequired[list[ObjectId]]
    blocked_by_ids: NotRequired[list[ObjectId]]
    labels: NotRequired[list[CatalogLabel]]
    main_doc_id: NotRequired[ObjectId | None]
    progress: NotRequired[IssueProgress | None]
    development_summary: NotRequired[IssueDevelopmentSummary | None]
    team: NotRequired[TeamBasic]
    project: NotRequired[IssueProject | None]
    cycle: NotRequired[IssueCycle | None]
    milestone: NotRequired[Milestone | None]
    requests: NotRequired[list[Request]]
    reporter: NotRequired[UserBasic]
    assignee: NotRequired[UserBasic | None]
    delegate: NotRequired[UserBasic | None]
    delegated_via_agent: NotRequired[UserBasic | None]
    parent: NotRequired[IssueBasic | None]
    children: NotRequired[list[IssueChildrenItem]]
    blocks: NotRequired[list[IssueBlocksItem]]
    blocked_by: NotRequired[list[IssueBlockedByItem]]
    content: NotRequired[list[ContentBasic]]
    releases: NotRequired[list[ReleaseResponse]]
    main_doc: NotRequired[ContentBasic | None]
    grant_info: NotRequired[GrantInfo | None]
    sla: NotRequired[SLASummaryResponse | None]
    agent_session: NotRequired[IssueAgentSessionResponse]
    time_in_status: NotRequired[IssueTimeInStatus | None]
    is_subscribed: NotRequired[bool]
    subscriber_count: NotRequired[int]
    created_at: DateTime
    updated_at: DateTime


class MeResponseApp(TypedDict):
    id: str
    name: str


HomeViewType: TypeAlias = Literal['inbox', 'my_issues', 'all_issues', 'active_issues', 'current_cycle', 'projects', 'initiatives', 'favorite']


class HomeViewSelection(TypedDict):
    type: HomeViewType
    favorite_id: NotRequired[str]


HomeViewResponse = TypedDict("HomeViewResponse", {
    'effective': NotRequired[HomeViewSelection],
    'source': NotRequired[Literal['user', 'workspace', 'global']],
    'user': NotRequired[HomeViewSelection | None],
    'workspace': NotRequired[HomeViewSelection | None],
    'global': NotRequired[HomeViewSelection],
})


PreferenceScope: TypeAlias = Literal['user', 'workspace']


PreferencePlatform: TypeAlias = Literal['web', 'pwa', 'macos', 'ios']


class PreferenceEntry(TypedDict):
    v: object
    at: str
    by: NotRequired[PreferencePlatform]


class PreferencesDocument(TypedDict):
    scope: PreferenceScope
    version: int
    rev: int
    persisted: bool
    values: dict[str, PreferenceEntry]
    updated_at: NotRequired[str | None]


class PreferencesResponse(TypedDict):
    user: PreferencesDocument
    workspace: PreferencesDocument | None


class MeResponse(TypedDict):
    user: UserBasic
    app: NotRequired[MeResponseApp]
    installation_id: NotRequired[str]
    default_home_view: NotRequired[HomeViewResponse]
    preferences: NotRequired[PreferencesResponse]


class OAuthErrorBody(TypedDict):
    error: str
    error_description: NotRequired[str]


class OAuthTokenResponse(TypedDict):
    access_token: str
    token_type: str
    expires_in: int
    refresh_token: NotRequired[str]
    scope: NotRequired[str]
    actor: NotRequired[Literal['user', 'app']]
    installation_id: NotRequired[str]
    app_user_id: NotRequired[str]
    workspace_id: NotRequired[str]
