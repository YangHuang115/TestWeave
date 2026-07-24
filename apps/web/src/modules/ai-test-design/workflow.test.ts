import { describe, expect, it } from "vitest";
import { router } from "../../app/router";
import {
  canAcceptStage,
  resolveRecordId,
  shouldPollRun,
  shouldPollWorkbench,
  stageStatusLabel,
} from "./workflow";

describe("AI 测试设计工作台路由与人工门禁", () => {
  it("注册四条独立、可深链接的阶段路由", () => {
    const paths = router.getRoutes().map((route) => route.path);
    expect(paths).toContain(
      "/projects/:projectId/test-tasks/:taskId/ai-design/requirement-analysis",
    );
    expect(paths).toContain("/projects/:projectId/test-tasks/:taskId/ai-design/test-points");
    expect(paths).toContain("/projects/:projectId/test-tasks/:taskId/ai-design/test-cases");
    expect(paths).toContain("/projects/:projectId/test-tasks/:taskId/ai-design/case-review");
  });

  it("刷新时优先恢复深链接指定记录，否则恢复最新未完成记录", () => {
    expect(resolveRecordId("record-from-url", "latest-unfinished")).toBe("record-from-url");
    expect(resolveRecordId(undefined, "latest-unfinished")).toBe("latest-unfinished");
    expect(resolveRecordId(undefined, null)).toBeNull();
  });

  it("等待人工确认时不允许自动进入下一阶段", () => {
    expect(stageStatusLabel("WAITING_HUMAN")).toBe("等待人工确认");
    expect(
      canAcceptStage("requirement-analysis", [
        {
          questions: [{ blocking: true, status: "PENDING" }],
        },
      ]),
    ).toBe(false);
  });

  it("只有人工选择的测试点才能通过用例生成门禁", () => {
    expect(
      canAcceptStage("test-points", [
        { stableKey: "TP-1", allowCaseGeneration: false },
      ]),
    ).toBe(false);
    expect(
      canAcceptStage("test-points", [
        { stableKey: "TP-1", allowCaseGeneration: true },
      ]),
    ).toBe(true);
  });

  it("驳回 Finding 时必须填写原因", () => {
    expect(
      canAcceptStage("case-review", [
        { findings: [{ decision: "REJECTED", decisionReason: "" }] },
      ]),
    ).toBe(false);
    expect(
      canAcceptStage("case-review", [
        { findings: [{ decision: "REJECTED", decisionReason: "与原需求不符" }] },
      ]),
    ).toBe(true);
  });

  it("只对真实运行中的状态轮询，不制造假进度", () => {
    expect(shouldPollRun("PENDING")).toBe(true);
    expect(shouldPollRun("RUNNING")).toBe(true);
    expect(shouldPollRun("WAITING_HUMAN")).toBe(false);
    expect(shouldPollRun("FAILED")).toBe(false);
    expect(shouldPollWorkbench("WAITING_HUMAN", ["PENDING"])).toBe(true);
    expect(shouldPollWorkbench("WAITING_HUMAN", ["RUNNING"])).toBe(true);
    expect(shouldPollWorkbench("WAITING_HUMAN", ["COMPLETED"])).toBe(false);
  });
});
