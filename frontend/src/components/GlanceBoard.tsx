import {
  ArrowDownToLine,
  Check,
  ChevronRight,
  CircleAlert,
  Clock3,
  Eye,
  Link2,
  Pin,
  ShieldAlert,
  X,
} from "lucide-react";

import type { Glance, HighlightItem, PatientFacingItem, Role, TaskItem } from "../types";
import { TrustBadge } from "./TrustBadge";

type FeedbackAction = "accept" | "reject" | "pin";

interface Props {
  glance: Glance;
  role: Role;
  busyHighlight: string | null;
  onSource: (spanId: string) => void;
  onFeedback: (highlightId: string, action: FeedbackAction) => void;
  onTaskSource: (entryId: string) => void;
}

function isHighlight(item: HighlightItem | PatientFacingItem): item is HighlightItem {
  return "risk_level" in item;
}

function riskLabel(value: string) {
  return value === "critical" ? "Critical" : value.charAt(0).toUpperCase() + value.slice(1);
}

function supportBand(item: HighlightItem) {
  if (item.evidence_support_band) return item.evidence_support_band;
  if (item.evidence_support < 0.6) return "low";
  if (item.evidence_support < 0.85) return "medium";
  return "high";
}

function HighlightCard({
  item,
  role,
  busy,
  onSource,
  onFeedback,
}: {
  item: HighlightItem | PatientFacingItem;
  role: Role;
  busy: boolean;
  onSource: (spanId: string) => void;
  onFeedback: (highlightId: string, action: FeedbackAction) => void;
}) {
  if (!isHighlight(item)) {
    return (
      <article className="glance-card patient-facing-card">
        <div className="glance-card-topline">
          <span className="risk-pill low">Care instruction</span>
          <TrustBadge state={item.trust_state} />
        </div>
        <h3>{item.title}</h3>
        <p>{item.content}</p>
      </article>
    );
  }

  const canTrain = role === "clinician" || role === "staff";
  const needsReview = item.trust_state === "ai_proposed" && item.status === "suggested";
  const shadowFeedback = item.shadow_score_factors?.bounded_feedback ?? 0;
  const band = supportBand(item);
  return (
    <article className={`glance-card risk-${item.risk_level}`}>
      <div className="glance-card-topline">
        <span className={`risk-pill ${item.risk_level}`}>
          {item.risk_level === "critical" ? <ShieldAlert size={12} /> : <CircleAlert size={12} />}
          {riskLabel(item.risk_level)}
        </span>
        <TrustBadge state={item.trust_state} />
      </div>
      <h3>{item.title}</h3>
      <p>{item.risk_reason}</p>
      <div className="tag-row" aria-label="Clinical entities">
        {item.entity_tags.slice(0, 3).map((tag) => (
          <span key={tag}>{tag.replaceAll("_", " ")}</span>
        ))}
      </div>
      <div className="glance-card-footer">
        <button className="source-link" onClick={() => onSource(item.provenance_span_id)}>
          <Link2 size={14} /> Exact source
        </button>
        <span
          className={`confidence confidence-${band}`}
          title={item.evidence_support_interpretation ?? "Policy-defined evidence support; not a correctness probability."}
        >
          {band} support · {Math.round(item.evidence_support * 100)}/100
        </span>
      </div>
      <details className="score-explainer">
        <summary>Why this order</summary>
        <p>
          Live rank {item.rank_score.toFixed(2)} is fixed by policy. Bounded feedback {shadowFeedback.toFixed(2)} is evaluated in shadow and is not applied. Neither score is a probability.
        </p>
      </details>
      {canTrain && needsReview && (
        <div className="feedback-row" aria-label="Review AI suggestion">
          <button disabled={busy} onClick={() => onFeedback(item.id, "accept")}>
            <Check size={14} /> Accept
          </button>
          <button disabled={busy} onClick={() => onFeedback(item.id, "pin")}>
            <Pin size={14} /> Pin
          </button>
          <button disabled={busy} onClick={() => onFeedback(item.id, "reject")}>
            <X size={14} /> Reject
          </button>
        </div>
      )}
    </article>
  );
}

function TaskCard({ item, onTaskSource }: { item: TaskItem; onTaskSource: (entryId: string) => void }) {
  return (
    <article className="glance-card task-card">
      <div className="glance-card-topline">
        <span className={`risk-pill ${item.urgency === "high" ? "high" : "medium"}`}>
          <Clock3 size={12} /> {item.urgency}
        </span>
        <span className="task-status">Open</span>
      </div>
      <h3>{item.title}</h3>
      <p>{item.assigned_to ? "Assigned with explicit ownership" : "Needs an owner"}</p>
      {item.source_entry_id && (
        <button className="source-link" onClick={() => onTaskSource(item.source_entry_id!)}>
          <ArrowDownToLine size={14} /> Related note
        </button>
      )}
    </article>
  );
}

export function GlanceBoard({
  glance,
  role,
  busyHighlight,
  onSource,
  onFeedback,
  onTaskSource,
}: Props) {
  const actNow = glance.groups.act_now.slice(0, 3);
  const watch = glance.groups.watch.slice(0, 2);
  const awaiting = glance.groups.awaiting.slice(0, 3);
  const hidden =
    glance.groups.act_now.length - actNow.length +
    (glance.groups.watch.length - watch.length) +
    (glance.groups.awaiting.length - awaiting.length);

  return (
    <section className="glance-section" aria-labelledby="glance-title">
      <div className="section-heading glance-heading">
        <div>
          <span className="eyebrow">Consult glance</span>
          <h2 id="glance-title">What needs attention now</h2>
        </div>
        <div className="glance-assurance" title={glance.safety_rule}>
          <Eye size={16} />
          <span>Human-reviewed safety rules stay above learned ranking</span>
        </div>
      </div>

      <div className={`glance-grid ${glance.patient_mode ? "patient-glance" : ""}`}>
        <div className="glance-lane act-now-lane">
          <div className="lane-heading">
            <div>
              <span className="lane-dot" />
              <h3>{glance.patient_mode ? "Your plan" : "Act now"}</h3>
            </div>
            <span>{actNow.length || watch.length}</span>
          </div>
          {(glance.patient_mode ? watch : actNow).map((item) => (
            <HighlightCard
              key={item.id}
              item={item}
              role={role}
              busy={busyHighlight === item.id}
              onSource={onSource}
              onFeedback={onFeedback}
            />
          ))}
          {!glance.patient_mode && actNow.length === 0 && (
            <div className="lane-empty"><Check size={18} /> No urgent items</div>
          )}
        </div>

        {!glance.patient_mode && (
          <>
            <div className="glance-lane watch-lane">
              <div className="lane-heading">
                <div><span className="lane-dot" /><h3>Watch</h3></div>
                <span>{watch.length}</span>
              </div>
              {watch.map((item) => (
                <HighlightCard
                  key={item.id}
                  item={item}
                  role={role}
                  busy={busyHighlight === item.id}
                  onSource={onSource}
                  onFeedback={onFeedback}
                />
              ))}
              {watch.length === 0 && (
                <div className="lane-empty"><Eye size={18} /> No lower-priority watch items</div>
              )}
            </div>
            <div className="glance-lane awaiting-lane">
              <div className="lane-heading">
                <div><span className="lane-dot" /><h3>Awaiting</h3></div>
                <span>{awaiting.length}</span>
              </div>
              {awaiting.map((item) => (
                <TaskCard key={item.id} item={item} onTaskSource={onTaskSource} />
              ))}
              {awaiting.length === 0 && (
                <div className="lane-empty"><Check size={18} /> No open handoffs</div>
              )}
            </div>
          </>
        )}
      </div>
      {hidden > 0 && (
        <button className="overflow-note" onClick={() => document.querySelector("#timeline")?.scrollIntoView({ behavior: "smooth" })}>
          {hidden} lower-priority items remain in the evidence timeline <ChevronRight size={14} />
        </button>
      )}
    </section>
  );
}
