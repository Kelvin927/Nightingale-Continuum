import { expect, test } from "@playwright/test";

test("clinician can understand the glance and resolve an exact source", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "What needs attention now" })).toBeVisible();
  await expect(page.getByText("Allergy safety signal")).toBeVisible();
  await expect(page.getByText("AI proposed").first()).toBeVisible();

  const safetyCard = page.locator(".glance-card").filter({ hasText: "Allergy safety signal" });
  await safetyCard.getByRole("button", { name: "Exact source" }).click();
  await expect(page.getByRole("heading", { name: "Verified exact source" })).toBeVisible();
  await expect(page.getByText("Pointer verified")).toBeVisible();
  await expect(page.locator(".source-quote blockquote")).not.toBeEmpty();
  await page.getByRole("button", { name: "Close source drawer" }).last().click();
});

test("evidence review stays citation-first and opens its immutable source", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Evidence review" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Which medication evidence conflicts?" }).click();
  await dialog.getByRole("button", { name: "Review evidence" }).click();

  await expect(dialog.getByText(/source-bound signal/)).toBeVisible();
  await expect(dialog.locator("blockquote").first()).not.toBeEmpty();
  await expect(dialog.getByText(/no external model call/i)).toBeVisible();
  await expect(dialog.getByText("Conflict review required")).toBeVisible();
  await dialog.getByRole("button", { name: "Verify exact source" }).first().click();
  await expect(page.getByRole("heading", { name: "Verified exact source" })).toBeVisible();
  await expect(page.getByText("Pointer verified")).toBeVisible();
});

test("patient projection excludes internal and raw AI content", async ({ page }) => {
  await page.goto("/");
  await page.locator(".role-trigger").click();
  await page.locator(".role-menu button").filter({ hasText: "Maya Chen" }).click();

  await expect(page.getByText("Your plan", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Care timeline" })).toBeVisible();
  await expect(page.getByText("AI proposed")).toHaveCount(0);
  await expect(page.getByText("Follow-up coordination")).toHaveCount(0);
  await expect(
    page.getByLabel("Care timeline").getByRole("heading", { name: "Your visit summary" }),
  ).toBeVisible();
});

test("phone-only access creates a device-bound patient projection without email", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Phone-only access" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("No email dependency")).toBeVisible();
  await dialog.getByRole("button", { name: "Create one-time access claim" }).click();
  await expect(dialog.getByText(/No message was sent in this synthetic rehearsal/i)).toBeVisible();
  await dialog.getByRole("button", { name: "Verify and open patient view" }).click();
  await expect(dialog.getByText("Authenticated without email")).toBeVisible();
  await expect(dialog.getByText("channel claim", { exact: true })).toBeVisible();
  await expect(dialog.getByText("no", { exact: true })).toBeVisible();
  await expect(dialog.getByText(/patient-visible longitudinal projection/i)).toBeVisible();
});

test("clinician sees version-bound medication evidence before patient delivery", async ({ page }) => {
  await page.goto("/");
  const summary = page.locator('article[aria-label^="Your visit summary,"]');
  await summary.getByRole("button", { name: "Edit section" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Note content").fill(
    "Take lisinopril 10 mg daily, not 20 mg. Call the clinic if the instruction is unclear.",
  );
  await dialog.getByRole("button", { name: "Save version" }).click();

  const source = page.getByLabel("Patient-facing source");
  const summaryOption = source.locator("option").filter({ hasText: "Your visit summary" });
  const summaryEntryId = await summaryOption.getAttribute("value");
  expect(summaryEntryId).not.toBeNull();
  await source.selectOption(summaryEntryId!);

  const gate = page.getByRole("group", { name: "Medication terminology release gate" });
  await expect(gate.getByText("Structured medication evidence ready")).toBeVisible();
  await expect(gate.getByText("10 mg", { exact: true })).toBeVisible();
  await expect(gate.getByText("20 mg", { exact: true })).toBeVisible();
  await expect(gate.getByText(/scanner does not infer clinical intent/i)).toBeVisible();
  await gate.getByText(/what this check does/i).click();
  await expect(gate.getByText(/does not establish prescription accuracy/i)).toBeVisible();

  await page.getByLabel(/reviewed the exact patient-facing copy/i).check();
  await page.getByLabel(/verified the patient and contact route/i).check();
  await expect(page.getByRole("button", { name: /queue approved copy/i })).toBeDisabled();
  await page.getByLabel(/verified every medication and dose/i).check();
  await expect(page.getByRole("button", { name: /queue approved copy/i })).toBeEnabled();
});

test("appointment delivery closes only after provider receipt and patient acknowledgement", async ({ page }) => {
  await page.goto("/");

  const appointmentCard = page.locator('article[aria-label^="Your follow-up appointment,"]');
  await appointmentCard.getByRole("button", { name: "Edit section" }).click();
  const editDialog = page.getByRole("dialog");
  const appointmentCopy = editDialog.getByLabel("Note content");
  await appointmentCopy.fill(
    `${await appointmentCopy.inputValue()}\nReviewed for this synthetic closed-loop rehearsal.`,
  );
  await editDialog.getByRole("button", { name: "Save version" }).click();

  const source = page.getByLabel("Patient-facing source");
  const appointmentOption = source.locator("option").filter({
    hasText: "Your follow-up appointment",
  });
  const appointmentEntryId = await appointmentOption.getAttribute("value");
  expect(appointmentEntryId).not.toBeNull();
  await source.selectOption(appointmentEntryId!);
  await page.getByLabel("Communication purpose").selectOption("appointment_invitation");
  await page.getByLabel(/reviewed the exact patient-facing copy/i).check();
  await page.getByLabel(/verified the patient and contact route/i).check();
  await page.getByLabel(/verified the appointment date, time, location, and exact link/i).check();
  await page.getByRole("button", { name: /queue approved copy/i }).click();
  await expect(page.getByText("pending provider acceptance", { exact: true }).first()).toBeVisible();

  await page.locator(".role-trigger").click();
  await page.getByRole("button", { name: /Rose Tan admin/i }).click();
  await page.getByRole("button", { name: /record synthetic provider acceptance/i }).first().click();
  await expect(page.getByText("pending delivery", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: /record synthetic delivery receipt/i }).first().click();
  await expect(page.getByText("awaiting patient acknowledgement", { exact: true }).first()).toBeVisible();

  await page.locator(".role-trigger").click();
  await page.getByRole("button", { name: /Maya Chen patient/i }).click();
  await page.getByRole("button", { name: /i received this appointment invitation/i }).first().click();
  await expect(page.getByText("acknowledged", { exact: true }).first()).toBeVisible();
});

test("mobile layout preserves the glance and role navigation @mobile", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "What needs attention now" })).toBeVisible();
  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(page.getByRole("navigation", { name: "Primary navigation" })).toBeVisible();
});
