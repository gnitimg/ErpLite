<script setup lang="ts">
import { ElMessage } from "element-plus"
import { computed, nextTick, onMounted, reactive, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { api, money, qty, useLiveRefresh } from "./api"
import QuantityInput from "./components/QuantityInput.vue"
import PrintBrandHeader from "./components/PrintBrandHeader.vue"
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
const successDialog = ref(false)
const savedDirection = ref<Direction | null>(null)
const savedDocumentNo = ref("")
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
const successTitle = computed(() => savedDirection.value === "INBOUND" ? "入库成功" : "出库成功")
const savedDocumentTitle = computed(() => savedDirection.value === "INBOUND" ? "入库单" : "出库单")
const counterpartyLabel = computed(() => direction.value === "INBOUND" ? "供应商" : "收货单位")
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

/** 打印表格里"物料及规格型号"列的文本。 */
function itemLabel(item: any) {
  return [item.sku, item.name, item.spec].filter(Boolean).join(" · ")
}

/** 日期打印格式：2026 年 8 月 29 日。 */
function chineseDate(value: string) {
  if (!value) return "-"
  const [year, month, day] = value.split("-")
  return `${year} 年 ${Number(month)} 月 ${Number(day)} 日`
}

function addLine() {
  form.items.push({ quantity: 1, unit_price: 0 })
}

/** 纸质单据版面：明细区固定至少 5 行，不足补空行。 */
function ensureMinLines(min = 5) {
  while (form.items.length < min) addLine()
}

function clearLine(line: any) {
  line.item_id = undefined
  line.order_item_id = undefined
  line.quantity = 1
  line.unit_price = 0
}

function clearAll() {
  form.items.splice(0, form.items.length, { quantity: 1, unit_price: 0 })
  ensureMinLines()
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
  ensureMinLines()
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
    let result: any
    if (linkedOrder.value) {
      result = await api(`/api/orders/${linkedOrder.value.id}/ship`, {
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
    } else {
      result = await api("/api/stock/documents", {
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
    }
    documentNo.value = result.transaction_no
    savedDocumentNo.value = result.transaction_no
    savedDirection.value = direction.value
    successDialog.value = true
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

async function printSavedDocument() {
  successDialog.value = false
  await nextTick()
  await printDocument()
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
        <div class="document-head">
          <PrintBrandHeader class="head-brand" />
          <h1>{{ title }}</h1>
          <div class="document-number"><span>NO.</span><strong>{{ documentNo }}</strong></div>
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
            <strong class="print-only">{{ chineseDate(form.occurred_date) }}</strong>
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

        <table class="doc-table document-lines">
          <colgroup>
            <col class="col-idx">
            <col>
            <col class="col-qty">
            <col class="col-unit">
            <col class="col-price">
            <col class="col-sub">
            <col class="col-remark">
          </colgroup>
          <thead>
            <tr>
              <th class="ta-c">序号</th>
              <th class="ta-c">物料及规格型号</th>
              <th class="ta-c">数量</th>
              <th class="ta-c">单位</th>
              <th class="ta-c">单价</th>
              <th class="ta-c">小计</th>
              <th class="ta-c">备注</th>
              <th class="ta-c no-print">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, index) in form.items" :key="index">
              <td class="ta-c">{{ index + 1 }}</td>
              <td>
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
                <span class="print-only ta-c">{{ itemOf(row) ? itemLabel(itemOf(row)) : '' }}</span>
              </td>
              <td class="ta-r">
                <QuantityInput
                  v-model="row.quantity"
                  class="no-print"
                  :integer="itemOf(row)?.kind === 'PRODUCT'"
                  :min="0"
                />
                <span class="print-only">{{ qty(row.quantity) }}</span>
              </td>
              <td class="ta-c">{{ itemOf(row)?.unit || '' }}</td>
              <td class="ta-r">
                <el-input-number v-model="row.unit_price" class="no-print" :min="0" :precision="2" :controls="false" />
                <span class="print-only">{{ money(row.unit_price) }}</span>
              </td>
              <td class="ta-r">{{ money(originalQty(row) * Number(row.unit_price || 0)) }}</td>
              <td class="ta-l">
                <span v-if="replacementQty(row) > 0">换货 {{ replacementQty(row) }}</span>
              </td>
              <td class="ta-c no-print">
                <el-button link type="danger" @click="clearLine(row)">清空</el-button>
              </td>
            </tr>
          </tbody>
          <tfoot>
            <tr>
              <td colspan="2" class="ta-l">合计金额（人民币）　{{ money(totalAmount) }}</td>
              <td colspan="5" class="ta-l">备注：{{ form.notes || '-' }}</td>
              <td class="no-print"></td>
            </tr>
          </tfoot>
        </table>

        <div class="document-footer-fields">
          <label><span>经办人</span><el-input v-model="form.operator" class="no-print" placeholder="选填，打印后显示在制单处" /><strong class="print-only">{{ form.operator || '-' }}</strong></label>
          <label><span>备注</span><el-input v-model="form.notes" class="no-print" placeholder="填写本单说明，打印后显示在合计行" /><strong class="print-only">{{ form.notes || '-' }}</strong></label>
        </div>
        <div class="signature-row">
          <span>制单：{{ form.operator || '________________' }}</span>
          <span>仓库：________________</span>
          <span>审核：________________</span>
        </div>
      </div>

      <footer class="document-actions no-print">
        <el-button v-if="documentNo !== '提交后自动生成'" @click="viewDocument">查看已保存单据</el-button>
        <el-button v-if="documentNo !== '提交后自动生成'" @click="printDocument">打印{{ title }}</el-button>
        <el-button
          v-if="documentNo === '提交后自动生成'"
          type="primary"
          :loading="saving"
          @click="submit"
        >
          保存并{{ direction === 'INBOUND' ? '入库' : '出库' }}
        </el-button>
      </footer>
    </section>

    <el-dialog
      v-model="successDialog"
      append-to-body
      width="min(420px, 92vw)"
      class="stock-document-success-dialog no-print"
      :close-on-click-modal="false"
    >
      <div class="document-success-content">
        <div class="document-success-mark" aria-hidden="true">✓</div>
        <h2>{{ successTitle }}</h2>
        <p>库存与单据记录已同步更新</p>
        <div class="document-success-number">
          <span>{{ savedDocumentTitle }}号</span>
          <strong>{{ savedDocumentNo }}</strong>
        </div>
      </div>
      <template #footer>
        <div class="document-success-actions">
          <el-button @click="successDialog = false">完成</el-button>
          <el-button type="primary" @click="printSavedDocument">打印{{ savedDocumentTitle }}</el-button>
        </div>
      </template>
    </el-dialog>
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
/* 页眉按 6 等份定位：品牌占 0-1.5 份，标题占 2-4 份（页面正中），编号从 5 份起；高度固定 */
.document-head { display: grid; grid-template-columns: repeat(12, 1fr); align-items: center; height: 64px; margin-bottom: 22px; }
.document-head h1 { grid-column: 5 / 9; margin: 0; font-size: 32px; letter-spacing: .35em; text-indent: .35em; color: var(--el-text-color-primary); text-align: center; }
.head-brand { grid-column: 1 / 4; justify-self: start; }
.document-number { grid-column: 11 / 13; justify-self: start; display: flex; align-items: baseline; gap: 8px; font-size: 15px; }
.document-number strong { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 16px; }
.document-meta { display: grid; grid-template-columns: 1.2fr 1fr 1fr; gap: 14px 20px; margin-bottom: 20px; font-size: 16px; }
.document-meta label, .document-footer-fields label, .total-notes { display: grid; grid-template-columns: auto 1fr; align-items: center; gap: 10px; }
.document-meta label > span, .document-footer-fields label > span, .total-notes > span { white-space: nowrap; color: var(--el-text-color-regular); }
.address-field { grid-column: 1 / -1; }
.line-actions { display: flex; align-items: center; justify-content: space-between; margin: 14px 0 10px; font-weight: 600; }
.document-lines :deep(.el-input-number) { width: 100%; }
/* 原生表格：全部列线由边框保证，合计行备注通过 colspan 合并到最右侧 */
.doc-table { width: 100%; border-collapse: collapse; table-layout: fixed; border: 2px solid var(--el-border-color); }
.doc-table th, .doc-table td { border: 1px solid var(--el-border-color); padding: 6px 10px; font-size: 15px; color: var(--el-text-color-primary); word-break: break-all; vertical-align: middle; }
.doc-table th { height: 40px; font-weight: 700; }
.doc-table tbody td { height: 42px; }
.doc-table tfoot td { height: 42px; font-weight: 700; }
.doc-table .col-idx { width: 5.5%; }
.doc-table .col-qty { width: 13%; }
.doc-table .col-unit { width: 6.5%; }
.doc-table .col-price { width: 12.5%; }
.doc-table .col-sub { width: 12.5%; }
.doc-table .col-remark { width: 11.5%; }
.ta-c { text-align: center; }
.ta-l { text-align: left; }
.ta-r { text-align: right; }
.document-footer-fields { display: grid; grid-template-columns: 1fr; gap: 20px; margin-top: 20px; }
.signature-row { display: flex; justify-content: space-between; gap: 32px; margin-top: 30px; color: var(--el-text-color-regular); }
.document-actions { display: flex; justify-content: flex-end; gap: 10px; padding: 0 24px 24px; }
.document-success-content { display: grid; justify-items: center; padding: 8px 8px 2px; text-align: center; }
.document-success-mark { display: grid; place-items: center; width: 52px; height: 52px; margin-bottom: 16px; border-radius: 50%; color: #fff; background: var(--el-color-success); font-size: 28px; font-weight: 700; box-shadow: 0 8px 24px color-mix(in srgb, var(--el-color-success) 24%, transparent); }
.document-success-content h2 { margin: 0; color: var(--el-text-color-primary); font-size: 22px; }
.document-success-content p { margin: 8px 0 18px; color: var(--el-text-color-secondary); }
.document-success-number { display: grid; width: 100%; gap: 6px; padding: 14px 16px; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; background: var(--el-fill-color-light); text-align: left; }
.document-success-number span { color: var(--el-text-color-secondary); font-size: 12px; }
.document-success-number strong { color: var(--el-text-color-primary); font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 16px; letter-spacing: .02em; word-break: break-all; }
.document-success-actions { display: flex; justify-content: flex-end; gap: 10px; width: 100%; }
.print-only { display: none; }
@media (max-width: 900px) {
  .document-sheet { margin: 16px; padding: 20px; overflow-x: auto; }
  .document-head { grid-template-columns: 1fr; height: auto; }
  .document-head h1 { grid-column: 1; justify-self: start; }
  .head-brand, .document-number { grid-column: 1; justify-self: start; }
  .document-meta, .document-footer-fields { grid-template-columns: 1fr; }
  .address-field { grid-column: 1; }
  .total-notes { max-width: none; }
  .signature-row { flex-direction: column; }
}
@media print {
  :global(html), :global(body) { width: var(--erp-print-page-width, 297mm); height: var(--erp-print-page-height, 210mm); margin: 0 !important; overflow: visible !important; background: #fff !important; }
  :global(body *) { visibility: hidden !important; }
  .document-sheet, .document-sheet * { visibility: visible !important; }
  .document-sheet { --el-border-color: #000; --el-border-color-light: #000; --el-border-color-lighter: #000; --el-table-border-color: #000; --el-table-header-text-color: #000; --el-table-text-color: #000; --el-text-color-primary: #000; --el-text-color-regular: #000; --el-text-color-secondary: #000; --el-fill-color-light: #fff; --el-fill-color-lighter: #fff; position: absolute; top: var(--erp-print-margin, 8mm); left: var(--erp-print-margin, 8mm); width: 277mm; margin: 0; padding: 0; border: 0; overflow: visible; color: #000; background: #fff; transform: scale(var(--erp-print-scale, 1)); transform-origin: top left; print-color-adjust: exact; }
  .no-print, :deep(.no-print) { display: none !important; }
  .print-only { display: inline !important; color: #000; font-weight: 500; }
  .document-meta { grid-template-columns: 1.2fr 1fr 1fr; }
  .address-field { grid-column: 1 / -1; }
  .document-footer-fields { grid-template-columns: 1fr; }
  .signature-row { flex-direction: row; }
  .document-meta label, .document-footer-fields label { grid-template-columns: auto 1fr; min-height: 32px; border-bottom: 1px solid #d7dce3; }
}
</style>
