<script setup lang="ts">
import { ElMessage, ElMessageBox } from "element-plus"
import { computed, onMounted, reactive, ref } from "vue"
import { api, formatDate, productQty, useLiveRefresh } from "./api"

const loading = ref(false)
const saving = ref(false)
const rows = ref<any[]>([])
const statusFilter = ref("ACTIVE")
const completionDrawer = ref(false)
const terminationDrawer = ref(false)
const activeRun = ref<any>(null)
const form = reactive({ qualified_quantity: 1, scrap_quantity: 0, completion_date: "", notes: "" })
const terminationForm = reactive({ qualified_quantity: 0, scrap_quantity: 0, termination_reason: "" })
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
function openTermination(row: any) {
  activeRun.value = row
  terminationForm.qualified_quantity = 0
  terminationForm.scrap_quantity = 0
  terminationForm.termination_reason = ""
  terminationDrawer.value = true
}
function materialShortageText(row: any) {
  return (row.material_shortages || [])
    .map((item: any) => `${item.name}缺 ${productQty(item.shortage_quantity)} ${item.unit}`)
    .join("；")
}
async function startRun(row: any) {
  if (!row.materials_ready) {
    void ElMessageBox.alert(
      `当前不能开工：${materialShortageText(row)}。请先办理零件入库。`,
      "生产缺料",
      { type: "warning" }
    )
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认开始生产"${row.product_name}" ${productQty(row.planned_quantity)} ${row.unit}？确认后将按 BOM 自动办理零件出库。`,
      "开始生产",
      { type: "warning" }
    )
    await api(`/api/production/runs/${row.id}/status`, {
      method: "PUT",
      body: JSON.stringify({ status: "RUNNING" })
    })
    ElMessage.success("生产已开始，BOM 零件已自动出库；完工后请审核实际合格数量")
    await load(true)
  } catch (error: any) {
    if (error !== "cancel") ElMessage.error(error.message)
  }
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
      await ElMessageBox.confirm(`合格+报废高于计划数量 ${productQty(excess)}，超出部分将补领 BOM 零件。是否继续？`, "产量高于计划", { type: "warning" })
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
async function terminateRun() {
  const qualified = Number(terminationForm.qualified_quantity)
  const scrap = Number(terminationForm.scrap_quantity)
  if (qualified < 0 || scrap < 0) return ElMessage.warning("数量不能为负")
  if (qualified + scrap > Number(activeRun.value.planned_quantity)) {
    return ElMessage.warning("合格+报废不能超过计划数量")
  }
  saving.value = true
  try {
    await api(`/api/production/runs/${activeRun.value.id}/status`, {
      method: "PUT",
      body: JSON.stringify({ status: "TERMINATED", ...terminationForm })
    })
    const unproduced = Number(activeRun.value.planned_quantity) - qualified - scrap
    ElMessage.success(`已终止生产：合格 ${qualified}、报废 ${scrap}、退未生产料 ${unproduced} 套`)
    terminationDrawer.value = false
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
        <h3>生产入库审核</h3>
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
        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'PLANNED'" link type="primary" @click="startRun(row)">
              开始生产
            </el-button><template v-else-if="row.status === 'RUNNING'">
              <el-button link type="primary" @click="openCompletion(row)">
                审核入库
              </el-button><el-button link type="danger" @click="openTermination(row)">
                终止生产
              </el-button>
            </template><span v-else class="muted">{{ row.status === 'COMPLETED' ? '已入库' : row.status === 'TERMINATED' ? '已终止' : '已取消' }}</span>
          </template>
        </el-table-column>
      </el-table>
    </section>
    <el-drawer v-model="completionDrawer" title="审核生产入库" size="min(520px, 96vw)">
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
          {{ activeRun?.requires_external_processing ? '审核并入半成品库' : '审核通过并入库' }}
        </el-button>
      </div>
    </el-drawer>
    <el-drawer v-model="terminationDrawer" title="终止生产结算" size="min(520px, 96vw)">
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
        type="warning"
        :closable="false"
        show-icon
        style="margin-top: 16px"
        title="终止生产将退回未生产部分的 BOM 零件，合格品入库，报废品消耗 BOM 但不入库。"
      />
      <el-form label-position="top" style="margin-top: 20px">
        <el-form-item label="合格数量" required>
          <el-input-number v-model="terminationForm.qualified_quantity" :min="0" :precision="0" :max="Number(activeRun?.planned_quantity || 0)" style="width:100%" />
        </el-form-item><el-form-item label="报废数量">
          <el-input-number v-model="terminationForm.scrap_quantity" :min="0" :precision="0" :max="Number(activeRun?.planned_quantity || 0)" style="width:100%" />
        </el-form-item><el-form-item label="终止原因">
          <el-input v-model="terminationForm.termination_reason" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <div class="drawer-footer">
        <el-button @click="terminationDrawer = false">
          取消
        </el-button><el-button type="danger" :loading="saving" @click="terminateRun">
          确认终止生产
        </el-button>
      </div>
    </el-drawer>
  </div>
</template>
