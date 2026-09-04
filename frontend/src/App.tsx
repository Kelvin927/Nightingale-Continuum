import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertCircle,
  Bell,
  Bot,
  ChevronDown,
  ClipboardPlus,
  FlaskConical,
  HeartPulse,
  Menu,
  MessageCircleMore,
  Mic,
  KeyRound,
  PanelLeftClose,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  UserRound,
  UsersRound,
  X,
} from "lucide-react";

import { ApiError, api } from "./api";
import { AdminPanel } from "./components/AdminPanel";
import { ConcurrentEditDialog } from "./components/ConcurrentEditDialog";
import { ConflictReviewDialog } from "./components/ConflictReviewDialog";
import {
  CommentDialog,
  HistoryDialog,
  NoteDialog,
  ScribeDialog,
} from "./components/Dialogs";
import { DeltaLens } from "./components/DeltaLens";
import { DeliveryCenter } from "./components/DeliveryCenter";
import { GlanceBoard } from "./components/GlanceBoard";
import { PatientAccessDialog } from "./components/PatientAccessDialog";
import { ProvenanceDrawer } from "./components/ProvenanceDrawer";
import { RegenerationDialog } from "./components/RegenerationDialog";
import { ReviewCopilotDialog } from "./components/ReviewCopilot";
import { ResearchPanel } from "./components/ResearchPanel";
import { Timeline } from "./components/Timeline";
import type {
  AuditEvent,
  AuditVerification,
  ConflictItem,
  DeliveryItem,
  DeliveryReadiness,
  DeltaLens as DeltaLensType,
  EvidenceReview,
  Entry,
  EntryVersion,
  Glance,
  Identity,
  Patient,
  PatientAccessClaim,
  PatientAccessProof,
  PolicyEvaluation,
  RegenerationResult,
  ResolvedProvenance,
  Role,
  StreamingCapture,
  VersionConflictDetail,
  Viewer,
  Workspace,
} from "./types";

type Page = "care" | "research" | "admin";

const roleIcons: Record<Role, React.ComponentType<{ size?: number }>> = {
  clinician: HeartPulse,
  staff: UsersRound,
  patient: UserRound,
  admin: ShieldCheck,
};

function friendlyError(reason: unknown): string {
  if (reason instanceof ApiError && typeof reason.detail === "object" && reason.detail !== null) {
    const detail = reason.detail as { message?: string };
    return detail.message ?? reason.message;
  }
  return reason instanceof Error ? reason.message : "Something went wrong.";
}

function isVersionConflictDetail(detail: unknown): detail is VersionConflictDetail {
  if (!detail || typeof detail !== "object") return false;
  const candidate = detail as Partial<VersionConflictDetail>;
  return candidate.code === "version_conflict"
    && typeof candidate.current_version === "number"
    && typeof candidate.resolution === "string";
}

function AppSkeleton() {
  return (
    <div className="app-skeleton" aria-label="Loading care note">
      <div className="skeleton-sidebar" />
      <div className="skeleton-main"><i /><i /><div><i /><i /><i /></div><i /><i /></div>
    </div>
  );
}

export default function App() {
  const [identities, setIdentities] = useState<Identity[]>([]);
  const [userId, setUserId] = useState(() => localStorage.getItem("continuum-demo-user") ?? "user-clinician-lina");
  const [viewer, setViewer] = useState<Viewer | null>(null);
  const [patients, setPatients] = useState<Patient[]>([]);
  const [patientId, setPatientId] = useState<string | null>(null);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [glance, setGlance] = useState<Glance | null>(null);
  const [delta, setDelta] = useState<DeltaLensType | null>(null);
  const [delivery, setDelivery] = useState<DeliveryReadiness | null>(null);
  const [deliveryBusy, setDeliveryBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState<Page>("care");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [roleMenuOpen, setRoleMenuOpen] = useState(false);
  const [activeSource, setActiveSource] = useState<ResolvedProvenance | null>(null);
  const [sourceLoading, setSourceLoading] = useState(false);
  const [busyHighlight, setBusyHighlight] = useState<string | null>(null);
  const [noteDialog, setNoteDialog] = useState<{ open: boolean; entry: Entry | null }>({ open: false, entry: null });
  const [commentEntry, setCommentEntry] = useState<Entry | null>(null);
  const [historyEntry, setHistoryEntry] = useState<Entry | null>(null);
  const [versions, setVersions] = useState<EntryVersion[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [scribeOpen, setScribeOpen] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [reviewResult, setReviewResult] = useState<EvidenceReview | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [evaluation, setEvaluation] = useState<PolicyEvaluation | null>(null);
  const [verification, setVerification] = useState<AuditVerification | null>(null);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [retentionBusy, setRetentionBusy] = useState(false);
  const [activeConflict, setActiveConflict] = useState<ConflictItem | null>(null);
  const [conflictBusy, setConflictBusy] = useState(false);
  const [editConflict, setEditConflict] = useState<{
    entry: Entry;
    detail: VersionConflictDetail;
  } | null>(null);
  const [regenerationEntry, setRegenerationEntry] = useState<Entry | null>(null);
  const [patientAccessOpen, setPatientAccessOpen] = useState(false);
  const toastTimeout = useRef<number | null>(null);

  const selectedIdentity = identities.find((item) => item.id === userId) ?? null;
  const currentPatient = workspace?.patient ?? patients.find((patient) => patient.id === patientId) ?? null;
  const currentRole = viewer?.role ?? selectedIdentity?.role ?? "clinician";
  const RoleIcon = roleIcons[currentRole];
  const actionContext = useRef({
    userId,
    patientId,
    role: currentRole,
    noteDialog,
    commentEntry,
    historyEntry,
    scribeOpen,
    activeConflict,
    editConflict,
  });
  actionContext.current = {
    userId,
    patientId,
    role: currentRole,
    noteDialog,
    commentEntry,
    historyEntry,
    scribeOpen,
    activeConflict,
    editConflict,
  };

  const collaborator = useMemo(() => {
    const targetRole = currentRole === "staff" ? "clinician" : "staff";
    const identity = identities.find((item) => item.role === targetRole);
    return identity ? { id: identity.id, name: identity.display_name } : null;
  }, [currentRole, identities]);

  const announce = useCallback((message: string) => {
    setToast(message);
    if (toastTimeout.current !== null) window.clearTimeout(toastTimeout.current);
    toastTimeout.current = window.setTimeout(() => {
      setToast(null);
      toastTimeout.current = null;
    }, 3200);
  }, []);

  useEffect(() => () => {
    if (toastTimeout.current !== null) window.clearTimeout(toastTimeout.current);
  }, []);

  const loadWorkspace = useCallback(async (activeUser: string, activePatient: string, activeRole: Role) => {
    const [nextWorkspace, nextGlance, nextDelta, nextDelivery] = await Promise.all([
      api.workspace(activeUser, activePatient),
      api.glance(activeUser, activePatient),
      activeRole === "patient" ? Promise.resolve(null) : api.delta(activeUser, activePatient),
      api.deliveryReadiness(activeUser, activePatient),
    ]);
    setWorkspace(nextWorkspace);
    setGlance(nextGlance);
    setDelta(nextDelta);
    setDelivery(nextDelivery);
  }, []);

  const reload = useCallback(
    async (activeUser: string, activePatient: string, activeRole: Role) => {
      await loadWorkspace(activeUser, activePatient, activeRole);
    },
    [loadWorkspace],
  );

  useEffect(() => {
    let cancelled = false;
    api.identities().then((payload) => {
      if (cancelled) return;
      setIdentities(payload.identities);
      if (!payload.identities.some((identity) => identity.id === userId)) {
        setUserId(payload.identities[0]?.id ?? "");
      }
    }).catch((reason) => setError(friendlyError(reason)));
    return () => { cancelled = true; };
  }, [userId]);

  useEffect(() => {
    if (!userId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setActiveSource(null);
    setActiveConflict(null);
    setEditConflict(null);
    setRegenerationEntry(null);
    setPatientAccessOpen(false);
    setPatientId(null);
    setWorkspace(null);
    setGlance(null);
    setDelta(null);
    setDelivery(null);
    Promise.all([api.me(userId), api.patients(userId)])
      .then(async ([nextViewer, patientPayload]) => {
        if (cancelled) return;
        setViewer(nextViewer);
        setPatients(patientPayload.patients);
        const nextPatient = patientPayload.patients.find((item) => item.id === nextViewer.patient_id) ?? patientPayload.patients[0];
        setPatientId(nextPatient?.id ?? null);
        if (nextPatient) await loadWorkspace(userId, nextPatient.id, nextViewer.role);
        if (cancelled) return;
        if (nextViewer.role === "patient") setPage("care");
      })
      .catch((reason) => !cancelled && setError(friendlyError(reason)))
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, [loadWorkspace, userId]);

  useEffect(() => {
    if (!viewer || page !== "research") return;
    api.policyEvaluation(viewer.id).then(setEvaluation).catch((reason) => setError(friendlyError(reason)));
  }, [page, viewer]);

  const loadAdmin = useCallback(async (adminId: string) => {
    const [nextVerification, events] = await Promise.all([
      api.auditVerification(adminId),
      api.auditEvents(adminId),
    ]);
    setVerification(nextVerification);
    setAuditEvents(events.events);
  }, []);

  useEffect(() => {
    if (page === "admin" && viewer?.role === "admin") {
      loadAdmin(viewer.id).catch((reason) => setError(friendlyError(reason)));
    }
  }, [loadAdmin, page, viewer]);

  useEffect(() => {
    if (!viewer || !patientId || page !== "care" || glance?.source_revision === undefined) return;
    let cancelled = false;
    const activeRevision = glance.source_revision;
    const timer = window.setInterval(async () => {
      try {
        const latest = await api.glance(viewer.id, patientId);
        if (
          cancelled
          || latest.source_revision === undefined
          || latest.source_revision === activeRevision
        ) return;
        await loadWorkspace(viewer.id, patientId, viewer.role);
        announce("New collaboration evidence synchronized.");
      } catch {
        // A transient poll failure must not interrupt the active review session.
      }
    }, 4000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [announce, glance?.source_revision, loadWorkspace, page, patientId, viewer]);

  function switchIdentity(identity: Identity) {
    localStorage.setItem("continuum-demo-user", identity.id);
    setUserId(identity.id);
    setRoleMenuOpen(false);
    setSidebarOpen(false);
  }

  async function openSource(spanId: string) {
    setSourceLoading(true);
    try {
      const source = await api.provenance(userId, spanId);
      setActiveSource(source);
      window.setTimeout(() => {
        const element = document.getElementById(`entry-${source.source_entry_id}`);
        element?.scrollIntoView({ behavior: "smooth", block: "center" });
        element?.focus({ preventScroll: true });
      }, 120);
    } catch (reason) {
      setError(friendlyError(reason));
    } finally {
      setSourceLoading(false);
    }
  }

  function scrollToEntry(entryId: string) {
    document.getElementById(`entry-${entryId}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  async function sendFeedback(highlightId: string, action: "accept" | "reject" | "pin") {
    const active = actionContext.current;
    if (!active.patientId) return;
    setBusyHighlight(highlightId);
    try {
      await api.feedback(active.userId, highlightId, action);
      await reload(active.userId, active.patientId, active.role);
      announce(`${action.charAt(0).toUpperCase() + action.slice(1)} recorded. Similar ranking updated within safety bounds.`);
    } catch (reason) {
      setError(friendlyError(reason));
    } finally {
      setBusyHighlight(null);
    }
  }

  async function saveNote(payload: { title: string; content: string; entryType: string; visibility: string }) {
    const active = actionContext.current;
    if (!active.patientId || !active.noteDialog.open) return;
    if (active.noteDialog.entry) {
      try {
        await api.editEntry(active.userId, active.noteDialog.entry.id, {
          content: payload.content,
          expected_version: active.noteDialog.entry.current_version,
          reason: "Manual role-owned update",
        });
      } catch (reason) {
        if (reason instanceof ApiError && isVersionConflictDetail(reason.detail)) {
          setEditConflict({ entry: active.noteDialog.entry, detail: reason.detail });
          await reload(active.userId, active.patientId, active.role);
          return;
        }
        throw reason;
      }
      announce("A new immutable version was saved.");
    } else {
      await api.createEntry(active.userId, active.patientId, {
        entry_type: payload.entryType,
        title: payload.title,
        content: payload.content,
        visibility: payload.visibility,
      });
      announce("The longitudinal entry was added.");
    }
    await reload(active.userId, active.patientId, active.role);
  }

  function openReviewedMergeDraft(content: string) {
    const conflict = actionContext.current.editConflict;
    if (!conflict) return;
    const current = conflict.detail.current_snapshot;
    if (!current) return;
    const { entry } = conflict;
    setEditConflict(null);
    setNoteDialog({
      open: true,
      entry: {
        ...entry,
        current_version: current.version,
        version: {
          ...entry.version,
          id: current.version_id,
          version: current.version,
          content,
          content_hash: current.content_hash,
          created_at: current.created_at,
        },
      },
    });
  }

  async function regenerateProposal(transcript: string): Promise<RegenerationResult> {
    const active = actionContext.current;
    const predecessor = regenerationEntry;
    if (!active.patientId || !predecessor) {
      throw new Error("No AI proposal is selected for regeneration.");
    }
    const result = await api.regenerateScribe(active.userId, predecessor.id, {
      expected_version: predecessor.current_version,
      transcript,
      source_uri: `regeneration://synthetic/${predecessor.id}/v${predecessor.current_version}`,
    });
    await reload(active.userId, active.patientId, active.role);
    announce("A separate AI proposal was created; protected human state is unchanged.");
    return result;
  }

  async function startThread(title: string, body: string, assignedTo: string | null) {
    const active = actionContext.current;
    if (!active.commentEntry || !active.patientId) return;
    await api.createThread(active.userId, active.commentEntry.id, {
      title,
      body,
      mentions: assignedTo ? [assignedTo] : [],
      assigned_to: assignedTo,
    });
    await reload(active.userId, active.patientId, active.role);
    announce("Review thread added with an auditable handoff.");
  }

  async function openHistory(entry: Entry) {
    setHistoryEntry(entry);
    setHistoryLoading(true);
    try {
      const payload = await api.versions(userId, entry.id);
      setVersions(payload.versions);
    } catch (reason) {
      setError(friendlyError(reason));
    } finally {
      setHistoryLoading(false);
    }
  }

  async function restoreVersion(targetVersion: number) {
    const active = actionContext.current;
    if (!active.historyEntry || !active.patientId) return;
    await api.revert(
      active.userId,
      active.historyEntry.id,
      targetVersion,
      active.historyEntry.current_version,
    );
    await reload(active.userId, active.patientId, active.role);
    announce(`Version ${targetVersion} restored as a new auditable version.`);
  }

  async function submitScribe(interactionType: string, transcript: string) {
    const active = actionContext.current;
    if (!active.patientId || !active.scribeOpen) {
      return {
        receipt: {},
        flags: [],
        clinicalAnchorCount: 0,
        clinicalAnchorsPreserved: false,
        providerStatus: "failed_closed",
        providerFailureCode: "inactive_capture_context",
      };
    }
    const payload = await api.ingestScribe(active.userId, {
      patient_id: active.patientId,
      interaction_type: interactionType,
      transcript,
      source_uri: `session://synthetic/capture-${Date.now()}`,
    });
    await reload(active.userId, active.patientId, active.role);
    return {
      receipt: payload.redaction_receipt.entity_counts,
      flags: payload.flags,
      clinicalAnchorCount: payload.redaction_receipt.clinical_anchor_count,
      clinicalAnchorsPreserved: payload.redaction_receipt.clinical_anchors_preserved,
      providerStatus: payload.provider_status,
      providerFailureCode: payload.provider_failure_code,
    };
  }

  async function runStreamingSafetyScenario(
    interactionType: string,
  ): Promise<StreamingCapture> {
    const active = actionContext.current;
    if (!active.patientId || !active.scribeOpen) {
      throw new Error("No active patient capture context.");
    }
    const capture = await api.startCapture(
      active.userId,
      active.patientId,
      interactionType,
    );
    const stamp = Date.now();
    await api.appendCaptureSegment(active.userId, capture.id, {
      chunk_id: `synthetic-intro-${stamp}`,
      sequence: 1,
      start_ms: 0,
      end_ms: 2_400,
      speaker_label: "clinician",
      text: "How have you been since the dose change?",
      language_spans: [
        {
          language_tag: "en-SG",
          start_offset: 0,
          end_offset: 40,
          confidence: 0.97,
        },
      ],
      asr_confidence: 0.95,
      audio_quality: 0.92,
      correction_of_segment_id: null,
    });
    const text = "Saya allergic to penicillin, bo pian.";
    const englishStart = text.indexOf(" allergic");
    const hokkienStart = text.indexOf("bo pian");
    return api.appendCaptureSegment(active.userId, capture.id, {
      chunk_id: `synthetic-safety-${stamp}`,
      sequence: 2,
      start_ms: 120_000,
      end_ms: 123_000,
      speaker_label: "patient",
      text,
      language_spans: [
        {
          language_tag: "ms-SG",
          start_offset: 0,
          end_offset: englishStart,
          confidence: 0.93,
        },
        {
          language_tag: "en-SG",
          start_offset: englishStart,
          end_offset: hokkienStart,
          confidence: 0.96,
        },
        {
          language_tag: "nan",
          start_offset: hokkienStart,
          end_offset: text.length,
          confidence: 0.84,
        },
      ],
      asr_confidence: 0.91,
      audio_quality: 0.86,
      correction_of_segment_id: null,
    });
  }

  async function reviewStreamingSignal(
    captureId: string,
    signalId: string,
    decision: "confirm" | "dismiss",
  ): Promise<StreamingCapture> {
    const active = actionContext.current;
    await api.reviewSafetySignal(
      active.userId,
      signalId,
      decision,
      decision === "confirm"
        ? "Confirmed directly with the patient during the consult."
        : "Dismissed after clinician review of the source interaction.",
    );
    return api.capture(active.userId, captureId);
  }

  async function finalizeStreamingCapture(captureId: string): Promise<StreamingCapture> {
    const active = actionContext.current;
    const result = await api.finalizeCapture(active.userId, captureId);
    if (active.patientId) {
      await reload(active.userId, active.patientId, active.role);
    }
    return result;
  }

  async function resolveActiveConflict(
    decision: "confirm_left" | "confirm_right" | "escalate_unresolved",
    rationale: string,
    sourcesReviewed: boolean,
  ) {
    const active = actionContext.current;
    if (!active.activeConflict || !active.patientId) return;
    setConflictBusy(true);
    try {
      const resolved = await api.resolveConflict(
        active.userId,
        active.activeConflict.id,
        decision,
        rationale,
        sourcesReviewed,
      );
      setActiveConflict(resolved);
      await reload(active.userId, active.patientId, active.role);
      announce(
        decision === "escalate_unresolved"
          ? "Contradiction preserved and escalated without selecting a winner."
          : "Conflict decision recorded against both immutable sources.",
      );
    } finally {
      setConflictBusy(false);
    }
  }

  async function askEvidenceReview(question: string, activePatientId: string) {
    const active = actionContext.current;
    setReviewBusy(true);
    try {
      setReviewResult(await api.evidenceReview(active.userId, activePatientId, question));
    } catch (reason) {
      setError(friendlyError(reason));
    } finally {
      setReviewBusy(false);
    }
  }

  async function runRetention() {
    const active = actionContext.current;
    if (active.role !== "admin") return;
    setRetentionBusy(true);
    try {
      const result = await api.runRetention(active.userId);
      announce(`Retention policy evaluated; ${result.changes.length} tier changes recorded.`);
      const refreshes: Promise<unknown>[] = [loadAdmin(active.userId)];
      if (active.patientId) {
        refreshes.push(reload(active.userId, active.patientId, active.role));
      }
      await Promise.all(refreshes);
    } catch (reason) {
      setError(friendlyError(reason));
    } finally {
      setRetentionBusy(false);
    }
  }

  async function queuePatientDelivery(
    entry: Entry,
    contactId: string,
    purpose: DeliveryItem["communication_purpose"],
    attestations: {
      clinical: boolean;
      identity: boolean;
      medication: boolean;
      appointment: boolean;
    },
  ) {
    const active = actionContext.current;
    if (active.role !== "clinician" || !active.patientId || entry.patient_id !== active.patientId) return;
    setDeliveryBusy(true);
    try {
      const next = await api.queueDelivery(active.userId, entry.id, {
        contact_id: contactId,
        expected_version: entry.current_version,
        idempotency_key: `delivery-${entry.id}-v${entry.current_version}-${contactId}`,
        confirm_clinical_review: attestations.clinical,
        confirm_patient_identity: attestations.identity,
        confirm_medication_and_dose: attestations.medication,
        communication_purpose: purpose,
        confirm_appointment_details: attestations.appointment,
        acknowledgement_window_minutes: 1_440,
      });
      setDelivery(next);
      announce("Approved copy queued. Provider acceptance is still unconfirmed.");
    } catch (reason) {
      setError(friendlyError(reason));
    } finally {
      setDeliveryBusy(false);
    }
  }

  async function queuePatientCorrection(
    original: DeliveryItem,
    entry: Entry,
    contactId: string,
    attestations: {
      clinical: boolean;
      identity: boolean;
      medication: boolean;
      appointment: boolean;
    },
  ) {
    const active = actionContext.current;
    if (active.role !== "clinician" || !active.patientId || entry.patient_id !== active.patientId) return;
    setDeliveryBusy(true);
    try {
      const next = await api.queueCorrection(active.userId, original.id, {
        replacement_entry_id: entry.id,
        contact_id: contactId,
        expected_version: entry.current_version,
        idempotency_key: `correction-${original.id}-v${entry.current_version}-${contactId}`,
        confirm_clinical_review: attestations.clinical,
        confirm_patient_identity: attestations.identity,
        confirm_medication_and_dose: attestations.medication,
        communication_purpose: original.communication_purpose,
        confirm_appointment_details: attestations.appointment,
        acknowledgement_window_minutes: original.follow_up?.acknowledgement_window_minutes ?? 1_440,
      });
      setDelivery(next);
      announce("Correction queued as a new immutable, clinician-approved copy.");
    } catch (reason) {
      setError(friendlyError(reason));
    } finally {
      setDeliveryBusy(false);
    }
  }

  async function recordSyntheticReceipt(
    item: DeliveryItem,
    outcome: "queued" | "accepted" | "delivered" | "failed",
  ) {
    const active = actionContext.current;
    if (active.role !== "admin" || !active.patientId) return;
    setDeliveryBusy(true);
    try {
      const next = await api.transitionDelivery(active.userId, item.id, {
        outcome,
        ...(outcome === "accepted"
          ? { provider_message_id: `synthetic-${item.id}` }
          : {}),
      });
      setDelivery(next);
      announce(outcome === "accepted"
        ? "Provider acceptance recorded; patient delivery remains unconfirmed."
        : "Synthetic patient delivery receipt recorded.");
    } catch (reason) {
      setError(friendlyError(reason));
    } finally {
      setDeliveryBusy(false);
    }
  }

  async function acknowledgeAppointmentDelivery(item: DeliveryItem) {
    const active = actionContext.current;
    if (
      active.role !== "patient"
      || !active.patientId
      || item.patient_id !== active.patientId
    ) return;
    setDeliveryBusy(true);
    try {
      const next = await api.acknowledgeDelivery(active.userId, item.id);
      setDelivery(next);
      announce("Appointment invitation acknowledged by the authenticated patient.");
    } catch (reason) {
      setError(friendlyError(reason));
    } finally {
      setDeliveryBusy(false);
    }
  }

  async function sweepAppointmentFollowUps() {
    const active = actionContext.current;
    if (active.role === "patient" || !active.patientId) return;
    setDeliveryBusy(true);
    try {
      const next = await api.escalateDeliveryFollowUps(active.userId, active.patientId);
      setDelivery(next);
      announce(next.escalated_count
        ? `${next.escalated_count} appointment follow-up escalated to the care team.`
        : "No failed or overdue appointment invitations require escalation.");
    } catch (reason) {
      setError(friendlyError(reason));
    } finally {
      setDeliveryBusy(false);
    }
  }

  async function issuePatientAccess(payload: {
    contactId: string;
    purpose: PatientAccessClaim["purpose"];
    ttlMinutes: number;
  }): Promise<PatientAccessClaim> {
    const active = actionContext.current;
    if (!active.patientId || !["clinician", "staff"].includes(active.role)) {
      throw new Error("Only an authorized care-team member can issue patient access.");
    }
    return api.issuePatientAccess(active.userId, active.patientId, {
      contact_id: payload.contactId,
      purpose: payload.purpose,
      ttl_minutes: payload.ttlMinutes,
    });
  }

  async function redeemPatientAccess(payload: {
    claimToken: string;
    recordNumber: string;
    dateOfBirth: string;
  }): Promise<PatientAccessProof> {
    const active = actionContext.current;
    if (!active.patientId) throw new Error("No active patient access context.");
    const deviceBinding = "synthetic-browser-rehearsal-v1";
    const grant = await api.redeemPatientAccess({
      claim_token: payload.claimToken,
      synthetic_record_number: payload.recordNumber,
      date_of_birth: payload.dateOfBirth,
      device_binding: deviceBinding,
    });
    const [sessionViewer, patientWorkspace] = await Promise.all([
      api.patientSessionMe(grant.session_token, deviceBinding),
      api.patientSessionWorkspace(grant.session_token, deviceBinding, grant.patient_id),
    ]);
    const scopeValid = sessionViewer.authentication_mode === "channel_claim"
      && sessionViewer.role === "patient"
      && sessionViewer.patient_id === active.patientId
      && patientWorkspace.viewer.role === "patient"
      && patientWorkspace.patient.id === active.patientId
      && patientWorkspace.entries.every((entry) => entry.visibility === "patient");
    if (!scopeValid) {
      throw new Error("Patient access failed closed because the returned scope was not patient-only.");
    }
    return {
      viewer: sessionViewer,
      workspace: patientWorkspace,
      grant_expires_at: grant.expires_at,
      email_required: grant.email_required,
    };
  }

  if (loading && !workspace) return <AppSkeleton />;

  return (
    <div className="app-shell">
      <header className="topbar">
        <button className="mobile-menu-button" onClick={() => setSidebarOpen(true)} aria-label="Open navigation"><Menu /></button>
        <div className="brand-lockup"><div className="brand-mark" aria-hidden="true"><span /><span /><i /></div><div><strong>Nightingale</strong><small>Continuum</small></div></div>
        <div className="topbar-search"><Search size={16} /><span>Search this longitudinal record</span><kbd>/</kbd></div>
        <div className="topbar-actions"><span className="synthetic-badge"><ShieldCheck size={13} />Synthetic data</span><button className="icon-button" aria-label="Notifications"><Bell size={18} /><i /></button><div className="role-switcher"><button className="role-trigger" onClick={() => setRoleMenuOpen((value) => !value)} aria-expanded={roleMenuOpen}><span className={`avatar role-${currentRole}`}><RoleIcon size={16} /></span><span><strong>{viewer?.display_name ?? "Loading"}</strong><small>{currentRole}</small></span><ChevronDown size={14} /></button>{roleMenuOpen && <div className="role-menu"><span>View as demo role</span>{identities.map((identity) => { const Icon = roleIcons[identity.role]; return <button key={identity.id} className={identity.id === userId ? "active" : ""} onClick={() => switchIdentity(identity)}><span className={`avatar role-${identity.role}`}><Icon size={15} /></span><span><strong>{identity.display_name}</strong><small>{identity.role}</small></span>{identity.id === userId && <ShieldCheck size={14} />}</button>; })}<p>Identity, role, and clinic scope are resolved by the server.</p></div>}</div></div>
      </header>

      <aside className={`sidebar ${sidebarOpen ? "sidebar-open" : ""}`}>
        <div className="sidebar-mobile-heading"><strong>Navigate</strong><button className="icon-button" onClick={() => setSidebarOpen(false)}><PanelLeftClose /></button></div>
        <nav aria-label="Primary navigation">
          <span className="nav-label">Workspace</span>
          <button className={page === "care" ? "active" : ""} onClick={() => { setPage("care"); setSidebarOpen(false); }}><Activity size={17} />Care note<span>{workspace?.entries.length ?? 0}</span></button>
          {currentRole !== "patient" && <button className={page === "research" ? "active" : ""} onClick={() => { setPage("research"); setSidebarOpen(false); }}><FlaskConical size={17} />Policy lab<span className="beta-pill">BETA</span></button>}
          {currentRole === "admin" && <button className={page === "admin" ? "active" : ""} onClick={() => { setPage("admin"); setSidebarOpen(false); }}><ShieldCheck size={17} />Trust ops</button>}
        </nav>
        <div className="patient-nav"><span className="nav-label">Synthetic patients</span>{patients.map((patient) => <button key={patient.id} className={patient.id === patientId ? "patient-active" : ""}><span className="patient-avatar">{patient.initials}</span><span><strong>{patient.display_name}</strong><small>{patient.synthetic_record_number}</small></span></button>)}</div>
        <div className="sidebar-footer"><div className="privacy-pulse"><i /><span><strong>Privacy boundary active</strong><small>Local deterministic provider</small></span></div><p>Prototype only. Not for clinical use.</p></div>
      </aside>
      {sidebarOpen && <button className="mobile-sidebar-scrim" onClick={() => setSidebarOpen(false)} aria-label="Close navigation" />}

      <main className="main-content">
        {error && <div className="global-error" role="alert"><AlertCircle size={17} /><span>{error}</span><button onClick={() => setError(null)}><X size={16} /></button></div>}
        {page === "care" && workspace && glance && currentPatient && (
          <>
            <section className="patient-header">
              <div className="patient-identity"><span className="patient-avatar large">{currentPatient.initials}</span><div><div className="patient-name-line"><h1>{currentPatient.display_name}</h1><span>synthetic</span></div><p>{currentPatient.synthetic_record_number} <i /> DOB {new Date(currentPatient.date_of_birth).toLocaleDateString("en-SG", { day: "2-digit", month: "short", year: "numeric" })} <i /> {currentPatient.pronouns}</p></div></div>
              <div className="patient-actions">
                {currentRole !== "patient" && <span className="live-sync"><i />Live evidence sync</span>}
                {currentRole !== "patient" && <button className="secondary-button" onClick={() => { setReviewResult(null); setReviewOpen(true); }}><Sparkles size={16} />Evidence review</button>}
                {["clinician", "staff"].includes(currentRole) && delivery?.contacts.some((contact) => contact.preferred && contact.active && contact.verified && contact.consent_status === "granted") && <button className="secondary-button" onClick={() => setPatientAccessOpen(true)}><KeyRound size={16} />Phone-only access</button>}
                <button className="secondary-button" onClick={() => setScribeOpen(true)}><Mic size={16} />Capture consult</button>
                {currentRole !== "admin" && <button className="primary-button" onClick={() => setNoteDialog({ open: true, entry: null })}><ClipboardPlus size={16} />{currentRole === "patient" ? "Share an insight" : "Add note"}</button>}
              </div>
            </section>

            <GlanceBoard glance={glance} role={currentRole} busyHighlight={busyHighlight} onSource={openSource} onFeedback={sendFeedback} onTaskSource={scrollToEntry} />

            {delivery && (
              <DeliveryCenter
                readiness={delivery}
                role={currentRole}
                patientFacingEntries={workspace.entries.filter((entry) =>
                  entry.visibility === "patient"
                  && entry.owner_role === "clinician"
                  && entry.trust_state === "clinician_confirmed"
                  && ["patient_summary", "patient_instruction"].includes(entry.entry_type))}
                busy={deliveryBusy}
                onQueue={queuePatientDelivery}
                onCorrect={queuePatientCorrection}
                onTransition={recordSyntheticReceipt}
                onAcknowledge={acknowledgeAppointmentDelivery}
                onSweep={sweepAppointmentFollowUps}
              />
            )}

            <div className="care-layout">
              <Timeline entries={workspace.entries} role={currentRole} activeSource={activeSource} onHistory={openHistory} onEdit={(entry) => setNoteDialog({ open: true, entry })} onComment={setCommentEntry} onRegenerate={setRegenerationEntry} />
              {currentRole !== "patient" && (
                <aside className="care-rail">
                  {delta && <DeltaLens delta={delta} onSource={openSource} />}
                  <div className="rail-card">
                    <div className="rail-heading">
                      <span><AlertCircle size={16} />Conflict watch</span>
                      <strong>{workspace.conflicts.filter((item) => item.status === "open").length}</strong>
                    </div>
                    {workspace.conflicts.map((conflict) => (
                      <article key={conflict.id}>
                        <span>{conflict.conflict_type.replaceAll("_", " ")}</span>
                        <p>{conflict.summary}</p>
                        <button onClick={() => setActiveConflict(conflict)}>Compare both sources</button>
                      </article>
                    ))}
                  </div>
                  <div className="rail-card assurance-card">
                    <div className="rail-heading"><span><Sparkles size={16} />Trust contract</span></div>
                    <ul>
                      <li><ShieldCheck size={14} />Exact source on every highlight</li>
                      <li><RefreshCw size={14} />Reverts never erase history</li>
                      <li><Bot size={14} />AI drafts stay unconfirmed</li>
                    </ul>
                  </div>
                  <div className="rail-card">
                    <div className="rail-heading"><span><MessageCircleMore size={16} />Open collaboration</span></div>
                    <p className="rail-stat">
                      {workspace.entries.reduce((count, entry) => count + (entry.comment_threads?.filter((thread) => !thread.resolved).length ?? 0), 0)}
                      <small>unresolved review threads</small>
                    </p>
                  </div>
                </aside>
              )}
            </div>
          </>
        )}
        {page === "research" && <ResearchPanel evaluation={evaluation} />}
        {page === "admin" && currentRole === "admin" && <AdminPanel verification={verification} events={auditEvents} retentionBusy={retentionBusy} onRetention={runRetention} />}
      </main>

      {sourceLoading && <div className="source-loading"><RefreshCw className="spin" size={16} />Verifying source...</div>}
      {activeSource && <ProvenanceDrawer source={activeSource} onClose={() => setActiveSource(null)} />}
      {noteDialog.open && <NoteDialog role={currentRole} editing={noteDialog.entry} onClose={() => setNoteDialog({ open: false, entry: null })} onSubmit={saveNote} />}
      {commentEntry && <CommentDialog entry={commentEntry} collaborator={collaborator} onClose={() => setCommentEntry(null)} onSubmit={startThread} />}
      {historyEntry && <HistoryDialog entry={historyEntry} versions={versions} loading={historyLoading} onClose={() => { setHistoryEntry(null); setVersions([]); }} onRevert={restoreVersion} />}
      {scribeOpen && <ScribeDialog role={currentRole} onClose={() => setScribeOpen(false)} onSubmit={submitScribe} onRunStreamScenario={runStreamingSafetyScenario} onReviewStreamSignal={reviewStreamingSignal} onFinalizeStream={finalizeStreamingCapture} />}
      {activeConflict && <ConflictReviewDialog conflict={activeConflict} role={currentRole} busy={conflictBusy} onClose={() => setActiveConflict(null)} onResolve={resolveActiveConflict} />}
      {editConflict && <ConcurrentEditDialog detail={editConflict.detail} onClose={() => setEditConflict(null)} onUseDraft={openReviewedMergeDraft} />}
      {regenerationEntry && <RegenerationDialog entry={regenerationEntry} onClose={() => setRegenerationEntry(null)} onRegenerate={regenerateProposal} />}
      {patientAccessOpen && currentPatient && delivery?.contacts.find((contact) => contact.preferred && contact.active && contact.verified && contact.consent_status === "granted") && <PatientAccessDialog patient={currentPatient} contact={delivery.contacts.find((contact) => contact.preferred && contact.active && contact.verified && contact.consent_status === "granted")!} onClose={() => setPatientAccessOpen(false)} onIssue={issuePatientAccess} onRedeem={redeemPatientAccess} />}
      {reviewOpen && currentPatient && <ReviewCopilotDialog result={reviewResult} busy={reviewBusy} onClose={() => setReviewOpen(false)} onAsk={(question) => askEvidenceReview(question, currentPatient.id)} onSource={(spanId) => { setReviewOpen(false); void openSource(spanId); }} onTaskSource={(entryId) => { setReviewOpen(false); scrollToEntry(entryId); }} />}
      {toast && <div className="toast" role="status"><ShieldCheck size={17} />{toast}</div>}
    </div>
  );
}
