<script setup lang="ts">
defineProps<{
  content: string
  placement?: "top" | "top-start" | "top-end" | "bottom" | "bottom-start" | "bottom-end"
}>()
</script>

<template>
  <el-tooltip
    :content="content"
    :placement="placement || 'top'"
    effect="dark"
    :show-after="180"
  >
    <sup class="info-tip" aria-label="说明" tabindex="0">i</sup>
  </el-tooltip>
</template>

<style scoped>
.info-tip {
  display: inline-grid;
  width: 16px;
  height: 16px;
  margin-left: 5px;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color);
  border-radius: 50%;
  cursor: help;
  font-family: Georgia, serif;
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
  place-items: center;
  vertical-align: super;
}

.info-tip:hover,
.info-tip:focus-visible {
  color: var(--el-color-primary);
  border-color: var(--el-color-primary-light-5);
  outline: none;
}
</style>
