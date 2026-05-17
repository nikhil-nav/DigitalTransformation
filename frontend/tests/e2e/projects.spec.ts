import { test, expect } from "@playwright/test";

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel(/username/i).fill("user");
  await page.getByLabel(/password/i).fill("password");
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL(/\/$/);
}

test("project lifecycle: create -> edit -> reload -> delete", async ({ page }) => {
  await login(page);

  const initialName = `E2E Project ${Date.now()}`;
  const renamedName = `${initialName} (renamed)`;

  // Create
  await page.getByRole("link", { name: /\+ new project/i }).click();
  await expect(page).toHaveURL(/\/projects\/new$/);

  // Value Discovery is active and selected by default; the others are disabled
  await expect(page.getByLabel("Value Discovery")).toBeEnabled();
  await expect(page.getByLabel("AI Assessment")).toBeDisabled();
  await expect(page.getByLabel("Business Process Discovery")).toBeDisabled();
  await expect(page.getByLabel("Data Quality Assessment")).toBeDisabled();

  await page.getByLabel(/^name$/i).fill(initialName);
  await page.getByLabel(/description/i).fill("created by e2e");
  await page.getByRole("button", { name: /create project/i }).click();

  await expect(page).toHaveURL(/\/projects\/\d+$/);
  await expect(page.getByRole("heading", { name: initialName })).toBeVisible();

  // Edit
  await page.getByRole("button", { name: /^edit$/i }).click();
  const nameInput = page.getByLabel(/^name$/i);
  await nameInput.fill(renamedName);
  await page.getByLabel(/status/i).selectOption("active");
  await page.getByRole("button", { name: /^save$/i }).click();

  await expect(page.getByRole("heading", { name: renamedName })).toBeVisible();
  await expect(page.getByText(/Value Discovery · active/i)).toBeVisible();

  // Reload — verify the rename persisted
  await page.reload();
  await expect(page.getByRole("heading", { name: renamedName })).toBeVisible();

  // Back on the list, the project shows up
  await page.getByRole("link", { name: /all projects/i }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("link", { name: new RegExp(renamedName) })).toBeVisible();

  // Delete via the detail page's confirm dialog
  await page.getByRole("link", { name: new RegExp(renamedName) }).click();
  await page.getByRole("button", { name: /^delete$/i }).click();
  const dialog = page.getByRole("dialog", { name: /confirm delete/i });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: /yes, delete/i }).click();

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("link", { name: new RegExp(renamedName) })).not.toBeVisible();
});
