<template>
  <div v-if="analysis" class="stage-editor">
    <section class="source-card">
      <div class="section-title">
        <div><span class="eyebrow">输入来源</span><h2>原始需求与附件</h2></div>
        <span class="source-badge">{{ source.requirement.requirementNo }}</span>
      </div>
      <h3>{{ source.requirement.title }}</h3>
      <p>{{ source.requirement.description || "未填写需求描述" }}</p>
      <p v-if="source.requirement.acceptanceCriteria" class="acceptance">
        <strong>验收标准：</strong>{{ source.requirement.acceptanceCriteria }}
      </p>
      <div v-if="source.attachments.length" class="attachment-row">
        <span v-for="attachment in source.attachments" :key="String(attachment.id)">
          📎 {{ attachment.fileName }}
        </span>
      </div>
    </section>

    <section class="editor-section">
      <div class="section-title">
        <div><span class="eyebrow">分析结论</span><h2>目标与范围</h2></div>
        <button type="button" class="lock-btn" @click="$emit('lock-field', analysis.stableKey, '/goal')">
          🔒 锁定目标
        </button>
      </div>
      <label class="field-label">需求目标</label>
      <textarea v-model="analysis.goal" rows="3" @input="changed" />
      <div class="scope-grid">
        <label>
          <span class="field-label">范围内（每行一项）</span>
          <textarea :value="analysis.inScope.join('\n')" rows="5" @input="updateLines('inScope', $event)" />
        </label>
        <label>
          <span class="field-label">排除范围（每行一项）</span>
          <textarea :value="analysis.outOfScope.join('\n')" rows="5" @input="updateLines('outOfScope', $event)" />
        </label>
      </div>
    </section>

    <section class="editor-section">
      <div class="section-title">
        <div><span class="eyebrow">结构建模</span><h2>模块及模块关系</h2></div>
        <button type="button" class="add-btn" @click="addModule">＋ 模块</button>
      </div>
      <div class="module-grid">
        <article v-for="(module, index) in analysis.modules" :key="module.id" class="inline-card">
          <div class="inline-head">
            <input v-model="module.title" placeholder="模块名称" @input="changed" />
            <button type="button" @click="analysis.modules.splice(index, 1); changed()">×</button>
          </div>
          <textarea v-model="module.description" rows="2" placeholder="职责与边界" @input="changed" />
          <small>{{ module.id }}</small>
        </article>
        <p v-if="!analysis.modules.length" class="empty-copy">未识别到模块，可手工补充。</p>
      </div>
      <div class="subsection-head"><h3>模块关系</h3><button type="button" @click="addRelation">＋ 关系</button></div>
      <div class="relation-list">
        <div v-for="(relation, index) in analysis.moduleRelations" :key="relation.id" class="relation-row">
          <select v-model="relation.sourceModuleRef" @change="changed">
            <option value="">来源模块</option><option v-for="m in analysis.modules" :key="m.id" :value="m.id">{{ m.title }}</option>
          </select>
          <span>→</span>
          <select v-model="relation.targetModuleRef" @change="changed">
            <option value="">目标模块</option><option v-for="m in analysis.modules" :key="m.id" :value="m.id">{{ m.title }}</option>
          </select>
          <input v-model="relation.relationType" placeholder="依赖/调用/共享状态" @input="changed" />
          <input v-model="relation.description" placeholder="关系说明" @input="changed" />
          <button type="button" @click="analysis.moduleRelations.splice(index, 1); changed()">删除</button>
        </div>
        <p v-if="!analysis.moduleRelations.length" class="empty-copy">暂无模块关系。</p>
      </div>
    </section>

    <section class="editor-section">
      <div class="section-title">
        <div><span class="eyebrow">事实与推断</span><h2>规则、推断与风险信号</h2></div>
      </div>
      <div class="split-columns">
        <div>
          <div class="subsection-head"><h3>明确规则</h3><button type="button" @click="addRule">＋ 规则</button></div>
          <article v-for="(rule, index) in analysis.rules" :key="rule.id" class="fact-row">
            <span class="id-chip">{{ rule.id }}</span>
            <textarea v-model="rule.description" rows="2" @input="changed" />
            <input :value="rule.evidenceRefs.join(', ')" placeholder="来源引用" @input="updateRefs(rule, 'evidenceRefs', $event)" />
            <button type="button" class="icon-btn" @click="$emit('lock-field', analysis.stableKey, `/rules/${index}/description`)">🔒</button>
            <button type="button" class="icon-btn" @click="analysis.rules.splice(index, 1); changed()">×</button>
          </article>
        </div>
        <div>
          <div class="subsection-head"><h3>推断内容</h3><button type="button" @click="addInference">＋ 推断</button></div>
          <article v-for="(inference, index) in analysis.inferences" :key="inference.id" class="fact-row">
            <span class="id-chip inferred">{{ inference.id }}</span>
            <textarea v-model="inference.description" rows="2" @input="changed" />
            <input v-model="inference.basis" placeholder="推断依据" @input="changed" />
            <select v-model="inference.decision" @change="changed">
              <option value="PENDING">待确认</option><option value="ACCEPTED">接受</option><option value="REJECTED">驳回</option>
            </select>
            <button type="button" class="icon-btn" @click="analysis.inferences.splice(index, 1); changed()">×</button>
          </article>
        </div>
      </div>
      <div class="subsection-head risk-head"><h3>风险与测试设计信号</h3><button type="button" @click="addRisk">＋ 风险</button></div>
      <div class="risk-grid">
        <article v-for="(risk, index) in analysis.risks" :key="risk.id" class="risk-card" :class="risk.level.toLowerCase()">
          <div class="inline-head"><input v-model="risk.title" @input="changed" /><select v-model="risk.level" @change="changed"><option>HIGH</option><option>MEDIUM</option><option>LOW</option></select><button type="button" @click="analysis.risks.splice(index, 1); changed()">×</button></div>
          <textarea v-model="risk.description" rows="2" @input="changed" />
          <input :value="risk.testSignals.join(', ')" placeholder="测试信号（逗号分隔）" @input="updateRefs(risk, 'testSignals', $event)" />
        </article>
      </div>
    </section>

    <section class="editor-section questions-section">
      <div class="section-title">
        <div><span class="eyebrow">人工决策</span><h2>待确认问题</h2></div>
        <span class="blocking-count">{{ unresolvedBlocking }} 个阻塞问题</span>
      </div>
      <article v-for="(question, index) in analysis.questions" :key="question.id" class="question-card" :class="{ blocking: question.blocking && question.status === 'PENDING' }">
        <div class="question-head">
          <span class="id-chip">{{ question.id }}</span>
          <input v-model="question.question" @input="changed" />
          <label class="checkbox"><input v-model="question.blocking" type="checkbox" @change="changed" /> 阻塞</label>
          <button type="button" class="icon-btn" @click="analysis.questions.splice(index, 1); changed()">×</button>
        </div>
        <div class="question-decision">
          <select v-model="question.status" @change="changed">
            <option value="PENDING">待回答</option><option value="ANSWERED">已回答</option><option value="ASSUMPTION_ACCEPTED">接受假设</option><option value="DEFERRED">暂不处理</option><option value="OUT_OF_SCOPE">范围外</option>
          </select>
          <input v-model="question.answer" placeholder="人工回答" @input="changed" />
          <input v-model="question.decisionReason" placeholder="决策说明" @input="changed" />
        </div>
      </article>
      <button type="button" class="add-question" @click="addQuestion">＋ 新增待确认问题</button>
    </section>

    <section class="editor-section">
      <div class="section-title"><div><span class="eyebrow">追踪</span><h2>来源证据</h2></div></div>
      <div class="evidence-list">
        <article v-for="evidence in analysis.evidence" :key="evidence.id">
          <div><span class="id-chip">{{ evidence.id }}</span><strong>{{ evidence.sourceRef }}</strong><small>{{ evidence.sourceType }}</small></div>
          <textarea v-model="evidence.quote" rows="2" @input="changed" />
        </article>
        <p v-if="!analysis.evidence.length" class="empty-copy">尚无证据引用；接受前建议补齐关键规则的来源。</p>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { AiArtifactContent, RequirementAnalysis } from "../types";

const props = defineProps<{
  modelValue: AiArtifactContent[];
  source: { requirement: Record<string, string | null>; attachments: Array<Record<string, string | null>> };
}>();
const emit = defineEmits<{
  "update:modelValue": [value: AiArtifactContent[]];
  changed: [];
  "lock-field": [stableKey: string, pointer: string];
}>();

const analysis = computed(() => props.modelValue[0] as RequirementAnalysis | undefined);
const unresolvedBlocking = computed(() => analysis.value?.questions.filter((q) => q.blocking && q.status === "PENDING").length ?? 0);

function changed() { emit("update:modelValue", props.modelValue); emit("changed"); }
function eventValue(event: Event): string { return (event.target as HTMLInputElement | HTMLTextAreaElement).value; }
function lines(value: string): string[] { return value.split("\n").map((item) => item.trim()).filter(Boolean); }
function updateLines(key: "inScope" | "outOfScope", event: Event) { if (!analysis.value) return; analysis.value[key] = lines(eventValue(event)); changed(); }
function updateRefs<T, K extends keyof T>(target: T, key: K, event: Event) {
  target[key] = eventValue(event).split(",").map((item) => item.trim()).filter(Boolean) as T[K];
  changed();
}
function id(prefix: string, count: number) { return `${prefix}-${String(count + 1).padStart(3, "0")}`; }
function addModule() { if (!analysis.value) return; analysis.value.modules.push({ id: `module-${crypto.randomUUID().slice(0, 8)}`, title: "新模块", description: "" }); changed(); }
function addRelation() { if (!analysis.value) return; analysis.value.moduleRelations.push({ id: id("REL", analysis.value.moduleRelations.length), sourceModuleRef: "", targetModuleRef: "", relationType: "依赖", description: "", evidenceRefs: [] }); changed(); }
function addRule() { if (!analysis.value) return; analysis.value.rules.push({ id: id("RULE", analysis.value.rules.length), description: "", evidenceRefs: [] }); changed(); }
function addInference() { if (!analysis.value) return; analysis.value.inferences.push({ id: id("INF", analysis.value.inferences.length), description: "", basis: "", evidenceRefs: [], decision: "PENDING" }); changed(); }
function addRisk() { if (!analysis.value) return; analysis.value.risks.push({ id: id("RISK", analysis.value.risks.length), title: "新风险", description: "", level: "MEDIUM", testSignals: [], evidenceRefs: [] }); changed(); }
function addQuestion() { if (!analysis.value) return; analysis.value.questions.push({ id: id("Q", analysis.value.questions.length), question: "", blocking: false, status: "PENDING", answer: "", decisionReason: "", scope: "IN_SCOPE" }); changed(); }
</script>

<style scoped>
.stage-editor { padding: 18px; display: grid; gap: 14px; background: #f9fafb; }.source-card,.editor-section { border: 1px solid #e4e7ec; background: #fff; border-radius: 11px; padding: 17px; }.source-card { background: linear-gradient(135deg,#f8f7ff,#fff); border-color: #e4e0ff; }.section-title,.inline-head,.subsection-head,.question-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }.eyebrow { color: #7f56d9; font-size: 10px; text-transform: uppercase; letter-spacing: .08em; }.section-title h2 { margin: 3px 0 0; font-size: 17px; }.source-card h3 { margin: 15px 0 5px; }.source-card p { margin: 5px 0; color: #475467; font-size: 13px; line-height: 1.6; }.source-badge,.id-chip { border-radius: 6px; background: #f0edff; color: #6941c6; padding: 4px 7px; font-size: 10px; font-weight: 700; }.acceptance { padding-top: 8px; border-top: 1px dashed #d6d0f5; }.attachment-row { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 10px; }.attachment-row span { font-size: 11px; background: #fff; border: 1px solid #e4e7ec; padding: 5px 8px; border-radius: 6px; }
.field-label { display: block; margin: 14px 0 6px; color: #344054; font-size: 12px; font-weight: 650; }textarea,input,select { box-sizing: border-box; width: 100%; border: 1px solid #d0d5dd; border-radius: 7px; background: #fff; color: #1d2939; padding: 8px 10px; font: inherit; font-size: 12px; }textarea:focus,input:focus,select:focus { outline: 2px solid #7f56d925; border-color: #7f56d9; }.scope-grid,.split-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 13px; }.module-grid,.risk-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 9px; margin-top: 13px; }.inline-card,.risk-card { padding: 10px; background: #f9fafb; border: 1px solid #eaecf0; border-radius: 8px; }.inline-head { margin-bottom: 7px; }.inline-head button,.icon-btn { width: auto; border: 0; background: transparent; color: #98a2b3; cursor: pointer; }.inline-card small { color: #98a2b3; }.add-btn,.lock-btn,.subsection-head button,.add-question { width: auto; border: 1px solid #d6d0ff; background: #f7f5ff; color: #6941c6; border-radius: 7px; padding: 6px 9px; font-size: 11px; cursor: pointer; }.subsection-head { margin: 17px 0 8px; }.subsection-head h3 { margin: 0; font-size: 13px; }.relation-list { display: grid; gap: 7px; }.relation-row { display: grid; grid-template-columns: 1fr auto 1fr 1fr 1.4fr auto; gap: 6px; align-items: center; }.relation-row button { border: 0; background: transparent; color: #b42318; cursor: pointer; }.fact-row { display: grid; grid-template-columns: auto 1fr auto; gap: 7px; align-items: start; padding: 8px 0; border-bottom: 1px solid #f2f4f7; }.fact-row textarea,.fact-row input,.fact-row select { grid-column: 2; }.fact-row .icon-btn { grid-column: 3; grid-row: auto; }.id-chip.inferred { background: #fffaeb; color: #b54708; }.risk-card { border-left: 3px solid #f79009; }.risk-card.high { border-left-color: #f04438; }.risk-card.low { border-left-color: #12b76a; }.risk-head { border-top: 1px solid #eaecf0; padding-top: 15px; }
.questions-section { border-color: #d9d6fe; }.blocking-count { background: #fff4ed; color: #b93815; border-radius: 999px; padding: 5px 8px; font-size: 10px; }.question-card { margin-top: 9px; padding: 10px; border: 1px solid #eaecf0; border-radius: 8px; }.question-card.blocking { border-color: #fdb022; background: #fffcf5; }.question-head { display: grid; grid-template-columns: auto 1fr auto auto; }.checkbox { display: flex; align-items: center; gap: 4px; font-size: 11px; white-space: nowrap; }.checkbox input { width: auto; }.question-decision { display: grid; grid-template-columns: 150px 1fr 1fr; gap: 7px; margin-top: 8px; }.add-question { margin-top: 10px; }.evidence-list article { display: grid; grid-template-columns: 180px 1fr; gap: 10px; align-items: start; padding: 9px 0; border-bottom: 1px solid #f2f4f7; }.evidence-list article div { display: grid; gap: 5px; }.evidence-list small { color: #98a2b3; }.empty-copy { color: #98a2b3; font-size: 12px; }
@media(max-width:900px){.scope-grid,.split-columns,.module-grid,.risk-grid{grid-template-columns:1fr}.relation-row{grid-template-columns:1fr 1fr}.question-decision{grid-template-columns:1fr}.evidence-list article{grid-template-columns:1fr}}
</style>
