<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, money, qty } from './api'

const loading = ref(false)
const rows = ref<any[]>([])
const kind = ref('')
const lowStock = ref(false)
const keyword = ref('')
const totalValue = computed(() => rows.value.reduce((sum, row) => sum + row.stock_qty * row.cost_price, 0))
const lowCount = computed(() => rows.value.filter(row => row.low_stock).length)

async function load() {
  loading.value = true
  const params = new URLSearchParams()
  if (kind.value) params.set('kind', kind.value)
  if (lowStock.value) params.set('low_stock', 'true')
  if (keyword.value) params.set('keyword', keyword.value)
  try { rows.value = await api(`/api/inventory?${params}`) }
  catch (error: any) { ElMessage.error(error.message) }
  finally { loading.value = false }
}
onMounted(load)
</script>

<template>
  <div>
    <div class="metric-grid" style="grid-template-columns:repeat(3,minmax(0,1fr))">
      <div class="metric-card"><div><div class="metric-label">当前物料</div><div class="metric-value">{{ rows.length }}</div><div class="metric-note">筛选范围内的物料</div></div><div class="metric-icon"><el-icon><Files /></el-icon></div></div>
      <div class="metric-card"><div><div class="metric-label">库存预警</div><div class="metric-value">{{ lowCount }}</div><div class="metric-note">结存小于或等于安全线</div></div><div class="metric-icon"><el-icon><Warning /></el-icon></div></div>
      <div class="metric-card"><div><div class="metric-label">库存成本</div><div class="metric-value">{{ money(totalValue) }}</div><div class="metric-note">按最新参考成本计算</div></div><div class="metric-icon"><el-icon><Wallet /></el-icon></div></div>
    </div>
    <div class="page-toolbar">
      <div class="toolbar-group">
        <el-input v-model="keyword" clearable placeholder="搜索物料" style="width:230px" @keyup.enter="load" @clear="load"><template #prefix><el-icon><Search /></el-icon></template></el-input>
        <el-select v-model="kind" placeholder="全部类型" clearable style="width:130px" @change="load"><el-option label="零件" value="PART" /><el-option label="产品" value="PRODUCT" /></el-select>
        <el-checkbox v-model="lowStock" border @change="load">只看预警</el-checkbox>
        <el-button @click="load">查询</el-button>
      </div>
      <el-button @click="load"><el-icon><Refresh /></el-icon>刷新库存</el-button>
    </div>
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
  </div>
</template>
