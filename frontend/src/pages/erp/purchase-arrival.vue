<script setup lang="ts">
import { ElMessage, ElMessageBox } from "element-plus"
import { onMounted, ref, reactive } from "vue"
import { api, formatTime, useLiveRefresh } from "./api"
import ListToolbar from "./components/ListToolbar.vue"
import InfoTip from "./components/InfoTip.vue"

interface Commitment {
  id: number
  part_id: number
  part_sku: string
  part_name: string
  unit: string
  supplier_text: string
  quantity: number
  expected_arrival_at: string
  status: string
  notes: string
  created_at: string
  updated_at: string
}

const loading = ref(false)
const keyword = ref("")
const rows = ref<Commitment[]>([])
const dialog = ref(false)
const form = reactive({ part_id: 0, supplier_text: "", quantity: 0, expected_arrival_date: "", notes: "" })
const parts = ref<{ id: number; sku: string; name: string }[]>([])

const statusLabels: Record<string, string> = { PLANNED: "待到货", ARRIVED: "已到货", CANCELLED: "已取消" }
const statusTypes: Record<string, string> = { PLANNED: "warning", ARRIVED: "success", CANCELLED: "info" }

const filteredRows = ref<Commitment[]>([])
function applyFilter() {
  const token = keyword.value.trim().toLowerCase()
  filteredRows.value = rows.value.filter(r => !token || `#${r.id} ${r.part_sku} ${r.part_name} ${r.supplier_text}`.toLowerCase().includes(token))
}

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    rows.value = await api("/api/purchase/commitments")
    applyFilter()
    if (!parts.value.length) {
      const data = await api("/api/inventory?kind=PART&pageSize=9999")
      parts.value = (data.items || data || []).map((p: any) => ({ id: p.id, sku: p.sku, name: p.name }))
    }
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    if (!silent) loading.value = false
  }
}

async function save() {
  try {
    await api("/api/purchase/commitments", {
      method: "POST",
      body: JSON.stringify(form)
    })
    ElMessage.success("采购预计到货已登记")
    dialog.value = false
    await load()
  } catch (error: any) {
    ElMessage.error(error.message)
  }
}

async function markArrived(row: Commitment) {
  try {
    await ElMessageBox.confirm(`确认标记 #${row.id}（${row.part_sku}）已到货？`, "到货确认", { type: "warning" })
    await api(`/api/purchase/commitments/${row.id}/status`, {
      method: "PUT",
      body: JSON.stringify({ status: "ARRIVED" })
    })
    ElMessage.success("已标记到货")
    await load()
  } catch (error: any) {
    if (error !== "cancel" && error !== "close") ElMessage.error(error.message)
  }
}

async function remove(row: Commitment) {
  try {
    await ElMessageBox.confirm(`确认取消 #${row.id}（${row.part_sku}）的预计到货？`, "取消预计到货", { type: "warning" })
    await api(`/api/purchase/commitments/${row.id}`, { method: "DELETE" })
    ElMessage.success("预计到货已取消")
    await load()
  } catch (error: any) {
    if (error !== "cancel" && error !== "close") ElMessage.error(error.message)
  }
}

onMounted(load)
useLiveRefresh(() => load(true))
</script>

<template>
  <div class="erp-page">
    <ListToolbar v-model="keyword" placeholder="搜索原料、供应商" :loading="loading" @refresh="load" @update:model-value="applyFilter">
      <el-button type="primary" @click="dialog = true; form.part_id = 0; form.supplier_text = ''; form.quantity = 0; form.expected_arrival_date = ''; form.notes = ''">
        <el-icon><Plus /></el-icon>登记预计到货
      </el-button>
    </ListToolbar>

    <div class="content-card">
      <div class="card-head">
        <h3>
          到货登记
          <InfoTip content="登记采购数量和预计到货日期后，系统会自动更新排产预计完成日期。" />
        </h3>
      </div>
      <el-table v-loading="loading" :data="filteredRows" row-key="id" empty-text="暂无到货登记">
        <el-table-column label="原料" min-width="180">
          <template #default="{ row }">{{ row.part_sku }} {{ row.part_name }}</template>
        </el-table-column>
        <el-table-column label="供应商" prop="supplier_text" width="120" />
        <el-table-column label="数量" prop="quantity" width="80" align="right" />
        <el-table-column label="预计到货" width="120">
          <template #default="{ row }">{{ row.expected_arrival_at?.slice(0, 10) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="(statusTypes[row.status] as any) || 'info'" size="small">{{ statusLabels[row.status] || row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'PLANNED'" link type="success" @click="markArrived(row as any)">确认到货</el-button>
            <el-button v-if="row.status === 'PLANNED'" link type="danger" @click="remove(row as any)">取消</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialog" title="登记采购预计到货" width="480px">
      <el-form label-position="top">
        <el-form-item label="原料">
          <el-select v-model="form.part_id" filterable placeholder="选择原料" style="width:100%">
            <el-option v-for="p in parts" :key="p.id" :label="`${p.sku} ${p.name}`" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="供应商"><el-input v-model="form.supplier_text" /></el-form-item>
        <el-form-item label="数量"><el-input-number v-model="form.quantity" :min="0" style="width:100%" /></el-form-item>
        <el-form-item label="预计到货日期"><el-date-picker v-model="form.expected_arrival_date" type="date" value-format="YYYY-MM-DD" style="width:100%" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.notes" type="textarea" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="save">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>
