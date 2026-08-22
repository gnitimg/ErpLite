<script setup lang="ts">
import { ElMessage } from "element-plus"
import { onMounted, ref, reactive } from "vue"
import { api, useLiveRefresh } from "./api"
import ListToolbar from "./components/ListToolbar.vue"

interface InventoryRow {
  id: number
  sku: string
  name: string
  spec: string
  stock_qty: number
  unit: string
}

const loading = ref(false)
const submitting = ref(false)
const keyword = ref("")
const rows = ref<InventoryRow[]>([])
const counts = reactive<Record<number, number | undefined>>({})
const notes = ref("")

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    const data = await api("/api/inventory?kind=PART&pageSize=9999")
    rows.value = data.items || data || []
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    if (!silent) loading.value = false
  }
}

const filteredRows = ref<InventoryRow[]>([])
function applyFilter() {
  const token = keyword.value.trim().toLowerCase()
  filteredRows.value = rows.value.filter(r => !token || `${r.sku} ${r.name} ${r.spec}`.toLowerCase().includes(token))
}

const discrepancies = ref<{ item: InventoryRow; difference: number }[]>([])
function computeDiscrepancies() {
  discrepancies.value = filteredRows.value
    .map(item => ({ item, difference: (counts[item.id] ?? item.stock_qty) - item.stock_qty }))
    .filter(d => d.difference !== 0)
}

async function submit() {
  computeDiscrepancies()
  if (!discrepancies.value.length) {
    ElMessage.info("没有差异，无需调整")
    return
  }
  submitting.value = true
  try {
    await api("/api/stock/reconcile", {
      method: "POST",
      body: JSON.stringify({
        items: discrepancies.value.map(d => ({ item_id: d.item.id, physical_count: counts[d.item.id] ?? d.item.stock_qty })),
        notes: notes.value
      })
    })
    ElMessage.success(`对账完成，调整 ${discrepancies.value.length} 项`)
    discrepancies.value = []
    notes.value = ""
    await load()
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    submitting.value = false
  }
}

onMounted(async () => { await load(); applyFilter() })
useLiveRefresh(() => load(true))
</script>

<template>
  <div class="erp-page">
    <ListToolbar v-model="keyword" placeholder="搜索SKU、名称" :loading="loading" @refresh="load" @update:model-value="applyFilter" />

    <el-alert class="list-page-alert" title="录入实际盘点数量后点击「提交对账」，系统将自动生成库存调整流水记录差异。" type="info" :closable="false" show-icon />

    <div class="content-card">
      <div class="card-head">
        <h3>库存对账</h3><span>录入实物数量，系统自动生成调整流水</span>
      </div>
      <el-table v-loading="loading" :data="filteredRows" row-key="id" empty-text="暂无库存">
        <el-table-column label="SKU" prop="sku" width="140" />
        <el-table-column label="名称" prop="name" min-width="120" />
        <el-table-column label="规格" prop="spec" width="120" />
        <el-table-column label="账面库存" prop="stock_qty" width="100" align="right" />
        <el-table-column label="实物盘点" width="140">
          <template #default="{ row }">
            <el-input-number v-model="counts[row.id]" :placeholder="String(row.stock_qty)" :controls="false" size="small" style="width:100%" />
          </template>
        </el-table-column>
        <el-table-column label="差异" width="80" align="right">
          <template #default="{ row }">
            <span :style="{ color: (counts[row.id] ?? row.stock_qty) - row.stock_qty !== 0 ? 'var(--el-color-danger)' : '' }">
              {{ (counts[row.id] ?? row.stock_qty) - row.stock_qty }}
            </span>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div style="margin-top:16px;display:flex;gap:12px;align-items:center">
      <el-input v-model="notes" placeholder="对账备注" style="max-width:300px" />
      <el-button type="primary" :loading="submitting" @click="submit">提交对账</el-button>
    </div>
  </div>
</template>
