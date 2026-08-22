<script setup lang="ts">
import { ElMessage } from "element-plus"
import { computed, onMounted, reactive, ref, watch } from "vue"
import { useRoute } from "vue-router"
import { api, money, productQty, stockQty, useLiveRefresh } from "./api"
import ListToolbar from "./components/ListToolbar.vue"

const loading = ref(false)
const route = useRoute()
const rows = ref<any[]>([])
const filterDrawer = ref(false)
const inboundDrawer = ref(false)
const saving = ref(false)
const activePart = ref<any>(null)
const keyword = ref("")
const filters = reactive({ stockStatus: "" })
const inboundForm = reactive({ quantity: 1, unit_cost: 0, notes: "" })
const kind = computed(() => route.meta.inventoryKind === "PRODUCT" ? "PRODUCT" : "PART")
const pageTitle = computed(() => kind.value === "PRODUCT" ? "产品库存" : "零件库存")
const activeFilterCount = computed(() => Number(Boolean(filters.stockStatus)))
const displayQty = (value: number) => stockQty(value, kind.value === "PRODUCT")

async function load(silent = false) {
  if (!silent) loading.value = true
  const params = new URLSearchParams()
  params.set("kind", kind.value)
  if (filters.stockStatus) params.set("stock_status", filters.stockStatus)
  if (keyword.value.trim()) params.set("keyword", keyword.value.trim())
  try {
    rows.value = await api(`/api/inventory?${params}`)
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
  filters.stockStatus = ""
  applyFilters()
}
function openInbound(row: any) {
  activePart.value = row
  inboundForm.quantity = Number(row.shortage_qty) > 0
    ? Number(row.shortage_qty)
    : 1
  inboundForm.unit_cost = Number(row.cost_price || 0)
  inboundForm.notes = Number(row.shortage_qty) > 0
    ? `补足当前订单生产缺口 ${displayQty(row.shortage_qty)} ${row.unit}`
    : "零件快捷入库"
  inboundDrawer.value = true
}
async function submitInbound() {
  if (Number(inboundForm.quantity) <= 0) {
    return ElMessage.warning("入库数量必须大于 0")
  }
  saving.value = true
  try {
    await api("/api/stock/inbound", {
      method: "POST",
      body: JSON.stringify({
        item_id: activePart.value.id,
        quantity: Number(inboundForm.quantity),
        unit_cost: Number(inboundForm.unit_cost),
        notes: inboundForm.notes,
        consume_bom: false
      })
    })
    ElMessage.success("零件已入库，入库单和缺口数量已自动更新")
    inboundDrawer.value = false
    await load()
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    saving.value = false
  }
}
onMounted(load)
watch(() => route.name, () => load())
useLiveRefresh(() => load(true))
</script>

<template>
  <div class="erp-page">
    <ListToolbar
      v-model="keyword"
      placeholder="搜索物料编码、名称或规格"
      :filter-count="activeFilterCount"
      :loading="loading"
      @search="load"
      @filter="filterDrawer = true"
      @refresh="load"
    />
    <div class="content-card">
      <div class="card-head">
        <h3>{{ pageTitle }}</h3>
      </div>
      <el-table v-loading="loading" :data="rows">
        <el-table-column label="物料" min-width="210">
          <template #default="{ row }">
            <div class="sku-cell">
              <strong>{{ row.name }}</strong><span class="mono">{{ row.sku }} · {{ row.spec || '无规格' }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="实时结存" width="125" align="right">
          <template #default="{ row }">
            <b :class="row.low_stock ? 'number-negative' : 'number-positive'">
              {{ displayQty(row.stock_qty) }}
            </b>
            {{ row.unit }}
          </template>
        </el-table-column>
        <el-table-column v-if="kind === 'PRODUCT'" label="半成品" width="105" align="right">
          <template #default="{ row }">
            <b :class="row.semi_finished_qty ? 'number-positive' : ''">
              {{ productQty(row.semi_finished_qty) }}
            </b>
          </template>
        </el-table-column>
        <el-table-column v-if="kind === 'PRODUCT'" label="外协在途" width="105" align="right">
          <template #default="{ row }">
            <b :class="row.processing_qty ? 'number-positive' : ''">
              {{ productQty(row.processing_qty) }}
            </b>
          </template>
        </el-table-column>
        <el-table-column v-if="kind === 'PRODUCT'" label="客单预留" width="105" align="right">
          <template #default="{ row }">
            {{ productQty(row.reserved_qty) }}
          </template>
        </el-table-column>
        <el-table-column v-if="kind === 'PRODUCT'" label="可用库存" width="105" align="right">
          <template #default="{ row }">
            <b :class="row.available_qty <= 0 ? 'number-negative' : 'number-positive'">
              {{ productQty(Math.max(row.available_qty, 0)) }}
            </b>
          </template>
        </el-table-column>
        <el-table-column label="订单缺口" width="125" align="right">
          <template #default="{ row }">
            <b :class="row.gap_qty < 0 ? 'number-negative' : ''">
              {{ displayQty(row.gap_qty) }}
            </b>
            {{ row.unit }}
          </template>
        </el-table-column>
        <el-table-column label="安全库存" width="100" align="right">
          <template #default="{ row }">
            {{ displayQty(row.min_stock) }}
          </template>
        </el-table-column>
        <el-table-column label="库存水位" min-width="180">
          <template #default="{ row }">
            <div class="stock-meter">
              <div class="stock-meter-label">
                <span>{{ row.low_stock ? '低库存' : '充足' }}</span>
                <span>
                  {{ Math.round(Math.min(100, row.stock_qty / Math.max(row.min_stock * 2, 1) * 100)) }}%
                </span>
              </div>
              <el-progress
                :percentage="Math.round(Math.min(100, row.stock_qty / Math.max(row.min_stock * 2, 1) * 100))"
                :show-text="false"
                :stroke-width="6"
                :color="row.low_stock ? '#e05757' : '#39aa7b'"
              />
            </div>
          </template>
        </el-table-column>
        <el-table-column label="参考成本" width="110" align="right">
          <template #default="{ row }">
            {{ money(row.cost_price) }}
          </template>
        </el-table-column>
        <el-table-column label="库存金额" width="125" align="right">
          <template #default="{ row }">
            <strong>{{ money(row.stock_qty * row.cost_price) }}</strong>
          </template>
        </el-table-column>
        <el-table-column v-if="kind === 'PART'" label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openInbound(row)">
              入库
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="filterDrawer" title="筛选库存" size="min(420px, 92vw)">
      <el-form label-position="top">
        <el-form-item label="库存状态">
          <el-select v-model="filters.stockStatus" clearable placeholder="全部状态" style="width:100%">
            <el-option label="库存预警" value="LOW" /><el-option label="库存正常" value="NORMAL" />
          </el-select>
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

    <el-drawer
      v-model="inboundDrawer"
      title="零件快捷入库"
      size="min(520px, 96vw)"
    >
      <el-descriptions v-if="activePart" :column="1" border>
        <el-descriptions-item label="零件">
          {{ activePart.sku }} · {{ activePart.name }}
        </el-descriptions-item>
        <el-descriptions-item label="当前库存">
          {{ displayQty(activePart.stock_qty) }} {{ activePart.unit }}
        </el-descriptions-item>
        <el-descriptions-item label="生产总需求">
          {{ displayQty(activePart.order_required_qty) }} {{ activePart.unit }}
        </el-descriptions-item>
        <el-descriptions-item label="当前缺口">
          <b :class="activePart.gap_qty < 0 ? 'number-negative' : ''">
            {{ displayQty(activePart.gap_qty) }} {{ activePart.unit }}
          </b>
        </el-descriptions-item>
      </el-descriptions>
      <el-form label-position="top" style="margin-top: 20px">
        <el-form-item label="本次入库数量" required>
          <el-input-number
            v-model="inboundForm.quantity"
            :min="0.001"
            :precision="3"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="入库单位成本">
          <el-input-number
            v-model="inboundForm.unit_cost"
            :min="0"
            :precision="2"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="inboundForm.notes" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <div class="drawer-footer">
        <el-button @click="inboundDrawer = false">
          取消
        </el-button>
        <el-button type="primary" :loading="saving" @click="submitInbound">
          确认入库并生成入库单
        </el-button>
      </div>
    </el-drawer>
  </div>
</template>
