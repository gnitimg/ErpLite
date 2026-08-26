<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { useUserStore } from "@/pinia/stores/user"
import Backups from "./backups.vue"
import OperationLogs from "./operation-logs.vue"
import PrintSettings from "./print-settings.vue"
import Users from "./users.vue"

type SystemTab = "users" | "backups" | "print" | "logs"

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const isAdmin = computed(() => userStore.roles.includes("ADMIN"))
const allowedTabs = computed<SystemTab[]>(() => isAdmin.value
  ? ["users", "backups", "print", "logs"]
  : ["print", "logs"])
const requestedTab = route.query.tab as SystemTab
const initialTab = allowedTabs.value.includes(requestedTab) ? requestedTab : allowedTabs.value[0]
const activeTab = ref<SystemTab>(initialTab)
const components = { users: Users, backups: Backups, print: PrintSettings, logs: OperationLogs }
const activeComponent = computed(() => components[activeTab.value])

function selectTab(value: string | number) {
  const tab = value as SystemTab
  if (allowedTabs.value.includes(tab)) router.replace({ query: { ...route.query, tab } })
}

watch([() => route.query.tab, allowedTabs], ([value]) => {
  const tab = value as SystemTab
  activeTab.value = allowedTabs.value.includes(tab) ? tab : allowedTabs.value[0]
})
</script>

<template>
  <div class="lite-composite-page">
    <div class="lite-page-tabs">
      <el-tabs v-model="activeTab" @tab-change="selectTab">
        <el-tab-pane v-if="isAdmin" label="用户" name="users" />
        <el-tab-pane v-if="isAdmin" label="备份" name="backups" />
        <el-tab-pane label="打印" name="print" />
        <el-tab-pane label="操作日志" name="logs" />
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
