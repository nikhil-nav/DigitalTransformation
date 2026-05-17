import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:3000",
  },
  reporter: [["list"]],
});
