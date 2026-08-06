/**
 * THOX CX Fabric contracts — typed mirror, v0.1.0.
 *
 * SOURCE OF TRUTH: `packages/contracts` in ttracx/thox-customer-experience-fabric
 * (`@thox-cx/contracts`, JSON Schemas under `schemas/`, TS mirror under `src/`).
 * This file is a SUBSET vendored into the app, not a parallel design. It exists because this
 * app cannot depend on a package in another private repo yet; when that dependency is possible,
 * delete this file and import from `@thox-cx/contracts` instead — the names and shapes here are
 * chosen to make that a pure import swap.
 *
 * DO NOT widen these types locally. If a field is missing, change the contract upstream and
 * re-mirror; a divergent copy is worse than a missing field, because both sides keep compiling
 * while they disagree about what an approval means.
 *
 * Mirrored: TaskEnvelope, AgentResponse, Artifact, Handoff, ApprovalRequest/Decision,
 * EventEnvelope + EVENT_TYPES. Omitted (not used by this surface): ContentItem,
 * EvaluationScorecard, ExternalAction, PolicyEvaluation, AgentTeamManifest.
 */

export const CONTRACTS_VERSION = "0.1.0";

export type Id = string;
/** RFC 3339 UTC. Stored as a string to stay byte-identical to the contract on the wire. */
export type Timestamp = string;

export type Sensitivity = "public" | "internal" | "confidential" | "restricted";
export type Priority = "low" | "normal" | "high" | "urgent";
export type AutonomyLevel = 0 | 1 | 2 | 3 | 4 | 5;
export type Capability = string;

export type SourceKind =
	| "thoxbrain_record"
	| "product_spec"
	| "campaign_brief"
	| "web_page"
	| "release_note"
	| "faq"
	| "legal_statement"
	| "executive_statement";

export interface SourceReference {
	kind: SourceKind;
	ref: string;
	retrieved_at?: Timestamp;
	confidence?: number;
}

export interface TaskOrigin {
	channel: string;
	/** false for all external/untrusted content. Untrusted content must never override policy. */
	trusted: boolean;
	external_platform?: string | null;
	external_object_id?: string | null;
}

export interface TaskEnvelope {
	task_id: Id;
	tenant_id: Id;
	session_id?: Id;
	parent_team_id?: Id;
	correlation_id?: Id;
	objective: string;
	capabilities: Capability[];
	sensitivity: Sensitivity;
	origin: TaskOrigin;
	priority: Priority;
	deadline?: Timestamp | null;
	autonomy_level?: AutonomyLevel;
	input?: Record<string, unknown>;
}

export type HandoffReason =
	| "capability_gap"
	| "low_confidence"
	| "compliance"
	| "memory_escalation"
	| "device_ownership"
	| "tool_ownership"
	| "background_finding"
	| "human_escalation";

export interface Handoff {
	reason: HandoffReason;
	target_capability: Capability;
	target_agent_id?: Id;
	note?: string;
}

export interface Artifact {
	artifact_id: Id;
	type: string;
	ref?: string;
	sensitivity?: Sensitivity;
}

export type AgentResponseStatus =
	| "completed"
	| "needs_handoff"
	| "blocked"
	| "failed"
	| "awaiting_approval";

export interface AgentResponse {
	task_id: Id;
	agent_id: Id;
	run_id?: Id;
	status: AgentResponseStatus;
	confidence: number;
	summary?: string;
	artifacts?: Artifact[];
	memory_references?: Id[];
	source_references?: SourceReference[];
	telemetry?: Record<string, unknown>;
	handoff?: Handoff | null;
}

export type ActionType =
	| "internal_summary"
	| "campaign_brief"
	| "social_post_draft"
	| "social_schedule"
	| "social_publish"
	| "pricing_statement"
	| "product_spec"
	| "shipping_fulfillment"
	| "partnership_announcement"
	| "public_faq_reply"
	| "account_support_reply"
	| "complaint_refund_reply"
	| "legal_regulatory"
	| "delete_public_content"
	| "update_production_website"
	| "create_github_issue"
	| "push_code_branch"
	| "merge_pr";

export type ApproverRole =
	| "marketing"
	| "customer_experience_lead"
	| "product_owner_and_compliance"
	| "executive"
	| "approved_template"
	| "automatic";

export interface ApprovalRequest {
	approval_request_id: Id;
	tenant_id: Id;
	action_type: ActionType;
	required_approver: ApproverRole;
	subject_ref: string;
	requested_by_agent_id?: Id;
	source_references?: SourceReference[];
	evaluation_scorecard_ref?: string | null;
	created_at: Timestamp;
}

export interface ApprovalDecision {
	approval_decision_id: Id;
	approval_request_id: Id;
	decision: "approved" | "rejected";
	/** Human OIDC subject. Never an agent id — an agent approving its own work is not an approval. */
	decided_by: string;
	approver_role?: ApproverRole;
	note?: string;
	decided_at: Timestamp;
}

export const EVENT_TYPES = [
	"signal.received",
	"signal.classified",
	"task.created",
	"task.assigned",
	"team.spawned",
	"team.completed",
	"agent.started",
	"agent.completed",
	"handoff.requested",
	"handoff.completed",
	"artifact.created",
	"knowledge.retrieved",
	"knowledge.contradiction",
	"policy.allowed",
	"policy.blocked",
	"approval.requested",
	"approval.granted",
	"approval.rejected",
	"content.scheduled",
	"content.published",
	"content.failed",
	"message.received",
	"message.drafted",
	"message.sent",
	"message.escalated",
	"feedback.clustered",
	"ux.opportunity.created",
	"experiment.started",
	"experiment.completed",
	"development.issue.proposed",
	"brain.sync.started",
	"brain.sync.completed",
	"incident.opened",
	"incident.resolved",
] as const;

export type EventType = (typeof EVENT_TYPES)[number];

export function isEventType(value: string): value is EventType {
	return (EVENT_TYPES as readonly string[]).includes(value);
}

export interface EventEnvelope {
	event_id: Id;
	type: EventType;
	tenant_id: Id;
	correlation_id?: Id;
	run_id?: Id;
	team_id?: Id;
	agent_id?: Id;
	occurred_at: Timestamp;
	payload?: Record<string, unknown>;
	outbox: { sequence: number; committed: boolean; dispatched_at?: Timestamp | null };
}
