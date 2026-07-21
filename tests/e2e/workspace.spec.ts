import { test, expect } from "@playwright/test";
import { execSync } from "child_process";

test.beforeAll(async () => {
  // 在启动所有 E2E 前，初始化数据库与合成用户
  try {
    console.log("Upgrading database and initializing E2E mock users...");
    // 运行迁移 (因为测试可能是全新库或者是当前本地库)
    execSync("make migrate", { stdio: "inherit" });
    // 初始化用户
    execSync("uv run --project apps/server python apps/server/src/testweave/init_e2e_data.py", { stdio: "inherit" });
  } catch (e) {
    console.warn("E2E database init skipped or failed:", e);
  }
});

test.describe("TestWeave E2E Platform Journeys", () => {
  test.beforeEach(async ({ context }) => {
    await context.clearCookies();
  });

  test("Journey 1: Authentication & Unauthorized Redirects", async ({ page }) => {
    // 1. 无登录直接访问受保护深层页面，应被重定向至登录页且带有 returnUrl
    await page.goto("/projects/some-fake-id/workbench");
    await expect(page).toHaveURL(/\/login\?returnUrl=.*/);

    // 2. 错误密码登录显示报错 (Argon2id 首次对比消耗较大，设定较宽超时)
    await page.locator("input[id='identity']").fill("admin@e2e.com");
    await page.locator("input[id='password']").fill("WrongPass123!");
    await page.click("button[type='submit']");
    await expect(page.locator(".error-banner")).toContainText("密码错误", { timeout: 15000 });

    // 3. 正常密码登录，并能成功安全重定向回原深层页面 (由于 fake-id 不存在，应该最终展示 404 错误页)
    await page.locator("input[id='password']").fill("1");
    await page.click("button[type='submit']");
    await page.waitForURL(/\/404/, { timeout: 15000 });
    await expect(page.locator(".error-code")).toContainText("404");
  });

  test("Journey 2: System Admin Project Creation & Access", async ({ page }) => {
    // 1. 管理员登录
    await page.goto("/login");
    await page.locator("input[id='identity']").fill("admin@e2e.com");
    await page.locator("input[id='password']").fill("1");
    await page.click("button[type='submit']");
    await page.waitForURL(/\/projects/, { timeout: 15000 });
    
    // 2. 显式强制导航至项目列表页面，以防止由于残留单个项目而自动直达工作台
    await page.goto("/projects");
    await page.waitForURL(/\/projects$/, { timeout: 10000 });

    // 3. 验证出现创建按钮
    const createBtn = page.locator(".create-btn");
    await expect(createBtn).toBeVisible({ timeout: 10000 });
    await createBtn.click();

    // 4. 填写表单创建新项目 (Key 必须只包含大写字母且长度为 2-10 字符)
    const randomKey = Array.from({ length: 5 }, () => "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[Math.floor(Math.random() * 26)]).join("");
    await page.locator("input[id='proj-key']").fill(randomKey);
    await page.locator("input[id='proj-name']").fill("E2E Project " + randomKey);
    await page.locator("textarea[id='proj-desc']").fill("This is an auto created project by E2E test suite.");
    await page.click("button:has-text('创建项目')");

    // 5. 创建成功，应自动重定向到该项目工作台
    await page.waitForURL(/\/projects\/.*\/workbench/, { timeout: 15000 });
    await expect(page.locator(".bc-active.page-title")).toContainText("工作台");
  });

  test("Journey 3: Normal User Without Projects Hint", async ({ page }) => {
    // 1. 无项目普通用户登录
    await page.goto("/login");
    await page.locator("input[id='identity']").fill("normal@e2e.com");
    await page.locator("input[id='password']").fill("1");
    await page.click("button[type='submit']");
    await page.waitForURL(/\/projects/, { timeout: 15000 });

    // 2. 显式强制导航至项目选择列表
    await page.goto("/projects");

    // 3. 应展示“无所属项目”空态容器
    await expect(page.locator(".empty-state")).toContainText("您目前不属于任何项目", { timeout: 10000 });
    // 4. 普通用户不应能看到创建项目按钮
    await expect(page.locator(".create-btn")).not.toBeVisible();
  });

  test("Journey 4: Project Admin settings, role changes, and archiving", async ({ page }) => {
    // 1. 登录管理员
    await page.goto("/login");
    await page.locator("input[id='identity']").fill("admin@e2e.com");
    await page.locator("input[id='password']").fill("1");
    await page.click("button[type='submit']");
    await page.waitForURL(/\/projects/, { timeout: 15000 });

    // 2. 强制进入项目选择列表，并新建一个专用于归档测试的项目
    await page.goto("/projects");
    await page.locator(".create-btn").click();
    const key = Array.from({ length: 5 }, () => "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[Math.floor(Math.random() * 26)]).join("");
    await page.locator("input[id='proj-key']").fill(key);
    await page.locator("input[id='proj-name']").fill("Archive Project " + key);
    await page.click("button:has-text('创建项目')");
    await page.waitForURL(/\/projects\/.*\/workbench/, { timeout: 15000 });

    // 3. 进入管理员设置页
    const projectId = page.url().split("/projects/")[1].split("/")[0];
    await page.goto(`/projects/${projectId}/admin`);
    await expect(page.locator("h3:has-text('项目信息')")).toBeVisible();

    // 4. 对项目执行归档
    page.on("dialog", async (dialog) => {
      expect(dialog.message()).toContain("归档此项目");
      await dialog.accept();
    });
    await page.click("button:has-text('归档项目')");

    // 5. 验证归档横幅并检查输入框置灰
    await expect(page.locator(".archived-banner")).toBeVisible({ timeout: 10000 });
    await expect(page.locator("input[id='p-name']")).toBeDisabled();
    await expect(page.locator("button:has-text('保存更改')")).toBeDisabled();
    await expect(page.locator("select[class='role-select']").first()).toBeDisabled();
  });
});
