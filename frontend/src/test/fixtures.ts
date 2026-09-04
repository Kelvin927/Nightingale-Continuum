import type {
  AuditEvent,
  AuditVerification,
  DeltaLens,
  DeliveryReadiness,
  EvidenceReview,
  Entry,
  EntryVersion,
  Glance,
  Identity,
  Patient,
  PolicyEvaluation,
  ResolvedProvenance,
  Viewer,
  Workspace,
} from "../types";

export const identities: Identity[] = [
  { id: "user-clinician", display_name: "Dr Lina", role: "clinician" },
  { id: "user-staff", display_name: "Nurse Noor", role: "staff" },
  { id: "user-patient", display_name: "Maya Chen", role: "patient" },
  { id: "user-admin", display_name: "Ari Admin", role: "admin" },
];

export const patient: Patient = {
  id: "patient-1",
  display_name: "Maya Chen",
  initials: "MC",
  synthetic_record_number: "SYN-0001",
  date_of_birth: "1988-05-12",
  pronouns: "she/her",
  synthetic: true,
};

export const versionOne: EntryVersion = {
  id: "version-1",
  version: 1,
  content: "Medication changed from 10 mg to 20 mg. Renal lab pending.",
  content_hash: "a".repeat(64),
  created_by: "user-clinician",
  change_reason: "Initial version",
  reverted_from_version_id: null,
  created_at: "2026-08-25T08:00:00Z",
};

export const versionTwo: EntryVersion = {
  ...versionOne,
  id: "version-2",
  version: 2,
  content: "Medication remains at 20 mg. Renal lab reviewed.",
  content_hash: "b".repeat(64),
  change_reason: "Reviewed result",
  created_at: "2026-08-26T08:00:00Z",
};

export const clinicianEntry: Entry = {
  id: "entry-clinician",
  patient_id: patient.id,
  entry_type: "clinician_note",
  title: "Assessment and plan",
  owner_role: "clinician",
  author: identities[0],
  visibility: "internal",
  trust_state: "clinician_confirmed",
  source_uri: "entry://entry-clinician/versions/1",
  current_version: 1,
  retention_tier: "hot",
  created_at: "2026-08-25T08:00:00Z",
  updated_at: "2026-08-25T08:00:00Z",
  version: versionOne,
  comment_threads: [
    {
      id: "thread-1",
      title: "Confirm renal result",
      resolved: false,
      resolved_by: null,
      comments: [
        {
          id: "comment-1",
          body: "I will verify this today.",
          author: identities[1],
          mentions: ["user-clinician"],
          assigned_to: "user-clinician",
          created_at: "2026-08-25T09:00:00Z",
        },
      ],
    },
  ],
};

export const aiEntry: Entry = {
  ...clinicianEntry,
  id: "entry-ai",
  entry_type: "ai_doctor_consult_summary",
  title: "AI consult draft",
  owner_role: "system",
  author: null,
  visibility: "internal",
  trust_state: "ai_proposed",
  source_uri: null,
  retention_tier: "warm",
  comment_threads: [],
};

export const patientEntry: Entry = {
  ...clinicianEntry,
  id: "entry-patient",
  entry_type: "patient_insight",
  title: "What matters to me",
  owner_role: "patient",
  author: identities[2],
  visibility: "patient",
  trust_state: "human_authored",
  retention_tier: "cold",
  comment_threads: undefined,
};

export const patientInstruction: Entry = {
  ...clinicianEntry,
  id: "entry-patient-instruction",
  entry_type: "patient_instruction",
  title: "Your medication plan",
  owner_role: "clinician",
  author: identities[0],
  visibility: "patient",
  trust_state: "clinician_confirmed",
  comment_threads: [],
};

export const deliveryReadiness: DeliveryReadiness = {
  contacts: [
    {
      id: "contact-whatsapp",
      channel: "whatsapp",
      masked_destination: "WhatsApp ending 4567",
      consent_status: "granted",
      preferred: true,
      active: true,
      verified: true,
    },
  ],
  deliveries: [],
  safety_contract: (
    "Provider acceptance is not patient delivery. Sent snapshots remain immutable; "
    + "corrections preserve the original side by side."
  ),
};

export const workspace: Workspace = {
  patient,
  viewer: { id: identities[0].id, role: "clinician" },
  entries: [clinicianEntry, aiEntry, patientEntry, patientInstruction],
  conflicts: [
    {
      id: "conflict-1",
      conflict_type: "dose_mismatch",
      summary: "Two dose values require reconciliation.",
      status: "open",
      disposition: null,
    },
  ],
};

export const glance: Glance = {
  patient_mode: false,
  source_revision: 1,
  projection_updated_at: "2026-08-26T08:00:00Z",
  safety_rule: "Live order is deterministic; feedback remains shadow-only.",
  policy_version: "safe-beta-v1",
  groups: {
    act_now: [
      {
        id: "highlight-1",
        title: "Medication detail to reconcile",
        risk_level: "critical",
        risk_reason: "Medication changes require review",
        entity_tags: ["medication", "dose_change", "critical_result", "extra"],
        evidence_support: 0.88,
        trust_state: "ai_proposed",
        status: "suggested",
        rank_score: 8.4,
        score_factors: { risk: 8 },
        shadow_score_factors: { bounded_feedback: 0.1 },
        ranking_mode: "fixed_safety_with_shadow_learning",
        provenance_span_id: "span-1",
        policy_version: "safe-beta-v1",
      },
    ],
    watch: [
      {
        id: "highlight-2",
        title: "Follow-up result",
        risk_level: "medium",
        risk_reason: "Open follow-up requires ownership",
        entity_tags: ["follow_up"],
        evidence_support: 0.98,
        trust_state: "clinician_confirmed",
        status: "accepted",
        rank_score: 3.1,
        score_factors: { risk: 2.5 },
        shadow_score_factors: { bounded_feedback: 0 },
        ranking_mode: "fixed_safety_with_shadow_learning",
        provenance_span_id: "span-2",
        policy_version: "safe-beta-v1",
      },
    ],
    awaiting: [
      {
        id: "task-1",
        title: "Review renal result",
        urgency: "high",
        assigned_to: "user-clinician",
        due_at: "2026-08-27T08:00:00Z",
        source_entry_id: "entry-clinician",
      },
      {
        id: "task-2",
        title: "Assign follow-up owner",
        urgency: "medium",
        assigned_to: null,
        due_at: null,
        source_entry_id: null,
      },
    ],
  },
};

export const patientGlance: Glance = {
  patient_mode: true,
  safety_rule: glance.safety_rule,
  groups: {
    act_now: [],
    watch: [
      {
        id: "patient-item-1",
        title: "Your medication plan",
        trust_state: "clinician_confirmed",
        entry_type: "patient_instruction",
        content: "Continue the confirmed dose and call if symptoms worsen.",
      },
    ],
    awaiting: [],
  },
};

export const delta: DeltaLens = {
  comparison: { from: "24 Aug", to: "26 Aug", entry_count: 3 },
  new: [
    {
      label: "Renal result",
      evidence: {
        entry_id: clinicianEntry.id,
        provenance_span_id: "span-2",
        quote: "Renal lab reviewed",
        trust_state: "clinician_confirmed",
      },
    },
  ],
  changed_or_conflicting: [{ label: "Medication dose", evidence: null }],
  persistent: [{ label: "Hypertension", evidence: null }],
  resolved: [],
  unknown: [],
  interpretation: "Descriptive change only.",
  causal_guardrail: "This comparison is descriptive and does not identify causation.",
};

export const provenance: ResolvedProvenance = {
  span_id: "span-1",
  source_entry_id: clinicianEntry.id,
  source_version_id: versionOne.id,
  source_version: 1,
  source_kind: "clinician_note",
  source_uri: "entry://entry-clinician/versions/1",
  start_offset: 0,
  end_offset: 41,
  quote: "Medication changed from 10 mg to 20 mg.",
  content: versionOne.content,
  content_hash: versionOne.content_hash,
  verified: true,
  source_is_current: true,
  current_version_id: versionOne.id,
  current_version: 1,
  current_content: versionOne.content,
  current_content_hash: versionOne.content_hash,
  changes_since_source: [],
};

export const evaluation: PolicyEvaluation = {
  estimand: "Expected accepted highlight feedback under the shadow policy",
  observations: 64,
  effective_sample_size: 41.2,
  behavior_value: 0.69,
  doubly_robust_value: 0.72,
  standard_error: 0.04,
  ci_95: [0.64, 0.8],
  overlap_warning: false,
  exposure_bias_warning: false,
  status: "shadow_evaluable",
  assumptions: ["Consistency", "Conditional exchangeability", "Positivity"],
};

export const verification: AuditVerification = {
  valid: true,
  events_checked: 42,
  first_invalid_sequence: null,
  reason: null,
};

export const auditEvents: AuditEvent[] = [
  {
    id: "event-1",
    sequence: 1,
    actor_id: "user-clinician",
    action: "entry_created",
    object_type: "entry",
    object_id: "entry-clinician-long-id",
    object_version: 1,
    request_id: "request-1",
    metadata: {},
    event_hash: "c".repeat(64),
    previous_hash: "0".repeat(64),
    created_at: "2026-08-25T08:00:00Z",
  },
  {
    id: "event-2",
    sequence: 2,
    actor_id: null,
    action: "retention_evaluated",
    object_type: "clinic",
    object_id: "clinic-1",
    object_version: null,
    request_id: "request-2",
    metadata: {},
    event_hash: "d".repeat(64),
    previous_hash: "c".repeat(64),
    created_at: "2026-08-26T08:00:00Z",
  },
];

export const evidenceReview: EvidenceReview = {
  intent: "medication",
  answer_state: "supported",
  summary: "Found 1 source-bound signal for this medication review.",
  claims: [
    {
      text: "Medication detail to reconcile",
      risk_level: "critical",
      risk_reason: "Medication changes require review",
      trust_state: "ai_proposed",
      evidence_support: 0.88,
      provenance_span_id: "span-1",
      source_entry_id: "entry-clinician",
      quote: "Medication changed from 10 mg to 20 mg.",
    },
  ],
  open_actions: [
    {
      title: "Review renal result",
      urgency: "high",
      assigned_to: "user-clinician",
      due_at: "2026-08-27T08:00:00Z",
      source_entry_id: "entry-clinician",
    },
  ],
  conflicts: ["Two dose values require reconciliation."],
  abstention_reason: null,
  provider: "local-evidence-reviewer-v1",
  safety_notice: "Decision support only. Verify the cited record before clinical action.",
};

export function viewer(role: Viewer["role"]): Viewer {
  const identity = identities.find((item) => item.role === role) ?? identities[0];
  return {
    ...identity,
    clinic_id: "clinic-1",
    patient_id: role === "patient" ? patient.id : null,
    authentication_mode: "demo-header",
  };
}
