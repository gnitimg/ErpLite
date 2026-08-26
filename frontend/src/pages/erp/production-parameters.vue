<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import ProductionCalendar from "./production-calendar.vue"
import ProductionSettings from "./production-settings.vue"

type ProductionTab = "basic" | "calendar"

const route = useRoute()
const router = useRouter()
const activeTab = ref<ProductionTab>(route.query.tab === "calendar" ? "calendar" : "basic")
const activeComponent = computed(() => activeTab.value === "calendar" ? ProductionCalendar : ProductionSettings)

function selectTab(value: string | number) {
  const tab: ProductionTab = value === "calendar" ? "calendar" : "basic"
  router.replace({ query: { ...route.query, tab } })
}

watch(() => route.query.tab, (value) => {
  activeTab.value = value === "calendar" ? "calendar" : "basic"
})
</script>

<template>
  <div class="lite-composite-page">
    <div class="lite-page-tabs">
      <el-tabs v-model="activeTab" @tab-change="selectTab">
        <el-tab-pane label="基本参数" name="basic" />
        <el-tab-pane label="工作日历" name="calendar" />
      </el-tabs>
    </div>
    <component :is="activeComponent" />
  </div>
</template>

<style scoped>
.lite-page-tabs {
  display: flex;
  margin: 20px 24px 0;
  padding: 0 22px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  background: var(--el-bg-color);
}
.lite-page-tabs :deep(.el-tabs__header) { margin: 0; }
.lite-page-tabs :deep(.el-tabs__nav-wrap::after) { height: 1px; }
@media (max-width: 720px) {
  .lite-page-tabs { margin: 12px 12px 0; }
}
</style>
