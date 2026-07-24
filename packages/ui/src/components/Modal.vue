<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    title?: string;
    width?: number;
    closeOnMask?: boolean;
  }>(),
  { title: "", width: 460, closeOnMask: true },
);
const emit = defineEmits<{ (e: "close"): void }>();

function onMask() {
  if (props.closeOnMask) emit("close");
}
</script>

<template>
  <div class="tw-modal-mask" @click.self="onMask">
    <div class="tw-modal" :style="{ width: width + 'px' }">
      <header v-if="title || $slots.header" class="tw-modal__head">
        <slot name="header">
          <h3>{{ title }}</h3>
        </slot>
      </header>
      <div class="tw-modal__body">
        <slot />
      </div>
      <footer v-if="$slots.footer" class="tw-modal__foot">
        <slot name="footer" />
      </footer>
    </div>
  </div>
</template>

<style scoped>
.tw-modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.tw-modal {
  background: var(--tw-panel, #161a21);
  border: 1px solid var(--tw-border2, #3a424f);
  border-radius: 14px;
  padding: 20px;
  max-width: calc(100vw - 32px);
  max-height: calc(100vh - 64px);
  overflow: auto;
}
.tw-modal__head h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 500;
  color: var(--tw-text, #e6e8ec);
}
.tw-modal__body {
  color: var(--tw-text, #e6e8ec);
}
.tw-modal__foot {
  display: flex;
  justify-content: flex-end;
  gap: 9px;
  margin-top: 18px;
}
</style>
