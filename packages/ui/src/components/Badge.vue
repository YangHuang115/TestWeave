<script setup lang="ts">
withDefaults(
  defineProps<{
    tone?: "neutral" | "info" | "success" | "danger" | "warning";
  }>(),
  { tone: "neutral" },
);
</script>

<template>
  <span class="tw-badge" :class="`tw-badge--${tone}`">
    <slot />
  </span>
</template>

<style scoped>
.tw-badge {
  display: inline-block;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid var(--tw-border, #3a424f);
  background: var(--tw-surface2, #222834);
  color: var(--tw-muted, #9aa3b2);
  white-space: nowrap;
}
.tw-badge--info {
  background: rgba(56, 189, 248, 0.12);
  border-color: rgba(56, 189, 248, 0.3);
  color: #7dd3fc;
}
.tw-badge--success {
  background: rgba(34, 197, 94, 0.12);
  border-color: rgba(34, 197, 94, 0.3);
  color: #4ade80;
}
.tw-badge--danger {
  background: rgba(239, 68, 68, 0.12);
  border-color: rgba(239, 68, 68, 0.3);
  color: #fca5a5;
}
.tw-badge--warning {
  background: rgba(245, 158, 11, 0.12);
  border-color: rgba(245, 158, 11, 0.3);
  color: #fcd34d;
}
</style>
