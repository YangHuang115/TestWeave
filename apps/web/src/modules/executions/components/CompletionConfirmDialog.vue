<script setup lang="ts">
import { computed } from "vue";
import { Modal, Button } from "@testweave/ui";
import { useExecutionStore } from "../store";

const store = useExecutionStore();
const c = computed(() => store.completion);

async function onComplete(): Promise<void> {
  await store.complete();
}
function onFilterUnrun(): void {
  store.filterUnrun();
  store.closeDialog();
}
</script>

<template>
  <Modal
    v-if="store.dialog === 'complete' && c"
    title="确认完成执行任务？"
    :width="460"
    @close="store.closeDialog()"
  >
    <p class="sub">
      完成后将进入只读状态：禁止新增执行记录、上传证据与关联缺陷（仍可查看与导出）。
    </p>

    <div v-if="c.notRun > 0" class="warn">
      ⚠ 仍有 <b>{{ c.notRun }}</b> 个用例未执行，无法完成。请先执行全部用例。
    </div>

    <div class="kv"><span class="k">总用例</span><span>{{ c.total }}</span></div>
    <div class="kv"><span class="k">未执行</span><span class="danger">{{ c.notRun }}</span></div>
    <div class="kv">
      <span class="k">通过 / 失败 / 阻塞 / 跳过</span>
      <span>{{ c.passed }} / {{ c.failed }} / {{ c.blocked }} / {{ c.skipped }}</span>
    </div>
    <div class="kv">
      <span class="k">失败且无缺陷</span><span class="warn-t">{{ c.failureWithoutDefect }}</span>
    </div>

    <template #footer>
      <Button variant="ghost" :disabled="store.busy" @click="store.closeDialog()">取消</Button>
      <Button variant="ghost" :disabled="store.busy" @click="onFilterUnrun">
        筛选未执行 →
      </Button>
      <Button variant="primary" :disabled="store.busy || c.notRun > 0" @click="onComplete">
        完成
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
.warn {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3);
  color: #fca5a5;
  border-radius: 10px;
  padding: 11px;
  font-size: 12.5px;
  margin-bottom: 14px;
}
.kv {
  display: flex;
  justify-content: space-between;
  padding: 7px 0;
  border-bottom: 1px solid var(--tw-border);
  font-size: 13px;
}
.k {
  color: var(--tw-muted);
}
.danger {
  color: var(--tw-fail);
}
.warn-t {
  color: var(--tw-block);
}
</style>
