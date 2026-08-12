<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, formatTime, money, productQty, qty, txLabels } from './api'

const loading = ref(true)
const data = ref<any>({ metrics: {}, recent_transactions: [], low_stock_items: [] })

async function load() {
  loading.value = true
  try { data.value = await api('/api/dashboard') }
  catch (error: any) { ElMessage.error(error.message) }
  finally { loading.value = false }
}
onMounted(load)

const metrics = [
  { key: 'parts', label: '零件种类', note: '在用零件档案', icon: 'Cpu' },
  { key: 'products', label: '产品种类', note: '含 BOM 成品', icon: 'Box' },
  { key: 'pending_orders', label: '待处理客单', note: '草稿及已确认', icon: 'Tickets' },
  { key: 'low_stock', label: '库存预警', note: '低于安全库存', icon: 'Warning' },
  { key: 'inventory_value', label: '库存成本', note: '按最新成本估算', icon: 'Coin', money: true },
]
</script>

<template>
  <div v-loading="loading" class="erp-page">
    <section class="metric-grid">
      <div v-for="metric in metrics" :key="metric.key" class="metric-card">
        <div>
          <div class="metric-label">{{ metric.label }}</div>
          <div class="metric-value">{{ metric.money ? money(data.metrics[metric.key]) : qty(data.metrics[metric.key]) }}</div>
          <div class="metric-note">{{ metric.note }}</div>
        </div>
        <div class="metric-icon"><el-icon><component :is="metric.icon" /></el-icon></div>
      </div>
    </section>

    <section class="dashboard-grid">
      <div class="content-card">
        <div class="card-head"><h3>最近库存动态</h3><router-link to="/warehouse/movements">查看全部</router-link></div>
        <el-table :data="data.recent_transactions" style="width: 100%">
          <el-table-column label="流水号" min-width="175"><template #default="{ row }"><span class="mono">{{ row.transaction_no }}</span></template></el-table-column>
          <el-table-column label="业务类型" width="105"><template #default="{ row }"><el-tag size="small" effect="plain">{{ txLabels[row.transaction_type] || row.transaction_type }}</el-tag></template></el-table-column>
          <el-table-column label="物料变化" min-width="230"><template #default="{ row }"><div class="tx-lines"><span v-for="line in row.lines" :key="line.id" class="tx-line">{{ line.name }} <b :class="line.quantity_change > 0 ? 'number-positive' : 'number-negative'">{{ line.quantity_change > 0 ? '+' : '' }}{{ line.kind === 'PRODUCT' ? productQty(line.quantity_change) : qty(line.quantity_change) }}</b></span></div></template></el-table-column>
          <el-table-column label="时间" width="165"><template #default="{ row }"><span class="muted">{{ formatTime(row.occurred_at) }}</span></template></el-table-column>
        </el-table>
      </div>

      <div style="display:flex;flex-direction:column;gap:18px">
        <div class="content-card">
          <div class="card-head"><h3>快捷入口</h3><span>常用操作</span></div>
          <div class="card-body quick-actions">
            <router-link class="quick-action" to="/master-data/parts"><strong>新建零件</strong><span>建立配件档案</span></router-link>
            <router-link class="quick-action" to="/master-data/products"><strong>新建产品</strong><span>编辑产品 BOM</span></router-link>
            <router-link class="quick-action" to="/warehouse/operations"><strong>办理入库</strong><span>采购或其他入库作业</span></router-link>
            <router-link class="quick-action" to="/warehouse/production"><strong>产品生产</strong><span>按 BOM 领料并入库</span></router-link>
            <router-link class="quick-action" to="/operations/orders"><strong>录入客单</strong><span>创建销售订单</span></router-link>
          </div>
        </div>
        <div class="content-card">
          <div class="card-head"><h3>库存预警</h3><router-link to="/warehouse/parts-inventory">库存详情</router-link></div>
          <div v-if="!data.low_stock_items.length" class="empty-state">当前没有低库存物料</div>
          <el-table v-else :data="data.low_stock_items" :show-header="false">
            <el-table-column min-width="150"><template #default="{ row }"><div class="sku-cell"><strong>{{ row.name }}</strong><span>{{ row.sku }}</span></div></template></el-table-column>
            <el-table-column width="100" align="right"><template #default="{ row }"><b class="number-negative">{{ qty(row.stock_qty) }}</b><span class="muted"> / {{ qty(row.min_stock) }}</span></template></el-table-column>
          </el-table>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.card-head a { color: #3155d9; font-size: 12px; text-decoration: none; }
</style>
