import { fireEvent, render, screen } from "@testing-library/react";

import type { Glance } from "../types";
import { glance as fullGlance, patientGlance } from "../test/fixtures";
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

test("covers bounded feedback, task provenance, assignment states, and noncritical labels", () => {
  const onFeedback = vi.fn();
  const onTaskSource = vi.fn();
  const { rerender } = render(
    <GlanceBoard
      glance={fullGlance}
      role="staff"
      busyHighlight="highlight-1"
      onSource={vi.fn()}
      onFeedback={onFeedback}
      onTaskSource={onTaskSource}
    />,
  );
  expect(screen.getByText("Critical")).toBeVisible();
  expect(screen.getByText("Medium")).toBeVisible();
  expect(screen.getByText("Assigned with explicit ownership")).toBeVisible();
  expect(screen.getByText("Needs an owner")).toBeVisible();
  const feedbackButtons = screen.getAllByRole("button", { name: /accept|pin|reject/i });
  expect(feedbackButtons).toHaveLength(3);
  expect(feedbackButtons.every((button) => button.hasAttribute("disabled"))).toBe(true);
  rerender(
    <GlanceBoard
      glance={fullGlance}
      role="staff"
      busyHighlight={null}
      onSource={vi.fn()}
      onFeedback={onFeedback}
      onTaskSource={onTaskSource}
    />,
  );
  screen.getAllByRole("button", { name: /accept|pin|reject/i }).forEach(fireEvent.click);
  expect(onFeedback.mock.calls).toEqual([
    ["highlight-1", "accept"],
    ["highlight-1", "pin"],
    ["highlight-1", "reject"],
  ]);
  fireEvent.click(screen.getByRole("button", { name: /related note/i }));
  expect(onTaskSource).toHaveBeenCalledWith("entry-clinician");
});

test("renders patient-safe instructions without internal lanes or training controls", () => {
  render(
    <GlanceBoard
      glance={patientGlance}
      role="patient"
      busyHighlight={null}
      onSource={vi.fn()}
      onFeedback={vi.fn()}
      onTaskSource={vi.fn()}
    />,
  );
  expect(screen.getByText("Your plan")).toBeVisible();
  expect(screen.getByText("Your medication plan")).toBeVisible();
  expect(screen.getByText("Care instruction")).toBeVisible();
  expect(screen.queryByText("Awaiting")).toBeNull();
  expect(screen.queryByRole("button", { name: /exact source/i })).toBeNull();
});

test("renders empty assurances and exposes overflow navigation", () => {
  const overflow: Glance = {
    patient_mode: false,
    safety_rule: "Safety rule",
    groups: {
      act_now: Array.from({ length: 4 }, (_, index) => ({
        ...fullGlance.groups.act_now[0],
        id: `urgent-${index}`,
        provenance_span_id: `span-${index}`,
      })),
      watch: Array.from({ length: 3 }, (_, index) => ({
        ...fullGlance.groups.watch[0],
        id: `watch-${index}`,
        provenance_span_id: `watch-span-${index}`,
      })),
      awaiting: Array.from({ length: 4 }, (_, index) => ({
        ...fullGlance.groups.awaiting[1],
        id: `task-${index}`,
      })),
    },
  };
  const timeline = document.createElement("div");
  timeline.id = "timeline";
  document.body.appendChild(timeline);
  const view = render(
    <GlanceBoard
      glance={overflow}
      role="admin"
      busyHighlight={null}
      onSource={vi.fn()}
      onFeedback={vi.fn()}
      onTaskSource={vi.fn()}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /3 lower-priority items/i }));
  expect(timeline.scrollIntoView).toHaveBeenCalled();
  view.unmount();
  timeline.remove();

  render(
    <GlanceBoard
      glance={{
        patient_mode: false,
        safety_rule: "Safety rule",
        groups: { act_now: [], watch: [], awaiting: [] },
      }}
      role="admin"
      busyHighlight={null}
      onSource={vi.fn()}
      onFeedback={vi.fn()}
      onTaskSource={vi.fn()}
    />,
  );
  expect(screen.getByText("No urgent items")).toBeVisible();
  expect(screen.getByText("No lower-priority watch items")).toBeVisible();
  expect(screen.getByText("No open handoffs")).toBeVisible();
});
