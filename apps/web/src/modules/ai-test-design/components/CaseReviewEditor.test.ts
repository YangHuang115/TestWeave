import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import CaseReviewEditor from "./CaseReviewEditor.vue";
import type { CaseReviewReport } from "../types";

function report(): CaseReviewReport {
  return {
    schemaVersion: "1.0",
    stableKey: "case-review-report",
    mode: "TRACEABLE",
    gateRecommendation: "PASS_WITH_WARNINGS",
    summary: "存在一条观察点问题",
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
        description: "预期缺少服务端观察点",
        suggestion: "补充失败计数持久化观察",
        decision: "PENDING",
        decisionReason: "",
      },
    ],
    coverage: { ruleCoverage: 1, testPointCoverage: 1, uncoveredRefs: [] },
    duplicateClusters: [],
    unresolvedAssumptions: [],
    revisionRequests: [],
  };
}

describe("CaseReviewEditor", () => {
  it("先形成修订请求，再由用户确认发起定向用例重生成", async () => {
    const value = report();
    const wrapper = mount(CaseReviewEditor, { props: { modelValue: [value] } });

    const convert = wrapper
      .findAll("button")
      .find((button) => button.text().includes("转为定向修订请求"));
    expect(convert).toBeDefined();
    await convert!.trigger("click");

    expect(value.revisionRequests).toEqual([
      {
        id: "RR-F-001",
        caseRef: "TC-001",
        fieldPath: "/steps/0/expected",
        instruction: "补充失败计数持久化观察",
        status: "DRAFT",
      },
    ]);
    expect(value.findings[0]!.decision).toBe("ACCEPTED");

    const apply = wrapper
      .findAll("button")
      .find((button) => button.text().includes("确认并发起用例重生成"));
    expect(apply).toBeDefined();
    await apply!.trigger("click");

    expect(value.revisionRequests[0]!.status).toBe("CONFIRMED");
    expect(wrapper.emitted("apply-revision-request")?.[0]).toEqual([
      {
        caseRef: "TC-001",
        fieldPath: "/steps/0/expected",
        instruction: "补充失败计数持久化观察",
      },
    ]);
  });
});
