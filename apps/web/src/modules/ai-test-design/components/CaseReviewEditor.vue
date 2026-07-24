<template>
  <div v-if="report" class="review-editor">
    <header class="review-header">
      <div><span class="eyebrow">质量门禁</span><h2>测试用例评审报告</h2><p>评审只形成 Finding 与定向修订请求，不直接覆盖测试用例。</p></div>
      <div class="mode-switch"><button v-for="mode in ['TRACEABLE','INTRINSIC']" :key="mode" type="button" :class="{active:report.mode===mode}" @click="report.mode=mode as CaseReviewReport['mode'];changed()">{{ mode==='TRACEABLE'?'可追踪评审':'内在质量评审' }}</button></div>
    </header>

    <section class="gate-card" :class="report.gateRecommendation.toLowerCase()">
      <div><span>总体门禁建议</span><select v-model="report.gateRecommendation" @change="changed"><option value="PASS">通过</option><option value="PASS_WITH_WARNINGS">带警告通过</option><option value="BLOCK">阻止发布</option></select></div>
      <textarea v-model="report.summary" rows="3" @input="changed" />
      <div class="metrics"><article><strong>{{ passCount }}</strong><span>通过用例</span></article><article><strong>{{ warningCount }}</strong><span>警告用例</span></article><article><strong>{{ failCount }}</strong><span>失败用例</span></article><article><strong>{{ report.findings.length }}</strong><span>Finding</span></article></div>
    </section>

    <section class="review-section">
      <div class="section-head"><div><span class="eyebrow">逐条结果</span><h2>用例评审状态</h2></div></div>
      <div class="case-result-grid"><button v-for="result in report.caseResults" :key="result.caseRef" type="button" @click="$emit('jump-case', result.caseRef)"><span class="status-dot" :class="result.status.toLowerCase()"></span><strong>{{ result.caseRef }}</strong><small>{{ statusLabel(result.status) }} · {{ result.findingRefs.length }} 个问题</small><span>定位字段 →</span></button></div>
    </section>

    <section class="review-section">
      <div class="section-head"><div><span class="eyebrow">审查意见</span><h2>Finding 决策</h2></div><span class="pending-pill">{{ pendingCount }} 条待处理</span></div>
      <article v-for="(finding,index) in report.findings" :key="finding.stableKey" class="finding-card" :class="finding.severity.toLowerCase()">
        <div class="finding-head"><div><span class="severity">{{ severityLabel(finding.severity) }}</span><strong>{{ finding.stableKey }}</strong><button type="button" @click="$emit('jump-case', finding.caseRef, finding.fieldPath)">{{ finding.caseRef }} · {{ finding.fieldPath }} ↗</button></div><button type="button" class="remove" @click="report.findings.splice(index,1);changed()">×</button></div>
        <label><span>问题说明</span><textarea v-model="finding.description" rows="2" @input="changed" /></label>
        <label><span>定向修改建议</span><textarea v-model="finding.suggestion" rows="2" @input="changed" /></label>
        <div class="finding-meta"><label><span>证据引用</span><input :value="finding.evidenceRefs.join(', ')" @input="updateFindingRefs(finding,$event)" /></label><label><span>严重级别</span><select v-model="finding.severity" @change="changed"><option>INFO</option><option>WARNING</option><option>ERROR</option><option>CRITICAL</option></select></label></div>
        <div class="decision-row"><button v-for="decision in ['ACCEPTED','REJECTED','EDITED']" :key="decision" type="button" :class="{active:finding.decision===decision}" @click="finding.decision=decision as ReviewFinding['decision'];changed()">{{ decisionLabel(decision) }}</button><input v-model="finding.decisionReason" :placeholder="finding.decision==='REJECTED'?'驳回原因（必填）':'人工决策说明'" @input="changed" /><button type="button" class="revision-btn" @click="toRevisionRequest(finding)">转为定向修订请求</button></div>
      </article>
      <p v-if="!report.findings.length" class="empty">没有 Finding。</p>
    </section>

    <section class="review-section">
      <div class="coverage-layout">
        <div><span class="eyebrow">覆盖报告</span><h2>规则与测试点覆盖</h2><div class="bar-row"><span>规则覆盖</span><div><i :style="{width:`${report.coverage.ruleCoverage*100}%`}"></i></div><strong>{{ Math.round(report.coverage.ruleCoverage*100) }}%</strong></div><div class="bar-row"><span>测试点覆盖</span><div><i :style="{width:`${report.coverage.testPointCoverage*100}%`}"></i></div><strong>{{ Math.round(report.coverage.testPointCoverage*100) }}%</strong></div><div v-if="report.coverage.uncoveredRefs.length" class="uncovered"><strong>未覆盖：</strong><span v-for="ref in report.coverage.uncoveredRefs" :key="ref">{{ ref }}</span></div></div>
        <div><span class="eyebrow">重复聚类</span><h2>疑似重复用例</h2><article v-for="cluster in report.duplicateClusters" :key="cluster.id" class="cluster"><strong>{{ cluster.caseRefs.join(' ↔ ') }}</strong><p>{{ cluster.reason }}</p></article><p v-if="!report.duplicateClusters.length" class="empty">未发现重复聚类。</p></div>
      </div>
    </section>

    <section class="review-section">
      <div class="coverage-layout">
        <div><span class="eyebrow">风险保留</span><h2>未解决假设</h2><div class="assumptions"><span v-for="assumption in report.unresolvedAssumptions" :key="assumption">{{ assumption }}</span><span v-if="!report.unresolvedAssumptions.length">暂无</span></div></div>
        <div><span class="eyebrow">人工确认后应用</span><h2>定向修订请求</h2><article v-for="request in report.revisionRequests" :key="request.id" class="request-card"><div><strong>{{ request.caseRef }} · {{ request.fieldPath }}</strong><span>{{ request.status }}</span></div><textarea v-model="request.instruction" rows="2" @input="changed" /><div class="request-actions"><select v-model="request.status" @change="changed"><option value="DRAFT">草稿</option><option value="CONFIRMED">已确认</option><option value="REJECTED">已驳回</option><option value="APPLIED">已应用</option></select><button type="button" :disabled="request.status==='REJECTED'||request.status==='APPLIED'" @click="confirmRevisionRequest(request)">确认并发起用例重生成</button></div></article><p v-if="!report.revisionRequests.length" class="empty">尚未形成修订请求。</p></div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { AiArtifactContent, CaseReviewReport, ReviewFinding } from "../types";
const props=defineProps<{modelValue:AiArtifactContent[]}>();
const emit=defineEmits<{"update:modelValue":[value:AiArtifactContent[]];changed:[];"jump-case":[caseRef:string,fieldPath?:string];"apply-revision-request":[request:{caseRef:string;fieldPath:string;instruction:string}]}>();
const report=computed(()=>props.modelValue[0] as CaseReviewReport|undefined);
const passCount=computed(()=>report.value?.caseResults.filter((r)=>r.status==="PASS").length??0);const warningCount=computed(()=>report.value?.caseResults.filter((r)=>r.status==="WARNING").length??0);const failCount=computed(()=>report.value?.caseResults.filter((r)=>r.status==="FAIL").length??0);const pendingCount=computed(()=>report.value?.findings.filter((f)=>f.decision==="PENDING").length??0);
function changed(){emit("update:modelValue",props.modelValue);emit("changed")}
function eventValue(event:Event){return(event.target as HTMLInputElement).value}
function updateFindingRefs(finding:ReviewFinding,event:Event){finding.evidenceRefs=eventValue(event).split(",").map((v)=>v.trim()).filter(Boolean);changed()}
function toRevisionRequest(finding:ReviewFinding){if(!report.value)return;const exists=report.value.revisionRequests.some((r)=>r.id===`RR-${finding.stableKey}`);if(!exists)report.value.revisionRequests.push({id:`RR-${finding.stableKey}`,caseRef:finding.caseRef,fieldPath:finding.fieldPath,instruction:finding.suggestion,status:"DRAFT"});finding.decision="ACCEPTED";finding.decisionReason="已转为定向修订请求，等待用户确认应用";changed()}
function confirmRevisionRequest(request:CaseReviewReport["revisionRequests"][number]){request.status="CONFIRMED";changed();emit("apply-revision-request",{caseRef:request.caseRef,fieldPath:request.fieldPath,instruction:request.instruction})}
function statusLabel(status:string){return{PASS:"通过",WARNING:"警告",FAIL:"失败"}[status]??status}function severityLabel(value:string){return{INFO:"提示",WARNING:"警告",ERROR:"错误",CRITICAL:"严重"}[value]??value}function decisionLabel(value:string){return{ACCEPTED:"接受",REJECTED:"驳回",EDITED:"编辑后接受"}[value]??value}
</script>

<style scoped>
.review-editor{padding:18px;background:#f9fafb;display:grid;gap:13px}.review-header,.section-head,.finding-head,.finding-head>div{display:flex;align-items:center;justify-content:space-between;gap:10px}.review-header h2,.review-section h2{margin:3px 0;font-size:18px}.review-header p{margin:0;color:#667085;font-size:12px}.eyebrow{color:#7f56d9;font-size:10px;text-transform:uppercase;letter-spacing:.08em}.mode-switch{display:flex;padding:3px;background:#f2f4f7;border-radius:8px}.mode-switch button{border:0;background:transparent;padding:7px 9px;border-radius:6px;color:#667085;font-size:10px}.mode-switch button.active{background:#fff;color:#6941c6;box-shadow:0 1px 3px #1018281a}.gate-card,.review-section{background:#fff;border:1px solid #e4e7ec;border-radius:10px;padding:15px}.gate-card{display:grid;grid-template-columns:180px 1fr;gap:12px;border-left:4px solid #f79009}.gate-card.pass{border-left-color:#12b76a}.gate-card.block{border-left-color:#f04438}.gate-card>div:first-child span{display:block;color:#667085;font-size:10px;margin-bottom:5px}input,select,textarea{box-sizing:border-box;width:100%;border:1px solid #d0d5dd;border-radius:6px;padding:7px 8px;background:#fff;font:inherit;font-size:11px}.metrics{grid-column:1/-1;display:grid;grid-template-columns:repeat(4,1fr);gap:7px}.metrics article{display:grid;justify-items:center;padding:9px;background:#f9fafb;border-radius:7px}.metrics strong{font-size:18px}.metrics span{font-size:9px;color:#667085}.case-result-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-top:11px}.case-result-grid button{display:grid;grid-template-columns:auto 1fr;gap:4px 7px;text-align:left;padding:9px;border:1px solid #eaecf0;background:#fff;border-radius:7px}.case-result-grid small,.case-result-grid button>span:last-child{grid-column:2;color:#667085;font-size:9px}.status-dot{width:7px;height:7px;border-radius:50%;background:#12b76a;margin-top:3px}.status-dot.warning{background:#f79009}.status-dot.fail{background:#f04438}.pending-pill{background:#fffaeb;color:#b54708;padding:4px 7px;border-radius:999px;font-size:10px}.finding-card{margin-top:9px;padding:11px;border:1px solid #fedf89;border-left:3px solid #f79009;border-radius:8px}.finding-card.error,.finding-card.critical{border-color:#fecdca;border-left-color:#f04438}.finding-card.info{border-color:#b9e6fe;border-left-color:#0ba5ec}.severity{font-size:9px;background:#fffaeb;color:#b54708;padding:3px 5px;border-radius:4px}.finding-head button{border:0;background:transparent;color:#6941c6;font-size:10px}.finding-head button.remove{color:#b42318}.finding-card label>span{display:block;margin:8px 0 4px;color:#475467;font-size:9px}.finding-meta{display:grid;grid-template-columns:2fr 1fr;gap:7px}.decision-row{display:grid;grid-template-columns:auto auto auto 1fr auto;gap:5px;margin-top:9px}.decision-row button{border:1px solid #d0d5dd;background:#fff;color:#475467;border-radius:6px;padding:6px;font-size:9px}.decision-row button.active{border-color:#7f56d9;background:#f4f3ff;color:#6941c6}.decision-row button.revision-btn{border-color:#fdb022;color:#b54708}.coverage-layout{display:grid;grid-template-columns:1fr 1fr;gap:20px}.bar-row{display:grid;grid-template-columns:80px 1fr 38px;align-items:center;gap:7px;margin-top:10px;font-size:10px}.bar-row>div{height:6px;background:#eaecf0;border-radius:999px;overflow:hidden}.bar-row i{display:block;height:100%;background:#12b76a}.uncovered,.assumptions{display:flex;gap:5px;flex-wrap:wrap;margin-top:10px;font-size:10px}.uncovered span,.assumptions span{padding:4px 6px;background:#fffaeb;border-radius:4px}.cluster,.request-card{padding:8px;margin-top:7px;background:#f9fafb;border-radius:7px}.cluster p{margin:4px 0 0;color:#667085;font-size:10px}.request-card>div{display:flex;justify-content:space-between;margin-bottom:6px;font-size:10px}.request-card span{color:#b54708}.request-actions{display:grid!important;grid-template-columns:110px 1fr;gap:6px;margin-top:7px}.request-actions button{border:1px solid #fdb022;background:#fffaeb;color:#b54708;border-radius:6px;padding:7px;font-size:9px}.request-actions button:disabled{opacity:.45}.empty{color:#98a2b3;font-size:11px}@media(max-width:800px){.review-header{align-items:flex-start;flex-direction:column}.gate-card,.coverage-layout{grid-template-columns:1fr}.case-result-grid{grid-template-columns:1fr 1fr}.decision-row{grid-template-columns:1fr 1fr}.metrics{grid-template-columns:1fr 1fr}}
</style>
