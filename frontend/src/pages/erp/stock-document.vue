<script setup lang="ts">
import { ElMessage } from "element-plus"
import { computed, onMounted, reactive, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { api, money, qty, useLiveRefresh } from "./api"
import QuantityInput from "./components/QuantityInput.vue"
import { printWithSavedSize } from "./print"

type Direction = "INBOUND" | "OUTBOUND"

interface DocumentLine {
  item_id?: number
  order_item_id?: number
  quantity: number
  unit_price: number
}

const props = withDefaults(defineProps<{
  embedded?: boolean
  initialDirection?: Direction
  initialOrderId?: number
}>(), {
  embedded: false,
  initialDirection: "INBOUND",
  initialOrderId: 0
})
const emit = defineEmits<{
  saved: [payload: { direction: Direction, scope: string, keyword: string }]
  view: [payload: { direction: Direction, scope: string, keyword: string }]
}>()

const route = useRoute()
const router = useRouter()
const saving = ref(false)
const loading = ref(false)
const inventory = ref<any[]>([])
const linkedOrder = ref<any>(null)
const documentNo = ref("提交后自动生成")
const direction = ref<Direction>(props.initialDirection)
const directionOptions = [
  { label: "入库", value: "INBOUND" },
  { label: "出库", value: "OUTBOUND" }
]
const today = () => new Date().toISOString().slice(0, 10)
const form = reactive({
  counterparty_name: "",
  counterparty_phone: "",
  counterparty_address: "",
  occurred_date: today(),
  operator: "",
  notes: "",
  items: [] as DocumentLine[]
})

const orderId = computed(() => {
  if (Number.isInteger(props.initialOrderId) && props.initialOrderId > 0) {
    return props.initialOrderId
  }
  const value = Number(route.query.order_id)
  return Number.isInteger(value) && value > 0 ? value : 0
})
const title = computed(() => direction.value === "INBOUND" ? "入库单" : "出库单")
const counterpartyLabel = computed(() => direction.value === "INBOUND" ? "供应商" : "收货单位")
const totalQuantity = computed(() => form.items.reduce((sum, line) => sum + Number(line.quantity || 0), 0))
const totalReplacement = computed(() => form.items.reduce((sum, line) => sum + replacementQty(line), 0))
const totalAmount = computed(() => form.items.reduce(
  (sum, line) => sum + originalQty(line) * Number(line.unit_price || 0),
  0
))
const availableItems = computed(() => {
  if (!linkedOrder.value) return inventory.value
  const productIds = new Set(linkedOrder.value.items.map((line: any) => Number(line.product_id)))
  return inventory.value.filter(item => productIds.has(Number(item.id)))
})

function itemOf(line: any) {
  return inventory.value.find(item => Number(item.id) === Number(line.item_id))
}

function addLine() {
  form.items.push({ quantity: 1, unit_price: 0 })
}

function clearLine(line: any) {
  line.item_id = undefined
  line.order_item_id = undefined
  line.quantity = 1
  line.unit_price = 0
}

function clearAll() {
  form.items.splice(0, form.items.length, { quantity: 1, unit_price: 0 })
  documentNo.value = "提交后自动生成"
}

function itemChanged(line: any) {
  const item = itemOf(line)
  if (!item) return
  const orderLine = linkedOrder.value?.items.find(
    (candidate: any) => Number(candidate.product_id) === Number(line.item_id)
  )
  line.order_item_id = orderLine?.id
  line.unit_price = Number(
    orderLine?.unit_price
      ?? (direction.value === "INBOUND" ? item.cost_price : item.sale_price)
      ?? 0
  )
  if (orderLine) {
    line.quantity = Math.min(
      Number(orderLine.remaining_quantity || 0),
      Number(orderLine.reserved_quantity || 0)
    )
  }
  documentNo.value = "提交后自动生成"
}

/** 本行中属于换货补发的数量：超出原单剩余（quantity - shipped）的部分。 */
function replacementQty(line: any) {
  if (!linkedOrder.value || !line.order_item_id) return 0
  const orderLine = linkedOrder.value.items.find(
    (candidate: any) => Number(candidate.id) === Number(line.order_item_id)
  )
  if (!orderLine) return 0
  const originalRemaining = Math.max(
    Number(orderLine.quantity || 0) - Number(orderLine.shipped_quantity || 0), 0
  )
  return Math.max(0, Number(line.quantity || 0) - originalRemaining)
}

/** 本行按原单计价的数量（换货补发不产生销售金额）。 */
function originalQty(line: any) {
  return Math.max(0, Number(line.quantity || 0) - replacementQty(line))
}

function savedPayload() {
  return {
    direction: direction.value,
    scope: itemOf(form.items.find(line => line.item_id) || {})?.kind || "PART",
    keyword: documentNo.value
  }
}

function applyOrder(order: any) {
  linkedOrder.value = order
  direction.value = "OUTBOUND"
  form.counterparty_name = order.customer_name || ""
  form.counterparty_phone = order.customer_phone || ""
  form.counterparty_address = order.customer_address || ""
  form.notes = `客户订单 ${order.order_no} 出库`
  form.items = order.items
    .filter((line: any) => Number(line.remaining_quantity) > 0)
    .map((line: any) => ({
      item_id: Number(line.product_id),
      order_item_id: Number(line.id),
      quantity: Math.min(
        Number(line.remaining_quantity || 0),
        Number(line.reserved_quantity || 0)
      ),
      unit_price: Number(line.unit_price || 0)
    }))
  if (!form.items.length) addLine()
}

async function loadInventory(silent = false) {
  if (!silent) loading.value = true
  try {
    inventory.value = await api("/api/inventory")
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    if (!silent) loading.value = false
  }
}

async function initialise() {
  await loadInventory()
  if (orderId.value) {
    try {
      applyOrder(await api(`/api/orders/${orderId.value}`))
    } catch (error: any) {
      ElMessage.error(error.message)
    }
  } else if (!form.items.length) {
    addLine()
  }
}

function validateLines() {
  const lines = form.items.filter(line => line.item_id)
  if (!lines.length) {
    ElMessage.warning("请至少填写一项物料")
    return null
  }
  if (lines.some(line => Number(line.quantity) <= 0)) {
    ElMessage.warning("物料数量必须大于 0")
    return null
  }
  const ids = lines.map(line => Number(line.item_id))
  if (new Set(ids).size !== ids.length) {
    ElMessage.warning("同一张单据不能重复添加相同物料")
    return null
  }
  if (lines.some(line => itemOf(line)?.kind === "PRODUCT" && !Number.isInteger(Number(line.quantity)))) {
    ElMessage.warning("产品数量必须是整数")
    return null
  }
  return lines
}

async function submit() {
  const lines = validateLines()
  if (!lines) return
  saving.value = true
  try {
    if (linkedOrder.value) {
      const result = await api(`/api/orders/${linkedOrder.value.id}/ship`, {
        method: "POST",
        body: JSON.stringify({
          items: lines.map(line => ({
            order_item_id: line.order_item_id,
            quantity: Number(line.quantity),
            unit_price: Number(line.unit_price || 0)
          })),
          counterparty_name: form.counterparty_name,
          counterparty_phone: form.counterparty_phone,
          counterparty_address: form.counterparty_address,
          occurred_date: form.occurred_date,
          operator: form.operator,
          notes: form.notes
        })
      })
      documentNo.value = result.transaction_no
    } else {
      const result = await api("/api/stock/documents", {
        method: "POST",
        body: JSON.stringify({
          direction: direction.value,
          counterparty_name: form.counterparty_name,
          counterparty_phone: form.counterparty_phone,
          counterparty_address: form.counterparty_address,
          occurred_date: form.occurred_date,
          operator: form.operator,
          notes: form.notes,
          items: lines.map(line => ({
            item_id: line.item_id,
            quantity: Number(line.quantity),
            unit_price: Number(line.unit_price || 0)
          }))
        })
      })
      documentNo.value = result.transaction_no
    }
    ElMessage.success(`${title.value}已保存，库存与单据记录已同步更新`)
    await loadInventory(true)
    emit("saved", savedPayload())
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    saving.value = false
  }
}

function viewDocument() {
  if (documentNo.value === "提交后自动生成") return
  const payload = savedPayload()
  if (props.embedded) {
    emit("view", payload)
    return
  }
  router.push({
    path: linkedOrder.value ? "/lite-orders/documents" : "/lite-stock-documents/list",
    query: {
      keyword: payload.keyword,
      scope: payload.scope,
      ...(!linkedOrder.value && {
        direction: direction.value === "INBOUND" ? "inbound" : "outbound"
      })
    }
  })
}

async function printDocument() {
  await printWithSavedSize()
}

watch(direction, () => {
  if (linkedOrder.value) direction.value = "OUTBOUND"
  documentNo.value = "提交后自动生成"
})

onMounted(initialise)
useLiveRefresh(() => loadInventory(true))
</script>

<template>
  <div
    :class="['stock-document-page', { 'erp-page': !embedded, embedded }]"
    v-loading="loading"
  >
    <section class="content-card document-card">
      <header v-if="!embedded || linkedOrder" class="card-head document-card-head">
        <div>
          <h3 v-if="!embedded">出入库开单</h3>
          <p v-if="linkedOrder" class="order-hint">由客户订单 {{ linkedOrder.order_no }} 回填，提交后同步更新订单状态</p>
        </div>
        <el-segmented
          v-if="!embedded"
          v-model="direction"
          :options="directionOptions"
          :disabled="Boolean(linkedOrder)"
          class="direction-switch no-print"
        />
      </header>

      <div class="document-sheet">
        <div class="document-title-row">
          <h1>{{ title }}</h1>
          <div class="document-number"><span>单据编号</span><strong>{{ documentNo }}</strong></div>
        </div>

        <div class="document-meta">
          <label>
            <span>{{ counterpartyLabel }}</span>
            <el-input v-model="form.counterparty_name" class="no-print" :placeholder="`请输入${counterpartyLabel}`" />
            <strong class="print-only">{{ form.counterparty_name || '-' }}</strong>
          </label>
          <label>
            <span>联系电话</span>
            <el-input v-model="form.counterparty_phone" class="no-print" placeholder="选填" />
            <strong class="print-only">{{ form.counterparty_phone || '-' }}</strong>
          </label>
          <label>
            <span>日期</span>
            <el-date-picker
              v-model="form.occurred_date"
              type="date"
              value-format="YYYY-MM-DD"
              format="YYYY-MM-DD"
              class="no-print"
              style="width: 100%"
            />
            <strong class="print-only">{{ form.occurred_date }}</strong>
          </label>
          <label class="address-field">
            <span>{{ direction === 'INBOUND' ? '供应商地址' : '收货地址' }}</span>
            <el-input v-model="form.counterparty_address" class="no-print" placeholder="选填" />
            <strong class="print-only">{{ form.counterparty_address || '-' }}</strong>
          </label>
        </div>

        <div class="line-actions no-print">
          <span>物料明细</span>
          <div>
            <el-button @click="addLine">添加一行</el-button>
            <el-button type="danger" plain @click="clearAll">全部清空</el-button>
          </div>
        </div>

        <el-table :data="form.items" border class="document-lines">
          <el-table-column type="index" label="序号" width="64" align="center" />
          <el-table-column label="物料编码 / 名称" min-width="280">
            <template #default="{ row }">
              <el-select
                v-model="row.item_id"
                class="no-print"
                filterable
                placeholder="搜索编码或名称"
                style="width: 100%"
                @change="itemChanged(row)"
              >
                <el-option
                  v-for="item in availableItems"
                  :key="item.id"
                  :label="`${item.sku} · ${item.name}`"
                  :value="item.id"
                />
              </el-select>
              <span class="print-only">{{ itemOf(row) ? `${itemOf(row).sku} · ${itemOf(row).name}` : '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="规格型号" min-width="150">
            <template #default="{ row }">{{ itemOf(row)?.spec || '-' }}</template>
          </el-table-column>
          <el-table-column label="单位" width="80" align="center">
            <template #default="{ row }">{{ itemOf(row)?.unit || '-' }}</template>
          </el-table-column>
          <el-table-column label="数量" width="170">
            <template #default="{ row }">
              <QuantityInput
                v-model="row.quantity"
                class="no-print"
                :integer="itemOf(row)?.kind === 'PRODUCT'"
                :min="0"
              />
              <span class="print-only">
                {{ qty(row.quantity) }}<template v-if="replacementQty(row) > 0">（换货 {{ replacementQty(row) }}）</template>
              </span>
            </template>
          </el-table-column>
          <el-table-column label="单价" width="150">
            <template #default="{ row }">
              <el-input-number v-model="row.unit_price" class="no-print" :min="0" :precision="2" :controls="false" />
              <span class="print-only">{{ money(row.unit_price) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="金额" width="120" align="right">
            <template #default="{ row }">{{ money(originalQty(row) * Number(row.unit_price || 0)) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="82" align="center" class-name="no-print">
            <template #default="{ row }">
              <el-button link type="danger" @click="clearLine(row)">清空</el-button>
            </template>
          </el-table-column>
        </el-table>

        <div class="document-summary">
          <div v-if="totalReplacement > 0"><span>其中换货</span><strong>{{ qty(totalReplacement) }}</strong></div>
          <div><span>数量合计</span><strong>{{ qty(totalQuantity) }}</strong></div>
          <div><span>金额合计</span><strong>{{ money(totalAmount) }}</strong></div>
        </div>

        <div class="document-footer-fields">
          <label><span>经办人</span><el-input v-model="form.operator" class="no-print" placeholder="选填" /><strong class="print-only">{{ form.operator || '-' }}</strong></label>
          <label class="notes-field"><span>备注</span><el-input v-model="form.notes" class="no-print" placeholder="填写本单说明" /><strong class="print-only">{{ form.notes || '-' }}</strong></label>
        </div>
        <div class="signature-row">
          <span>制单：________________</span>
          <span>仓管：________________</span>
          <span>审核：________________</span>
        </div>
      </div>

      <footer class="document-actions no-print">
        <el-button v-if="documentNo !== '提交后自动生成'" @click="viewDocument">查看已保存单据</el-button>
        <el-button @click="printDocument">打印</el-button>
        <el-button type="primary" :loading="saving" @click="submit">保存并{{ direction === 'INBOUND' ? '入库' : '出库' }}</el-button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
@page { size: 297mm 210mm; margin: 0; }
.document-card { overflow: hidden; }
.stock-document-page.embedded {
  padding: 0;
}
.stock-document-page.embedded .document-card {
  border: 0;
  border-radius: 0;
  box-shadow: none;
}
.stock-document-page.embedded .document-sheet {
  margin-top: 4px;
}
.document-card-head { display: flex; align-items: center; justify-content: space-between; gap: 24px; }
.document-card-head h3 { margin: 0; }
.order-hint { margin: 6px 0 0; color: var(--el-text-color-secondary); font-size: 13px; }
.direction-switch { flex: none; align-self: center; }
.document-sheet { margin: 24px; padding: 28px 32px; border: 1px solid var(--el-border-color); background: var(--el-bg-color); }
.document-title-row { display: grid; grid-template-columns: 1fr auto 1fr; align-items: end; margin-bottom: 24px; }
.document-title-row h1 { grid-column: 2; margin: 0; font-size: 28px; letter-spacing: .35em; text-indent: .35em; color: var(--el-text-color-primary); }
.document-number { grid-column: 3; display: flex; justify-content: flex-end; align-items: baseline; gap: 10px; font-size: 13px; }
.document-number strong { min-width: 180px; text-align: right; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
.document-meta { display: grid; grid-template-columns: 1.2fr 1fr 1fr; gap: 14px 20px; margin-bottom: 20px; }
.document-meta label, .document-footer-fields label { display: grid; grid-template-columns: auto 1fr; align-items: center; gap: 10px; }
.document-meta label > span, .document-footer-fields label > span { white-space: nowrap; color: var(--el-text-color-regular); }
.address-field { grid-column: 1 / -1; }
.line-actions { display: flex; align-items: center; justify-content: space-between; margin: 14px 0 10px; font-weight: 600; }
.document-lines :deep(.el-input-number) { width: 100%; }
.document-summary { display: flex; justify-content: flex-end; gap: 42px; padding: 16px 12px; border: 1px solid var(--el-border-color); border-top: 0; }
.document-summary div { display: flex; gap: 14px; }
.document-summary strong { min-width: 90px; text-align: right; }
.document-footer-fields { display: grid; grid-template-columns: 1fr 2fr; gap: 20px; margin-top: 20px; }
.signature-row { display: flex; justify-content: space-between; gap: 32px; margin-top: 30px; color: var(--el-text-color-regular); }
.document-actions { display: flex; justify-content: flex-end; gap: 10px; padding: 0 24px 24px; }
.print-only { display: none; }
@media (max-width: 900px) {
  .document-sheet { margin: 16px; padding: 20px; overflow-x: auto; }
  .document-title-row { grid-template-columns: 1fr; gap: 12px; }
  .document-title-row h1, .document-number { grid-column: 1; justify-self: start; }
  .document-meta, .document-footer-fields { grid-template-columns: 1fr; }
  .address-field { grid-column: 1; }
  .signature-row { flex-direction: column; }
}
@media print {
  :global(html), :global(body) { width: var(--erp-print-page-width, 297mm); height: var(--erp-print-page-height, 210mm); margin: 0 !important; overflow: visible !important; background: #fff !important; }
  :global(body *) { visibility: hidden !important; }
  .document-sheet, .document-sheet * { visibility: visible !important; }
  .document-sheet { position: absolute; top: var(--erp-print-margin, 8mm); left: var(--erp-print-margin, 8mm); width: 277mm; margin: 0; padding: 0; border: 0; overflow: visible; color: #000; background: #fff; transform: scale(var(--erp-print-scale, 1)); transform-origin: top left; print-color-adjust: exact; }
  .no-print, :deep(.no-print) { display: none !important; }
  .print-only { display: inline !important; color: #000; font-weight: 500; }
  .document-title-row { grid-template-columns: 1fr auto 1fr; gap: 0; }
  .document-title-row h1 { grid-column: 2; justify-self: stretch; }
  .document-number { grid-column: 3; justify-self: stretch; }
  .document-meta { grid-template-columns: 1.2fr 1fr 1fr; }
  .address-field { grid-column: 1 / -1; }
  .document-footer-fields { grid-template-columns: 1fr 2fr; }
  .signature-row { flex-direction: row; }
  .document-meta label, .document-footer-fields label { grid-template-columns: auto 1fr; min-height: 32px; border-bottom: 1px solid #d7dce3; }
  .document-lines :deep(.el-table__inner-wrapper::before) { background-color: #606266; }
}
</style>
