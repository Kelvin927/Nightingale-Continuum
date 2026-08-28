import { FormEvent, useState } from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  Bot,
  CheckCircle2,
  ClipboardCheck,
  LockKeyhole,
  SearchCheck,
  ShieldCheck,
} from "lucide-react";

import type { EvidenceReview } from "../types";
import { DialogShell } from "./Dialogs";
import { TrustBadge } from "./TrustBadge";

const suggestedQuestions = [
  "What needs attention now?",
  "Which medication evidence conflicts?",
  "What changed across visits?",
  "What follow-up action is pending?",
];

// The dialog renders structured server evidence. It never invents a free-form
// answer in the browser or treats an AI-proposed claim as confirmed truth.

export function ReviewCopilotDialog({
  result,
  busy,
  onClose,
  onAsk,
  onSource,
  onTaskSource,
}: {
  result: EvidenceReview | null;
  busy: boolean;
  onClose: () => void;
  onAsk: (question: string) => Promise<void>;
  onSource: (spanId: string) => void;
  onTaskSource: (entryId: string) => void;
}) {
  const [question, setQuestion] = useState(suggestedQuestions[0]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    await onAsk(question);
  }

  return (
    <DialogShell
      title="Evidence review copilot"
      eyebrow="Role-scoped, citation-first review"
      onClose={onClose}
      wide
    >
      <div className="review-contract">
        <ShieldCheck size={18} />
        <span>
          <strong>Evidence before prose.</strong>
          The local reviewer can organize this authorized record, but it cannot diagnose,
          prescribe, or confirm clinical truth.
        </span>
      </div>

      <form className="review-query" onSubmit={submit}>
        <label>
          Ask about this longitudinal record
          <div>
            <input
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              minLength={3}
              maxLength={500}
              required
              autoFocus
            />
            <button className="primary-button" disabled={busy || question.trim().length < 3}>
              <SearchCheck size={16} />
              {busy ? "Reviewing..." : "Review evidence"}
            </button>
          </div>
        </label>
        <div className="review-prompts" aria-label="Suggested review questions">
          {suggestedQuestions.map((suggestion) => (
            <button type="button" key={suggestion} onClick={() => setQuestion(suggestion)}>
              {suggestion}
            </button>
          ))}
        </div>
      </form>

      {result && (
        <section className="review-result" aria-live="polite">
          <div className={`review-summary state-${result.answer_state}`}>
            {result.answer_state === "supported" ? (
              <CheckCircle2 size={19} />
            ) : (
              <AlertTriangle size={19} />
            )}
            <div>
              <span>{result.intent} review</span>
              <h3>{result.summary}</h3>
              {result.abstention_reason && <p>{result.abstention_reason}</p>}
            </div>
          </div>

          {result.claims.length > 0 && (
            <div className="review-section">
              <h3><Bot size={17} />Source-bound signals</h3>
              <div className="review-claims">
                {result.claims.map((claim) => (
                  <article key={claim.provenance_span_id}>
                    <div>
                      <span className={`risk-dot risk-${claim.risk_level}`} />
                      <strong>{claim.text}</strong>
                      <TrustBadge state={claim.trust_state} />
                    </div>
                    <p>{claim.risk_reason}</p>
                    <small className="claim-support" title={claim.confidence_interpretation ?? "Policy-defined evidence support; not a correctness probability."}>
                      {(claim.confidence_band ?? "review").replaceAll("_", " ")} support · {Math.round(claim.confidence * 100)}/100
                    </small>
                    <blockquote>{claim.quote}</blockquote>
                    <button onClick={() => onSource(claim.provenance_span_id)}>
                      Verify exact source <ArrowUpRight size={14} />
                    </button>
                  </article>
                ))}
              </div>
            </div>
          )}

          {result.open_actions.length > 0 && (
            <div className="review-section">
              <h3><ClipboardCheck size={17} />Open workflow</h3>
              <div className="review-actions">
                {result.open_actions.map((action) => (
                  <article key={`${action.title}-${action.source_entry_id ?? "unlinked"}`}>
                    <span>{action.urgency}</span>
                    <strong>{action.title}</strong>
                    <small>{action.assigned_to ? "Explicit owner assigned" : "Owner required"}</small>
                    {action.source_entry_id && (
                      <button onClick={() => onTaskSource(action.source_entry_id!)}>
                        Open source entry <ArrowUpRight size={13} />
                      </button>
                    )}
                  </article>
                ))}
              </div>
            </div>
          )}

          {result.conflicts.length > 0 && (
            <div className="review-conflicts">
              <AlertTriangle size={17} />
              <div><strong>Conflict review required</strong>{result.conflicts.map((item) => <p key={item}>{item}</p>)}</div>
            </div>
          )}

          <div className="review-receipt">
            <LockKeyhole size={15} />
            <span>{result.provider} - no external model call - question stored as hash only</span>
          </div>
          <p className="review-safety-notice">{result.safety_notice}</p>
        </section>
      )}
    </DialogShell>
  );
}
