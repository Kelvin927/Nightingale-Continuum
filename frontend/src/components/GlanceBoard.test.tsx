import { fireEvent, render, screen } from "@testing-library/react";

import type { Glance } from "../types";
import { GlanceBoard } from "./GlanceBoard";

const glance: Glance = {
  patient_mode: false,
  safety_rule: "Critical risks outrank learned adjustments.",
  policy_version: "safe-beta-v1",
  groups: {
    act_now: [
      {
        id: "highlight-1",
        title: "Medication detail to reconcile",
        risk_level: "high",
        risk_reason: "Medication changes require review",
        entity_tags: ["medication", "dose_change"],
        confidence: 0.88,
        trust_state: "ai_proposed",
        status: "suggested",
        rank_score: 6.4,
        score_factors: { risk: 5, adaptive: 0.1 },
        provenance_span_id: "span-1",
        policy_version: "safe-beta-v1",
      },
    ],
    watch: [],
    awaiting: [],
  },
};

test("shows reason, trust state, provenance, and one-action feedback", () => {
  const onSource = vi.fn();
  const onFeedback = vi.fn();
  render(
    <GlanceBoard
      glance={glance}
      role="clinician"
      busyHighlight={null}
      onSource={onSource}
      onFeedback={onFeedback}
      onTaskSource={vi.fn()}
    />,
  );

  expect(screen.getByText("Medication detail to reconcile")).toBeInTheDocument();
  expect(screen.getByText("Medication changes require review")).toBeInTheDocument();
  expect(screen.getByText("AI proposed")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /exact source/i }));
  expect(onSource).toHaveBeenCalledWith("span-1");
  fireEvent.click(screen.getByRole("button", { name: /pin/i }));
  expect(onFeedback).toHaveBeenCalledWith("highlight-1", "pin");
});

test("does not expose ranking feedback controls to patients", () => {
  render(
    <GlanceBoard
      glance={glance}
      role="patient"
      busyHighlight={null}
      onSource={vi.fn()}
      onFeedback={vi.fn()}
      onTaskSource={vi.fn()}
    />,
  );
  expect(screen.queryByRole("button", { name: /pin/i })).not.toBeInTheDocument();
});

