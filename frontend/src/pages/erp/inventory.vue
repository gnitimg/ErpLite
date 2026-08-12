<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api, money, productQty, qty } from './api'
import ListToolbar from './components/ListToolbar.vue'

const loading = ref(false)
const route = useRoute()
const rows = ref<any[]>([])
const filterDrawer = ref(false)
const keyword = ref('')
const filters = reactive({ stockStatus: '' })
const kind = computed(() => route.meta.inventoryKind === 'PRODUCT' ? 'PRODUCT' : 'PART')
const pageTitle = computed(() => kind.value === 'PRODUCT' ? '产品库存' : '零件库存')
const pageNote = computed(() => kind.value === 'PRODUCT' ? '成品结存包含客单预留与可用数量' : '零件结存用于采购、领用和产品生产')
const activeFilterCount = computed(() => Number(Boolean(filters.stockStatus)))
const displayQty = (value: number) => kind.value === 'PRODUCT' ? productQty(value) : qty(value)

async function load() {
  loading.value = true
  const params = new URLSearchParams()
  params.set('kind', kind.value)
  if (filters.stockStatus) params.set('stock_status', filters.stockStatus)
  if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
  try { rows.value = await api(`/api/inventory?${params}`) }
  catch (error: any) { ElMessage.error(error.message) }
  finally { loading.value = false }
}
function applyFilters() { filterDrawer.value = false; load() }
function resetFilters() { filters.stockStatus = ''; applyFilters() }
onMounted(load)
watch(() => route.name, load)
</script>

<template>
  <div class="erp-page">
    <ListToolbar v-model="keyword" placeholder="搜索物料编码、名称或规格" :filter-count="activeFilterCount" :loading="loading" @search="load" @filter="filterDrawer=true" @refresh="load" />
    <div class="content-card">
      <div class="card-head"><h3>{{ pageTitle }}</h3><span>{{ pageNote }}</span></div>
      <el-table v-loading="loading" :data="rows">
        <el-table-column label="物料" min-width="210"><template #default="{ row }"><div class="sku-cell"><strong>{{ row.name }}</strong><span class="mono">{{ row.sku }} · {{ row.spec || '无规格' }}</span></div></template></el-table-column>
        <el-table-column label="实时结存" width="125" align="right"><template #default="{ row }"><b :class="row.low_stock ? 'number-negative' : 'number-positive'">{{ displayQty(row.stock_qty) }}</b> {{ row.unit }}</template></el-table-column>
        <el-table-column v-if="kind === 'PRODUCT'" label="客单预留" width="105" align="right"><template #default="{ row }">{{ productQty(row.reserved_qty) }}</template></el-table-column>
        <el-table-column v-if="kind === 'PRODUCT'" label="可用库存" width="105" align="right"><template #default="{ row }"><b>{{ productQty(row.available_qty) }}</b></template></el-table-column>
        <el-table-column label="安全库存" width="100" align="right"><template #default="{ row }">{{ displayQty(row.min_stock) }}</template></el-table-column>
        <el-table-column label="库存水位" min-width="180"><template #default="{ row }"><div class="stock-meter"><div class="stock-meter-label"><span>{{ row.low_stock ? '低库存' : '充足' }}</span><span>{{ Math.round(Math.min(100, row.stock_qty / Math.max(row.min_stock * 2, 1) * 100)) }}%</span></div><el-progress :percentage="Math.round(Math.min(100, row.stock_qty / Math.max(row.min_stock * 2, 1) * 100))" :show-text="false" :stroke-width="6" :color="row.low_stock ? '#e05757' : '#39aa7b'" /></div></template></el-table-column>
        <el-table-column label="参考成本" width="110" align="right"><template #default="{ row }">{{ money(row.cost_price) }}</template></el-table-column>
        <el-table-column label="库存金额" width="125" align="right"><template #default="{ row }"><strong>{{ money(row.stock_qty * row.cost_price) }}</strong></template></el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="filterDrawer" title="筛选库存" size="min(420px, 92vw)">
      <el-form label-position="top">
        <el-form-item label="库存状态"><el-select v-model="filters.stockStatus" clearable placeholder="全部状态" style="width:100%"><el-option label="库存预警" value="LOW" /><el-option label="库存正常" value="NORMAL" /></el-select></el-form-item>
        <div class="filter-drawer-footer"><el-button @click="resetFilters">重置</el-button><el-button type="primary" @click="applyFilters">应用筛选</el-button></div>
      </el-form>
    </el-drawer>
  </div>
</template>
