<script setup lang="ts">
import { computed } from "vue";
import { Badge } from "@testweave/ui";
import { useExecutionStore } from "../store";

const store = useExecutionStore();
const t = computed(() => store.task);

const passRate = computed(() => {
  if (!t.value || t.value.totalCount === 0) return 0;
  return Math.round((t.value.passedCount / t.value.totalCount) * 100);
});
const executed = computed(() =>
  t.value ? t.value.totalCount - t.value.notRunCount : 0,
);
</script>

<template>
  <div v-if="t" class="overview">
    <div class="stats">
      <div class="stat"><div class="l">总用例</div><div class="n">{{ t.totalCount }}</div></div>
      <div class="stat"><div class="l">已执行</div><div class="n">{{ executed }}</div></div>
      <div class="stat">
        <div class="l">通过率</div>
        <div class="n" style="color: var(--tw-pass)">{{ passRate }}%</div>
      </div>
      <div class="stat">
        <div class="l">未执行</div>
        <div class="n" style="color: var(--tw-fail)">{{ t.notRunCount }}</div>
      </div>
    </div>
    <div class="progress">
      <i :style="{ width: passRate + '%' }" />
    </div>

    <div class="stats">
      <div class="stat"><div class="l">通过 PASSED</div><div class="n" style="color: var(--tw-pass)">{{ t.passedCount }}</div></div>
      <div class="stat"><div class="l">失败 FAILED</div><div class="n" style="color: var(--tw-fail)">{{ t.failedCount }}</div></div>
      <div class="stat"><div class="l">阻塞 BLOCKED</div><div class="n" style="color: var(--tw-block)">{{ t.blockedCount }}</div></div>
      <div class="stat"><div class="l">跳过 SKIPPED</div><div class="n" style="color: var(--tw-skip)">{{ t.skippedCount }}</div></div>
    </div>

    <div class="info">
      <div class="row"><span class="k">来源设计任务</span><span>{{ t.sourceDesignTaskNo }} · {{ t.title }}</span></div>
      <div class="row"><span class="k">来源需求</span><span>{{ t.sourceRequirementTitle ?? "—" }}</span></div>
      <div class="row"><span class="k">测试环境 / 构建版本</span><span>{{ (t.testEnvironment as any)?.name ?? "—" }} / {{ t.buildVersion ?? "—" }}</span></div>
      <div class="row"><span class="k">执行记录数</span><span>{{ t.executionRecordCount }}</span></div>
    </div>

    <div class="status-row">
      任务状态：<Badge :tone="t.status === 'COMPLETED' ? 'success' : t.status === 'DRAFT' ? 'neutral' : 'info'">{{ t.status }}</Badge>
    </div>
  </div>
</template>

<style scoped>
.overview {
  padding: 18px;
}
.stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}
.stat {
  background: var(--tw-surface);
  border: 1px solid var(--tw-border);
  border-radius: 10px;
  padding: 12px 14px;
}
.l {
  font-size: 12px;
  color: var(--tw-muted);
}
.n {
  font-size: 22px;
  font-weight: 600;
  margin-top: 4px;
}
.progress {
  height: 8px;
  border-radius: 999px;
  background: var(--tw-surface2);
  overflow: hidden;
  margin-bottom: 16px;
}
.progress > i {
  display: block;
  height: 100%;
  background: var(--tw-pass);
}
.info {
  margin-top: 8px;
  background: var(--tw-surface);
  border: 1px solid var(--tw-border);
  border-radius: 10px;
  padding: 6px 14px;
}
.row {
  display: flex;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px solid var(--tw-border);
  font-size: 13px;
  gap: 12px;
}
.row:last-child {
  border-bottom: none;
}
.k {
  color: var(--tw-muted);
}
.status-row {
  margin-top: 14px;
  font-size: 13px;
  color: var(--tw-muted);
}
</style>
