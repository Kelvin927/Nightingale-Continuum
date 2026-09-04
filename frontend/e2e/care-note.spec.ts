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

test("mobile layout preserves the glance and role navigation @mobile", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "What needs attention now" })).toBeVisible();
  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(page.getByRole("navigation", { name: "Primary navigation" })).toBeVisible();
});
