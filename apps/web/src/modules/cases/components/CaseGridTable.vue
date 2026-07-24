<template>
  <div class="grid-table-container">
    <!-- 顶部 Toolbar 与 FilterBar -->
    <div class="grid-toolbar">
      <div class="filter-left">
        <div class="search-box">
          <span class="search-icon">🔍</span>
          <input
            v-model="filterKeyword"
            type="text"
            placeholder="搜索用例编号、标题..."
            class="search-input"
            @input="debouncedFetch"
          />
        </div>

        <select v-model="filterPriority" class="select-filter" @change="fetchCases">
          <option value="">全部优先级</option>
          <option value="URGENT">URGENT (紧急)</option>
          <option value="HIGH">HIGH (高)</option>
          <option value="MEDIUM">MEDIUM (中)</option>
          <option value="LOW">LOW (低)</option>
        </select>

        <select v-model="filterCaseType" class="select-filter" @change="fetchCases">
          <option value="">全部类型</option>
          <option value="FUNCTIONAL">功能测试</option>
          <option value="API">接口测试</option>
          <option value="PERFORMANCE">性能测试</option>
          <option value="SECURITY">安全测试</option>
        </select>
      </div>

      <div class="actions-right">
        <div v-if="activeSessionCount > 0" class="draft-badge">
          <span>📝 {{ activeSessionCount }} 条用例有暂存草稿</span>
          <button class="btn-finalize-all" :disabled="saving" @click="finalizeAllActiveSessions">
            {{ saving ? "发布中..." : "提交发布新版本" }}
          </button>
        </div>

        <button class="btn-add-row" @click="insertDraftRow">
          <span>+ 新增用例行</span>
        </button>
      </div>
    </div>

    <!-- 电子表格区域 -->
    <div class="table-scroll-wrapper">
      <table class="cases-spreadsheet">
        <thead>
          <tr>
            <th class="col-check"><input type="checkbox" /></th>
            <th class="col-no">用例编号</th>
            <th class="col-title">用例标题 *</th>
            <th class="col-modules">所属模块 *</th>
            <th class="col-pre">前置条件</th>
            <th class="col-steps">执行步骤 *</th>
            <th class="col-expected">预期结果 *</th>
            <th class="col-prio">优先级</th>
            <th class="col-type">用例类型</th>
            <th class="col-acts">操作</th>
          </tr>
        </thead>
        <tbody>
          <!-- 正在加载 -->
          <tr v-if="loading">
            <td colspan="10" class="td-state-msg">正在加载用例数据...</td>
          </tr>
          <tr v-else-if="cases.length === 0 && draftRows.length === 0">
            <td colspan="10" class="td-state-msg">
              当前暂无测试用例，点击“新增用例行”开始表格式编写。
            </td>
          </tr>

          <!-- 正式用例列表 (单元格直编) -->
          <tr
            v-for="row in cases"
            :key="row.id"
            :class="{ 'editing-row': editingCaseId === row.id, 'dirty-row': hasDirty(row.id) }"
          >
            <td class="col-check"><input type="checkbox" /></td>
            <td class="col-no text-mono">
              {{ row.caseNo }}
              <span v-if="hasDirty(row.id)" class="tag-dirty" title="有未发布草稿">草稿</span>
            </td>

            <!-- 用例标题 -->
            <td class="col-title cell-editable" @click="focusCell(row.id, 'title')">
              <input
                v-if="editingCaseId === row.id && activeField === 'title'"
                v-model="cellDrafts[row.id].title"
                type="text"
                class="cell-input"
                @blur="handleCellBlur(row)"
              />
              <span v-else class="cell-text">{{ row.title }}</span>
            </td>

            <!-- 所属模块 -->
            <td class="col-modules cell-editable" @click="focusCell(row.id, 'moduleIds')">
              <select
                v-if="editingCaseId === row.id && activeField === 'moduleIds'"
                v-model="cellDrafts[row.id].moduleIds[0]"
                class="cell-select"
                @blur="handleCellBlur(row)"
              >
                <option v-for="m in flatModules" :key="m.id" :value="m.id">{{ m.name }}</option>
              </select>
              <span v-else class="cell-text text-muted">
                {{ getModuleName(row.moduleIds?.[0]) }}
              </span>
            </td>

            <!-- 前置条件 -->
            <td class="col-pre cell-editable" @click="focusCell(row.id, 'precondition')">
              <textarea
                v-if="editingCaseId === row.id && activeField === 'precondition'"
                v-model="cellDrafts[row.id].precondition"
                class="cell-textarea"
                rows="2"
                @blur="handleCellBlur(row)"
              ></textarea>
              <span v-else class="cell-text text-pre">{{ row.precondition || "-" }}</span>
            </td>

            <!-- 执行步骤 (多步骤编辑器) -->
            <td class="col-steps cell-editable" @click="focusCell(row.id, 'steps')">
              <div v-if="editingCaseId === row.id && activeField === 'steps'" class="steps-editor">
                <div
                  v-for="(st, idx) in cellDrafts[row.id].steps"
                  :key="idx"
                  class="step-edit-item"
                >
                  <span class="step-num">{{ idx + 1 }}.</span>
                  <input v-model="st.action" placeholder="输入步骤描述" class="step-input" />
                </div>
                <button class="btn-step-add" @click.stop="addStep(row.id)">+ 添加步骤</button>
                <button class="btn-step-save" @click.stop="handleCellBlur(row)">完成编辑</button>
              </div>
              <div v-else class="steps-preview">
                <div v-for="(st, idx) in row.steps || []" :key="idx" class="step-row">
                  <span class="step-num">{{ idx + 1 }}.</span>
                  <span>{{ st.action }}</span>
                </div>
              </div>
            </td>

            <!-- 预期结果 -->
            <td class="col-expected cell-editable" @click="focusCell(row.id, 'steps')">
              <div v-if="editingCaseId === row.id && activeField === 'steps'" class="steps-editor">
                <div
                  v-for="(st, idx) in cellDrafts[row.id].steps"
                  :key="idx"
                  class="step-edit-item"
                >
                  <span class="step-num">{{ idx + 1 }}.</span>
                  <input
                    v-model="st.expectedResult"
                    placeholder="输入预期结果"
                    class="step-input"
                  />
                  <button
                    class="btn-step-del"
                    title="删除此步骤"
                    @click.stop="removeStep(row.id, idx)"
                  >
                    ×
                  </button>
                </div>
              </div>
              <div v-else class="steps-preview">
                <div v-for="(st, idx) in row.steps || []" :key="idx" class="step-row">
                  <span class="step-num">{{ idx + 1 }}.</span>
                  <span>{{ st.expectedResult }}</span>
                </div>
              </div>
            </td>

            <!-- 优先级 -->
            <td class="col-prio cell-editable" @click="focusCell(row.id, 'priority')">
              <select
                v-if="editingCaseId === row.id && activeField === 'priority'"
                v-model="cellDrafts[row.id].priority"
                class="cell-select"
                @blur="handleCellBlur(row)"
              >
                <option value="URGENT">URGENT</option>
                <option value="HIGH">HIGH</option>
                <option value="MEDIUM">MEDIUM</option>
                <option value="LOW">LOW</option>
              </select>
              <span v-else class="prio-tag" :class="row.priority">{{ row.priority }}</span>
            </td>

            <!-- 用例类型 -->
            <td class="col-type cell-editable" @click="focusCell(row.id, 'caseType')">
              <select
                v-if="editingCaseId === row.id && activeField === 'caseType'"
                v-model="cellDrafts[row.id].caseType"
                class="cell-select"
                @blur="handleCellBlur(row)"
              >
                <option value="FUNCTIONAL">功能测试</option>
                <option value="API">接口测试</option>
                <option value="PERFORMANCE">性能测试</option>
                <option value="SECURITY">安全测试</option>
              </select>
              <span v-else class="type-tag">{{ row.caseType }}</span>
            </td>

            <!-- 操作 -->
            <td class="col-acts">
              <button class="act-btn" title="查看历史修订" @click="$emit('open-history', row)">
                📜 历史
              </button>
            </td>
          </tr>

          <!-- 前端插入的临时空白行 -->
          <tr v-for="(dRow, index) in draftRows" :key="'draft-' + index" class="draft-new-row">
            <td class="col-check">NEW</td>
            <td class="col-no text-muted">新建立即暂存</td>

            <td class="col-title">
              <input
                v-model="dRow.title"
                type="text"
                placeholder="必填：用例标题"
                class="cell-input"
              />
            </td>

            <td class="col-modules">
              <select v-model="dRow.moduleId" class="cell-select">
                <option v-for="m in flatModules" :key="m.id" :value="m.id">{{ m.name }}</option>
              </select>
            </td>

            <td class="col-pre">
              <textarea
                v-model="dRow.precondition"
                placeholder="选填：前置条件"
                class="cell-textarea"
              ></textarea>
            </td>

            <td class="col-steps">
              <div class="steps-editor">
                <div v-for="(st, sIdx) in dRow.steps" :key="sIdx" class="step-edit-item">
                  <span class="step-num">{{ sIdx + 1 }}.</span>
                  <input v-model="st.action" placeholder="步骤描述" class="step-input" />
                </div>
                <button class="btn-step-add" @click="addDraftRowStep(index)">+ 步骤</button>
              </div>
            </td>

            <td class="col-expected">
              <div class="steps-editor">
                <div v-for="(st, sIdx) in dRow.steps" :key="sIdx" class="step-edit-item">
                  <span class="step-num">{{ sIdx + 1 }}.</span>
                  <input v-model="st.expectedResult" placeholder="预期结果" class="step-input" />
                  <button class="btn-step-del" @click="removeDraftRowStep(index, sIdx)">×</button>
                </div>
              </div>
            </td>

            <td class="col-prio">
              <select v-model="dRow.priority" class="cell-select">
                <option value="URGENT">URGENT</option>
                <option value="HIGH">HIGH</option>
                <option value="MEDIUM">MEDIUM</option>
                <option value="LOW">LOW</option>
              </select>
            </td>

            <td class="col-type">
              <select v-model="dRow.caseType" class="cell-select">
                <option value="FUNCTIONAL">功能测试</option>
                <option value="API">接口测试</option>
              </select>
            </td>

            <td class="col-acts">
              <button class="btn-confirm-save" @click="submitDraftRow(index)">保存</button>
              <button class="btn-cancel-draft" @click="removeDraftRow(index)">取消</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from "vue";
import {
  TestCaseItem,
  CaseModuleNode,
  getTestCases,
  getTestCaseDetail,
  createTestCase,
  startEditSession,
  updateSessionDraft,
  finalizeEditSession,
} from "../api";

const props = defineProps({
  projectId: { type: String, required: true },
  selectedModuleId: { type: String as () => string | null, default: null },
  modules: { type: Array as () => CaseModuleNode[], default: () => [] },
});

defineEmits(["open-history"]);

const loading = ref(false);
const saving = ref(false);
const cases = ref<TestCaseItem[]>([]);
const filterKeyword = ref("");
const filterPriority = ref("");
const filterCaseType = ref("");

// 编辑会话及草稿状态
const editingCaseId = ref<string | null>(null);
const activeField = ref<string | null>(null);
const sessionMap = ref<Record<string, { sessionId: string; baseRowVersion: number }>>({});
const cellDrafts = ref<Record<string, any>>({});
const dirtyMap = ref<Record<string, boolean>>({});

// 插入新建的临时空白行列表
const draftRows = ref<any[]>([]);

const activeSessionCount = computed(() => Object.keys(dirtyMap.value).length);

const flatModules = computed(() => {
  const list: { id: string; name: string }[] = [];
  function walk(nodes: CaseModuleNode[]) {
    for (const n of nodes) {
      list.push({ id: n.id, name: n.name });
      if (n.children?.length) walk(n.children);
    }
  }
  walk(props.modules);
  return list;
});

function getModuleName(modId?: string): string {
  if (!modId) return "未归类模块";
  const found = flatModules.value.find((m) => m.id === modId);
  return found ? found.name : "未知模块";
}

let timer: any = null;
function debouncedFetch() {
  clearTimeout(timer);
  timer = setTimeout(fetchCases, 300);
}

async function fetchCases() {
  try {
    loading.value = true;
    const data = await getTestCases(props.projectId, {
      moduleId: props.selectedModuleId,
      keyword: filterKeyword.value,
      priority: filterPriority.value,
      caseType: filterCaseType.value,
    });

    // 补齐 steps
    for (const c of data) {
      if (!c.steps) {
        const detail = await getTestCaseDetail(props.projectId, c.id);
        c.steps = detail.steps || [];
        c.moduleIds = detail.moduleIds || [];
      }
    }
    cases.value = data;
  } catch (err: any) {
    console.error("加载测试用例失败", err);
  } finally {
    loading.value = false;
  }
}

watch(() => props.selectedModuleId, fetchCases);

function hasDirty(caseId: string): boolean {
  return !!dirtyMap.value[caseId];
}

async function focusCell(caseId: string, field: string) {
  editingCaseId.value = caseId;
  activeField.value = field;

  // 初始化该用例的草稿
  if (!cellDrafts.value[caseId]) {
    const c = cases.value.find((x) => x.id === caseId);
    if (c) {
      cellDrafts.value[caseId] = {
        title: c.title,
        precondition: c.precondition || "",
        priority: c.priority,
        caseType: c.caseType,
        moduleIds: [...(c.moduleIds || [])],
        steps: (c.steps || []).map((s) => ({ action: s.action, expectedResult: s.expectedResult })),
      };
    }
  }

  // 建立 Edit Session
  if (!sessionMap.value[caseId]) {
    try {
      const sess = await startEditSession(props.projectId, caseId);
      sessionMap.value[caseId] = {
        sessionId: sess.id,
        baseRowVersion: sess.baseRowVersion,
      };
    } catch (err: any) {
      console.error("启动编辑会话失败", err);
    }
  }
}

function addStep(caseId: string) {
  if (cellDrafts.value[caseId]) {
    cellDrafts.value[caseId].steps.push({ action: "", expectedResult: "" });
  }
}

function removeStep(caseId: string, idx: number) {
  if (cellDrafts.value[caseId] && cellDrafts.value[caseId].steps.length > 1) {
    cellDrafts.value[caseId].steps.splice(idx, 1);
  }
}

async function handleCellBlur(row: TestCaseItem) {
  const caseId = row.id;
  const draft = cellDrafts.value[caseId];
  const session = sessionMap.value[caseId];

  if (!draft || !session) return;

  try {
    // 暂存草稿
    await updateSessionDraft(props.projectId, caseId, session.sessionId, draft);
    dirtyMap.value[caseId] = true;

    // 本地同步视图呈现
    row.title = draft.title;
    row.precondition = draft.precondition;
    row.priority = draft.priority;
    row.caseType = draft.caseType;
    row.moduleIds = draft.moduleIds;
    row.steps = draft.steps;
  } catch (err: any) {
    console.error("暂存草稿失败", err);
  }
}

async function finalizeAllActiveSessions() {
  const caseIds = Object.keys(dirtyMap.value);
  if (caseIds.length === 0) return;

  try {
    saving.value = true;
    for (const caseId of caseIds) {
      const session = sessionMap.value[caseId];
      if (session) {
        await finalizeEditSession(props.projectId, caseId, session.sessionId, {
          note: "电子表格直编发布",
        });
      }
    }
    dirtyMap.value = {};
    sessionMap.value = {};
    cellDrafts.value = {};
    editingCaseId.value = null;
    activeField.value = null;

    alert("用例更新成功，已生成最新不可变修订版本！");
    await fetchCases();
  } catch (err: any) {
    const msg = err?.response?.data?.message || err?.message || "发布更新失败";
    alert(`发布冲突或失败: ${msg}`);
  } finally {
    saving.value = false;
  }
}

// 临时空白行
function insertDraftRow() {
  const defaultModId = props.selectedModuleId || flatModules.value[0]?.id || "";
  draftRows.value.push({
    title: "",
    moduleId: defaultModId,
    precondition: "",
    priority: "MEDIUM",
    caseType: "FUNCTIONAL",
    steps: [{ action: "", expectedResult: "" }],
  });
}

function addDraftRowStep(rIdx: number) {
  draftRows.value[rIdx].steps.push({ action: "", expectedResult: "" });
}

function removeDraftRowStep(rIdx: number, sIdx: number) {
  if (draftRows.value[rIdx].steps.length > 1) {
    draftRows.value[rIdx].steps.splice(sIdx, 1);
  }
}

function removeDraftRow(rIdx: number) {
  draftRows.value.splice(rIdx, 1);
}

async function submitDraftRow(rIdx: number) {
  const dRow = draftRows.value[rIdx];
  if (!dRow.title.trim()) {
    alert("请输入用例标题");
    return;
  }

  const invalidStep = dRow.steps.find((s: any) => !s.action.trim() || !s.expectedResult.trim());
  if (invalidStep) {
    alert("用例步骤的操作描述和预期结果均为必填项！");
    return;
  }

  try {
    await createTestCase(props.projectId, {
      title: dRow.title.trim(),
      precondition: dRow.precondition ? dRow.precondition.trim() : null,
      priority: dRow.priority,
      caseType: dRow.caseType,
      moduleIds: dRow.moduleId ? [dRow.moduleId] : [],
      steps: dRow.steps,
    });
    draftRows.value.splice(rIdx, 1);
    await fetchCases();
  } catch (err: any) {
    alert("新建用例失败: " + (err?.response?.data?.message || err?.message));
  }
}

onMounted(fetchCases);
</script>

<style scoped>
.grid-table-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #0f172a;
  overflow: hidden;
}

.grid-toolbar {
  height: 52px;
  padding: 0 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.filter-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.search-box {
  position: relative;
  width: 220px;
}

.search-icon {
  position: absolute;
  left: 10px;
  top: 8px;
  font-size: 12px;
  color: #64748b;
}

.search-input {
  width: 100%;
  background: rgba(30, 41, 59, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
  height: 32px;
  padding: 0 10px 0 30px;
  color: #f8fafc;
  font-size: 13px;

  &:focus {
    outline: none;
    border-color: #38bdf8;
  }
}

.select-filter {
  background: rgba(30, 41, 59, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
  height: 32px;
  padding: 0 10px;
  color: #94a3b8;
  font-size: 13px;
}

.actions-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.draft-badge {
  display: flex;
  align-items: center;
  gap: 10px;
  background: rgba(234, 179, 8, 0.15);
  border: 1px solid rgba(234, 179, 8, 0.3);
  color: #fde047;
  padding: 4px 12px;
  border-radius: 6px;
  font-size: 12px;
}

.btn-finalize-all {
  background: #eab308;
  color: #0f172a;
  border: none;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 4px;
  cursor: pointer;
}

.btn-add-row {
  background: #0284c7;
  border: none;
  color: #ffffff;
  height: 32px;
  padding: 0 14px;
  border-radius: 6px;
  font-weight: 500;
  font-size: 13px;
  cursor: pointer;

  &:hover {
    background: #0369a1;
  }
}

.table-scroll-wrapper {
  flex: 1;
  overflow: auto;
}

.cases-spreadsheet {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  color: #cbd5e1;

  th {
    position: sticky;
    top: 0;
    background: #1e293b;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    color: #94a3b8;
    font-weight: 600;
    text-align: left;
    padding: 10px 12px;
    white-space: nowrap;
    z-index: 10;
  }

  td {
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    padding: 8px 12px;
    vertical-align: top;
  }
}

.col-check {
  width: 40px;
  text-align: center;
}
.col-no {
  width: 110px;
}
.col-title {
  width: 220px;
}
.col-modules {
  width: 140px;
}
.col-pre {
  width: 180px;
}
.col-steps {
  width: 320px;
}
.col-expected {
  width: 320px;
}
.col-prio {
  width: 90px;
}
.col-type {
  width: 100px;
}
.col-acts {
  width: 90px;
}

.cell-editable {
  cursor: pointer;

  &:hover {
    background: rgba(255, 255, 255, 0.03);
  }
}

.editing-row {
  background: rgba(56, 189, 248, 0.05);
}

.tag-dirty {
  background: rgba(234, 179, 8, 0.2);
  color: #fde047;
  font-size: 10px;
  padding: 1px 4px;
  border-radius: 3px;
  margin-left: 4px;
}

.text-mono {
  font-family: monospace;
  font-size: 12px;
}
.text-muted {
  color: #64748b;
}
.cell-text {
  display: block;
  line-height: 1.5;
}
.cell-pre {
  white-space: pre-wrap;
}

.cell-input,
.cell-select,
.cell-textarea {
  width: 100%;
  background: rgba(15, 23, 42, 0.9);
  border: 1px solid #38bdf8;
  border-radius: 4px;
  color: #f8fafc;
  padding: 4px 8px;
  font-size: 13px;
}

.steps-preview {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.step-row {
  display: flex;
  gap: 6px;
  line-height: 1.4;
}

.step-num {
  color: #38bdf8;
  font-weight: 600;
}

.steps-editor {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.step-edit-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.step-input {
  flex: 1;
  background: rgba(15, 23, 42, 0.9);
  border: 1px solid #38bdf8;
  border-radius: 4px;
  color: #f8fafc;
  padding: 4px 8px;
  font-size: 12px;
}

.btn-step-add,
.btn-step-save {
  background: rgba(255, 255, 255, 0.08);
  border: none;
  color: #38bdf8;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
  align-self: flex-start;
}

.btn-step-del {
  background: transparent;
  border: none;
  color: #ef4444;
  font-size: 14px;
  cursor: pointer;
}

.prio-tag {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 600;

  &.URGENT {
    background: rgba(239, 68, 68, 0.2);
    color: #f87171;
  }
  &.HIGH {
    background: rgba(249, 115, 22, 0.2);
    color: #fb923c;
  }
  &.MEDIUM {
    background: rgba(56, 189, 248, 0.2);
    color: #38bdf8;
  }
  &.LOW {
    background: rgba(148, 163, 184, 0.2);
    color: #cbd5e1;
  }
}

.type-tag {
  background: rgba(255, 255, 255, 0.06);
  color: #94a3b8;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 11px;
}

.act-btn {
  background: transparent;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  font-size: 12px;

  &:hover {
    color: #38bdf8;
  }
}

.btn-confirm-save {
  background: #0284c7;
  border: none;
  color: #fff;
  padding: 4px 8px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  margin-right: 4px;
}

.btn-cancel-draft {
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #94a3b8;
  padding: 4px 8px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
}

.td-state-msg {
  padding: 40px;
  text-align: center;
  color: #64748b;
}
</style>
