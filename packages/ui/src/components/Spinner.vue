<script setup lang="ts">
withDefaults(defineProps<{ size?: number }>(), { size: 18 });
</script>

<template>
  <span
    class="tw-spinner"
    :style="{ width: size + 'px', height: size + 'px' }"
    aria-label="loading"
  />
</template>

<style scoped>
.tw-spinner {
  display: inline-block;
  border: 2px solid var(--tw-border2, #3a424f);
  border-top-color: var(--tw-accent, #5b7cfa);
  border-radius: 50%;
  animation: tw-spin 0.7s linear infinite;
}
@keyframes tw-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
