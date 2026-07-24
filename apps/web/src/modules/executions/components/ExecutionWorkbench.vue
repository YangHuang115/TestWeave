<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { Badge } from "@testweave/ui";
import { useExecutionStore } from "../store";
import OverviewPanel from "./OverviewPanel.vue";
import ExecutionCaseGrid from "./ExecutionCaseGrid.vue";
import DefectPlaceholderTab from "./DefectPlaceholderTab.vue";
import ResultRecordPopover from "./ResultRecordPopover.vue";
import ExecutionHistoryDrawer from "./ExecutionHistoryDrawer.vue";
import CompletionConfirmDialog from "./CompletionConfirmDialog.vue";
import ReopenDialog from "./ReopenDialog.vue";
import ExportDialog from "./ExportDialog.vue";

const route = useRoute();
const store = useExecutionStore();
const tab = ref<"overview" | "cases" | "defect" | "activity">("cases");

async function load(): Promise<void> {
  const p = String(route.params.projectId);
  const t = String(route.params.taskId);
  await store.init(p, t);
}

onMounted(load);
watch(() => [route.params.projectId, route.params.taskId], load);
</script>

<template>
  <div class="wb">
    <header class="head">
      <div class="title-row">
        <h2>{{ store.task?.title ?? "加载中…" }}</h2>
        <Badge
          :tone="
            store.task?.status === 'COMPLETED'
              ? 'success'
              : store.task?.status === 'DRAFT'
                ? 'neutral'
                : 'info'
          "
        >
          {{ store.task?.status ?? "" }}
        </Badge>
      </div>
      <div class="meta">
        <span>编号 {{ store.task?.taskNo ?? "—" }}</span>
        <span>负责人 {{ store.task?.ownerId?.slice(0, 8) ?? "—" }}</span>
        <span>需求 {{ store.task?.sourceRequirementTitle ?? "—" }}</span>
        <span>构建 {{ store.task?.buildVersion ?? "—" }}</span>
      </div>
    </header>

    <nav class="tabs">
      <button :class="{ active: tab === 'overview' }" @click="tab = 'overview'">概览</button>
      <button :class="{ active: tab === 'cases' }" @click="tab = 'cases'">执行用例</button>
      <button :class="{ active: tab === 'defect' }" @click="tab = 'defect'">缺陷</button>
      <button :class="{ active: tab === 'activity' }" @click="tab = 'activity'">活动记录</button>
    </nav>

    <section class="content">
      <OverviewPanel v-show="tab === 'overview'" />
      <ExecutionCaseGrid v-if="tab === 'cases'" />
      <DefectPlaceholderTab v-if="tab === 'defect'" />
      <div v-if="tab === 'activity'" class="placeholder">
        <p class="sub">
          活动记录由服务端审计事件记录（test_execution.created / record_created / completed 等），
          M06 首版未暴露列表查询端点，后续补充。
        </p>
      </div>
    </section>

    <!-- 浮层 / 抽屉 / 对话框（自管理显隐） -->
    <ResultRecordPopover />
    <ExecutionHistoryDrawer />
    <CompletionConfirmDialog />
    <ReopenDialog />
    <ExportDialog />
  </div>
</template>

<style scoped>
.wb {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.head {
  padding: 16px 18px 10px;
  border-bottom: 1px solid var(--tw-border);
}
.title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.title-row h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}
.meta {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin-top: 8px;
  font-size: 12px;
  color: var(--tw-muted);
}
.tabs {
  display: flex;
  gap: 4px;
  padding: 0 18px;
  border-bottom: 1px solid var(--tw-border);
}
.tabs button {
  padding: 10px 14px;
  font-size: 13px;
  color: var(--tw-muted);
  border: none;
  background: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
}
.tabs button.active {
  color: var(--tw-text);
  border-bottom-color: var(--tw-accent);
}
.content {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
.placeholder {
  padding: 48px 20px;
  text-align: center;
}
.sub {
  color: var(--tw-muted);
  font-size: 12.5px;
}
</style>
