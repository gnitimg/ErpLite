<script setup lang="ts">
import { ElMessage } from "element-plus"
import { computed, onMounted, ref } from "vue"
import { api, formatTime, money, productQty, qty, stockQty, txLabels, useLiveRefresh } from "./api"

const loading = ref(true)
const data = ref<any>({
  metrics: {},
  recent_transactions: [],
  low_stock_items: [],
  todos: { purchase: [], production: [], shipping: [] }
})
const todoFilter = ref("all")

const metrics = [
  { key: "parts", label: "零件种类", note: "在用零件档案", icon: "Cpu" },
  { key: "products", label: "产品种类", note: "含 BOM 成品", icon: "Box" },
  { key: "pending_orders", label: "待处理客单", note: "草稿及备货中", icon: "Tickets" },
  { key: "low_stock", label: "库存预警", note: "低于安全库存", icon: "Warning" },
  { key: "inventory_value", label: "库存成本", note: "按最新成本估算", icon: "Coin", money: true }
]

const todoTypeMeta: Record<string, { label: string, type: string }> = {
  purchase: { label: "采购零件", type: "warning" },
  production: { label: "生产产品", type: "primary" },
  shipping: { label: "产品出库", type: "success" }
}

const allTodoRows = computed(() => [
  ...(data.value.todos.purchase || []).map((row: any) => ({
    ...row,
    taskType: "purchase",
    title: `${row.sku} · ${row.name}`,
    summary: `待购买 ${qty(row.shortage_quantity)} ${row.unit}，涉及 ${row.involved_products || "产品需求"}`
  })),
  ...(data.value.todos.production || []).map((row: any) => ({
    ...row,
    taskType: "production",
    title: `${row.sku} · ${row.name}`,
    summary: `待生产 ${productQty(row.total_production_required)} ${row.unit}，已排产 ${productQty(row.scheduled_quantity)}`
  })),
  ...(data.value.todos.shipping || []).map((row: any) => ({
    ...row,
    taskType: "shipping",
    title: `${row.order_no} · ${row.customer_name}`,
    summary: row.lines?.map((line: any) => `${line.name} ${productQty(line.remaining_quantity)}`).join("、")
  }))
])

const activeTodoRows = computed(() => allTodoRows.value.filter((row: any) => {
  if (todoFilter.value === "all") return true
  if (todoFilter.value === "overdue") return row.required_date && dueMeta(row.required_date).days < 0
  return row.taskType === todoFilter.value
}))

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    data.value = await api("/api/dashboard")
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    if (!silent) loading.value = false
  }
}

function todoSummary(row: any) {
  return row.summary || "系统正在自动计算"
}

function dueMeta(value: string) {
  const due = new Date(`${value}T00:00:00`)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const days = Math.round((due.getTime() - today.getTime()) / 86400000)
  if (days < 0) return { days, label: `逾期 ${Math.abs(days)} 天`, type: "danger" }
  if (days === 0) return { days, label: "今天到期", type: "warning" }
  if (days === 1) return { days, label: "明天到期", type: "primary" }
  return { days, label: `剩余 ${days} 天`, type: "info" }
}

function todoRoute(row: any) {
  if (row.taskType === "purchase") return "/operations/purchase"
  if (row.taskType === "production") return "/operations/production"
  return "/operations/orders"
}

function transactionSummary(row: any) {
  if (!row.lines?.length) return "暂无物料变化"
  const first = row.lines[0]
  const direction = first.quantity_change > 0 ? "入库" : "出库"
  const quantity = first.kind === "PRODUCT"
    ? productQty(Math.abs(first.quantity_change))
    : qty(Math.abs(first.quantity_change))
  return `${first.name} ${direction} ${quantity}${row.lines.length > 1 ? ` 等 ${row.lines.length} 项` : ""}`
}

onMounted(load)
useLiveRefresh(() => load(true))
</script>

<template>
  <div v-loading="loading" class="erp-page">
    <section class="metric-grid">
      <div v-for="metric in metrics" :key="metric.key" class="metric-card">
        <div>
          <div class="metric-label">
            {{ metric.label }}
          </div>
          <div class="metric-value">
            {{ metric.money ? money(data.metrics[metric.key]) : productQty(data.metrics[metric.key]) }}
          </div>
          <div class="metric-note">
            {{ metric.note }}
          </div>
        </div>
        <div class="metric-icon">
          <el-icon><component :is="metric.icon" /></el-icon>
        </div>
      </div>
    </section>

    <section class="content-card dashboard-todos">
      <div class="card-head">
        <div>
          <h3>业务待办</h3>
        </div>
        <div class="todo-filter">
          <el-select v-model="todoFilter" aria-label="筛选备货任务" style="width: 150px">
            <el-option label="全部任务" value="all" />
            <el-option label="待采购" value="purchase" />
            <el-option label="待生产" value="production" />
            <el-option label="待出库" value="shipping" />
            <el-option label="只看逾期" value="overdue" />
          </el-select>
          <router-link to="/operations/orders">
            全部客单
          </router-link>
        </div>
      </div>
      <el-table :data="activeTodoRows" empty-text="当前没有符合条件的业务待办">
        <el-table-column label="待办对象" min-width="250">
          <template #default="{ row }">
            <span>{{ row.title }}</span>
          </template>
        </el-table-column>
        <el-table-column label="交付时限" width="210">
          <template #default="{ row }">
            <div v-if="row.required_date" class="due-cell">
              <span>{{ row.required_date }}</span>
              <el-tag :type="dueMeta(row.required_date).type as any" effect="light" size="small">
                {{ dueMeta(row.required_date).label }}
              </el-tag>
            </div><span v-else class="muted">按汇总需求处理</span>
          </template>
        </el-table-column>
        <el-table-column label="任务" width="110">
          <template #default="{ row }">
            <el-tag :type="todoTypeMeta[row.taskType].type as any" effect="plain" size="small">
              {{ todoTypeMeta[row.taskType].label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="任务内容" min-width="260">
          <template #default="{ row }">
            {{ todoSummary(row) }}
          </template>
        </el-table-column>
        <el-table-column label="处理" width="110" fixed="right">
          <template #default="{ row }">
            <router-link class="todo-action" :to="todoRoute(row)">
              去处理
            </router-link>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <section class="dashboard-grid dashboard-lower-grid">
      <div class="content-card">
        <div class="card-head">
          <h3>最近库存动态</h3>
          <router-link to="/logs/stock">
            查看全部
          </router-link>
        </div>
        <el-table :data="data.recent_transactions">
          <el-table-column label="流水号" min-width="175">
            <template #default="{ row }">
              <span class="mono">{{ row.transaction_no }}</span>
            </template>
          </el-table-column>
          <el-table-column label="业务类型" width="105">
            <template #default="{ row }">
              <el-tag size="small" effect="plain">
                {{ txLabels[row.transaction_type] || row.transaction_type }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="物料变化" min-width="230">
            <template #default="{ row }">
              <span>{{ transactionSummary(row) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="时间" width="165">
            <template #default="{ row }">
              <span class="muted">{{ formatTime(row.occurred_at) }}</span>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="dashboard-side-stack">
        <div class="content-card">
          <div class="card-head">
            <h3>快捷开单</h3><span>常用单据入口</span>
          </div>
          <div class="card-body quick-actions">
            <router-link class="quick-action" to="/operations/stock-operations">
              <strong>开入库单</strong><span>采购件或普通物料入库</span>
            </router-link>
            <router-link class="quick-action" to="/operations/stock-operations">
              <strong>开出库单</strong><span>领料或普通物料出库</span>
            </router-link>
            <router-link class="quick-action" to="/logs/inbound-documents">
              <strong>查看入库单</strong><span>生产与采购入库凭证</span>
            </router-link>
            <router-link class="quick-action" to="/logs/outbound-documents">
              <strong>查看出库单</strong><span>销售与普通出库凭证</span>
            </router-link>
            <router-link class="quick-action" to="/operations/orders">
              <strong>新建客户订单</strong><span>录入客户需求与交期</span>
            </router-link>
          </div>
        </div>
        <div class="content-card">
          <div class="card-head">
            <h3>库存预警</h3>
            <router-link to="/warehouse/parts-inventory">
              库存详情
            </router-link>
          </div>
          <div v-if="!data.low_stock_items.length" class="empty-state">
            当前没有低库存物料
          </div>
          <el-table v-else :data="data.low_stock_items" :show-header="false">
            <el-table-column min-width="150">
              <template #default="{ row }">
                <div class="sku-cell">
                  <strong>{{ row.name }}</strong><span>{{ row.sku }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column width="125" align="right">
              <template #default="{ row }">
                <b class="number-negative">{{ stockQty(row.stock_qty, row.kind === 'PRODUCT') }}</b>
                <span class="muted"> / {{ stockQty(row.min_stock, row.kind === 'PRODUCT') }}</span>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.card-head a,
.todo-action {
  color: var(--el-color-primary);
  font-size: 12px;
  text-decoration: none;
}
</style>
