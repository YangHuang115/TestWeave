<template>
  <div class="mindmap-page" :class="{ 'dark-mode': isDarkMode }">
    <!-- 顶部操作栏 -->
    <div class="mindmap-header">
      <div class="header-left">
        <button class="btn-back" @click="goBack">← 返回任务</button>
        <span class="divider">|</span>
        <h3 class="mindmap-title">
          {{ mindmap?.title || '测试用例脑图' }}
        </h3>
        <span class="draft-badge" v-if="hasChanges">未保存</span>
      </div>

      <div class="header-actions">
        <!-- 明暗主题切换 -->
        <button class="btn btn-theme" @click="isDarkMode = !isDarkMode">
          {{ isDarkMode ? '☀️ 切换浅色模式' : '🌙 切换暗黑模式' }}
        </button>
        <button class="btn btn-save" @click="handleSave" :disabled="saving">
          💾 {{ saving ? '正在保存...' : '保存脑图' }}
        </button>
        <button class="btn btn-sync" @click="handleSync" :disabled="syncing">
          ⇄ {{ syncing ? '同步中...' : '一键同步为用例' }}
        </button>
      </div>
    </div>

    <!-- 脑图主画布容器 -->
    <div
      class="canvas-container"
      ref="containerRef"
      @mousedown="startPan"
      @mousemove="onPan"
      @mouseup="endPan"
      @mouseleave="endPan"
      @wheel="onZoom"
    >
      <!-- 画布视口缩放平移层 -->
      <div
        class="mindmap-viewport"
        :style="{ transform: `translate(${panX}px, ${panY}px) scale(${scale})` }"
      >
        <!-- SVG 连线层：绝对定位在 (0, 0)，确保 path 坐标完美呈现线段 -->
        <svg class="svg-connections-layer">
          <path
            v-for="line in connectionLines"
            :key="line.id"
            :d="line.d"
            class="connection-line"
          />
        </svg>

        <!-- 扁平节点渲染列表 -->
        <div
          v-for="node in renderedNodes"
          :key="node.id"
          class="mindmap-node"
          :class="{ selected: selectedNodeId === node.id, root: node.id === 'root' }"
          :style="{ left: `${node.x}px`, top: `${node.y}px` }"
          @mousedown.stop="selectNode(node.id)"
          @dblclick.stop="startEdit(node.id)"
        >
          <div class="node-text-wrapper">
            <!-- 激活编辑时的输入框 -->
            <input
              v-if="editingNodeId === node.id"
              ref="editInputRef"
              v-model="editTempText"
              class="node-input"
              @blur="finishEdit"
              @keydown.enter="finishEdit"
              @keydown.esc="cancelEdit"
              @mousedown.stop
            />
            <span v-else class="node-topic">{{ node.topic }}</span>
          </div>
          <!-- 展开折叠控制小圆点 -->
          <div
            v-if="node.hasChildren"
            class="collapse-dot"
            @click.stop="toggleCollapse(node.id)"
          >
            {{ node.collapsed ? '+' : '-' }}
          </div>
        </div>
      </div>
    </div>

    <!-- 底部快捷键提示浮层 -->
    <div class="shortcuts-tip">
      <span class="tip-item"><b>Tab</b> 新建子节点</span>
      <span class="tip-item"><b>Enter</b> 新建同级节点</span>
      <span class="tip-item"><b>F2 / 双击</b> 编辑节点</span>
      <span class="tip-item"><b>Delete / Backspace</b> 删除节点</span>
      <span class="tip-item"><b>拖拽画布</b> 鼠标右键/中键/空白处</span>
      <span class="tip-item"><b>缩放</b> 鼠标滚轮</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from "vue";
import { useRoute, useRouter } from "vue-router";
import { getMindmap, saveMindmap, syncMindmapToCases, TestCaseMindmap } from "./api";

interface MindNode {
  id: string;
  topic: string;
  children?: MindNode[];
  collapsed?: boolean;
}

const route = useRoute();
const router = useRouter();
const projectId = computed(() => route.params.projectId as string);
const taskId = computed(() => route.params.taskId as string);

// 主题，默认 ProcessOn 式高可视度的浅色明亮模式
const isDarkMode = ref(false);

const mindmap = ref<TestCaseMindmap | null>(null);
const rawTree = ref<MindNode>({
  id: "root",
  topic: "测试用例脑图",
  children: [],
});

const selectedNodeId = ref<string>("root");
const editingNodeId = ref<string | null>(null);
const editTempText = ref("");
const editInputRef = ref<HTMLInputElement[] | null>(null);
const hasChanges = ref(false);

const saving = ref(false);
const syncing = ref(false);

// 画布平移与缩放状态
const panX = ref(350);
const panY = ref(250);
const scale = ref(1.0);
const containerRef = ref<HTMLDivElement | null>(null);

let isPanning = false;
let startX = 0;
let startY = 0;

// 获取与保存脑图
async function loadMindmapData() {
  try {
    const res = await getMindmap(projectId.value, taskId.value);
    mindmap.value = res;
    if (res && res.data && res.data.nodeData) {
      rawTree.value = res.data.nodeData as MindNode;
    }
  } catch (err) {
    console.error("加载脑图失败", err);
  }
}

async function handleSave() {
  if (saving.value) return;
  try {
    saving.value = true;
    const res = await saveMindmap(projectId.value, taskId.value, {
      title: mindmap.value?.title || "测试用例脑图",
      data: { nodeData: rawTree.value },
    });
    mindmap.value = res;
    hasChanges.value = false;
    alert("脑图已成功保存！");
  } catch (err: any) {
    alert("保存脑图失败: " + (err.message || err));
  } finally {
    saving.value = false;
  }
}

async function handleSync() {
  if (syncing.value) return;
  if (hasChanges.value) {
    if (!confirm("您有未保存的脑图修改。是否直接进行同步？（建议先保存）")) return;
  }
  try {
    syncing.value = true;
    const res = await syncMindmapToCases(projectId.value, taskId.value);
    alert(`同步成功！共自动翻译生成了 ${res.syncedCount} 条 TestCase。`);
  } catch (err: any) {
    alert("同步用例失败: " + (err.message || err));
  } finally {
    syncing.value = false;
  }
}

function goBack() {
  router.push(`/projects/${projectId.value}/test-tasks/${taskId.value}`);
}

// -------------------------------------------------------------
// 脑图经典布局算法 (扁平计算节点与连线坐标)
// -------------------------------------------------------------
interface RenderedNode {
  id: string;
  topic: string;
  x: number;
  y: number;
  hasChildren: boolean;
  collapsed: boolean;
}

interface ConnectionLine {
  id: string;
  d: string;
}

// 递归计算每个节点占据的子树总高度 (用于垂直布局)
function calculateSubtreeHeight(node: MindNode): number {
  if (node.collapsed || !node.children || node.children.length === 0) {
    return 60; // 默认节点占位高
  }
  let h = 0;
  for (const child of node.children) {
    h += calculateSubtreeHeight(child);
  }
  return h;
}

// 递归给每个节点计算相对绝对坐标 (x, y)
function computeLayout(
  node: MindNode,
  x: number,
  y: number,
  nodesList: RenderedNode[],
  linesList: ConnectionLine[]
) {
  const hasChildren = !!node.children && node.children.length > 0;
  const collapsed = !!node.collapsed;

  nodesList.push({
    id: node.id,
    topic: node.topic,
    x,
    y,
    hasChildren,
    collapsed,
  });

  if (collapsed || !node.children || node.children.length === 0) return;

  const totalHeight = calculateSubtreeHeight(node);
  let currentY = y - totalHeight / 2;

  const childX = x + 220; // 水平间距 220px

  for (const child of node.children) {
    const childHeight = calculateSubtreeHeight(child);
    const childY = currentY + childHeight / 2;

    // 精准对齐的曲线起点与终点
    const parentWidth = node.id === "root" ? 140 : 100;
    const startX = x + parentWidth;
    const startY = y + 16;
    const endX = childX;
    const endY = childY + 16;

    const cp1x = startX + 60;
    const cp1y = startY;
    const cp2x = endX - 60;
    const cp2y = endY;

    linesList.push({
      id: `${node.id}-${child.id}`,
      d: `M ${startX} ${startY} C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${endX} ${endY}`,
    });

    computeLayout(child, childX, childY, nodesList, linesList);
    currentY += childHeight;
  }
}

const renderedNodes = computed(() => {
  const list: RenderedNode[] = [];
  const lines: ConnectionLine[] = [];
  computeLayout(rawTree.value, 0, 0, list, lines);
  return list;
});

const connectionLines = computed(() => {
  const list: RenderedNode[] = [];
  const lines: ConnectionLine[] = [];
  computeLayout(rawTree.value, 0, 0, list, lines);
  return lines;
});

// -------------------------------------------------------------
// 键盘节点编辑流逻辑 (Tab/Enter/Delete/F2)
// -------------------------------------------------------------
function selectNode(id: string) {
  selectedNodeId.value = id;
}

// 展开/收起
function toggleCollapse(id: string) {
  const node = findNodeById(rawTree.value, id);
  if (node) {
    node.collapsed = !node.collapsed;
    hasChanges.value = true;
  }
}

// 行内直接双击/F2编辑节点文本
function startEdit(id: string) {
  editingNodeId.value = id;
  const node = findNodeById(rawTree.value, id);
  if (node) {
    editTempText.value = node.topic;
    nextTick(() => {
      if (editInputRef.value && editInputRef.value.length > 0) {
        editInputRef.value[0].focus();
        editInputRef.value[0].select();
      }
    });
  }
}

function finishEdit() {
  if (editingNodeId.value === null) return;
  const node = findNodeById(rawTree.value, editingNodeId.value);
  if (node && editTempText.value.trim()) {
    if (node.topic !== editTempText.value.trim()) {
      node.topic = editTempText.value.trim();
      hasChanges.value = true;
    }
  }
  editingNodeId.value = null;
}

function cancelEdit() {
  editingNodeId.value = null;
}

// 快捷键 Tab：新增子节点
function addSubNode() {
  if (editingNodeId.value !== null) return;
  const parentNode = findNodeById(rawTree.value, selectedNodeId.value);
  if (parentNode) {
    parentNode.collapsed = false; // 强行展开
    if (!parentNode.children) {
      parentNode.children = [];
    }
    const newId = "node-" + Date.now();
    const newNode: MindNode = {
      id: newId,
      topic: "新分支节点",
      children: [],
    };
    parentNode.children.push(newNode);
    selectedNodeId.value = newId;
    hasChanges.value = true;

    // 自动触发新节点编辑
    nextTick(() => {
      startEdit(newId);
    });
  }
}

// 快捷键 Enter：新增同级节点
function addSiblingNode() {
  if (editingNodeId.value !== null) return;
  if (selectedNodeId.value === "root") return; // 根节点无同级

  const pInfo = findParentInfo(rawTree.value, selectedNodeId.value);
  if (pInfo) {
    const { parent, index } = pInfo;
    const newId = "node-" + Date.now();
    const newNode: MindNode = {
      id: newId,
      topic: "新同级节点",
      children: [],
    };
    parent.children!.splice(index + 1, 0, newNode);
    selectedNodeId.value = newId;
    hasChanges.value = true;

    nextTick(() => {
      startEdit(newId);
    });
  }
}

// 删除选中节点
function deleteSelectedNode() {
  if (editingNodeId.value !== null) return;
  if (selectedNodeId.value === "root") {
    alert("根节点无法删除！");
    return;
  }

  const pInfo = findParentInfo(rawTree.value, selectedNodeId.value);
  if (pInfo) {
    const { parent, index } = pInfo;
    parent.children!.splice(index, 1);
    selectedNodeId.value = parent.id; // 删除后聚焦回退给父节点
    hasChanges.value = true;
  }
}

// -------------------------------------------------------------
// 辅助查找算法
// -------------------------------------------------------------
function findNodeById(node: MindNode, id: string): MindNode | null {
  if (node.id === id) return node;
  if (node.children) {
    for (const child of node.children) {
      const found = findNodeById(child, id);
      if (found) return found;
    }
  }
  return null;
}

function findParentInfo(
  rootNode: MindNode,
  id: string
): { parent: MindNode; index: number } | null {
  if (rootNode.children) {
    for (let i = 0; i < rootNode.children.length; i++) {
      if (rootNode.children[i].id === id) {
        return { parent: rootNode, index: i };
      }
      const found = findParentInfo(rootNode.children[i], id);
      if (found) return found;
    }
  }
  return null;
}

// -------------------------------------------------------------
// 画布平移、拖拽与缩放逻辑 (Pan & Zoom)
// -------------------------------------------------------------
function startPan(e: MouseEvent) {
  if (e.button !== 2 && e.button !== 1 && e.button !== 0) return;
  isPanning = true;
  startX = e.clientX - panX.value;
  startY = e.clientY - panY.value;
  if (e.button === 2) {
    e.preventDefault();
  }
}

function onPan(e: MouseEvent) {
  if (!isPanning) return;
  panX.value = e.clientX - startX;
  panY.value = e.clientY - startY;
}

function endPan() {
  isPanning = false;
}

function onZoom(e: WheelEvent) {
  e.preventDefault();
  const zoomFactor = 0.08;
  if (e.deltaY < 0) {
    scale.value = Math.min(scale.value + zoomFactor, 2.5);
  } else {
    scale.value = Math.max(scale.value - zoomFactor, 0.4);
  }
}

// 键盘事件监听
function handleKeydown(e: KeyboardEvent) {
  if (editingNodeId.value !== null) return;

  if (e.key === "Tab") {
    e.preventDefault();
    addSubNode();
  } else if (e.key === "Enter") {
    e.preventDefault();
    addSiblingNode();
  } else if (e.key === "Delete" || e.key === "Backspace") {
    e.preventDefault();
    deleteSelectedNode();
  } else if (e.key === "F2") {
    e.preventDefault();
    startEdit(selectedNodeId.value);
  }
}

onMounted(() => {
  document.addEventListener("contextmenu", (e) => e.preventDefault());
  window.addEventListener("keydown", handleKeydown);
  loadMindmapData();
});

onUnmounted(() => {
  window.removeEventListener("keydown", handleKeydown);
});
</script>

<style scoped>
.mindmap-page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  width: 100%;
  overflow: hidden;
  background: #f1f5f9; /* 默认浅色清爽模式底色 */
  color: #1e293b;
  user-select: none;
  transition: background 0.25s ease, color 0.25s ease;
}

.mindmap-page.dark-mode {
  background: #090d16;
  color: #e2e8f0;
}

/* 顶部 Header */
.mindmap-header {
  height: 60px;
  background: rgba(255, 255, 255, 0.95);
  border-bottom: 1px solid rgba(0, 0, 0, 0.08);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  backdrop-filter: blur(12px);
  z-index: 10;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
}

.dark-mode .mindmap-header {
  background: rgba(15, 23, 42, 0.95);
  border-bottom-color: rgba(255, 255, 255, 0.1);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.btn-back {
  background: transparent;
  border: none;
  color: #64748b;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;

  &:hover {
    color: #0284c7;
  }
}

.dark-mode .btn-back {
  color: #94a3b8;
}

.dark-mode .btn-back:hover {
  color: #f8fafc;
}

.divider {
  color: #cbd5e1;
}

.dark-mode .divider {
  color: #334155;
}

.mindmap-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: #0f172a;
}

.dark-mode .mindmap-title {
  color: #f1f5f9;
}

.draft-badge {
  font-size: 10px;
  background: rgba(234, 179, 8, 0.15);
  border: 1px solid rgba(234, 179, 8, 0.4);
  color: #ca8a04;
  padding: 1px 6px;
  border-radius: 4px;
}

.dark-mode .draft-badge {
  color: #facc15;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

/* 脑图主画布容器 */
.canvas-container {
  flex: 1;
  width: 100%;
  position: relative;
  overflow: hidden;
  cursor: grab;
  background-image: radial-gradient(rgba(0, 0, 0, 0.08) 1.2px, transparent 1.2px);
  background-size: 24px 24px;
}

.dark-mode .canvas-container {
  background-image: radial-gradient(rgba(255, 255, 255, 0.15) 1.2px, transparent 1.2px);
}

.canvas-container:active {
  cursor: grabbing;
}

.mindmap-viewport {
  position: absolute;
  left: 0;
  top: 0;
  width: 1px;
  height: 1px;
  transform-origin: 0 0;
  pointer-events: none;
}

/* SVG 连线层：固定定位在 (0, 0) 并充许 overflow 溢出，确保线条 100% 能看见 */
.svg-connections-layer {
  position: absolute;
  left: 0;
  top: 0;
  width: 100%;
  height: 100%;
  overflow: visible;
  pointer-events: none;
  z-index: 1;
}

/* 线条极粗且鲜明 */
.connection-line {
  fill: none;
  stroke: #0284c7; /* 浅色下最清晰的鲜艳蓝线 */
  stroke-width: 3.5px;
  transition: stroke 0.2s ease;
}

.dark-mode .connection-line {
  stroke: #38bdf8; /* 暗黑下高发光天蓝霓虹光束 */
  filter: drop-shadow(0 0 5px rgba(56, 189, 248, 0.8));
}

/* 节点样式 */
.mindmap-node {
  position: absolute;
  padding: 8px 16px;
  background: #ffffff;
  border: 1.5px solid #cbd5e1;
  border-radius: 8px;
  color: #1e293b;
  font-size: 13.5px;
  white-space: nowrap;
  pointer-events: auto;
  z-index: 2;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
  transition: all 0.15s ease;

  &:hover {
    border-color: #0284c7;
    transform: translateY(-1px);
  }

  &.root {
    background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%);
    border: 2px solid #0284c7;
    color: #ffffff;
    font-weight: 600;
    font-size: 15px;
    padding: 12px 24px;
    box-shadow: 0 4px 16px rgba(2, 132, 199, 0.3);
  }

  &.selected {
    border-color: #0284c7;
    box-shadow: 0 0 0 3px rgba(2, 132, 199, 0.25);
  }
}

.dark-mode .mindmap-node {
  background: #1e293b;
  border-color: rgba(255, 255, 255, 0.15);
  color: #f8fafc;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);

  &.root {
    background: linear-gradient(135deg, #312e81 0%, #4c1d95 100%);
    border-color: #818cf8;
    color: #ffffff;
    box-shadow: 0 0 20px rgba(129, 140, 248, 0.3);
  }

  &.selected {
    border-color: #00f0ff;
    box-shadow: 0 0 14px rgba(0, 240, 255, 0.5);
  }
}

.node-text-wrapper {
  display: flex;
  align-items: center;
}

.node-topic {
  display: inline-block;
  min-width: 80px;
}

.node-input {
  background: #ffffff;
  border: 1.5px solid #0284c7;
  outline: none;
  color: #0f172a;
  font-size: 13px;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: inherit;
}

.dark-mode .node-input {
  background: #0f172a;
  border-color: #38bdf8;
  color: #f8fafc;
}

/* 展开收起控制点 */
.collapse-dot {
  position: absolute;
  right: -10px;
  top: 50%;
  transform: translateY(-50%);
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #ffffff;
  border: 1.5px solid #0284c7;
  color: #0284c7;
  font-size: 11px;
  font-weight: bold;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  z-index: 3;

  &:hover {
    background: #0284c7;
    color: #ffffff;
  }
}

.dark-mode .collapse-dot {
  background: #0f172a;
  border-color: #38bdf8;
  color: #38bdf8;

  &:hover {
    background: #38bdf8;
    color: #0f172a;
  }
}

/* 底部快捷键面板 */
.shortcuts-tip {
  position: absolute;
  bottom: 20px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(255, 255, 255, 0.95);
  border: 1px solid rgba(0, 0, 0, 0.1);
  border-radius: 30px;
  padding: 8px 24px;
  display: flex;
  align-items: center;
  gap: 16px;
  font-size: 11.5px;
  color: #475569;
  backdrop-filter: blur(12px);
  z-index: 10;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
}

.dark-mode .shortcuts-tip {
  background: rgba(15, 23, 42, 0.95);
  border-color: rgba(255, 255, 255, 0.12);
  color: #94a3b8;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
}

.tip-item b {
  color: #0284c7;
  background: rgba(2, 132, 199, 0.1);
  padding: 2px 6px;
  border-radius: 4px;
  margin-right: 4px;
}

.dark-mode .tip-item b {
  color: #38bdf8;
  background: rgba(56, 189, 248, 0.15);
}

/* 按钮基础 */
.btn {
  border: none;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  padding: 8px 16px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}

.btn-theme {
  background: rgba(0, 0, 0, 0.05);
  border: 1px solid rgba(0, 0, 0, 0.1);
  color: #334155;

  &:hover {
    background: rgba(0, 0, 0, 0.08);
  }
}

.dark-mode .btn-theme {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.15);
  color: #f1f5f9;

  &:hover {
    background: rgba(255, 255, 255, 0.15);
  }
}

.btn-save {
  background: rgba(0, 0, 0, 0.05);
  border: 1px solid rgba(0, 0, 0, 0.1);
  color: #334155;

  &:hover {
    background: rgba(0, 0, 0, 0.08);
  }
}

.dark-mode .btn-save {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.15);
  color: #f1f5f9;

  &:hover {
    background: rgba(255, 255, 255, 0.15);
  }
}

.btn-sync {
  background: #0284c7;
  color: #fff;
  box-shadow: 0 2px 8px rgba(2, 132, 199, 0.25);

  &:hover {
    background: #0369a1;
  }
}

.dark-mode .btn-sync {
  box-shadow: 0 0 12px rgba(2, 132, 199, 0.4);
}
</style>
