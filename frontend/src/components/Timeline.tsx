import { useMemo, useState } from "react";
import {
  Bot,
  ChevronDown,
  ChevronUp,
  Clock3,
  History,
  MessageSquareText,
  PencilLine,
  Snowflake,
  UserRound,
} from "lucide-react";

import type { Entry, ResolvedProvenance, Role } from "../types";
import { TrustBadge } from "./TrustBadge";

type TimelineFilter = "all" | "human" | "ai" | "patient";

interface Props {
  entries: Entry[];
  role: Role;
  activeSource: ResolvedProvenance | null;
  onHistory: (entry: Entry) => void;
  onEdit: (entry: Entry) => void;
  onComment: (entry: Entry) => void;
}

const entryLabels: Record<string, string> = {
  ai_doctor_consult_summary: "AI doctor consult",
  ai_nurse_consult_summary: "AI nurse consult",
  ai_patient_session_summary: "AI patient session",
  clinician_note: "Clinical note",
  staff_note: "Staff workflow",
  patient_summary: "Patient summary",
  patient_instruction: "Patient instruction",
  patient_insight: "Patient insight",
};

function displayDate(value: string) {
  return new Intl.DateTimeFormat("en-SG", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function SourceAwareContent({ entry, source }: { entry: Entry; source: ResolvedProvenance | null }) {
  const content = entry.version.content;
  if (!source || source.source_entry_id !== entry.id) return <p className="entry-content">{content}</p>;
  const start = content.indexOf(source.quote);
  if (start < 0) return <p className="entry-content">{content}</p>;
  return (
    <p className="entry-content">
      {content.slice(0, start)}
      <mark className="source-focus">{source.quote}</mark>
      {content.slice(start + source.quote.length)}
    </p>
  );
}

function EntryCard({
  entry,
  role,
  activeSource,
  onHistory,
  onEdit,
  onComment,
}: {
  entry: Entry;
  role: Role;
  activeSource: ResolvedProvenance | null;
  onHistory: (entry: Entry) => void;
  onEdit: (entry: Entry) => void;
  onComment: (entry: Entry) => void;
}) {
  const [commentsOpen, setCommentsOpen] = useState(false);
  const isAi = entry.entry_type.startsWith("ai_");
  const canEdit = entry.owner_role === role && ["staff", "clinician", "patient"].includes(role);
  const canComment = role !== "patient";
  const threadCount = entry.comment_threads?.length ?? 0;
  const active = activeSource?.source_entry_id === entry.id;

  return (
    <article
      id={`entry-${entry.id}`}
      className={`timeline-entry ${active ? "timeline-entry-active" : ""}`}
      tabIndex={-1}
      aria-label={`${entry.title}, ${entryLabels[entry.entry_type] ?? entry.entry_type}`}
    >
      <div className={`timeline-icon ${isAi ? "ai" : entry.owner_role}`}>
        {isAi ? <Bot size={17} /> : <UserRound size={17} />}
      </div>
      <div className="timeline-body">
        <div className="entry-meta-line">
          <span className="entry-type">{entryLabels[entry.entry_type] ?? entry.entry_type.replaceAll("_", " ")}</span>
          <span>{displayDate(entry.created_at)}</span>
          <span className={`retention-tier retention-${entry.retention_tier}`}>
            {entry.retention_tier === "cold" && <Snowflake size={11} />}
            {entry.retention_tier} tier
          </span>
        </div>
        <div className="entry-title-row">
          <div>
            <h3>{entry.title}</h3>
            <span className="entry-author">{entry.author?.display_name ?? "System"}</span>
          </div>
          <TrustBadge state={entry.trust_state} />
        </div>
        <SourceAwareContent entry={entry} source={activeSource} />
        {entry.source_uri && (
          <div className="source-uri" title={entry.source_uri}>
            Source: {entry.source_uri}
          </div>
        )}
        <div className="entry-actions">
          <button onClick={() => onHistory(entry)}><History size={14} /> Version {entry.current_version}</button>
          {canEdit && <button onClick={() => onEdit(entry)}><PencilLine size={14} /> Edit section</button>}
          {canComment && (
            <button onClick={() => threadCount ? setCommentsOpen((value) => !value) : onComment(entry)}>
              <MessageSquareText size={14} /> {threadCount ? `${threadCount} thread${threadCount === 1 ? "" : "s"}` : "Comment"}
              {threadCount > 0 && (commentsOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />)}
            </button>
          )}
        </div>
        {commentsOpen && entry.comment_threads && (
          <div className="thread-list">
            {entry.comment_threads.map((thread) => (
              <div key={thread.id} className={`thread ${thread.resolved ? "resolved" : ""}`}>
                <div className="thread-heading">
                  <strong>{thread.title}</strong>
                  <span>{thread.resolved ? "Resolved" : "Open"}</span>
                </div>
                {thread.comments.map((comment) => (
                  <div className="comment" key={comment.id}>
                    <span>{comment.author.display_name}</span>
                    <p>{comment.body}</p>
                  </div>
                ))}
              </div>
            ))}
            <button className="add-thread-button" onClick={() => onComment(entry)}>
              <MessageSquareText size={14} /> Start another thread
            </button>
          </div>
        )}
      </div>
    </article>
  );
}

export function Timeline({ entries, role, activeSource, onHistory, onEdit, onComment }: Props) {
  const [filter, setFilter] = useState<TimelineFilter>("all");
  const visible = useMemo(
    () =>
      entries.filter((entry) => {
        if (filter === "all") return true;
        if (filter === "ai") return entry.entry_type.startsWith("ai_");
        if (filter === "patient") return entry.visibility === "patient";
        return !entry.entry_type.startsWith("ai_");
      }),
    [entries, filter],
  );

  return (
    <section className="timeline-section" id="timeline" aria-labelledby="timeline-title">
      <div className="section-heading">
        <div>
          <span className="eyebrow">Longitudinal evidence</span>
          <h2 id="timeline-title">Care timeline</h2>
        </div>
        <div className="timeline-filters" role="group" aria-label="Filter timeline">
          {(["all", "human", "ai", "patient"] as const).map((value) => (
            <button
              key={value}
              className={filter === value ? "active" : ""}
              onClick={() => setFilter(value)}
              aria-pressed={filter === value}
            >
              {value === "ai" ? "AI drafts" : value.charAt(0).toUpperCase() + value.slice(1)}
            </button>
          ))}
        </div>
      </div>
      <div className="timeline-list">
        {visible.map((entry) => (
          <EntryCard
            key={entry.id}
            entry={entry}
            role={role}
            activeSource={activeSource}
            onHistory={onHistory}
            onEdit={onEdit}
            onComment={onComment}
          />
        ))}
      </div>
      {visible.length === 0 && (
        <div className="empty-state"><Clock3 size={22} /><p>No entries match this filter.</p></div>
      )}
    </section>
  );
}

