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
        <h1>{{ direction === 'inbound' ? '入 库 单' : '出 库 单' }}</h1>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="单号">
            {{ detail.transaction_no }}
          </el-descriptions-item>
          <el-descriptions-item label="日期">
            {{ formatDate(detail.occurred_at) }}
          </el-descriptions-item>
          <el-descriptions-item
            v-if="detail.counterparty_name"
            :label="direction === 'inbound' ? '供应商' : '收货单位'"
          >
            {{ detail.counterparty_name }}
          </el-descriptions-item>
          <el-descriptions-item v-if="detail.counterparty_phone" label="联系电话">
            {{ detail.counterparty_phone }}
          </el-descriptions-item>
          <el-descriptions-item v-if="detail.counterparty_address" label="地址" :span="2">
            {{ detail.counterparty_address }}
          </el-descriptions-item>
          <el-descriptions-item
            v-if="detail.related_production_run_no"
            label="生产批次"
            :span="2"
          >
            {{ detail.related_production_run_no }}
          </el-descriptions-item>
          <template v-if="detail.transaction_type === 'SALE_OUT'">
            <el-descriptions-item label="订单号" :span="2">
              {{ detail.related_order_no || '-' }}
            </el-descriptions-item>
          </template>
        </el-descriptions>
        <el-table :data="detail.lines" border style="margin-top: 18px">
          <el-table-column prop="sku" label="编码" min-width="130" />
          <el-table-column prop="name" label="物料" min-width="150" />
          <el-table-column prop="spec" label="规格" min-width="120" />
          <el-table-column label="数量" min-width="130" align="right">
            <template #default="{ row }">
              {{
                row.kind === 'PRODUCT'
                  ? productQty(Math.abs(row.quantity_change))
                  : qty(Math.abs(row.quantity_change))
              }}
              <el-tag v-if="Number(row.replacement_quantity) > 0" type="warning" size="small" effect="plain" style="margin-left:6px">
                换货 {{ qty(row.replacement_quantity) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="unit" label="单位" min-width="70" />
          <el-table-column label="单价" min-width="110" align="right">
            <template #default="{ row }">
              {{ row.unit_price == null ? '-' : money(row.unit_price) }}
            </template>
          </el-table-column>
          <el-table-column label="金额" min-width="120" align="right">
            <template #default="{ row }">
              {{ row.line_total == null ? '-' : money(row.line_total) }}
            </template>
          </el-table-column>
        </el-table>
        <p class="document-notes">
          备注：{{ detail.notes || '-' }}
        </p>
        <div class="history-signature-row">
          <span>制单：{{ detail.operator || '________________' }}</span>
          <span>仓管：________________</span>
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
.print-sheet h1 {
  margin: 0 0 22px;
  text-align: center;
  font-size: 24px;
  letter-spacing: 8px;
}
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
  .print-sheet :deep(.el-table__header),
  .print-sheet :deep(.el-table__body) { width: 100% !important; }
}
</style>
