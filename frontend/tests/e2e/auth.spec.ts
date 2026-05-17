import { test, expect } from "@playwright/test";

test("redirects unauthenticated users from / to /login", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: /sign in/i })).toBeVisible();
});

test("login -> home -> logout flow", async ({ page }) => {
  await page.goto("/login");

  await page.getByLabel(/username/i).fill("user");
  await page.getByLabel(/password/i).fill("password");
  await page.getByRole("button", { name: /sign in/i }).click();

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByText(/Signed in as/i)).toBeVisible();
  await expect(page.getByRole("heading", { name: /your projects/i })).toBeVisible();

  await page.getByRole("button", { name: /sign out/i }).click();
  await expect(page).toHaveURL(/\/login$/);
});

test("wrong credentials show inline error and stay on /login", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel(/username/i).fill("user");
  await page.getByLabel(/password/i).fill("wrong");
  await page.getByRole("button", { name: /sign in/i }).click();

  await expect(page.getByRole("alert")).toContainText(/invalid username or password/i);
  await expect(page).toHaveURL(/\/login$/);
});
