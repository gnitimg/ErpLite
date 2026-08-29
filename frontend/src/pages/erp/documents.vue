<script setup lang="ts">
import { ElMessage } from "element-plus"
import { computed, nextTick, onMounted, reactive, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import {
  api,
  formatDate,
  formatTime,
  money,
  productQty,
  qty,
  txLabels,
  useLiveRefresh
} from "./api"
import ListToolbar from "./components/ListToolbar.vue"
import InfoTip from "./components/InfoTip.vue"
import PrintBrandHeader from "./components/PrintBrandHeader.vue"
import { printWithSavedSize } from "./print"
import StockDocument from "./stock-document.vue"

type DocumentTab = "inbound" | "outbound" | "returns"
type StockDocumentDirection = "INBOUND" | "OUTBOUND"

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const rows = ref<any[]>([])
const itemOptions = ref<any[]>([])
const detail = ref<any>(null)
const drawer = ref(false)
const drawerSheetRef = ref<HTMLElement | null>(null)
const filterDrawer = ref(false)
const documentDialog = ref(false)
const stockDocumentDirection = ref<StockDocumentDirection>("INBOUND")
const stockDocumentKey = ref(0)
const keyword = ref("")
const scope = ref("PART")
const filters = reactive({
  itemId: undefined as number | undefined,
  transactionType: "",
  dateRange: [] as string[]
})
const documentContext = computed(() => String(route.meta.documentContext || "inventory"))
const isSales = computed(() => documentContext.value === "sales")
const supportsDirectionTabs = computed(() => route.meta.documentDirection === "both")
const documentTab = ref<DocumentTab>(
  isSales.value
    ? route.query.tab === "returns" ? "returns" : "outbound"
    : route.query.direction === "outbound" ? "outbound" : "inbound"
)
const direction = computed(() => {
  if (isSales.value) return documentTab.value === "returns" ? "inbound" : "outbound"
  if (supportsDirectionTabs.value) return documentTab.value === "outbound" ? "outbound" : "inbound"
  return String(route.meta.documentDirection || "inbound").toLowerCase()
})
const title = computed(() => {
  if (isSales.value) return documentTab.value === "returns" ? "退货记录" : "销售出库单"
  return direction.value === "inbound" ? "入库单" : "出库单"
})
const routeOrderId = computed(() => {
  const value = Number(route.query.order_id)
  return Number.isInteger(value) && value > 0 ? value : 0
})
const dialogTitle = computed(() =>
  stockDocumentDirection.value === "INBOUND" ? "开入库单" : "开出库单"
)
const scopeTitle = computed(() => scope.value === "PART" ? "原料" : "产品")
const activeFilterCount = computed(() =>
  Number(Boolean(filters.itemId))
  + Number(Boolean(filters.transactionType))
  + Number(filters.dateRange.length > 0)
)
const transactionOptions = computed(() => {
  if (isSales.value) return documentTab.value === "returns" ? ["SALE_RETURN_IN"] : ["SALE_OUT"]
  if (direction.value === "inbound" && scope.value === "PART") {
    return ["PURCHASE_IN", "GENERAL_IN", "OPENING"]
  }
  if (direction.value === "inbound") {
    return [
      "ASSEMBLY_IN", "SEMI_FINISHED_IN", "PROCESS_RETURN_IN",
      "SALE_RETURN_IN", "MANUAL_IN", "GENERAL_IN", "OPENING"
    ]
  }
  if (scope.value === "PART") {
    return ["PRODUCTION_OUT", "MANUAL_OUT", "GENERAL_OUT"]
  }
  return ["SALE_OUT", "PROCESS_OUT", "MANUAL_OUT", "GENERAL_OUT"]
})

async function load(silent = false) {
  if (!silent) loading.value = true
  const params = new URLSearchParams({ scope: scope.value })
  if (keyword.value.trim()) params.set("keyword", keyword.value.trim())
  if (filters.itemId) params.set("item_id", String(filters.itemId))
  const transactionType = isSales.value ? transactionOptions.value[0] : filters.transactionType
  if (transactionType) params.set("transaction_type", transactionType)
  if (filters.dateRange[0]) params.set("start_date", filters.dateRange[0])
  if (filters.dateRange[1]) params.set("end_date", filters.dateRange[1])
  try {
    const response = await api<any[]>(`/api/documents/${direction.value}?${params}`)
    const inbound = direction.value === "inbound"
    rows.value = response
      .map(row => ({
        ...row,
        lines: (row.lines || []).filter((line: any) =>
          line.kind === scope.value
          && (Number(line.quantity_change) > 0) === inbound
        )
      }))
      .filter(row =>
        row.lines.length > 0
        && (!transactionType || row.transaction_type === transactionType)
        && (!filters.itemId || row.lines.some(
          (line: any) => line.item_id === filters.itemId
        ))
      )
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    if (!silent) loading.value = false
  }
}
async function loadItemOptions() {
  try {
    itemOptions.value = await api(`/api/inventory?kind=${scope.value}`)
  } catch (error: any) {
    ElMessage.error(error.message)
  }
}
function materialSummary(row: any) {
  return row.lines
    .slice(0, 3)
    .map((line: any) => `${line.name} × ${Math.abs(line.quantity_change)}`)
    .join("、")
}
const detailTotal = computed(() => (detail.value?.lines || []).reduce(
  (sum: number, line: any) => sum + Number(
    line.line_total ?? Number(line.unit_price || 0) * Math.abs(Number(line.quantity_change || 0))
  ),
  0
))
const detailRemarks = computed(() => [
  detail.value?.notes,
  detail.value?.related_order_no ? `订单 ${detail.value.related_order_no}` : "",
  detail.value?.related_production_run_no ? `生产批次 ${detail.value.related_production_run_no}` : ""
].filter(Boolean).join("；"))
/** 明细不足 5 行时用空行补齐，保持纸质单据的版面。 */
const displayLines = computed(() => {
  const lines = [...(detail.value?.lines || [])]
  while (lines.length < 5) lines.push({})
  return lines
})
function isBlankLine(row: any) {
  return row.sku == null && row.name == null && row.quantity_change == null
}
/** 日期打印格式：2026 年 8 月 29 日。 */
function chineseDate(value: string) {
  if (!value) return "-"
  const [year, month, day] = value.split("-")
  return `${year} 年 ${Number(month)} 月 ${Number(day)} 日`
}
function open(row: any) {
  detail.value = row
  drawer.value = true
}
async function printRow(row: any) {
  open(row)
  await nextTick()
  await printDocument()
}
async function printDocument() {
  const sheet = drawerSheetRef.value
  if (!sheet) return
  await printWithSavedSize(sheet)
}
function applyFilters() {
  filterDrawer.value = false
  load()
}
function resetFilters() {
  filters.itemId = undefined
  filters.transactionType = ""
  filters.dateRange = []
  applyFilters()
}
function selectDocumentTab(value: string | number) {
  const tab = value as DocumentTab
  const query = { ...route.query }
  if (isSales.value) query.tab = tab
  else query.direction = tab
  router.replace({ query })
}
function openDocumentDialog(selectedDirection?: StockDocumentDirection) {
  stockDocumentDirection.value = selectedDirection
    || (direction.value === "inbound" ? "INBOUND" : "OUTBOUND")
  stockDocumentKey.value += 1
  documentDialog.value = true
}
async function showSavedDocument(payload: {
  direction: StockDocumentDirection
  scope: string
  keyword: string
}) {
  documentDialog.value = false
  documentTab.value = payload.direction === "INBOUND" ? "inbound" : "outbound"
  await nextTick()
  scope.value = payload.scope === "PRODUCT" ? "PRODUCT" : "PART"
  keyword.value = payload.keyword
  router.replace({
    query: {
      direction: documentTab.value,
      scope: scope.value,
      keyword: keyword.value
    }
  })
  load()
}
onMounted(() => {
  keyword.value = typeof route.query.keyword === "string" ? route.query.keyword : ""
  scope.value = isSales.value || route.query.scope === "PRODUCT" ? "PRODUCT" : "PART"
  load()
  loadItemOptions()
})
watch(routeOrderId, value => {
  if (!isSales.value && value) openDocumentDialog("OUTBOUND")
}, { immediate: true })
watch(direction, () => {
  scope.value = isSales.value ? "PRODUCT" : "PART"
  filters.itemId = undefined
  filters.transactionType = ""
  filters.dateRange = []
  load()
})
watch(scope, () => {
  filters.itemId = undefined
  filters.transactionType = ""
  loadItemOptions()
  load()
})
useLiveRefresh(() => load(true))
</script>

<template>
  <div class="erp-page document-page">
    <el-tabs v-if="isSales" v-model="documentTab" class="document-context-tabs" @tab-change="selectDocumentTab">
      <el-tab-pane label="出库单" name="outbound" />
      <el-tab-pane label="退货记录" name="returns" />
    </el-tabs>
    <el-tabs v-else-if="supportsDirectionTabs" v-model="documentTab" class="document-context-tabs" @tab-change="selectDocumentTab">
      <el-tab-pane label="入库" name="inbound" />
      <el-tab-pane label="出库" name="outbound" />
    </el-tabs>
    <ListToolbar
      v-model="keyword"
      placeholder="搜索单号、物料编码、名称、规格或客户"
      :filter-count="activeFilterCount"
      :loading="loading"
      @search="load"
      @filter="filterDrawer = true"
      @refresh="load"
    >
      <router-link v-if="isSales" to="/lite-orders/list">
        <el-button type="primary">
          {{ documentTab === 'returns' ? '登记客户退货' : '办理订单出库' }}
        </el-button>
      </router-link>
      <el-button
        v-else
        type="primary"
        @click="openDocumentDialog()"
      >
        {{ direction === 'inbound' ? '开入库单' : '开出库单' }}
      </el-button>
    </ListToolbar>

    <section class="content-card">
      <div class="card-head">
        <h3>
          {{ title }}
          <InfoTip
            v-if="isSales && documentTab === 'returns'"
            content="退货请在客户订单详情中登记；此处汇总已经产生库存记录的客户退货。"
          />
        </h3>
        <el-segmented
          v-if="!isSales"
          v-model="scope"
          :options="[
            { label: '原料', value: 'PART' },
            { label: '产品', value: 'PRODUCT' },
          ]"
          class="operation-scope-switch"
        />
      </div>

      <el-table v-loading="loading" :data="rows" empty-text="暂无单据">
        <el-table-column prop="transaction_no" label="单号" min-width="190">
          <template #default="{ row }">
            <span class="mono">{{ row.transaction_no }}</span>
          </template>
        </el-table-column>
        <el-table-column label="业务类型" width="130">
          <template #default="{ row }">
            {{ txLabels[row.transaction_type] || row.transaction_type }}
          </template>
        </el-table-column>
        <el-table-column label="物料摘要" min-width="260">
          <template #default="{ row }">
            {{ materialSummary(row) }}
            <span v-if="row.lines.length > 3" class="muted">
              等 {{ row.lines.length }} 项
            </span>
          </template>
        </el-table-column>
        <el-table-column
          prop="related_production_run_no"
          label="生产批次"
          min-width="160"
        />
        <el-table-column label="发生时间" width="175">
          <template #default="{ row }">
            {{ formatTime(row.occurred_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="open(row)">
              查看
            </el-button>
            <el-button link type="primary" @click="printRow(row)">
              打印
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-drawer
      v-model="filterDrawer"
      :title="`筛选${scopeTitle}${title}`"
      size="min(420px, 92vw)"
    >
      <el-form label-position="top">
        <el-form-item :label="scope === 'PART' ? '原料' : '产品'">
          <el-select
            v-model="filters.itemId"
            filterable
            clearable
            :placeholder="scope === 'PART' ? '搜索并选择原料' : '搜索并选择产品'"
            style="width: 100%"
          >
            <el-option
              v-for="item in itemOptions"
              :key="item.id"
              :label="`${item.sku} · ${item.name}`"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-if="!isSales" label="业务类型">
          <el-select
            v-model="filters.transactionType"
            clearable
            placeholder="全部类型"
            style="width: 100%"
          >
            <el-option
              v-for="value in transactionOptions"
              :key="value"
              :label="txLabels[value] || value"
              :value="value"
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
      v-model="drawer"
      class="document-drawer"
      :title="`${scopeTitle}${title} · ${detail?.transaction_no || ''}`"
      size="min(820px, 98vw)"
    >
      <div v-if="detail" ref="drawerSheetRef" class="print-sheet">
        <div class="sheet-head">
          <PrintBrandHeader class="head-brand" />
          <h1>{{ direction === 'inbound' ? '入 库 单' : '出 库 单' }}</h1>
          <div class="sheet-no"><span class="no-label">NO.</span><strong>{{ detail.transaction_no }}</strong></div>
        </div>
        <div class="sheet-info">
          <span class="info-party">
            {{ direction === 'inbound' ? '供应商' : '客户' }}：{{ detail.counterparty_name || '-' }}
          </span>
          <span v-if="detail.counterparty_phone">电话：{{ detail.counterparty_phone }}</span>
          <span v-if="detail.counterparty_address">地址：{{ detail.counterparty_address }}</span>
          <span class="info-date">{{ chineseDate(formatDate(detail.occurred_at)) }}</span>
        </div>
        <table class="doc-table">
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
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, index) in displayLines" :key="index">
              <td class="ta-c">{{ index + 1 }}</td>
              <td class="ta-c">{{ isBlankLine(row) ? '' : [row.sku, row.name, row.spec].filter(Boolean).join(' · ') }}</td>
              <td class="ta-r">
                <template v-if="!isBlankLine(row)">
                  {{ row.kind === 'PRODUCT' ? productQty(Math.abs(row.quantity_change)) : qty(Math.abs(row.quantity_change)) }}
                </template>
              </td>
              <td class="ta-c">{{ row.unit }}</td>
              <td class="ta-r">{{ isBlankLine(row) || row.unit_price == null ? '' : money(row.unit_price) }}</td>
              <td class="ta-r">{{ isBlankLine(row) || row.line_total == null ? '' : money(row.line_total) }}</td>
              <td class="ta-l">
                <span v-if="Number(row.replacement_quantity) > 0">换货 {{ qty(row.replacement_quantity) }}</span>
              </td>
            </tr>
          </tbody>
          <tfoot>
            <tr>
              <td colspan="2" class="ta-l">合计金额（人民币）　{{ money(detailTotal) }}</td>
              <td colspan="5" class="ta-l">备注：{{ detailRemarks || '-' }}</td>
            </tr>
          </tfoot>
        </table>
        <div class="history-signature-row">
          <span>制单：{{ detail.operator || '________________' }}</span>
          <span>仓库：________________</span>
          <span>审核：________________</span>
        </div>
      </div>
      <template #footer>
        <el-button @click="drawer = false">
          关闭
        </el-button>
        <el-button type="primary" @click="printDocument">
          打印
        </el-button>
      </template>
    </el-drawer>

    <el-dialog
      v-model="documentDialog"
      :title="dialogTitle"
      width="min(1480px, 96vw)"
      top="2vh"
      destroy-on-close
      class="stock-document-dialog"
    >
      <StockDocument
        :key="stockDocumentKey"
        embedded
        :initial-direction="stockDocumentDirection"
        :initial-order-id="routeOrderId"
        @saved="load(true)"
        @view="showSavedDocument"
      />
    </el-dialog>
  </div>
</template>

<style scoped>
@page { size: 297mm 210mm; margin: 0; }
.document-context-tabs :deep(.el-tabs__header) { margin-bottom: 12px; }
.card-head .operation-scope-switch {
  margin-bottom: 0;
  align-self: center;
}
:global(.stock-document-dialog) {
  max-width: 1480px;
}
:global(.stock-document-dialog .el-dialog__body) {
  max-height: calc(96vh - 72px);
  padding: 0;
  overflow: auto;
}
.print-sheet { color: var(--el-text-color-primary); }
/* 页眉按 6 等份定位：品牌占 0-1.5 份，标题占 2-4 份（页面正中），编号从 5 份起；高度固定 */
.sheet-head { display: grid; grid-template-columns: repeat(12, 1fr); align-items: center; height: 64px; }
.head-brand { grid-column: 1 / 4; justify-self: start; }
.sheet-head h1 { grid-column: 5 / 9; margin: 0; text-align: center; font-size: 32px; letter-spacing: .35em; text-indent: .35em; }
.sheet-no { grid-column: 11 / 13; justify-self: start; display: flex; align-items: baseline; gap: 8px; font-size: 30px; }
.sheet-no .no-label { font-family: FangSong, "FangSong_GB2312", "仿宋", "仿宋_GB2312", serif; }
.sheet-no strong { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
.lines-table :deep(td.el-table__cell) { height: 42px; padding-top: 8px; padding-bottom: 8px; }
.sheet-info { display: flex; flex-wrap: wrap; gap: 6px 28px; padding: 6px 0 14px; border-bottom: 1px solid var(--el-border-color); font-size: 16px; }
.info-date { margin-left: auto; }
/* 原生表格：全部列线由边框保证，合计行备注通过 colspan 合并到最右侧 */
.doc-table { width: 100%; border-collapse: collapse; table-layout: fixed; border: 2px solid var(--el-border-color); }
.doc-table th, .doc-table td { border: 1px solid var(--el-border-color); padding: 6px 10px; font-size: 15px; color: var(--el-text-color-primary); word-break: break-all; }
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
.document-notes {
  margin-top: 18px;
  color: var(--el-text-color-regular);
}
.history-signature-row { display: flex; justify-content: space-between; gap: 32px; margin-top: 30px; color: var(--el-text-color-regular); }
@media print {
  :global(html), :global(body) { width: var(--erp-print-page-width, 297mm); height: var(--erp-print-page-height, 210mm); margin: 0 !important; overflow: visible !important; background: #fff !important; }
  :global(body *) {
    visibility: hidden !important;
  }
  .print-sheet,
  .print-sheet * {
    visibility: visible !important;
  }
  .print-sheet {
    --el-border-color: #000;
    --el-border-color-light: #000;
    --el-border-color-lighter: #000;
    --el-table-border-color: #000;
    --el-table-header-text-color: #000;
    --el-table-text-color: #000;
    --el-text-color-primary: #000;
    --el-text-color-regular: #000;
    --el-text-color-secondary: #000;
    --el-fill-color-light: #fff;
    --el-fill-color-lighter: #fff;
    position: absolute;
    top: var(--erp-print-margin, 8mm);
    left: var(--erp-print-margin, 8mm);
    width: 277mm;
    min-height: 0;
    padding: 0;
    color: #000;
    background: #fff;
    transform: scale(var(--erp-print-scale, 1));
    transform-origin: top left;
    print-color-adjust: exact;
  }
}
</style>
