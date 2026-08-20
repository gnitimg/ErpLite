<script setup lang="ts">
import { ElMessage, ElMessageBox } from "element-plus"
import { computed, onMounted, reactive, ref } from "vue"
import { api, formatTime, money, productQty, qty, useLiveRefresh } from "./api"
import ListToolbar from "./components/ListToolbar.vue"
import QuantityInput from "./components/QuantityInput.vue"

const loading = ref(false)
const saving = ref(false)
const drawer = ref(false)
const keyword = ref("")
const products = ref<any[]>([])
const recentRows = ref<any[]>([])
const productionRuns = ref<any[]>([])
const activeTab = ref("plan")
const form = reactive({ item_id: undefined as number | undefined, quantity: 1, unit_cost: 0, notes: "", production_run_id: undefined as number | undefined })
const selected = computed(() => products.value.find(row => row.id === form.item_id))
const filteredProducts = computed(() => {
  const token = keyword.value.trim().toLowerCase()
  return token ? products.value.filter(row => `${row.sku} ${row.name} ${row.spec}`.toLowerCase().includes(token)) : products.value
})
function maxProducible(product: any) {
  if (!product?.components?.length) return 0
  return Math.max(0, Math.floor(Math.min(...product.components.map((line: any) => Number(line.available_stock || 0) / Number(line.quantity || 1)))))
}
const materialPreview = computed(() => selected.value?.components?.map((line: any) => ({
  ...line,
  required: Number(line.quantity) * Number(form.quantity),
  remaining: Number(line.available_stock) - Number(line.quantity) * Number(form.quantity)
})) || [])
const canProduce = computed(() => selected.value?.components?.length && materialPreview.value.every((line: any) => line.remaining >= -1e-9))
const runStatusMap: Record<string, string> = {
  PLANNED: "待生产",
  RUNNING: "生产中",
  COMPLETED: "已完成",
  CANCELLED: "已取消"
}

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    [products.value, recentRows.value, productionRuns.value] = await Promise.all([
      api("/api/products"),
      api("/api/stock/transactions?transaction_type=ASSEMBLY_IN&limit=20"),
      api("/api/production/runs")
    ])
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    if (!silent) loading.value = false
  }
}
function openProduction(product?: any, run?: any) {
  const target = product || products.value[0]
  Object.assign(form, {
    item_id: target?.id,
    quantity: run ? Math.round(run.planned_quantity) : 1,
    unit_cost: target?.cost_price || 0,
    notes: run ? `完成排产批次 ${run.run_no}` : "",
    production_run_id: run?.id
  })
  drawer.value = true
}
function productChanged() {
  form.unit_cost = selected.value?.cost_price || 0
}
async function save() {
  if (!selected.value) return ElMessage.warning("请选择需要生产的产品")
  if (!Number.isInteger(form.quantity) || form.quantity <= 0) return ElMessage.warning("产品生产数量必须为正整数")
  if (!selected.value.components?.length) return ElMessage.warning("该产品尚未配置 BOM，不能生产")
  if (!canProduce.value) return ElMessage.warning("组成零件库存不足，请先完成采购入库")
  try {
    await ElMessageBox.confirm(`确认生产 ${form.quantity} ${selected.value.unit}“${selected.value.name}”吗？系统将同步扣减 BOM 零件。`, "确认产品生产", { type: "warning" })
    saving.value = true
    await api("/api/stock/inbound", { method: "POST", body: JSON.stringify({ ...form, consume_bom: true }) })
    ElMessage.success("生产入库已完成，产品和零件库存已同步更新")
    drawer.value = false
    await load()
  } catch (error: any) {
    if (error !== "cancel") ElMessage.error(error.message)
  } finally {
    saving.value = false
  }
}
async function recalculate() {
  loading.value = true
  try {
    const result = await api<any>("/api/production/plan/recalculate", { method: "POST" })
    ElMessage.success(`生产计划已重算，共生成 ${result.created_run_count} 个批次`)
    await load(true)
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}
async function startRun(run: any) {
  try {
    await api(`/api/production/runs/${run.id}/status`, {
      method: "PUT",
      body: JSON.stringify({ status: "RUNNING" })
    })
    ElMessage.success(`${run.run_no} 已开始生产`)
    await load()
  } catch (error: any) {
    ElMessage.error(error.message)
  }
}
async function cancelRun(run: any) {
  try {
    await ElMessageBox.confirm(`确定取消生产批次“${run.run_no}”吗？系统会立即重新计算其余客单 ETA。`, "取消生产批次", { type: "warning" })
    await api(`/api/production/runs/${run.id}/status`, {
      method: "PUT",
      body: JSON.stringify({ status: "CANCELLED" })
    })
    ElMessage.success(`${run.run_no} 已取消，生产计划已重算`)
    await load()
  } catch (error: any) {
    if (error !== "cancel") ElMessage.error(error.message)
  }
}
function completeRun(run: any) {
  const product = products.value.find(row => row.id === run.product_id)
  openProduction(product, run)
}
onMounted(load)
useLiveRefresh(() => load(true))
</script>

<template>
  <div class="erp-page production-page">
    <ListToolbar v-model="keyword" placeholder="搜索待生产的产品编码、名称或规格" :loading="loading" @search="() => {}" @refresh="load">
      <el-button @click="recalculate">
        <el-icon><Refresh /></el-icon>重算生产计划
      </el-button>
      <el-button type="primary" @click="openProduction()">
        <el-icon><Tools /></el-icon>手工生产入库
      </el-button>
    </ListToolbar>
    <div class="content-card">
      <div class="card-head">
        <h3>产品生产</h3><span>计划按同产品合批，生产线和模具占用不会重叠</span>
      </div>
      <el-tabs v-model="activeTab">
        <el-tab-pane name="plan" label="生产计划">
          <el-table v-loading="loading" :data="productionRuns" empty-text="暂无生产计划；请先确认客单并维护生产资源">
            <el-table-column label="批次 / 产品" min-width="210">
              <template #default="{ row }"><div class="sku-cell"><strong>{{ row.product_name }}</strong><span class="mono">{{ row.run_no }} · {{ row.product_sku }}</span></div></template>
            </el-table-column>
            <el-table-column label="资源" min-width="190"><template #default="{ row }"><div class="sku-cell"><strong>{{ row.line_code }} · {{ row.line_name }}</strong><span>{{ row.mold_code }} · {{ row.mold_name }} · 有效日产 {{ productQty(row.effective_daily_capacity) }}</span></div></template></el-table-column>
            <el-table-column label="计划数量" width="115" align="right"><template #default="{ row }"><b>{{ productQty(row.planned_quantity) }}</b> {{ row.unit }}</template></el-table-column>
            <el-table-column label="预计开始" width="170"><template #default="{ row }">{{ formatTime(row.planned_start_at) }}</template></el-table-column>
            <el-table-column label="预计完成" width="170"><template #default="{ row }">{{ formatTime(row.planned_end_at) }}</template></el-table-column>
            <el-table-column label="订单分配" min-width="210"><template #default="{ row }"><div class="tx-lines"><el-tag v-for="allocation in row.allocations" :key="allocation.id" size="small" effect="plain">{{ allocation.order_no }} · {{ productQty(allocation.quantity) }}</el-tag></div></template></el-table-column>
            <el-table-column label="状态" width="90"><template #default="{ row }"><el-tag :type="row.status === 'RUNNING' ? 'warning' : row.status === 'COMPLETED' ? 'success' : row.status === 'CANCELLED' ? 'info' : 'primary'" size="small">{{ runStatusMap[row.status] || row.status }}</el-tag></template></el-table-column>
            <el-table-column label="操作" width="170" fixed="right"><template #default="{ row }"><el-button v-if="row.status === 'PLANNED'" link type="primary" @click="startRun(row)">开始</el-button><el-button v-if="row.status === 'RUNNING'" link type="success" @click="completeRun(row)">完成入库</el-button><el-button v-if="['PLANNED', 'RUNNING'].includes(row.status)" link type="danger" @click="cancelRun(row)">取消</el-button><span v-if="['COMPLETED', 'CANCELLED'].includes(row.status)" class="muted">已结束</span></template></el-table-column>
          </el-table>
        </el-tab-pane>
        <el-tab-pane name="manual" label="产品与 BOM">
      <el-table v-loading="loading" :data="filteredProducts" empty-text="暂无可生产产品">
        <el-table-column label="产品" min-width="210">
          <template #default="{ row }">
            <div class="sku-cell">
              <strong>{{ row.name }}</strong><span class="mono">{{ row.sku }} · {{ row.spec || '无规格' }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="成品库存" width="110" align="right">
          <template #default="{ row }">
            <b>{{ productQty(row.stock_qty) }}</b> {{ row.unit }}
          </template>
        </el-table-column>
        <el-table-column label="BOM 齐套情况" min-width="330">
          <template #default="{ row }">
            <div v-if="row.components.length" class="bom-summary">
              <el-tag
                v-for="line in row.components"
                :key="line.id"
                :type="line.available_stock < line.quantity ? 'danger' : 'info'"
                size="small"
                effect="plain"
              >
                {{ line.part_name }} {{ qty(line.available_stock) }} / {{ qty(line.quantity) }}
              </el-tag>
            </div><el-tag v-else type="danger" size="small">
              未配置 BOM
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最多可生产" width="125" align="right">
          <template #default="{ row }">
            <b :class="maxProducible(row) ? 'number-positive' : 'number-negative'">{{ productQty(maxProducible(row)) }}</b> {{ row.unit }}
          </template>
        </el-table-column>
        <el-table-column label="参考成本" width="120" align="right">
          <template #default="{ row }">
            {{ money(row.cost_price) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :disabled="!row.components.length" @click="openProduction(row)">
              安排生产
            </el-button>
          </template>
        </el-table-column>
      </el-table>
        </el-tab-pane>
      </el-tabs>
    </div>
    <div class="content-card production-history">
      <div class="card-head">
        <h3>最近生产记录</h3><span>最近 {{ recentRows.length }} 条生产入库流水</span>
      </div>
      <el-table :data="recentRows" empty-text="暂无生产记录">
        <el-table-column label="生产流水" min-width="190">
          <template #default="{ row }">
            <div class="sku-cell">
              <strong class="mono">{{ row.transaction_no }}</strong><span>{{ formatTime(row.occurred_at) }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="生产结果" min-width="300">
          <template #default="{ row }">
            <div class="tx-lines">
              <span
                v-for="line in row.lines.filter((item: any) => item.kind === 'PRODUCT')"
                :key="line.id"
                class="tx-line"
              >
                {{ line.name }}
                <b class="number-positive">+{{ productQty(line.quantity_change) }} {{ line.unit }}</b>
              </span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="消耗零件" min-width="340">
          <template #default="{ row }">
            <div class="tx-lines">
              <span
                v-for="line in row.lines.filter((item: any) => item.kind === 'PART')"
                :key="line.id"
                class="tx-line"
              >
                {{ line.name }}
                <b class="number-negative">{{ qty(line.quantity_change) }} {{ line.unit }}</b>
              </span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="备注" min-width="150">
          <template #default="{ row }">
            <span class="muted">{{ row.notes || '-' }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="drawer" :title="form.production_run_id ? '完成排产批次并入库' : '新建手工生产作业'" size="min(720px, 96vw)">
      <el-form label-position="top">
        <el-form-item label="生产产品" required>
          <el-select v-model="form.item_id" filterable :disabled="Boolean(form.production_run_id)" placeholder="选择已配置 BOM 的产品" style="width:100%" @change="productChanged">
            <el-option
              v-for="product in products"
              :key="product.id"
              :label="`${product.sku} · ${product.name}（最多生产 ${maxProducible(product)}）`"
              :value="product.id"
              :disabled="!product.components.length"
            />
          </el-select>
        </el-form-item>
        <div class="form-grid">
          <el-form-item label="生产数量" required>
            <QuantityInput v-model="form.quantity" integer :min="1" :unit="selected?.unit" :disabled="Boolean(form.production_run_id)" />
          </el-form-item><el-form-item label="成品单位成本">
            <el-input-number v-model="form.unit_cost" :min="0" :precision="2" :controls="false" style="width:100%" />
          </el-form-item>
        </div>
        <div class="detail-section-head">
          <strong>BOM 领料预览</strong><span v-if="selected">当前最多可生产 {{ maxProducible(selected) }} {{ selected.unit }}</span>
        </div>
        <el-table :data="materialPreview" border empty-text="选择产品后显示 BOM 零件">
          <el-table-column label="零件" min-width="190">
            <template #default="{ row }">
              <div class="sku-cell">
                <strong>{{ row.part_name }}</strong><span>{{ row.part_sku }}</span>
              </div>
            </template>
          </el-table-column><el-table-column label="单台用量" width="105" align="right">
            <template #default="{ row }">
              {{ qty(row.quantity) }}
            </template>
          </el-table-column><el-table-column label="本次需要" width="105" align="right">
            <template #default="{ row }">
              {{ qty(row.required) }}
            </template>
          </el-table-column><el-table-column label="现有库存" width="105" align="right">
            <template #default="{ row }">
              {{ qty(row.available_stock) }}
            </template>
          </el-table-column><el-table-column label="生产后" width="105" align="right">
            <template #default="{ row }">
              <b :class="row.remaining < 0 ? 'number-negative' : 'number-positive'">{{ qty(row.remaining) }}</b>
            </template>
          </el-table-column>
        </el-table>
        <el-alert
          v-if="selected && !selected.components.length"
          title="该产品未配置 BOM，请先到“产品目录”页面维护组成零件。"
          type="error"
          :closable="false"
          show-icon
          style="margin-top: 14px"
        />
        <el-alert v-else-if="selected && !canProduce" title="零件库存不足，当前生产数量不能提交。" type="warning" :closable="false" show-icon style="margin-top:14px" />
        <el-form-item label="生产备注" style="margin-top:18px">
          <el-input v-model="form.notes" type="textarea" :rows="3" placeholder="生产批次、负责人或其他说明" />
        </el-form-item>
        <div class="drawer-footer">
          <el-button @click="drawer = false">
            取消
          </el-button><el-button type="primary" :loading="saving" :disabled="!canProduce" @click="save">
            确认生产并入库
          </el-button>
        </div>
      </el-form>
    </el-drawer>
  </div>
</template>
