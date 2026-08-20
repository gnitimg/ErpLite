<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, formatTime } from './api'

const loading = ref(false)
const rows = ref<any[]>([])
const actions = ref<string[]>([])
const keyword = ref('')
const filters = reactive({ action: '', status: '', dateRange: [] as string[] })
const activeFilterCount = computed(() => Number(Boolean(filters.action)) + Number(Boolean(filters.status)) + Number(filters.dateRange.length === 2))
const filterDrawer = ref(false)

type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'
const statusMeta: Record<string, { label: string; type: TagType }> = {
  SUCCESS: { label: '成功', type: 'success' },
  FAILED: { label: '失败', type: 'danger' },
}
function statusTag(row: any): { label: string; type: TagType } {
  return statusMeta[row.status] || { label: row.status, type: 'info' }
}

async function load() {
  loading.value = true
  const params = new URLSearchParams()
  if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
  if (filters.action) params.set('action', filters.action)
  if (filters.status) params.set('status', filters.status)
  if (filters.dateRange.length === 2) {
    params.set('start_date', filters.dateRange[0])
    params.set('end_date', filters.dateRange[1])
  }
  try { rows.value = await api(`/api/operation-logs?${params}`) }
  catch (error: any) { ElMessage.error(error.message) }
  finally { loading.value = false }
}
async function loadActions() {
  try { actions.value = await api('/api/operation-logs/actions') }
  catch { actions.value = [] }
}
function applyFilters() { filterDrawer.value = false; load() }
function resetFilters() { filters.action = ''; filters.status = ''; filters.dateRange = []; applyFilters() }
onMounted(() => { loadActions(); load() })
</script>

<template>
  <div class="erp-page">
    <div class="page-toolbar">
      <div class="toolbar-group list-actions">
        <el-input v-model="keyword" clearable class="list-search" placeholder="搜索操作、对象、路径或详情" @keyup.enter="load" @clear="load"><template #prefix><el-icon><Search /></el-icon></template></el-input>
        <el-badge :value="activeFilterCount" :hidden="!activeFilterCount" class="filter-badge"><el-button @click="filterDrawer=true"><el-icon><Filter /></el-icon>筛选</el-button></el-badge>
        <el-button @click="load"><el-icon><Refresh /></el-icon>刷新</el-button>
      </div>
      <el-alert title="系统自动记录登录及各类业务操作的发起用户、客户端 IP 与请求路径。" type="info" :closable="false" show-icon style="flex:1;max-width:420px" />
    </div>
    <div class="content-card">
      <div class="card-head"><h3>操作日志</h3><span>共 {{ rows.length }} 条</span></div>
      <el-table v-loading="loading" :data="rows">
        <el-table-column label="时间" width="165"><template #default="{ row }"><span class="muted">{{ formatTime(row.created_at) }}</span></template></el-table-column>
        <el-table-column label="用户" width="110"><template #default="{ row }"><strong>{{ row.username || '-' }}</strong></template></el-table-column>
        <el-table-column label="操作" width="110"><template #default="{ row }"><el-tag effect="plain" size="small">{{ row.action || '-' }}</el-tag></template></el-table-column>
        <el-table-column label="操作对象" min-width="200"><template #default="{ row }"><span>{{ row.target || '-' }}</span></template></el-table-column>
        <el-table-column label="客户端 IP" width="140"><template #default="{ row }"><span class="mono">{{ row.ip_address || '-' }}</span></template></el-table-column>
        <el-table-column label="请求" min-width="160"><template #default="{ row }"><span class="mono">{{ row.method }} {{ row.path }}</span></template></el-table-column>
        <el-table-column label="状态" width="90"><template #default="{ row }"><el-tag :type="statusTag(row).type" effect="light" size="small">{{ statusTag(row).label }}</el-tag></template></el-table-column>
        <el-table-column label="详情" min-width="160"><template #default="{ row }"><span class="muted">{{ row.detail || '-' }}</span></template></el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="filterDrawer" title="筛选操作日志" size="min(420px, 92vw)">
      <el-form label-position="top">
        <el-form-item label="操作类型"><el-select v-model="filters.action" clearable placeholder="全部操作" style="width:100%"><el-option v-for="action in actions" :key="action" :label="action" :value="action" /></el-select></el-form-item>
        <el-form-item label="状态"><el-select v-model="filters.status" clearable placeholder="全部状态" style="width:100%"><el-option label="成功" value="SUCCESS" /><el-option label="失败" value="FAILED" /></el-select></el-form-item>
        <el-form-item label="时间范围"><el-date-picker v-model="filters.dateRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" range-separator="至" style="width:100%" /></el-form-item>
        <div class="filter-drawer-footer"><el-button @click="resetFilters">重置</el-button><el-button type="primary" @click="applyFilters">应用筛选</el-button></div>
      </el-form>
    </el-drawer>
  </div>
</template>
