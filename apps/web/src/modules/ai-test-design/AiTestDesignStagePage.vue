<template>
  <AiTestDesignWorkbenchLayout
    :stage-key="stageKey"
    :state="state"
    :records="records"
    :active-record-id="activeRecordId"
    :loading="loading"
    :error="errorMessage"
    :dirty="dirty"
    :saving="saving"
    :accepting="accepting"
    :can-accept="canAccept"
    @back="goBack"
    @refresh="refreshAll"
    @new-record="createRecord('TRACEABLE')"
    @navigate-stage="navigateStage"
    @select-record="selectRecord"
    @delete-record="deleteRecord"
    @show-diff="showDiff"
    @open-feedback="openFeedback()"
    @retry="retryStage"
    @release-lock="releaseFieldLock"
    @save="saveOnly"
    @accept="acceptStage"
  >
    <div v-if="!state && !loading" class="empty-stage">
      <div class="empty-icon">✦</div>
      <h2>开始一条完整的 AI 测试设计记录</h2>
      <p>一条记录会保存需求分析、测试点、测试用例和评审四个阶段；中途退出后可以继续恢复。</p>
      <div class="empty-actions">
        <button type="button" class="primary" @click="createRecord('TRACEABLE')">以可追踪模式开始</button>
        <button type="button" @click="createRecord('INTRINSIC')">以内在质量模式开始</button>
      </div>
      <ul><li>每个阶段单独保存版本</li><li>只有人工确认才会继续</li><li>“新建一轮”才创建另一条记录</li></ul>
    </div>

    <div v-else-if="state && !draftItems.length" class="empty-stage live-state">
      <div v-if="state.stage.status === 'GENERATING'" class="live-orb"><span></span></div>
      <div v-else class="empty-icon">◎</div>
      <h2>{{ emptyStageTitle }}</h2>
      <p>{{ emptyStageDescription }}</p>
      <div v-if="state.stage.steps.length" class="live-steps">
        <div v-for="step in state.stage.steps" :key="step.id"><span :class="step.status.toLowerCase()"></span><strong>{{ step.nodeName || step.nodeId }}</strong><small>{{ step.errorSummary || step.status }}</small></div>
      </div>
      <button v-if="state.allowedActions.canRetry" type="button" class="danger" @click="retryStage">重试失败步骤</button>
    </div>

    <RequirementAnalysisEditor
      v-else-if="stageKey === 'requirement-analysis' && state"
      v-model="draftItems"
      :source="state.source"
      @changed="dirty = true"
      @lock-field="lockField"
    />
    <TestPointsEditor
      v-else-if="stageKey === 'test-points'"
      v-model="draftItems"
      :known-rules="knownRules"
      @changed="dirty = true"
      @selection="selectedKeys = $event"
      @lock-field="lockField"
      @regenerate="openRegeneration"
    />
    <TestCasesEditor
      v-else-if="stageKey === 'test-cases'"
      v-model="draftItems"
      :focus-case="typeof route.query.focusCase === 'string' ? route.query.focusCase : undefined"
      :focus-field-path="typeof route.query.fieldPath === 'string' ? route.query.fieldPath : undefined"
      @changed="dirty = true"
      @selection="selectedKeys = $event"
      @lock-field="lockField"
      @regenerate="openRegeneration"
    />
    <CaseReviewEditor
      v-else-if="stageKey === 'case-review'"
      v-model="draftItems"
      @changed="dirty = true"
      @jump-case="jumpToCase"
      @apply-revision-request="applyReviewRevisionRequest"
    />
  </AiTestDesignWorkbenchLayout>

  <div v-if="feedbackOpen" class="drawer-overlay" @click.self="feedbackOpen = false">
    <aside class="feedback-drawer">
      <header><div><span>模型反馈</span><h2>保存反馈与局部重生成</h2><p>反馈会随重生成请求冻结为快照，但不会自动训练或微调模型。</p></div><button type="button" @click="feedbackOpen = false">×</button></header>
      <section>
        <label><span>反馈层级</span><select v-model="feedbackForm.targetType"><option value="FIELD">字段级</option><option value="ARTIFACT">单条产物</option><option value="STEP">生成步骤</option></select></label>
        <label><span>反馈分类</span><select v-model="feedbackForm.category"><option v-for="category in feedbackCategories" :key="category" :value="category">{{ category }}</option></select></label>
        <label v-if="feedbackForm.targetType !== 'STEP'"><span>目标产物</span><select v-model="feedbackForm.targetStableKey"><option v-for="item in baseRevision?.items || []" :key="item.stableKey" :value="item.stableKey">{{ item.stableKey }} · {{ artifactTitle(item.content) }}</option></select></label>
        <label v-if="feedbackForm.targetType === 'FIELD'"><span>目标字段路径</span><input v-model="feedbackForm.jsonPointer" placeholder="例如 /coreExpected 或 /steps/0/expected" /></label>
        <label><span>反馈说明</span><textarea v-model="feedbackForm.comment" rows="6" placeholder="说明事实错误、遗漏、覆盖不足或希望如何改进…" /></label>
      </section>
      <section class="snapshot-card"><strong>将写入重生成上下文</strong><p>当前完整版本、选中的目标、活动反馈、字段锁与上游已接受版本。</p><span v-if="selectedKeys.length">本次选择：{{ selectedKeys.join('、') }}</span></section>
      <footer><button type="button" @click="feedbackOpen = false">取消</button><button type="button" :disabled="feedbackSubmitting" @click="submitFeedback(false)">仅保存反馈</button><button type="button" class="primary" :disabled="feedbackSubmitting || !baseRevision" @click="submitFeedback(true)">{{ feedbackSubmitting ? '正在提交…' : '保存反馈并重新生成' }}</button></footer>
    </aside>
  </div>

  <div v-if="diffOpen" class="modal-overlay" @click.self="diffOpen = false">
    <section class="diff-modal">
      <header><div><span>版本差异</span><h2>AI 原始版本与当前修改</h2></div><button type="button" @click="diffOpen = false">×</button></header>
      <div v-if="diffLoading" class="diff-loading">正在计算结构化差异…</div>
      <template v-else-if="diffData">
        <div class="diff-summary"><article><strong>{{ diffSummary('added_count') }}</strong><span>新增</span></article><article><strong>{{ diffSummary('modified_count') }}</strong><span>修改</span></article><article><strong>{{ diffSummary('removed_count') }}</strong><span>删除</span></article><article><strong>{{ diffSummary('unchanged_count') }}</strong><span>未变</span></article></div>
        <div class="diff-items"><article v-for="(item,index) in diffItems" :key="index"><span :class="String(item.change_type || item.changeType || 'modified').toLowerCase()">{{ diffTypeLabel(String(item.change_type || item.changeType || 'modified')) }}</span><strong>{{ item.stable_key || item.stableKey || `变更 ${index+1}` }}</strong><pre>{{ formatDiffItem(item) }}</pre></article><p v-if="!diffItems.length">两个版本没有结构差异。</p></div>
      </template>
      <footer><button type="button" @click="diffOpen = false">关闭</button></footer>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ApiError } from "../../shared/api/client";
import { aiTestDesignApi } from "./api";
import AiTestDesignWorkbenchLayout from "./components/AiTestDesignWorkbenchLayout.vue";
import CaseReviewEditor from "./components/CaseReviewEditor.vue";
import RequirementAnalysisEditor from "./components/RequirementAnalysisEditor.vue";
import TestCasesEditor from "./components/TestCasesEditor.vue";
import TestPointsEditor from "./components/TestPointsEditor.vue";
import type {
  AiArtifactContent,
  AiDesignRecordSummary,
  AiDesignStageKey,
  AiRevisionItem,
  AiSetRevision,
  AiWorkbenchState,
  RequirementAnalysis,
  RequirementRule,
} from "./types";
import { canAcceptStage, resolveRecordId, shouldPollWorkbench, STAGE_ROUTES } from "./workflow";

const props = defineProps<{ stageKey: AiDesignStageKey }>();
const route = useRoute(); const router = useRouter();
const projectId = computed(() => String(route.params.projectId)); const taskId = computed(() => String(route.params.taskId));
const records = ref<AiDesignRecordSummary[]>([]); const activeRecordId = ref<string | null>(null); const state = ref<AiWorkbenchState | null>(null); const draftItems = ref<AiArtifactContent[]>([]); const knownRules = ref<RequirementRule[]>([]);
const loading = ref(true); const saving = ref(false); const accepting = ref(false); const dirty = ref(false); const errorMessage = ref(""); const selectedKeys = ref<string[]>([]);
const feedbackOpen = ref(false); const feedbackSubmitting = ref(false); const diffOpen = ref(false); const diffLoading = ref(false); const diffData = ref<Record<string, unknown> | null>(null);
let pollTimer: number | null = null; let pollBusy = false;
const feedbackCategories = ["事实错误","遗漏需求","覆盖不足","重复内容","表达模糊","前置条件不可构造","预期不可观察","追踪错误","优先级不合理","其他"];
const feedbackForm = reactive({ targetType: "ARTIFACT", category: "覆盖不足", targetStableKey: "", jsonPointer: "", comment: "" });
const baseRevision = computed<AiSetRevision | null>(() => state.value?.stage.candidateRevision ?? state.value?.stage.acceptedRevision ?? null);
const canAccept = computed(() => !!state.value?.stage.candidateRevision && state.value.allowedActions.canAccept && canAcceptStage(props.stageKey, draftItems.value));
const emptyStageTitle = computed(() => state.value?.stage.status === "GENERATION_FAILED" ? "本阶段生成失败" : state.value?.stage.status === "GENERATING" ? "模型正在生成真实候选结果" : "本阶段尚未生成");
const emptyStageDescription = computed(() => state.value?.stage.status === "GENERATION_FAILED" ? state.value.run.errorSummary || "请查看失败步骤并安全重试。" : state.value?.stage.status === "GENERATING" ? "页面展示来自服务端的真实步骤状态；完成后将自动出现候选版本，不使用假进度条。" : "请先完成人工确认的上游阶段。系统不会读取未接受或已过期的上游产物。" );

function clone<T>(value:T):T{return JSON.parse(JSON.stringify(value)) as T}
function setDraft(next:AiWorkbenchState){const revision=next.stage.candidateRevision??next.stage.acceptedRevision;draftItems.value=revision?revision.items.map((item)=>clone(item.content)):[];selectedKeys.value=props.stageKey==="test-points"?draftItems.value.filter((item)=>(item as {allowCaseGeneration?:boolean}).allowCaseGeneration).map((item)=>(item as {stableKey:string}).stableKey):[];dirty.value=false}
function message(error:unknown){if(error instanceof ApiError)return `${error.message}${error.code?`（${error.code}）`:""}`;return error instanceof Error?error.message:"操作失败，请稍后重试"}
async function loadRecords(){const response=await aiTestDesignApi.listRecords(projectId.value,taskId.value);records.value=response.items;const queryRecord=typeof route.query.recordId==="string"?route.query.recordId:undefined;activeRecordId.value=resolveRecordId(queryRecord,response.resumeRecordId)}
async function loadState(silent=false){if(!activeRecordId.value){state.value=null;draftItems.value=[];return}if(!silent)loading.value=true;try{const next=await aiTestDesignApi.getRecord(projectId.value,taskId.value,activeRecordId.value,props.stageKey);state.value=next;if(!dirty.value||!silent)setDraft(next);errorMessage.value="";await loadKnownRules();configurePolling()}catch(error){errorMessage.value=message(error)}finally{if(!silent)loading.value=false}}
async function loadKnownRules(){knownRules.value=[];if(!activeRecordId.value||props.stageKey==="requirement-analysis")return;try{const upstream=await aiTestDesignApi.getRecord(projectId.value,taskId.value,activeRecordId.value,"requirement-analysis");const item=(upstream.stage.acceptedRevision??upstream.stage.candidateRevision)?.items[0]?.content as RequirementAnalysis|undefined;knownRules.value=item?.rules??[]}catch{knownRules.value=[]}}
async function refreshAll(){loading.value=true;try{await loadRecords();const hasDeepLinkedRecord=typeof route.query.recordId==="string";const resumeRecord=records.value.find((record)=>record.id===activeRecordId.value);if(!hasDeepLinkedRecord&&resumeRecord){await router.replace({path:`/projects/${projectId.value}/test-tasks/${taskId.value}/ai-design/${STAGE_ROUTES[resumeRecord.currentStage]}`,query:{recordId:resumeRecord.id}});return}await loadState(true)}catch(error){errorMessage.value=message(error)}finally{loading.value=false}}
function configurePolling(){if(pollTimer!==null){window.clearInterval(pollTimer);pollTimer=null}if(state.value&&shouldPollWorkbench(state.value.run.status,state.value.stage.regenerationRequests.map((request)=>request.status))){pollTimer=window.setInterval(async()=>{if(pollBusy)return;pollBusy=true;try{await loadRecords();await loadState(true)}finally{pollBusy=false}},2500)}}
async function createRecord(mode:"TRACEABLE"|"INTRINSIC"){loading.value=true;errorMessage.value="";try{const created=await aiTestDesignApi.createRecord(projectId.value,taskId.value,mode,`ai-design-${crypto.randomUUID()}`);activeRecordId.value=created.id;await router.replace({path:`/projects/${projectId.value}/test-tasks/${taskId.value}/ai-design/requirement-analysis`,query:{recordId:created.id}});await loadRecords();await loadState(true)}catch(error){errorMessage.value=message(error)}finally{loading.value=false}}
async function selectRecord(recordId:string){if(dirty.value&&!window.confirm("当前有未保存修改，切换记录将丢失这些修改。是否继续？"))return;activeRecordId.value=recordId;await router.replace({query:{...route.query,recordId}});await loadState()}
async function deleteRecord(recordId:string){loading.value=true;errorMessage.value="";try{await aiTestDesignApi.deleteRecord(projectId.value,taskId.value,recordId);dirty.value=false;await loadRecords();if(activeRecordId.value===recordId){activeRecordId.value=records.value[0]?.id??null;await router.replace({query:{...route.query,recordId:activeRecordId.value??undefined}})}await loadState(true)}catch(error){errorMessage.value=message(error)}finally{loading.value=false}}
async function navigateStage(stage:AiDesignStageKey){if(dirty.value&&!window.confirm("当前有未保存修改，离开阶段将丢失这些修改。是否继续？"))return;await router.push({path:`/projects/${projectId.value}/test-tasks/${taskId.value}/ai-design/${STAGE_ROUTES[stage]}`,query:activeRecordId.value?{recordId:activeRecordId.value}:{}})}
function goBack(){router.push(`/projects/${projectId.value}/test-tasks/${taskId.value}`)}
async function saveOnly():Promise<boolean>{if(!state.value||!activeRecordId.value||!baseRevision.value)return false;if(!dirty.value)return true;saving.value=true;errorMessage.value="";try{await aiTestDesignApi.saveRevision(projectId.value,taskId.value,activeRecordId.value,props.stageKey,{baseSetRevisionId:baseRevision.value.id,expectedSetHash:baseRevision.value.setHash,items:clone(draftItems.value)});dirty.value=false;await loadRecords();await loadState(true);return true}catch(error){errorMessage.value=message(error);return false}finally{saving.value=false}}
function decisionSnapshot():Record<string,unknown>{if(props.stageKey==="requirement-analysis"){const analysis=draftItems.value[0] as RequirementAnalysis;return{questions:analysis.questions.map(({id,status,answer,decisionReason})=>({id,status,answer,decisionReason})),inferences:analysis.inferences.map(({id,decision})=>({id,decision}))}}if(props.stageKey==="test-points")return{selectedTestPointKeys:draftItems.value.filter((item)=>(item as {allowCaseGeneration?:boolean}).allowCaseGeneration).map((item)=>(item as {stableKey:string}).stableKey)};if(props.stageKey==="case-review")return{findingDecisions:(draftItems.value[0] as {findings:Array<Record<string,unknown>>}).findings.map((finding)=>({stableKey:finding.stableKey,decision:finding.decision,decisionReason:finding.decisionReason}))};return{acceptedCaseKeys:draftItems.value.map((item)=>(item as {stableKey:string}).stableKey)}}
async function acceptStage(){if(!state.value||!activeRecordId.value||!state.value.stage.candidateRevision||dirty.value||!canAccept.value)return;accepting.value=true;errorMessage.value="";try{await aiTestDesignApi.acceptStage(projectId.value,taskId.value,activeRecordId.value,props.stageKey,{setRevisionId:state.value.stage.candidateRevision.id,expectedCurrentSetRevisionId:state.value.stage.acceptedRevision?.id??null,decisionSnapshot:decisionSnapshot()});await loadRecords();await loadState(true)}catch(error){errorMessage.value=message(error)}finally{accepting.value=false}}
function openFeedback(keys:string[]=[]){if(keys.length)selectedKeys.value=keys;const first=selectedKeys.value[0]??baseRevision.value?.items[0]?.stableKey??"";feedbackForm.targetStableKey=first;feedbackOpen.value=true}
function openRegeneration(keys:string[]){openFeedback(keys)}
function targetItem():AiRevisionItem|undefined{return baseRevision.value?.items.find((item)=>item.stableKey===feedbackForm.targetStableKey)}
async function submitFeedback(regenerate:boolean){if(!state.value||!activeRecordId.value)return;feedbackSubmitting.value=true;errorMessage.value="";try{const item=targetItem();const step=state.value.stage.steps.find((entry)=>entry.nodeId===state.value?.stage.nodeId)??state.value.stage.steps[0];const payload:Record<string,unknown>={targetType:feedbackForm.targetType,category:feedbackForm.category,comment:feedbackForm.comment};if(feedbackForm.targetType==="STEP")payload.targetStepExecutionId=step?.id;else{payload.targetItemId=item?.itemId;payload.targetRevisionId=item?.revisionId;if(feedbackForm.targetType==="FIELD")payload.jsonPointer=feedbackForm.jsonPointer}const feedback=await aiTestDesignApi.createFeedback(projectId.value,taskId.value,activeRecordId.value,props.stageKey,payload);if(regenerate&&baseRevision.value){const targets=selectedKeys.value.length?selectedKeys.value:item?[item.stableKey]:[];await aiTestDesignApi.createRegenerationRequest(projectId.value,taskId.value,activeRecordId.value,props.stageKey,{targetItemStableKeys:targets,baseSetRevisionId:baseRevision.value.id,feedbackIds:[feedback.id]},`regen-${crypto.randomUUID()}`)}feedbackOpen.value=false;feedbackForm.comment="";await loadState(true)}catch(error){errorMessage.value=message(error)}finally{feedbackSubmitting.value=false}}
async function lockField(stableKey:string,pointer:string){if(!activeRecordId.value)return;const item=baseRevision.value?.items.find((entry)=>entry.stableKey===stableKey);if(!item)return;try{await aiTestDesignApi.createFieldLock(projectId.value,taskId.value,activeRecordId.value,props.stageKey,{itemId:item.itemId,revisionId:item.revisionId,jsonPointer:pointer});await loadState(true)}catch(error){errorMessage.value=message(error)}}
async function releaseFieldLock(lockId:string){if(!activeRecordId.value)return;try{await aiTestDesignApi.releaseFieldLock(projectId.value,taskId.value,activeRecordId.value,props.stageKey,lockId);await loadState(true)}catch(error){errorMessage.value=message(error)}}
async function retryStage(){if(!activeRecordId.value)return;try{await aiTestDesignApi.retryStage(projectId.value,taskId.value,activeRecordId.value,props.stageKey);await loadState(true)}catch(error){errorMessage.value=message(error)}}
async function showDiff(){const candidate=state.value?.stage.candidateRevision;if(!state.value||!candidate?.baseSetRevisionId)return;diffOpen.value=true;diffLoading.value=true;try{diffData.value=await aiTestDesignApi.getDiff(projectId.value,state.value.run.id,candidate.id,candidate.baseSetRevisionId)}catch(error){errorMessage.value=message(error);diffOpen.value=false}finally{diffLoading.value=false}}
function diffSummary(key:string){const summary=diffData.value?.summary as Record<string,unknown>|undefined;return Number(summary?.[key]??0)}
const diffItems=computed(()=>{const data=diffData.value as Record<string,unknown>|null;for(const key of ["items","changes","item_diffs"]){if(Array.isArray(data?.[key]))return data[key] as Array<Record<string,unknown>>}return[]})
function diffTypeLabel(type:string){return{added:"新增",modified:"修改",removed:"删除",unchanged:"未变"}[type.toLowerCase()]??type}
function formatDiffItem(item:Record<string,unknown>){const compact={before:item.before??item.old_content??item.oldContent,after:item.after??item.new_content??item.newContent,fields:item.field_changes??item.fieldChanges};return JSON.stringify(compact,null,2)}
function artifactTitle(content:AiArtifactContent){return (content as {title?:string;goal?:string;summary?:string}).title??(content as {goal?:string}).goal??(content as {summary?:string}).summary??"产物"}
function jumpToCase(caseRef:string,fieldPath?:string){router.push({path:`/projects/${projectId.value}/test-tasks/${taskId.value}/ai-design/test-cases`,query:{recordId:activeRecordId.value??undefined,focusCase:caseRef,fieldPath}})}
async function applyReviewRevisionRequest(request:{caseRef:string;fieldPath:string;instruction:string}){if(!activeRecordId.value)return;errorMessage.value="";if(!(await saveOnly()))return;try{const casesState=await aiTestDesignApi.getRecord(projectId.value,taskId.value,activeRecordId.value,"test-cases");const casesBase=casesState.stage.candidateRevision??casesState.stage.acceptedRevision;const target=casesBase?.items.find((item)=>item.stableKey===request.caseRef);if(!casesBase||!target)throw new Error("修订请求对应的测试用例或当前版本不存在");const feedback=await aiTestDesignApi.createFeedback(projectId.value,taskId.value,activeRecordId.value,"test-cases",{targetType:"FIELD",category:"其他",comment:request.instruction,targetItemId:target.itemId,targetRevisionId:target.revisionId,jsonPointer:request.fieldPath});await aiTestDesignApi.createRegenerationRequest(projectId.value,taskId.value,activeRecordId.value,"test-cases",{targetItemStableKeys:[target.stableKey],baseSetRevisionId:casesBase.id,feedbackIds:[feedback.id]},`review-regen-${crypto.randomUUID()}`);jumpToCase(request.caseRef,request.fieldPath)}catch(error){errorMessage.value=message(error)}}
watch(()=>[props.stageKey,route.query.recordId],async()=>{dirty.value=false;await loadRecords();await loadState()});
onMounted(refreshAll);onBeforeUnmount(()=>{if(pollTimer!==null)window.clearInterval(pollTimer)});
</script>

<style scoped>
.empty-stage{min-height:620px;display:grid;place-content:center;justify-items:center;text-align:center;padding:30px;color:#475467}.empty-icon{width:58px;height:58px;display:grid;place-items:center;border-radius:16px;background:#f0edff;color:#6941c6;font-size:27px}.empty-stage h2{margin:16px 0 7px;color:#1d2939}.empty-stage p{max-width:520px;margin:0;line-height:1.7;font-size:13px}.empty-actions{display:flex;gap:8px;margin-top:18px}.empty-actions button,.empty-stage>button{border:1px solid #d0d5dd;background:#fff;color:#475467;border-radius:8px;padding:9px 13px;font-weight:650}.empty-actions button.primary{background:#6754e9;border-color:#6754e9;color:#fff}.empty-stage ul{display:flex;gap:20px;margin-top:22px;padding:0;color:#667085;font-size:11px}.live-orb{width:64px;height:64px;border-radius:50%;border:1px solid #d9d6fe;display:grid;place-items:center;background:#f4f3ff}.live-orb span{width:18px;height:18px;border-radius:50%;background:#7f56d9;box-shadow:0 0 0 10px #7f56d919;animation:pulse 1.4s infinite}.live-steps{width:min(480px,80vw);display:grid;gap:6px;margin-top:18px;text-align:left}.live-steps>div{display:grid;grid-template-columns:auto 1fr;gap:3px 8px;padding:8px;border:1px solid #eaecf0;border-radius:7px}.live-steps span{width:8px;height:8px;border-radius:50%;background:#98a2b3;margin-top:4px}.live-steps span.running,.live-steps span.pending{background:#7f56d9}.live-steps span.failed{background:#f04438}.live-steps small{grid-column:2;color:#667085}.empty-stage button.danger{margin-top:15px;color:#b42318;border-color:#fecdca;background:#fff5f4}
.drawer-overlay,.modal-overlay{position:fixed;inset:0;z-index:1200;background:#10182866;display:flex;justify-content:flex-end}.feedback-drawer{width:min(460px,94vw);height:100%;background:#fff;display:flex;flex-direction:column;box-shadow:-14px 0 35px #10182826}.feedback-drawer header,.diff-modal header{display:flex;justify-content:space-between;gap:10px;padding:18px;border-bottom:1px solid #e4e7ec}.feedback-drawer header span,.diff-modal header span{color:#7f56d9;font-size:10px;text-transform:uppercase;letter-spacing:.08em}.feedback-drawer h2,.diff-modal h2{margin:4px 0}.feedback-drawer header p{margin:0;color:#667085;font-size:11px}.feedback-drawer header button,.diff-modal header button{border:0;background:transparent;font-size:22px}.feedback-drawer section{padding:16px;display:grid;gap:10px}.feedback-drawer label span{display:block;margin-bottom:5px;color:#475467;font-size:11px}.feedback-drawer input,.feedback-drawer select,.feedback-drawer textarea{box-sizing:border-box;width:100%;border:1px solid #d0d5dd;border-radius:7px;padding:8px;font:inherit;font-size:12px}.snapshot-card{margin:0 16px;padding:12px!important;background:#f9f5ff;border:1px solid #e9d7fe;border-radius:8px}.snapshot-card p{margin:5px 0;color:#667085;font-size:11px}.snapshot-card span{font-size:10px;color:#6941c6}.feedback-drawer footer,.diff-modal footer{margin-top:auto;display:flex;justify-content:flex-end;gap:7px;padding:14px 18px;border-top:1px solid #e4e7ec}.feedback-drawer footer button,.diff-modal footer button{border:1px solid #d0d5dd;background:#fff;border-radius:7px;padding:8px 10px}.feedback-drawer footer button.primary{background:#6754e9;color:#fff;border-color:#6754e9}.modal-overlay{justify-content:center;align-items:center}.diff-modal{width:min(850px,92vw);max-height:84vh;display:flex;flex-direction:column;background:#fff;border-radius:12px;overflow:hidden}.diff-loading{padding:50px;text-align:center;color:#667085}.diff-summary{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;padding:15px}.diff-summary article{display:grid;justify-items:center;padding:10px;background:#f9fafb;border-radius:7px}.diff-summary strong{font-size:20px}.diff-summary span{font-size:10px;color:#667085}.diff-items{padding:0 15px 15px;overflow:auto}.diff-items article{display:grid;grid-template-columns:auto 1fr;gap:6px;padding:10px 0;border-top:1px solid #eaecf0}.diff-items article>span{padding:3px 5px;border-radius:4px;background:#fffaeb;color:#b54708;font-size:9px}.diff-items span.added{background:#ecfdf3;color:#027a48}.diff-items span.removed{background:#fef3f2;color:#b42318}.diff-items pre{grid-column:1/-1;max-height:220px;overflow:auto;margin:0;padding:10px;background:#101828;color:#e4e7ec;border-radius:6px;font-size:10px}@keyframes pulse{50%{transform:scale(.75);opacity:.55}}@media(max-width:700px){.empty-stage ul{display:grid;gap:5px}.diff-summary{grid-template-columns:1fr 1fr}}
</style>
