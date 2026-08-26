<script setup lang="ts">
import { ElMessage } from "element-plus"
import { computed, onMounted, ref } from "vue"
import { api, formatDate, money, productQty, qty, stockQty, useLiveRefresh } from "./api"

const loading = ref(true)
const data = ref<any>({
  metrics: {},
  low_stock_items: [],
  todos: { purchase: [], production: [], shipping: [] },
  orders: [],
  receivables: []
})
const todoFilter = ref("all")

const activeOrders = computed(() => (data.value.orders || []).filter((order: any) => !["FULFILLED", "CANCELLED"].includes(order.status)))
const orderHasRisk = (order: any) => {
  if (!order.eta_reliable) return true
  if (!order.estimated_completion_at) return false
  return order.estimated_completion_at.slice(0, 10) > order.required_date
}
const dueSoonOrders = computed(() => activeOrders.value.filter((order: any) => {
  const days = dueMeta(order.required_date).days
  return days >= 0 && days <= 7
}))
const riskOrders = computed(() => activeOrders.value.filter((order: any) => dueMeta(order.required_date).days < 0 || orderHasRisk(order)))
const recentOrders = computed(() => activeOrders.value.slice(0, 8))
const outstandingReceivable = computed(() => (data.value.receivables || [])
  .filter((row: any) => row.status !== "CANCELLED")
  .reduce((total: number, row: any) => total + Number(row.remaining_amount ?? 0), 0))
const pendingProduction = computed(() => (data.value.todos.production || [])
  .reduce((total: number, row: any) => total + Number(row.total_production_required || 0), 0))
const metrics = computed(() => [
  { label: "进行中订单", note: "尚未全部交付", icon: "Tickets", value: activeOrders.value.length },
  { label: "七天内到期", note: "需要优先跟进", icon: "Timer", value: dueSoonOrders.value.length },
  { label: "延期 / ETA 风险", note: "逾期或预计不可靠", icon: "Warning", value: riskOrders.value.length },
  { label: "待生产", note: "成品库存不足部分", icon: "Tools", value: pendingProduction.value },
  { label: "待采购原料", note: "存在采购缺口的物料", icon: "ShoppingCart", value: (data.value.todos.purchase || []).length },
  { label: "应收未收", note: "客户未结清金额", icon: "Money", value: outstandingReceivable.value, money: true }
])

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
    const [dashboard, orders, receivables] = await Promise.all([
      api("/api/dashboard"),
      api("/api/orders"),
      api("/api/finance/receivables")
    ])
    data.value = { ...dashboard, orders, receivables }
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
  if (row.taskType === "purchase") return "/lite-purchase/requirements"
  if (row.taskType === "production") return "/lite-production/schedule"
  return "/lite-orders/list"
}

onMounted(load)
useLiveRefresh(() => load(true))
</script>

<template>
  <div v-loading="loading" class="erp-page">
    <section class="metric-grid">
      <div v-for="metric in metrics" :key="metric.label" class="metric-card">
        <div>
          <div class="metric-label">
            {{ metric.label }}
          </div>
          <div class="metric-value">
            {{ metric.money ? money(metric.value) : productQty(metric.value) }}
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
          <router-link to="/lite-orders/list">
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
          <h3>近期客户订单</h3>
          <router-link to="/lite-orders/list">
            查看订单
          </router-link>
        </div>
        <el-table :data="recentOrders" empty-text="当前没有进行中的客户订单">
          <el-table-column label="订单 / 客户" min-width="210">
            <template #default="{ row }">
              <div class="sku-cell"><strong>{{ row.order_no }}</strong><span>{{ row.customer_name }}</span></div>
            </template>
          </el-table-column>
          <el-table-column label="要求交期" width="160">
            <template #default="{ row }">
              <div class="due-cell"><span>{{ row.required_date }}</span><el-tag :type="dueMeta(row.required_date).type as any" size="small">{{ dueMeta(row.required_date).label }}</el-tag></div>
            </template>
          </el-table-column>
          <el-table-column label="预计可交" width="150">
            <template #default="{ row }">
              {{ formatDate(row.estimated_completion_at) }}
            </template>
          </el-table-column>
          <el-table-column label="风险" min-width="150">
            <template #default="{ row }">
              <el-tag :type="orderHasRisk(row) ? 'warning' : 'success'" size="small" effect="plain">
                {{ orderHasRisk(row) ? (row.eta_note || '需要关注') : '交期正常' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="dashboard-side-stack">
        <div class="content-card">
          <div class="card-head">
            <h3>快捷开单</h3>
          </div>
          <div class="card-body quick-actions">
            <router-link class="quick-action" to="/lite-stock-documents/list">
              <strong>库存单据</strong><span>开入库单或开出库单</span>
            </router-link>
            <router-link class="quick-action" to="/lite-inventory/history">
              <strong>查看库存流水</strong><span>按时间追溯库存变化</span>
            </router-link>
            <router-link class="quick-action" to="/lite-orders/documents">
              <strong>查看销售单据</strong><span>订单出库与客户退货记录</span>
            </router-link>
            <router-link class="quick-action" to="/lite-orders/list">
              <strong>新建客户订单</strong><span>录入客户需求与交期</span>
            </router-link>
          </div>
        </div>
        <div class="content-card">
          <div class="card-head">
            <h3>库存预警</h3>
            <router-link :to="{ path: '/lite-inventory/overview', query: { tab: 'materials' } }">
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
