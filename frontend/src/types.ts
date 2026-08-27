export type Role = "patient" | "staff" | "clinician" | "admin";

export interface Identity {
  id: string;
  display_name: string;
  role: Role;
}

export interface Viewer extends Identity {
  clinic_id: string;
  patient_id: string | null;
  authentication_mode: string;
}

export interface Patient {
  id: string;
  display_name: string;
  initials: string;
  synthetic_record_number: string;
  date_of_birth: string;
  pronouns: string;
  synthetic: boolean;
}

export interface EntryVersion {
  id: string;
  version: number;
  content: string;
  content_hash: string;
  created_by: string | null;
  change_reason: string;
  reverted_from_version_id: string | null;
  created_at: string;
}

export interface CommentItem {
  id: string;
  body: string;
  author: Identity;
  mentions: string[];
  assigned_to: string | null;
  created_at: string;
}

export interface CommentThread {
  id: string;
  title: string;
  resolved: boolean;
  resolved_by: string | null;
  comments: CommentItem[];
}

export interface Entry {
  id: string;
  patient_id: string;
  entry_type: string;
  title: string;
  owner_role: string;
  author: Identity | null;
  visibility: "internal" | "patient";
  trust_state: string;
  source_uri: string | null;
  current_version: number;
  retention_tier: "hot" | "warm" | "cold";
  created_at: string;
  updated_at: string;
  version: EntryVersion;
  comment_threads?: CommentThread[];
}

export interface ConflictItem {
  id: string;
  conflict_type: string;
  summary: string;
  status: string;
  disposition: string | null;
}

export interface Workspace {
  patient: Patient;
  viewer: { id: string; role: Role };
  entries: Entry[];
  conflicts: ConflictItem[];
}

export interface HighlightItem {
  id: string;
  title: string;
  risk_level: "critical" | "high" | "medium" | "low";
  risk_reason: string;
  entity_tags: string[];
  confidence: number;
  trust_state: string;
  status: string;
  rank_score: number;
  score_factors: Record<string, number>;
  provenance_span_id: string;
  policy_version: string;
}

export interface TaskItem {
  id: string;
  title: string;
  urgency: string;
  assigned_to: string | null;
  due_at: string | null;
  source_entry_id: string | null;
}

export interface Glance {
  patient_mode: boolean;
  groups: {
    act_now: Array<HighlightItem | PatientFacingItem>;
    watch: Array<HighlightItem | PatientFacingItem>;
    awaiting: TaskItem[];
  };
  safety_rule: string;
  policy_version?: string;
  source_revision?: number;
  projection_updated_at?: string;
}

export interface PatientFacingItem {
  id: string;
  title: string;
  trust_state: string;
  entry_type: string;
  content: string;
}

export interface ResolvedProvenance {
  span_id: string;
  source_entry_id: string;
  source_version_id: string;
  source_version: number;
  source_kind: string;
  source_uri: string;
  start_offset: number;
  end_offset: number;
  quote: string;
  content: string;
  content_hash: string;
  verified: boolean;
}

export interface PolicyEvaluation {
  estimand: string;
  observations: number;
  effective_sample_size: number;
  behavior_value: number | null;
  doubly_robust_value: number | null;
  standard_error: number | null;
  ci_95: [number, number] | null;
  overlap_warning: boolean;
  status: string;
  assumptions: string[];
}

export interface AuditVerification {
  valid: boolean;
  events_checked: number;
  first_invalid_sequence: number | null;
  reason: string | null;
}

export interface AuditEvent {
  id: string;
  sequence: number;
  actor_id: string | null;
  action: string;
  object_type: string;
  object_id: string;
  object_version: number | null;
  request_id: string;
  metadata: Record<string, unknown>;
  event_hash: string;
  previous_hash: string;
  created_at: string;
}

export interface DeltaEvidence {
  entry_id: string;
  provenance_span_id: string;
  quote: string;
  trust_state: string;
}

export interface DeltaItem {
  label: string;
  observed_on?: string;
  classification?: string;
  evidence: DeltaEvidence | null;
}

export interface DeltaLens {
  comparison: { from: string; to: string; entry_count: number } | null;
  new: DeltaItem[];
  changed_or_conflicting: DeltaItem[];
  persistent: DeltaItem[];
  resolved: DeltaItem[];
  unknown: string[];
  interpretation: string;
  causal_guardrail: string;
}

export interface ReviewClaim {
  text: string;
  risk_level: "critical" | "high" | "medium" | "low";
  risk_reason: string;
  trust_state: string;
  confidence: number;
  provenance_span_id: string;
  source_entry_id: string;
  quote: string;
}

export interface ReviewAction {
  title: string;
  urgency: string;
  assigned_to: string | null;
  due_at: string | null;
  source_entry_id: string | null;
}

export interface EvidenceReview {
  intent: "overview" | "medication" | "change" | "action" | "safety";
  answer_state: "supported" | "workflow_only" | "insufficient_evidence";
  summary: string;
  claims: ReviewClaim[];
  open_actions: ReviewAction[];
  conflicts: string[];
  abstention_reason: string | null;
  provider: string;
  safety_notice: string;
}
