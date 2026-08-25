import { CheckCircle2, DatabaseZap, Fingerprint, ShieldAlert } from "lucide-react";

import type { AuditEvent, AuditVerification } from "../types";

export function AdminPanel({
  verification,
  events,
  retentionBusy,
  onRetention,
}: {
  verification: AuditVerification | null;
  events: AuditEvent[];
  retentionBusy: boolean;
  onRetention: () => void;
}) {
  return (
    <section className="admin-panel" aria-labelledby="admin-title">
      <div className="section-heading"><div><span className="eyebrow">Clinic oversight</span><h2 id="admin-title">Trust operations</h2></div><button className="secondary-button" disabled={retentionBusy} onClick={onRetention}><DatabaseZap size={15} />{retentionBusy ? "Evaluating..." : "Run retention policy"}</button></div>
      <div className={`audit-verification ${verification?.valid ? "valid" : "invalid"}`}><div>{verification?.valid ? <CheckCircle2 size={25} /> : <ShieldAlert size={25} />}<div><strong>{verification?.valid ? "Audit chain verified" : "Audit chain needs review"}</strong><span>{verification?.events_checked ?? 0} metadata-only events checked</span></div></div><Fingerprint size={28} /></div>
      <div className="audit-table-wrap"><table className="audit-table"><thead><tr><th>Seq</th><th>Action</th><th>Object</th><th>Actor</th><th>Integrity</th></tr></thead><tbody>{events.map((event) => <tr key={event.id}><td>#{event.sequence}</td><td>{event.action.replaceAll("_", " ")}</td><td>{event.object_type}<small>{event.object_id.slice(0, 12)}...</small></td><td>{event.actor_id?.replace("user-", "") ?? "system"}</td><td><code>{event.event_hash.slice(0, 10)}...</code></td></tr>)}</tbody></table></div>
    </section>
  );
}

