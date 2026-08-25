<script setup lang="ts">
import { ElMessage, ElMessageBox } from "element-plus"
import { computed, onMounted, reactive, ref } from "vue"
import { api, formatDate, productQty, useLiveRefresh } from "./api"
import InfoTip from "./components/InfoTip.vue"

const loading = ref(false)
const saving = ref(false)
const rows = ref<any[]>([])
const statusFilter = ref("ACTIVE")
const completionDrawer = ref(false)
const activeRun = ref<any>(null)
const form = reactive({ qualified_quantity: 1, scrap_quantity: 0, completion_date: "", notes: "" })
const today = () => new Date().toISOString().slice(0, 10)
const visibleRows = computed(() => statusFilter.value === "ACTIVE"
  ? rows.value.filter(row => ["PLANNED", "RUNNING"].includes(row.status))
  : rows.value.filter(row => row.status === statusFilter.value))

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    rows.value = await api("/api/production/runs")
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    if (!silent) loading.value = false
  }
}
function openCompletion(row: any) {
  activeRun.value = row
  form.qualified_quantity = Number(row.planned_quantity)
  form.scrap_quantity = 0
  form.completion_date = today()
  form.notes = ""
  completionDrawer.value = true
}
function materialShortageText(row: any) {
  return (row.material_shortages || [])
    .map((item: any) => `${item.name}缺 ${productQty(item.shortage_quantity)} ${item.unit}`)
    .join("；")
}
async function completeRun() {
  const qualified = Number(form.qualified_quantity)
  const scrap = Number(form.scrap_quantity)
  if (!Number.isInteger(qualified) || qualified <= 0) return ElMessage.warning("合格数量必须是正整数")
  if (scrap < 0 || !Number.isInteger(scrap)) return ElMessage.warning("报废数量必须是非负整数")
  const total = qualified + scrap
  if (total > Number(activeRun.value.planned_quantity)) {
    const excess = total - Number(activeRun.value.planned_quantity)
    try {
      await ElMessageBox.confirm(`合格+报废高于计划数量 ${productQty(excess)}，超出部分将补领 BOM 原料。是否继续？`, "产量高于计划", { type: "warning" })
    } catch {
      return
    }
  }
  saving.value = true
  try {
    await api(`/api/production/runs/${activeRun.value.id}/complete`, { method: "POST", body: JSON.stringify(form) })
    ElMessage.success(activeRun.value.requires_external_processing
      ? `审核通过，合格品已进入半成品库存，等待${activeRun.value.external_process_name}`
      : "审核通过，合格品已进入成品库存")
    completionDrawer.value = false
    await load()
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    saving.value = false
  }
}
const involvedOrders = (row: any) => [...new Set(row.allocations.map((item: any) => item.order_no))].join("、") || "自由库存"
onMounted(load)
useLiveRefresh(() => load(true))
</script>

<template>
  <div class="erp-page production-page">
    <div class="page-toolbar">
      <div class="toolbar-group">
        <el-select v-model="statusFilter" style="width: 150px">
          <el-option label="待完工批次" value="ACTIVE" /><el-option label="已完成" value="COMPLETED" /><el-option label="已终止" value="TERMINATED" /><el-option label="已取消" value="CANCELLED" />
        </el-select><el-button :loading="loading" @click="load()">
          <el-icon><Refresh /></el-icon>刷新
        </el-button>
      </div>
    </div>
    <section class="content-card">
      <div class="card-head">
        <h3>
          完工登记
          <InfoTip content="登记实际合格数量；审核后系统按 BOM 扣减零件并办理成品或半成品入库。" />
        </h3>
      </div>
      <el-table v-loading="loading" :data="visibleRows" empty-text="当前没有待完工生产批次">
        <el-table-column prop="run_no" label="批次号" min-width="180">
          <template #default="{ row }">
            <span class="mono">{{ row.run_no }}</span>
          </template>
        </el-table-column>
        <el-table-column label="产品" min-width="190">
          <template #default="{ row }">
            <div class="sku-cell">
              <strong>{{ row.product_name }}</strong><span>{{ row.product_sku }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="计划数量" width="115" align="right">
          <template #default="{ row }">
            {{ productQty(row.planned_quantity) }}
          </template>
        </el-table-column>
        <el-table-column label="生产位" width="90">
          <template #default="{ row }">
            {{ row.line_slot }} 号位
          </template>
        </el-table-column>
        <el-table-column label="计划日期" width="205">
          <template #default="{ row }">
            {{ formatDate(row.planned_start_at) }} 至 {{ formatDate(row.planned_end_at) }}
          </template>
        </el-table-column>
        <el-table-column label="材料状态" width="125">
          <template #default="{ row }">
            <el-tag :type="row.materials_ready ? 'success' : 'warning'" size="small" effect="plain">
              {{ row.materials_ready ? '材料充足' : '材料不足' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="涉及订单" min-width="210">
          <template #default="{ row }">
            {{ involvedOrders(row) }}
          </template>
        </el-table-column>
        <el-table-column label="排期来源" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.schedule_locked ? 'warning' : 'info'">
              {{ row.source_type === 'REPLENISHMENT'
                ? '自主补库存'
                : row.schedule_locked ? '人工排定' : '系统建议' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button v-if="['PLANNED', 'RUNNING'].includes(row.status)" link type="primary" @click="openCompletion(row)">
              登记完工
            </el-button><span v-else class="muted">{{ row.status === 'COMPLETED' ? '已入库' : row.status === 'TERMINATED' ? '已终止' : '已取消' }}</span>
          </template>
        </el-table-column>
      </el-table>
    </section>
    <el-drawer v-model="completionDrawer" title="登记生产完工" size="min(520px, 96vw)">
      <el-descriptions v-if="activeRun" :column="1" border>
        <el-descriptions-item label="批次">
          {{ activeRun.run_no }}
        </el-descriptions-item><el-descriptions-item label="产品">
          {{ activeRun.product_sku }} · {{ activeRun.product_name }}
        </el-descriptions-item><el-descriptions-item label="计划数量">
          {{ productQty(activeRun.planned_quantity) }}
        </el-descriptions-item>
      </el-descriptions>
      <el-alert
        v-if="activeRun?.requires_external_processing"
        :title="`该产品需${activeRun.external_process_name}：审核后进入半成品库存，不会立即占用成品库存。`"
        type="warning"
        :closable="false"
        show-icon
        style="margin-top: 16px"
      />
      <el-alert
        v-else-if="activeRun && !activeRun.materials_ready"
        :title="`当前材料不足：${materialShortageText(activeRun)}。理论排期仍保留，但实际完工会在库存不足时被阻止。`"
        type="warning"
        :closable="false"
        show-icon
        style="margin-top: 16px"
      />
      <el-form label-position="top" style="margin-top: 20px">
        <el-form-item label="合格入库数量" required>
          <el-input-number v-model="form.qualified_quantity" :min="1" :precision="0" style="width:100%" />
        </el-form-item><el-form-item label="报废数量">
          <el-input-number v-model="form.scrap_quantity" :min="0" :precision="0" style="width:100%" />
        </el-form-item><el-form-item label="完成日期" required>
          <el-date-picker v-model="form.completion_date" type="date" value-format="YYYY-MM-DD" style="width:100%" />
        </el-form-item><el-form-item label="备注">
          <el-input v-model="form.notes" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <div class="drawer-footer">
        <el-button @click="completionDrawer = false">
          取消
        </el-button><el-button type="primary" :loading="saving" @click="completeRun">
          {{ activeRun?.requires_external_processing ? '完工并入半成品库' : '确认完工并入库' }}
        </el-button>
      </div>
    </el-drawer>
  </div>
</template>
