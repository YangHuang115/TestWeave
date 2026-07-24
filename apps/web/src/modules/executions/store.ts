import { defineStore } from "pinia";
import { ref } from "vue";
import * as api from "./api";
import type {
  BatchPassResult,
  CompletionPreview,
  CreateRecordPayload,
  ExecutionCaseSummary,
  ExecutionRecordSummary,
  ExecutionTaskSummary,
} from "./types";

// 前端生成的幂等键：结果录入 / 批量通过 / 纠错的去重依据
function genIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return "idem-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export const useExecutionStore = defineStore("execution", () => {
  const projectId = ref<string>("");
  const taskId = ref<string>("");
  const task = ref<ExecutionTaskSummary | null>(null);
  const cases = ref<ExecutionCaseSummary[]>([]);
  const loading = ref(false);
  const error = ref<string | null>(null);

  // 记录录入浮层
  const recordCase = ref<ExecutionCaseSummary | null>(null);
  // 历史抽屉
  const historyCase = ref<ExecutionCaseSummary | null>(null);
  const historyRecords = ref<ExecutionRecordSummary[]>([]);
  const historyLoading = ref(false);
  // 对话框
  const dialog = ref<"none" | "complete" | "reopen" | "export">("none");
  const completion = ref<CompletionPreview | null>(null);
  const busy = ref(false);
  // 完成对话框「筛选未执行」驱动网格过滤
  const unrunTick = ref(0);

  async function init(pId: string, tId: string): Promise<void> {
    projectId.value = pId;
    taskId.value = tId;
    await Promise.all([reloadTask(), loadCases()]);
  }

  async function reloadTask(): Promise<void> {
    if (!projectId.value || !taskId.value) return;
    try {
      task.value = await api.getExecutionTask(projectId.value, taskId.value);
    } catch (e) {
      error.value = e instanceof Error ? e.message : "加载任务失败";
    }
  }

  async function loadCases(): Promise<void> {
    if (!projectId.value || !taskId.value) return;
    loading.value = true;
    error.value = null;
    try {
      const res = await api.listExecutionCases(projectId.value, taskId.value, 500);
      cases.value = res.items;
    } catch (e) {
      error.value = e instanceof Error ? e.message : "加载用例失败";
    } finally {
      loading.value = false;
    }
  }

  async function markReady(): Promise<void> {
    if (!task.value) return;
    busy.value = true;
    try {
      // 复用通用 test-tasks 流转，需传入后端返回的当前 rowVersion
      await api.transitionTask(
        projectId.value,
        taskId.value,
        "READY",
        task.value.rowVersion ?? 1,
      );
      await reloadTask();
    } finally {
      busy.value = false;
    }
  }

  async function complete(): Promise<boolean> {
    busy.value = true;
    try {
      await api.completeTask(projectId.value, taskId.value);
      dialog.value = "none";
      await reloadTask();
      return true;
    } catch (e) {
      error.value = e instanceof Error ? e.message : "完成失败";
      return false;
    } finally {
      busy.value = false;
    }
  }

  async function reopen(reasonText: string): Promise<boolean> {
    busy.value = true;
    try {
      await api.reopenTask(projectId.value, taskId.value, reasonText);
      dialog.value = "none";
      await reloadTask();
      return true;
    } catch (e) {
      error.value = e instanceof Error ? e.message : "重新打开失败";
      return false;
    } finally {
      busy.value = false;
    }
  }

  async function doBatchPass(ids: string[]): Promise<BatchPassResult> {
    busy.value = true;
    try {
      const res = await api.batchPass(projectId.value, taskId.value, {
        executionCaseIds: ids,
        idempotencyKey: genIdempotencyKey(),
      });
      await Promise.all([reloadTask(), loadCases()]);
      return res;
    } finally {
      busy.value = false;
    }
  }

  function openRecord(c: ExecutionCaseSummary): void {
    recordCase.value = c;
  }
  function closeRecord(): void {
    recordCase.value = null;
  }

  async function saveRecord(
    executionCaseId: string,
    payload: Omit<CreateRecordPayload, "idempotencyKey">,
  ): Promise<ExecutionRecordSummary | null> {
    busy.value = true;
    try {
      const rec = await api.createRecord(projectId.value, taskId.value, executionCaseId, {
        ...payload,
        idempotencyKey: genIdempotencyKey(),
      });
      closeRecord();
      await Promise.all([reloadTask(), loadCases()]);
      return rec;
    } catch (e) {
      error.value = e instanceof Error ? e.message : "保存执行记录失败";
      return null;
    } finally {
      busy.value = false;
    }
  }

  async function openHistory(c: ExecutionCaseSummary): Promise<void> {
    historyCase.value = c;
    historyLoading.value = true;
    historyRecords.value = [];
    try {
      const res = await api.listRecords(projectId.value, taskId.value, c.id);
      historyRecords.value = res.items;
    } catch (e) {
      error.value = e instanceof Error ? e.message : "加载历史失败";
    } finally {
      historyLoading.value = false;
    }
  }
  function closeHistory(): void {
    historyCase.value = null;
    historyRecords.value = [];
  }

  async function openComplete(): Promise<void> {
    try {
      completion.value = await api.getCompletionPreview(projectId.value, taskId.value);
      dialog.value = "complete";
    } catch (e) {
      error.value = e instanceof Error ? e.message : "获取完成预检失败";
    }
  }

  function openExport(): void {
    dialog.value = "export";
  }
  function openReopen(): void {
    dialog.value = "reopen";
  }
  function closeDialog(): void {
    dialog.value = "none";
  }
  function filterUnrun(): void {
    unrunTick.value++;
  }

  return {
    projectId,
    taskId,
    task,
    cases,
    loading,
    error,
    recordCase,
    historyCase,
    historyRecords,
    historyLoading,
    dialog,
    completion,
    busy,
    init,
    reloadTask,
    loadCases,
    markReady,
    complete,
    reopen,
    doBatchPass,
    openRecord,
    closeRecord,
    saveRecord,
    openHistory,
    closeHistory,
    openComplete,
    openExport,
    openReopen,
    closeDialog,
    filterUnrun,
    unrunTick,
  };
});
