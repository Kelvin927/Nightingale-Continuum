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

test("mobile layout preserves the glance and role navigation @mobile", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "What needs attention now" })).toBeVisible();
  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(page.getByRole("navigation", { name: "Primary navigation" })).toBeVisible();
});
