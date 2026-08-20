<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, money, qty } from './api'
import ListToolbar from './components/ListToolbar.vue'

const loading = ref(false)
const rows = ref<any[]>([])
const filterDrawer = ref(false)
const keyword = ref('')
const filters = reactive({ kind: '', stockStatus: '' })
const totalValue = computed(() => rows.value.reduce((sum, row) => sum + row.stock_qty * row.cost_price, 0))
const lowCount = computed(() => rows.value.filter(row => row.low_stock).length)
const activeFilterCount = computed(() => Number(Boolean(filters.kind)) + Number(Boolean(filters.stockStatus)))

async function load() {
  loading.value = true
  const params = new URLSearchParams()
  if (filters.kind) params.set('kind', filters.kind)
  if (filters.stockStatus) params.set('stock_status', filters.stockStatus)
  if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
  try { rows.value = await api(`/api/inventory?${params}`) }
  catch (error: any) { ElMessage.error(error.message) }
  finally { loading.value = false }
}
function applyFilters() { filterDrawer.value = false; load() }
function resetFilters() { filters.kind = ''; filters.stockStatus = ''; applyFilters() }
onMounted(load)
</script>

<template>
  <div class="erp-page">
    <div class="metric-grid" style="grid-template-columns:repeat(3,minmax(0,1fr))">
      <div class="metric-card"><div><div class="metric-label">当前物料</div><div class="metric-value">{{ rows.length }}</div><div class="metric-note">筛选范围内的物料</div></div><div class="metric-icon"><el-icon><Files /></el-icon></div></div>
      <div class="metric-card"><div><div class="metric-label">库存预警</div><div class="metric-value">{{ lowCount }}</div><div class="metric-note">结存小于或等于安全线</div></div><div class="metric-icon"><el-icon><Warning /></el-icon></div></div>
      <div class="metric-card"><div><div class="metric-label">库存成本</div><div class="metric-value">{{ money(totalValue) }}</div><div class="metric-note">按最新参考成本计算</div></div><div class="metric-icon"><el-icon><Wallet /></el-icon></div></div>
    </div>
    <ListToolbar v-model="keyword" placeholder="搜索物料编码、名称或规格" :filter-count="activeFilterCount" :loading="loading" @search="load" @filter="filterDrawer=true" @refresh="load" />
    <div class="content-card">
      <div class="card-head"><h3>库存台账</h3><span>实时结存来自库存流水</span></div>
      <el-table v-loading="loading" :data="rows">
        <el-table-column label="物料" min-width="210"><template #default="{ row }"><div class="sku-cell"><strong>{{ row.name }}</strong><span class="mono">{{ row.sku }} · {{ row.spec || '无规格' }}</span></div></template></el-table-column>
        <el-table-column label="类型" width="85"><template #default="{ row }"><el-tag :type="row.kind === 'PRODUCT' ? 'primary' : 'info'" effect="plain" size="small">{{ row.kind === 'PRODUCT' ? '产品' : '零件' }}</el-tag></template></el-table-column>
        <el-table-column label="实时结存" width="125" align="right"><template #default="{ row }"><b :class="row.low_stock ? 'number-negative' : 'number-positive'">{{ qty(row.stock_qty) }}</b> {{ row.unit }}</template></el-table-column>
        <el-table-column label="安全库存" width="100" align="right"><template #default="{ row }">{{ qty(row.min_stock) }}</template></el-table-column>
        <el-table-column label="库存水位" min-width="180"><template #default="{ row }"><div class="stock-meter"><div class="stock-meter-label"><span>{{ row.low_stock ? '低库存' : '充足' }}</span><span>{{ Math.round(Math.min(100, row.stock_qty / Math.max(row.min_stock * 2, 1) * 100)) }}%</span></div><el-progress :percentage="Math.round(Math.min(100, row.stock_qty / Math.max(row.min_stock * 2, 1) * 100))" :show-text="false" :stroke-width="6" :color="row.low_stock ? '#e05757' : '#39aa7b'" /></div></template></el-table-column>
        <el-table-column label="参考成本" width="110" align="right"><template #default="{ row }">{{ money(row.cost_price) }}</template></el-table-column>
        <el-table-column label="库存金额" width="125" align="right"><template #default="{ row }"><strong>{{ money(row.stock_qty * row.cost_price) }}</strong></template></el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="filterDrawer" title="筛选库存" size="min(420px, 92vw)">
      <el-form label-position="top">
        <el-form-item label="物料类型"><el-select v-model="filters.kind" clearable placeholder="全部类型" style="width:100%"><el-option label="零件" value="PART" /><el-option label="产品" value="PRODUCT" /></el-select></el-form-item>
        <el-form-item label="库存状态"><el-select v-model="filters.stockStatus" clearable placeholder="全部状态" style="width:100%"><el-option label="库存预警" value="LOW" /><el-option label="库存正常" value="NORMAL" /></el-select></el-form-item>
        <div class="filter-drawer-footer"><el-button @click="resetFilters">重置</el-button><el-button type="primary" @click="applyFilters">应用筛选</el-button></div>
      </el-form>
    </el-drawer>
  </div>
</template>
