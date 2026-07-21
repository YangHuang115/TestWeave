import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./",
  testMatch: "**/*.spec.ts",
  timeout: 45 * 1000,
  expect: {
    timeout: 5000,
  },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: "cd ../.. && make server",
      url: "http://127.0.0.1:8000/health/ready",
      reuseExistingServer: true,
      timeout: 60 * 1000,
    },
    {
      command: "cd ../.. && make web",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: true,
      timeout: 60 * 1000,
    },
  ],
});
