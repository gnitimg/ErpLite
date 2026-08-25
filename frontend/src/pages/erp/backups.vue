<script setup lang="ts">
import { ElMessage, ElMessageBox } from "element-plus"
import { computed, onMounted, reactive, ref } from "vue"
import { api, apiBlob, formatTime, useLiveRefresh } from "./api"
import ListToolbar from "./components/ListToolbar.vue"
import InfoTip from "./components/InfoTip.vue"

interface BackupRow {
  filename: string
  created_at: string
  backup_type: "MANUAL" | "PRE_RESTORE"
  source_backup?: string | null
  size_bytes: number
  table_counts: Record<string, number>
  total_records: number
}

const loading = ref(false)
const creating = ref(false)
const restoring = ref("")
const filterDrawer = ref(false)
const keyword = ref("")
const rows = ref<BackupRow[]>([])
const filters = reactive({ backupType: "", dateRange: [] as string[] })
const typeLabels: Record<string, string> = { MANUAL: "手动备份", PRE_RESTORE: "恢复前自动备份" }
const activeFilterCount = computed(() => Number(Boolean(filters.backupType)) + Number(filters.dateRange.length === 2))
const totalSize = computed(() => rows.value.reduce((sum, row) => sum + row.size_bytes, 0))
const latestBackup = computed(() => rows.value[0])
const filteredRows = computed(() => {
  const token = keyword.value.trim().toLocaleLowerCase()
  return rows.value.filter((row) => {
    const matchesKeyword = !token || `${row.filename} ${typeLabels[row.backup_type] || ""}`.toLocaleLowerCase().includes(token)
    const matchesType = !filters.backupType || row.backup_type === filters.backupType
    const date = row.created_at.slice(0, 10)
    const matchesDate = filters.dateRange.length !== 2 || (date >= filters.dateRange[0] && date <= filters.dateRange[1])
    return matchesKeyword && matchesType && matchesDate
  })
})

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    rows.value = await api("/api/backups")
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    if (!silent) loading.value = false
  }
}

async function createBackup() {
  creating.value = true
  try {
    const backup: BackupRow = await api("/api/backups", { method: "POST" })
    ElMessage.success(`备份已创建：${backup.filename}`)
    await load()
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    creating.value = false
  }
}

async function download(row: any) {
  try {
    const blob = await apiBlob(`/api/backups/${encodeURIComponent(row.filename)}/download`)
    const url = URL.createObjectURL(blob)
    const link = document.createElement("a")
    link.href = url
    link.download = row.filename
    link.click()
    URL.revokeObjectURL(url)
  } catch (error: any) {
    ElMessage.error(error.message || "下载失败")
  }
}

async function restore(row: any) {
  try {
    const { value } = await ElMessageBox.prompt(
      `恢复会用该快照覆盖当前业务数据。系统会先自动备份当前数据；请输入完整文件名确认：${row.filename}`,
      "确认恢复数据",
      {
        type: "warning",
        confirmButtonText: "确认恢复",
        cancelButtonText: "取消",
        inputPlaceholder: row.filename,
        inputValidator: value => value === row.filename || "输入的文件名不一致"
      }
    )
    restoring.value = row.filename
    const result = await api(`/api/backups/${encodeURIComponent(row.filename)}/restore`, {
      method: "POST",
      body: JSON.stringify({ confirm_filename: value })
    })
    ElMessage.success(`数据已恢复；恢复前快照：${result.safety_backup.filename}`)
    await load()
  } catch (error: any) {
    if (error !== "cancel" && error !== "close") ElMessage.error(error.message)
  } finally {
    restoring.value = ""
  }
}

function applyFilters() {
  filterDrawer.value = false
}
function resetFilters() {
  filters.backupType = ""
  filters.dateRange = []
  applyFilters()
}

onMounted(load)
useLiveRefresh(() => load(true))
</script>

<template>
  <div class="erp-page">
    <div class="metric-grid" style="grid-template-columns:repeat(3,minmax(0,1fr))">
      <div class="metric-card">
        <div>
          <div class="metric-label">
            可用备份
          </div><div class="metric-value">
            {{ rows.length }}
          </div><div class="metric-note">
            本机保存的数据快照
          </div>
        </div><div class="metric-icon">
          <el-icon><FolderOpened /></el-icon>
        </div>
      </div>
      <div class="metric-card">
        <div>
          <div class="metric-label">
            备份占用
          </div><div class="metric-value">
            {{ formatBytes(totalSize) }}
          </div><div class="metric-note">
            ZIP 压缩后的合计大小
          </div>
        </div><div class="metric-icon">
          <el-icon><Coin /></el-icon>
        </div>
      </div>
      <div class="metric-card">
        <div>
          <div class="metric-label">
            最近备份
          </div><div class="metric-value" style="font-size:18px">
            {{ latestBackup ? formatTime(latestBackup.created_at) : '暂无' }}
          </div><div class="metric-note">
            建议在批量操作前创建快照
          </div>
        </div><div class="metric-icon">
          <el-icon><Clock /></el-icon>
        </div>
      </div>
    </div>

    <ListToolbar v-model="keyword" placeholder="搜索备份文件名或类型" :filter-count="activeFilterCount" :loading="loading" @filter="filterDrawer = true" @refresh="load">
      <el-button type="primary" :loading="creating" @click="createBackup">
        <el-icon><DocumentAdd /></el-icon>立即备份
      </el-button>
    </ListToolbar>
    <div class="content-card">
      <div class="card-head">
        <h3>
          数据备份
          <InfoTip content="备份保存在项目 backups 目录并可下载留存。恢复会覆盖当前数据，但系统会先自动生成安全快照。" />
        </h3>
      </div>
      <el-table v-loading="loading" :data="filteredRows" row-key="filename" empty-text="暂无符合条件的数据备份">
        <el-table-column label="备份文件" min-width="310">
          <template #default="{ row }">
            <div class="sku-cell">
              <strong class="mono">{{ row.filename }}</strong><span v-if="row.source_backup">恢复目标：{{ row.source_backup }}</span><span v-else>完整业务数据快照</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="145">
          <template #default="{ row }">
            <el-tag :type="row.backup_type === 'PRE_RESTORE' ? 'warning' : 'success'" effect="light" size="small">
              {{ typeLabels[row.backup_type] || row.backup_type }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="175">
          <template #default="{ row }">
            {{ formatTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="数据量" width="110" align="right">
          <template #default="{ row }">
            {{ row.total_records }} 条
          </template>
        </el-table-column>
        <el-table-column label="文件大小" width="105" align="right">
          <template #default="{ row }">
            {{ formatBytes(row.size_bytes) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="download(row)">
              下载
            </el-button><el-button link type="danger" :loading="restoring === row.filename" @click="restore(row)">
              恢复
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="filterDrawer" title="筛选数据备份" size="min(420px, 92vw)">
      <el-form label-position="top">
        <el-form-item label="备份类型">
          <el-select v-model="filters.backupType" clearable placeholder="全部类型" style="width:100%">
            <el-option label="手动备份" value="MANUAL" /><el-option label="恢复前自动备份" value="PRE_RESTORE" />
          </el-select>
        </el-form-item>
        <el-form-item label="创建日期">
          <el-date-picker
            v-model="filters.dateRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            range-separator="至"
            style="width: 100%"
          />
        </el-form-item>
        <div class="filter-drawer-footer">
          <el-button @click="resetFilters">
            重置
          </el-button><el-button type="primary" @click="applyFilters">
            应用筛选
          </el-button>
        </div>
      </el-form>
    </el-drawer>
  </div>
</template>
