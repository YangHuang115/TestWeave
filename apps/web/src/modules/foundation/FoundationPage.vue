<script setup lang="ts">
import { StatusPanel } from "@testweave/ui";
import { onMounted, ref } from "vue";

import { ApiError } from "../../shared/api/client";
import { getReadyHealth } from "../../shared/api/health";

type HealthState =
  | { phase: "loading" }
  | { phase: "ready" }
  | { phase: "error"; message: string; requestId: string | null };

const healthState = ref<HealthState>({ phase: "loading" });

async function loadHealth(): Promise<void> {
  healthState.value = { phase: "loading" };
  try {
    await getReadyHealth();
    healthState.value = { phase: "ready" };
  } catch (error) {
    if (error instanceof ApiError) {
      healthState.value = {
        phase: "error",
        message: error.message,
        requestId: error.requestId,
      };
      return;
    }
    healthState.value = {
      phase: "error",
      message: "页面暂时无法读取服务状态",
      requestId: null,
    };
  }
}

onMounted(loadHealth);
</script>

<template>
  <main class="foundation-page">
    <section class="foundation-hero" aria-labelledby="foundation-title">
      <p class="foundation-kicker">M00 · P0 工程基线</p>
      <h1 id="foundation-title">TestWeave</h1>
      <p class="foundation-summary">AI 原生测试设计与测试资产管理平台</p>
    </section>

    <StatusPanel
      v-if="healthState.phase === 'loading'"
      title="正在连接服务端"
      message="正在读取真实健康检查，请稍候。"
      tone="loading"
    />
    <StatusPanel
      v-else-if="healthState.phase === 'ready'"
      title="服务端连接正常"
      message="数据库与迁移状态正常，平台工程基线已经就绪；登录与项目工作区将在后续纵向切片接入。"
      tone="success"
    />
    <StatusPanel
      v-else
      title="暂时无法连接服务端"
      :message="healthState.message"
      :request-id="healthState.requestId"
      tone="error"
    >
      <button class="retry-button" type="button" @click="loadHealth">重新检查</button>
    </StatusPanel>
  </main>
</template>

<style scoped>
.foundation-page {
  display: grid;
  width: min(100% - 2rem, 72rem);
  min-height: 100vh;
  margin: 0 auto;
  align-content: center;
  gap: 2rem;
  padding: 3rem 0;
}

.foundation-hero {
  max-width: 46rem;
}

.foundation-kicker {
  margin: 0 0 0.75rem;
  color: var(--tw-color-accent-strong);
  font-size: 0.8rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

h1 {
  margin: 0;
  font-size: clamp(2.8rem, 7vw, 5.5rem);
  letter-spacing: -0.06em;
  line-height: 0.95;
}

.foundation-summary {
  margin: 1.25rem 0 0;
  color: var(--tw-color-text-muted);
  font-size: clamp(1rem, 2vw, 1.35rem);
}

.retry-button {
  border: 1px solid currentColor;
  border-radius: 0.5rem;
  padding: 0.55rem 0.9rem;
  color: inherit;
  background: transparent;
  font: inherit;
  font-weight: 650;
  cursor: pointer;
}

.retry-button:focus-visible {
  outline: 3px solid var(--tw-color-focus);
  outline-offset: 3px;
}
</style>
