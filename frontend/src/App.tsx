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
import {
  CommentDialog,
  HistoryDialog,
  NoteDialog,
  ScribeDialog,
} from "./components/Dialogs";
import { DeltaLens } from "./components/DeltaLens";
import { GlanceBoard } from "./components/GlanceBoard";
import { ProvenanceDrawer } from "./components/ProvenanceDrawer";
import { ReviewCopilotDialog } from "./components/ReviewCopilot";
import { ResearchPanel } from "./components/ResearchPanel";
import { Timeline } from "./components/Timeline";
import type {
  AuditEvent,
  AuditVerification,
  DeltaLens as DeltaLensType,
  EvidenceReview,
  Entry,
  EntryVersion,
  Glance,
  Identity,
  Patient,
  PolicyEvaluation,
  ResolvedProvenance,
  Role,
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
  });
  actionContext.current = {
    userId,
    patientId,
    role: currentRole,
    noteDialog,
    commentEntry,
    historyEntry,
    scribeOpen,
  };

  const collaborator = useMemo(() => {
    const targetRole = currentRole === "staff" ? "clinician" : "staff";
    const identity = identities.find((item) => item.role === targetRole);
    return identity ? { id: identity.id, name: identity.display_name } : null;
  }, [currentRole, identities]);

  const announce = useCallback((message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(null), 3200);
  }, []);

  const loadWorkspace = useCallback(async (activeUser: string, activePatient: string, activeRole: Role) => {
    const [nextWorkspace, nextGlance, nextDelta] = await Promise.all([
      api.workspace(activeUser, activePatient),
      api.glance(activeUser, activePatient),
      activeRole === "patient" ? Promise.resolve(null) : api.delta(activeUser, activePatient),
    ]);
    setWorkspace(nextWorkspace);
    setGlance(nextGlance);
    setDelta(nextDelta);
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
    setPatientId(null);
    setWorkspace(null);
    setGlance(null);
    setDelta(null);
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
      await api.editEntry(active.userId, active.noteDialog.entry.id, {
        content: payload.content,
        expected_version: active.noteDialog.entry.current_version,
        reason: "Manual role-owned update",
      });
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
      return { receipt: {}, flags: [], clinicalAnchorCount: 0, clinicalAnchorsPreserved: false };
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
    };
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
                <button className="secondary-button" onClick={() => setScribeOpen(true)}><Mic size={16} />Capture consult</button>
                {currentRole !== "admin" && <button className="primary-button" onClick={() => setNoteDialog({ open: true, entry: null })}><ClipboardPlus size={16} />{currentRole === "patient" ? "Share an insight" : "Add note"}</button>}
              </div>
            </section>

            <GlanceBoard glance={glance} role={currentRole} busyHighlight={busyHighlight} onSource={openSource} onFeedback={sendFeedback} onTaskSource={scrollToEntry} />

            <div className="care-layout">
              <Timeline entries={workspace.entries} role={currentRole} activeSource={activeSource} onHistory={openHistory} onEdit={(entry) => setNoteDialog({ open: true, entry })} onComment={setCommentEntry} />
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
                        <button onClick={() => document.querySelector("#timeline")?.scrollIntoView({ behavior: "smooth" })}>Review evidence</button>
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
      {scribeOpen && <ScribeDialog role={currentRole} onClose={() => setScribeOpen(false)} onSubmit={submitScribe} />}
      {reviewOpen && currentPatient && <ReviewCopilotDialog result={reviewResult} busy={reviewBusy} onClose={() => setReviewOpen(false)} onAsk={(question) => askEvidenceReview(question, currentPatient.id)} onSource={(spanId) => { setReviewOpen(false); void openSource(spanId); }} onTaskSource={(entryId) => { setReviewOpen(false); scrollToEntry(entryId); }} />}
      {toast && <div className="toast" role="status"><ShieldCheck size={17} />{toast}</div>}
    </div>
  );
}
