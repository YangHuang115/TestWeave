<script setup lang="ts">
import { computed } from "vue";
import { Button, Spinner } from "@testweave/ui";
import { useExecutionStore } from "../store";
import ResultBadge from "./ResultBadge.vue";

const store = useExecutionStore();
const case_ = computed(() => store.historyCase);
</script>

<template>
  <div v-if="case_" class="mask" @click.self="store.closeHistory()">
    <aside class="drawer">
      <header class="head">
        <h3>执行历史 · {{ case_.caseNo }}</h3>
        <button class="x" @click="store.closeHistory()">×</button>
      </header>
      <div v-if="store.historyLoading" class="center">
        <Spinner :size="20" />
      </div>
      <div v-else>
        <div
          v-for="r in store.historyRecords"
          :key="r.id"
          class="rec"
          :class="{ corr: r.recordSource === 'CORRECTION' }"
        >
          <div class="meta">
            <span><ResultBadge :result="r.result" /> #{{ r.recordNo }}</span>
            <span>{{ r.executedBy }} · {{ r.executedAt }}</span>
          </div>
          <div class="src">{{ r.recordSource }}</div>
          <div v-if="r.actualResult" class="body">实际结果：{{ r.actualResult }}</div>
          <div v-if="r.note" class="body muted">备注：{{ r.note }}</div>
          <div v-if="r.correctionNote" class="body warn">
            纠错说明：{{ r.correctionNote }}（指向 #{{ r.correctionOfRecordId?.slice(0, 8) }}）
          </div>
        </div>
        <div v-if="store.historyRecords.length === 0" class="center muted">
          暂无执行记录
        </div>
        <p class="tip">
          主表「最新结果」取最大 record_no；两人同时执行同一用例会各生成一条真实记录，均保留。
        </p>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  z-index: 900;
}
.drawer {
  position: absolute;
  top: 0;
  right: 0;
  height: 100%;
  width: 420px;
  max-width: 92vw;
  background: var(--tw-panel);
  border-left: 1px solid var(--tw-border2);
  padding: 16px;
  overflow: auto;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.head h3 {
  margin: 0;
  font-size: 14px;
}
.x {
  background: none;
  border: none;
  color: var(--tw-muted);
  font-size: 20px;
  cursor: pointer;
}
.rec {
  border: 1px solid var(--tw-border);
  border-radius: 10px;
  padding: 11px 12px;
  margin-bottom: 10px;
  background: var(--tw-surface);
}
.rec.corr {
  border-color: rgba(239, 68, 68, 0.35);
}
.meta {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--tw-muted);
  margin-bottom: 6px;
  gap: 8px;
}
.src {
  font-size: 10.5px;
  color: var(--tw-faint);
  margin-bottom: 4px;
}
.body {
  font-size: 12.5px;
  line-height: 1.5;
}
.muted {
  color: var(--tw-muted);
}
.warn {
  color: #fca5a5;
}
.tip {
  font-size: 11.5px;
  color: var(--tw-faint);
  margin-top: 10px;
}
.center {
  display: flex;
  justify-content: center;
  padding: 40px;
}
</style>
