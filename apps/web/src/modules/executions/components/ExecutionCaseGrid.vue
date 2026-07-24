<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { Button } from "@testweave/ui";
import { useExecutionStore } from "../store";
import type { ExecutionCaseSummary, ExecutionResult } from "../types";
import ResultBadge from "./ResultBadge.vue";

const store = useExecutionStore();

const resultFilter = ref<"ALL" | ExecutionResult>("ALL");
const moduleFilter = ref<string>("ALL");
const selected = ref<Set<string>>(new Set());

const modules = computed(() => {
  const set = new Set<string>();
  for (const c of store.cases) {
    for (const m of c.modulePaths ?? []) set.add(m);
  }
  return Array.from(set).sort();
});

const filtered = computed(() => {
  return store.cases.filter((c) => {
    if (resultFilter.value !== "ALL" && (c.currentResult ?? "NOT_RUN") !== resultFilter.value)
      return false;
    if (moduleFilter.value !== "ALL" && !(c.modulePaths ?? []).includes(moduleFilter.value))
      return false;
    return true;
  });
});

const allSelected = computed(
  () =>
    filtered.value.length > 0 &&
    filtered.value.every((c) => selected.value.has(c.id)),
);

function toggleAll(): void {
  if (allSelected.value) {
    for (const c of filtered.value) selected.value.delete(c.id);
  } else {
    for (const c of filtered.value) selected.value.add(c.id);
  }
  selected.value = new Set(selected.value);
}

function toggleOne(c: ExecutionCaseSummary): void {
  if (selected.value.has(c.id)) selected.value.delete(c.id);
  else selected.value.add(c.id);
  selected.value = new Set(selected.value);
}

const selectedIds = computed(() => Array.from(selected.value));

function steps(c: ExecutionCaseSummary): string {
  return (c.steps ?? [])
    .map((s, i) => `${i + 1}. ${s.action ?? ""}`)
    .join("\n");
}
function expected(c: ExecutionCaseSummary): string {
  return (c.steps ?? [])
    .map((s, i) => `${i + 1}. ${s.expectedResult ?? ""}`)
    .join("\n");
}

async function batchPass(): Promise<void> {
  if (selectedIds.value.length === 0) return;
  const res = await store.doBatchPass(selectedIds.value);
  selected.value.clear();
  selected.value = new Set();
  alert(
    `批量通过完成：成功 ${res.succeeded} / 失败 ${res.failed} / 共 ${res.total}`,
  );
}

function filterUnrun(): void {
  resultFilter.value = "NOT_RUN";
}

// 完成对话框「筛选未执行」驱动
watch(
  () => store.unrunTick,
  () => {
    resultFilter.value = "NOT_RUN";
  },
);
</script>

<template>
  <div class="grid-wrap">
    <div class="toolbar">
      <select v-model="moduleFilter" class="sel">
        <option value="ALL">全部模块</option>
        <option v-for="m in modules" :key="m" :value="m">{{ m }}</option>
      </select>
      <select v-model="resultFilter" class="sel">
        <option value="ALL">全部结果</option>
        <option value="NOT_RUN">未执行</option>
        <option value="PASSED">通过</option>
        <option value="FAILED">失败</option>
        <option value="BLOCKED">阻塞</option>
        <option value="SKIPPED">跳过</option>
      </select>
      <span class="spacer" />
      <span class="pill">已选 {{ selectedIds.length }} 行</span>
      <Button size="sm" :disabled="selectedIds.length === 0" @click="batchPass">
        批量通过
      </Button>
      <Button size="sm" variant="ghost" @click="store.openExport()">导出 Excel</Button>
      <template v-if="store.task?.status === 'DRAFT'">
        <Button size="sm" variant="primary" :disabled="store.busy" @click="store.markReady()">
          转为就绪
        </Button>
      </template>
      <template v-else-if="store.task?.status === 'COMPLETED'">
        <Button size="sm" variant="ghost" @click="store.openReopen()">重新打开</Button>
      </template>
      <Button
        v-else
        size="sm"
        variant="primary"
        :disabled="store.busy"
        @click="store.openComplete()"
      >
        完成
      </Button>
    </div>

    <div v-if="store.error" class="err">{{ store.error }}</div>

    <div class="table-scroll">
      <table class="grid">
        <thead>
          <tr>
            <th class="c-fixed w-chk">
              <input type="checkbox" :checked="allSelected" @change="toggleAll" />
            </th>
            <th class="w-mod">所属模块</th>
            <th class="w-title">用例标题</th>
            <th class="w-pre">前置条件</th>
            <th class="w-step">执行步骤</th>
            <th class="w-step">预期结果</th>
            <th class="w-res">最新结果</th>
            <th class="w-actual">实际结果／执行备注</th>
            <th class="w-by">最近执行人</th>
            <th class="w-at">最近执行时间</th>
            <th class="w-cnt">执行次数</th>
            <th class="w-def">缺陷</th>
            <th class="w-ev">执行证据</th>
            <th class="w-act">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="c in filtered" :key="c.id">
            <td class="c-fixed w-chk">
              <input type="checkbox" :checked="selected.has(c.id)" @change="toggleOne(c)" />
            </td>
            <td class="w-mod">{{ (c.modulePaths ?? []).join(" / ") || "—" }}</td>
            <td class="w-title">{{ c.title || "—" }}</td>
            <td class="w-pre">{{ c.precondition || "—" }}</td>
            <td class="w-step mono">{{ steps(c) }}</td>
            <td class="w-step mono">{{ expected(c) }}</td>
            <td class="w-res">
              <a href="javascript:void(0)" @click="store.openRecord(c)">
                <ResultBadge :result="c.currentResult" />
              </a>
            </td>
            <td class="w-actual">{{ c.latestActualResult || c.latestNote || "—" }}</td>
            <td class="w-by">{{ c.latestExecutedBy || "—" }}</td>
            <td class="w-at mono">{{ c.latestExecutedAt || "—" }}</td>
            <td class="w-cnt">{{ c.executionCount }}</td>
            <td class="w-def">
              <span class="chip">无</span>
            </td>
            <td class="w-ev">—</td>
            <td class="w-act">
              <button class="link" @click="store.openRecord(c)">录入</button>
              <button class="link" @click="store.openHistory(c)">历史</button>
            </td>
          </tr>
          <tr v-if="filtered.length === 0">
            <td :colspan="14" class="empty">暂无用例（或筛选无匹配）</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="footer-note">
      点击「最新结果」或「录入」打开结果录入层（新增一条执行记录，不编辑当前值）。
      <button class="link" @click="filterUnrun">一键筛选未执行</button>
    </div>
  </div>
</template>

<style scoped>
.grid-wrap {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 11px 16px;
  border-bottom: 1px solid var(--tw-border);
  flex-wrap: wrap;
  background: var(--tw-bg);
}
.spacer {
  flex: 1;
}
.sel {
  font-size: 12px;
  padding: 5px 9px;
  border-radius: 8px;
  border: 1px solid var(--tw-border2);
  background: var(--tw-surface2);
  color: var(--tw-text);
}
.pill {
  font-size: 11px;
  padding: 3px 9px;
  border-radius: 999px;
  background: var(--tw-surface2);
  color: var(--tw-muted);
  border: 1px solid var(--tw-border);
}
.table-scroll {
  overflow: auto;
  max-height: 60vh;
}
.grid {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  table-layout: fixed;
}
.grid th,
.grid td {
  border-bottom: 1px solid var(--tw-border);
  padding: 8px 10px;
  text-align: left;
  vertical-align: top;
}
.grid thead th {
  background: var(--tw-surface);
  color: var(--tw-muted);
  font-weight: 500;
  font-size: 11.5px;
  position: sticky;
  top: 0;
  white-space: nowrap;
}
.grid tbody tr:hover {
  background: rgba(255, 255, 255, 0.02);
}
.c-fixed {
  position: sticky;
  left: 0;
  background: var(--tw-panel);
  z-index: 1;
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  color: var(--tw-muted);
  white-space: pre-wrap;
  font-size: 11.5px;
  line-height: 1.5;
}
.chip {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--tw-surface2);
  border: 1px solid var(--tw-border);
  color: var(--tw-muted);
}
.link {
  background: none;
  border: none;
  color: var(--tw-accent);
  cursor: pointer;
  font-size: 12px;
  padding: 0 4px;
}
.empty {
  text-align: center;
  color: var(--tw-faint);
  padding: 28px;
}
.err {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3);
  color: #fca5a5;
  padding: 8px 14px;
  font-size: 12.5px;
}
.footer-note {
  padding: 9px 16px;
  font-size: 12px;
  color: var(--tw-muted);
  border-top: 1px solid var(--tw-border);
}
/* 默认列宽（design.md §4.4） */
.w-chk { width: 44px; }
.w-mod { width: 150px; }
.w-title { width: 240px; }
.w-pre { width: 200px; }
.w-step { width: 380px; }
.w-res { width: 112px; }
.w-actual { width: 280px; }
.w-by { width: 120px; }
.w-at { width: 160px; }
.w-cnt { width: 96px; }
.w-def { width: 180px; }
.w-ev { width: 140px; }
.w-act { width: 96px; }
</style>
