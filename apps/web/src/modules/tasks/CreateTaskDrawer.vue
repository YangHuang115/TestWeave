<template>
  <div class="drawer-overlay" @click.self="closeDrawer">
    <div class="drawer-content">
      <div class="drawer-header">
        <h2>新建测试任务</h2>
        <button class="btn-close" @click="closeDrawer">×</button>
      </div>

      <form @submit.prevent="submitForm" class="drawer-body">
        <div class="form-group">
          <label class="required">任务标题</label>
          <input
            type="text"
            v-model="form.title"
            placeholder="请输入简洁清晰的任务标题..."
            class="form-control"
            required
          />
        </div>

        <div class="form-row">
          <div class="form-group">
            <label class="required">任务类型</label>
            <select v-model="form.taskType" class="form-select" @change="handleTypeChange">
              <option value="CASE_DESIGN">用例设计任务 (CASE_DESIGN)</option>
              <option value="TEST_EXECUTION">用例执行任务 (TEST_EXECUTION)</option>
            </select>
          </div>

          <div class="form-group">
            <label class="required">优先级</label>
            <select v-model="form.priority" class="form-select">
              <option value="LOW">低 (LOW)</option>
              <option value="MEDIUM">中 (MEDIUM)</option>
              <option value="HIGH">高 (HIGH)</option>
              <option value="URGENT">紧急 (URGENT)</option>
            </select>
          </div>
        </div>

        <!-- 针对执行模块的提示 -->
        <div v-if="form.taskType === 'TEST_EXECUTION'" class="info-alert danger-alert">
          🚫 <b>用例执行模块尚未接入：</b> 执行任务目前无法进入开始状态，仅供预排期。
        </div>

        <div class="form-row">
          <div class="form-group">
            <label class="required">所属版本</label>
            <select
              v-model="form.versionId"
              class="form-select"
              required
              @change="handleVersionChange"
            >
              <option value="" disabled>请选择关联的版本</option>
              <option v-for="v in versions" :key="v.id" :value="v.id">
                {{ v.key }} - {{ v.name }}
              </option>
            </select>
          </div>

          <div class="form-group">
            <label class="required">负责人</label>
            <select v-model="form.ownerId" class="form-select" required>
              <option value="" disabled>请选择任务负责人</option>
              <option v-for="m in members" :key="m.user_id" :value="m.user_id">
                {{ m.display_name }}
              </option>
            </select>
          </div>
        </div>

        <!-- 版本截止时间上限提示 -->
        <div v-if="selectedVersionEnd" class="info-alert info-glow">
          💡 <b>时间提示：</b> 该版本计划截止于 <b>{{ selectedVersionEnd }}</b
          >，任务截止时间不得晚于该时间。
        </div>

        <div class="form-row">
          <div class="form-group">
            <label class="required">计划开始时间</label>
            <input
              type="datetime-local"
              v-model="form.plannedStartAt"
              class="form-control"
              required
            />
          </div>

          <div class="form-group">
            <label class="required">计划结束时间</label>
            <input
              type="datetime-local"
              v-model="form.plannedEndAt"
              class="form-control"
              required
            />
          </div>
        </div>

        <div class="form-group">
          <label>测试标签 (输入后按回车添加)</label>
          <div class="tag-input-container">
            <div class="tags-list">
              <span v-for="tag in form.tagsJson" :key="tag" class="tag-badge">
                {{ tag }} <span class="tag-remove" @click="removeTag(tag)">×</span>
              </span>
            </div>
            <input
              type="text"
              v-model="newTag"
              placeholder="添加标签..."
              @keydown.enter.prevent="addTag"
              class="form-control"
            />
          </div>
        </div>

        <div class="form-group">
          <label>描述</label>
          <textarea
            v-model="form.description"
            placeholder="任务的背景或补充说明..."
            rows="3"
            class="form-control textarea"
          ></textarea>
        </div>

        <!-- 用例设计任务的专属字段 -->
        <template v-if="form.taskType === 'CASE_DESIGN'">
          <div class="form-group">
            <label class="required">关联需求 (Requirement)</label>
            <select v-model="form.requirementId" class="form-control" required>
              <option value="" disabled>请选择要覆盖的唯一项目需求...</option>
              <option v-for="r in allRequirements" :key="r.id" :value="r.id">
                [{{ r.requirement_no || r.requirementNo }}] {{ r.title }}
              </option>
            </select>
          </div>

          <div class="form-group">
            <label>测试目标 (Test Goal)</label>
            <textarea
              v-model="form.testGoal"
              placeholder="阐述本次用例设计的质量目标和覆盖面要求..."
              rows="2"
              class="form-control textarea"
            ></textarea>
          </div>

          <div class="form-group">
            <label>排除范围 (Excluded Scope)</label>
            <textarea
              v-model="form.excludedScope"
              placeholder="明确本次不覆盖的边界和范围..."
              rows="2"
              class="form-control textarea"
            ></textarea>
          </div>
        </template>

        <div v-if="errorMsg" class="error-msg">❌ {{ errorMsg }}</div>

        <div class="drawer-footer">
          <button type="button" class="btn btn-secondary" @click="closeDrawer" :disabled="saving">
            取消
          </button>
          <button type="submit" class="btn btn-primary btn-glow" :disabled="saving">
            {{ saving ? "正在保存..." : "确认创建" }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from "vue";
import { testTasksApi } from "./api";
import { Version } from "../versions/api";
import { apiClient } from "../../shared/api/client";

interface Member {
  user_id: string;
  display_name: string;
  role_id?: string;
}

const props = defineProps<{
  projectId: string;
  versions: Version[];
  members: Member[];
  defaultVersionId?: string;
  defaultRequirementId?: string;
}>();

const emit = defineEmits(["close", "created"]);

// 状态
const saving = ref(false);
const errorMsg = ref("");
const newTag = ref("");
interface Requirement {
  id: string;
  requirement_no?: string;
  requirementNo?: string;
  title: string;
  status: string;
}

const allRequirements = ref<Requirement[]>([]);

// 设置默认时间 (开始时间为当前时间，结束时间为2天后)
const formatDatetimeLocal = (d: Date) => {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

const defaultStart = new Date();
const defaultEnd = new Date();
defaultEnd.setDate(defaultStart.getDate() + 2);

// 表单数据
const form = reactive({
  title: "",
  versionId: props.defaultVersionId || "",
  taskType: "CASE_DESIGN" as "CASE_DESIGN" | "TEST_EXECUTION",
  ownerId: "",
  plannedStartAt: formatDatetimeLocal(defaultStart),
  plannedEndAt: formatDatetimeLocal(defaultEnd),
  priority: "MEDIUM" as "LOW" | "MEDIUM" | "HIGH" | "URGENT",
  description: "",
  testGoal: "",
  excludedScope: "",
  tagsJson: [] as string[],
  requirementId: props.defaultRequirementId || "",
});

// 加载项目需求
onMounted(() => {
  apiClient
    .get(`/api/v1/projects/${props.projectId}/requirements`, (data) => data as Requirement[])
    .then((list) => {
      allRequirements.value = list.filter((r) => r.status !== "ARCHIVED");
    })
    .catch((err) => {
      console.error("加载项目需求列表失败:", err);
    });
});

// 版本选择辅助提示
const selectedVersionEnd = computed(() => {
  if (!form.versionId) return "";
  const v = props.versions.find((x) => x.id === form.versionId);
  if (v && v.plannedEndAt) {
    const d = new Date(v.plannedEndAt);
    return d.toLocaleString("zh-CN", { timeZone: "UTC" });
  }
  return "";
});

const handleVersionChange = () => {
  const v = props.versions.find((x) => x.id === form.versionId);
  if (v && v.plannedEndAt) {
    // 自动将结束时间限制在版本截止前
    const vEnd = new Date(v.plannedEndAt);
    const formEnd = new Date(form.plannedEndAt);
    if (formEnd > vEnd) {
      form.plannedEndAt = formatDatetimeLocal(vEnd);
    }
  }
};

const handleTypeChange = () => {
  if (form.taskType === "TEST_EXECUTION") {
    form.testGoal = "";
    form.excludedScope = "";
    form.requirementId = "";
  }
};

// 标签控制
const addTag = () => {
  const tag = newTag.value.trim();
  if (tag && !form.tagsJson.includes(tag)) {
    form.tagsJson.push(tag);
  }
  newTag.value = "";
};

const removeTag = (tag: string) => {
  form.tagsJson = form.tagsJson.filter((t) => t !== tag);
};

const closeDrawer = () => {
  emit("close");
};

// 提交表单
const submitForm = async () => {
  saving.value = true;
  errorMsg.value = "";

  try {
    // 前端基础时间校验
    const start = new Date(form.plannedStartAt);
    const end = new Date(form.plannedEndAt);
    if (end <= start) {
      throw new Error("计划结束时间不能早于或等于计划开始时间");
    }

    if (form.taskType === "CASE_DESIGN" && !form.requirementId) {
      throw new Error("用例设计任务必须关联一个项目需求");
    }

    const payload = {
      title: form.title,
      versionId: form.versionId,
      taskType: form.taskType,
      ownerId: form.ownerId,
      plannedStartAt: new Date(form.plannedStartAt).toISOString(),
      plannedEndAt: new Date(form.plannedEndAt).toISOString(),
      priority: form.priority,
      description: form.description || null,
      testGoal: form.taskType === "CASE_DESIGN" ? form.testGoal || null : null,
      excludedScope: form.taskType === "CASE_DESIGN" ? form.excludedScope || null : null,
      tagsJson: form.tagsJson.length > 0 ? form.tagsJson : null,
      requirementId: form.taskType === "CASE_DESIGN" ? form.requirementId || null : null,
    };

    const task = await testTasksApi.create(props.projectId, payload, `req-${Date.now()}`);
    emit("created", task);
  } catch (err: any) {
    errorMsg.value = err.message || "创建任务失败，请检查输入";
  } finally {
    saving.value = false;
  }
};
</script>

<style scoped>
.drawer-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
  z-index: 1000;
  display: flex;
  justify-content: flex-end;
}

.drawer-content {
  width: 580px;
  max-width: 100%;
  height: 100%;
  background: #0f172a;
  border-left: 1px solid rgba(255, 255, 255, 0.08);
  box-shadow: -10px 0 30px rgba(0, 0, 0, 0.5);
  display: flex;
  flex-direction: column;
  animation: slideIn 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

.drawer-header {
  padding: 20px 24px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.drawer-header h2 {
  font-size: 20px;
  font-weight: 600;
  color: #f1f5f9;
  margin: 0;
}

.btn-close {
  background: transparent;
  border: none;
  color: #94a3b8;
  font-size: 28px;
  cursor: pointer;
  line-height: 1;
}

.btn-close:hover {
  color: #f1f5f9;
}

.drawer-body {
  padding: 24px;
  overflow-y: auto;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

label {
  font-size: 13.5px;
  color: #94a3b8;
  font-weight: 500;
}

.required::after {
  content: " *";
  color: #ef4444;
}

.form-control,
.form-select {
  background: rgba(30, 41, 59, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 6px;
  color: #f1f5f9;
  font-size: 14px;
  padding: 10px 12px;
  outline: none;
  width: 100%;
}

.form-control:focus,
.form-select:focus {
  border-color: #6366f1;
}

.textarea {
  resize: vertical;
  min-height: 60px;
}

/* 提示卡片 */
.info-alert {
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 12.5px;
  line-height: 1.5;
}

.info-glow {
  background: rgba(99, 102, 241, 0.1);
  border: 1px solid rgba(99, 102, 241, 0.2);
  color: #cbd5e1;
}

.danger-alert {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.2);
  color: #f87171;
}

/* 标签列表 */
.tag-input-container {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tags-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tag-badge {
  background: rgba(99, 102, 241, 0.15);
  border: 1px solid rgba(99, 102, 241, 0.25);
  color: #a5b4fc;
  font-size: 12px;
  padding: 3px 8px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.tag-remove {
  cursor: pointer;
  font-weight: bold;
  color: #818cf8;
}

.tag-remove:hover {
  color: #f87171;
}

.error-msg {
  color: #ef4444;
  font-size: 13px;
  background: rgba(239, 68, 68, 0.08);
  padding: 8px 12px;
  border-radius: 6px;
}

.drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding-top: 20px;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}

.btn {
  padding: 10px 20px;
  font-size: 14px;
  font-weight: 500;
  border-radius: 6px;
  cursor: pointer;
  border: 1px solid transparent;
}

.btn-primary {
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  color: #ffffff;
}

.btn-glow {
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.btn-secondary {
  background: rgba(30, 41, 59, 0.5);
  color: #cbd5e1;
  border: 1px solid rgba(255, 255, 255, 0.08);
}

@keyframes slideIn {
  from {
    transform: translateX(100%);
  }
  to {
    transform: translateX(0);
  }
}
</style>
