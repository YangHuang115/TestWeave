<script setup lang="ts">
import { Button } from "@testweave/ui";
import { useExecutionStore } from "../store";

const store = useExecutionStore();
const failed = () => store.task?.failedCount ?? 0;

function viewFailed(): void {
  store.filterUnrun();
  // 失败记录筛选复用未执行信号不合适；此处仅提示，详见 M07。
}
</script>

<template>
  <div class="placeholder">
    <div class="title">缺陷管理将在 M07 接入</div>
    <p class="sub">
      当前仅可查看「失败且无缺陷」的执行记录，待 M07 关联缺陷。M06 不创建临时或伪缺陷数据。
    </p>
    <Button size="sm" variant="ghost" :disabled="true">查看 {{ failed() }} 条失败记录</Button>
  </div>
</template>

<style scoped>
.placeholder {
  text-align: center;
  padding: 48px 20px;
}
.title {
  font-size: 14px;
  color: var(--tw-text);
}
.sub {
  color: var(--tw-muted);
  font-size: 12.5px;
  margin: 8px 0 16px;
}
</style>
