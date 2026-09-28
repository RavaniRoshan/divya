import { defineConfig, devices } from "@playwright/test";

/**
 * These tests drive the real stack. There is no webServer block on purpose: the backend holds
 * 2.8 GB of model and must not be started and killed by the test runner on every run. Start it
 * yourself with `divya serve` and `pnpm start`, and the suite will fail loudly with an
 * explicit message if it is not reachable.
 */
export default defineConfig({
  testDir: "./tests",
  timeout: 45_000,
  expect: { timeout: 12_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:3000",
    ...devices["Desktop Chrome"],
    launchOptions: { args: ["--no-sandbox"] },
  },
});
