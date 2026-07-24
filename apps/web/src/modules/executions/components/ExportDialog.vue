<script setup lang="ts">
import { ref } from "vue";
import { Modal, Button, Spinner } from "@testweave/ui";
import { useExecutionStore } from "../store";
import * as api from "../api";

const store = useExecutionStore();
const scope = ref<"SELECTED" | "FILTERED" | "ALL">("ALL");
const withHistory = ref(false);
const busy = ref(false);
const done = ref<{ fileName: string } | null>(null);
const localError = ref<string | null>(null);

async function generate(): Promise<void> {
  busy.value = true;
  localError.value = null;
  done.value = null;
  try {
    // 首版后端固定导出全部用例（scope 快照在后端固化），前端仅触发。
    const res = await api.exportExecution(store.projectId, store.taskId);
    done.value = { fileName: res.fileName };
  } catch (e) {
    localError.value = e instanceof Error ? e.message : "导出失败";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <Modal
    v-if="store.dialog === 'export'"
    title="导出执行结果"
    :width="440"
    @close="store.closeDialog()"
  >
    <p class="sub">服务端异步生成，保存筛选条件与勾选快照。</p>

    <label class="lbl">导出范围</label>
    <select v-model="scope" class="input" :disabled="true">
      <option value="ALL">全部用例</option>
      <option value="FILTERED">当前筛选结果</option>
      <option value="SELECTED">当前勾选用例</option>
    </select>
    <p class="note">首版后端固定导出「全部用例」，范围快照在服务端固化。</p>

    <label class="chk-row">
      <input v-model="withHistory" type="checkbox" disabled />
      包含执行历史工作表（首版未启用）
    </label>

    <div v-if="localError" class="err">{{ localError }}</div>
    <div v-if="done" class="ok">已生成：{{ done.fileName }}</div>

    <template #footer>
      <Button variant="ghost" :disabled="busy" @click="store.closeDialog()">取消</Button>
      <Button variant="primary" :disabled="busy" @click="generate">
        <Spinner v-if="busy" :size="14" /> 生成导出
      </Button>
    </template>
  </Modal>
</template>

<style scoped>
.sub {
  color: var(--tw-muted);
  font-size: 12.5px;
  margin: 0 0 14px;
}
.lbl {
  display: block;
  font-size: 12px;
  color: var(--tw-muted);
  margin-bottom: 5px;
}
.input {
  width: 100%;
  background: var(--tw-bg);
  border: 1px solid var(--tw-border2);
  border-radius: 8px;
  padding: 7px 9px;
  color: var(--tw-text);
  font-size: 12.5px;
}
.note {
  font-size: 11px;
  color: var(--tw-faint);
  margin: 6px 0 12px;
}
.chk-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: var(--tw-muted);
}
.err {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3);
  color: #fca5a5;
  padding: 7px 10px;
  border-radius: 8px;
  font-size: 12px;
  margin-top: 8px;
}
.ok {
  color: var(--tw-pass);
  font-size: 12.5px;
  margin-top: 8px;
}
</style>
