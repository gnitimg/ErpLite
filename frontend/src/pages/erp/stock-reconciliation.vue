<script setup lang="ts">
import { ElMessage } from "element-plus"
import { computed, onMounted, reactive, ref } from "vue"
import { api, useLiveRefresh } from "./api"
import ListToolbar from "./components/ListToolbar.vue"

interface InventoryRow {
  id: number
  sku: string
  name: string
  spec: string
  kind: "PART" | "PRODUCT"
  stock_qty: number
  unit: string
}

interface AuditRow {
  item_id: number
  sku: string
  name: string
  kind: "PART" | "PRODUCT"
  stored_stock: number
  ledger_stock: number
  difference: number
  ok: boolean
  audit_note: string | null
}

const loading = ref(false)
const submitting = ref(false)
const activeTab = ref("stocktake")
const keyword = ref("")
const rows = ref<InventoryRow[]>([])
const auditRows = ref<AuditRow[]>([])
const counts = reactive<Record<number, number | undefined>>({})
const notes = ref("")
const onlyDifferences = ref(false)

const token = computed(() => keyword.value.trim().toLowerCase())
const filteredRows = computed(() => rows.value.filter(row =>
  !token.value || `${row.sku} ${row.name} ${row.spec}`.toLowerCase().includes(token.value)
))
const filteredAuditRows = computed(() => auditRows.value.filter(row =>
  (!onlyDifferences.value || !row.ok)
  && (!token.value || `${row.sku} ${row.name}`.toLowerCase().includes(token.value))
))

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    const [inventory, audit] = await Promise.all([
      api("/api/inventory?pageSize=9999"),
      api("/api/stock/audit")
    ])
    rows.value = inventory.items || inventory || []
    auditRows.value = audit || []
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    if (!silent) loading.value = false
  }
}

async function submit() {
  const discrepancies = filteredRows.value
    .map(item => ({ item, difference: (counts[item.id] ?? item.stock_qty) - item.stock_qty }))
    .filter(row => Math.abs(row.difference) > 1e-9)
  if (!discrepancies.length) {
    ElMessage.info("没有盘点差异，无需调整")
    return
  }
  submitting.value = true
  try {
    const result = await api("/api/stock/stocktake", {
      method: "POST",
      body: JSON.stringify({
        items: discrepancies.map(row => ({
          item_id: row.item.id,
          physical_count: counts[row.item.id] ?? row.item.stock_qty
        })),
        notes: notes.value
      })
    })
    ElMessage.success(`盘点完成，调整 ${discrepancies.length} 项，生成 ${result.transactions?.length || 0} 张流水`)
    Object.keys(counts).forEach(key => delete counts[Number(key)])
    notes.value = ""
    await load()
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    submitting.value = false
  }
}

onMounted(() => load())
useLiveRefresh(() => load(true))
</script>

<template>
  <div class="erp-page">
    <ListToolbar v-model="keyword" placeholder="搜索SKU、名称" :loading="loading" @refresh="load" />

    <el-tabs v-model="activeTab" class="content-card">
      <el-tab-pane label="库存盘点" name="stocktake">
        <el-alert
          class="list-page-alert"
          title="录入实物数量后提交盘点；盘盈生成 MANUAL_IN，盘亏生成 MANUAL_OUT。"
          type="info"
          :closable="false"
          show-icon
        />
        <div class="card-head">
          <h3>库存盘点</h3><span>零件与产品均可盘点</span>
        </div>
        <el-table v-loading="loading" :data="filteredRows" row-key="id" empty-text="暂无库存">
          <el-table-column label="SKU" prop="sku" width="140" />
          <el-table-column label="名称" prop="name" min-width="120" />
          <el-table-column label="类型" width="90">
            <template #default="{ row }">{{ row.kind === "PART" ? "零件" : "产品" }}</template>
          </el-table-column>
          <el-table-column label="规格" prop="spec" width="120" />
          <el-table-column label="系统库存" prop="stock_qty" width="100" align="right" />
          <el-table-column label="实物盘点" width="140">
            <template #default="{ row }">
              <el-input-number
                v-model="counts[row.id]"
                :placeholder="String(row.stock_qty)"
                :controls="false"
                :precision="row.kind === 'PRODUCT' ? 0 : undefined"
                :min="0"
                size="small"
                style="width:100%"
              />
            </template>
          </el-table-column>
          <el-table-column label="差异" width="90" align="right">
            <template #default="{ row }">
              <span :style="{ color: (counts[row.id] ?? row.stock_qty) - row.stock_qty !== 0 ? 'var(--el-color-danger)' : '' }">
                {{ (counts[row.id] ?? row.stock_qty) - row.stock_qty }}
              </span>
            </template>
          </el-table-column>
        </el-table>
        <div style="margin-top:16px;display:flex;gap:12px;align-items:center">
          <el-input v-model="notes" placeholder="盘点备注" style="max-width:300px" />
          <el-button type="primary" :loading="submitting" @click="submit">提交盘点</el-button>
        </div>
      </el-tab-pane>

      <el-tab-pane label="系统库存对账" name="audit">
        <el-alert
          class="list-page-alert"
          title="只读比较系统库存与主库存流水，不会自动修改库存；发现差异后请人工盘点。"
          type="warning"
          :closable="false"
          show-icon
        />
        <div class="card-head">
          <h3>系统库存对账</h3>
          <el-checkbox v-model="onlyDifferences">只显示差异</el-checkbox>
        </div>
        <el-table v-loading="loading" :data="filteredAuditRows" row-key="item_id" empty-text="暂无库存">
          <el-table-column label="SKU" prop="sku" width="140" />
          <el-table-column label="名称" prop="name" min-width="140" />
          <el-table-column label="类型" width="90">
            <template #default="{ row }">{{ row.kind === "PART" ? "零件" : "产品" }}</template>
          </el-table-column>
          <el-table-column label="系统库存" prop="stored_stock" width="110" align="right" />
          <el-table-column label="流水库存" prop="ledger_stock" width="110" align="right" />
          <el-table-column label="差异" prop="difference" width="100" align="right" />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="row.ok ? 'success' : 'danger'">{{ row.ok ? "一致" : "有差异" }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="说明" min-width="220">
            <template #default="{ row }">{{ row.audit_note || "—" }}</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>
