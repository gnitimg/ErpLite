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

const route = useRoute()
const loading = ref(false)
const saving = ref(false)
const itemDrawer = ref(false)
const detailDrawer = ref(false)
const filterDrawer = ref(false)
const direction = ref<Direction>("inbound")
const itemKind = ref<"PART" | "PRODUCT">("PART")
const items = ref<any[]>([])
const rows = ref<any[]>([])
const activeTransaction = ref<any>(null)
const keyword = ref("")
const filters = reactive({ transactionType: "", dateRange: [] as string[] })
const itemForm = reactive({
  item_id: undefined as number | undefined,
  quantity: 1,
  unit_cost: 0,
  notes: ""
})

const isHistory = computed(() => route.meta.stockView === "history")
const selectedItem = computed(() => items.value.find(item => item.id === itemForm.item_id))
const filteredItems = computed(() => items.value.filter(item => item.kind === itemKind.value))
const activeFilterCount = computed(
  () => Number(Boolean(filters.transactionType)) + Number(filters.dateRange.length === 2)
)

function quantityText(item: any, value: number) {
  return stockQty(
    value,
    item?.kind === "PRODUCT" || item?.inventory_scope === "SAMPLE"
  )
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
    [items.value, rows.value] = await Promise.all([
      api("/api/inventory"),
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
  openItemOperation(value)
}

function openItemOperation(value: Direction, item?: any) {
  direction.value = value
  itemKind.value = item?.kind === "PRODUCT" ? "PRODUCT" : "PART"
  Object.assign(itemForm, {
    item_id: item?.id,
    quantity: 1,
    unit_cost: item?.cost_price || 0,
    notes: ""
  })
  itemDrawer.value = true
}

function onItemKindChange() {
  itemForm.item_id = undefined
  itemForm.quantity = 1
  itemForm.unit_cost = 0
}

function onItemChange() {
  itemForm.unit_cost = selectedItem.value?.cost_price || 0
  itemForm.quantity = 1
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

onMounted(load)
useLiveRefresh(() => load(true))
watch(() => route.name, () => load())
</script>

<template>
  <div class="erp-page stock-work-page">
    <template v-if="!isHistory">
      <div class="stock-operation-grid">
        <button
          class="stock-operation-card inbound"
          type="button"
          @click="chooseDirection('inbound')"
        >
          <span class="stock-operation-icon"><el-icon><BottomLeft /></el-icon></span>
          <span>
            <strong>办理物料入库</strong>
            <small>零件采购到货、成品盘盈或其他普通入库</small>
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
            <strong>办理物料出库</strong>
            <small>零件领用、产品非订单出库或库存调整；订单出库请在客户订单中办理</small>
          </span>
          <el-icon class="stock-operation-arrow">
            <ArrowRight />
          </el-icon>
        </button>
      </div>

      <div class="content-card">
        <div class="card-head">
          <h3>当前物料库存</h3>
        </div>
        <el-table v-loading="loading" :data="items" height="420">
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
          <span>共 {{ rows.length }} 条</span>
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
          <div class="material-picker-row">
            <el-select
              v-model="itemKind"
              class="material-kind-select"
              @change="onItemKindChange"
            >
              <el-option label="零件" value="PART" />
              <el-option label="产品" value="PRODUCT" />
            </el-select>
            <el-select
              v-model="itemForm.item_id"
              filterable
              class="material-item-select"
              placeholder="按物料编码或名称搜索"
              @change="onItemChange"
            >
              <el-option
                v-for="item in filteredItems"
                :key="item.id"
                :label="item.kind === 'PART'
                  ? `${item.sku} · ${item.name}（库存 ${qty(item.stock_qty)}）`
                  : `${item.sku} · ${item.name}（可用 ${productQty(item.available_qty)}）`"
                :value="item.id"
              />
            </el-select>
          </div>
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
