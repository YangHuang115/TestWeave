<template>
  <div class="device-monitor-page">
    <header class="page-header">
      <div>
        <div class="title-row">
          <h2>设备监看</h2>
          <span class="readonly-badge">只读</span>
        </div>
        <p class="subtitle">持续查看本机 Android 设备最新画面，Agent 操作后无需手动刷新</p>
      </div>
      <div class="scope-note">本机设备 · 所有项目共享</div>
    </header>

    <div v-if="listLoading" class="state-card" role="status" aria-live="polite">
      <div class="state-icon">⟳</div>
      <h3>正在读取本机设备</h3>
      <p>正在连接本机 Android MCP，请稍候。</p>
    </div>

    <div v-else-if="listError" class="state-card error-state" role="alert">
      <div class="state-icon">!</div>
      <h3>{{ listError.message }}</h3>
      <p v-if="listError.code === 'ANDROID_MCP_DISABLED'">请先配置独立 Android MCP 运行时。</p>
      <p v-else>设备列表暂时不可用，请稍后重试。</p>
      <p v-if="listError.requestId" class="request-id">请求编号：{{ listError.requestId }}</p>
      <button v-if="listError.retryable" class="secondary-button" type="button" @click="retryList">
        重试读取
      </button>
    </div>

    <div v-else-if="devices.length === 0" class="state-card empty-state" role="status">
      <div class="state-icon">⌁</div>
      <h3>暂无本机 Android 设备</h3>
      <p>连接设备或启动模拟器后，再回来刷新设备列表。</p>
      <button class="secondary-button" type="button" @click="retryList">重新读取</button>
    </div>

    <div v-else class="monitor-grid">
      <aside class="device-list-card" aria-label="本机 Android 设备列表">
        <div class="card-heading">
          <div>
            <h3>设备列表</h3>
            <p>{{ devices.length }} 台本机设备</p>
          </div>
          <span class="list-hint">只读观察</span>
        </div>

        <div class="device-list" role="listbox" aria-label="选择设备">
          <button
            v-for="device in devices"
            :key="device.deviceRef"
            class="device-item"
            :class="{ selected: device.deviceRef === selectedDeviceRef }"
            type="button"
            role="option"
            :aria-selected="device.deviceRef === selectedDeviceRef"
            @click="selectDevice(device)"
          >
            <span class="status-dot" :class="statusClass(device.state)" aria-hidden="true"></span>
            <span class="device-copy">
              <strong>{{ device.displayName }}</strong>
              <span
                >{{ stateLabel(device.state)
                }}<template v-if="device.model"> · {{ device.model }}</template></span
              >
              <small v-if="device.infoError">{{ device.infoError }}</small>
            </span>
            <span
              v-if="device.deviceRef === selectedDeviceRef"
              class="selected-mark"
              aria-hidden="true"
              >✓</span
            >
          </button>
        </div>

        <div class="readonly-help">
          <strong>只读范围</strong>
          <p>设备列表、设备信息、最新画面</p>
          <p>不包含点击、输入、安装或 Shell 操作</p>
        </div>
      </aside>

      <section class="screen-card" aria-label="设备当前画面">
        <template v-if="selectedDevice">
          <div class="card-heading screen-heading">
            <div class="screen-heading-copy">
              <div class="screen-title-row">
                <h3>{{ selectedDevice.displayName }}</h3>
                <span
                  class="stream-status-pill"
                  :class="`stream-${streamState}`"
                  role="status"
                  aria-live="polite"
                >
                  <span class="stream-status-dot" aria-hidden="true"></span>
                  {{ streamStatusText }}
                </span>
              </div>
              <p>
                {{ stateLabel(selectedDevice.state)
                }}<template v-if="selectedDevice.model"> · {{ selectedDevice.model }}</template>
              </p>
            </div>
            <div class="screen-actions">
              <button
                v-if="canToggleStream"
                class="primary-button stream-toggle-button"
                type="button"
                @click="toggleStream"
              >
                {{ userPaused ? "恢复实时" : "暂停实时" }}
              </button>
              <button
                class="secondary-button single-frame-button"
                type="button"
                :disabled="screenLoading || !isOnline(selectedDevice)"
                @click="refreshScreen"
              >
                {{ screenLoading ? "正在获取…" : "获取单帧" }}
              </button>
            </div>
          </div>

          <div class="stream-notice" :class="`stream-notice-${streamState}`">
            <strong>{{ streamNoticeTitle }}</strong>
            <span>{{ streamNoticeDetail }}</span>
          </div>

          <div v-if="screenUrl" class="screen-preview" :class="{ refreshing: screenLoading }">
            <img :src="screenUrl" :alt="screenAlt" />
            <div v-if="screenLoading" class="refresh-overlay" role="status">
              正在获取一帧新画面…
            </div>
          </div>
          <div v-else-if="screenLoading" class="screen-placeholder" role="status">
            <div class="placeholder-icon">◌</div>
            <p>正在获取设备当前画面…</p>
          </div>
          <div v-else class="screen-placeholder unavailable-screen" role="status">
            <div class="placeholder-icon">▧</div>
            <p>{{ screenPlaceholderTitle }}</p>
            <span>{{ screenPlaceholderDetail }}</span>
          </div>

          <div v-if="streamFailure" class="screen-error stream-error" role="alert">
            <div>
              <strong>{{ streamFailure.message }}</strong>
              <span v-if="screenUrl" class="stale-label">最后成功画面仍保留，但不标记为实时</span>
            </div>
            <button
              v-if="streamFailure.retryable && isOnline(selectedDevice)"
              class="link-button"
              type="button"
              @click="retryStream"
            >
              重试实时
            </button>
          </div>

          <div v-if="screenError" class="screen-error" role="alert">
            <div>
              <strong>{{ screenError.message }}</strong>
              <span v-if="screenUrl" class="stale-label">最后成功画面仍保留</span>
              <span v-if="screenError.requestId" class="request-id"
                >请求编号：{{ screenError.requestId }}</span
              >
            </div>
            <button
              v-if="screenError.retryable && isOnline(selectedDevice)"
              class="link-button"
              type="button"
              :disabled="screenLoading"
              @click="refreshScreen"
            >
              重试
            </button>
          </div>

          <div class="screen-meta">
            <span v-if="capturedAt">最后成功画面 · {{ formatCapturedAt(capturedAt) }}</span>
            <span v-else>尚未获取成功画面</span>
            <span>{{ screenMetaText }}</span>
          </div>
        </template>

        <div v-else class="screen-placeholder no-selection" role="status">
          <div class="placeholder-icon">⌖</div>
          <p>选择一台在线设备查看当前画面</p>
          <span>页面不会自动控制设备</span>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { ApiError } from "@/shared/api/client";
import {
  androidDevicesApi,
  isAndroidRequestCancelled,
  type AndroidDevice,
} from "./androidDevicesApi";
import {
  createAndroidDeviceStream,
  type AndroidDeviceStreamController,
  type AndroidStreamFailure,
  type AndroidStreamState,
  type AndroidStreamStatus,
} from "./androidDeviceStream";

interface DisplayError {
  code: string;
  message: string;
  requestId: string;
  retryable: boolean;
}

type StreamViewState = AndroidStreamState | "idle";

const props = defineProps<{ projectId?: string }>();
const projectId = computed(() => props.projectId ?? "");

const devices = ref<AndroidDevice[]>([]);
const listLoading = ref(false);
const listError = ref<DisplayError | null>(null);
const selectedDeviceRef = ref<string | null>(null);
const screenUrl = ref<string | null>(null);
const capturedAt = ref<string | null>(null);
const screenLoading = ref(false);
const screenError = ref<DisplayError | null>(null);
const streamState = ref<StreamViewState>("idle");
const streamFailure = ref<AndroidStreamFailure | null>(null);
const effectiveFps = ref<number | null>(null);
const userPaused = ref(false);

const selectedDevice = computed(
  () => devices.value.find((device) => device.deviceRef === selectedDeviceRef.value) ?? null,
);
const screenAlt = computed(() =>
  selectedDevice.value ? `${selectedDevice.value.displayName} 的当前设备画面` : "设备当前画面",
);
const streamStatusText = computed(() => {
  if (streamState.value === "live") {
    return effectiveFps.value === null ? "实时" : `实时 · ${effectiveFps.value.toFixed(1)} FPS`;
  }
  if (streamState.value === "connecting") return "连接中";
  if (streamState.value === "reconnecting") return "重连中";
  if (streamState.value === "paused") return "已暂停";
  if (streamState.value === "offline") return "设备离线";
  if (streamState.value === "disabled") return "实时未启用";
  if (streamState.value === "error") return "连接错误";
  return "未连接";
});
const canToggleStream = computed(
  () =>
    selectedDevice.value !== null &&
    isOnline(selectedDevice.value) &&
    !["disabled", "error", "offline", "idle"].includes(streamState.value),
);
const streamNoticeTitle = computed(() => {
  if (streamState.value === "live") return "准实时只读画面";
  if (streamState.value === "connecting") return "正在建立实时连接";
  if (streamState.value === "reconnecting") return "实时连接正在恢复";
  if (streamState.value === "paused") return "实时订阅已暂停";
  if (streamState.value === "offline") return "设备当前离线";
  if (streamState.value === "disabled") return "实时监看未启用";
  if (streamState.value === "error") return "实时连接不可用";
  return "尚未建立实时连接";
});
const streamNoticeDetail = computed(() => {
  if (streamState.value === "live") return "画面持续更新；不录屏、不保存历史帧";
  if (streamState.value === "connecting") return "连接成功后会自动展示 Agent 操作结果";
  if (streamState.value === "reconnecting") return "保留最后成功画面，恢复前不标记为实时";
  if (streamState.value === "paused") return "点击“恢复实时”后继续接收最新画面";
  if (streamState.value === "offline") return "设备恢复在线后可重新建立连接";
  if (streamState.value === "disabled") return "当前仍可使用“获取单帧”查看设备";
  if (streamState.value === "error") return "可重试实时连接，或继续使用单帧模式";
  return "选择一台在线设备后自动连接";
});
const screenPlaceholderTitle = computed(() => {
  if (!selectedDevice.value || !isOnline(selectedDevice.value)) return "设备当前不可用";
  if (streamState.value === "disabled" || streamState.value === "error") {
    return "实时画面暂不可用";
  }
  return "正在等待设备画面";
});
const screenPlaceholderDetail = computed(() => {
  if (!selectedDevice.value || !isOnline(selectedDevice.value)) return "设备在线后才能抓取画面";
  if (streamState.value === "disabled" || streamState.value === "error") {
    return "点击“获取单帧”查看一张只读快照";
  }
  return "实时连接建立后会自动显示最新画面";
});
const screenMetaText = computed(() => {
  if (streamState.value === "live") {
    return effectiveFps.value === null
      ? "画面持续更新"
      : `画面持续更新 · ${effectiveFps.value.toFixed(1)} FPS`;
  }
  if (streamState.value === "paused") return "实时订阅已暂停";
  if (streamState.value === "disabled" || streamState.value === "error") return "当前为单帧模式";
  return streamStatusText.value;
});

let mounted = true;
let listRequest: AbortController | null = null;
let screenRequest: AbortController | null = null;
let streamController: AndroidDeviceStreamController | null = null;
let listSequence = 0;
let screenSequence = 0;
let streamSequence = 0;

function toDisplayError(error: unknown, fallback: string): DisplayError {
  if (error instanceof ApiError) {
    return {
      code: error.code,
      message: error.message,
      requestId: error.requestId,
      retryable: error.retryable,
    };
  }
  return { code: "NETWORK_ERROR", message: fallback, requestId: "", retryable: true };
}

function isOnline(device: AndroidDevice): boolean {
  return device.state === "online";
}

function stateLabel(state: string): string {
  if (state === "online") return "在线";
  if (state === "offline") return "离线";
  if (state === "unauthorized") return "未授权";
  return "状态未知";
}

function statusClass(state: string): string {
  if (state === "online") return "status-online";
  if (state === "unauthorized") return "status-unauthorized";
  if (state === "offline") return "status-offline";
  return "status-unknown";
}

function formatCapturedAt(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

function releaseScreenUrl(): void {
  if (screenUrl.value) {
    URL.revokeObjectURL(screenUrl.value);
    screenUrl.value = null;
  }
}

function cancelScreenRequest(): void {
  screenSequence += 1;
  screenRequest?.abort();
  screenRequest = null;
  screenLoading.value = false;
}

function cancelListRequest(): void {
  listSequence += 1;
  listRequest?.abort();
  listRequest = null;
  listLoading.value = false;
}

function clearScreen(): void {
  cancelScreenRequest();
  releaseScreenUrl();
  capturedAt.value = null;
  screenError.value = null;
}

function stopStream(nextState: StreamViewState = "idle"): void {
  streamSequence += 1;
  streamController?.stop();
  streamController = null;
  streamState.value = nextState;
  effectiveFps.value = null;
}

function startStream(deviceRef: string): void {
  if (!mounted || !projectId.value || document.visibilityState !== "visible") return;
  const device = devices.value.find((item) => item.deviceRef === deviceRef);
  if (!device || !isOnline(device)) {
    stopStream("offline");
    return;
  }

  stopStream("connecting");
  streamFailure.value = null;
  effectiveFps.value = null;
  const sequence = streamSequence;
  const targetProjectId = projectId.value;

  const controller = createAndroidDeviceStream({
    projectId: targetProjectId,
    deviceRef,
    onStatus: (status: AndroidStreamStatus) => {
      if (
        !mounted ||
        sequence !== streamSequence ||
        selectedDeviceRef.value !== deviceRef ||
        projectId.value !== targetProjectId
      ) {
        return;
      }
      streamState.value = status.state;
      effectiveFps.value = status.effectiveFps;
      if (status.state === "live") {
        streamFailure.value = null;
      }
    },
    onFrame: (frame) => {
      if (
        !mounted ||
        sequence !== streamSequence ||
        selectedDeviceRef.value !== deviceRef ||
        projectId.value !== targetProjectId
      ) {
        return;
      }
      cancelScreenRequest();
      const nextUrl = URL.createObjectURL(frame.blob);
      releaseScreenUrl();
      screenUrl.value = nextUrl;
      capturedAt.value = frame.capturedAt;
      effectiveFps.value = frame.effectiveFps;
      streamState.value = "live";
      streamFailure.value = null;
      screenError.value = null;
    },
    onFailure: (failure) => {
      if (
        !mounted ||
        sequence !== streamSequence ||
        selectedDeviceRef.value !== deviceRef ||
        projectId.value !== targetProjectId
      ) {
        return;
      }
      streamFailure.value = failure;
    },
  });
  streamController = controller;
  controller.start();
}

async function loadDevices(autoSelect: boolean): Promise<void> {
  if (!projectId.value || !mounted) return;
  listRequest?.abort();
  const request = new AbortController();
  listRequest = request;
  const sequence = ++listSequence;
  listLoading.value = true;
  listError.value = null;
  try {
    const response = await androidDevicesApi.list(projectId.value, request.signal);
    if (!mounted || sequence !== listSequence) return;
    devices.value = response.items;
    const currentSelection = selectedDeviceRef.value
      ? response.items.find((device) => device.deviceRef === selectedDeviceRef.value)
      : null;
    if (selectedDeviceRef.value && !currentSelection) {
      selectedDeviceRef.value = null;
      userPaused.value = false;
      stopStream("idle");
      clearScreen();
    }
    if (autoSelect && !selectedDeviceRef.value) {
      const firstOnline = response.items.find((device) => isOnline(device));
      if (firstOnline) {
        selectedDeviceRef.value = firstOnline.deviceRef;
      }
    }
    const activeDevice = selectedDeviceRef.value
      ? response.items.find((device) => device.deviceRef === selectedDeviceRef.value)
      : null;
    if (activeDevice && isOnline(activeDevice) && document.visibilityState === "visible") {
      if (!screenUrl.value) {
        void captureScreen(activeDevice.deviceRef);
      }
      if (!userPaused.value) {
        startStream(activeDevice.deviceRef);
      }
    } else if (activeDevice) {
      stopStream("offline");
    } else {
      stopStream("idle");
    }
  } catch (error) {
    if (isAndroidRequestCancelled(error) || !mounted || sequence !== listSequence) return;
    stopStream("error");
    listError.value = toDisplayError(error, "无法读取本机设备，请稍后重试");
  } finally {
    if (sequence === listSequence) {
      listLoading.value = false;
    }
  }
}

async function captureScreen(deviceRef: string): Promise<void> {
  if (!mounted || document.visibilityState !== "visible" || screenLoading.value) return;
  const device = devices.value.find((item) => item.deviceRef === deviceRef);
  if (!device || !isOnline(device)) {
    screenError.value = {
      code: "ANDROID_DEVICE_UNAVAILABLE",
      message: "设备当前离线或未授权，无法抓取画面",
      requestId: "",
      retryable: true,
    };
    return;
  }
  cancelScreenRequest();
  const request = new AbortController();
  screenRequest = request;
  const sequence = ++screenSequence;
  screenLoading.value = true;
  screenError.value = null;
  try {
    const response = await androidDevicesApi.getScreen(projectId.value, deviceRef, request.signal);
    if (!mounted || sequence !== screenSequence || selectedDeviceRef.value !== deviceRef) {
      return;
    }
    const nextUrl = URL.createObjectURL(response.blob);
    releaseScreenUrl();
    screenUrl.value = nextUrl;
    capturedAt.value = response.capturedAt ?? new Date().toISOString();
  } catch (error) {
    if (isAndroidRequestCancelled(error) || !mounted || sequence !== screenSequence) return;
    screenError.value = toDisplayError(error, "无法获取设备当前画面，请重试");
  } finally {
    if (sequence === screenSequence) {
      screenLoading.value = false;
      screenRequest = null;
    }
  }
}

function selectDevice(device: AndroidDevice): void {
  if (selectedDeviceRef.value === device.deviceRef) return;
  stopStream("idle");
  selectedDeviceRef.value = device.deviceRef;
  userPaused.value = false;
  streamFailure.value = null;
  clearScreen();
  if (isOnline(device) && document.visibilityState === "visible") {
    void captureScreen(device.deviceRef);
    startStream(device.deviceRef);
  } else {
    streamState.value = "offline";
  }
}

function refreshScreen(): void {
  if (selectedDeviceRef.value) {
    void captureScreen(selectedDeviceRef.value);
  }
}

function toggleStream(): void {
  if (!selectedDeviceRef.value) return;
  if (userPaused.value) {
    userPaused.value = false;
    streamFailure.value = null;
    if (streamController) {
      streamController.resume();
    } else {
      startStream(selectedDeviceRef.value);
    }
    return;
  }
  userPaused.value = true;
  streamController?.pause();
  streamState.value = "paused";
  effectiveFps.value = null;
}

function retryStream(): void {
  if (!selectedDeviceRef.value || document.visibilityState !== "visible") return;
  userPaused.value = false;
  streamFailure.value = null;
  startStream(selectedDeviceRef.value);
}

function retryList(): void {
  void loadDevices(selectedDeviceRef.value === null);
}

function handleVisibilityChange(): void {
  if (document.visibilityState !== "visible") {
    cancelListRequest();
    cancelScreenRequest();
    stopStream(userPaused.value ? "paused" : "idle");
    return;
  }
  if (selectedDeviceRef.value && !userPaused.value) {
    startStream(selectedDeviceRef.value);
  }
}

watch(
  projectId,
  (value, previous) => {
    if (!value) return;
    stopStream("idle");
    userPaused.value = false;
    streamFailure.value = null;
    clearScreen();
    // 项目切换后必须使用新的项目 ID 重新读取列表并建立实时连接。
    void loadDevices(previous === undefined);
  },
  { immediate: true },
);

onMounted(() => {
  document.addEventListener("visibilitychange", handleVisibilityChange);
});

onUnmounted(() => {
  mounted = false;
  cancelListRequest();
  cancelScreenRequest();
  stopStream("idle");
  releaseScreenUrl();
  document.removeEventListener("visibilitychange", handleVisibilityChange);
});
</script>

<style scoped>
.device-monitor-page {
  min-height: 100%;
  color: #d9e4f2;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 24px;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

h2,
h3,
p {
  margin: 0;
}

h2 {
  color: #f4f8ff;
  font-size: 24px;
}

h3 {
  color: #eef4ff;
  font-size: 16px;
}

.subtitle,
.card-heading p,
.device-copy span,
.device-copy small,
.screen-meta,
.screen-placeholder span,
.readonly-help p {
  color: #8fa3bd;
  font-size: 13px;
}

.subtitle {
  margin-top: 8px;
}

.readonly-badge,
.list-hint {
  border: 1px solid rgba(111, 157, 226, 0.38);
  border-radius: 999px;
  color: #8fc1ff;
  font-size: 12px;
  padding: 3px 9px;
}

.scope-note {
  border: 1px solid rgba(147, 173, 206, 0.22);
  border-radius: 9px;
  color: #a9bad1;
  font-size: 13px;
  padding: 10px 13px;
}

.state-card,
.device-list-card,
.screen-card {
  background: rgba(17, 29, 49, 0.86);
  border: 1px solid rgba(157, 183, 220, 0.14);
  border-radius: 14px;
  box-shadow: 0 12px 35px rgba(0, 0, 0, 0.18);
}

.state-card {
  align-items: center;
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-height: 360px;
  padding: 24px;
  text-align: center;
}

.state-card h3 {
  margin-top: 14px;
}

.state-card p {
  color: #93a8c2;
  font-size: 14px;
  margin-top: 8px;
}

.state-icon,
.placeholder-icon {
  align-items: center;
  background: rgba(79, 135, 220, 0.13);
  border-radius: 50%;
  color: #83b6f5;
  display: flex;
  font-size: 25px;
  height: 56px;
  justify-content: center;
  width: 56px;
}

.error-state .state-icon {
  background: rgba(228, 106, 106, 0.14);
  color: #ff9e9e;
}

.empty-state .state-icon {
  background: rgba(220, 170, 81, 0.13);
  color: #f0c774;
}

.request-id {
  color: #6f87a5 !important;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px !important;
}

.monitor-grid {
  display: grid;
  gap: 20px;
  grid-template-columns: minmax(260px, 330px) minmax(0, 1fr);
}

.device-list-card,
.screen-card {
  min-height: 620px;
  padding: 20px;
}

.card-heading {
  align-items: flex-start;
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.card-heading p {
  margin-top: 5px;
}

.device-list {
  display: flex;
  flex-direction: column;
  gap: 9px;
  margin-top: 22px;
}

.device-item {
  align-items: flex-start;
  background: rgba(9, 20, 37, 0.54);
  border: 1px solid transparent;
  border-radius: 11px;
  color: inherit;
  cursor: pointer;
  display: flex;
  gap: 10px;
  padding: 13px 12px;
  text-align: left;
  transition:
    border-color 0.18s ease,
    background 0.18s ease;
  width: 100%;
}

.device-item:hover,
.device-item:focus-visible {
  border-color: rgba(103, 161, 244, 0.5);
  outline: none;
}

.device-item.selected {
  background: rgba(57, 117, 210, 0.2);
  border-color: #4e8be4;
}

.status-dot {
  border-radius: 50%;
  flex: 0 0 auto;
  height: 9px;
  margin-top: 5px;
  width: 9px;
}

.status-online {
  background: #35ce8a;
}

.status-unauthorized {
  background: #e8ac4e;
}

.status-offline,
.status-unknown {
  background: #7a8ba4;
}

.device-copy {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.device-copy strong {
  color: #eaf2ff;
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.device-copy small {
  color: #d9ae66;
  font-size: 11px;
}

.selected-mark {
  color: #8fc1ff;
  font-size: 15px;
}

.readonly-help {
  border-top: 1px solid rgba(157, 183, 220, 0.12);
  margin-top: 26px;
  padding-top: 18px;
}

.readonly-help strong {
  color: #b9cbe2;
  font-size: 12px;
}

.readonly-help p {
  line-height: 1.6;
  margin-top: 5px;
}

.screen-heading {
  align-items: center;
}

.screen-heading-copy {
  min-width: 0;
}

.screen-title-row {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 9px;
}

.screen-actions {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 9px;
  justify-content: flex-end;
}

.stream-status-pill {
  align-items: center;
  border: 1px solid rgba(142, 164, 194, 0.3);
  border-radius: 999px;
  color: #a9bad1;
  display: inline-flex;
  font-size: 11px;
  font-weight: 600;
  gap: 6px;
  padding: 3px 8px;
}

.stream-status-dot {
  background: currentcolor;
  border-radius: 50%;
  height: 6px;
  width: 6px;
}

.stream-live {
  background: rgba(53, 206, 138, 0.1);
  border-color: rgba(53, 206, 138, 0.3);
  color: #6ee7b7;
}

.stream-connecting {
  background: rgba(56, 189, 248, 0.1);
  border-color: rgba(56, 189, 248, 0.3);
  color: #7dd3fc;
}

.stream-reconnecting,
.stream-disabled {
  background: rgba(232, 172, 78, 0.1);
  border-color: rgba(232, 172, 78, 0.3);
  color: #f2c879;
}

.stream-error {
  background: rgba(228, 106, 106, 0.1);
  border-color: rgba(228, 106, 106, 0.3);
  color: #ffaaaa;
}

.stream-paused,
.stream-offline,
.stream-idle {
  color: #94a3b8;
}

.primary-button,
.secondary-button,
.link-button {
  border: 0;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  transition:
    opacity 0.18s ease,
    transform 0.18s ease;
}

.primary-button {
  background: #3c7fe0;
  color: #fff;
  padding: 10px 13px;
}

.secondary-button {
  background: rgba(75, 130, 218, 0.2);
  color: #9ec8ff;
  margin-top: 18px;
  padding: 10px 15px;
}

.screen-actions .secondary-button {
  margin-top: 0;
}

.link-button {
  background: transparent;
  color: #9ec8ff;
  padding: 5px 0;
}

.primary-button:hover:not(:disabled),
.secondary-button:hover,
.link-button:hover:not(:disabled) {
  opacity: 0.82;
}

.primary-button:disabled,
.secondary-button:disabled,
.link-button:disabled {
  cursor: not-allowed;
  opacity: 0.48;
}

.stream-notice {
  align-items: center;
  background: rgba(31, 104, 151, 0.12);
  border: 1px solid rgba(75, 146, 194, 0.22);
  border-radius: 9px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  margin-top: 18px;
  padding: 10px 12px;
}

.stream-notice strong {
  color: #c9eaff;
  font-size: 13px;
}

.stream-notice span {
  color: #8fa9c7;
  font-size: 12px;
}

.stream-notice-live {
  background: rgba(31, 135, 99, 0.12);
  border-color: rgba(53, 206, 138, 0.22);
}

.stream-notice-live strong {
  color: #b6f2dc;
}

.stream-notice-reconnecting,
.stream-notice-disabled {
  background: rgba(159, 112, 35, 0.13);
  border-color: rgba(232, 172, 78, 0.24);
}

.stream-notice-reconnecting strong,
.stream-notice-disabled strong {
  color: #f2cf8c;
}

.stream-notice-error {
  background: rgba(151, 61, 73, 0.13);
  border-color: rgba(228, 106, 106, 0.24);
}

.stream-notice-error strong {
  color: #ffb4b4;
}

.screen-preview,
.screen-placeholder {
  align-items: center;
  background: #081321;
  border: 1px solid rgba(157, 183, 220, 0.12);
  border-radius: 11px;
  display: flex;
  justify-content: center;
  margin-top: 14px;
  min-height: 470px;
  overflow: hidden;
  position: relative;
}

.screen-preview img {
  display: block;
  height: auto;
  max-height: 620px;
  max-width: 100%;
  object-fit: contain;
}

.screen-preview.refreshing img {
  opacity: 0.58;
}

.refresh-overlay {
  background: rgba(5, 13, 25, 0.78);
  border-radius: 999px;
  color: #d8e8ff;
  font-size: 13px;
  left: 50%;
  padding: 9px 14px;
  position: absolute;
  top: 50%;
  transform: translate(-50%, -50%);
}

.screen-placeholder {
  flex-direction: column;
  gap: 10px;
  padding: 24px;
  text-align: center;
}

.screen-placeholder p {
  color: #d4e0ef;
  font-size: 15px;
}

.unavailable-screen .placeholder-icon {
  background: rgba(218, 171, 82, 0.13);
  color: #edbf6c;
}

.screen-error {
  align-items: center;
  background: rgba(188, 73, 73, 0.13);
  border: 1px solid rgba(222, 105, 105, 0.25);
  border-radius: 9px;
  color: #ffb4b4;
  display: flex;
  font-size: 13px;
  justify-content: space-between;
  margin-top: 14px;
  padding: 10px 12px;
}

.screen-error.stream-error {
  color: #ffb4b4;
}

.screen-error > div {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stale-label {
  color: #f4cf8c;
  font-size: 12px;
}

.screen-meta {
  display: flex;
  justify-content: space-between;
  margin-top: 13px;
}

.no-selection {
  height: calc(100% - 20px);
  margin-top: 0;
  min-height: 570px;
}

@media (max-width: 980px) {
  .monitor-grid {
    grid-template-columns: 1fr;
  }

  .device-list-card,
  .screen-card {
    min-height: auto;
  }

  .device-list {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  }
}

@media (max-width: 620px) {
  .page-header,
  .screen-heading,
  .screen-actions,
  .screen-meta {
    align-items: flex-start;
    flex-direction: column;
  }

  .scope-note {
    width: 100%;
  }
}
</style>
