import { defineConfig, devices } from "@playwright/test";

// 端口跟随环境变量 SERVER_PORT / WEB_PORT（缺省与 Makefile 一致）
const serverPort = process.env.SERVER_PORT ?? 8000;
const webPort = process.env.WEB_PORT ?? 5173;

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
    baseURL: `http://127.0.0.1:${webPort}`,
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
      url: `http://127.0.0.1:${serverPort}/health/ready`,
      reuseExistingServer: true,
      timeout: 60 * 1000,
    },
    {
      command: "cd ../.. && make web",
      url: `http://127.0.0.1:${webPort}`,
      reuseExistingServer: true,
      timeout: 60 * 1000,
    },
  ],
});
