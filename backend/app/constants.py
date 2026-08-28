"""Shared role, risk, trust, and retention vocabulary."""

ROLES = {"patient", "staff", "clinician", "admin"}

AI_ENTRY_TYPES = {
    "doctor_consult": "ai_doctor_consult_summary",
    "nurse_consult": "ai_nurse_consult_summary",
    "patient_session": "ai_patient_session_summary",
}

PATIENT_VISIBLE_ENTRY_TYPES = {
    "patient_summary",
    "patient_instruction",
    "patient_insight",
}

CLINICIAN_APPROVED_PATIENT_ENTRY_TYPES = {
    "patient_summary",
    "patient_instruction",
}

SAFETY_ENTITY_TAGS = {"allergy", "medication", "dose_change", "critical_result"}
NON_DECAY_ENTITY_TAGS = SAFETY_ENTITY_TAGS | {"active_diagnosis"}

RISK_WEIGHT = {
    "critical": 8.0,
    "high": 5.0,
    "medium": 2.5,
    "low": 1.0,
}

RISK_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

POLICY_VERSION = "safe-beta-v1"
REDACTION_VERSION = "continuum-redactor-v1"

# These are policy-defined evidence-support scores, not calibrated probabilities
# of clinical correctness. Exact immutable provenance is mandatory for every
# highlight; trust state determines the remaining bounded support contribution.
EVIDENCE_SUPPORT_BY_TRUST = {
    "ai_proposed": 0.65,
    "human_authored": 0.75,
    "staff_verified": 0.85,
    "clinician_confirmed": 0.95,
    "superseded": 0.0,
}

# The prototype display policy is deterministic. Surfaced feedback therefore
# has propensity 1.0, and policy evaluation must retain an exposure-bias warning.
DETERMINISTIC_DISPLAY_PROPENSITY = 1.0
