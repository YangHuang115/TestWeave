<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { Modal, Button, Spinner } from "@testweave/ui";
import { useExecutionStore } from "../store";
import * as api from "../api";
import type { ExecutionResult } from "../types";
import ResultBadge from "./ResultBadge.vue";

const store = useExecutionStore();

const result = ref<ExecutionResult>("PASSED");
const actualResult = ref("");
const note = ref("");
const links = ref<string[]>([]);
const linkInput = ref("");
const file = ref<File | null>(null);
const localError = ref<string | null>(null);
const saving = ref(false);

const case_ = computed(() => store.recordCase);

watch(case_, (c) => {
  if (c) {
    result.value = "PASSED";
    actualResult.value = "";
    note.value = "";
    links.value = [];
    linkInput.value = "";
    file.value = null;
    localError.value = null;
  }
});

const needsActual = computed(() => result.value === "FAILED");

function addLink(): void {
  const v = linkInput.value.trim();
  if (v && !links.value.includes(v)) links.value.push(v);
  linkInput.value = "";
}

async function save(): Promise<void> {
  if (!case_.value) return;
  localError.value = null;
  if (needsActual.value && !actualResult.value.trim()) {
    localError.value = "失败（FAILED）时必须填写实际结果";
    return;
  }
  saving.value = true;
  try {
    const evidences: Record<string, unknown>[] = [];
    if (file.value) {
      const up = await api.uploadEvidence(store.projectId, store.taskId, file.value);
      evidences.push({
        objectKey: up.objectKey,
        fileName: up.fileName,
        mimeType: up.mimeType,
        fileSize: up.fileSize,
        checksum: up.checksum,
      });
    }
    const rec = await store.saveRecord(case_.value.id, {
      result: result.value,
      actualResult: actualResult.value || null,
      note: note.value || null,
      evidences: evidences.length ? evidences : null,
    });
    if (!rec) return;
    // 外部链接证据：使用独立端点，需 recordId
    for (const url of links.value) {
      await api.addExternalLinkEvidence(store.projectId, store.taskId, rec.id, url);
    }
    await store.openHistory(case_.value);
  } catch (e) {
    localError.value = e instanceof Error ? e.message : "保存失败";
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <Modal
    v-if="case_"
    :title="`录入执行结果`"
    :width="420"
    @close="store.closeRecord()"
  >
    <div class="mono case-id">{{ case_.caseNo }} · {{ case_.title }}</div>

    <div class="field">
      <label>结果 <span class="req">*</span></label>
      <select v-model="result" class="input">
        <option value="PASSED">通过 PASSED</option>
        <option value="FAILED">失败 FAILED</option>
        <option value="BLOCKED">阻塞 BLOCKED</option>
        <option value="SKIPPED">跳过 SKIPPED</option>
      </select>
    </div>

    <div class="field">
      <label>
        实际结果 <span v-if="needsActual" class="req">*</span>
        <span class="hint">（失败必填）</span>
      </label>
      <textarea v-model="actualResult" class="input" rows="3" />
    </div>

    <div class="field">
      <label>执行备注</label>
      <input v-model="note" class="input" placeholder="可选" />
    </div>

    <div class="field">
      <label>外部链接（https）</label>
      <div class="link-row">
        <input v-model="linkInput" class="input" placeholder="https://..." @keyup.enter="addLink" />
        <Button size="sm" variant="ghost" @click="addLink">添加</Button>
      </div>
      <div v-if="links.length" class="links">
        <span v-for="l in links" :key="l" class="chip">{{ l }}</span>
      </div>
    </div>

    <div class="field">
      <label>证据上传</label>
      <input type="file" @change="(e: any) => (file = e.target.files?.[0] ?? null)" />
    </div>

    <div v-if="store.error || localError" class="err">
      {{ localError || store.error }}
    </div>

    <template #footer>
      <Button variant="ghost" :disabled="saving" @click="store.closeRecord()">取消</Button>
      <Button variant="primary" :disabled="saving" @click="save">
        <Spinner v-if="saving" :size="14" /> 保存（新建记录）
      </Button>
    </template>
  </Modal>
</template>

<style scoped>
.case-id {
  font-size: 11px;
  color: var(--tw-muted);
  margin-bottom: 10px;
}
.field {
  margin-bottom: 11px;
}
.field label {
  display: block;
  font-size: 12px;
  color: var(--tw-muted);
  margin-bottom: 5px;
}
.req {
  color: var(--tw-fail);
}
.hint {
  color: var(--tw-faint);
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
textarea.input {
  resize: vertical;
  font-family: inherit;
}
.link-row {
  display: flex;
  gap: 8px;
}
.links {
  margin-top: 6px;
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.chip {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--tw-surface2);
  border: 1px solid var(--tw-border);
  color: var(--tw-muted);
}
.err {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3);
  color: #fca5a5;
  padding: 7px 10px;
  border-radius: 8px;
  font-size: 12px;
  margin-bottom: 8px;
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
</style>
