<template>
  <div class="run-details-page">
    <!-- 顶部 Summary Header -->
    <div class="top-nav-bar">
      <button class="btn-back" @click="goBack"><span class="icon">⬅</span> 返回 AI 能力中心</button>
      <div class="breadcrumbs font-mono">
        / projects / {{ projectId }} / agent / runs / {{ runId }}
      </div>
    </div>

    <div v-if="loading && !runDetail" class="loading-state">
      <div class="spinner"></div>
      <p>正在载入 AI 运行状态与全量拓扑数据...</p>
    </div>

    <div v-else-if="error" class="error-banner">
      <span class="icon">⚠️</span>
      <div class="msg-box">
        <strong>加载失败</strong>
        <p>{{ error }}</p>
      </div>
      <button class="btn btn-secondary btn-sm" @click="handleRefresh">重试</button>
    </div>

    <div v-else-if="runDetail" class="main-content">
      <!-- 运行概览 Header 卡片 -->
      <div class="glass-card header-card">
        <div class="header-main">
          <div class="title-area">
            <div class="status-row">
              <span class="badge-status" :class="'status-' + runDetail.run.status.toLowerCase()">
                <span class="status-dot"></span>
                {{ formatRunStatus(runDetail.run.status) }}
              </span>
              <span class="mode-tag" :class="'mode-' + runDetail.run.runMode.toLowerCase()">
                {{
                  runDetail.run.runMode === "PREVIEW" ? "预览调试 (PREVIEW)" : "正式生成 (NORMAL)"
                }}
              </span>
              <span v-if="runDetail.run.cancelRequested" class="cancel-tag"> 取消请求已挂起 </span>
            </div>
            <h2 class="run-title">
              AI 运行实例
              <span class="font-mono text-muted">#{{ runDetail.run.id.slice(0, 8) }}</span>
            </h2>
          </div>

          <div class="action-group">
            <button class="btn btn-secondary" :disabled="loading" @click="handleRefresh">
              <span>🔄</span> 刷新
            </button>
            <button
              v-if="canCancel"
              class="btn btn-danger"
              :disabled="actionInProgress"
              @click="handleCancel"
            >
              <span>⛔</span> 取消运行
            </button>
          </div>
        </div>

        <!-- 详细属性列 -->
        <div class="meta-grid">
          <div class="meta-item">
            <span class="label">幂等 Key (Idempotency)</span>
            <span class="value font-mono">{{ runDetail.run.idempotencyKey }}</span>
          </div>
          <div class="meta-item">
            <span class="label">快照 Hash (SHA-256)</span>
            <span
              class="value font-mono text-truncate"
              :title="runDetail.run.executionSnapshotHash"
            >
              {{ runDetail.run.executionSnapshotHash.slice(0, 16) }}...
            </span>
          </div>
          <div class="meta-item">
            <span class="label">创建时间</span>
            <span class="value">{{ formatDate(runDetail.run.createdAt) }}</span>
          </div>
          <div class="meta-item">
            <span class="label">完成时间</span>
            <span class="value">{{
              runDetail.run.completedAt ? formatDate(runDetail.run.completedAt) : "-"
            }}</span>
          </div>
        </div>

        <div v-if="runDetail.run.errorSummary" class="run-error-alert">
          <span class="icon">❌</span>
          <div class="err-content">
            <strong>运行失败 [错误码: {{ runDetail.run.errorCode || "UNKNOWN" }}]</strong>
            <p>{{ runDetail.run.errorSummary }}</p>
          </div>
        </div>
      </div>

      <!-- 双栏布局：左侧 Workflow 时间线，右侧 Output & Event 查看器 -->
      <div class="workspace-grid">
        <!-- 左侧：Workflow 步骤节点链表 -->
        <div class="glass-card timeline-card">
          <div class="card-header">
            <h3>🤖 工作流分步执行拓扑 (Workflow DAG)</h3>
            <span class="step-count">共 {{ runDetail.steps.length }} 个节点步骤</span>
          </div>

          <div class="timeline-body">
            <div
              v-for="(step, idx) in runDetail.steps"
              :key="step.id"
              class="step-item"
              :class="{
                active: selectedStepId === step.id,
                'status-waiting': step.status === 'WAITING_HUMAN',
                'status-failed': step.status === 'FAILED',
              }"
              @click="selectedStepId = step.id"
            >
              <div class="step-node-line">
                <div class="node-icon" :class="'type-' + step.nodeType.toLowerCase()">
                  {{ getNodeTypeIcon(step.nodeType) }}
                </div>
                <div v-if="idx < runDetail.steps.length - 1" class="connector-line"></div>
              </div>

              <div class="step-content-card">
                <div class="step-top font-sans">
                  <span class="node-name">{{ step.nodeName }}</span>
                  <span class="node-type-badge">{{ step.nodeType }}</span>
                  <span class="step-status-badge" :class="'step-' + step.status.toLowerCase()">
                    {{ formatStepStatus(step.status) }}
                  </span>
                </div>

                <div class="step-sub-info font-mono text-small">
                  <span>Attempt #{{ step.attempt }}</span>
                  <span v-if="step.durationMs">· {{ step.durationMs }}ms</span>
                  <span v-if="step.modelName">· {{ step.modelName }}</span>
                </div>

                <div v-if="step.errorSummary" class="step-err-summary">
                  ⚠️ {{ step.errorSummary }}
                </div>

                <!-- 交互入口按钮区 -->
                <div class="step-actions">
                  <button
                    v-if="step.status === 'WAITING_HUMAN'"
                    class="btn btn-primary btn-xs"
                    @click.stop="openHumanModal(step)"
                  >
                    👤 提交人工确认决策
                  </button>
                  <button
                    v-if="step.status === 'FAILED' && step.retryable"
                    class="btn btn-secondary btn-xs"
                    :disabled="actionInProgress"
                    @click.stop="handleRetry(step)"
                  >
                    🔄 重试当前步骤
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 右侧：Candidate Output / Events 面板 -->
        <div class="glass-card detail-pane-card">
          <div class="pane-tabs">
            <button :class="{ active: rightTab === 'output' }" @click="rightTab = 'output'">
              📦 候选输出 (Candidate Output)
            </button>
            <button
              :class="{ active: rightTab === 'step_detail' }"
              @click="rightTab = 'step_detail'"
            >
              🔍 选中节点详情
            </button>
            <button :class="{ active: rightTab === 'events' }" @click="rightTab = 'events'">
              ⚡ 游标事件流 ({{ events.length }})
            </button>
          </div>

          <div class="pane-body">
            <!-- Tab 1: 最终候选输出 -->
            <div v-if="rightTab === 'output'" class="output-tab">
              <div v-if="runDetail.finalOutput" class="json-box">
                <div class="json-header">
                  <span>最终成果 Candidate Output</span>
                  <button class="btn btn-text-sm" @click="copyJson(runDetail.finalOutput)">
                    复制 JSON
                  </button>
                </div>
                <pre class="json-code font-mono">{{
                  JSON.stringify(runDetail.finalOutput, null, 2)
                }}</pre>
              </div>
              <div v-else class="empty-placeholder">
                <span class="icon">⏳</span>
                <p>工作流尚在运行或中断中，暂未生成最终成果。</p>
              </div>
            </div>

            <!-- Tab 2: 选中步骤详情 -->
            <div v-if="rightTab === 'step_detail'" class="step-detail-tab">
              <div v-if="currentSelectedStep" class="step-meta-box">
                <h4>{{ currentSelectedStep.nodeName }} ({{ currentSelectedStep.nodeId }})</h4>
                <p class="text-muted">
                  Node Type: {{ currentSelectedStep.nodeType }} | ID: {{ currentSelectedStep.id }}
                </p>

                <div class="meta-section">
                  <h5>输入概况 (Input Summary)</h5>
                  <pre class="json-code font-mono">{{
                    JSON.stringify(currentSelectedStep.inputSummary || {}, null, 2)
                  }}</pre>
                </div>

                <div v-if="currentSelectedStep.usageSnapshot" class="meta-section">
                  <h5>Token 消耗统计 (Usage)</h5>
                  <pre class="json-code font-mono">{{
                    JSON.stringify(currentSelectedStep.usageSnapshot, null, 2)
                  }}</pre>
                </div>
              </div>
              <div v-else class="empty-placeholder">
                <p>请点击左侧节点查看该步骤输入输出与模型元数据</p>
              </div>
            </div>

            <!-- Tab 3: 实时事件流日志 -->
            <div v-if="rightTab === 'events'" class="events-tab">
              <div class="events-timeline">
                <div v-for="evt in events" :key="evt.id" class="evt-item">
                  <div class="evt-seq font-mono">#{{ evt.sequenceNo }}</div>
                  <div class="evt-main">
                    <div class="evt-title font-mono">
                      <span class="evt-type">{{ evt.eventType }}</span>
                      <span class="evt-time text-muted">{{ formatDate(evt.createdAt) }}</span>
                    </div>
                    <pre
                      v-if="Object.keys(evt.payload || {}).length > 0"
                      class="evt-payload font-mono"
                      >{{ JSON.stringify(evt.payload, null, 2) }}</pre>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Human Gate 交互弹窗 (Human Gate Decision Modal) -->
    <div v-if="showHumanModal" class="modal-overlay">
      <div class="modal-card">
        <div class="modal-header">
          <h3>👤 人工决策确认 (Human Gate Action Required)</h3>
          <button class="btn-close" @click="showHumanModal = false">✕</button>
        </div>
        <div class="modal-body">
          <p class="modal-desc">
            节点
            <strong>{{ activeHumanStep?.nodeName }}</strong>
            请求人工审核通过或拒绝，决策提交后工作流将自动恢复。
          </p>

          <div class="form-group">
            <label>决策动作 (Action)</label>
            <div class="radio-group">
              <label class="radio-label">
                <input v-model="humanAction" type="radio" value="APPROVE" />
                <span class="text-success font-bold">✅ 批准通过 (APPROVE)</span>
              </label>
              <label class="radio-label">
                <input v-model="humanAction" type="radio" value="REJECT" />
                <span class="text-danger font-bold">❌ 拒绝中断 (REJECT)</span>
              </label>
            </div>
          </div>

          <div class="form-group">
            <label>决策数据 JSON (Decision Context)</label>
            <textarea
              v-model="humanDecisionJson"
              class="form-control font-mono"
              rows="5"
              placeholder='{"approved": true, "note": "符合测试要求"}'
            ></textarea>
            <span v-if="humanJsonError" class="field-error">{{ humanJsonError }}</span>
          </div>
        </div>

        <div class="modal-footer">
          <button class="btn btn-secondary" @click="showHumanModal = false">取消</button>
          <button
            class="btn btn-primary"
            :disabled="actionInProgress"
            @click="handleSubmitDecision"
          >
            提交决策并恢复
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import type {
  AIRunDetailResponse,
  AIRunEventResponse,
  AIStepExecutionResponse,
  CapabilityRunStatus,
  StepExecutionStatus,
} from "./aiRunsApi";
import { aiRunsApi } from "./aiRunsApi";

const route = useRoute();
const router = useRouter();

const projectId = computed(() => route.params.projectId as string);
const runId = computed(() => route.params.runId as string);

const loading = ref(true);
const error = ref<string | null>(null);
const runDetail = ref<AIRunDetailResponse | null>(null);
const events = ref<AIRunEventResponse[]>([]);
const selectedStepId = ref<string | null>(null);
const rightTab = ref<"output" | "step_detail" | "events">("output");
const actionInProgress = ref(false);

// Human Modal 状态
const showHumanModal = ref(false);
const activeHumanStep = ref<AIStepExecutionResponse | null>(null);
const humanAction = ref<"APPROVE" | "REJECT">("APPROVE");
const humanDecisionJson = ref('{\n  "approved": true,\n  "note": "确认通过"\n}');
const humanJsonError = ref<string | null>(null);

let pollTimer: number | null = null;
let lastSeq = 0;

const currentSelectedStep = computed(() => {
  if (!runDetail.value || !selectedStepId.value) return null;
  return runDetail.value.steps.find((s) => s.id === selectedStepId.value) || null;
});

const canCancel = computed(() => {
  if (!runDetail.value) return false;
  return runDetail.value.run.allowedActions.includes("cancelRun");
});

function goBack(): void {
  void router.push(`/projects/${projectId.value}/agent`);
}

function getNodeTypeIcon(type: string): string {
  switch (type.toUpperCase()) {
    case "SKILL":
      return "🤖";
    case "TRANSFORM":
      return "🔄";
    case "VALIDATOR":
      return "✅";
    case "HUMAN":
      return "👤";
    default:
      return "⚙️";
  }
}

function formatRunStatus(status: CapabilityRunStatus): string {
  const map: Record<CapabilityRunStatus, string> = {
    PENDING: "排队中",
    RUNNING: "运行中",
    WAITING_HUMAN: "等待人工确认",
    WAITING_RETRY: "等待自动重试",
    SUCCEEDED: "成功完成",
    FAILED: "运行失败",
    CANCELLED: "已取消",
  };
  return map[status] || status;
}

function formatStepStatus(status: StepExecutionStatus): string {
  const map: Record<StepExecutionStatus, string> = {
    PENDING: "等待中",
    RUNNING: "执行中",
    WAITING_HUMAN: "挂起等待",
    SUCCEEDED: "已完成",
    FAILED: "失败",
    CANCELLED: "已取消",
    SKIPPED: "已跳过",
  };
  return map[status] || status;
}

function formatDate(isoStr: string | null): string {
  if (!isoStr) return "-";
  return new Date(isoStr).toLocaleString();
}

async function loadData(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    const detail = await aiRunsApi.getRunDetail(projectId.value, runId.value);
    runDetail.value = detail;
    if (!selectedStepId.value && detail.steps.length > 0) {
      selectedStepId.value = detail.steps[0].id;
    }
    await fetchNewEvents();
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : "加载运行记录失败";
  } finally {
    loading.value = false;
  }
}

async function fetchNewEvents(): Promise<void> {
  try {
    const pollRes = await aiRunsApi.pollEvents(projectId.value, runId.value, lastSeq);
    if (pollRes.events.length > 0) {
      events.value = [...events.value, ...pollRes.events];
      lastSeq = pollRes.nextSequenceNo;
    }
  } catch {
    // 轮询偶发静默失败
  }
}

function startPolling(): void {
  stopPolling();
  pollTimer = window.setInterval(() => {
    if (!runDetail.value) return;
    const activeStatuses: CapabilityRunStatus[] = ["PENDING", "RUNNING", "WAITING_RETRY"];
    if (activeStatuses.includes(runDetail.value.run.status)) {
      void (async () => {
        try {
          const fresh = await aiRunsApi.getRunDetail(projectId.value, runId.value);
          runDetail.value = fresh;
          await fetchNewEvents();
        } catch {
          // 静默
        }
      })();
    }
  }, 2500);
}

function stopPolling(): void {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function handleRefresh(): void {
  loadData().catch((err: unknown) => console.error(err));
}

function handleCancel(): void {
  confirmCancel().catch((err: unknown) => console.error(err));
}

function handleRetry(step: AIStepExecutionResponse): void {
  confirmRetry(step).catch((err: unknown) => console.error(err));
}

function handleSubmitDecision(): void {
  submitHumanDecision().catch((err: unknown) => console.error(err));
}

async function confirmCancel(): Promise<void> {
  if (!confirm("确定要取消此 AI 运行吗？中断后未处理节点将被跳过。")) return;
  actionInProgress.value = true;
  try {
    await aiRunsApi.cancelRun(projectId.value, runId.value);
    loadData().catch((err: unknown) => console.error(err));
  } catch (err: unknown) {
    alert(err instanceof Error ? err.message : "取消运行失败");
  } finally {
    actionInProgress.value = false;
  }
}

async function confirmRetry(step: AIStepExecutionResponse): Promise<void> {
  actionInProgress.value = true;
  try {
    await aiRunsApi.retryStep(projectId.value, runId.value, step.id);
    loadData().catch((err: unknown) => console.error(err));
  } catch (err: unknown) {
    alert(err instanceof Error ? err.message : "重试节点失败");
  } finally {
    actionInProgress.value = false;
  }
}

async function submitHumanDecision(): Promise<void> {
  if (!activeHumanStep.value) return;
  humanJsonError.value = null;
  let parsedObj: Record<string, unknown> = {};

  try {
    parsedObj = JSON.parse(humanDecisionJson.value) as Record<string, unknown>;
  } catch {
    humanJsonError.value = "JSON 格式语法错误，请检查文本。";
    return;
  }

  actionInProgress.value = true;
  try {
    await aiRunsApi.submitHumanDecision(projectId.value, runId.value, activeHumanStep.value.id, {
      action: humanAction.value,
      decision: parsedObj,
    });
    showHumanModal.value = false;
    await loadData();
  } catch (err: unknown) {
    alert(err instanceof Error ? err.message : "提交决策失败");
  } finally {
    actionInProgress.value = false;
  }
}

function copyJson(data: unknown): void {
  void navigator.clipboard.writeText(JSON.stringify(data, null, 2));
  alert("JSON 候选成果已复制到剪贴板");
}

onMounted(() => {
  loadData().catch((err: unknown) => console.error(err));
  startPolling();
});

onUnmounted(() => {
  stopPolling();
});
</script>

<style scoped>
.run-details-page {
  padding: 24px;
  max-width: 1440px;
  margin: 0 auto;
  min-height: 100vh;
  color: var(--color-text-main, #e2e8f0);
}

.top-nav-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
}

.btn-back {
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.15);
  color: #cbd5e1;
  padding: 6px 14px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.2s;
}
.btn-back:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
}

.breadcrumbs {
  color: #64748b;
  font-size: 13px;
}

.glass-card {
  background: rgba(15, 23, 42, 0.75);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 20px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.36);
}

.header-main {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}

.status-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.badge-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
}
.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}
.status-pending {
  background: rgba(234, 179, 8, 0.15);
  color: #eab308;
}
.status-running {
  background: rgba(59, 130, 246, 0.15);
  color: #60a5fa;
}
.status-waiting_human {
  background: rgba(168, 85, 247, 0.2);
  color: #c084fc;
}
.status-succeeded {
  background: rgba(34, 197, 94, 0.15);
  color: #4ade80;
}
.status-failed {
  background: rgba(239, 68, 68, 0.15);
  color: #f87171;
}
.status-cancelled {
  background: rgba(148, 163, 184, 0.15);
  color: #94a3b8;
}

.mode-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  border: 1px solid rgba(255, 255, 255, 0.15);
  color: #94a3b8;
}

.run-title {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
}

.action-group {
  display: flex;
  gap: 10px;
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  padding-top: 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.meta-item .label {
  font-size: 12px;
  color: #64748b;
}
.meta-item .value {
  font-size: 13px;
  color: #e2e8f0;
}

.workspace-grid {
  display: grid;
  grid-template-columns: 460px 1fr;
  gap: 20px;
}

.timeline-card {
  margin-bottom: 0;
}
.timeline-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-top: 16px;
}

.step-item {
  display: flex;
  gap: 12px;
  cursor: pointer;
}
.step-node-line {
  display: flex;
  flex-direction: column;
  align-items: center;
}
.node-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
}
.connector-line {
  width: 2px;
  flex: 1;
  background: rgba(255, 255, 255, 0.1);
  margin: 4px 0;
}

.step-content-card {
  flex: 1;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 8px;
  padding: 12px 14px;
  transition: all 0.2s;
}
.step-item.active .step-content-card {
  border-color: #3b82f6;
  background: rgba(59, 130, 246, 0.08);
}
.step-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.node-name {
  font-weight: 600;
  font-size: 14px;
  flex: 1;
}
.node-type-badge {
  font-size: 10px;
  background: rgba(255, 255, 255, 0.08);
  padding: 2px 6px;
  border-radius: 4px;
  color: #94a3b8;
}

.step-actions {
  margin-top: 10px;
  display: flex;
  gap: 8px;
}

.pane-tabs {
  display: flex;
  gap: 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  padding-bottom: 12px;
  margin-bottom: 16px;
}
.pane-tabs button {
  background: transparent;
  border: none;
  color: #94a3b8;
  font-size: 14px;
  font-weight: 500;
  padding: 6px 12px;
  border-radius: 6px;
  cursor: pointer;
}
.pane-tabs button.active {
  background: rgba(59, 130, 246, 0.15);
  color: #60a5fa;
}

.json-code {
  background: rgba(0, 0, 0, 0.4);
  border-radius: 8px;
  padding: 14px;
  color: #a5f3fc;
  font-size: 13px;
  overflow-x: auto;
  max-height: 520px;
}

.evt-item {
  display: flex;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}
.evt-seq {
  color: #3b82f6;
  font-size: 12px;
}
.evt-type {
  font-weight: 600;
  color: #f1f5f9;
  margin-right: 10px;
}
.evt-time {
  font-size: 11px;
}
.evt-payload {
  margin-top: 6px;
  font-size: 11px;
  color: #cbd5e1;
  background: rgba(0, 0, 0, 0.3);
  padding: 6px 10px;
  border-radius: 4px;
}

/* Modal Styling */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.modal-card {
  background: #0f172a;
  border: 1px solid rgba(255, 255, 255, 0.15);
  width: 560px;
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.5);
}
.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.modal-header h3 {
  margin: 0;
  font-size: 18px;
}
.btn-close {
  background: transparent;
  border: none;
  color: #94a3b8;
  font-size: 18px;
  cursor: pointer;
}
.form-group {
  margin-bottom: 16px;
}
.form-group label {
  display: block;
  font-size: 13px;
  color: #cbd5e1;
  margin-bottom: 8px;
}
.radio-group {
  display: flex;
  gap: 20px;
}
.radio-label {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}
.form-control {
  width: 100%;
  background: rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.15);
  color: #e2e8f0;
  border-radius: 6px;
  padding: 10px;
  font-size: 13px;
}
.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 24px;
}

/* Base Buttons */
.btn {
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border: none;
  transition: all 0.2s;
}
.btn-primary {
  background: #2563eb;
  color: #fff;
}
.btn-primary:hover {
  background: #1d4ed8;
}
.btn-secondary {
  background: rgba(255, 255, 255, 0.08);
  color: #cbd5e1;
}
.btn-secondary:hover {
  background: rgba(255, 255, 255, 0.15);
}
.btn-danger {
  background: #dc2626;
  color: #fff;
}
.btn-danger:hover {
  background: #b91c1c;
}
.btn-xs {
  padding: 4px 10px;
  font-size: 12px;
  border-radius: 4px;
}
.btn-text-sm {
  background: transparent;
  border: none;
  color: #60a5fa;
  cursor: pointer;
  font-size: 12px;
}
.text-muted {
  color: #64748b;
}
.text-danger {
  color: #f87171;
}
.text-success {
  color: #4ade80;
}
.font-mono {
  font-family: monospace;
}
.field-error {
  color: #f87171;
  font-size: 12px;
  margin-top: 4px;
  display: block;
}
</style>
