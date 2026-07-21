<template>
  <div class="module-tree-container">
    <div class="tree-header">
      <div class="header-title">
        <span class="icon">📁</span>
        <span>模块目录</span>
      </div>
      <button class="btn-icon-add" title="新建根模块" @click="openCreateModal(null)">
        <span>+</span>
      </button>
    </div>

    <div class="tree-body">
      <!-- 全部用例 -->
      <div
        class="tree-node all-node"
        :class="{ active: selectedModuleId === null }"
        @click="selectModule(null)"
      >
        <span class="node-icon">📦</span>
        <span class="node-name">全部用例</span>
      </div>

      <!-- 递归渲染模块树 -->
      <div v-if="modules.length > 0" class="tree-list">
        <TreeNodeItem
          v-for="mod in modules"
          :key="mod.id"
          :node="mod"
          :selected-id="selectedModuleId"
          @select="selectModule"
          @create-child="openCreateModal"
          @rename="openRenameModal"
          @archive="handleArchive"
        />
      </div>
      <div v-else class="empty-hint">暂无用例模块</div>
    </div>

    <!-- 创建 / 修改模块弹窗 -->
    <div v-if="showModal" class="modal-backdrop" @click.self="closeModal">
      <div class="modal-content">
        <h3>{{ isEditing ? '重命名模块' : '新建子模块' }}</h3>
        <div class="form-group">
          <label>模块名称</label>
          <input
            v-model="form.name"
            type="text"
            placeholder="请输入模块名称"
            class="input-control"
            maxlength="100"
            @keyup.enter="submitForm"
          />
        </div>


        <div v-if="errorMsg" class="error-banner">{{ errorMsg }}</div>

        <div class="modal-actions">
          <button class="btn-cancel" @click="closeModal">取消</button>
          <button class="btn-confirm" :disabled="submitting" @click="submitForm">
            {{ submitting ? '保存中...' : '确定' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, defineComponent, h, PropType } from "vue";
import { CaseModuleNode, createModule, updateModule, archiveModule } from "../api";

const props = defineProps({
  projectId: { type: String, required: true },
  modules: { type: Array as () => CaseModuleNode[], default: () => [] },
  selectedModuleId: { type: String as () => string | null, default: null },
});

const emit = defineEmits(["select", "refresh"]);

const showModal = ref(false);
const isEditing = ref(false);
const submitting = ref(false);
const errorMsg = ref("");
const targetParentId = ref<string | null>(null);
const editingModuleId = ref<string | null>(null);

const form = ref({
  name: "",
  sortOrder: 0,
});

function selectModule(id: string | null) {
  emit("select", id);
}

function openCreateModal(parentId: string | null = null) {
  isEditing.value = false;
  targetParentId.value = parentId;
  editingModuleId.value = null;
  form.value = { name: "", sortOrder: 0 };
  errorMsg.value = "";
  showModal.value = true;
}

function openRenameModal(node: CaseModuleNode) {
  isEditing.value = true;
  editingModuleId.value = node.id;
  targetParentId.value = node.parentId;
  form.value = { name: node.name, sortOrder: node.sortOrder };
  errorMsg.value = "";
  showModal.value = true;
}

function closeModal() {
  showModal.value = false;
  submitting.value = false;
  errorMsg.value = "";
}

async function submitForm() {
  if (!form.value.name.trim()) {
    errorMsg.value = "请输入模块名称";
    return;
  }

  try {
    submitting.value = true;
    errorMsg.value = "";

    if (isEditing.value && editingModuleId.value) {
      await updateModule(props.projectId, editingModuleId.value, {
        name: form.value.name.trim(),
        sortOrder: form.value.sortOrder,
      });
    } else {
      await createModule(props.projectId, {
        name: form.value.name.trim(),
        parentId: targetParentId.value,
        sortOrder: form.value.sortOrder,
      });
    }

    closeModal();
    emit("refresh");
  } catch (err: any) {
    submitting.value = false;
    errorMsg.value = err?.response?.data?.message || err?.message || "操作失败";
  }
}

async function handleArchive(node: CaseModuleNode) {
  if (!confirm(`确定归档模块 "${node.name}" 吗？`)) return;

  try {
    await archiveModule(props.projectId, node.id);
    if (props.selectedModuleId === node.id) {
      emit("select", null);
    }
    emit("refresh");
  } catch (err: any) {
    const msg = err?.response?.data?.message || err?.message || "归档失败";
    alert(`归档失败: ${msg}`);
  }
}

// 内部树节点组件
const TreeNodeItem = defineComponent({
  name: "TreeNodeItem",
  props: {
    node: { type: Object as PropType<CaseModuleNode>, required: true },
    selectedId: { type: String as PropType<string | null>, default: null },
  },
  emits: ["select", "create-child", "rename", "archive"],
  setup(p, { emit: itemEmit }) {
    const expanded = ref(true);

    function toggleExpand(e: Event) {
      e.stopPropagation();
      expanded.value = !expanded.value;
    }

    return () => {
      const hasChildren = p.node.children && p.node.children.length > 0;
      const isSelected = p.selectedId === p.node.id;

      return h("div", { class: "tree-node-wrapper" }, [
        h(
          "div",
          {
            class: ["tree-node", { active: isSelected }],
            onClick: () => itemEmit("select", p.node.id),
          },
          [
            hasChildren
              ? h(
                  "span",
                  { class: ["arrow-icon", { expanded: expanded.value }], onClick: toggleExpand },
                  "▶"
                )
              : h("span", { class: "arrow-placeholder" }),
            h("span", { class: "node-icon" }, "📂"),
            h("span", { class: "node-name" }, p.node.name),
            h("div", { class: "node-actions" }, [
              h(
                "button",
                {
                  class: "act-btn",
                  title: "新建子模块",
                  onClick: (e: Event) => {
                    e.stopPropagation();
                    itemEmit("create-child", p.node.id);
                  },
                },
                "+"
              ),
              h(
                "button",
                {
                  class: "act-btn",
                  title: "重命名",
                  onClick: (e: Event) => {
                    e.stopPropagation();
                    itemEmit("rename", p.node);
                  },
                },
                "✏️"
              ),
              h(
                "button",
                {
                  class: "act-btn danger",
                  title: "归档模块",
                  onClick: (e: Event) => {
                    e.stopPropagation();
                    itemEmit("archive", p.node);
                  },
                },
                "🗑️"
              ),
            ]),
          ]
        ),
        hasChildren && expanded.value
          ? h(
              "div",
              { class: "tree-children" },
              p.node.children.map((child) =>
                h(TreeNodeItem, {
                  node: child,
                  selectedId: p.selectedId,
                  onSelect: (id: string | null) => itemEmit("select", id),
                  onCreateChild: (id: string | null) => itemEmit("create-child", id),
                  onRename: (mod: CaseModuleNode) => itemEmit("rename", mod),
                  onArchive: (mod: CaseModuleNode) => itemEmit("archive", mod),
                })
              )
            )
          : null,
      ]);
    };
  },
});
</script>

<style scoped>
.module-tree-container {
  width: 240px;
  background: rgba(15, 23, 42, 0.6);
  border-right: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  flex-direction: column;
  height: 100%;
  user-select: none;
}

.tree-header {
  height: 48px;
  padding: 0 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.header-title {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #e2e8f0;
  font-weight: 600;
  font-size: 14px;
}

.btn-icon-add {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #38bdf8;
  border-radius: 6px;
  width: 26px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 16px;

  &:hover {
    background: rgba(56, 189, 248, 0.15);
  }
}

.tree-body {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0;
}

.tree-node {
  height: 34px;
  padding: 0 12px;
  display: flex;
  align-items: center;
  gap: 6px;
  color: #94a3b8;
  font-size: 13px;
  cursor: pointer;
  border-radius: 6px;
  margin: 2px 8px;
  transition: all 0.15s ease;

  &:hover {
    background: rgba(255, 255, 255, 0.05);
    color: #e2e8f0;

    .node-actions {
      display: flex;
    }
  }

  &.active {
    background: rgba(56, 189, 248, 0.15);
    color: #38bdf8;
    font-weight: 500;
  }
}

.arrow-icon {
  font-size: 9px;
  width: 14px;
  height: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.15s ease;
  color: #64748b;

  &.expanded {
    transform: rotate(90deg);
  }
}

.arrow-placeholder {
  width: 14px;
}

.node-name {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.node-actions {
  display: none;
  align-items: center;
  gap: 4px;
}

.act-btn {
  background: transparent;
  border: none;
  color: #94a3b8;
  font-size: 11px;
  padding: 2px 4px;
  border-radius: 4px;
  cursor: pointer;

  &:hover {
    background: rgba(255, 255, 255, 0.1);
    color: #f8fafc;
  }

  &.danger:hover {
    background: rgba(239, 68, 68, 0.2);
    color: #f87171;
  }
}

.tree-children {
  padding-left: 12px;
}

.empty-hint {
  padding: 20px;
  text-align: center;
  color: #64748b;
  font-size: 12px;
}

/* Modal CSS */
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
  width: 380px;
  padding: 24px;
  color: #f8fafc;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5);
}

.form-group {
  margin-top: 16px;

  label {
    display: block;
    font-size: 12px;
    color: #94a3b8;
    margin-bottom: 6px;
  }
}

.input-control {
  width: 100%;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
  height: 36px;
  padding: 0 12px;
  color: #f8fafc;
  font-size: 13px;

  &:focus {
    outline: none;
    border-color: #38bdf8;
  }
}

.error-banner {
  margin-top: 12px;
  color: #f87171;
  font-size: 12px;
}

.modal-actions {
  margin-top: 24px;
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.btn-cancel {
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #94a3b8;
  padding: 6px 16px;
  border-radius: 6px;
  cursor: pointer;
}

.btn-confirm {
  background: #0284c7;
  border: none;
  color: #ffffff;
  padding: 6px 16px;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 500;

  &:hover {
    background: #0369a1;
  }

  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
}
</style>
