<script setup lang="ts">
import { ElMessage, ElMessageBox } from "element-plus"
import { computed, onMounted, reactive, ref } from "vue"
import { api, formatDate, money, productQty, qty, statusMap, useLiveRefresh } from "./api"
import ListToolbar from "./components/ListToolbar.vue"
import QuantityInput from "./components/QuantityInput.vue"

const loading = ref(false)
const saving = ref(false)
const drawer = ref(false)
const filterDrawer = ref(false)
const workflowDrawer = ref(false)
const workflowLoading = ref(false)
const workflow = ref<any>(null)
const activeOrder = ref<any>(null)
const activeDetailTab = ref("overview")
const rows = ref<any[]>([])
const products = ref<any[]>([])
const keyword = ref("")
const filters = reactive({ status: "", dateRange: [] as string[] })
const today = () => new Date().toISOString().slice(0, 10)
function emptyOrderForm() {
  return {
    customer_name: "",
    customer_phone: "",
    customer_address: "",
    order_date: today(),
    required_date: today(),
    notes: "",
    items: [] as any[]
  }
}
const form = reactive(emptyOrderForm())
const total = computed(() => form.items.reduce((sum, line) => sum + Number(line.quantity || 0) * Number(line.unit_price || 0), 0))
const activeFilterCount = computed(() => Number(Boolean(filters.status)) + Number(filters.dateRange.length === 2))
const workflowNextAction = computed(() => {
  const labels: Record<string, string> = {
    CONFIRM: "确认客单后检查产品库存",
    PURCHASE: "采购缺口零件并办理入库",
    WAIT_PRIORITY: "等待更近交期客单优先备货",
    PRODUCE: "零件齐套后完成生产入库",
    SHIP: "确认产品出库并完成客单",
    CONFIGURE_BOM: "补充缺货产品的 BOM 配置"
  }
  return labels[workflow.value?.next_action] || "当前无需处理"
})
const orderedQuantity = computed(() => activeOrder.value?.items?.reduce((sum: number, line: any) => sum + Number(line.quantity || 0), 0) || 0)

async function load(silent = false) {
  if (!silent) loading.value = true
  const params = new URLSearchParams()
  if (keyword.value.trim()) params.set("keyword", keyword.value.trim())
  if (filters.status) params.set("status", filters.status)
  if (filters.dateRange.length === 2) {
    params.set("start_date", filters.dateRange[0])
    params.set("end_date", filters.dateRange[1])
  }
  try {
    [rows.value, products.value] = await Promise.all([api(`/api/orders?${params}`), api("/api/products")])
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    if (!silent) loading.value = false
  }
}
function applyFilters() {
  filterDrawer.value = false
  load()
}
function resetFilters() {
  filters.status = ""
  filters.dateRange = []
  applyFilters()
}
function openCreate() {
  Object.assign(form, emptyOrderForm())
  form.items.push({ product_id: undefined, quantity: 1, reference_price: 0, unit_price: 0 })
  drawer.value = true
}
function addLine() {
  form.items.push({ product_id: undefined, quantity: 1, reference_price: 0, unit_price: 0 })
}
function productChanged(line: any) {
  const product = products.value.find(x => x.id === line.product_id)
  line.reference_price = product?.sale_price || 0
  line.unit_price = product?.sale_price || 0
}
function disableRequiredDate(value: Date) {
  return value < new Date(`${form.order_date}T00:00:00`)
}
async function save() {
  if (!form.customer_name.trim()) return ElMessage.warning("请输入客户名称")
  if (!form.required_date || form.required_date < form.order_date) return ElMessage.warning("请选择不早于订单日期的要求交期")
  if (!form.items.length || form.items.some(line => !line.product_id || line.quantity <= 0)) return ElMessage.warning("请完整填写产品明细")
  saving.value = true
  try {
    await api("/api/orders", { method: "POST", body: JSON.stringify(form) })
    ElMessage.success("客单已创建")
    drawer.value = false
    await load()
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    saving.value = false
  }
}
async function openWorkflow(row: any) {
  activeOrder.value = row
  activeDetailTab.value = "overview"
  workflowDrawer.value = true
  workflowLoading.value = true
  try {
    workflow.value = await api(`/api/orders/${row.id}/availability`)
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    workflowLoading.value = false
  }
}
async function action(row: any, type: "confirm" | "prepare" | "fulfill" | "cancel") {
  const labels = { confirm: "确认客单、预留库存并计算 ETA", prepare: "重新计算生产计划", fulfill: "确认产品出库", cancel: "取消客单" }
  try {
    await ElMessageBox.confirm(`确定${labels[type]}“${row.order_no}”吗？`, "客单操作", { type: type === "cancel" ? "warning" : "info" })
    await api(`/api/orders/${row.id}/${type}`, { method: "POST" })
    ElMessage.success(`${labels[type]}成功`)
    await load()
    if (workflowDrawer.value && activeOrder.value?.id === row.id) await openWorkflow(rows.value.find(x => x.id === row.id) || row)
  } catch (error: any) {
    if (error !== "cancel") ElMessage.error(error.message)
  }
}
onMounted(load)
useLiveRefresh(async () => {
  await load(true)
  if (workflowDrawer.value && activeOrder.value) await openWorkflow(activeOrder.value)
})
</script>

<template>
  <div class="erp-page orders-page">
    <ListToolbar
      v-model="keyword"
      placeholder="搜索客单号、客户名称或电话"
      :filter-count="activeFilterCount"
      :loading="loading"
      @search="load"
      @filter="filterDrawer = true"
      @refresh="load"
    >
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>新建客单
      </el-button>
    </ListToolbar>
    <div class="content-card">
      <div class="card-head">
        <h3>客户订单</h3><span>出库后自动写入库存流水</span>
      </div>
      <el-table v-loading="loading" :data="rows" row-key="id" empty-text="暂无符合条件的客户订单">
        <el-table-column label="客单号" min-width="185">
          <template #default="{ row }">
            <span class="mono">{{ row.order_no }}</span>
          </template>
        </el-table-column>
        <el-table-column label="客户" min-width="170">
          <template #default="{ row }">
            <div class="sku-cell">
              <strong>{{ row.customer_name }}</strong><span>{{ row.customer_phone || '未留电话' }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="order_date" label="订单日期" width="115" />
        <el-table-column prop="required_date" label="要求交期" width="115" />
        <el-table-column label="预计完成" width="125">
          <template #default="{ row }">
            <div v-if="row.estimated_completion_at" class="sku-cell">
              <strong :class="row.eta_reliable ? '' : 'number-negative'">{{ formatDate(row.estimated_completion_at) }}</strong>
              <span>{{ row.eta_reliable ? '当前可承诺' : '仅机器排程参考' }}</span>
            </div><span v-else class="muted">待确认 / 待配置产能</span>
          </template>
        </el-table-column>
        <el-table-column label="产品数" width="90" align="right">
          <template #default="{ row }">
            {{ row.items.length }} 项
          </template>
        </el-table-column>
        <el-table-column label="订单金额" width="125" align="right">
          <template #default="{ row }">
            <strong>{{ money(row.total_amount) }}</strong>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="statusMap[row.status]?.type as any" size="small">
              {{ statusMap[row.status]?.label || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="245" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openWorkflow(row)">
              详情
            </el-button><el-button v-if="row.status === 'DRAFT'" link @click="action(row, 'confirm')">
              确认
            </el-button><el-button v-if="row.status === 'READY_TO_SHIP'" link type="success" @click="action(row, 'fulfill')">
              出库
            </el-button><el-button v-if="!['FULFILLED', 'CANCELLED'].includes(row.status)" link type="danger" @click="action(row, 'cancel')">
              取消
            </el-button><span v-if="['FULFILLED', 'CANCELLED'].includes(row.status)" class="muted">已完结</span>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="filterDrawer" title="筛选客户订单" size="min(420px, 92vw)">
      <el-form label-position="top">
        <el-form-item label="订单状态">
          <el-select v-model="filters.status" clearable placeholder="全部状态" style="width:100%">
            <el-option v-for="(meta, key) in statusMap" :key="key" :label="meta.label" :value="key" />
          </el-select>
        </el-form-item>
        <el-form-item label="订单日期">
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

    <el-drawer v-model="workflowDrawer" class="order-workspace-drawer" size="min(1040px, 98vw)">
      <template #header>
        <div class="order-workspace-header">
          <div class="order-workspace-title">
            <strong>客单工作区</strong>
            <span class="mono">{{ activeOrder?.order_no || '' }}</span>
            <el-tag
              v-if="activeOrder"
              :type="statusMap[activeOrder.status]?.type as any"
              size="small"
            >
              {{ statusMap[activeOrder.status]?.label || activeOrder.status }}
            </el-tag>
          </div>
          <div v-if="activeOrder" class="order-workspace-actions">
            <el-button v-if="activeOrder.status === 'DRAFT'" type="primary" @click="action(activeOrder, 'confirm')">
              确认并计算 ETA
            </el-button>
            <el-button v-if="activeOrder.status === 'WAITING_MATERIALS'" type="primary" @click="action(activeOrder, 'prepare')">
              重算生产计划
            </el-button>
            <el-button v-if="activeOrder.status === 'READY_TO_SHIP'" type="success" @click="action(activeOrder, 'fulfill')">
              确认产品出库
            </el-button>
            <el-button v-if="!['FULFILLED', 'CANCELLED'].includes(activeOrder.status)" plain type="danger" @click="action(activeOrder, 'cancel')">
              取消客单
            </el-button>
          </div>
        </div>
      </template>
      <div v-loading="workflowLoading" class="order-workspace-body">
        <el-tabs v-model="activeDetailTab" class="order-detail-tabs">
          <el-tab-pane name="overview">
            <template #label>
              <span class="detail-tab-label">订单概况</span>
            </template>
            <div v-if="activeOrder" class="detail-page">
              <div class="order-overview-strip">
                <div>
                  <span>当前状态</span>
                  <strong>{{ statusMap[activeOrder.status]?.label || activeOrder.status }}</strong>
                </div>
                <div><span>要求交期</span><strong>{{ activeOrder.required_date }}</strong></div>
                <div>
                  <span>预计完成</span>
                  <strong :class="workflow?.eta_reliable ? '' : 'number-negative'">{{ formatDate(workflow?.estimated_completion_at) }}</strong>
                </div>
                <div><span>产品数量</span><strong>{{ productQty(orderedQuantity) }}</strong></div>
                <div><span>订单金额</span><strong>{{ money(activeOrder.total_amount) }}</strong></div>
              </div>
              <div class="detail-section-head">
                <strong>客户与交付信息</strong><span>客单建立时记录的信息</span>
              </div>
              <el-descriptions :column="2" border>
                <el-descriptions-item label="客户">
                  {{ activeOrder.customer_name }}
                </el-descriptions-item><el-descriptions-item label="联系电话">
                  {{ activeOrder.customer_phone || '-' }}
                </el-descriptions-item><el-descriptions-item label="订单日期">
                  {{ activeOrder.order_date }}
                </el-descriptions-item><el-descriptions-item label="要求交期">
                  <b>{{ activeOrder.required_date }}</b>
                </el-descriptions-item><el-descriptions-item label="送货地址" :span="2">
                  {{ activeOrder.customer_address || '-' }}
                </el-descriptions-item><el-descriptions-item label="备注" :span="2">
                  {{ activeOrder.notes || '-' }}
                </el-descriptions-item>
              </el-descriptions>
              <div v-if="workflow" class="detail-section-head">
                <strong>当前处理建议</strong><span>根据库存、交期和 BOM 自动判断</span>
              </div>
              <el-alert
                v-if="workflow && !workflow.eta_reliable"
                :title="workflow.eta_note || '当前预计完成时间缺少可靠生产条件，仅供内部参考。'"
                type="warning"
                :closable="false"
                show-icon
              />
              <div v-if="workflow" class="next-action-card">
                <div class="next-action-icon">
                  <el-icon><Guide /></el-icon>
                </div>
                <div><span>下一步</span><strong>{{ workflowNextAction }}</strong></div>
                <el-button
                  text
                  type="primary"
                  @click="activeDetailTab = ['PURCHASE', 'CONFIGURE_BOM'].includes(workflow.next_action)
                    ? 'materials'
                    : 'inventory'"
                >
                  查看相关信息
                </el-button>
              </div>
            </div>
          </el-tab-pane>
          <el-tab-pane name="pricing">
            <template #label>
              <span class="detail-tab-label">产品与价格 <el-badge :value="activeOrder?.items?.length || 0" /></span>
            </template>
            <div v-if="activeOrder" class="detail-page">
              <div class="detail-section-head detail-section-head-first">
                <strong>成交明细</strong><span>参考价用于比价，本单价格为实际出库成交价</span>
              </div>
              <el-table :data="activeOrder.items" border>
                <el-table-column label="产品" min-width="210">
                  <template #default="{ row }">
                    <div class="sku-cell">
                      <strong>{{ row.product_name }}</strong><span>{{ row.product_sku }}</span>
                    </div>
                  </template>
                </el-table-column><el-table-column label="数量" width="90" align="right">
                  <template #default="{ row }">
                    {{ productQty(row.quantity) }}
                  </template>
                </el-table-column><el-table-column label="参考价" width="120" align="right">
                  <template #default="{ row }">
                    {{ money(row.reference_price) }}
                  </template>
                </el-table-column><el-table-column label="本单价格" width="125" align="right">
                  <template #default="{ row }">
                    <b>{{ money(row.unit_price) }}</b>
                  </template>
                </el-table-column><el-table-column label="折扣" width="90" align="right">
                  <template #default="{ row }">
                    <el-tag :type="row.discount_rate < 100 ? 'warning' : 'info'" size="small" effect="plain">
                      {{ row.discount_rate }}%
                    </el-tag>
                  </template>
                </el-table-column><el-table-column label="优惠" width="120" align="right">
                  <template #default="{ row }">
                    {{ money(row.discount_amount) }}
                  </template>
                </el-table-column><el-table-column label="小计" width="125" align="right">
                  <template #default="{ row }">
                    <b>{{ money(row.line_total) }}</b>
                  </template>
                </el-table-column>
              </el-table>
              <div class="order-price-total">
                <span>客单成交总额</span><strong>{{ money(activeOrder.total_amount) }}</strong>
              </div>
            </div>
          </el-tab-pane>
          <el-tab-pane name="inventory">
            <template #label>
              <span class="detail-tab-label">库存与交付</span>
            </template>
            <div v-if="workflow" class="detail-page">
              <div class="detail-section-head detail-section-head-first">
                <strong>履约进度</strong><span>按照交期优先级自动预留产品库存</span>
              </div>
              <div class="workflow-panel">
                <div class="workflow-steps">
                  <div class="workflow-step active">
                    1 接单
                  </div><div class="workflow-step" :class="{ active: workflow.status !== 'DRAFT' }">
                    2 检查产品库存
                  </div><div class="workflow-step" :class="{ active: ['WAITING_MATERIALS', 'READY_TO_SHIP', 'FULFILLED'].includes(workflow.status) }">
                    3 零件采购/备料
                  </div><div class="workflow-step" :class="{ active: ['READY_TO_SHIP', 'FULFILLED'].includes(workflow.status) }">
                    4 生产并预留
                  </div><div class="workflow-step" :class="{ active: workflow.status === 'FULFILLED' }">
                    5 产品出库
                  </div>
                </div><div class="workflow-summary">
                  <el-tag :type="statusMap[workflow.status]?.type as any">
                    {{ statusMap[workflow.status]?.label || workflow.status }}
                  </el-tag><span>{{ workflowNextAction }}</span>
                </div>
              </div>
              <el-alert
                v-if="workflow.missing_bom.length"
                :title="`有 ${workflow.missing_bom.length} 个缺货产品未配置 BOM，暂不能自动生产。`"
                type="error"
                :closable="false"
                show-icon
              />
              <div class="detail-section-head">
                <strong>产品库存与预留</strong><span>交期相同的客单按下单时间排序</span>
              </div>
              <el-table :data="workflow.product_lines" border empty-text="暂无产品库存信息">
                <el-table-column label="产品" min-width="220">
                  <template #default="{ row }">
                    <div class="sku-cell">
                      <strong>{{ row.name }}</strong><span>{{ row.sku }}</span>
                    </div>
                  </template>
                </el-table-column><el-table-column label="交期优先级" width="140" align="center">
                  <template #default="{ row }">
                    <el-tag :type="row.waiting_for_earlier_orders ? 'warning' : 'success'" size="small">
                      第 {{ row.priority_rank }} / {{ row.priority_total }} 位
                    </el-tag>
                  </template>
                </el-table-column><el-table-column label="订单数量" width="120" align="right">
                  <template #default="{ row }">
                    {{ productQty(row.ordered_quantity) }}
                  </template>
                </el-table-column><el-table-column label="已预留" width="120" align="right">
                  <template #default="{ row }">
                    <b class="number-positive">{{ productQty(row.reserved_quantity) }}</b>
                  </template>
                </el-table-column><el-table-column label="需生产" width="120" align="right">
                  <template #default="{ row }">
                    <b :class="row.production_required ? 'number-negative' : ''">{{ productQty(row.production_required) }}</b>
                  </template>
                </el-table-column><el-table-column label="预计满足" width="170">
                  <template #default="{ row }">
                    <div class="sku-cell"><strong :class="row.eta_reliable ? '' : 'number-negative'">{{ formatDate(row.estimated_completion_at) }}</strong><span>{{ row.eta_note || (row.eta_reliable ? '可承诺' : '暂不可承诺') }}</span></div>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </el-tab-pane>
          <el-tab-pane name="materials">
            <template #label>
              <span class="detail-tab-label">零件与备料 <el-badge v-if="workflow?.material_lines?.length" :value="workflow.material_lines.length" /></span>
            </template>
            <div v-if="workflow" class="detail-page">
              <div class="detail-section-head detail-section-head-first">
                <strong>零件需求与采购</strong><span>按 BOM 汇总全部缺货产品所需零件</span>
              </div>
              <el-alert v-if="workflow.next_action === 'PURCHASE'" title="存在零件缺口：按单采购零件应优先采购，其余零件办理常规入库后可重新检查。" type="warning" :closable="false" show-icon />
              <el-alert
                v-else-if="workflow.next_action === 'CONFIGURE_BOM'"
                title="缺货产品尚未配置 BOM，请先前往产品目录页面补充零件组成。"
                type="error"
                :closable="false"
                show-icon
              />
              <el-table :data="workflow.material_lines" border empty-text="当前无需额外生产，或暂无 BOM 零件需求">
                <el-table-column label="零件" min-width="230">
                  <template #default="{ row }">
                    <div class="sku-cell">
                      <strong>{{ row.name }}</strong><span>{{ row.sku }}</span>
                    </div>
                  </template>
                </el-table-column><el-table-column label="备料方式" width="140">
                  <template #default="{ row }">
                    <el-tag :type="row.supply_mode === 'BUY_TO_ORDER' ? 'warning' : 'info'" size="small" effect="plain">
                      {{ row.supply_mode === 'BUY_TO_ORDER' ? '按单采购' : '库存备料' }}
                    </el-tag>
                  </template>
                </el-table-column><el-table-column label="需要" width="120" align="right">
                  <template #default="{ row }">
                    {{ qty(row.required_quantity) }}
                  </template>
                </el-table-column><el-table-column label="现有" width="120" align="right">
                  <template #default="{ row }">
                    {{ qty(row.available_stock) }}
                  </template>
                </el-table-column><el-table-column label="缺口" width="120" align="right">
                  <template #default="{ row }">
                    <b :class="row.shortage_quantity ? 'number-negative' : 'number-positive'">{{ qty(row.shortage_quantity) }}</b>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </el-tab-pane>
        </el-tabs>
      </div>
    </el-drawer>

    <el-drawer v-model="drawer" title="新建客户订单" size="min(760px, 96vw)">
      <el-form label-position="top">
        <div class="form-grid">
          <el-form-item label="客户名称" required>
            <el-input v-model="form.customer_name" placeholder="公司或联系人名称" />
          </el-form-item>
          <el-form-item label="联系电话">
            <el-input v-model="form.customer_phone" placeholder="手机或座机" />
          </el-form-item>
          <el-form-item label="订单日期">
            <el-date-picker v-model="form.order_date" type="date" value-format="YYYY-MM-DD" style="width:100%" />
          </el-form-item>
          <el-form-item label="要求交期" required>
            <el-date-picker v-model="form.required_date" type="date" value-format="YYYY-MM-DD" :disabled-date="disableRequiredDate" style="width:100%" />
          </el-form-item>
          <el-form-item label="送货地址">
            <el-input v-model="form.customer_address" />
          </el-form-item>
          <el-form-item class="span-2" label="备注">
            <el-input v-model="form.notes" type="textarea" :rows="2" />
          </el-form-item>
        </div>
        <div class="section-label">
          <span>产品明细</span><el-button size="small" plain @click="addLine">
            <el-icon><Plus /></el-icon>添加产品
          </el-button>
        </div>
        <el-table :data="form.items" border>
          <el-table-column label="产品" min-width="260">
            <template #default="{ row: line }">
              <el-select v-model="line.product_id" filterable placeholder="选择产品" style="width:100%" @change="productChanged(line)">
                <el-option
                  v-for="product in products"
                  :key="product.id"
                  :label="`${product.sku} · ${product.name}（库存 ${productQty(product.stock_qty)}）`"
                  :value="product.id"
                  :disabled="form.items.some(x => x !== line && x.product_id === product.id)"
                />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="数量" width="125">
            <template #default="{ row: line }">
              <QuantityInput v-model="line.quantity" integer :min="1" />
            </template>
          </el-table-column>
          <el-table-column label="参考价" width="105" align="right">
            <template #default="{ row: line }">
              {{ money(line.reference_price || 0) }}
            </template>
          </el-table-column>
          <el-table-column label="本单价格" width="135">
            <template #default="{ row: line }">
              <el-input-number v-model="line.unit_price" :min="0" :precision="2" :controls="false" style="width:100%" />
            </template>
          </el-table-column>
          <el-table-column label="折扣" width="80" align="right">
            <template #default="{ row: line }">
              {{ line.reference_price ? Math.round(line.unit_price / line.reference_price * 100) : 100 }}%
            </template>
          </el-table-column>
          <el-table-column label="小计" width="105" align="right">
            <template #default="{ row: line }">
              {{ money(line.quantity * line.unit_price) }}
            </template>
          </el-table-column>
          <el-table-column width="58">
            <template #default="{ $index }">
              <el-button link type="danger" @click="form.items.splice($index, 1)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="line-total">
          订单合计 <strong>{{ money(total) }}</strong>
        </div>
        <div class="drawer-footer">
          <el-button @click="drawer = false">
            取消
          </el-button><el-button type="primary" :loading="saving" @click="save">
            保存为草稿
          </el-button>
        </div>
      </el-form>
    </el-drawer>
  </div>
</template>
