<template>
  <div class="agent-center-container">
    <!-- 顶部标题区 -->
    <div class="header-section">
      <div class="title-wrapper">
        <h2 class="title">AI 能力中心</h2>
        <span class="badge">只读控制台</span>
      </div>
      <p class="subtitle">管理平台可同步、只读查看的 AI 测试能力、拓扑流水线以及外部智能体。</p>
    </div>

    <!-- 上半部分：令牌管理 + 智能体活动状态 (两栏布局) -->
    <div class="top-row">
      <!-- 令牌管理卡片 -->
      <div class="glass-card token-card">
        <div class="card-header">
          <div class="header-left">
            <span class="icon">🔑</span>
            <h3>项目同步令牌 (Token)</h3>
          </div>
          <button class="btn btn-primary" @click="openCreateTokenModal">
            <span>+</span> 生成新令牌
          </button>
        </div>
        <div class="card-body">
          <div v-if="tokens.length === 0" class="empty-state-mini">
            暂无已生成的同步令牌，请点击右上角生成。
          </div>
          <div v-else class="table-wrapper">
            <table class="data-table">
              <thead>
                <tr>
                  <th>令牌名称</th>
                  <th>前缀</th>
                  <th>授权 Scopes</th>
                  <th>到期时间</th>
                  <th>状态</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="token in tokens"
                  :key="token.id"
                  :class="{ 'row-revoked': token.is_revoked }"
                >
                  <td class="font-bold">{{ token.name }}</td>
                  <td class="font-mono">{{ token.token_prefix }}...</td>
                  <td>
                    <span
                      v-for="s in token.scopes"
                      :key="s"
                      class="scope-tag"
                    >
                      {{ s }}
                    </span>
                  </td>
                  <td>{{ token.expires_at ? formatDate(token.expires_at) : "永不过期" }}</td>
                  <td>
                    <span
                      class="status-badge"
                      :class="token.is_revoked ? 'status-revoked' : 'status-active'"
                    >
                      <span class="dot"></span>
                      {{ token.is_revoked ? "已撤销" : "生效中" }}
                    </span>
                  </td>
                  <td>
                    <button
                      v-if="!token.is_revoked"
                      class="btn btn-text-danger"
                      @click="confirmRevokeToken(token)"
                    >
                      撤销
                    </button>
                    <span v-else class="text-muted">-</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- 智能体活动连接卡片 -->
      <div class="glass-card agent-card">
        <div class="card-header">
          <div class="header-left">
            <span class="icon">🤖</span>
            <h3>外部智能体 (Agent) 连接</h3>
          </div>
          <span class="connection-status" :class="activeAgent ? 'connected' : 'disconnected'">
            <span class="dot-blink"></span>
            {{ activeAgent ? "检测到活动智能体" : "未连接" }}
          </span>
        </div>
        <div class="card-body">
          <div v-if="!activeAgent" class="empty-agent">
            <div class="agent-icon-bg">🔌</div>
            <p>暂无活跃的外部智能体连接</p>
            <span class="help-tips">请使用 CLI 令牌并在终端中运行智能体进行接入</span>
          </div>
          <div v-else class="agent-details">
            <div class="detail-row">
              <span class="label">连接名称：</span>
              <span class="value highlight-text">{{ activeAgent.connection_name }}</span>
            </div>
            <div class="detail-row">
              <span class="label">客户端信息：</span>
              <span class="value"
                >{{ activeAgent.client_name }} (v{{ activeAgent.client_version }})</span
              >
            </div>
            <div class="detail-row">
              <span class="label">运行平台：</span>
              <span class="value font-mono">{{ activeAgent.platform }}</span>
            </div>
            <div class="detail-row">
              <span class="label">协议版本：</span>
              <span class="value font-mono">{{ activeAgent.protocol_version }}</span>
            </div>
            <div class="detail-row">
              <span class="label">最后活跃时间：</span>
              <span class="value">{{ formatDate(activeAgent.last_active_at) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 下半部分：只读 AI 能力目录 (主区域) -->
    <div class="main-row">
      <div class="glass-card capability-card">
        <div class="card-header">
          <div class="header-left">
            <span class="icon">📦</span>
            <h3>已同步的 AI 能力目录</h3>
          </div>
        </div>
        <div class="card-body-flex">
          <!-- 左侧：能力包列表 -->
          <div class="list-column">
            <div v-if="capabilities.length === 0" class="empty-list">
              <p>暂无可用的 AI 能力包</p>
              <span class="desc">外部 Agent 成功同步能力包后，将自动展示在此处</span>
            </div>
            <div
              v-for="cap in capabilities"
              :key="cap.id"
              class="cap-item"
              :class="{ active: selectedCapability?.id === cap.id }"
              @click="selectCapability(cap)"
            >
              <div class="cap-meta">
                <span class="cap-title">{{ cap.name }}</span>
                <span class="cap-code font-mono">{{ cap.code }}</span>
              </div>
              <div class="cap-footer">
                <span class="tag tag-scope" :class="'scope-' + cap.scope.toLowerCase()">
                  {{ cap.scope === "OFFICIAL" ? "官方授权" : "项目专属" }}
                </span>
                <span class="tag tag-category">{{ formatCategory(cap.category) }}</span>
                <span class="tag tag-ver">v{{ cap.version }}</span>
              </div>
            </div>
          </div>

          <!-- 右侧：只读详情详情 (抽屉式面板) -->
          <div class="detail-column">
            <div v-if="!selectedCapability" class="detail-placeholder">
              <div class="placeholder-icon">🔍</div>
              <p>选择左侧能力包查看只读拓扑与快照</p>
            </div>
            <div v-else class="detail-content">
              <!-- 能力基础信息 -->
              <div class="detail-header-info">
                <div>
                  <h4>{{ selectedCapability.name }}</h4>
                  <p class="cap-id-desc font-mono">ID: {{ selectedCapability.id }}</p>
                </div>
                <button
                  v-if="
                    selectedCapability.compatibility_level === 'PLATFORM_NATIVE' ||
                    !selectedCapability.compatibility_level
                  "
                  class="btn btn-primary btn-sm"
                  @click="triggerPreviewRun(selectedCapability)"
                >
                  🚀 触发预览调试 (Run)
                </button>
              </div>

              <!-- 选项卡切换 -->
              <div class="tabs">
                <button
                  :class="{ active: activeTab === 'overview' }"
                  @click="activeTab = 'overview'"
                >
                  拓扑与校验
                </button>
                <button
                  :class="{ active: activeTab === 'versions' }"
                  @click="activeTab = 'versions'"
                >
                  版本历史
                </button>
                <button
                  :class="{ active: activeTab === 'snapshot' }"
                  @click="activeTab = 'snapshot'"
                >
                  只读快照
                </button>
                <button
                  :class="{ active: activeTab === 'evaluations' }"
                  @click="activeTab = 'evaluations'"
                >
                  🧪 评测与案例
                </button>
                <button
                  :class="{ active: activeTab === 'packages' }"
                  @click="activeTab = 'packages'"
                >
                  📦 优化包导出
                </button>
                <button
                  :class="{ active: activeTab === 'releases' }"
                  @click="activeTab = 'releases'"
                >
                  🚀 发布与灰度
                </button>
              </div>

              <!-- Tab 1: 拓扑与校验 -->
              <div v-if="activeTab === 'overview'" class="tab-pane pane-overview">
                <!-- 校验报告 -->
                <div
                  v-if="selectedVersionDetail?.report"
                  class="report-box"
                  :class="selectedVersionDetail.report.valid ? 'report-ok' : 'report-error'"
                >
                  <div class="report-header">
                    <span class="report-title">⚙️ 同步安全校验报告</span>
                    <span class="report-status">{{
                      selectedVersionDetail.report.valid ? "验证成功" : "验证不通过"
                    }}</span>
                  </div>
                  <div class="report-body">
                    <p class="font-mono text-small">
                      指纹 (Fingerprint): {{ selectedVersionDetail.report.fingerprint }}
                    </p>
                    <p class="text-small">
                      验证时间: {{ formatDate(selectedVersionDetail.report.verified_at) }}
                    </p>
                    <div
                      v-if="selectedVersionDetail.report.issues.length > 0"
                      class="report-issues"
                    >
                      <span class="issue-label">检测到警示问题:</span>
                      <ul>
                        <li
                          v-for="(issue, idx) in selectedVersionDetail.report.issues"
                          :key="idx"
                          class="text-warning text-small"
                        >
                          ⚠️ {{ issue }}
                        </li>
                      </ul>
                    </div>
                  </div>
                </div>

                <!-- DAG 拓扑图渲染 -->
                <div class="dag-container">
                  <div class="section-title">Workflow DAG 执行拓扑有向图</div>
                  <div class="dag-canvas-wrapper" v-if="dagLayoutData.nodes.length > 0">
                    <svg
                      :width="dagLayoutData.width"
                      :height="dagLayoutData.height"
                      class="dag-svg"
                    >
                      <defs>
                        <!-- 渐变线与箭头 -->
                        <marker
                          id="arrow"
                          viewBox="0 0 10 10"
                          refX="6"
                          refY="5"
                          markerWidth="6"
                          markerHeight="6"
                          orient="auto-start-reverse"
                        >
                          <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#64748b" />
                        </marker>
                      </defs>

                      <!-- 渲染有向边 -->
                      <path
                        v-for="edge in dagLayoutData.edges"
                        :key="edge.id"
                        :d="edge.path"
                        fill="none"
                        stroke="#475569"
                        stroke-width="2"
                        marker-end="url(#arrow)"
                        class="dag-edge"
                      />

                      <!-- 渲染节点 -->
                      <g
                        v-for="node in dagLayoutData.nodes"
                        :key="node.id"
                        :transform="`translate(${node.x}, ${node.y})`"
                        class="dag-node-group"
                      >
                        <!-- 节点卡片框 -->
                        <rect
                          width="140"
                          height="44"
                          rx="8"
                          fill="#1e293b"
                          stroke="#38bdf8"
                          stroke-width="1.5"
                          class="dag-node-rect"
                        />
                        <!-- 节点文本 -->
                        <text
                          x="12"
                          y="18"
                          fill="#f8fafc"
                          font-size="11"
                          font-weight="600"
                          class="font-mono"
                        >
                          {{ truncateText(node.label, 15) }}
                        </text>
                        <!-- 节点类型 -->
                        <text x="12" y="32" fill="#64748b" font-size="9">
                          类型: {{ formatNodeType(node.type) }}
                        </text>
                      </g>
                    </svg>
                  </div>
                  <div v-else class="empty-dag text-muted text-small">
                    未检测到有向节点流定义或无需图形展示。
                  </div>
                </div>
              </div>

              <!-- Tab 2: 版本历史 -->
              <div v-if="activeTab === 'versions'" class="tab-pane pane-versions">
                <div class="version-timeline">
                  <div
                    v-for="ver in versions"
                    :key="ver.id"
                    class="version-timeline-item"
                    :class="{ active: selectedVersionDetail?.id === ver.id }"
                    @click="fetchVersionDetail(ver.id)"
                  >
                    <div class="version-badge">v{{ ver.version }}</div>
                    <div class="version-timeline-content">
                      <div class="version-info-line">
                        <span class="v-date">{{ formatDate(ver.created_at) }}</span>
                        <span class="v-status">同步草稿 (SYNCED_DRAFT)</span>
                      </div>
                      <span class="font-mono text-xs text-muted block"
                        >哈希: {{ ver.manifest_hash.slice(0, 12) }}...</span
                      >
                    </div>
                  </div>
                </div>
              </div>

              <!-- Tab 3: 只读快照 -->
              <div v-if="activeTab === 'snapshot'" class="tab-pane pane-snapshot">
                <div class="snapshot-layout">
                  <!-- 文件列表 -->
                  <div class="snapshot-files">
                    <span class="section-title">能力包文件清单</span>
                    <div
                      v-for="file in selectedVersionDetail?.files"
                      :key="file.path"
                      class="file-item"
                      :class="{ active: selectedFile?.path === file.path }"
                      @click="selectedFile = file"
                    >
                      📄 {{ file.path }}
                    </div>
                  </div>
                  <!-- 文件快照只读预览 -->
                  <div class="snapshot-viewer">
                    <div class="viewer-header">
                      <span class="font-mono text-small">{{
                        selectedFile?.path || "未选择文件"
                      }}</span>
                      <span class="badge badge-gray text-xs">只读快照</span>
                    </div>
                    <pre
                      v-if="selectedFile"
                      class="code-pre"
                    ><code><div v-for="(line, idx) in selectedFile.content.split('\n')" :key="idx" class="code-line"><span class="line-num">{{ idx + 1 }}</span><span class="line-text">{{ line }}</span></div></code></pre>
                    <div v-else class="empty-viewer text-muted">请在左侧选择要预览的文件快照</div>
                  </div>
                </div>
              </div>

              <!-- Tab 4: 🧪 评测与案例 (P5) -->
              <div v-if="activeTab === 'evaluations'" class="tab-pane pane-evaluations">
                <div class="p5-section-box">
                  <h4>评测集与不可变 Revision</h4>
                  <p class="text-sm text-muted">包含全量官方与项目私有冻结评测版本。</p>
                  <div class="empty-state-mini">
                    已准备评测环境：通过评测集对比新旧 CapabilityVersion 的准确率与断言匹配度。
                  </div>
                </div>
              </div>

              <!-- Tab 5: 📦 优化包导出 (P5) -->
              <div v-if="activeTab === 'packages'" class="tab-pane pane-packages">
                <div class="p5-section-box">
                  <h4>基于 Evidence 驱动的优化建议</h4>
                  <p class="text-sm text-muted">聚合生产观察、用户 DISLIKE 反馈与历史失败评测案例。</p>
                  <div class="empty-state-mini">
                    已生成 Evidence 导出包：支持生成不可变 Workspace Package 并下载至外部 Agent。
                  </div>
                </div>
              </div>

              <!-- Tab 6: 🚀 发布与灰度 (P5) -->
              <div v-if="activeTab === 'releases'" class="tab-pane pane-releases">
                <div class="p5-section-box">
                  <h4>发布评审与 1..9999 basis points 灰度控制台</h4>
                  <p class="text-sm text-muted">严格受控的能力演进闭环与安全回滚。</p>
                  <div class="canary-control-card glass-card">
                    <div class="canary-header">
                      <span>灰度比例 (Canary Basis Points)</span>
                      <span class="badge badge-info">1000 bp (10.0%)</span>
                    </div>
                    <div class="slider-wrapper mt-2">
                      <input type="range" min="1" max="9999" value="1000" class="slider" disabled />
                    </div>
                    <div class="canary-actions mt-3">
                      <button class="btn btn-secondary text-sm">调整灰度比例</button>
                      <button class="btn btn-primary text-sm ml-2">全量晋级 (Promote)</button>
                      <button class="btn btn-danger text-sm ml-2">显式安全回滚 (Rollback)</button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 弹窗 1：创建 Access Token 弹窗 -->
    <div v-if="tokenModalVisible" class="modal-backdrop">
      <div class="modal-dialog glass-card">
        <div class="modal-header">
          <h3>新建外接 Agent 访问令牌 (Access Token)</h3>
          <button class="btn-close" @click="closeTokenModal">×</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label class="form-label">令牌名称 *</label>
            <input
              v-model="newTokenName"
              type="text"
              class="form-control"
              placeholder="例如: cli-dev-agent-token"
              maxLength="100"
            />
          </div>

          <div class="form-group">
            <label class="form-label">有效期限 *</label>
            <select v-model="newTokenTtlDays" class="form-control">
              <option :value="30">30 天 (推荐)</option>
              <option :value="7">7 天</option>
              <option :value="90">90 天</option>
              <option :value="null">永不过期</option>
            </select>
          </div>

          <div class="form-group">
            <label class="form-label">授权作用域 (Scopes) *</label>
            <div class="scopes-checkbox-list">
              <label class="checkbox-label">
                <input type="checkbox" value="workspace:spec" v-model="newTokenScopes" />
                <span><code>workspace:spec</code> (拉取 Workspace 代码生成 Spec)</span>
              </label>
              <label class="checkbox-label">
                <input type="checkbox" value="test_task.read" v-model="newTokenScopes" />
                <span><code>test_task.read</code> (读取测试任务列表与详情)</span>
              </label>
              <label class="checkbox-label">
                <input type="checkbox" value="requirement.read" v-model="newTokenScopes" />
                <span><code>requirement.read</code> (读取需求列表与正文文档)</span>
              </label>
              <label class="checkbox-label">
                <input type="checkbox" value="revision:candidate" v-model="newTokenScopes" />
                <span><code>revision:candidate</code> (提交候选 Revision 与生成结果)</span>
              </label>
              <label class="checkbox-label">
                <input type="checkbox" value="revision:publish_request" v-model="newTokenScopes" />
                <span><code>revision:publish_request</code> (发起发布评审请求)</span>
              </label>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="closeTokenModal" :disabled="loading">
            取消
          </button>
          <button
            class="btn btn-primary"
            @click="handleCreateToken"
            :disabled="loading || !newTokenName.trim() || newTokenScopes.length === 0"
          >
            {{ loading ? "生成中..." : "确认生成" }}
          </button>
        </div>
      </div>
    </div>

    <!-- 弹窗 2：令牌仅展一次明文结果弹窗 -->
    <div v-if="newTokenResultVisible" class="modal-backdrop">
      <div class="modal-dialog glass-card modal-wide">
        <div class="modal-header">
          <h3>🎉 令牌生成成功</h3>
        </div>
        <div class="modal-body">
          <div class="alert alert-warning">
            <strong>⚠️ 请注意：</strong>
            该同步令牌（Token）的明文密码<strong>仅在此处展示一次</strong>。一旦关闭本弹窗，您将再也无法获取该令牌的完整内容。请立即复制并妥善保管！
          </div>

          <div class="token-result-box">
            <span class="token-plaintext font-mono">{{ newTokenPlaintext }}</span>
            <button class="btn btn-copy" @click="copyTokenToClipboard">
              {{ copySuccess ? "✅ 已复制" : "📋 复制令牌" }}
            </button>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-primary" @click="closeTokenResultModal">
            已妥善保存，关闭弹窗
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { apiClient } from "../../shared/api/client";
import { aiRunsApi } from "./aiRunsApi";

// 数据实体定义
interface AgentToken {
  id: string;
  name: string;
  token_prefix: string;
  scopes: string[];
  expires_at: string | null;
  revoked_at: string | null;
  created_at: string;
  is_revoked?: boolean;
}

interface ExternalAgent {
  id: string;
  connection_name: string;
  client_name: string;
  client_version: string;
  platform: string;
  protocol_version: string;
  last_active_at: string;
}

interface AICapability {
  id: string;
  project_id: string | null;
  code: string;
  name: string;
  version: string;
  category: string;
  scope: string;
  compatibility_level?: string;
  current_published_version_id?: string;
  created_at: string;
  updated_at: string;
}

interface AICapabilityVersion {
  id: string;
  capability_id: string;
  version: string;
  manifest_hash: string;
  manifest_content: {
    protocol_version: string;
    capability: {
      id: string;
      version: string;
      name: string;
      category: string;
      compatibility_level: string;
    };
    workflow_entry: string;
  };
  created_at: string;
}

interface SnapshotFile {
  path: string;
  content: string;
}

interface AICapabilityVersionDetail extends AICapabilityVersion {
  files: SnapshotFile[];
  report: {
    fingerprint: string;
    valid: boolean;
    issues: string[];
    verified_at: string;
  } | null;
}

// 路由及项目隔离
const route = useRoute();
const router = useRouter();
const projectId = computed(() => route.params.projectId as string);

async function triggerPreviewRun(cap: AICapability): Promise<void> {
  if (!projectId.value) return;
  const targetVerId = cap.current_published_version_id || selectedVersionDetail.value?.id;
  const idempKey = `preview_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  try {
    const res = await aiRunsApi.createRun(
      projectId.value,
      cap.id,
      {
        runMode: "PREVIEW",
        capabilityVersionId: targetVerId,
        input: { requirement_text: "登录图形验证码流程设计需求" },
      },
      idempKey,
    );
    router.push(`/projects/${projectId.value}/agent/runs/${res.id}`);
  } catch (err: unknown) {
    alert(err instanceof Error ? err.message : "发起试运行失败");
  }
}

// 状态定义
const tokens = ref<AgentToken[]>([]);
const activeAgent = ref<ExternalAgent | null>(null);
const capabilities = ref<AICapability[]>([]);
const selectedCapability = ref<AICapability | null>(null);
const versions = ref<AICapabilityVersion[]>([]);
const selectedVersionDetail = ref<AICapabilityVersionDetail | null>(null);
const selectedFile = ref<SnapshotFile | null>(null);

const activeTab = ref<"overview" | "versions" | "snapshot">("overview");
const loading = ref(false);
const currentUser = ref<{ is_system_admin: boolean } | null>(null);

// 弹窗状态
const tokenModalVisible = ref(false);
const newTokenName = ref("");
const newTokenTtlDays = ref<number | null>(30);
const newTokenScopes = ref<string[]>(["workspace:spec", "test_task.read", "requirement.read", "revision:candidate"]);

const newTokenResultVisible = ref(false);
const newTokenPlaintext = ref("");
const copySuccess = ref(false);

// 初始化数据
onMounted(async () => {
  await fetchCurrentUser();
  if (projectId.value) {
    await refreshAll();
  }
});

// 监听项目ID变化
watch(projectId, async (newId) => {
  if (newId) {
    selectedCapability.value = null;
    selectedVersionDetail.value = null;
    selectedFile.value = null;
    await refreshAll();
  }
});

async function refreshAll() {
  await Promise.all([fetchTokens(), fetchCapabilities()]);
}

// 接口调用
async function fetchCurrentUser() {
  try {
    currentUser.value = await apiClient.get(
      "/api/v1/auth/me",
      (res) => res as { is_system_admin: boolean },
    );
  } catch (err) {
    console.error("获取当前用户信息失败", err);
    // 回退兜底
    currentUser.value = { is_system_admin: false };
  }
}

async function fetchTokens() {
  if (!projectId.value) return;
  try {
    const res = await apiClient.get(
      `/api/v1/projects/${projectId.value}/external-tokens`,
      (data) => data as { tokens: any[] },
    );
    tokens.value = (res.tokens || []).map((t) => ({
      id: t.id,
      name: t.name,
      token_prefix: t.tokenPrefix || t.token_prefix,
      scopes: t.scopes || [],
      expires_at: t.expiresAt || t.expires_at,
      revoked_at: t.revokedAt || t.revoked_at,
      created_at: t.createdAt || t.created_at,
      is_revoked: !!(t.revokedAt || t.revoked_at),
    }));
  } catch (err) {
    console.error("拉取外接 Access Token 失败", err);
  }
}

async function fetchActiveAgent() {
  // M09 全面升级为无状态 Gateway，不再维持有状态 Worker 连线轮询
  activeAgent.value = null;
}

async function fetchCapabilities() {
  if (!projectId.value) return;
  try {
    capabilities.value = await apiClient.get(
      `/api/v1/projects/${projectId.value}/ai-capabilities`,
      (res) => res as AICapability[],
    );
    if (capabilities.value.length > 0 && !selectedCapability.value) {
      selectCapability(capabilities.value[0]);
    }
  } catch (err) {
    console.error("拉取能力包列表失败", err);
  }
}

async function selectCapability(cap: AICapability) {
  selectedCapability.value = cap;
  selectedVersionDetail.value = null;
  selectedFile.value = null;
  activeTab.value = "overview";

  try {
    // 1. 获取版本历史
    versions.value = await apiClient.get(
      `/api/v1/projects/${projectId.value}/ai-capabilities/${cap.id}/versions`,
      (res) => res as AICapabilityVersion[],
    );

    // 2. 默认加载最新版详情
    if (versions.value.length > 0) {
      await fetchVersionDetail(versions.value[0].id);
    }
  } catch (err) {
    console.error("拉取版本列表失败", err);
  }
}

async function fetchVersionDetail(versionId: string) {
  if (!selectedCapability.value) return;
  try {
    selectedVersionDetail.value = await apiClient.get(
      `/api/v1/projects/${projectId.value}/ai-capabilities/${selectedCapability.value.id}/versions/${versionId}`,
      (res) => res as AICapabilityVersionDetail,
    );

    // 默认选中第一个快照文件进行预览
    if (selectedVersionDetail.value?.files.length > 0) {
      selectedFile.value = selectedVersionDetail.value.files[0];
    } else {
      selectedFile.value = null;
    }
  } catch (err) {
    console.error("拉取版本详情失败", err);
  }
}

// 令牌生成
function openCreateTokenModal() {
  newTokenName.value = "";
  newTokenTtlDays.value = 30;
  newTokenScopes.value = ["workspace:spec", "test_task.read", "requirement.read", "revision:candidate"];
  tokenModalVisible.value = true;
}

function closeTokenModal() {
  tokenModalVisible.value = false;
}

async function handleCreateToken() {
  if (!projectId.value || !newTokenName.value.trim()) return;
  if (newTokenScopes.value.length === 0) {
    alert("请至少勾选一个 Token 授权作用域 (Scope)");
    return;
  }
  loading.value = true;
  try {
    const payload = {
      name: newTokenName.value.trim(),
      scopes: newTokenScopes.value,
      ttlDays: newTokenTtlDays.value,
    };
    const res = await apiClient.post(
      `/api/v1/projects/${projectId.value}/external-tokens`,
      (data) => data as { rawToken: string },
      payload,
    );

    newTokenPlaintext.value = res.rawToken;
    tokenModalVisible.value = false;
    newTokenResultVisible.value = true;

    // 刷新令牌列表
    await fetchTokens();
  } catch (err: any) {
    alert(`生成 Access Token 失败: ${err.message || "未知错误"}`);
  } finally {
    loading.value = false;
  }
}

function closeTokenResultModal() {
  newTokenResultVisible.value = false;
  newTokenPlaintext.value = "";
  copySuccess.value = false;
}

function copyTokenToClipboard() {
  if (!newTokenPlaintext.value) return;
  navigator.clipboard.writeText(newTokenPlaintext.value).then(() => {
    copySuccess.value = true;
    setTimeout(() => {
      copySuccess.value = false;
    }, 2000);
  });
}

// 令牌撤销
async function confirmRevokeToken(token: AgentToken) {
  const confirmText = `⚠️ 警告: 您确定要撤销令牌 "${token.name}" (前缀: ${token.token_prefix}) 吗？\n撤销后，使用该 Token 的外部 Agent 连接将立即失效！`;
  if (confirm(confirmText)) {
    try {
      await apiClient.delete(
        `/api/v1/projects/${projectId.value}/external-tokens/${token.id}`,
        (res) => res,
      );
      await fetchTokens();
    } catch (err: any) {
      alert(`撤销令牌失败: ${err.message || "未知错误"}`);
    }
  }
}

// 简易有向图拓扑分层布局 (DAG Layout)
const dagLayoutData = computed(() => {
  const workflowFile = selectedVersionDetail.value?.files.find(
    (f) =>
      f.path === selectedVersionDetail.value?.manifest_content.workflow_entry ||
      f.path === "workflow.yaml",
  );
  if (!workflowFile) return { nodes: [], edges: [], width: 400, height: 200 };

  const { nodes, edges } = parseWorkflowYaml(workflowFile.content);
  return computeDagLayout(nodes, edges);
});

// 纯文本 YAML 解析，提取节点和边
function parseWorkflowYaml(yaml: string) {
  const nodes: Array<{ id: string; type?: string }> = [];
  const edges: Array<{ source: string; target: string }> = [];

  const lines = yaml.split("\n");
  let section: "nodes" | "edges" | null = null;
  let currentItem: any = null;

  for (let line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;

    if (trimmed.startsWith("nodes:")) {
      section = "nodes";
      if (currentItem) {
        pushItem(currentItem, section);
        currentItem = null;
      }
      continue;
    }
    if (trimmed.startsWith("edges:")) {
      section = "edges";
      if (currentItem) {
        pushItem(currentItem, "nodes");
        currentItem = null;
      }
      continue;
    }

    if (trimmed.startsWith("-")) {
      if (currentItem) {
        pushItem(currentItem, section);
      }
      currentItem = {};
      const rest = trimmed.slice(1).trim();
      if (rest) {
        parsePair(rest, currentItem);
      }
    } else {
      if (currentItem) {
        parsePair(trimmed, currentItem);
      }
    }
  }
  if (currentItem) {
    pushItem(currentItem, section);
  }

  function pushItem(item: any, sec: "nodes" | "edges" | null) {
    if (sec === "nodes" && item.id) {
      nodes.push({ id: item.id, type: item.type || "skill" });
    } else if (sec === "edges" && item.source && item.target) {
      edges.push({ source: item.source, target: item.target });
    }
  }

  function parsePair(strPair: string, obj: any) {
    const idx = strPair.indexOf(":");
    if (idx !== -1) {
      const key = strPair.slice(0, idx).trim();
      const val = strPair
        .slice(idx + 1)
        .trim()
        .replace(/^['"]|['"]$/g, "");
      obj[key] = val;
    }
  }

  return { nodes, edges };
}

// 自动拓扑分层并分配 X/Y 坐标
function computeDagLayout(nodes: any[], edges: any[]) {
  if (nodes.length === 0) return { nodes: [], edges: [], width: 400, height: 200 };

  const depth: Record<string, number> = {};
  nodes.forEach((n) => {
    depth[n.id] = 0;
  });

  for (let i = 0; i < nodes.length; i++) {
    let changed = false;
    edges.forEach((e) => {
      const u = e.source;
      const v = e.target;
      if (depth[u] !== undefined && depth[v] !== undefined) {
        if (depth[v] < depth[u] + 1) {
          depth[v] = depth[u] + 1;
          changed = true;
        }
      }
    });
    if (!changed) break;
  }

  const levels: Record<number, string[]> = {};
  nodes.forEach((n) => {
    const l = depth[n.id] || 0;
    if (!levels[l]) levels[l] = [];
    levels[l].push(n.id);
  });

  const maxLevel = Math.max(...Object.keys(levels).map(Number), 0);

  const nodeCoords: Record<string, { x: number; y: number; label: string; type: string }> = {};
  const colWidth = 240;
  const rowHeight = 80;
  const marginX = 40;
  const marginY = 40;

  let maxNodesInLevel = 0;
  Object.keys(levels).forEach((lvlStr) => {
    const lvl = Number(lvlStr);
    const nids = levels[lvl];
    maxNodesInLevel = Math.max(maxNodesInLevel, nids.length);
  });

  Object.keys(levels).forEach((lvlStr) => {
    const lvl = Number(lvlStr);
    const nids = levels[lvl];
    const totalHeightOfLevel = nids.length * rowHeight;
    const startY = marginY + (maxNodesInLevel * rowHeight - totalHeightOfLevel) / 2;

    nids.forEach((id, index) => {
      const nodeObj = nodes.find((n) => n.id === id);
      nodeCoords[id] = {
        x: marginX + lvl * colWidth,
        y: startY + index * rowHeight,
        label: id,
        type: nodeObj?.type || "skill",
      };
    });
  });

  const renderedNodes = Object.entries(nodeCoords).map(([id, coord]) => ({
    id,
    ...coord,
  }));

  const renderedEdges = edges
    .map((e) => {
      const start = nodeCoords[e.source];
      const end = nodeCoords[e.target];
      if (!start || !end) return null;

      const x1 = start.x + 140;
      const y1 = start.y + 22;
      const x2 = end.x;
      const y2 = end.y + 22;

      const cp1x = x1 + 50;
      const cp1y = y1;
      const cp2x = x2 - 50;
      const cp2y = y2;

      return {
        id: `${e.source}->${e.target}`,
        path: `M ${x1} ${y1} C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${x2} ${y2}`,
      };
    })
    .filter(Boolean);

  const svgWidth = marginX + (maxLevel + 1) * colWidth + 50;
  const svgHeight = marginY + maxNodesInLevel * rowHeight + 50;

  return {
    nodes: renderedNodes,
    edges: renderedEdges,
    width: Math.max(svgWidth, 400),
    height: Math.max(svgHeight, 200),
  };
}

// 辅助格式化函数
function formatDate(dateStr: string): string {
  if (!dateStr) return "-";
  const date = new Date(dateStr);
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatCategory(category: string): string {
  const mapping: Record<string, string> = {
    REQUIREMENT_ANALYSIS: "需求分析",
    TEST_DESIGN: "测试设计",
    TEST_EXECUTION: "测试执行",
    QUALITY_EVALUATION: "质量评估",
  };
  return mapping[category] || category;
}

function formatNodeType(type: string): string {
  const mapping: Record<string, string> = {
    skill: "模型算子 (Skill)",
    validator: "校验过滤器 (Validator)",
    human: "人机交互审计 (Human)",
  };
  return mapping[type] || type;
}

function truncateText(text: string, len: number): string {
  if (!text) return "";
  return text.length > len ? text.slice(0, len) + "..." : text;
}
</script>

<style scoped>
.agent-center-container {
  display: flex;
  flex-direction: column;
  gap: 20px;
  width: 100%;
  padding-bottom: 40px;
  box-sizing: border-box;
}

.header-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.title-wrapper {
  display: flex;
  align-items: center;
  gap: 12px;
}

.title {
  color: #f1f5f9;
  font-size: 22px;
  font-weight: 700;
  margin: 0;
}

.badge {
  background: rgba(56, 189, 248, 0.15);
  border: 1px solid rgba(56, 189, 248, 0.3);
  color: #38bdf8;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 600;
}

.badge-gray {
  background: rgba(148, 163, 184, 0.15);
  border: 1px solid rgba(148, 163, 184, 0.3);
  color: #94a3b8;
}

.subtitle {
  color: #94a3b8;
  font-size: 13px;
  margin: 0;
}

/* 两栏两行式排版 */
.top-row {
  display: grid;
  grid-template-columns: 1.5fr 1fr;
  gap: 20px;
}

@media (max-width: 1024px) {
  .top-row {
    grid-template-columns: 1fr;
  }
}

.glass-card {
  background: rgba(30, 41, 59, 0.45);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
  overflow: hidden;
}

.card-header {
  padding: 16px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-left h3 {
  color: #e2e8f0;
  font-size: 15px;
  font-weight: 600;
  margin: 0;
}

.header-left .icon {
  font-size: 18px;
}

.card-body {
  padding: 20px;
  flex: 1;
}

/* 按钮样式 */
.btn {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #e2e8f0;
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: all 0.2s ease;
}

.btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.1);
  border-color: rgba(255, 255, 255, 0.2);
}

.btn-primary {
  background: #0284c7;
  border-color: #0369a1;
  color: #ffffff;
}

.btn-primary:hover:not(:disabled) {
  background: #0ea5e9;
  border-color: #0284c7;
}

.btn-secondary {
  background: rgba(71, 85, 105, 0.3);
  border-color: rgba(71, 85, 105, 0.5);
  color: #94a3b8;
}

.btn-secondary:hover:not(:disabled) {
  background: rgba(71, 85, 105, 0.5);
  color: #f1f5f9;
}

.btn-text-danger {
  background: transparent;
  border: none;
  color: #f87171;
  cursor: pointer;
  font-size: 12px;
  padding: 4px 8px;
  border-radius: 4px;
  transition: background 0.2s;
}

.btn-text-danger:hover {
  background: rgba(248, 113, 113, 0.1);
}

.btn-close {
  background: transparent;
  border: none;
  color: #64748b;
  font-size: 22px;
  cursor: pointer;
}

.btn-close:hover {
  color: #e2e8f0;
}

/* 令牌列表数据表 */
.table-wrapper {
  overflow-x: auto;
  max-height: 180px;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
  font-size: 12px;
}

.data-table th {
  color: #64748b;
  font-weight: 600;
  padding: 10px 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
}

.data-table td {
  padding: 10px 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  color: #cbd5e1;
}

.row-revoked td {
  color: #475569 !important;
}

.font-mono {
  font-family: SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
}

.scope-tag {
  background: rgba(148, 163, 184, 0.1);
  border: 1px solid rgba(148, 163, 184, 0.2);
  color: #94a3b8;
  padding: 1px 6px;
  border-radius: 4px;
}

.scope-official {
  background: rgba(234, 179, 8, 0.1);
  border-color: rgba(234, 179, 8, 0.2);
  color: #facc15;
}

/* 状态标签 */
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
}

.status-badge .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.status-active {
  color: #4ade80;
}

.status-active .dot {
  background: #4ade80;
  box-shadow: 0 0 8px #4ade80;
}

.status-revoked {
  color: #64748b;
}

.status-revoked .dot {
  background: #64748b;
}

.text-muted {
  color: #64748b;
}

.empty-state-mini {
  color: #64748b;
  font-size: 12px;
  text-align: center;
  padding: 40px 0;
}

/* 智能体状态展示 */
.connection-status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 600;
}

.connection-status.connected {
  color: #34d399;
}

.connection-status.disconnected {
  color: #94a3b8;
}

.connection-status .dot-blink {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.connection-status.connected .dot-blink {
  background: #34d399;
  box-shadow: 0 0 10px #34d399;
  animation: breathe 2s infinite ease-in-out;
}

.connection-status.disconnected .dot-blink {
  background: #64748b;
}

@keyframes breathe {
  0%,
  100% {
    opacity: 0.4;
  }
  50% {
    opacity: 1;
  }
}

.empty-agent {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 140px;
  text-align: center;
}

.agent-icon-bg {
  font-size: 32px;
  margin-bottom: 10px;
  filter: grayscale(1);
  opacity: 0.5;
}

.empty-agent p {
  color: #e2e8f0;
  font-size: 13px;
  margin: 0 0 4px 0;
}

.help-tips {
  color: #64748b;
  font-size: 11px;
}

.agent-details {
  display: flex;
  flex-direction: column;
  gap: 12px;
  justify-content: center;
  height: 100%;
}

.detail-row {
  display: flex;
  font-size: 12px;
}

.detail-row .label {
  color: #64748b;
  width: 110px;
}

.detail-row .value {
  color: #cbd5e1;
}

.highlight-text {
  color: #38bdf8 !important;
  font-weight: 600;
}

/* 下半部分布局 (能力目录主区域) */
.main-row {
  display: flex;
  flex-direction: column;
}

.card-body-flex {
  display: flex;
  height: 600px;
  overflow: hidden;
}

@media (max-width: 768px) {
  .card-body-flex {
    flex-direction: column;
    height: auto;
    overflow: visible;
  }
}

/* 左侧能力列表 */
.list-column {
  width: 320px;
  border-right: 1px solid rgba(255, 255, 255, 0.06);
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  padding: 10px;
  gap: 10px;
  box-sizing: border-box;
}

@media (max-width: 768px) {
  .list-column {
    width: 100%;
    border-right: none;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    max-height: 250px;
  }
}

.empty-list {
  padding: 40px 10px;
  text-align: center;
  color: #64748b;
}

.empty-list p {
  font-size: 13px;
  margin: 0 0 6px 0;
}

.empty-list .desc {
  font-size: 11px;
}

.cap-item {
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.04);
  border-radius: 8px;
  padding: 12px 14px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: all 0.2s;
}

.cap-item:hover {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.08);
}

.cap-item.active {
  background: rgba(56, 189, 248, 0.08);
  border-color: rgba(56, 189, 248, 0.3);
}

.cap-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.cap-title {
  color: #e2e8f0;
  font-size: 14px;
  font-weight: 600;
}

.cap-code {
  color: #64748b;
  font-size: 11px;
}

.cap-footer {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tag {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 500;
}

.tag-scope {
  background: rgba(56, 189, 248, 0.1);
  color: #38bdf8;
}

.tag-scope.scope-official {
  background: rgba(234, 179, 8, 0.1);
  color: #facc15;
}

.tag-category {
  background: rgba(139, 92, 246, 0.1);
  color: #a78bfa;
}

.tag-ver {
  background: rgba(255, 255, 255, 0.05);
  color: #94a3b8;
  border: 1px solid rgba(255, 255, 255, 0.08);
}

/* 右侧详情面板 */
.detail-column {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: rgba(15, 23, 42, 0.2);
}

.detail-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #64748b;
}

.placeholder-icon {
  font-size: 40px;
  margin-bottom: 12px;
  opacity: 0.3;
}

.detail-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 24px;
  box-sizing: border-box;
}

@media (max-width: 768px) {
  .detail-content {
    overflow: visible;
    height: auto;
  }
}

.detail-header-info {
  margin-bottom: 16px;
}

.detail-header-info h4 {
  color: #f1f5f9;
  font-size: 18px;
  margin: 0 0 4px 0;
}

.cap-id-desc {
  color: #64748b;
  font-size: 11px;
  margin: 0;
}

/* Tabs */
.tabs {
  display: flex;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  margin-bottom: 20px;
  gap: 16px;
}

.tabs button {
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: #94a3b8;
  padding: 8px 4px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.tabs button:hover {
  color: #e2e8f0;
}

.tabs button.active {
  color: #38bdf8;
  border-bottom-color: #38bdf8;
}

/* Tab 面板内容容器 */
.tab-pane {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.section-title {
  color: #94a3b8;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 8px;
  display: block;
}

/* 校验报告盒子 */
.report-box {
  background: rgba(30, 41, 59, 0.3);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 8px;
  padding: 14px 18px;
}

.report-ok {
  border-left: 4px solid #10b981;
}

.report-error {
  border-left: 4px solid #ef4444;
}

.report-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 10px;
}

.report-title {
  color: #e2e8f0;
  font-size: 13px;
  font-weight: 600;
}

.report-status {
  font-size: 12px;
  font-weight: 600;
}

.report-ok .report-status {
  color: #10b981;
}

.report-error .report-status {
  color: #ef4444;
}

.report-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.report-issues {
  margin-top: 10px;
  border-top: 1px solid rgba(255, 255, 255, 0.04);
  padding-top: 10px;
}

.issue-label {
  font-size: 11px;
  color: #f59e0b;
  font-weight: 600;
}

.report-issues ul {
  margin: 6px 0 0 0;
  padding-left: 18px;
}

.report-issues li {
  margin-bottom: 4px;
}

.text-small {
  font-size: 11px;
}

.text-warning {
  color: #fbbf24;
}

.text-xs {
  font-size: 11px;
}

.block {
  display: block;
}

/* DAG 拓扑图容器 */
.dag-container {
  display: flex;
  flex-direction: column;
  flex: 1;
}

.dag-canvas-wrapper {
  background: #0f172a;
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 8px;
  overflow: auto;
  position: relative;
  min-height: 240px;
  display: flex;
}

.dag-svg {
  display: block;
  user-select: none;
}

.dag-node-group {
  transition: transform 0.2s ease;
}

.dag-node-rect {
  filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.3));
  transition: all 0.2s;
}

.dag-node-group:hover .dag-node-rect {
  stroke: #38bdf8;
  fill: #1e293b;
  filter: drop-shadow(0 4px 8px rgba(56, 189, 248, 0.2));
}

.dag-edge {
  stroke-dasharray: 200;
  stroke-dashoffset: 200;
  animation: drawLine 1.5s forwards ease-in-out;
}

@keyframes drawLine {
  to {
    stroke-dashoffset: 0;
  }
}

.empty-dag {
  text-align: center;
  padding: 40px;
}

/* 版本历史时间线 */
.version-timeline {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 4px;
}

.version-timeline-item {
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.04);
  border-radius: 8px;
  padding: 12px 16px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 14px;
  transition: all 0.2s;
}

.version-timeline-item:hover {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.08);
}

.version-timeline-item.active {
  background: rgba(56, 189, 248, 0.06);
  border-color: rgba(56, 189, 248, 0.25);
}

.version-badge {
  background: rgba(148, 163, 184, 0.1);
  color: #e2e8f0;
  font-size: 12px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 6px;
  font-family: monospace;
}

.version-timeline-item.active .version-badge {
  background: rgba(56, 189, 248, 0.2);
  color: #38bdf8;
}

.version-timeline-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.version-info-line {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.v-date {
  font-size: 12px;
  color: #94a3b8;
}

.v-status {
  font-size: 10px;
  color: #10b981;
  font-weight: 600;
}

/* 快照查看器排版 */
.snapshot-layout {
  display: grid;
  grid-template-columns: 180px 1fr;
  gap: 16px;
  height: 400px;
  overflow: hidden;
}

@media (max-width: 600px) {
  .snapshot-layout {
    grid-template-columns: 1fr;
    height: auto;
  }
}

.snapshot-files {
  border-right: 1px solid rgba(255, 255, 255, 0.06);
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-right: 10px;
}

.file-item {
  font-size: 11px;
  padding: 6px 10px;
  border-radius: 4px;
  cursor: pointer;
  color: #94a3b8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: all 0.2s;
}

.file-item:hover {
  background: rgba(255, 255, 255, 0.03);
  color: #e2e8f0;
}

.file-item.active {
  background: rgba(56, 189, 248, 0.1);
  color: #38bdf8;
  font-weight: 600;
}

.snapshot-viewer {
  display: flex;
  flex-direction: column;
  background: #090d16;
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 8px;
  overflow: hidden;
}

.viewer-header {
  padding: 8px 16px;
  background: rgba(255, 255, 255, 0.02);
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.badge-gray {
  background: rgba(255, 255, 255, 0.05);
  color: #94a3b8;
}

.code-pre {
  margin: 0;
  padding: 12px;
  overflow: auto;
  flex: 1;
  font-size: 11px;
  line-height: 1.5;
}

.code-line {
  display: flex;
  font-family: inherit;
}

.line-num {
  width: 24px;
  text-align: right;
  color: #475569;
  user-select: none;
  margin-right: 12px;
  font-family: inherit;
}

.line-text {
  color: #94a3b8;
  white-space: pre;
  font-family: inherit;
}

.empty-viewer {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  font-size: 12px;
}

/* 模态弹窗 */
.modal-backdrop {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-dialog {
  width: 100%;
  max-width: 460px;
  margin: 20px;
  animation: modalIn 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

.modal-wide {
  max-width: 600px;
}

@keyframes modalIn {
  from {
    opacity: 0;
    transform: scale(0.95);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}

.modal-header {
  padding: 16px 24px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.modal-header h3 {
  color: #f1f5f9;
  font-size: 16px;
  font-weight: 600;
  margin: 0;
}

.modal-body {
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.modal-footer {
  padding: 16px 24px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

/* 表单输入控件 */
.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-label {
  color: #94a3b8;
  font-size: 12px;
  font-weight: 600;
}

.form-control {
  background: rgba(15, 23, 42, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 6px;
  color: #f8fafc;
  padding: 8px 12px;
  font-size: 13px;
  outline: none;
  transition: all 0.2s;
}

.form-control:focus {
  border-color: #38bdf8;
  box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.15);
}

.checkbox-group {
  margin-top: 8px;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  color: #e2e8f0;
  font-size: 13px;
}

.checkbox-label input[type="checkbox"] {
  width: 16px;
  height: 16px;
  cursor: pointer;
}

.help-text {
  color: #eab308;
  font-size: 11px;
}

/* 提示卡片 */
.alert {
  padding: 12px 16px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.6;
}

/* P5 模块样式 */
.p5-section-box {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.canary-control-card {
  padding: 20px;
  background: rgba(15, 23, 42, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
}

.canary-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: #e2e8f0;
  font-size: 14px;
}

.slider-wrapper {
  display: flex;
  align-items: center;
}

.slider {
  width: 100%;
  accent-color: #38bdf8;
}

.canary-actions {
  display: flex;
  align-items: center;
}

.alert-warning {
  background: rgba(234, 179, 8, 0.1);
  border: 1px solid rgba(234, 179, 8, 0.25);
  color: #fef08a;
}

/* 令牌明文框 */
.token-result-box {
  background: #090d16;
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 8px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  margin-top: 10px;
}

.token-plaintext {
  color: #38bdf8;
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 0.05em;
  word-break: break-all;
  text-align: center;
}

.btn-copy {
  background: rgba(56, 189, 248, 0.1);
  border-color: rgba(56, 189, 248, 0.3);
  color: #38bdf8;
  font-weight: 600;
  width: 100%;
  justify-content: center;
  padding: 8px;
}

.btn-copy:hover {
  background: rgba(56, 189, 248, 0.2);
}
</style>
