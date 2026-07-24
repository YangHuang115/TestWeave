export type AiDesignStageKey =
  | "requirement-analysis"
  | "test-points"
  | "test-cases"
  | "case-review";

export type AiDesignStageStatus =
  | "NOT_GENERATED"
  | "GENERATING"
  | "WAITING_HUMAN"
  | "CANDIDATE"
  | "ACCEPTED"
  | "STALE"
  | "RERUN_REQUIRED"
  | "GENERATION_FAILED";

export type AiRunStatus =
  | "PENDING"
  | "RUNNING"
  | "WAITING_HUMAN"
  | "WAITING_EXTERNAL_AGENT"
  | "WAITING_RETRY"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELLED";

export interface RequirementModule {
  id: string;
  title: string;
  description: string;
}

export interface ModuleRelation {
  id: string;
  sourceModuleRef: string;
  targetModuleRef: string;
  relationType: string;
  description: string;
  evidenceRefs: string[];
}

export interface RequirementRule {
  id: string;
  description: string;
  evidenceRefs: string[];
}

export interface RequirementInference {
  id: string;
  description: string;
  basis: string;
  evidenceRefs: string[];
  decision: "PENDING" | "ACCEPTED" | "REJECTED";
}

export interface RequirementQuestion {
  id: string;
  question: string;
  blocking: boolean;
  status: "PENDING" | "ANSWERED" | "ASSUMPTION_ACCEPTED" | "DEFERRED" | "OUT_OF_SCOPE";
  answer: string;
  decisionReason: string;
  scope: "IN_SCOPE" | "OUT_OF_SCOPE";
}

export interface RequirementRisk {
  id: string;
  title: string;
  description: string;
  level: "HIGH" | "MEDIUM" | "LOW";
  testSignals: string[];
  evidenceRefs: string[];
}

export interface EvidenceRef {
  id: string;
  sourceType: "REQUIREMENT" | "ATTACHMENT" | "HUMAN_DECISION";
  sourceRef: string;
  quote: string;
}

export interface RequirementAnalysis {
  schemaVersion: "1.0";
  stableKey: string;
  goal: string;
  inScope: string[];
  outOfScope: string[];
  modules: RequirementModule[];
  moduleRelations: ModuleRelation[];
  rules: RequirementRule[];
  inferences: RequirementInference[];
  questions: RequirementQuestion[];
  risks: RequirementRisk[];
  evidence: EvidenceRef[];
}

export interface TestPointVariable {
  name: string;
  partitions: string[];
}

export interface TestPoint {
  stableKey: string;
  title: string;
  description: string;
  module: string;
  scope: string;
  preconditions: string[];
  coreAction: string;
  coreExpected: string;
  variables: TestPointVariable[];
  testMethod: string;
  testMethodReason: string;
  risk: "HIGH" | "MEDIUM" | "LOW";
  priority: "HIGH" | "MEDIUM" | "LOW";
  ruleRefs: string[];
  questionRefs: string[];
  moduleRelationRefs: string[];
  allowCaseGeneration: boolean;
}

export interface TestCaseData {
  name: string;
  value: string;
  purpose: string;
}

export interface TestCaseStep {
  stepNo: number;
  action: string;
  expected: string;
}

export interface AiDesignedTestCase {
  stableKey: string;
  title: string;
  module: string;
  scope: string;
  priority: "HIGH" | "MEDIUM" | "LOW";
  primaryTestPointRef: string;
  ruleRefs: string[];
  preconditions: string[];
  testData: TestCaseData[];
  steps: TestCaseStep[];
  coreExpected: string;
  observationPoints: string[];
  cleanupActions: string[];
  testMethod: string;
  assumptionRefs: string[];
  qualityPrecheck: {
    status: "PASS" | "WARNING" | "FAIL";
    findings: string[];
  };
}

export interface ReviewFinding {
  stableKey: string;
  severity: "INFO" | "WARNING" | "ERROR" | "CRITICAL";
  caseRef: string;
  fieldPath: string;
  evidenceRefs: string[];
  description: string;
  suggestion: string;
  decision: "PENDING" | "ACCEPTED" | "REJECTED" | "EDITED";
  decisionReason: string;
}

export interface CaseReviewReport {
  schemaVersion: "1.0";
  stableKey: string;
  mode: "TRACEABLE" | "INTRINSIC";
  gateRecommendation: "PASS" | "PASS_WITH_WARNINGS" | "BLOCK";
  summary: string;
  caseResults: Array<{
    caseRef: string;
    status: "PASS" | "WARNING" | "FAIL";
    findingRefs: string[];
  }>;
  findings: ReviewFinding[];
  coverage: {
    ruleCoverage: number;
    testPointCoverage: number;
    uncoveredRefs: string[];
  };
  duplicateClusters: Array<{ id: string; caseRefs: string[]; reason: string }>;
  unresolvedAssumptions: string[];
  revisionRequests: Array<{
    id: string;
    caseRef: string;
    fieldPath: string;
    instruction: string;
    status: "DRAFT" | "CONFIRMED" | "APPLIED" | "REJECTED";
  }>;
}

export type AiArtifactContent =
  | RequirementAnalysis
  | TestPoint
  | AiDesignedTestCase
  | CaseReviewReport;

export interface AiRevisionItem<T extends AiArtifactContent = AiArtifactContent> {
  position: number;
  itemId: string;
  stableKey: string;
  artifactType: string;
  revisionId: string;
  revisionNo: number;
  source: string;
  contentHash: string;
  content: T;
  createdAt: string;
}

export interface AiSetRevision<T extends AiArtifactContent = AiArtifactContent> {
  id: string;
  revisionNo: number;
  baseSetRevisionId: string | null;
  setHash: string;
  inputContextHash: string;
  itemCount: number;
  reviewStatus: string;
  validationStatus: string;
  decisionSnapshot: Record<string, unknown> | null;
  createdAt: string;
  items: Array<AiRevisionItem<T>>;
}

export interface AiStageSummary {
  key: AiDesignStageKey;
  label: string;
  status: AiDesignStageStatus;
  revisionCount: number;
}

export interface AiDesignRecordSummary {
  id: string;
  recordNo: number;
  title: string;
  status: string;
  runId: string;
  runStatus: AiRunStatus;
  currentStage: AiDesignStageKey;
  lastOpenedStage: AiDesignStageKey;
  rowVersion: number;
  stages: AiStageSummary[];
  errorCode: string | null;
  errorSummary: string | null;
  createdBy: string;
  createdAt: string;
  updatedAt: string;
}

export interface AiRecordListResponse {
  items: AiDesignRecordSummary[];
  resumeRecordId: string | null;
}

export interface AiStageState {
  key: AiDesignStageKey;
  label: string;
  nodeId: string;
  artifactType: string;
  status: AiDesignStageStatus;
  candidateRevision: AiSetRevision | null;
  acceptedRevision: AiSetRevision | null;
  acceptedState: {
    freshnessStatus: string;
    rerunRequired: boolean;
    rowVersion: number;
    stateReasons: Record<string, unknown> | null;
  } | null;
  revisionHistory: Array<{
    id: string;
    revisionNo: number;
    baseSetRevisionId: string | null;
    setHash: string;
    reviewStatus: string;
    validationStatus: string;
    decisionSnapshot: Record<string, unknown> | null;
    itemCount: number;
    createdAt: string;
  }>;
  steps: Array<{
    id: string;
    nodeId: string;
    nodeName: string | null;
    attempt: number;
    status: string;
    retryable: boolean;
    errorCode: string | null;
    errorSummary: string | null;
    startedAt: string | null;
    completedAt: string | null;
  }>;
  fieldLocks: Array<{
    id: string;
    itemId: string;
    revisionId: string;
    jsonPointer: string;
    status: string;
    createdAt: string;
  }>;
  feedback: Array<{
    id: string;
    targetType: string;
    targetItemId: string | null;
    targetRevisionId: string | null;
    jsonPointer: string | null;
    category: string;
    comment: string | null;
    changeSnapshot: Record<string, unknown> | null;
    createdAt: string;
  }>;
  regenerationRequests: Array<{
    id: string;
    status: string;
    baseSetRevisionId: string;
    resultSetRevisionId: string | null;
    errorCode: string | null;
    errorSummary: string | null;
    createdAt: string;
  }>;
}

export interface AiWorkbenchState {
  record: AiDesignRecordSummary;
  source: {
    task: Record<string, string | null>;
    requirement: Record<string, string | null>;
    attachments: Array<Record<string, string | null>>;
    reviewMode: "TRACEABLE" | "INTRINSIC";
  };
  stage: AiStageState;
  run: {
    id: string;
    status: AiRunStatus;
    errorCode: string | null;
    errorSummary: string | null;
    startedAt: string | null;
    completedAt: string | null;
    createdAt: string;
  };
  allowedActions: {
    canEdit: boolean;
    canAccept: boolean;
    canFeedback: boolean;
    canRegenerate: boolean;
    canRetry: boolean;
  };
}
