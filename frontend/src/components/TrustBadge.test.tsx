import { render, screen } from "@testing-library/react";

import { TrustBadge } from "./TrustBadge";

test("communicates trust state with text, not color alone", () => {
  render(<TrustBadge state="clinician_confirmed" />);
  expect(screen.getByText("Clinician confirmed")).toBeVisible();
});

test.each([
  ["ai_proposed", "AI proposed"],
  ["staff_verified", "Staff verified"],
  ["human_authored", "Human authored"],
  ["superseded", "Superseded"],
  ["custom_state", "custom state"],
])("renders the %s trust-state contract", (state, label) => {
  render(<TrustBadge state={state} />);
  expect(screen.getByText(label)).toBeVisible();
});
