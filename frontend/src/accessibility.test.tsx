import { render } from "@testing-library/react";
import { axe } from "jest-axe";

import { glance, patientGlance, provenance } from "./test/fixtures";
import { GlanceBoard } from "./components/GlanceBoard";
import { NoteDialog } from "./components/Dialogs";
import { ProvenanceDrawer } from "./components/ProvenanceDrawer";

const noColorContrast = { rules: { "color-contrast": { enabled: false } } };

test.each([
  ["clinician", glance],
  ["patient", patientGlance],
] as const)("%s glance has no axe-detectable accessibility violations", async (role, payload) => {
  const view = render(
    <GlanceBoard
      glance={payload}
      role={role}
      busyHighlight={null}
      onSource={vi.fn()}
      onFeedback={vi.fn()}
      onTaskSource={vi.fn()}
    />,
  );
  const results = await axe(view.container, noColorContrast);
  expect(results.violations).toEqual([]);
  view.unmount();
});

test("authoring dialog has no axe-detectable accessibility violations", async () => {
  const view = render(
    <NoteDialog
      role="clinician"
      editing={null}
      onClose={vi.fn()}
      onSubmit={vi.fn().mockResolvedValue(undefined)}
    />,
  );
  const results = await axe(view.container, noColorContrast);
  expect(results.violations).toEqual([]);
  view.unmount();
});

test("provenance drawer has no axe-detectable accessibility violations", async () => {
  const view = render(<ProvenanceDrawer source={provenance} onClose={vi.fn()} />);
  const results = await axe(view.container, noColorContrast);
  expect(results.violations).toEqual([]);
});
