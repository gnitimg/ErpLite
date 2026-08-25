<script setup lang="ts">
import type { FormInstance, FormRules } from "element-plus"
import { ElMessage, ElMessageBox } from "element-plus"
import { computed, onMounted, reactive, ref } from "vue"
import { api, money, productQty, qty, useLiveRefresh } from "./api"
import ListToolbar from "./components/ListToolbar.vue"
import QuantityInput from "./components/QuantityInput.vue"

const loading = ref(false)
const saving = ref(false)
const drawer = ref(false)
const filterDrawer = ref(false)
const keyword = ref("")
const rows = ref<any[]>([])
const parts = ref<any[]>([])
const filters = reactive({ stockStatus: "", bomStatus: "" })
const activeFilterCount = computed(() => Number(Boolean(filters.stockStatus)) + Number(Boolean(filters.bomStatus)))
const editingId = ref<number | null>(null)
const formRef = ref<FormInstance>()
const emptyForm = () => ({
  sku: "",
  name: "",
  unit: "台",
  spec: "",
  cost_price: 0,
  sale_price: 0,
  min_stock: 0,
  mold_count: 1,
  daily_capacity: 0,
  requires_external_processing: false,
  external_process_name: "",
  default_external_lead_days: 0,
  components: [] as any[]
})
const form = reactive(emptyForm())
const rules: FormRules = {
  sku: [{ required: true, message: "请输入产品编码", trigger: "blur" }],
  name: [{ required: true, message: "请输入产品名称", trigger: "blur" }]
}

async function load(silent = false) {
  if (!silent) loading.value = true
  const params = new URLSearchParams()
  if (keyword.value.trim()) params.set("keyword", keyword.value.trim())
  if (filters.stockStatus) params.set("stock_status", filters.stockStatus)
  if (filters.bomStatus) params.set("bom_status", filters.bomStatus)
  try {
    [rows.value, parts.value] = await Promise.all([api(`/api/products?${params}`), api("/api/parts")])
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
  filters.bomStatus = ""
  applyFilters()
}
function openCreate() {
  editingId.value = null
  Object.assign(form, emptyForm())
  form.components.push({ part_id: undefined, quantity: 1 })
  drawer.value = true
}
function openEdit(row: any) {
  editingId.value = row.id
  Object.assign(form, {
    sku: row.sku,
    name: row.name,
    unit: row.unit,
    spec: row.spec,
    cost_price: row.cost_price,
    sale_price: row.sale_price,
    min_stock: row.min_stock,
    mold_count: row.mold_count || 1,
    daily_capacity: row.daily_capacity || 0,
    requires_external_processing: Boolean(row.requires_external_processing),
    external_process_name: row.external_process_name || "",
    default_external_lead_days: Number(row.default_external_lead_days || 0),
    components: row.components.map((line: any) => ({
      part_id: line.part_id,
      quantity: line.quantity
    }))
  })
  drawer.value = true
}
function addComponent() {
  form.components.push({ part_id: undefined, quantity: 1 })
}
function removeComponent(index: number) {
  form.components.splice(index, 1)
}
async function save() {
  if (!await formRef.value?.validate().catch(() => false)) return
  if (form.components.some(line => !line.part_id || Number(line.quantity) <= 0)) return ElMessage.warning("请完整填写 BOM 零件和用量")
  if (form.requires_external_processing && !form.external_process_name.trim()) return ElMessage.warning("请填写外协工序名称")
  saving.value = true
  try {
    await api(editingId.value ? `/api/products/${editingId.value}` : "/api/products", { method: editingId.value ? "PUT" : "POST", body: JSON.stringify(form) })
    ElMessage.success(editingId.value ? "产品已更新" : "产品已创建")
    drawer.value = false
    await load()
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    saving.value = false
  }
}
async function remove(row: any) {
  try {
    await ElMessageBox.confirm(`确定停用“${row.name}”吗？`, "停用产品", { type: "warning" })
    await api(`/api/products/${row.id}`, { method: "DELETE" })
    ElMessage.success("产品已停用")
    await load()
  } catch (error: any) {
    if (error !== "cancel") ElMessage.error(error.message)
  }
}
onMounted(load)
useLiveRefresh(() => load(true))
</script>

<template>
  <div class="erp-page">
    <ListToolbar
      v-model="keyword"
      placeholder="搜索产品编码或名称"
      :filter-count="activeFilterCount"
      :loading="loading"
      @search="load"
      @filter="filterDrawer = true"
      @refresh="load"
    >
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>新建产品
      </el-button>
    </ListToolbar>
    <div class="content-card">
      <div class="card-head">
        <h3>产品目录</h3>
      </div>
      <el-table v-loading="loading" :data="rows">
        <el-table-column label="产品" min-width="190">
          <template #default="{ row }">
            <div class="sku-cell">
              <strong>{{ row.name }}</strong><span class="mono">{{ row.sku }} · {{ row.spec || '无规格' }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="BOM 组成" min-width="280">
          <template #default="{ row }">
            <div v-if="row.components.length" class="bom-summary">
              <el-tag v-for="line in row.components" :key="line.id" size="small" effect="plain">
                {{ line.part_name }} × {{ qty(line.quantity) }}
              </el-tag>
            </div><span v-else class="muted">尚未配置</span>
          </template>
        </el-table-column>
        <el-table-column label="成本 / 售价" width="150" align="right">
          <template #default="{ row }">
            <div>{{ money(row.cost_price) }}</div><div class="muted">
              售 {{ money(row.sale_price) }}
            </div>
          </template>
        </el-table-column>
        <el-table-column label="成品库存" width="115" align="right">
          <template #default="{ row }">
            <b :class="row.low_stock ? 'number-negative' : ''">{{ productQty(row.stock_qty) }}</b> {{ row.unit }}
          </template>
        </el-table-column>
        <el-table-column label="模具数" width="90" align="right">
          <template #default="{ row }">
            {{ row.mold_count || 1 }} 套
          </template>
        </el-table-column>
        <el-table-column label="单机日产量" width="125" align="right">
          <template #default="{ row }">
            {{ productQty(row.daily_capacity) }} {{ row.unit }}/日
          </template>
        </el-table-column>
        <el-table-column label="状态" width="85">
          <template #default="{ row }">
            <el-tag :type="row.low_stock ? 'danger' : 'success'" size="small">
              {{ row.low_stock ? '偏低' : '正常' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">
              编辑
            </el-button><el-button link type="danger" @click="remove(row)">
              停用
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="filterDrawer" title="筛选产品" size="min(420px, 92vw)">
      <el-form label-position="top">
        <el-form-item label="库存状态">
          <el-select v-model="filters.stockStatus" clearable placeholder="全部状态" style="width:100%">
            <el-option label="库存偏低" value="LOW" /><el-option label="库存正常" value="NORMAL" />
          </el-select>
        </el-form-item>
        <el-form-item label="BOM 状态">
          <el-select v-model="filters.bomStatus" clearable placeholder="全部状态" style="width:100%">
            <el-option label="已配置 BOM" value="CONFIGURED" /><el-option label="未配置 BOM" value="EMPTY" />
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
      v-model="drawer"
      class="product-edit-drawer"
      :title="editingId ? '编辑产品目录' : '新建产品目录'"
      size="min(720px, 96vw)"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <div class="form-grid">
          <el-form-item label="产品编码" prop="sku">
            <el-input v-model="form.sku" placeholder="例如 FG-CTRL-01" />
          </el-form-item>
          <el-form-item label="产品名称" prop="name">
            <el-input v-model="form.name" placeholder="请输入产品名称" />
          </el-form-item>
          <el-form-item label="规格型号">
            <el-input v-model="form.spec" placeholder="版本、尺寸等" />
          </el-form-item>
          <el-form-item label="计量单位">
            <el-input v-model="form.unit" />
          </el-form-item>
          <el-form-item label="参考成本">
            <el-input-number v-model="form.cost_price" :min="0" :precision="2" :controls="false" style="width:100%" />
          </el-form-item>
          <el-form-item label="销售单价">
            <el-input-number v-model="form.sale_price" :min="0" :precision="2" :controls="false" style="width:100%" />
          </el-form-item>
        </div>
        <div class="form-grid form-grid-three">
          <el-form-item label="安全库存">
            <QuantityInput v-model="form.min_stock" integer :min="0" :unit="form.unit" />
          </el-form-item>
          <el-form-item label="模具数量">
            <QuantityInput v-model="form.mold_count" integer :min="1" unit="套" />
          </el-form-item>
          <el-form-item label="单机日产量">
            <QuantityInput
              v-model="form.daily_capacity"
              integer
              :min="0"
              :unit="`${form.unit}/日`"
            />
          </el-form-item>
        </div>
        <div class="section-label">
          <span>BOM 原料清单</span><el-button size="small" plain @click="addComponent">
            <el-icon><Plus /></el-icon>添加一行
          </el-button>
        </div>
        <el-table :data="form.components" border>
          <el-table-column label="组成原料" min-width="260">
            <template #default="{ row }">
              <el-select v-model="row.part_id" filterable placeholder="选择零件" style="width:100%">
                <el-option
                  v-for="part in parts"
                  :key="part.id"
                  :label="`${part.sku} · ${part.name}`"
                  :value="part.id"
                  :disabled="form.components.some(x => x !== row && x.part_id === part.id)"
                />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="单台用量" width="170">
            <template #default="{ row }">
              <el-input-number v-model="row.quantity" :min="0.001" :precision="3" :controls="false" style="width:100%" />
            </template>
          </el-table-column>
          <el-table-column width="65" align="center">
            <template #default="{ $index }">
              <el-button link type="danger" @click="removeComponent($index)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-alert v-if="!form.components.length" title="当前产品没有 BOM。仍可保存，但不能执行按 BOM 生产入库。" type="warning" :closable="false" style="margin-top:10px" />
      </el-form>
      <template #footer>
        <div class="drawer-action-bar">
          <el-button @click="drawer = false">
            取消
          </el-button><el-button type="primary" :loading="saving" @click="save">
            保存产品
          </el-button>
        </div>
      </template>
    </el-drawer>
  </div>
</template>
