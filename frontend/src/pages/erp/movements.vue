<script setup lang="ts">
import { ElMessage, ElMessageBox } from "element-plus"
import { computed, onMounted, reactive, ref, watch } from "vue"
import { useRoute } from "vue-router"
import {
  api,
  formatTime,
  money,
  productQty,
  qty,
  stockQty,
  txLabels,
  useLiveRefresh
} from "./api"
import ListToolbar from "./components/ListToolbar.vue"
import QuantityInput from "./components/QuantityInput.vue"

type Direction = "inbound" | "outbound"
type OperationScope = "item" | "order"

const route = useRoute()
const loading = ref(false)
const saving = ref(false)
const itemDrawer = ref(false)
const orderDrawer = ref(false)
const detailDrawer = ref(false)
const filterDrawer = ref(false)
const direction = ref<Direction>("inbound")
const operationScope = ref<OperationScope>("item")
const items = ref<any[]>([])
const orders = ref<any[]>([])
const rows = ref<any[]>([])
const activeTransaction = ref<any>(null)
const activeOrderWorkflow = ref<any>(null)
const keyword = ref("")
const filters = reactive({ transactionType: "", dateRange: [] as string[] })
const itemForm = reactive({
  item_id: undefined as number | undefined,
  quantity: 1,
  unit_cost: 0,
  notes: ""
})
const orderForm = reactive({
  order_id: undefined as number | undefined,
  notes: ""
})

const isHistory = computed(() => route.meta.stockView === "history")
const selectedItem = computed(() => items.value.find(item => item.id === itemForm.item_id))
const selectedOrder = computed(() => orders.value.find(order => order.id === orderForm.order_id))
const activeFilterCount = computed(
  () => Number(Boolean(filters.transactionType)) + Number(filters.dateRange.length === 2)
)
const candidateOrders = computed(() => orders.value.filter((order) => {
  if (direction.value === "outbound") return order.status === "READY_TO_SHIP"
  return ["CONFIRMED", "WAITING_MATERIALS"].includes(order.status)
}))

function quantityText(item: any, value: number) {
  return stockQty(value, item?.kind === "PRODUCT")
}

async function load(silent = false) {
  if (!silent) loading.value = true
  const params = new URLSearchParams()
  if (keyword.value.trim()) params.set("keyword", keyword.value.trim())
  if (filters.transactionType) params.set("transaction_type", filters.transactionType)
  if (filters.dateRange.length === 2) {
    params.set("start_date", filters.dateRange[0])
    params.set("end_date", filters.dateRange[1])
  }
  try {
    [items.value, orders.value, rows.value] = await Promise.all([
      api("/api/inventory"),
      api("/api/orders"),
      api(`/api/stock/transactions?${params}`)
    ])
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
  filters.transactionType = ""
  filters.dateRange = []
  applyFilters()
}

function chooseDirection(value: Direction) {
  direction.value = value
  if (operationScope.value === "item") openItemOperation(value)
  else openOrderOperation(value)
}

function openItemOperation(value: Direction, item?: any) {
  direction.value = value
  Object.assign(itemForm, {
    item_id: item?.id,
    quantity: 1,
    unit_cost: item?.cost_price || 0,
    notes: ""
  })
  itemDrawer.value = true
}

function openOrderOperation(value: Direction) {
  direction.value = value
  activeOrderWorkflow.value = null
  Object.assign(orderForm, { order_id: undefined, notes: "" })
  orderDrawer.value = true
}

function onItemChange() {
  itemForm.unit_cost = selectedItem.value?.cost_price || 0
  itemForm.quantity = 1
}

async function onOrderChange() {
  activeOrderWorkflow.value = null
  if (!orderForm.order_id) return
  try {
    activeOrderWorkflow.value = await api(`/api/orders/${orderForm.order_id}/availability`)
  } catch (error: any) {
    ElMessage.error(error.message)
  }
}

function openDetail(row: any) {
  activeTransaction.value = row
  detailDrawer.value = true
}

async function saveItemOperation() {
  if (!selectedItem.value || itemForm.quantity <= 0) {
    return ElMessage.warning("请选择物料并填写数量")
  }
  if (selectedItem.value.kind === "PRODUCT" && !Number.isInteger(itemForm.quantity)) {
    return ElMessage.warning("产品数量必须为正整数")
  }
  if (!itemForm.notes.trim()) return ElMessage.warning("请填写本次作业的备注信息")

  const verb = direction.value === "inbound" ? "入库" : "出库"
  const count = quantityText(selectedItem.value, itemForm.quantity)
  try {
    await ElMessageBox.confirm(
      `确认将 ${count} ${selectedItem.value.unit}“${selectedItem.value.name}”办理${verb}吗？`,
      `确认${verb}作业`,
      { type: "warning" }
    )
    saving.value = true
    await api(`/api/stock/${direction.value}`, {
      method: "POST",
      body: JSON.stringify({ ...itemForm, consume_bom: false })
    })
    ElMessage.success(`${verb}作业已完成并生成库存流水`)
    itemDrawer.value = false
    await load()
  } catch (error: any) {
    if (error !== "cancel") ElMessage.error(error.message)
  } finally {
    saving.value = false
  }
}

async function saveOrderOperation() {
  if (!selectedOrder.value) return ElMessage.warning("请选择客户订单")
  const inbound = direction.value === "inbound"
  const action = inbound ? "补齐缺口零件并继续备货" : "将已预留产品出库"
  try {
    await ElMessageBox.confirm(
      `确认按客单“${selectedOrder.value.order_no}”${action}吗？`,
      "确认客单作业",
      { type: "warning" }
    )
    saving.value = true
    const endpoint = inbound
      ? `/api/orders/${selectedOrder.value.id}/receive-materials`
      : `/api/orders/${selectedOrder.value.id}/fulfill`
    await api(endpoint, {
      method: "POST",
      body: JSON.stringify({ notes: orderForm.notes })
    })
    ElMessage.success(inbound ? "客单缺口零件已入库并继续备货" : "客单产品已完成出库")
    orderDrawer.value = false
    await load()
  } catch (error: any) {
    if (error !== "cancel") ElMessage.error(error.message)
  } finally {
    saving.value = false
  }
}

onMounted(load)
useLiveRefresh(() => load(true))
watch(() => route.name, () => load())
</script>

<template>
  <div class="erp-page stock-work-page">
    <template v-if="!isHistory">
      <el-segmented
        v-model="operationScope"
        :options="[
          { label: '按零件 / 产品作业', value: 'item' },
          { label: '按客户订单作业', value: 'order' },
        ]"
        class="operation-scope-switch"
      />

      <div class="stock-operation-grid">
        <button
          class="stock-operation-card inbound"
          type="button"
          @click="chooseDirection('inbound')"
        >
          <span class="stock-operation-icon"><el-icon><BottomLeft /></el-icon></span>
          <span>
            <strong>{{ operationScope === 'item' ? '办理物料入库' : '按客单补料入库' }}</strong>
            <small v-if="operationScope === 'item'">零件采购到货、成品盘盈或其他入库</small>
            <small v-else>自动按 BOM 缺口办理零件入库并继续生产备货</small>
          </span>
          <el-icon class="stock-operation-arrow">
            <ArrowRight />
          </el-icon>
        </button>
        <button
          class="stock-operation-card outbound"
          type="button"
          @click="chooseDirection('outbound')"
        >
          <span class="stock-operation-icon"><el-icon><TopRight /></el-icon></span>
          <span>
            <strong>{{ operationScope === 'item' ? '办理物料出库' : '按客单产品出库' }}</strong>
            <small v-if="operationScope === 'item'">零件领用、产品非客单出库或库存调整</small>
            <small v-else>选择已经完成库存预留的客单并一次性出库</small>
          </span>
          <el-icon class="stock-operation-arrow">
            <ArrowRight />
          </el-icon>
        </button>
      </div>

      <div class="content-card">
        <div class="card-head">
          <h3>{{ operationScope === 'item' ? '当前物料库存' : '待处理客户订单' }}</h3>
          <span>
            {{ operationScope === 'item'
              ? '库存不足用红色显示，不出现负库存'
              : '客单按照要求交期由近到远排列' }}
          </span>
        </div>
        <el-table v-if="operationScope === 'item'" v-loading="loading" :data="items" height="420">
          <el-table-column label="物料" min-width="230">
            <template #default="{ row }">
              <div class="sku-cell">
                <strong>{{ row.name }}</strong>
                <span class="mono">{{ row.sku }} · {{ row.spec || '无规格' }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="90">
            <template #default="{ row }">
              <el-tag :type="row.kind === 'PRODUCT' ? 'primary' : 'info'" size="small" effect="plain">
                {{ row.kind === 'PRODUCT' ? '产品' : '零件' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="实时结存" width="135" align="right">
            <template #default="{ row }">
              <b :class="row.low_stock ? 'number-negative' : 'number-positive'">
                {{ quantityText(row, row.stock_qty) }}
              </b>
              {{ row.unit }}
            </template>
          </el-table-column>
          <el-table-column label="可用库存" width="125" align="right">
            <template #default="{ row }">
              <b :class="row.available_qty <= 0 ? 'number-negative' : ''">
                {{ quantityText(row, row.available_qty ?? row.stock_qty) }} {{ row.unit }}
              </b>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="row.low_stock ? 'danger' : 'success'" size="small">
                {{ row.low_stock ? '库存不足' : '正常' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="快捷作业" width="150" fixed="right">
            <template #default="{ row }">
              <el-button link type="success" @click="openItemOperation('inbound', row)">
                入库
              </el-button>
              <el-button link type="warning" @click="openItemOperation('outbound', row)">
                出库
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-table v-else v-loading="loading" :data="orders" height="420">
          <el-table-column label="客单" min-width="200">
            <template #default="{ row }">
              <span class="mono">{{ row.order_no }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="customer_name" label="客户" min-width="160" />
          <el-table-column prop="required_date" label="要求交期" width="120" />
          <el-table-column label="产品" min-width="220">
            <template #default="{ row }">
              {{ row.items[0]?.product_name || '-' }}
              <span v-if="row.items.length > 1" class="muted">等 {{ row.items.length }} 项</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="120">
            <template #default="{ row }">
              <el-tag :type="row.status === 'READY_TO_SHIP' ? 'success' : 'warning'" size="small">
                {{ row.status === 'READY_TO_SHIP' ? '待出库' : '待备货' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="快捷作业" width="150" fixed="right">
            <template #default="{ row }">
              <el-button
                v-if="row.status === 'READY_TO_SHIP'"
                link
                type="success"
                @click="openOrderOperation('outbound'); orderForm.order_id = row.id; onOrderChange()"
              >
                产品出库
              </el-button>
              <el-button
                v-else-if="['CONFIRMED', 'WAITING_MATERIALS'].includes(row.status)"
                link
                type="primary"
                @click="openOrderOperation('inbound'); orderForm.order_id = row.id; onOrderChange()"
              >
                补料入库
              </el-button>
              <span v-else class="muted">无需处理</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </template>

    <template v-else>
      <ListToolbar
        v-model="keyword"
        placeholder="搜索流水号、物料编码/名称或备注"
        :filter-count="activeFilterCount"
        :loading="loading"
        @filter="filterDrawer = true"
        @refresh="load"
        @search="load"
      />
      <div class="content-card">
        <div class="card-head">
          <h3>库存流水</h3>
          <span>最近 {{ rows.length }} 条 · 点击详情查看完整信息</span>
        </div>
        <el-table v-loading="loading" :data="rows">
          <el-table-column label="流水号" min-width="190">
            <template #default="{ row }">
              <span class="mono">{{ row.transaction_no }}</span>
            </template>
          </el-table-column>
          <el-table-column label="发生时间" width="175">
            <template #default="{ row }">
              <span class="muted">{{ formatTime(row.occurred_at) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="业务类型" width="120">
            <template #default="{ row }">
              <el-tag effect="plain" size="small">
                {{ txLabels[row.transaction_type] || row.transaction_type }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="物料摘要" min-width="300">
            <template #default="{ row }">
              <span>{{ row.lines[0]?.name || '-' }}</span>
              <span v-if="row.lines.length > 1" class="muted"> 等 {{ row.lines.length }} 项</span>
              <template v-else-if="row.lines.length === 1">
                <el-tag
                  :type="row.lines[0].quantity_change > 0 ? 'success' : 'warning'"
                  size="small"
                  effect="plain"
                >
                  {{ row.lines[0].quantity_change > 0 ? '入库' : '出库' }}
                  {{ quantityText(row.lines[0], Math.abs(row.lines[0].quantity_change)) }}
                  {{ row.lines[0].unit }}
                </el-tag>
              </template>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="90" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openDetail(row)">
                详情
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </template>

    <el-drawer v-model="filterDrawer" title="筛选库存流水" size="min(420px, 92vw)">
      <el-form label-position="top">
        <el-form-item label="业务类型">
          <el-select v-model="filters.transactionType" clearable placeholder="全部类型" style="width: 100%">
            <el-option
              v-for="(label, key) in txLabels"
              :key="key"
              :label="label"
              :value="key"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="发生日期">
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
          </el-button>
          <el-button type="primary" @click="applyFilters">
            应用筛选
          </el-button>
        </div>
      </el-form>
    </el-drawer>

    <el-drawer
      v-model="itemDrawer"
      :title="direction === 'inbound' ? '按物料办理入库' : '按物料办理出库'"
      size="min(600px, 96vw)"
    >
      <el-form label-position="top">
        <el-alert
          :title="direction === 'inbound'
            ? '产品生产请使用“产品生产”页面；这里的成品入库不会扣减 BOM。'
            : '产品出库会校验客单预留，已预留库存不能被占用。'"
          type="info"
          :closable="false"
          show-icon
          class="drawer-alert"
        />
        <el-form-item label="物料" required>
          <el-select
            v-model="itemForm.item_id"
            filterable
            placeholder="按编码或名称选择物料"
            style="width: 100%"
            @change="onItemChange"
          >
            <el-option-group label="零件">
              <el-option
                v-for="item in items.filter(row => row.kind === 'PART')"
                :key="item.id"
                :label="`${item.sku} · ${item.name}（库存 ${qty(item.stock_qty)}）`"
                :value="item.id"
              />
            </el-option-group>
            <el-option-group label="产品">
              <el-option
                v-for="item in items.filter(row => row.kind === 'PRODUCT')"
                :key="item.id"
                :label="`${item.sku} · ${item.name}（可用 ${productQty(item.available_qty)}）`"
                :value="item.id"
              />
            </el-option-group>
          </el-select>
        </el-form-item>
        <div class="form-grid">
          <el-form-item :label="`作业数量${selectedItem ? `（${selectedItem.unit}）` : ''}`" required>
            <QuantityInput
              v-model="itemForm.quantity"
              :integer="selectedItem?.kind === 'PRODUCT'"
              :min="selectedItem?.kind === 'PRODUCT' ? 1 : 0.001"
              :unit="selectedItem?.unit"
            />
            <div class="form-help">
              达到 10,000 后自动显示为“万”，数据库仍保存原始数量。
            </div>
          </el-form-item>
          <el-form-item v-if="direction === 'inbound'" label="入库单位成本">
            <el-input-number
              v-model="itemForm.unit_cost"
              :min="0"
              :precision="2"
              :controls="false"
              style="width: 100%"
            />
          </el-form-item>
        </div>
        <div v-if="selectedItem" class="stock-operation-preview">
          <div>
            <span>当前结存</span>
            <strong>{{ quantityText(selectedItem, selectedItem.stock_qty) }} {{ selectedItem.unit }}</strong>
          </div>
          <div v-if="selectedItem.kind === 'PRODUCT'">
            <span>客单预留</span>
            <strong>{{ productQty(selectedItem.reserved_qty) }} {{ selectedItem.unit }}</strong>
          </div>
          <div>
            <span>作业后预计</span>
            <strong
              :class="direction === 'outbound'
                && itemForm.quantity > (selectedItem.available_qty ?? selectedItem.stock_qty)
                ? 'number-negative'
                : 'number-positive'"
            >
              {{ quantityText(
                selectedItem,
                Number(selectedItem.stock_qty)
                  + (direction === 'inbound' ? Number(itemForm.quantity) : -Number(itemForm.quantity)),
              ) }}
              {{ selectedItem.unit }}
            </strong>
          </div>
        </div>
        <el-form-item label="作业备注" required>
          <el-input
            v-model="itemForm.notes"
            type="textarea"
            :rows="4"
            :placeholder="direction === 'inbound'
              ? '请填写供应商、批次、到货单号或入库原因'
              : '请填写领用部门、领用人、用途或出库原因'"
          />
        </el-form-item>
        <div v-if="selectedItem && direction === 'inbound'" class="line-total">
          入库金额 <strong>{{ money(itemForm.quantity * itemForm.unit_cost) }}</strong>
        </div>
        <div class="drawer-footer">
          <el-button @click="itemDrawer = false">
            取消
          </el-button>
          <el-button type="primary" :loading="saving" @click="saveItemOperation">
            确认{{ direction === 'inbound' ? '入库' : '出库' }}
          </el-button>
        </div>
      </el-form>
    </el-drawer>

    <el-drawer
      v-model="orderDrawer"
      :title="direction === 'inbound' ? '按客单补料入库' : '按客单产品出库'"
      size="min(720px, 96vw)"
    >
      <el-form label-position="top">
        <el-form-item label="客户订单" required>
          <el-select
            v-model="orderForm.order_id"
            filterable
            placeholder="选择待处理客单"
            style="width: 100%"
            @change="onOrderChange"
          >
            <el-option
              v-for="order in candidateOrders"
              :key="order.id"
              :label="`${order.order_no} · ${order.customer_name} · 交期 ${order.required_date}`"
              :value="order.id"
            />
          </el-select>
        </el-form-item>
        <el-alert
          v-if="direction === 'inbound'"
          title="系统将按 BOM 自动补齐该客单的零件缺口，并继续执行生产和产品预留。"
          type="info"
          :closable="false"
          show-icon
          class="drawer-alert"
        />
        <el-alert
          v-else
          title="只显示已经全部预留产品的客单；确认后一次性生成客单出库流水。"
          type="success"
          :closable="false"
          show-icon
          class="drawer-alert"
        />
        <template v-if="activeOrderWorkflow">
          <div class="detail-section-head">
            <strong>{{ direction === 'inbound' ? '待入库零件' : '待出库产品' }}</strong>
            <span>{{ selectedOrder?.order_no }}</span>
          </div>
          <el-table
            :data="direction === 'inbound'
              ? activeOrderWorkflow.material_lines.filter((line: any) => line.shortage_quantity > 0)
              : activeOrderWorkflow.product_lines"
            border
            empty-text="当前客单没有需要处理的物料"
          >
            <el-table-column label="物料" min-width="230">
              <template #default="{ row }">
                <div class="sku-cell">
                  <strong>{{ row.name }}</strong><span>{{ row.sku }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column
              :label="direction === 'inbound' ? '缺口数量' : '出库数量'"
              width="130"
              align="right"
            >
              <template #default="{ row }">
                <b>{{ direction === 'inbound' ? qty(row.shortage_quantity) : productQty(row.ordered_quantity) }}</b>
                {{ row.unit }}
              </template>
            </el-table-column>
          </el-table>
        </template>
        <el-form-item label="作业备注" class="order-operation-notes">
          <el-input
            v-model="orderForm.notes"
            type="textarea"
            :rows="3"
            placeholder="供应商、到货单号、承运信息或其他说明"
          />
        </el-form-item>
        <div class="drawer-footer">
          <el-button @click="orderDrawer = false">
            取消
          </el-button>
          <el-button
            type="primary"
            :loading="saving"
            :disabled="!selectedOrder"
            @click="saveOrderOperation"
          >
            确认{{ direction === 'inbound' ? '补料入库' : '客单出库' }}
          </el-button>
        </div>
      </el-form>
    </el-drawer>

    <el-drawer v-model="detailDrawer" title="库存流水详情" size="min(720px, 96vw)">
      <template v-if="activeTransaction">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="流水号" :span="2">
            <span class="mono">{{ activeTransaction.transaction_no }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="业务类型">
            {{ txLabels[activeTransaction.transaction_type] || activeTransaction.transaction_type }}
          </el-descriptions-item>
          <el-descriptions-item label="发生时间">
            {{ formatTime(activeTransaction.occurred_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="关联客单" :span="2">
            <span class="mono">{{ activeTransaction.related_order_no || '无' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="备注" :span="2">
            {{ activeTransaction.notes || '无' }}
          </el-descriptions-item>
        </el-descriptions>
        <div class="detail-section-head">
          <strong>物料流水</strong>
          <span>使用出库/入库方向显示，不使用负数</span>
        </div>
        <el-table :data="activeTransaction.lines" border>
          <el-table-column label="物料" min-width="200">
            <template #default="{ row }">
              <div class="sku-cell">
                <strong>{{ row.name }}</strong>
                <span class="mono">{{ row.sku }} · {{ row.kind === 'PRODUCT' ? '产品' : '零件' }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="方向" width="90">
            <template #default="{ row }">
              <el-tag :type="row.quantity_change > 0 ? 'success' : 'warning'" size="small">
                {{ row.quantity_change > 0 ? '入库' : '出库' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="数量" width="130" align="right">
            <template #default="{ row }">
              <b>{{ quantityText(row, Math.abs(row.quantity_change)) }} {{ row.unit }}</b>
            </template>
          </el-table-column>
          <el-table-column label="单位成本" width="120" align="right">
            <template #default="{ row }">
              {{ money(row.unit_cost) }}
            </template>
          </el-table-column>
          <el-table-column label="变动金额" width="130" align="right">
            <template #default="{ row }">
              {{ money(Math.abs(row.quantity_change * row.unit_cost)) }}
            </template>
          </el-table-column>
        </el-table>
      </template>
    </el-drawer>
  </div>
</template>
