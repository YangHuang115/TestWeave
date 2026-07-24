import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AiTestDesignStagePage from "./AiTestDesignStagePage.vue";
import type {
  AiDesignedTestCase,
  AiWorkbenchState,
  CaseReviewReport,
  RequirementAnalysis,
} from "./types";

const routerMocks = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  route: {
    params: { projectId: "project-1", taskId: "task-1" },
    query: { recordId: "record-1" } as Record<string, string>,
  },
}));

const apiMocks = vi.hoisted(() => ({
  listRecords: vi.fn(),
  createRecord: vi.fn(),
  getRecord: vi.fn(),
  saveRevision: vi.fn(),
  acceptStage: vi.fn(),
  createFeedback: vi.fn(),
  createFieldLock: vi.fn(),
  releaseFieldLock: vi.fn(),
  createRegenerationRequest: vi.fn(),
  retryStage: vi.fn(),
  getDiff: vi.fn(),
}));

vi.mock("vue-router", () => ({
  useRoute: () => routerMocks.route,
  useRouter: () => ({ push: routerMocks.push, replace: routerMocks.replace }),
}));

vi.mock("./api", () => ({ aiTestDesignApi: apiMocks }));

const analysis: RequirementAnalysis = {
  schemaVersion: "1.0",
  stableKey: "requirement-analysis",
  goal: "验证登录需求",
  inScope: ["密码登录"],
  outOfScope: [],
  modules: [],
  moduleRelations: [],
  rules: [],
  inferences: [],
  questions: [],
  risks: [],
  evidence: [],
};

function buildState(): AiWorkbenchState {
  const createdAt = "2026-07-22T12:00:00Z";
  const stages = [
    { key: "requirement-analysis" as const, label: "需求分析", status: "WAITING_HUMAN" as const, revisionCount: 1 },
    { key: "test-points" as const, label: "测试点", status: "NOT_GENERATED" as const, revisionCount: 0 },
    { key: "test-cases" as const, label: "测试用例", status: "NOT_GENERATED" as const, revisionCount: 0 },
    { key: "case-review" as const, label: "用例评审", status: "NOT_GENERATED" as const, revisionCount: 0 },
  ];
  return {
    record: {
      id: "record-1",
      recordNo: 1,
      title: "第 1 轮 · 登录安全用例设计",
      status: "WAITING_HUMAN",
      runId: "run-1",
      runStatus: "WAITING_HUMAN",
      currentStage: "requirement-analysis",
      lastOpenedStage: "requirement-analysis",
      rowVersion: 1,
      stages,
      errorCode: null,
      errorSummary: null,
      createdBy: "user-1",
      createdAt,
      updatedAt: createdAt,
    },
    source: {
      task: { id: "task-1", taskNo: "TASK-001", title: "登录设计任务" },
      requirement: {
        id: "req-1",
        requirementNo: "REQ-001",
        title: "登录安全",
        description: "连续失败五次后锁定",
        acceptanceCriteria: "锁定后拒绝登录",
      },
      attachments: [],
      reviewMode: "TRACEABLE",
    },
    stage: {
      key: "requirement-analysis",
      label: "需求分析",
      nodeId: "requirement_analysis",
      artifactType: "requirement_analysis@1.0",
      status: "WAITING_HUMAN",
      candidateRevision: {
        id: "set-2",
        revisionNo: 2,
        baseSetRevisionId: "set-1",
        setHash: "set-hash-2",
        inputContextHash: "input-hash",
        itemCount: 1,
        reviewStatus: "CANDIDATE",
        validationStatus: "VALID",
        decisionSnapshot: null,
        createdAt,
        items: [
          {
            position: 0,
            itemId: "item-1",
            stableKey: "requirement-analysis",
            artifactType: "requirement_analysis@1.0",
            revisionId: "revision-2",
            revisionNo: 2,
            source: "USER_EDIT",
            contentHash: "content-hash-2",
            content: analysis,
            createdAt,
          },
        ],
      },
      acceptedRevision: null,
      acceptedState: null,
      revisionHistory: [
        {
          id: "set-2",
          revisionNo: 2,
          baseSetRevisionId: "set-1",
          setHash: "set-hash-2",
          reviewStatus: "CANDIDATE",
          validationStatus: "VALID",
          decisionSnapshot: null,
          itemCount: 1,
          createdAt,
        },
      ],
      steps: [
        {
          id: "gate-step-1",
          nodeId: "requirement_analysis_gate",
          nodeName: "确认需求分析",
          attempt: 1,
          status: "WAITING_HUMAN",
          retryable: false,
          errorCode: null,
          errorSummary: null,
          startedAt: createdAt,
          completedAt: null,
        },
      ],
      fieldLocks: [],
      feedback: [],
      regenerationRequests: [],
    },
    run: {
      id: "run-1",
      status: "WAITING_HUMAN",
      errorCode: null,
      errorSummary: null,
      startedAt: createdAt,
      completedAt: null,
      createdAt,
    },
    allowedActions: {
      canEdit: true,
      canAccept: true,
      canFeedback: true,
      canRegenerate: true,
      canRetry: false,
    },
  };
}

function buttonByText(wrapper: ReturnType<typeof mount>, text: string) {
  const button = wrapper.findAll("button").find((item) => item.text().includes(text));
  if (!button) throw new Error(`未找到按钮: ${text}`);
  return button;
}

describe("AiTestDesignStagePage", () => {
  let state: AiWorkbenchState;

  beforeEach(() => {
    state = buildState();
    routerMocks.route.query = { recordId: "record-1" };
    apiMocks.listRecords.mockResolvedValue({
      items: [state.record],
      resumeRecordId: "record-1",
    });
    apiMocks.getRecord.mockImplementation(async () => state);
    apiMocks.saveRevision.mockResolvedValue(state.stage.candidateRevision);
    apiMocks.createFeedback.mockResolvedValue({ id: "feedback-1", status: "ACTIVE" });
    apiMocks.createRegenerationRequest.mockResolvedValue({ id: "regen-1", status: "PENDING" });
    apiMocks.getDiff.mockResolvedValue({
      summary: { added_count: 0, modified_count: 1, removed_count: 0, unchanged_count: 0 },
      items: [{ change_type: "modified", stable_key: "requirement-analysis" }],
    });
  });

  it("恢复当前候选版本，并完成编辑保存、Diff、反馈和局部重生成", async () => {
    const wrapper = mount(AiTestDesignStagePage, {
      props: { stageKey: "requirement-analysis" },
    });
    await flushPromises();

    expect(wrapper.text()).toContain("等待人工确认");
    expect((wrapper.get(".stage-editor textarea").element as HTMLTextAreaElement).value).toBe(
      "验证登录需求",
    );
    expect(routerMocks.push).not.toHaveBeenCalled();

    await wrapper.get(".stage-editor textarea").setValue("验证登录与账号锁定");
    await buttonByText(wrapper, "仅保存修改").trigger("click");
    await flushPromises();
    expect(apiMocks.saveRevision).toHaveBeenCalledWith(
      "project-1",
      "task-1",
      "record-1",
      "requirement-analysis",
      expect.objectContaining({
        baseSetRevisionId: "set-2",
        expectedSetHash: "set-hash-2",
      }),
    );

    await buttonByText(wrapper, "查看生成前后 Diff").trigger("click");
    await flushPromises();
    expect(apiMocks.getDiff).toHaveBeenCalledWith(
      "project-1",
      "run-1",
      "set-2",
      "set-1",
    );
    expect(wrapper.text()).toContain("AI 原始版本与当前修改");
    await wrapper.get(".diff-modal header button").trigger("click");

    await buttonByText(wrapper, "提交反馈 / 局部重生成").trigger("click");
    await wrapper.get(".feedback-drawer textarea").setValue("补充失败次数重置规则");
    await buttonByText(wrapper, "保存反馈并重新生成").trigger("click");
    await flushPromises();
    expect(apiMocks.createFeedback).toHaveBeenCalled();
    expect(apiMocks.createRegenerationRequest).toHaveBeenCalledWith(
      "project-1",
      "task-1",
      "record-1",
      "requirement-analysis",
      expect.objectContaining({
        targetItemStableKeys: ["requirement-analysis"],
        baseSetRevisionId: "set-2",
        feedbackIds: ["feedback-1"],
      }),
      expect.stringMatching(/^regen-/),
    );

    wrapper.unmount();
  });

  it("展示 STALE 和真实失败原因，并调用安全重试接口", async () => {
    state.stage.status = "STALE";
    state.record.stages[0]!.status = "STALE";
    const wrapper = mount(AiTestDesignStagePage, {
      props: { stageKey: "requirement-analysis" },
    });
    await flushPromises();
    expect(wrapper.text()).toContain("当前阶段已过期");

    state.stage.status = "GENERATION_FAILED";
    state.record.stages[0]!.status = "GENERATION_FAILED";
    state.run.status = "FAILED";
    state.run.errorSummary = "模型服务超时";
    state.allowedActions.canRetry = true;
    state.stage.steps[0]!.status = "FAILED";
    state.stage.steps[0]!.retryable = true;
    state.stage.steps[0]!.errorSummary = "模型服务超时";
    apiMocks.retryStage.mockResolvedValue({ status: "PENDING" });
    await buttonByText(wrapper, "刷新状态").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("模型服务超时");
    await buttonByText(wrapper, "安全重试失败步骤").trigger("click");
    await flushPromises();
    expect(apiMocks.retryStage).toHaveBeenCalledWith(
      "project-1",
      "task-1",
      "record-1",
      "requirement-analysis",
    );

    wrapper.unmount();
  });

  it("确认评审修订请求后，保存评审版本并对目标用例发起局部重生成", async () => {
    const review: CaseReviewReport = {
      schemaVersion: "1.0",
      stableKey: "case-review-report",
      mode: "TRACEABLE",
      gateRecommendation: "PASS_WITH_WARNINGS",
      summary: "存在观察点问题",
      caseResults: [
        { caseRef: "TC-001", status: "WARNING", findingRefs: ["F-001"] },
      ],
      findings: [
        {
          stableKey: "F-001",
          severity: "WARNING",
          caseRef: "TC-001",
          fieldPath: "/steps/0/expected",
          evidenceRefs: ["TP-001"],
          description: "观察点不足",
          suggestion: "补充服务端失败计数观察",
          decision: "PENDING",
          decisionReason: "",
        },
      ],
      coverage: { ruleCoverage: 1, testPointCoverage: 1, uncoveredRefs: [] },
      duplicateClusters: [],
      unresolvedAssumptions: [],
      revisionRequests: [],
    };
    state.stage.key = "case-review";
    state.stage.label = "用例评审";
    state.stage.nodeId = "case_review";
    state.stage.artifactType = "test_case_review_report@1.0";
    state.stage.candidateRevision!.items[0]!.stableKey = "case-review-report";
    state.stage.candidateRevision!.items[0]!.content = review;
    state.record.currentStage = "case-review";

    const testCase: AiDesignedTestCase = {
      stableKey: "TC-001",
      title: "第五次失败后锁定",
      module: "账号",
      scope: "安全",
      priority: "HIGH",
      primaryTestPointRef: "TP-001",
      ruleRefs: [],
      preconditions: [],
      testData: [],
      steps: [{ stepNo: 1, action: "登录", expected: "账号锁定" }],
      coreExpected: "账号锁定",
      observationPoints: [],
      cleanupActions: [],
      testMethod: "边界值",
      assumptionRefs: [],
      qualityPrecheck: { status: "WARNING", findings: [] },
    };
    const casesState = buildState();
    casesState.stage.key = "test-cases";
    casesState.stage.nodeId = "test_cases";
    casesState.stage.artifactType = "test_case_set@1.0";
    casesState.stage.candidateRevision!.id = "case-set-2";
    casesState.stage.candidateRevision!.items[0]!.itemId = "case-item-1";
    casesState.stage.candidateRevision!.items[0]!.revisionId = "case-revision-2";
    casesState.stage.candidateRevision!.items[0]!.stableKey = "TC-001";
    casesState.stage.candidateRevision!.items[0]!.content = testCase;
    apiMocks.getRecord.mockImplementation(
      async (_projectId: string, _taskId: string, _recordId: string, stageKey: string) =>
        stageKey === "test-cases" ? casesState : state,
    );

    const wrapper = mount(AiTestDesignStagePage, {
      props: { stageKey: "case-review" },
    });
    await flushPromises();
    await buttonByText(wrapper, "转为定向修订请求").trigger("click");
    await buttonByText(wrapper, "确认并发起用例重生成").trigger("click");
    await flushPromises();

    expect(apiMocks.saveRevision).toHaveBeenCalled();
    expect(apiMocks.createFeedback).toHaveBeenCalledWith(
      "project-1",
      "task-1",
      "record-1",
      "test-cases",
      expect.objectContaining({
        targetType: "FIELD",
        targetItemId: "case-item-1",
        targetRevisionId: "case-revision-2",
        jsonPointer: "/steps/0/expected",
      }),
    );
    expect(apiMocks.createRegenerationRequest).toHaveBeenCalledWith(
      "project-1",
      "task-1",
      "record-1",
      "test-cases",
      expect.objectContaining({
        targetItemStableKeys: ["TC-001"],
        baseSetRevisionId: "case-set-2",
      }),
      expect.stringMatching(/^review-regen-/),
    );
    expect(routerMocks.push).toHaveBeenCalledWith(
      expect.objectContaining({
        path: "/projects/project-1/test-tasks/task-1/ai-design/test-cases",
      }),
    );

    wrapper.unmount();
  });
});
