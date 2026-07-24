<template>
  <div class="ai-workbench">
    <header class="workbench-header">
      <div>
        <button class="back-link" type="button" @click="$emit('back')">← 返回任务详情</button>
        <div class="title-row">
          <div class="title-mark">AI</div>
          <div>
            <h1>AI 测试设计工作台</h1>
            <p v-if="state">
              {{ state.source.task.taskNo }} · {{ state.source.task.title }}
            </p>
            <p v-else>四阶段产物、人工门禁与版本记录</p>
          </div>
        </div>
      </div>
      <div class="header-actions">
        <span v-if="state" class="run-pill" :class="state.run.status.toLowerCase()">
          <span class="status-dot"></span>{{ runStatusLabel(state.run.status) }}
        </span>
        <button type="button" class="secondary-btn" @click="$emit('refresh')">刷新状态</button>
        <button type="button" class="primary-btn" @click="$emit('new-record')">＋ 新建一轮</button>
      </div>
    </header>

    <nav class="stage-nav" aria-label="AI 测试设计阶段">
      <button
        v-for="(stage, index) in visibleStages"
        :key="stage.key"
        type="button"
        class="stage-tab"
        :class="{ active: stage.key === stageKey }"
        @click="$emit('navigate-stage', stage.key)"
      >
        <span class="stage-index">{{ index + 1 }}</span>
        <span class="stage-copy">
          <strong>{{ stage.label }}</strong>
          <small :class="`status-${stage.status.toLowerCase()}`">
            {{ stageStatusLabel(stage.status) }}
          </small>
        </span>
      </button>
    </nav>

    <div v-if="error" class="global-alert error-alert">
      <div>
        <strong>当前操作未完成</strong>
        <p>{{ error }}</p>
      </div>
      <button type="button" @click="$emit('refresh')">重新加载</button>
    </div>
    <div
      v-if="state?.stage.status === 'STALE' || state?.stage.status === 'RERUN_REQUIRED'"
      class="global-alert stale-alert"
    >
      <div>
        <strong>当前阶段已过期</strong>
        <p>上游已接受版本发生变化。请基于最新上游重新生成，过期结果不会继续向下游流转。</p>
      </div>
      <button type="button" @click="$emit('open-feedback')">查看原因并重生成</button>
    </div>
    <div v-if="state?.stage.status === 'WAITING_HUMAN'" class="global-alert human-alert">
      <div>
        <strong>等待人工确认</strong>
        <p>系统不会自动进入下一阶段。请处理阻塞项、保存修改并明确接受当前候选版本。</p>
      </div>
    </div>

    <div class="workbench-grid">
      <aside class="record-panel">
        <div class="panel-heading">
          <div>
            <span class="eyebrow">生成链记录</span>
            <h2>历史轮次</h2>
          </div>
          <span class="count-badge">{{ records.length }}</span>
        </div>
        <div v-if="records.length" class="record-list">
          <button
            v-for="record in records"
            :key="record.id"
            type="button"
            class="record-card"
            :class="{ active: record.id === activeRecordId, 'is-deleting': deletingRecordId === record.id }"
            @click="onCardClick(record.id)"
          >
            <template v-if="deletingRecordId === record.id">
              <div class="confirm-delete-box">
                <span class="delete-warning-text">确认删除此轮吗？</span>
                <div class="delete-btn-group">
                  <button type="button" class="btn-confirm" @click.stop.prevent="executeDelete(record.id)">删除</button>
                  <button type="button" class="btn-cancel" @click.stop.prevent="deletingRecordId = null">取消</button>
                </div>
              </div>
            </template>
            <template v-else>
              <div class="record-title">
                <strong>第 {{ record.recordNo }} 轮</strong>
                <span :class="`record-status status-${record.status.toLowerCase()}`">
                  {{ recordStatusLabel(record.status) }}
                </span>
                <button
                  v-if="records.length > 1"
                  type="button"
                  class="delete-btn"
                  title="删除此轮"
                  @click.stop.prevent="deletingRecordId = record.id"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                </button>
              </div>
              <p>
                {{ record.title.replace(/^第\s*\d+\s*轮\s*·\s*/, "") }}
                <span v-if="record.title.includes('外部') || record.title.includes('External')" class="external-tag">外部 Agent</span>
              </p>
              <div class="mini-stage-row">
                <span
                  v-for="stage in record.stages"
                  :key="stage.key"
                  :title="`${stage.label}：${stageStatusLabel(stage.status)}`"
                  :class="`mini-stage status-${stage.status.toLowerCase()}`"
                ></span>
              </div>
              <small>{{ formatTime(record.updatedAt) }}</small>
            </template>
          </button>
        </div>
        <div v-else class="record-empty">
          <span>◎</span>
          <p>还没有生成记录</p>
          <button type="button" @click="$emit('new-record')">开始第一轮</button>
        </div>
      </aside>

      <main class="artifact-panel">
        <div v-if="loading" class="loading-panel">
          <div class="spinner"></div>
          <strong>正在恢复生成记录</strong>
          <p>读取真实运行状态与当前版本…</p>
        </div>
        <slot v-else />
      </main>

      <aside class="revision-panel">
        <div class="panel-heading">
          <div>
            <span class="eyebrow">版本与人工决策</span>
            <h2>当前阶段</h2>
          </div>
        </div>

        <template v-if="state">
          <div class="revision-status-card">
            <span class="status-label">阶段状态</span>
            <strong>{{ stageStatusLabel(state.stage.status) }}</strong>
            <p v-if="state.stage.candidateRevision">
              候选版本 V{{ state.stage.candidateRevision.revisionNo }} ·
              {{ state.stage.candidateRevision.itemCount }} 项
            </p>
            <p v-else-if="state.stage.acceptedRevision">
              已接受 V{{ state.stage.acceptedRevision.revisionNo }}
            </p>
            <p v-else>尚未形成候选产物</p>
          </div>

          <div v-if="state.stage.steps.length" class="step-timeline">
            <h3>真实运行步骤</h3>
            <div v-for="step in state.stage.steps" :key="step.id" class="step-row">
              <span class="step-dot" :class="step.status.toLowerCase()"></span>
              <div>
                <strong>{{ step.nodeName || step.nodeId }}</strong>
                <small>第 {{ step.attempt }} 次 · {{ stepStatusLabel(step.status) }}</small>
                <p v-if="step.errorSummary">{{ step.errorSummary }}</p>
              </div>
            </div>
          </div>

          <div v-if="latestRegeneration" class="regeneration-card" :class="latestRegeneration.status.toLowerCase()">
            <strong>{{ regenerationStatusLabel(latestRegeneration.status) }}</strong>
            <p v-if="latestRegeneration.status === 'PENDING'">请求已入队，等待服务端执行。</p>
            <p v-else-if="latestRegeneration.status === 'RUNNING'">模型正在依据冻结的反馈快照重生成选中内容。</p>
            <p v-else-if="latestRegeneration.status === 'FAILED'">{{ latestRegeneration.errorSummary || "局部重生成失败，请检查反馈后重新提交。" }}</p>
            <p v-else>已生成新的完整候选版本，仍需人工确认。</p>
          </div>

          <div v-if="state.stage.fieldLocks.length" class="lock-section">
            <h3>已锁定字段</h3>
            <div v-for="lock in state.stage.fieldLocks" :key="lock.id" class="lock-row">
              <span>{{ lock.jsonPointer }}</span>
              <button type="button" @click="$emit('release-lock', lock.id)">解除</button>
            </div>
          </div>

          <div class="action-stack">
            <button
              type="button"
              class="secondary-btn block-btn"
              :disabled="!state.stage.candidateRevision?.baseSetRevisionId"
              @click="$emit('show-diff')"
            >
              查看生成前后 Diff
            </button>
            <button
              type="button"
              class="secondary-btn block-btn"
              :disabled="!state.allowedActions.canFeedback"
              @click="$emit('open-feedback')"
            >
              提交反馈 / 局部重生成
            </button>
            <button
              v-if="state.allowedActions.canRetry"
              type="button"
              class="danger-btn block-btn"
              @click="$emit('retry')"
            >
              安全重试失败步骤
            </button>
            <button
              type="button"
              class="secondary-btn block-btn"
              :disabled="!state.allowedActions.canEdit || !state.stage.candidateRevision"
              @click="$emit('save')"
            >
              {{ saving ? "正在保存…" : dirty ? "仅保存修改" : "当前内容已保存" }}
            </button>
            <button
              type="button"
              class="primary-btn block-btn"
              :disabled="!canAccept || dirty || accepting"
              @click="$emit('accept')"
            >
              {{ accepting ? "正在确认…" : acceptLabel }}
            </button>
            <p v-if="dirty" class="action-hint">请先“仅保存修改”，再接受新候选版本。</p>
            <p v-else-if="!canAccept" class="action-hint">仍有人工门禁条件未满足。</p>
          </div>

          <div class="history-section">
            <h3>版本历史</h3>
            <button
              v-for="revision in state.stage.revisionHistory"
              :key="revision.id"
              type="button"
              class="history-row"
            >
              <span>V{{ revision.revisionNo }}</span>
              <div>
                <strong>{{ revisionStatusLabel(revision.reviewStatus) }}</strong>
                <small>{{ formatTime(revision.createdAt) }}</small>
              </div>
            </button>
            <p v-if="!state.stage.revisionHistory.length" class="muted">暂无版本</p>
          </div>
        </template>
        <div v-else class="revision-empty">选择或新建一条生成记录后查看版本。</div>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import type {
  AiDesignRecordSummary,
  AiDesignStageKey,
  AiRunStatus,
  AiWorkbenchState,
} from "../types";
import { stageStatusLabel } from "../workflow";

const props = defineProps<{
  stageKey: AiDesignStageKey;
  state: AiWorkbenchState | null;
  records: AiDesignRecordSummary[];
  activeRecordId: string | null;
  loading: boolean;
  error: string;
  dirty: boolean;
  saving: boolean;
  accepting: boolean;
  canAccept: boolean;
}>();

const emit = defineEmits<{
  back: [];
  refresh: [];
  "new-record": [];
  "navigate-stage": [stage: AiDesignStageKey];
  "select-record": [recordId: string];
  "delete-record": [recordId: string];
  "show-diff": [];
  "open-feedback": [];
  retry: [];
  "release-lock": [lockId: string];
  save: [];
  accept: [];
}>();

const defaultStages = [
  { key: "requirement-analysis", label: "需求分析", status: "NOT_GENERATED", revisionCount: 0 },
  { key: "test-points", label: "测试点", status: "NOT_GENERATED", revisionCount: 0 },
  { key: "test-cases", label: "测试用例", status: "NOT_GENERATED", revisionCount: 0 },
  { key: "case-review", label: "用例评审", status: "NOT_GENERATED", revisionCount: 0 },
] as const;

const visibleStages = computed(() => props.state?.record.stages ?? defaultStages);
const latestRegeneration = computed(() => props.state?.stage.regenerationRequests[0] ?? null);
const acceptLabel = computed(() =>
  props.stageKey === "case-review" ? "确认评审报告" : "接受并进入下一阶段",
);

function runStatusLabel(status: AiRunStatus): string {
  return {
    PENDING: "等待调度",
    RUNNING: "生成中",
    WAITING_HUMAN: "等待人工确认",
    WAITING_EXTERNAL_AGENT: "等待外接 Agent",
    WAITING_RETRY: "等待重试",
    SUCCEEDED: "已完成",
    FAILED: "生成失败",
    CANCELLED: "已取消",
  }[status];
}

function recordStatusLabel(status: string): string {
  return {
    IN_PROGRESS: "进行中",
    WAITING_HUMAN: "待确认",
    RERUN_REQUIRED: "需重生成",
    COMPLETED: "已完成",
    FAILED: "失败",
    CANCELLED: "已取消",
  }[status] ?? status;
}

function stepStatusLabel(status: string): string {
  return {
    PENDING: "等待执行",
    RUNNING: "执行中",
    WAITING_HUMAN: "等待确认",
    SUCCEEDED: "已完成",
    FAILED: "失败",
    CANCELLED: "已取消",
  }[status] ?? status;
}

function revisionStatusLabel(status: string): string {
  return {
    CANDIDATE: "候选",
    ACCEPTED: "已接受",
    REJECTED: "已驳回",
    SUPERSEDED: "已被新版本替代",
  }[status] ?? status;
}

function regenerationStatusLabel(status: string): string {
  return {
    PENDING: "局部重生成等待执行",
    RUNNING: "局部重生成中",
    COMPLETED: "局部重生成已完成",
    FAILED: "局部重生成失败",
  }[status] ?? status;
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

const deletingRecordId = ref<string | null>(null);

function onCardClick(recordId: string) {
  if (deletingRecordId.value === recordId) return;
  deletingRecordId.value = null;
  emit("select-record", recordId);
}

function executeDelete(recordId: string) {
  emit("delete-record", recordId);
  deletingRecordId.value = null;
}
</script>

<style scoped>
.ai-workbench { min-height: calc(100vh - 64px); background: #f5f7fb; color: #172033; }
.workbench-header { display: flex; justify-content: space-between; gap: 24px; padding: 24px 28px 18px; background: #fff; border-bottom: 1px solid #e6eaf1; }
.back-link { border: 0; background: transparent; color: #667085; padding: 0 0 12px; cursor: pointer; }
.title-row { display: flex; align-items: center; gap: 12px; }
.title-mark { width: 42px; height: 42px; display: grid; place-items: center; border-radius: 12px; color: #fff; font-weight: 800; background: linear-gradient(135deg, #6754e9, #896cff); box-shadow: 0 8px 20px #6754e933; }
h1 { margin: 0; font-size: 23px; letter-spacing: -.02em; }
.title-row p { margin: 4px 0 0; color: #667085; font-size: 13px; }
.header-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.run-pill { display: inline-flex; align-items: center; gap: 7px; border: 1px solid #e4e7ec; background: #f9fafb; border-radius: 999px; padding: 8px 12px; font-size: 13px; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: #98a2b3; }
.run-pill.running .status-dot, .run-pill.pending .status-dot { background: #6d5ce7; box-shadow: 0 0 0 4px #6d5ce71f; animation: pulse 1.5s infinite; }
.run-pill.waiting_human .status-dot { background: #f79009; }
.run-pill.succeeded .status-dot { background: #12b76a; }
.run-pill.failed .status-dot { background: #f04438; }
.primary-btn, .secondary-btn, .danger-btn { border-radius: 9px; padding: 9px 14px; font-weight: 650; cursor: pointer; border: 1px solid transparent; }
.primary-btn { color: #fff; background: #6754e9; box-shadow: 0 4px 12px #6754e933; }
.secondary-btn { color: #344054; background: #fff; border-color: #d0d5dd; }
.danger-btn { color: #b42318; background: #fff5f4; border-color: #fecdca; }
button:disabled { opacity: .48; cursor: not-allowed; box-shadow: none; }
.stage-nav { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; margin: 0; padding: 0 28px; background: #fff; border-bottom: 1px solid #e6eaf1; }
.stage-tab { display: flex; align-items: center; gap: 11px; border: 0; border-bottom: 3px solid transparent; padding: 15px 12px 13px; background: transparent; color: #667085; text-align: left; cursor: pointer; }
.stage-tab.active { color: #5d4bd5; border-bottom-color: #6754e9; background: linear-gradient(180deg, transparent, #6754e908); }
.stage-index { width: 28px; height: 28px; border-radius: 50%; display: grid; place-items: center; background: #f0efff; color: #6754e9; font-weight: 750; }
.stage-copy { display: grid; gap: 2px; }
.stage-copy strong { font-size: 14px; }
.stage-copy small { font-size: 11px; }
.global-alert { margin: 14px 28px 0; display: flex; justify-content: space-between; gap: 18px; align-items: center; padding: 12px 15px; border-radius: 10px; border: 1px solid; }
.global-alert strong, .global-alert p { margin: 0; }.global-alert p { margin-top: 3px; font-size: 13px; }
.global-alert button { border: 0; background: transparent; font-weight: 700; cursor: pointer; }
.error-alert { background: #fff5f4; border-color: #fecdca; color: #912018; }
.stale-alert { background: #fffaeb; border-color: #fedf89; color: #7a2e0e; }
.human-alert { background: #f4f3ff; border-color: #d9d6fe; color: #42307d; }
.workbench-grid { display: grid; grid-template-columns: 230px minmax(0, 1fr) 270px; gap: 14px; padding: 16px 28px 28px; align-items: start; }
.record-panel, .artifact-panel, .revision-panel { background: #fff; border: 1px solid #e4e7ec; border-radius: 12px; box-shadow: 0 2px 8px #1018280a; }
.record-panel, .revision-panel { position: sticky; top: 12px; max-height: calc(100vh - 90px); overflow: auto; }
.artifact-panel { min-height: 620px; overflow: hidden; }
.panel-heading { display: flex; align-items: center; justify-content: space-between; padding: 16px; border-bottom: 1px solid #eaecf0; }
.eyebrow { font-size: 10px; text-transform: uppercase; letter-spacing: .08em; color: #98a2b3; }.panel-heading h2 { margin: 3px 0 0; font-size: 16px; }
.count-badge { min-width: 25px; height: 25px; border-radius: 50%; display: grid; place-items: center; background: #f2f4f7; color: #475467; font-size: 12px; }
.record-list { padding: 8px; display: grid; gap: 7px; }
.record-card { width: 100%; border: 1px solid transparent; background: #fff; border-radius: 9px; padding: 11px; text-align: left; cursor: pointer; }
.record-card:hover { background: #f9fafb; }.record-card.active { background: #f4f3ff; border-color: #d9d6fe; }
.record-title { display: flex; justify-content: space-between; gap: 6px; align-items: center; }.record-title strong { font-size: 13px; }
.record-status { font-size: 10px; border-radius: 999px; background: #f2f4f7; padding: 3px 6px; }
.record-card p { margin: 7px 0; color: #667085; font-size: 12px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }.record-card small { color: #98a2b3; font-size: 10px; }
.mini-stage-row { display: flex; gap: 4px; margin-bottom: 7px; }.mini-stage { height: 4px; flex: 1; border-radius: 999px; background: #e4e7ec; }
.status-accepted, .status-completed { color: #027a48; }.mini-stage.status-accepted { background: #12b76a; }
.status-waiting_human, .status-candidate { color: #b54708; }.mini-stage.status-waiting_human, .mini-stage.status-candidate { background: #f79009; }
.status-generating, .status-in_progress { color: #5925dc; }.mini-stage.status-generating { background: #7f56d9; }
.status-stale, .status-rerun_required, .status-generation_failed, .status-failed { color: #b42318; }.mini-stage.status-stale, .mini-stage.status-rerun_required, .mini-stage.status-generation_failed { background: #f04438; }
.record-empty, .revision-empty { padding: 34px 16px; text-align: center; color: #98a2b3; }.record-empty span { font-size: 25px; }.record-empty button { border: 0; color: #6754e9; background: transparent; font-weight: 700; cursor: pointer; }
.loading-panel { min-height: 620px; display: grid; place-content: center; justify-items: center; gap: 8px; color: #667085; }.loading-panel p { margin: 0; font-size: 12px; }.spinner { width: 30px; height: 30px; border: 3px solid #ebe9fe; border-top-color: #6754e9; border-radius: 50%; animation: spin .8s linear infinite; }
.revision-status-card { margin: 12px; padding: 13px; border-radius: 10px; background: #f9fafb; border: 1px solid #eaecf0; }.status-label { display: block; color: #98a2b3; font-size: 10px; text-transform: uppercase; }.revision-status-card strong { display: block; margin: 5px 0; }.revision-status-card p { margin: 0; color: #667085; font-size: 12px; }
.step-timeline, .history-section { padding: 14px 16px; border-top: 1px solid #eaecf0; }.step-timeline h3, .history-section h3 { margin: 0 0 11px; font-size: 13px; }
.step-row { display: flex; gap: 9px; margin: 11px 0; }.step-dot { width: 9px; height: 9px; margin-top: 4px; border-radius: 50%; background: #98a2b3; }.step-dot.running, .step-dot.pending { background: #7f56d9; }.step-dot.waiting_human { background: #f79009; }.step-dot.succeeded { background: #12b76a; }.step-dot.failed { background: #f04438; }
.step-row div { min-width: 0; }.step-row strong, .step-row small { display: block; font-size: 11px; }.step-row small { color: #98a2b3; margin-top: 2px; }.step-row p { color: #b42318; font-size: 10px; margin: 4px 0 0; }
.action-stack { padding: 12px; display: grid; gap: 8px; border-top: 1px solid #eaecf0; }.block-btn { width: 100%; }.action-hint { margin: 0; color: #667085; font-size: 10px; line-height: 1.4; }
.regeneration-card { margin: 12px; padding: 10px; border: 1px solid #d9d6fe; border-radius: 8px; background: #f4f3ff; color: #42307d; }.regeneration-card.failed { border-color: #fecdca; background: #fff5f4; color: #912018; }.regeneration-card.completed { border-color: #abefc6; background: #ecfdf3; color: #05603a; }.regeneration-card strong { font-size: 11px; }.regeneration-card p { margin: 4px 0 0; font-size: 10px; line-height: 1.45; }
.lock-section { padding: 12px 16px; border-top: 1px solid #eaecf0; }.lock-section h3 { margin: 0 0 8px; font-size: 12px; }.lock-row { display: flex; justify-content: space-between; gap: 7px; align-items: center; padding: 6px 0; color: #667085; font-size: 10px; }.lock-row button { border: 0; background: transparent; color: #6941c6; cursor: pointer; }
.history-row { width: 100%; display: flex; gap: 9px; align-items: center; padding: 8px 0; border: 0; background: transparent; text-align: left; }.history-row > span { width: 31px; height: 31px; border-radius: 8px; background: #f2f4f7; display: grid; place-items: center; font-size: 11px; }.history-row strong, .history-row small { display: block; font-size: 11px; }.history-row small { color: #98a2b3; }.muted { color: #98a2b3; font-size: 12px; }
.external-tag { display: inline-block; margin-left: 4px; padding: 1px 5px; background: #eff8ff; color: #175cd3; border: 1px solid #b2ddff; border-radius: 4px; font-size: 10px; font-weight: 500; }

.record-title { position: relative; }
.delete-btn {
  display: none;
  border: 0;
  background: transparent;
  color: #98a2b3;
  padding: 4px;
  cursor: pointer;
  border-radius: 6px;
  transition: all 0.2s ease-in-out;
}
.record-card:hover .delete-btn, .record-card.active .delete-btn {
  display: block;
}
.delete-btn:hover {
  color: #d92d20;
  background: #fef3f2;
}
.delete-btn svg {
  display: block;
}

.confirm-delete-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 2px 0;
}
.delete-warning-text {
  font-size: 12px;
  color: #b42318;
  font-weight: 650;
}
.delete-btn-group {
  display: flex;
  gap: 6px;
}
.btn-confirm, .btn-cancel {
  border: 1px solid transparent;
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-confirm {
  color: #fff;
  background: #d92d20;
}
.btn-confirm:hover {
  background: #b42318;
}
.btn-cancel {
  color: #344054;
  background: #fff;
  border-color: #d0d5dd;
}
.btn-cancel:hover {
  background: #f9fafb;
}

.record-card.is-deleting {
  border-color: #fca5a5 !important;
  background: #fef2f2 !important;
}

@keyframes spin { to { transform: rotate(360deg); } } @keyframes pulse { 50% { opacity: .45; } }
@media (max-width: 1180px) { .workbench-grid { grid-template-columns: 200px minmax(0, 1fr); }.revision-panel { position: static; grid-column: 1 / -1; max-height: none; }.stage-nav { overflow-x: auto; grid-template-columns: repeat(4, minmax(180px, 1fr)); } }
@media (max-width: 780px) { .workbench-header { flex-direction: column; }.workbench-grid { grid-template-columns: 1fr; padding: 12px; }.record-panel { position: static; max-height: 260px; }.stage-nav { padding: 0 12px; }.global-alert { margin-inline: 12px; }.revision-panel { grid-column: auto; } }
</style>
