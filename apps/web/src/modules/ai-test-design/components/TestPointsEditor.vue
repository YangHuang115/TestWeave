<template>
  <div class="points-editor">
    <header class="editor-header">
      <div>
        <span class="eyebrow">结构化测试点</span>
        <h2>测试点脑图与覆盖矩阵</h2>
        <p>勾选“进入用例”后，该测试点才会通过人工门禁进入用例生成。</p>
      </div>
      <div class="header-right-actions">
        <div class="view-mode-toggle">
          <button
            type="button"
            class="toggle-btn"
            :class="{ active: viewMode === 'mindmap' }"
            @click="viewMode = 'mindmap'"
          >
            🧠 交互脑图视图
          </button>
          <button
            type="button"
            class="toggle-btn"
            :class="{ active: viewMode === 'table' }"
            @click="viewMode = 'table'"
          >
            📋 列表矩阵视图
          </button>
        </div>
        <button type="button" class="add-btn" @click="addPoint">＋ 新增测试点</button>
      </div>
    </header>

    <!-- 🧠 交互脑图视图模式 -->
    <div v-if="viewMode === 'mindmap'" class="mindmap-view-wrapper">
      <TestPointMindmapCanvas
        :payload-data="{ points: points }"
        @update:payload="changed"
      />
    </div>

    <!-- 📋 传统列表矩阵视图模式 -->
    <template v-else>
      <div class="filter-bar">
        <input v-model="query" placeholder="搜索标题、动作或预期" />
        <select v-model="moduleFilter"><option value="">全部模块</option><option v-for="module in modules" :key="module" :value="module">{{ module }}</option></select>
        <select v-model="riskFilter"><option value="">全部风险</option><option>HIGH</option><option>MEDIUM</option><option>LOW</option></select>
        <select v-model="priorityFilter"><option value="">全部优先级</option><option>HIGH</option><option>MEDIUM</option><option>LOW</option></select>
        <select v-model="methodFilter"><option value="">全部测试方法</option><option v-for="method in methods" :key="method" :value="method">{{ method }}</option></select>
        <span>{{ filteredPoints.length }} / {{ points.length }} 条</span>
      </div>

    <div class="points-layout">
      <aside class="tree-panel">
        <h3>模块测试树</h3>
        <div v-for="group in groupedPoints" :key="group.module" class="tree-group">
          <button type="button" @click="toggleModule(group.module)"><span>{{ collapsedModules.has(group.module) ? '▸' : '▾' }}</span><strong>{{ group.module }}</strong><small>{{ group.items.length }}</small></button>
          <div v-if="!collapsedModules.has(group.module)" class="tree-children">
            <button v-for="point in group.items" :key="point.stableKey" type="button" :class="{ active: selectedStableKey === point.stableKey }" @click="selectPoint(point.stableKey)">
              <span :class="`risk-dot ${point.risk.toLowerCase()}`"></span>{{ point.title }}
            </button>
          </div>
        </div>
      </aside>

      <section class="table-panel">
        <div class="table-scroll">
          <table>
            <thead><tr><th class="check-col">进入用例</th><th>标题 / 描述</th><th>模块</th><th>范围</th><th>风险</th><th>优先级</th><th>测试方法</th><th>核心动作</th><th>核心预期</th><th>追踪</th><th></th></tr></thead>
            <tbody>
              <tr v-for="point in filteredPoints" :key="point.stableKey" :class="{ selected: selectedStableKey === point.stableKey }" @click="selectPoint(point.stableKey)">
                <td class="check-col"><input v-model="point.allowCaseGeneration" type="checkbox" @click.stop @change="changedAndSelect" /></td>
                <td><input v-model="point.title" class="title-input" @input="changed" /><textarea v-model="point.description" rows="2" @input="changed" /></td>
                <td><input v-model="point.module" @input="changed" /></td>
                <td><input v-model="point.scope" @input="changed" /></td>
                <td><select v-model="point.risk" @change="changed"><option>HIGH</option><option>MEDIUM</option><option>LOW</option></select></td>
                <td><select v-model="point.priority" @change="changed"><option>HIGH</option><option>MEDIUM</option><option>LOW</option></select></td>
                <td><input v-model="point.testMethod" @input="changed" /><small>{{ point.testMethodReason }}</small></td>
                <td><textarea v-model="point.coreAction" rows="2" @input="changed" /></td>
                <td><textarea v-model="point.coreExpected" rows="2" @input="changed" /></td>
                <td><div class="ref-chips"><span v-for="ref in point.ruleRefs" :key="ref">{{ ref }}</span><span v-for="ref in point.questionRefs" :key="ref" class="question-ref">{{ ref }}</span></div></td>
                <td><button type="button" class="delete-btn" @click.stop="removePoint(point.stableKey)">×</button></td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="selectedPoint" class="detail-card">
          <div class="detail-head"><div><span class="eyebrow">测试点详情</span><h3>{{ selectedPoint.title }}</h3></div><div><button type="button" @click="$emit('lock-field', selectedPoint.stableKey, '/coreExpected')">🔒 锁定核心预期</button><button type="button" @click="$emit('regenerate', [selectedPoint.stableKey])">仅重生成此测试点</button></div></div>
          <div class="detail-grid">
            <label><span>前置状态（每行一项）</span><textarea :value="selectedPoint.preconditions.join('\n')" rows="4" @input="updateLines(selectedPoint, 'preconditions', $event)" /></label>
            <label><span>测试方法选择原因</span><textarea v-model="selectedPoint.testMethodReason" rows="4" @input="changed" /></label>
            <label><span>规则引用（逗号分隔）</span><input :value="selectedPoint.ruleRefs.join(', ')" @input="updateRefs(selectedPoint, 'ruleRefs', $event)" /></label>
            <label><span>待确认问题引用</span><input :value="selectedPoint.questionRefs.join(', ')" @input="updateRefs(selectedPoint, 'questionRefs', $event)" /></label>
            <label><span>模块关系引用</span><input :value="selectedPoint.moduleRelationRefs.join(', ')" @input="updateRefs(selectedPoint, 'moduleRelationRefs', $event)" /></label>
          </div>
          <div class="variables-head"><h4>主要变量与输入分区</h4><button type="button" @click="selectedPoint.variables.push({ name: '新变量', partitions: [] }); changed()">＋ 变量</button></div>
          <div class="variable-list"><div v-for="(variable, index) in selectedPoint.variables" :key="`${variable.name}-${index}`"><input v-model="variable.name" @input="changed" /><input :value="variable.partitions.join(', ')" placeholder="有效、无效、边界…" @input="updateRefs(variable, 'partitions', $event)" /><button type="button" @click="selectedPoint.variables.splice(index,1); changed()">×</button></div></div>
        </div>
      </section>
    </div>

    <section class="coverage-panel">
      <div class="coverage-head"><div><span class="eyebrow">追踪完整性</span><h2>规则覆盖矩阵</h2></div><div class="coverage-metric"><strong>{{ coveragePercent }}%</strong><span>规则覆盖</span></div></div>
      <div class="coverage-grid"><article v-for="rule in knownRules" :key="rule.id" :class="{ uncovered: !coveredRuleRefs.has(rule.id) }"><div><span>{{ rule.id }}</span><strong>{{ rule.description }}</strong></div><small>{{ ruleCoverageCount(rule.id) }} 个测试点</small></article></div>
      <div v-if="uncoveredRules.length" class="uncovered-box"><strong>未覆盖规则</strong><span v-for="rule in uncoveredRules" :key="rule.id">{{ rule.id }} · {{ rule.description }}</span></div>
      <div class="blocked-box"><strong>被待确认问题阻塞的测试点</strong><span v-for="point in blockedPoints" :key="point.stableKey">{{ point.title }}（{{ point.questionRefs.join('、') }}）</span><span v-if="!blockedPoints.length">暂无</span></div>
    </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import type { AiArtifactContent, RequirementRule, TestPoint } from "../types";
import TestPointMindmapCanvas from "./TestPointMindmapCanvas.vue";

const viewMode = ref<"mindmap" | "table">("mindmap");

const props = defineProps<{ modelValue: AiArtifactContent[]; knownRules: RequirementRule[] }>();
const emit = defineEmits<{
  "update:modelValue": [value: AiArtifactContent[]]; changed: []; selection: [keys: string[]];
  "lock-field": [stableKey: string, pointer: string]; regenerate: [keys: string[]];
}>();
const query = ref(""); const moduleFilter = ref(""); const riskFilter = ref(""); const priorityFilter = ref(""); const methodFilter = ref("");
const selectedStableKey = ref<string | null>(null); const collapsedModules = ref(new Set<string>());
const points = computed(() => props.modelValue as TestPoint[]);
const modules = computed(() => [...new Set(points.value.map((p) => p.module))].filter(Boolean));
const methods = computed(() => [...new Set(points.value.map((p) => p.testMethod))].filter(Boolean));
const filteredPoints = computed(() => points.value.filter((p) => (!query.value || `${p.title} ${p.coreAction} ${p.coreExpected}`.toLowerCase().includes(query.value.toLowerCase())) && (!moduleFilter.value || p.module === moduleFilter.value) && (!riskFilter.value || p.risk === riskFilter.value) && (!priorityFilter.value || p.priority === priorityFilter.value) && (!methodFilter.value || p.testMethod === methodFilter.value)));
const groupedPoints = computed(() => modules.value.map((module) => ({ module, items: points.value.filter((p) => p.module === module) })));
const selectedPoint = computed(() => points.value.find((p) => p.stableKey === selectedStableKey.value) ?? points.value[0]);
const coveredRuleRefs = computed(() => new Set(points.value.flatMap((p) => p.ruleRefs)));
const uncoveredRules = computed(() => props.knownRules.filter((rule) => !coveredRuleRefs.value.has(rule.id)));
const coveragePercent = computed(() => props.knownRules.length ? Math.round(((props.knownRules.length - uncoveredRules.value.length) / props.knownRules.length) * 100) : 100);
const blockedPoints = computed(() => points.value.filter((p) => p.questionRefs.length > 0));
function changed() { emit("update:modelValue", props.modelValue); emit("changed"); }
function changedAndSelect() { changed(); emit("selection", points.value.filter((p) => p.allowCaseGeneration).map((p) => p.stableKey)); }
function selectPoint(key: string) { selectedStableKey.value = key; }
function toggleModule(module: string) { const next = new Set(collapsedModules.value); next.has(module) ? next.delete(module) : next.add(module); collapsedModules.value = next; }
function eventValue(event: Event) { return (event.target as HTMLInputElement | HTMLTextAreaElement).value; }
function updateLines(target: TestPoint, key: "preconditions", event: Event) { target[key] = eventValue(event).split("\n").map((v) => v.trim()).filter(Boolean); changed(); }
function updateRefs(target: object, key: string, event: Event) { (target as Record<string, unknown>)[key] = eventValue(event).split(",").map((v) => v.trim()).filter(Boolean); changed(); }
function addPoint() { const n = points.value.length + 1; points.value.push({ stableKey: `TP-${String(n).padStart(3,"0")}-${crypto.randomUUID().slice(0,4)}`, title: "新测试点", description: "", module: modules.value[0] || "未分组", scope: "功能", preconditions: [], coreAction: "", coreExpected: "", variables: [], testMethod: "场景法", testMethodReason: "", risk: "MEDIUM", priority: "MEDIUM", ruleRefs: [], questionRefs: [], moduleRelationRefs: [], allowCaseGeneration: false }); changed(); }
function removePoint(key: string) { const index = points.value.findIndex((p) => p.stableKey === key); if (index >= 0) points.value.splice(index, 1); if (selectedStableKey.value === key) selectedStableKey.value = null; changedAndSelect(); }
function ruleCoverageCount(ruleId: string) { return points.value.filter((p) => p.ruleRefs.includes(ruleId)).length; }
</script>

<style scoped>
.points-editor{background:#f9fafb;padding:18px;display:grid;gap:14px}.editor-header,.coverage-head,.detail-head,.variables-head{display:flex;justify-content:space-between;align-items:center;gap:12px}.editor-header h2,.coverage-head h2{margin:3px 0;font-size:18px}.editor-header p{margin:0;color:#667085;font-size:12px}.eyebrow{color:#7f56d9;font-size:10px;text-transform:uppercase;letter-spacing:.08em}.add-btn,.detail-head button,.variables-head button{border:1px solid #d6d0ff;background:#f7f5ff;color:#6941c6;border-radius:7px;padding:7px 10px;cursor:pointer;font-size:11px}.filter-bar{display:grid;grid-template-columns:2fr repeat(4,1fr) auto;gap:7px;padding:10px;background:#fff;border:1px solid #e4e7ec;border-radius:10px;align-items:center}.filter-bar input,.filter-bar select,input,select,textarea{box-sizing:border-box;width:100%;border:1px solid #d0d5dd;border-radius:6px;padding:7px 8px;background:#fff;font:inherit;font-size:11px}.filter-bar span{color:#667085;font-size:11px}.points-layout{display:grid;grid-template-columns:190px minmax(0,1fr);gap:11px}.tree-panel,.table-panel,.coverage-panel{background:#fff;border:1px solid #e4e7ec;border-radius:10px;overflow:hidden}.tree-panel{padding:12px}.tree-panel h3{font-size:13px;margin:0 0 10px}.tree-group>button{width:100%;display:grid;grid-template-columns:auto 1fr auto;gap:5px;text-align:left;border:0;background:transparent;padding:7px 3px;cursor:pointer}.tree-group small{color:#98a2b3}.tree-children{display:grid;padding-left:12px;border-left:1px solid #e4e7ec}.tree-children button{display:flex;align-items:center;gap:6px;border:0;background:transparent;text-align:left;padding:6px;color:#475467;font-size:11px;cursor:pointer}.tree-children button.active{background:#f4f3ff;color:#6941c6;border-radius:5px}.risk-dot{width:6px;height:6px;background:#f79009;border-radius:50%;flex:none}.risk-dot.high{background:#f04438}.risk-dot.low{background:#12b76a}.table-scroll{overflow:auto;max-height:460px}table{border-collapse:collapse;min-width:1300px;width:100%}th{position:sticky;top:0;z-index:1;background:#f9fafb;color:#667085;font-size:10px;text-align:left;padding:8px;border-bottom:1px solid #eaecf0}td{padding:7px;border-bottom:1px solid #f2f4f7;vertical-align:top;min-width:95px}tr.selected td{background:#faf9ff}.check-col{min-width:62px;text-align:center}.check-col input{width:auto}.title-input{font-weight:700;margin-bottom:5px}td small{display:block;margin-top:4px;color:#98a2b3}.ref-chips{display:flex;gap:3px;flex-wrap:wrap}.ref-chips span{background:#ecfdf3;color:#027a48;padding:3px 5px;border-radius:4px;font-size:9px}.ref-chips .question-ref{background:#fffaeb;color:#b54708}.delete-btn{border:0;background:transparent;color:#b42318;cursor:pointer}.detail-card{border-top:1px solid #eaecf0;padding:14px}.detail-head h3{margin:3px 0}.detail-head>div:last-child{display:flex;gap:6px}.detail-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-top:11px}.detail-grid label span{display:block;color:#475467;font-size:10px;margin-bottom:4px}.variables-head{margin-top:12px}.variables-head h4{margin:0;font-size:12px}.variable-list{display:grid;gap:6px;margin-top:7px}.variable-list>div{display:grid;grid-template-columns:1fr 2fr auto;gap:6px}.variable-list button{border:0;background:transparent;color:#b42318}.coverage-panel{padding:15px}.coverage-metric{display:flex;align-items:baseline;gap:5px}.coverage-metric strong{font-size:22px;color:#12b76a}.coverage-metric span{font-size:10px;color:#667085}.coverage-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:7px;margin-top:12px}.coverage-grid article{display:flex;justify-content:space-between;gap:8px;padding:9px;border:1px solid #abefc6;background:#f6fef9;border-radius:7px}.coverage-grid article.uncovered{border-color:#fedf89;background:#fffcf5}.coverage-grid article div{display:grid;gap:3px}.coverage-grid article span,.coverage-grid article small{font-size:9px;color:#667085}.coverage-grid article strong{font-size:11px}.uncovered-box,.blocked-box{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px;padding:9px;border-radius:7px;background:#fffaeb;font-size:10px}.uncovered-box span,.blocked-box span{background:#fff;padding:4px 6px;border-radius:4px}.blocked-box{background:#f9f5ff}@media(max-width:1000px){.filter-bar{grid-template-columns:1fr 1fr}.points-layout{grid-template-columns:1fr}.tree-panel{max-height:220px;overflow:auto}.detail-grid,.coverage-grid{grid-template-columns:1fr}}

.header-right-actions { display: flex; align-items: center; gap: 12px; }
.view-mode-toggle { display: flex; background: #eaecf0; padding: 3px; border-radius: 8px; gap: 2px; }
.toggle-btn { border: none; background: transparent; padding: 5px 12px; border-radius: 6px; font-size: 11px; font-weight: 600; color: #475467; cursor: pointer; transition: all 0.2s ease; }
.toggle-btn.active { background: #ffffff; color: #6941c6; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
.mindmap-view-wrapper { border-radius: 10px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.05); border: 1px solid #eaecf0; }
</style>
