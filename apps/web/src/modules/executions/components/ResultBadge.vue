<script setup lang="ts">
import { computed } from "vue";
import { Badge } from "@testweave/ui";
import { RESULT_LABEL, RESULT_TONE, normalizeResult } from "../result";
import type { ExecutionResult } from "../types";

const props = defineProps<{ result: ExecutionResult | null }>();
const r = computed(() => normalizeResult(props.result));
</script>

<template>
  <Badge :tone="RESULT_TONE[r]">{{ RESULT_LABEL[r] }}</Badge>
</template>
