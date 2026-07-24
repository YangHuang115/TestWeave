<script setup lang="ts">
withDefaults(
  defineProps<{
    variant?: "primary" | "default" | "ghost" | "danger";
    size?: "sm" | "md";
    disabled?: boolean;
    type?: "button" | "submit";
  }>(),
  { variant: "default", size: "md", disabled: false, type: "button" },
);
</script>

<template>
  <button
    :type="type"
    :disabled="disabled"
    class="tw-btn"
    :class="[`tw-btn--${variant}`, `tw-btn--${size}`]"
  >
    <slot />
  </button>
</template>

<style scoped>
.tw-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border-radius: 8px;
  border: 1px solid var(--tw-border, #3a424f);
  background: var(--tw-surface2, #222834);
  color: var(--tw-text, #e6e8ec);
  cursor: pointer;
  font-family: inherit;
  transition: background 0.12s ease, border-color 0.12s ease;
}
.tw-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.tw-btn--md {
  padding: 6px 12px;
  font-size: 12.5px;
}
.tw-btn--sm {
  padding: 4px 9px;
  font-size: 12px;
}
.tw-btn--primary {
  background: var(--tw-accent, #5b7cfa);
  border-color: var(--tw-accent-d, #3f5fd6);
  color: #fff;
}
.tw-btn--ghost {
  background: transparent;
}
.tw-btn--danger {
  background: rgba(239, 68, 68, 0.15);
  border-color: rgba(239, 68, 68, 0.4);
  color: #fca5a5;
}
.tw-btn:not(:disabled):hover {
  border-color: var(--tw-accent, #5b7cfa);
}
</style>
