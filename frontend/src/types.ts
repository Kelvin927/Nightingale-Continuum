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

export interface VersionSnapshot {
  version_id: string;
  version: number;
  content: string;
  content_hash: string;
  created_at: string;
}

export interface VersionConflictDetail {
  code: "version_conflict";
  message: string;
  expected_version: number;
  current_version: number;
  current_version_id: string;
  base_snapshot: VersionSnapshot | null;
  current_snapshot: VersionSnapshot | null;
  proposed_content: string | null;
  proposed_content_hash: string | null;
  merge_assistance: {
    status:
      | "identical"
      | "current_only"
      | "proposed_only"
      | "non_overlapping_draft"
      | "manual_review_required";
    auto_merge_safe: boolean;
    merged_content: string | null;
    conflicting_hunks: Array<{
      base_start_line: number;
      base_end_line: number;
      proposed_text: string;
      current_text: string;
    }>;
  } | null;
  resolution: string;
}

export interface RegenerationResult {
  entry_id: string;
  predecessor_entry_id: string;
  status: "new_ai_proposal_created";
  provider: string;
  provider_status: string;
  provider_failure_code: string | null;
  flags: string[];
  preservation_receipt: {
    unchanged: boolean;
    protected_state_hash: string;
    protected_highlight_count: number;
    completed_task_count: number;
    resolved_conflict_count: number;
    released_delivery_count: number;
    reviewed_signal_count: number;
    meaning: string;
  };
}

export interface DeliveryContact {
  id: string;
  channel: "whatsapp" | "sms" | "voice" | "email";
  masked_destination: string;
  consent_status: string;
  preferred: boolean;
  active: boolean;
  verified: boolean;
}

export interface DeliveryItem {
  id: string;
  source_entry_id: string;
  source_version_id: string;
  source_is_current: boolean;
  correction_for_id: string | null;
  channel: string;
  masked_destination: string;
  content_snapshot: string;
  content_hash: string;
  status: "queued" | "accepted" | "delivered" | "failed" | "superseded";
  receipt_meaning: string;
  attempt_count: number;
  failure_code?: string | null;
  approved_by?: string;
  approval_evidence?: Record<string, boolean>;
  created_at: string;
  accepted_at: string | null;
  delivered_at: string | null;
  superseded_at: string | null;
}

export interface DeliveryReadiness {
  contacts: DeliveryContact[];
  deliveries: DeliveryItem[];
  safety_contract: string;
}

export interface ConflictSource {
  state: "available" | "unavailable";
  version_id: string;
  entry_id?: string;
  entry_title?: string;
  entry_type?: string;
  owner_role?: string;
  trust_state?: string;
  author?: Identity | null;
  version?: number;
  content?: string;
  content_hash?: string;
  source_is_current?: boolean;
  created_at?: string;
}

export interface ConflictItem {
  id: string;
  conflict_type: string;
  summary: string;
  status: string;
  disposition: string | null;
  resolution: {
    decision: string | null;
    rationale: string | null;
    resolved_by: string | null;
  };
  left: ConflictSource;
  right: ConflictSource;
  decision_policy: string;
  created_at: string;
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
  evidence_support: number;
  evidence_support_band?: "low" | "medium" | "high";
  evidence_support_interpretation?: string;
  trust_state: string;
  status: string;
  rank_score: number;
  score_factors: Record<string, number>;
  shadow_score_factors: { bounded_feedback: number };
  ranking_mode: "fixed_safety_with_shadow_learning";
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
  source_is_current: boolean;
  current_version_id: string;
  current_version: number;
  current_content: string;
  current_content_hash: string;
  changes_since_source: Array<{ operation: string; before: string; after: string }>;
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
  exposure_bias_warning: boolean;
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
  evidence_support: number;
  evidence_support_band?: "low" | "medium" | "high";
  evidence_support_interpretation?: string;
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

export interface LanguageSpan {
  language_tag: string;
  start_offset: number;
  end_offset: number;
  confidence: number;
}

export interface TranscriptSegment {
  id: string;
  sequence: number;
  chunk_id: string;
  start_ms: number;
  end_ms: number;
  speaker_label: string;
  text: string;
  language_spans: LanguageSpan[];
  asr_confidence: number;
  audio_quality: number;
  processing_state: "supported" | "human_review_required" | "abstained";
  processing_reasons: string[];
  status: "provisional" | "final" | "retracted";
  correction_of_segment_id: string | null;
  received_at: string;
}

export interface SafetySignal {
  id: string;
  source_segment_id: string;
  signal_type: string;
  normalized_label: string;
  evidence_quote: string;
  source_start_offset: number;
  source_end_offset: number;
  severity: "critical" | "high";
  evidence_quality: string;
  review_state: "provisional" | "confirmed" | "dismissed" | "source_retracted";
  review_rationale: string | null;
  reviewed_by: string | null;
  detected_at: string;
  reviewed_at: string | null;
}

export interface StreamingCapture {
  id: string;
  patient_id: string;
  interaction_type: string;
  status: "streaming" | "finalized" | "finalized_with_abstention";
  latest_sequence: number;
  stream_contract_version: string;
  capabilities: {
    adapter_mode: string;
    audio_transcription_active: boolean;
    clinic_enabled_languages: string[];
    provider_supported_language_bases: string[];
    provider_supported_language_tags: string[];
    unsupported_language_policy: string;
    speaker_attribution: string;
    quality_policy: string;
  };
  segments: TranscriptSegment[];
  safety_signals: SafetySignal[];
  safety_signal_count: number;
  finalized_entry_id: string | null;
  provider_status: string | null;
  provider_failure_code: string | null;
  started_at: string;
  finalized_at: string | null;
  assurance_boundary: string;
  ingestion?: {
    segment_id: string;
    replayed: boolean;
    new_safety_signal_ids: string[];
    server_processing_ms: number;
    latency_scope: string;
  };
  finalization?: { replayed: boolean; entry_id: string };
}
