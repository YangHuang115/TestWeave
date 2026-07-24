<template>
  <div class="cases-editor">
    <header class="editor-header">
      <div><span class="eyebrow">批量编辑</span><h2>测试用例候选集</h2><p>每条用例只有一个主测试点和一个核心目标；详情抽屉用于维护数据、步骤和追踪。</p></div>
      <div><button type="button" @click="regenerateSelected" :disabled="!selectedKeys.size">局部重生成（{{ selectedKeys.size }}）</button><button type="button" class="primary" @click="addCase">＋ 新增用例</button></div>
    </header>
    <div class="toolbar"><input v-model="query" placeholder="搜索标题、模块、测试点" /><select v-model="priorityFilter"><option value="">全部优先级</option><option>HIGH</option><option>MEDIUM</option><option>LOW</option></select><select v-model="qualityFilter"><option value="">全部质量预检</option><option>PASS</option><option>WARNING</option><option>FAIL</option></select><span>已选 {{ selectedKeys.size }} / {{ cases.length }}</span></div>
    <div class="table-scroll">
      <table>
        <thead><tr><th><input type="checkbox" :checked="allVisibleSelected" @change="toggleAll" /></th><th>用例标题</th><th>模块 / 范围</th><th>优先级</th><th>主测试点</th><th>核心预期</th><th>质量预检</th><th>追踪</th><th></th></tr></thead>
        <tbody><tr v-for="testCase in filteredCases" :key="testCase.stableKey" :class="{ active: activeKey === testCase.stableKey }" @click="openCase(testCase.stableKey)">
          <td><input type="checkbox" :checked="selectedKeys.has(testCase.stableKey)" @click.stop @change="toggleSelected(testCase.stableKey)" /></td>
          <td><input v-model="testCase.title" class="title-input" @click.stop @input="changed" /><small>{{ testCase.stableKey }}</small></td>
          <td><input v-model="testCase.module" @click.stop @input="changed" /><input v-model="testCase.scope" @click.stop @input="changed" /></td>
          <td><select v-model="testCase.priority" @click.stop @change="changed"><option>HIGH</option><option>MEDIUM</option><option>LOW</option></select></td>
          <td><input v-model="testCase.primaryTestPointRef" @click.stop @input="changed" /></td>
          <td><textarea v-model="testCase.coreExpected" rows="2" @click.stop @input="changed" /></td>
          <td><span class="quality-pill" :class="testCase.qualityPrecheck.status.toLowerCase()">{{ qualityLabel(testCase.qualityPrecheck.status) }}</span><small>{{ testCase.qualityPrecheck.findings.join('；') }}</small></td>
          <td><div class="refs"><span v-for="ref in testCase.ruleRefs" :key="ref">{{ ref }}</span></div></td>
          <td><button type="button" class="delete" @click.stop="removeCase(testCase.stableKey)">×</button></td>
        </tr></tbody>
      </table>
    </div>

    <div v-if="activeCase" class="drawer-overlay" @click.self="activeKey = null">
      <aside class="case-drawer">
        <header><div><span class="eyebrow">用例详情</span><h2>{{ activeCase.title }}</h2><p>{{ activeCase.stableKey }}</p><p v-if="focusFieldPath" class="focus-path">评审定位字段：{{ focusFieldPath }}</p></div><button type="button" @click="activeKey = null">×</button></header>
        <div class="drawer-actions"><button type="button" @click="$emit('lock-field', activeCase.stableKey, '/coreExpected')">🔒 锁定核心预期</button><button type="button" @click="$emit('regenerate', [activeCase.stableKey])">反馈并重生成</button></div>
        <section><h3>基本信息与唯一目标</h3><div class="form-grid"><label><span>标题</span><input v-model="activeCase.title" @input="changed" /></label><label><span>主测试点（唯一）</span><input v-model="activeCase.primaryTestPointRef" @input="changed" /></label><label><span>模块</span><input v-model="activeCase.module" @input="changed" /></label><label><span>范围</span><input v-model="activeCase.scope" @input="changed" /></label></div><label><span>核心预期结果（唯一）</span><textarea v-model="activeCase.coreExpected" rows="3" @input="changed" /></label></section>
        <section><h3>前置条件</h3><textarea :value="activeCase.preconditions.join('\n')" rows="4" @input="updateLines(activeCase, 'preconditions', $event)" /></section>
        <section><div class="section-head"><h3>具体测试数据</h3><button type="button" @click="activeCase.testData.push({ name: '新数据', value: '', purpose: '' }); changed()">＋ 数据</button></div><div class="data-list"><div v-for="(data,index) in activeCase.testData" :key="index"><input v-model="data.name" placeholder="字段" @input="changed" /><input v-model="data.value" placeholder="具体值" @input="changed" /><input v-model="data.purpose" placeholder="用途/分区" @input="changed" /><button type="button" @click="activeCase.testData.splice(index,1);changed()">×</button></div></div></section>
        <section><div class="section-head"><h3>操作步骤与对应预期</h3><button type="button" @click="addStep">＋ 步骤</button></div><div class="step-list"><div v-for="(step,index) in activeCase.steps" :key="index"><span>{{ index+1 }}</span><textarea v-model="step.action" rows="2" placeholder="具体操作" @input="changed" /><textarea v-model="step.expected" rows="2" placeholder="对应可观察预期" @input="changed" /><button type="button" @click="removeStep(index)">×</button></div></div></section>
        <section><h3>观察点与清理动作</h3><div class="form-grid"><label><span>观察点（每行一项）</span><textarea :value="activeCase.observationPoints.join('\n')" rows="4" @input="updateLines(activeCase,'observationPoints',$event)" /></label><label><span>清理动作（每行一项）</span><textarea :value="activeCase.cleanupActions.join('\n')" rows="4" @input="updateLines(activeCase,'cleanupActions',$event)" /></label></div></section>
        <section><h3>测试方法与来源追踪</h3><div class="form-grid"><label><span>测试方法</span><input v-model="activeCase.testMethod" @input="changed" /></label><label><span>规则引用</span><input :value="activeCase.ruleRefs.join(', ')" @input="updateRefs(activeCase,'ruleRefs',$event)" /></label><label><span>假设引用</span><input :value="activeCase.assumptionRefs.join(', ')" @input="updateRefs(activeCase,'assumptionRefs',$event)" /></label><label><span>质量预检</span><select v-model="activeCase.qualityPrecheck.status" @change="changed"><option>PASS</option><option>WARNING</option><option>FAIL</option></select></label></div><label><span>预检问题（每行一项）</span><textarea :value="activeCase.qualityPrecheck.findings.join('\n')" rows="3" @input="updateQualityFindings" /></label></section>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { AiArtifactContent, AiDesignedTestCase } from "../types";
const props=defineProps<{modelValue:AiArtifactContent[];focusCase?:string|undefined;focusFieldPath?:string|undefined}>();
const emit=defineEmits<{"update:modelValue":[value:AiArtifactContent[]];changed:[];selection:[keys:string[]];"lock-field":[stableKey:string,pointer:string];regenerate:[keys:string[]]}>();
const query=ref("");const priorityFilter=ref("");const qualityFilter=ref("");const activeKey=ref<string|null>(null);const selectedKeys=ref(new Set<string>());
const cases=computed(()=>props.modelValue as AiDesignedTestCase[]);
const filteredCases=computed(()=>cases.value.filter((c)=>(!query.value||`${c.title} ${c.module} ${c.primaryTestPointRef}`.toLowerCase().includes(query.value.toLowerCase()))&&(!priorityFilter.value||c.priority===priorityFilter.value)&&(!qualityFilter.value||c.qualityPrecheck.status===qualityFilter.value)));
const activeCase=computed(()=>cases.value.find((c)=>c.stableKey===activeKey.value));
const allVisibleSelected=computed(()=>filteredCases.value.length>0&&filteredCases.value.every((c)=>selectedKeys.value.has(c.stableKey)));
watch(()=>[props.focusCase,cases.value.length],()=>{if(props.focusCase&&cases.value.some((item)=>item.stableKey===props.focusCase))activeKey.value=props.focusCase},{immediate:true});
function changed(){emit("update:modelValue",props.modelValue);emit("changed")}
function emitSelection(){emit("selection",[...selectedKeys.value])}
function openCase(key:string){activeKey.value=key}
function toggleSelected(key:string){const next=new Set(selectedKeys.value);next.has(key)?next.delete(key):next.add(key);selectedKeys.value=next;emitSelection()}
function toggleAll(){const next=new Set(selectedKeys.value);allVisibleSelected.value?filteredCases.value.forEach((c)=>next.delete(c.stableKey)):filteredCases.value.forEach((c)=>next.add(c.stableKey));selectedKeys.value=next;emitSelection()}
function eventValue(event:Event){return(event.target as HTMLInputElement|HTMLTextAreaElement).value}
function updateLines(target:AiDesignedTestCase,key:"preconditions"|"observationPoints"|"cleanupActions",event:Event){target[key]=eventValue(event).split("\n").map((v)=>v.trim()).filter(Boolean);changed()}
function updateRefs(target:AiDesignedTestCase,key:"ruleRefs"|"assumptionRefs",event:Event){target[key]=eventValue(event).split(",").map((v)=>v.trim()).filter(Boolean);changed()}
function updateQualityFindings(event:Event){if(!activeCase.value)return;activeCase.value.qualityPrecheck.findings=eventValue(event).split("\n").map((v)=>v.trim()).filter(Boolean);changed()}
function addCase(){const n=cases.value.length+1;const item:AiDesignedTestCase={stableKey:`TC-${String(n).padStart(3,"0")}-${crypto.randomUUID().slice(0,4)}`,title:"新测试用例",module:"未分组",scope:"功能",priority:"MEDIUM",primaryTestPointRef:"",ruleRefs:[],preconditions:[],testData:[],steps:[{stepNo:1,action:"",expected:""}],coreExpected:"",observationPoints:[],cleanupActions:[],testMethod:"场景法",assumptionRefs:[],qualityPrecheck:{status:"WARNING",findings:["待补充完整步骤"]}};cases.value.push(item);activeKey.value=item.stableKey;changed()}
function removeCase(key:string){const index=cases.value.findIndex((c)=>c.stableKey===key);if(index>=0)cases.value.splice(index,1);selectedKeys.value.delete(key);if(activeKey.value===key)activeKey.value=null;changed();emitSelection()}
function addStep(){if(!activeCase.value)return;activeCase.value.steps.push({stepNo:activeCase.value.steps.length+1,action:"",expected:""});changed()}
function removeStep(index:number){if(!activeCase.value||activeCase.value.steps.length<=1)return;activeCase.value.steps.splice(index,1);activeCase.value.steps.forEach((step,i)=>step.stepNo=i+1);changed()}
function regenerateSelected(){emit("regenerate",[...selectedKeys.value])}
function qualityLabel(status:string){return{PASS:"通过",WARNING:"警告",FAIL:"失败"}[status]??status}
</script>

<style scoped>
.cases-editor{padding:18px;background:#f9fafb;min-height:600px}.editor-header,.toolbar,.section-head{display:flex;align-items:center;justify-content:space-between;gap:10px}.editor-header h2{margin:3px 0;font-size:18px}.editor-header p{margin:0;color:#667085;font-size:12px}.eyebrow{color:#7f56d9;font-size:10px;text-transform:uppercase;letter-spacing:.08em}.editor-header>div:last-child{display:flex;gap:7px}.editor-header button,.drawer-actions button,.section-head button{border:1px solid #d0d5dd;background:#fff;color:#475467;border-radius:7px;padding:7px 10px;cursor:pointer}.editor-header button.primary{background:#6754e9;color:#fff;border-color:#6754e9}.toolbar{display:grid;grid-template-columns:2fr 1fr 1fr auto;margin:14px 0 9px;padding:9px;background:#fff;border:1px solid #e4e7ec;border-radius:9px}.toolbar span{font-size:11px;color:#667085}.table-scroll{overflow:auto;border:1px solid #e4e7ec;border-radius:10px;background:#fff;max-height:590px}table{border-collapse:collapse;width:100%;min-width:1120px}th{position:sticky;top:0;z-index:2;background:#f9fafb;color:#667085;font-size:10px;text-align:left;padding:8px;border-bottom:1px solid #eaecf0}td{padding:7px;border-bottom:1px solid #f2f4f7;vertical-align:top}tr.active td{background:#faf9ff}input,select,textarea{box-sizing:border-box;width:100%;border:1px solid #d0d5dd;border-radius:6px;padding:7px 8px;background:#fff;font:inherit;font-size:11px}td input+input{margin-top:4px}td>input[type=checkbox],th input{width:auto}.title-input{font-weight:700}.quality-pill{display:inline-block;border-radius:999px;padding:3px 6px;background:#ecfdf3;color:#027a48;font-size:9px}.quality-pill.warning{background:#fffaeb;color:#b54708}.quality-pill.fail{background:#fef3f2;color:#b42318}td small{display:block;color:#98a2b3;font-size:9px;margin-top:4px}.refs{display:flex;gap:3px;flex-wrap:wrap}.refs span{background:#f0f9ff;color:#026aa2;padding:3px 5px;border-radius:4px;font-size:9px}.delete{border:0;background:transparent;color:#b42318;cursor:pointer}.drawer-overlay{position:fixed;inset:0;background:#10182855;z-index:1000;display:flex;justify-content:flex-end}.case-drawer{width:min(680px,92vw);height:100%;overflow:auto;background:#f9fafb;box-shadow:-14px 0 35px #10182826}.case-drawer>header{position:sticky;top:0;z-index:2;display:flex;justify-content:space-between;padding:18px;background:#fff;border-bottom:1px solid #e4e7ec}.case-drawer header h2{margin:3px 0}.case-drawer header p{margin:0;color:#98a2b3;font-size:11px}.case-drawer header>button{border:0;background:transparent;font-size:23px}.drawer-actions{display:flex;gap:7px;padding:12px 18px}.case-drawer section{margin:0 18px 12px;padding:14px;background:#fff;border:1px solid #e4e7ec;border-radius:9px}.case-drawer section h3{margin:0 0 10px;font-size:13px}.case-drawer label>span{display:block;margin:8px 0 4px;color:#475467;font-size:10px}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.section-head h3{margin:0}.data-list,.step-list{display:grid;gap:6px}.data-list>div{display:grid;grid-template-columns:1fr 1.2fr 1.5fr auto;gap:5px}.step-list>div{display:grid;grid-template-columns:24px 1fr 1fr auto;gap:6px;align-items:start}.step-list>div>span{width:22px;height:22px;display:grid;place-items:center;background:#f0edff;color:#6941c6;border-radius:50%;font-size:10px}.data-list button,.step-list button{border:0;background:transparent;color:#b42318}@media(max-width:700px){.toolbar,.form-grid{grid-template-columns:1fr}.data-list>div,.step-list>div{grid-template-columns:1fr}.step-list>div>span{display:none}}
.case-drawer header p.focus-path{margin-top:4px;color:#b54708}
</style>
