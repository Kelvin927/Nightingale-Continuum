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
