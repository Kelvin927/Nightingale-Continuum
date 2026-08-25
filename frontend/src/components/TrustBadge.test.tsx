import { render, screen } from "@testing-library/react";

import { TrustBadge } from "./TrustBadge";

test("communicates trust state with text, not color alone", () => {
  render(<TrustBadge state="clinician_confirmed" />);
  expect(screen.getByText("Clinician confirmed")).toBeVisible();
});

