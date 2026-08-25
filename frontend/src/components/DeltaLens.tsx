import {
  ArrowRight,
  GitCompareArrows,
  HelpCircle,
  Link2,
  Minus,
  Plus,
} from "lucide-react";

import type { DeltaItem, DeltaLens as DeltaLensType } from "../types";

function DeltaRow({ item, onSource }: { item: DeltaItem; onSource: (spanId: string) => void }) {
  return (
    <li>
      <span>{item.label}</span>
      {item.evidence?.provenance_span_id && (
        <button
          onClick={() => onSource(item.evidence!.provenance_span_id)}
          aria-label={`Open source for ${item.label}`}
        >
          <Link2 size={12} />
        </button>
      )}
    </li>
  );
}

export function DeltaLens({
  delta,
  onSource,
}: {
  delta: DeltaLensType;
  onSource: (spanId: string) => void;
}) {
  return (
    <div className="rail-card delta-card">
      <div className="rail-heading"><span><GitCompareArrows size={16} />Delta lens</span></div>
      {delta.comparison && (
        <div className="delta-window">
          <span>{delta.comparison.from}</span><ArrowRight size={12} /><span>{delta.comparison.to}</span>
        </div>
      )}
      <div className="delta-group">
        <h4><Plus size={12} />New</h4>
        <ul>{delta.new.slice(0, 2).map((item) => <DeltaRow key={item.label} item={item} onSource={onSource} />)}</ul>
      </div>
      <div className="delta-group">
        <h4><GitCompareArrows size={12} />Changed or conflicting</h4>
        <ul>{delta.changed_or_conflicting.slice(0, 2).map((item) => <DeltaRow key={item.label} item={item} onSource={onSource} />)}</ul>
      </div>
      <div className="delta-group">
        <h4><Minus size={12} />Persistent</h4>
        <ul>{delta.persistent.slice(0, 1).map((item) => <DeltaRow key={item.label} item={item} onSource={onSource} />)}</ul>
      </div>
      <div className="causal-guardrail"><HelpCircle size={13} /><span>{delta.causal_guardrail}</span></div>
    </div>
  );
}
