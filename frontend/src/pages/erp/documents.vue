<script setup lang="ts">
import { ElMessage } from "element-plus"
import { computed, onMounted, reactive, ref, watch } from "vue"
import { useRoute } from "vue-router"
import {
  api,
  formatTime,
  money,
  productQty,
  qty,
  txLabels,
  useLiveRefresh
} from "./api"
import ListToolbar from "./components/ListToolbar.vue"

const route = useRoute()
const loading = ref(false)
const rows = ref<any[]>([])
const itemOptions = ref<any[]>([])
const detail = ref<any>(null)
const drawer = ref(false)
const filterDrawer = ref(false)
const keyword = ref("")
const scope = ref("PART")
const filters = reactive({
  itemId: undefined as number | undefined,
  transactionType: "",
  dateRange: [] as string[]
})
const direction = computed(() =>
  String(route.meta.documentDirection || "inbound").toLowerCase()
)
const title = computed(() => direction.value === "inbound" ? "入库单" : "出库单")
const scopeTitle = computed(() => scope.value === "PART" ? "零件" : "产品")
const activeFilterCount = computed(() =>
  Number(Boolean(filters.itemId))
  + Number(Boolean(filters.transactionType))
  + Number(filters.dateRange.length > 0)
)
const transactionOptions = computed(() => {
  if (direction.value === "inbound" && scope.value === "PART") {
    return ["PURCHASE_IN", "GENERAL_IN", "OPENING"]
  }
  if (direction.value === "inbound") {
    return ["ASSEMBLY_IN", "MANUAL_IN", "GENERAL_IN", "OPENING"]
  }
  if (scope.value === "PART") {
    return ["PRODUCTION_OUT", "MANUAL_OUT", "GENERAL_OUT"]
  }
  return ["SALE_OUT", "MANUAL_OUT", "GENERAL_OUT"]
})

async function load(silent = false) {
  if (!silent) loading.value = true
  const params = new URLSearchParams({ scope: scope.value })
  if (keyword.value.trim()) params.set("keyword", keyword.value.trim())
  if (filters.itemId) params.set("item_id", String(filters.itemId))
  if (filters.transactionType) {
    params.set("transaction_type", filters.transactionType)
  }
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
function printDocument() {
  window.print()
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
onMounted(() => {
  keyword.value = typeof route.query.keyword === "string" ? route.query.keyword : ""
  scope.value = route.query.scope === "PRODUCT" ? "PRODUCT" : "PART"
  load()
  loadItemOptions()
})
watch(direction, () => {
  scope.value = "PART"
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
    <ListToolbar
      v-model="keyword"
      placeholder="搜索单号、物料编码、名称、规格或客户"
      :filter-count="activeFilterCount"
      :loading="loading"
      @search="load"
      @filter="filterDrawer = true"
      @refresh="load"
    >
      <router-link to="/operations/stock-operations">
        <el-button type="primary">
          {{ direction === 'inbound' ? '开入库单' : '办理出库' }}
        </el-button>
      </router-link>
    </ListToolbar>

    <section class="content-card">
      <div class="card-head">
        <h3>{{ title }}</h3>
        <el-segmented
          v-model="scope"
          :options="[
            { label: '零件', value: 'PART' },
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
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="open(row)">
              查看
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
        <el-form-item :label="scope === 'PART' ? '零件' : '产品'">
          <el-select
            v-model="filters.itemId"
            filterable
            clearable
            :placeholder="scope === 'PART' ? '搜索并选择零件' : '搜索并选择产品'"
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
        <el-form-item label="业务类型">
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
      <div v-if="detail" class="print-sheet">
        <h1>{{ scopeTitle }}{{ direction === 'inbound' ? '入 库 单' : '出 库 单' }}</h1>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="单号">
            {{ detail.transaction_no }}
          </el-descriptions-item>
          <el-descriptions-item label="日期">
            {{ formatTime(detail.occurred_at) }}
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
            <el-descriptions-item label="客户" :span="2">
              {{ detail.counterparty_name || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="电话">
              {{ detail.counterparty_phone || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="地址">
              {{ detail.counterparty_address || '-' }}
            </el-descriptions-item>
          </template>
        </el-descriptions>
        <el-table :data="detail.lines" border style="margin-top: 18px">
          <el-table-column prop="sku" label="编码" width="130" />
          <el-table-column prop="name" label="物料" min-width="150" />
          <el-table-column prop="spec" label="规格" min-width="120" />
          <el-table-column label="数量" width="110" align="right">
            <template #default="{ row }">
              {{
                row.kind === 'PRODUCT'
                  ? productQty(Math.abs(row.quantity_change))
                  : qty(Math.abs(row.quantity_change))
              }}
            </template>
          </el-table-column>
          <el-table-column prop="unit" label="单位" width="70" />
          <el-table-column label="单价" width="110" align="right">
            <template #default="{ row }">
              {{ row.unit_price == null ? '-' : money(row.unit_price) }}
            </template>
          </el-table-column>
        </el-table>
        <p class="document-notes">
          备注：{{ detail.notes || '-' }}
        </p>
      </div>
      <template #footer>
        <el-button @click="drawer = false">
          关闭
        </el-button>
        <el-button type="primary" @click="printDocument">
          打印 A4
        </el-button>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.card-head .operation-scope-switch {
  margin-bottom: 0;
  align-self: center;
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
@media print {
  :global(body *) {
    visibility: hidden !important;
  }
  .print-sheet,
  .print-sheet * {
    visibility: visible !important;
  }
  .print-sheet {
    position: fixed;
    inset: 0;
    width: 210mm;
    min-height: 297mm;
    padding: 15mm;
    color: #000;
    background: #fff;
  }
}
</style>
