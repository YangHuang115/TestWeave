<template>
  <div class="cases-page-container">
    <!-- 左侧：模块目录树 -->
    <CaseModuleTree
      :project-id="projectId"
      :modules="modules"
      :selected-module-id="selectedModuleId"
      @select="handleSelectModule"
      @refresh="fetchModules"
    />

    <!-- 右侧：电子表格多用例直编区域 -->
    <CaseGridTable
      :project-id="projectId"
      :selected-module-id="selectedModuleId"
      :modules="modules"
      @open-history="handleOpenHistory"
    />

    <!-- 历史修订版本弹窗 -->
    <CaseRevisionHistoryModal
      :visible="historyModalVisible"
      :project-id="projectId"
      :case-item="historyTargetCase"
      @close="historyModalVisible = false"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import { useRoute } from "vue-router";
import { CaseModuleNode, TestCaseItem, getModuleTree } from "./api";
import CaseModuleTree from "./components/CaseModuleTree.vue";
import CaseGridTable from "./components/CaseGridTable.vue";
import CaseRevisionHistoryModal from "./components/CaseRevisionHistoryModal.vue";

const route = useRoute();
const projectId = computed(() => (route.params.projectId as string) || "");

const modules = ref<CaseModuleNode[]>([]);
const selectedModuleId = ref<string | null>(null);

const historyModalVisible = ref(false);
const historyTargetCase = ref<TestCaseItem | null>(null);

async function fetchModules() {
  if (!projectId.value) return;
  try {
    modules.value = await getModuleTree(projectId.value);
  } catch (err: any) {
    console.error("拉取模块树失败", err);
  }
}

function handleSelectModule(modId: string | null) {
  selectedModuleId.value = modId;
}

function handleOpenHistory(row: TestCaseItem) {
  historyTargetCase.value = row;
  historyModalVisible.value = true;
}

onMounted(() => {
  fetchModules();
});
</script>

<style scoped>
.cases-page-container {
  display: flex;
  height: calc(100vh - 60px);
  width: 100%;
  overflow: hidden;
  background: #0f172a;
}
</style>
