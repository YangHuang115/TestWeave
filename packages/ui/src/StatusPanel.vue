<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  title: string;
  message: string;
  tone: "loading" | "success" | "error";
  requestId?: string | null;
}>();

const accessibleRole = computed(() => (props.tone === "error" ? "alert" : "status"));
</script>

<template>
  <section
    class="tw-status-panel"
    :class="`tw-status-panel--${tone}`"
    :role="accessibleRole"
    :aria-live="tone === 'error' ? 'assertive' : 'polite'"
  >
    <span class="tw-status-panel__marker" aria-hidden="true"></span>
    <div>
      <h2>{{ title }}</h2>
      <p>{{ message }}</p>
      <p v-if="requestId" class="tw-status-panel__request-id">
        请求编号：<code>{{ requestId }}</code>
      </p>
      <div v-if="$slots.default" class="tw-status-panel__actions">
        <slot />
      </div>
    </div>
  </section>
</template>
