<template>
  <div class="test-point-mindmap-canvas" :class="{ 'dark-mode': isDarkMode, 'is-fullscreen': isFullscreen }">
    <!-- 顶栏操作与缩放工具条 -->
    <div class="mindmap-toolbar">
      <div class="toolbar-left">
        <span class="tree-summary">
          🧠 测试点脑图视角 (共 <strong>{{ totalPointsCount }}</strong> 项测试点)
        </span>
        <div class="action-btn-group">
          <button
            class="btn-action btn-add-sub"
            :disabled="!selectedNodeId"
            @click="addSubNode"
            title="在当前选中节点下添加子节点"
          >
            ＋ 添加子节点
          </button>
          <button
            class="btn-action btn-add-sibling"
            :disabled="!selectedNodeId || selectedNodeId === 'root'"
            @click="addSiblingNode"
            title="在当前选中节点同级添加新节点"
          >
            ↳ 添加同级节点
          </button>
          <button
            class="btn-action btn-delete"
            :disabled="!selectedNodeId || selectedNodeId === 'root'"
            @click="deleteSelectedNode"
            title="删除当前选中的节点"
          >
            🗑️ 删除节点
          </button>
        </div>
      </div>
      <div class="toolbar-controls">
        <button class="btn-tool" @click="zoomIn" title="放大">＋</button>
        <span class="zoom-level">{{ Math.round(scale * 100) }}%</span>
        <button class="btn-tool" @click="zoomOut" title="缩小">－</button>
        <button class="btn-tool" @click="resetView" title="重置视角">⟲ 重置</button>
        <span class="tool-divider">|</span>
        <button class="btn-tool btn-fullscreen" @click="toggleFullscreen" :title="isFullscreen ? '退出全屏 (Esc)' : '全屏沉浸浏览脑图'">
          {{ isFullscreen ? "🗗 退出全屏" : "⛶ 全屏模式" }}
        </button>
        <button class="btn-tool btn-theme" @click="isDarkMode = !isDarkMode">
          {{ isDarkMode ? "☀️ 浅色" : "🌙 暗黑" }}
        </button>
      </div>
    </div>

    <!-- 脑图主画布容器 -->
    <div
      class="canvas-viewport-container"
      ref="containerRef"
      @mousedown="startPan"
      @mousemove="onPan"
      @mouseup="endPan"
      @mouseleave="endPan"
      @wheel.prevent="onZoom"
    >
      <div
        class="mindmap-viewport"
        :style="{ transform: `translate(${panX}px, ${panY}px) scale(${scale})` }"
      >
        <!-- SVG 连线图层 -->
        <svg class="svg-connections-layer">
          <path
            v-for="line in connectionLines"
            :key="line.id"
            :d="line.d"
            class="connection-line"
          />
        </svg>

        <!-- 树节点渲染图层 -->
        <div
          v-for="node in renderedNodes"
          :key="node.id"
          class="mindmap-node"
          :class="{
            'node-root': node.level === 0,
            'node-module': node.level === 1,
            'node-point': node.level === 3,
            selected: selectedNodeId === node.id,
          }"
          :style="{ left: `${node.x}px`, top: `${node.y}px` }"
          @click.stop="selectNode(node)"
          @dblclick.stop="startEdit(node)"
        >
          <div class="node-content">
            <span class="node-icon" v-if="node.icon">{{ node.icon }}</span>
            <input
              v-if="editingNodeId === node.id"
              ref="editInputRef"
              v-model="editTempText"
              class="node-inline-input"
              @blur="finishEdit"
              @keydown.enter.prevent="finishEdit"
              @keydown.esc.prevent="cancelEdit"
              @click.stop
            />
            <span v-else class="node-title">{{ node.title }}</span>
            <span v-if="node.badge" class="node-badge" :class="node.badgeType">
              {{ node.badge }}
            </span>
          </div>

          <!-- 折叠展开控制点 -->
          <div
            v-if="node.hasChildren"
            class="collapse-toggle"
            @click.stop="toggleCollapse(node.id)"
          >
            {{ node.collapsed ? "+" : "−" }}
          </div>
        </div>
      </div>
    </div>

    <!-- 右侧选中的测试点详情抽屉面板 -->
    <div v-if="activePoint" class="point-detail-drawer">
      <div class="drawer-header">
        <h4>📌 测试点明细</h4>
        <button class="btn-close" @click="selectedNodeId = null">✕</button>
      </div>
      <div class="drawer-body">
        <div class="field-group">
          <label>测试点 ID / Key</label>
          <div class="field-value key-text">{{ activePoint.stableKey || activePoint.id }}</div>
        </div>

        <div class="field-group">
          <label>测试点标题</label>
          <textarea
            v-model="activePoint.title"
            class="textarea-box title-textarea"
            rows="3"
            placeholder="请输入测试点标题"
            @input="notifyChange"
          ></textarea>
        </div>

        <div class="field-group">
          <label>所属模块</label>
          <div class="field-value">{{ activePoint.module || "通用模块" }}</div>
        </div>

        <div class="field-group">
          <label>优先级</label>
          <select v-model="activePoint.priority" class="select-box" @change="notifyChange">
            <option value="HIGH">HIGH (高)</option>
            <option value="MEDIUM">MEDIUM (中)</option>
            <option value="LOW">LOW (低)</option>
          </select>
        </div>

        <div class="field-group">
          <label>核心动作 (Core Action)</label>
          <textarea v-model="activePoint.coreAction" class="textarea-box" rows="2" @input="notifyChange"></textarea>
        </div>

        <div class="field-group">
          <label>核心预期 (Core Expected)</label>
          <textarea v-model="activePoint.coreExpected" class="textarea-box" rows="2" @input="notifyChange"></textarea>
        </div>

        <div class="field-group">
          <label>前提条件 (Preconditions)</label>
          <div class="preconditions-list">
            <div v-for="(cond, i) in activePoint.preconditions || []" :key="i" class="cond-tag">
              • {{ cond }}
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from "vue";

export interface TestPointItem {
  id: string;
  stableKey?: string;
  module?: string;
  title: string;
  description?: string;
  priority?: "HIGH" | "MEDIUM" | "LOW";
  scope?: string;
  preconditions?: string[];
  coreAction?: string;
  coreExpected?: string;
  ruleRefs?: string[];
  [key: string]: any;
}

const props = defineProps<{
  payloadData?: {
    points?: TestPointItem[];
    [key: string]: any;
  } | null;
  readOnly?: boolean;
}>();

const emit = defineEmits<{
  (e: "update:payload", payload: any): void;
}>();

const isDarkMode = ref(false);
const isFullscreen = ref(false);
const containerRef = ref<HTMLDivElement | null>(null);

const editingNodeId = ref<string | null>(null);
const editTempText = ref("");
const editInputRef = ref<HTMLInputElement[] | null>(null);

function toggleFullscreen() {
  isFullscreen.value = !isFullscreen.value;
}

function startEdit(node: RenderedNode) {
  editingNodeId.value = node.id;
  editTempText.value = node.title;
  nextTick(() => {
    if (editInputRef.value && editInputRef.value.length > 0) {
      editInputRef.value[0].focus();
      editInputRef.value[0].select();
    }
  });
}

function finishEdit() {
  if (!editingNodeId.value) return;
  const val = editTempText.value.trim();
  if (val) {
    const point = pointsList.value.find((p) => (p.stableKey || p.id) === editingNodeId.value);
    if (point) {
      point.title = val;
      notifyChange();
    }
  }
  editingNodeId.value = null;
}

function cancelEdit() {
  editingNodeId.value = null;
}

// 快捷键 Tab：新建子节点 (新增对应模块的测试点)
function addSubNode() {
  if (editingNodeId.value) return;
  if (!selectedNodeId.value) return;

  const node = renderedNodes.value.find((n) => n.id === selectedNodeId.value);
  if (!node) return;

  let targetModule = "通用模块";
  if (node.level === 0) {
    targetModule = "通用模块";
  } else if (node.level === 1) {
    targetModule = node.title.replace(/\s*\(\d+\)$/, "");
  } else if (node.rawPoint) {
    targetModule = node.rawPoint.module || "通用模块";
  }

  const newKey = `TP-${String(pointsList.value.length + 1).padStart(3, "0")}-${crypto.randomUUID().slice(0, 4)}`;
  const newPoint: TestPointItem = {
    id: newKey,
    stableKey: newKey,
    title: "新分支测试点",
    module: targetModule,
    priority: "MEDIUM",
    scope: "功能",
    preconditions: [],
    coreAction: "",
    coreExpected: "",
    allowCaseGeneration: true,
  };

  pointsList.value.push(newPoint);
  selectedNodeId.value = newKey;
  notifyChange();

  nextTick(() => {
    startEdit({ id: newKey, title: "新分支测试点", level: 3 } as any);
  });
}

// 按钮 / 快捷键：新增同级节点
function addSiblingNode() {
  if (editingNodeId.value) return;
  if (!selectedNodeId.value || selectedNodeId.value === "root") return;

  const selNode = renderedNodes.value.find((n) => n.id === selectedNodeId.value);
  let targetModule = "新模块";
  if (selNode && selNode.level === 1) {
    targetModule = `新模块 ${pointsList.value.length + 1}`;
  } else {
    const point = pointsList.value.find((p) => (p.stableKey || p.id) === selectedNodeId.value);
    targetModule = point ? point.module || "通用模块" : "通用模块";
  }

  const newKey = `TP-${String(pointsList.value.length + 1).padStart(3, "0")}-${crypto.randomUUID().slice(0, 4)}`;
  const newPoint: TestPointItem = {
    id: newKey,
    stableKey: newKey,
    title: "新同级测试点",
    module: targetModule,
    priority: "MEDIUM",
    scope: "功能",
    preconditions: [],
    coreAction: "",
    coreExpected: "",
    allowCaseGeneration: true,
  };

  pointsList.value.push(newPoint);
  selectedNodeId.value = newKey;
  notifyChange();

  nextTick(() => {
    startEdit({ id: newKey, title: "新同级测试点", level: 3 } as any);
  });
}

// 按钮 / 快捷键：删除选中的节点
function deleteSelectedNode() {
  if (editingNodeId.value) return;
  if (!selectedNodeId.value || selectedNodeId.value === "root") return;

  const selNode = renderedNodes.value.find((n) => n.id === selectedNodeId.value);
  if (selNode && selNode.level === 1) {
    const modName = selNode.title.replace(/\s*\(\d+\)$/, "");
    if (!confirm(`确定要删除模块 [${modName}] 及其下方的所有测试点吗？`)) return;
    const remaining = pointsList.value.filter((p) => (p.module || "通用模块") !== modName);
    if (props.payloadData) {
      props.payloadData.points = remaining;
    }
    selectedNodeId.value = null;
    notifyChange();
    return;
  }

  const idx = pointsList.value.findIndex((p) => (p.stableKey || p.id) === selectedNodeId.value);
  if (idx >= 0) {
    pointsList.value.splice(idx, 1);
    selectedNodeId.value = null;
    notifyChange();
  }
}

function handleKeyDown(e: KeyboardEvent) {
  const tag = (e.target as HTMLElement)?.tagName?.toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select") {
    if (e.key === "Escape" && isFullscreen.value) {
      isFullscreen.value = false;
    }
    return;
  }

  if (e.key === "Tab") {
    e.preventDefault();
    addSubNode();
  } else if (e.key === "Enter") {
    e.preventDefault();
    addSiblingNode();
  } else if (e.key === "F2") {
    e.preventDefault();
    if (selectedNodeId.value) {
      const node = renderedNodes.value.find((n) => n.id === selectedNodeId.value);
      if (node) startEdit(node);
    }
  } else if (e.key === "Delete" || e.key === "Backspace") {
    e.preventDefault();
    deleteSelectedNode();
  } else if (e.key === "Escape") {
    if (editingNodeId.value) {
      cancelEdit();
    } else if (isFullscreen.value) {
      isFullscreen.value = false;
    }
  }
}

onMounted(() => {
  window.addEventListener("keydown", handleKeyDown);
});

onUnmounted(() => {
  window.removeEventListener("keydown", handleKeyDown);
});

// 画布平移与缩放
const panX = ref(150);
const panY = ref(200);
const scale = ref(0.95);
let isPanning = false;
let startX = 0;
let startY = 0;

const collapsedNodes = ref<Record<string, boolean>>({});
const selectedNodeId = ref<string | null>(null);

// 提取测试点列表
const pointsList = computed<TestPointItem[]>(() => {
  if (!props.payloadData || !props.payloadData.points) return [];
  return props.payloadData.points;
});

const totalPointsCount = computed(() => pointsList.value.length);

const activePoint = computed<TestPointItem | null>(() => {
  if (!selectedNodeId.value) return null;
  return pointsList.value.find((p) => (p.stableKey || p.id) === selectedNodeId.value) || null;
});

// 构建树状结构
interface InternalNode {
  id: string;
  title: string;
  icon?: string;
  level: number;
  badge?: string;
  badgeType?: string;
  rawPoint?: TestPointItem;
  children?: InternalNode[];
}

const treeData = computed<InternalNode>(() => {
  const points = pointsList.value;
  if (!points || points.length === 0) {
    return {
      id: "root",
      title: "需求分析 & AI 测试点总览",
      icon: "📦",
      level: 0,
      children: [],
    };
  }

  // 按 module 分组
  const groups: Record<string, TestPointItem[]> = {};
  for (const p of points) {
    const mod = p.module || "通用模块";
    if (!groups[mod]) groups[mod] = [];
    groups[mod].push(p);
  }

  const moduleNodes: InternalNode[] = [];
  for (const [modName, modPoints] of Object.entries(groups)) {
    const pNodes: InternalNode[] = modPoints.map((p) => {
      const prio = p.priority || "MEDIUM";
      return {
        id: p.stableKey || p.id,
        title: p.title,
        icon: "📌",
        level: 3,
        badge: prio === "HIGH" ? "高" : prio === "MEDIUM" ? "中" : "低",
        badgeType: prio === "HIGH" ? "badge-danger" : prio === "MEDIUM" ? "badge-warning" : "badge-info",
        rawPoint: p,
      };
    });

    moduleNodes.push({
      id: `mod-${modName}`,
      title: `${modName} (${modPoints.length})`,
      icon: "🎯",
      level: 1,
      children: pNodes,
    });
  }

  return {
    id: "root",
    title: "AI 架构设计需求根节点",
    icon: "📦",
    level: 0,
    children: moduleNodes,
  };
});

// 布局计算算法
interface RenderedNode {
  id: string;
  title: string;
  icon?: string;
  level: number;
  x: number;
  y: number;
  badge?: string;
  badgeType?: string;
  hasChildren: boolean;
  collapsed: boolean;
  rawPoint?: TestPointItem;
}

interface ConnectionLine {
  id: string;
  d: string;
}

function calculateSubtreeHeight(node: InternalNode): number {
  const isCollapsed = !!collapsedNodes.value[node.id];
  if (isCollapsed || !node.children || node.children.length === 0) {
    // 单节点固定基础高度 54px (卡片高 40px + 14px 垂直缝隙)
    return 54;
  }
  let total = 0;
  for (const child of node.children) {
    total += calculateSubtreeHeight(child);
  }
  return total;
}

function getNodeWidth(level: number): number {
  if (level === 0) return 240;
  if (level === 1) return 220;
  return 260;
}

function computeLayout(
  node: InternalNode,
  x: number,
  y: number,
  nodesList: RenderedNode[],
  linesList: ConnectionLine[]
) {
  const hasChildren = !!node.children && node.children.length > 0;
  const isCollapsed = !!collapsedNodes.value[node.id];

  nodesList.push({
    id: node.id,
    title: node.title,
    icon: node.icon,
    level: node.level,
    x,
    y,
    badge: node.badge,
    badgeType: node.badgeType,
    hasChildren,
    collapsed: isCollapsed,
    rawPoint: node.rawPoint,
  });

  if (isCollapsed || !node.children || node.children.length === 0) return;

  const totalHeight = calculateSubtreeHeight(node);
  let currentY = y - totalHeight / 2;

  const nodeW = getNodeWidth(node.level);
  // 水平步幅 = 当前节点估计宽度 + 90px 贝塞尔线条间隙
  const childX = x + nodeW + 90;

  for (const child of node.children) {
    const childHeight = calculateSubtreeHeight(child);
    const childY = currentY + childHeight / 2;

    // 起点：父节点右中点；终点：子节点左中点
    const startX = x + nodeW;
    const startY = y + 20;
    const endX = childX;
    const endY = childY + 20;

    const cp1x = startX + 45;
    const cp1y = startY;
    const cp2x = endX - 45;
    const cp2y = endY;

    linesList.push({
      id: `${node.id}->${child.id}`,
      d: `M ${startX} ${startY} C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${endX} ${endY}`,
    });

    computeLayout(child, childX, childY, nodesList, linesList);
    currentY += childHeight;
  }
}

const renderedNodes = ref<RenderedNode[]>([]);
const connectionLines = ref<ConnectionLine[]>([]);

function updateLayout() {
  const nList: RenderedNode[] = [];
  const lList: ConnectionLine[] = [];
  computeLayout(treeData.value, 0, 0, nList, lList);
  renderedNodes.value = nList;
  connectionLines.value = lList;
}

watch([treeData, collapsedNodes], updateLayout, { deep: true, immediate: true });

function selectNode(node: RenderedNode) {
  selectedNodeId.value = node.id;
}

function toggleCollapse(nodeId: string) {
  collapsedNodes.value[nodeId] = !collapsedNodes.value[nodeId];
}

// 平移与缩放
function startPan(e: MouseEvent) {
  if (e.button !== 0) return;
  isPanning = true;
  startX = e.clientX - panX.value;
  startY = e.clientY - panY.value;
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
  const delta = e.deltaY > 0 ? -0.05 : 0.05;
  const nextScale = scale.value + delta;
  if (nextScale >= 0.4 && nextScale <= 2.5) {
    scale.value = Number(nextScale.toFixed(2));
  }
}

function zoomIn() {
  if (scale.value < 2.5) scale.value = Number((scale.value + 0.1).toFixed(2));
}

function zoomOut() {
  if (scale.value > 0.4) scale.value = Number((scale.value - 0.1).toFixed(2));
}

function resetView() {
  panX.value = 150;
  panY.value = 200;
  scale.value = 0.95;
}

function notifyChange() {
  if (props.payloadData) {
    emit("update:payload", props.payloadData);
  }
}
</script>

<style scoped>
.test-point-mindmap-canvas {
  position: relative;
  width: 100%;
  height: 580px;
  background-color: #f8fafc;
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  user-select: none;
  transition: background-color 0.3s ease;
}

.test-point-mindmap-canvas.is-fullscreen {
  position: fixed !important;
  top: 0 !important;
  left: 0 !important;
  right: 0 !important;
  bottom: 0 !important;
  width: 100vw !important;
  height: 100vh !important;
  z-index: 99999 !important;
  border-radius: 0 !important;
  box-shadow: none !important;
}

.test-point-mindmap-canvas.dark-mode {
  background-color: #0f172a;
  color: #f8fafc;
}

.btn-fullscreen {
  background: #f1f5f9;
  font-weight: 600;
  color: #4f46e5;
  border-color: #c7d2fe;
}

.btn-fullscreen:hover {
  background: #e0e7ff;
  border-color: #6366f1;
}

.dark-mode .btn-fullscreen {
  background: #312e81;
  color: #a5b4fc;
  border-color: #4338ca;
}

.mindmap-toolbar {
  height: 44px;
  padding: 0 16px;
  background: #ffffff;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  z-index: 10;
}

.dark-mode .mindmap-toolbar {
  background: #1e293b;
  border-bottom-color: #334155;
}

.tree-summary {
  font-size: 13px;
  color: #475569;
}

.dark-mode .tree-summary {
  color: #94a3b8;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.action-btn-group {
  display: flex;
  align-items: center;
  gap: 6px;
}

.btn-action {
  height: 28px;
  padding: 0 12px;
  border: 1px solid #cbd5e1;
  background: #ffffff;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  color: #334155;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  transition: all 0.2s ease;
}

.btn-action:hover:not(:disabled) {
  border-color: #6366f1;
  color: #6366f1;
  background: #f5f3ff;
  transform: translateY(-1px);
}

.btn-action.btn-add-sub:hover:not(:disabled) {
  background: #6366f1;
  color: #ffffff;
  border-color: #6366f1;
}

.btn-action.btn-delete:hover:not(:disabled) {
  background: #fee2e2;
  color: #dc2626;
  border-color: #fca5a5;
}

.btn-action:disabled {
  opacity: 0.45;
  cursor: not-allowed;
  background: #f1f5f9;
}

.dark-mode .btn-action {
  background: #334155;
  border-color: #475569;
  color: #e2e8f0;
}

.dark-mode .btn-action:disabled {
  background: #1e293b;
  opacity: 0.35;
}

.toolbar-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn-tool {
  height: 28px;
  padding: 0 10px;
  border: 1px solid #cbd5e1;
  background: #fff;
  border-radius: 4px;
  font-size: 12px;
  color: #334155;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-tool:hover {
  border-color: #6366f1;
  color: #6366f1;
}

.dark-mode .btn-tool {
  background: #334155;
  border-color: #475569;
  color: #e2e8f0;
}

.dark-mode .btn-tool:hover {
  border-color: #818cf8;
  color: #818cf8;
}

.zoom-level {
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  min-width: 40px;
  text-align: center;
}

.tool-divider {
  color: #cbd5e1;
  margin: 0 4px;
}

.canvas-viewport-container {
  flex: 1;
  position: relative;
  cursor: grab;
  overflow: hidden;
}

.canvas-viewport-container:active {
  cursor: grabbing;
}

.mindmap-viewport {
  position: absolute;
  top: 0;
  left: 0;
  transform-origin: 0 0;
  width: 0;
  height: 0;
}

.svg-connections-layer {
  position: absolute;
  top: 0;
  left: 0;
  width: 20000px;
  height: 20000px;
  pointer-events: none;
  overflow: visible;
  z-index: 1;
}

.connection-line {
  fill: none;
  stroke: #6366f1;
  stroke-width: 2.5px;
  stroke-linecap: round;
  transition: stroke 0.3s ease;
}

.dark-mode .connection-line {
  stroke: #38bdf8;
}

.mindmap-node {
  position: absolute;
  z-index: 2;
  height: 40px;
  box-sizing: border-box;
  padding: 0 14px;
  border-radius: 8px;
  background: #ffffff;
  border: 1.5px solid #cbd5e1;
  box-shadow: 0 3px 10px rgba(0, 0, 0, 0.06);
  font-size: 13px;
  font-weight: 500;
  color: #1e293b;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
  cursor: pointer;
  pointer-events: auto;
  transition: all 0.15s ease;
}

.node-content {
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.node-title {
  display: inline-block;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mindmap-node:hover {
  border-color: #6366f1;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.15);
}

.mindmap-node.selected {
  border-color: #4f46e5 !important;
  background-color: #eff6ff !important;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.35), 0 4px 12px rgba(99, 102, 241, 0.2) !important;
}

.mindmap-node.node-root {
  background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
  color: #ffffff;
  border: none;
  font-weight: 600;
}

.mindmap-node.node-root.selected {
  background: linear-gradient(135deg, #4f46e5 0%, #4338ca 100%) !important;
  box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.5), 0 6px 16px rgba(79, 70, 229, 0.4) !important;
}

.mindmap-node.node-root .node-title {
  max-width: 240px;
}

.mindmap-node.node-module {
  background: #f1f5f9;
  border-color: #94a3b8;
  font-weight: 600;
}

.mindmap-node.node-module .node-title {
  max-width: 200px;
}

.dark-mode .mindmap-node {
  background: #1e293b;
  border-color: #475569;
  color: #f1f5f9;
}

.dark-mode .mindmap-node.selected {
  background-color: #1e1b4b;
  border-color: #818cf8;
}

.node-icon {
  font-size: 14px;
}

.node-badge {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
}

.badge-danger {
  background: #fee2e2;
  color: #dc2626;
}

.badge-warning {
  background: #fef3c7;
  color: #d97706;
}

.badge-info {
  background: #e0f2fe;
  color: #0284c7;
}

.collapse-toggle {
  width: 18px;
  height: 18px;
  line-height: 16px;
  text-align: center;
  background: #cbd5e1;
  color: #334155;
  border-radius: 50%;
  font-size: 12px;
  font-weight: bold;
  margin-left: 4px;
  cursor: pointer;
}

.collapse-toggle:hover {
  background: #6366f1;
  color: #ffffff;
}

.point-detail-drawer {
  position: absolute;
  top: 44px;
  right: 0;
  bottom: 0;
  width: 320px;
  background: #ffffff;
  border-left: 1px solid #e2e8f0;
  box-shadow: -4px 0 16px rgba(0, 0, 0, 0.08);
  display: flex;
  flex-direction: column;
  z-index: 20;
}

.dark-mode .point-detail-drawer {
  background: #1e293b;
  border-left-color: #334155;
}

.drawer-header {
  padding: 12px 16px;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.dark-mode .drawer-header {
  border-bottom-color: #334155;
}

.drawer-header h4 {
  margin: 0;
  font-size: 14px;
  color: #0f172a;
}

.dark-mode .drawer-header h4 {
  color: #f8fafc;
}

.btn-close {
  border: none;
  background: none;
  font-size: 16px;
  color: #64748b;
  cursor: pointer;
}

.drawer-body {
  flex: 1;
  padding: 16px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.field-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field-group label {
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
}

.dark-mode .field-group label {
  color: #94a3b8;
}

.field-value {
  font-size: 13px;
  color: #334155;
}

.dark-mode .field-value {
  color: #e2e8f0;
}

.key-text {
  font-family: monospace;
  background: #f1f5f9;
  padding: 4px 8px;
  border-radius: 4px;
}

.dark-mode .key-text {
  background: #334155;
}

.input-text,
.select-box,
.textarea-box {
  width: 100%;
  padding: 6px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  font-size: 13px;
  color: #1e293b;
  background: #fff;
  box-sizing: border-box;
}

.dark-mode .input-text,
.dark-mode .select-box,
.dark-mode .textarea-box {
  background: #0f172a;
  border-color: #475569;
  color: #f8fafc;
}

.cond-tag {
  font-size: 12px;
  color: #475569;
  background: #f8fafc;
  padding: 4px 8px;
  border-radius: 4px;
  margin-bottom: 4px;
}

.dark-mode .cond-tag {
  background: #0f172a;
  color: #cbd5e1;
}

.title-textarea {
  font-weight: 600;
  line-height: 1.4;
  resize: vertical;
  word-break: break-all;
  white-space: pre-wrap;
}

.node-inline-input {
  border: 1.5px solid #6366f1;
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 13px;
  font-weight: 500;
  color: #1e293b;
  outline: none;
  background: #ffffff;
  min-width: 120px;
}
</style>
