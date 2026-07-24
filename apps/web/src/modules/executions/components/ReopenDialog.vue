<script setup lang="ts">
import { ref } from "vue";
import { Modal, Button } from "@testweave/ui";
import { useExecutionStore } from "../store";

const store = useExecutionStore();
const reason = ref("");
const localError = ref<string | null>(null);

async function submit(): Promise<void> {
  localError.value = null;
  if (!reason.value.trim()) {
    localError.value = "重开原因必填";
    return;
  }
  const ok = await store.reopen(reason.value.trim());
  if (ok) reason.value = "";
}
</script>

<template>
  <Modal
    v-if="store.dialog === 'reopen'"
    title="重新打开任务"
    :width="440"
    @close="store.closeDialog()"
  >
    <p class="sub">
      仅测试负责人 / 项目管理员可操作。范围与历史保持不变，回到「进行中」。
    </p>
    <label class="lbl">重开原因 <span class="req">*</span></label>
    <textarea v-model="reason" class="input" rows="3" placeholder="如：回归发现新缺陷需补测" />
    <div v-if="localError" class="err">{{ localError }}</div>
    <div v-if="store.error" class="err">{{ store.error }}</div>
    <template #footer>
      <Button variant="ghost" :disabled="store.busy" @click="store.closeDialog()">取消</Button>
      <Button variant="primary" :disabled="store.busy" @click="submit">确认重开</Button>
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
.req {
  color: var(--tw-fail);
}
.input {
  width: 100%;
  background: var(--tw-bg);
  border: 1px solid var(--tw-border2);
  border-radius: 8px;
  padding: 7px 9px;
  color: var(--tw-text);
  font-size: 12.5px;
  font-family: inherit;
  resize: vertical;
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
</style>
