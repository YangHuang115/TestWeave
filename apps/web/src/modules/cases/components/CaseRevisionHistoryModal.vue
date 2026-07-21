<template>
  <div v-if="visible" class="modal-backdrop" @click.self="$emit('close')">
    <div class="modal-content">
      <div class="modal-header">
        <h3>用例修订历史记录 - {{ caseItem?.caseNo }}</h3>
        <button class="btn-close" @click="$emit('close')">×</button>
      </div>

      <div class="modal-body">
        <div v-if="loading" class="state-msg">加载修订版本中...</div>
        <div v-else-if="revisions.length === 0" class="state-msg">暂无历史修订版本</div>
        <div v-else class="revision-list">
          <div v-for="rev in revisions" :key="rev.id" class="revision-card">
            <div class="rev-header">
              <span class="rev-no">Revision {{ rev.revisionNo }}</span>
              <span class="rev-time">{{ formatDate(rev.createdAt) }}</span>
            </div>
            <div class="rev-hash">快照 Hash: {{ rev.snapshotHash.substring(0, 16) }}...</div>
            <div v-if="rev.changeSummary && Object.keys(rev.changeSummary).length" class="rev-summary">
              变更信息: {{ JSON.stringify(rev.changeSummary) }}
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, PropType } from "vue";
import { TestCaseItem, TestCaseRevision, getTestCaseRevisions } from "../api";

const props = defineProps({
  visible: { type: Boolean, default: false },
  projectId: { type: String, required: true },
  caseItem: { type: Object as PropType<TestCaseItem | null>, default: null },
});

defineEmits(["close"]);

const loading = ref(false);
const revisions = ref<TestCaseRevision[]>([]);

watch(
  () => [props.visible, props.caseItem],
  async ([vis, item]) => {
    if (vis && item) {
      try {
        loading.value = true;
        revisions.value = await getTestCaseRevisions(props.projectId, (item as TestCaseItem).id);
      } catch (err: any) {
        console.error("获取修订历史失败", err);
      } finally {
        loading.value = false;
      }
    }
  }
);

function formatDate(isoStr: string) {
  if (!isoStr) return "";
  return new Date(isoStr).toLocaleString("zh-CN");
}
</script>

<style scoped>
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-content {
  background: #1e293b;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  width: 520px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  color: #f8fafc;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5);
}

.modal-header {
  height: 52px;
  padding: 0 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);

  h3 {
    font-size: 15px;
    font-weight: 600;
    color: #e2e8f0;
  }
}

.btn-close {
  background: transparent;
  border: none;
  color: #94a3b8;
  font-size: 20px;
  cursor: pointer;

  &:hover {
    color: #f8fafc;
  }
}

.modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.state-msg {
  text-align: center;
  color: #64748b;
  padding: 30px 0;
}

.revision-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.revision-card {
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 8px;
  padding: 12px 16px;
}

.rev-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.rev-no {
  font-weight: 600;
  color: #38bdf8;
  font-size: 13px;
}

.rev-time {
  color: #64748b;
  font-size: 12px;
}

.rev-hash {
  font-family: monospace;
  font-size: 11px;
  color: #94a3b8;
}

.rev-summary {
  margin-top: 6px;
  font-size: 12px;
  color: #cbd5e1;
}
</style>
