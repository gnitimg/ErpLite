<script setup lang="ts">
import type { FormInstance, FormRules } from "element-plus"
import { ElMessage, ElMessageBox } from "element-plus"
import { computed, onMounted, reactive, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
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
type CatalogScope = "PART" | "PRODUCT"
const route = useRoute()
const router = useRouter()
const scope = ref<CatalogScope>(route.query.scope === "PART" ? "PART" : "PRODUCT")
const isProduct = computed(() => scope.value === "PRODUCT")
const scopeLabel = computed(() => isProduct.value ? "产品" : "材料")
const filters = reactive({ stockStatus: "", bomStatus: "", supplyMode: "" })
const activeFilterCount = computed(() => [
  filters.stockStatus,
  isProduct.value ? filters.bomStatus : filters.supplyMode
].filter(Boolean).length)
const editingId = ref<number | null>(null)
const formRef = ref<FormInstance>()
function emptyForm() {
  return {
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
    supply_mode: "STOCK",
    components: [] as any[]
  }
}
const form = reactive(emptyForm())
const rules: FormRules = {
  sku: [{ required: true, message: "请输入物料编码", trigger: "blur" }],
  name: [{ required: true, message: "请输入物料名称", trigger: "blur" }]
}

async function load(silent = false) {
  if (!silent) loading.value = true
  const params = new URLSearchParams()
  if (keyword.value.trim()) params.set("keyword", keyword.value.trim())
  if (filters.stockStatus) params.set("stock_status", filters.stockStatus)
  if (isProduct.value && filters.bomStatus) params.set("bom_status", filters.bomStatus)
  if (!isProduct.value && filters.supplyMode) params.set("supply_mode", filters.supplyMode)
  try {
    if (isProduct.value) {
      [rows.value, parts.value] = await Promise.all([
        api(`/api/products?${params}`),
        api("/api/parts")
      ])
    } else {
      rows.value = await api(`/api/parts?${params}`)
    }
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
  filters.supplyMode = ""
  applyFilters()
}
function openCreate() {
  editingId.value = null
  Object.assign(form, emptyForm())
  if (isProduct.value) form.components.push({ part_id: undefined, quantity: 1 })
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
    sale_price: row.sale_price || 0,
    min_stock: row.min_stock,
    mold_count: row.mold_count || 1,
    daily_capacity: row.daily_capacity || 0,
    requires_external_processing: Boolean(row.requires_external_processing),
    external_process_name: row.external_process_name || "",
    default_external_lead_days: Number(row.default_external_lead_days || 0),
    supply_mode: row.supply_mode || "STOCK",
    components: (row.components || []).map((line: any) => ({
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
  if (isProduct.value && form.components.some(line => !line.part_id || Number(line.quantity) <= 0)) {
    return ElMessage.warning("请完整填写 BOM 材料和用量")
  }
  if (isProduct.value && form.requires_external_processing && !form.external_process_name.trim()) {
    return ElMessage.warning("请填写外协工序名称")
  }
  saving.value = true
  try {
    const endpoint = isProduct.value ? "/api/products" : "/api/parts"
    const productPayload = {
      sku: form.sku,
      name: form.name,
      unit: form.unit,
      spec: form.spec,
      cost_price: form.cost_price,
      sale_price: form.sale_price,
      min_stock: form.min_stock,
      mold_count: form.mold_count,
      daily_capacity: form.daily_capacity,
      requires_external_processing: form.requires_external_processing,
      external_process_name: form.external_process_name,
      default_external_lead_days: form.default_external_lead_days,
      components: form.components
    }
    const partPayload = {
      sku: form.sku,
      name: form.name,
      unit: form.unit,
      spec: form.spec,
      cost_price: form.cost_price,
      min_stock: form.min_stock,
      supply_mode: form.supply_mode
    }
    await api(editingId.value ? `${endpoint}/${editingId.value}` : endpoint, {
      method: editingId.value ? "PUT" : "POST",
      body: JSON.stringify(isProduct.value ? productPayload : partPayload)
    })
    ElMessage.success(`${scopeLabel.value}${editingId.value ? "已更新" : "已创建"}`)
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
    await ElMessageBox.confirm(
      `确定停用“${row.name}”吗？`,
      `停用${scopeLabel.value}`,
      { type: "warning" }
    )
    await api(`/api/${isProduct.value ? "products" : "parts"}/${row.id}`, {
      method: "DELETE"
    })
    ElMessage.success(`${scopeLabel.value}已停用`)
    await load()
  } catch (error: any) {
    if (error !== "cancel") ElMessage.error(error.message)
  }
}
watch(scope, async (value) => {
  keyword.value = ""
  filters.stockStatus = ""
  filters.bomStatus = ""
  filters.supplyMode = ""
  await router.replace({
    path: "/lite-settings/items",
    query: { ...route.query, scope: value }
  })
  await load()
})
watch(() => route.query.scope, (value) => {
  const nextScope: CatalogScope = value === "PART" ? "PART" : "PRODUCT"
  if (scope.value !== nextScope) scope.value = nextScope
})
onMounted(load)
useLiveRefresh(() => load(true))
</script>

<template>
  <div class="erp-page">
    <ListToolbar
      v-model="keyword"
      :placeholder="`搜索${scopeLabel}编码、名称或规格`"
      :filter-count="activeFilterCount"
      :loading="loading"
      @search="load"
      @filter="filterDrawer = true"
      @refresh="load"
    >
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>新建{{ scopeLabel }}
      </el-button>
    </ListToolbar>
    <div class="content-card">
      <div class="card-head catalog-card-head">
        <h3>物料资料</h3>
        <div class="catalog-head-actions">
          <el-segmented
            v-model="scope"
            :options="[
              { label: '材料', value: 'PART' },
              { label: '产品', value: 'PRODUCT' },
            ]"
            class="operation-scope-switch"
          />
        </div>
      </div>
      <el-table v-if="isProduct" v-loading="loading" :data="rows">
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
      <el-table v-else v-loading="loading" :data="rows">
        <el-table-column label="材料" min-width="210">
          <template #default="{ row }">
            <div class="sku-cell">
              <strong>{{ row.name }}</strong>
              <span class="mono">{{ row.sku }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="规格" min-width="150">
          <template #default="{ row }">
            {{ row.spec || '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="unit" label="单位" width="75" />
        <el-table-column label="备料方式" width="115">
          <template #default="{ row }">
            <el-tag
              :type="row.supply_mode === 'BUY_TO_ORDER' ? 'warning' : 'info'"
              effect="plain"
              size="small"
            >
              {{ row.supply_mode === 'BUY_TO_ORDER' ? '按单即买' : '库存备料' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="参考成本" width="120" align="right">
          <template #default="{ row }">
            {{ money(row.cost_price) }}
          </template>
        </el-table-column>
        <el-table-column label="当前库存" width="125" align="right">
          <template #default="{ row }">
            <b :class="row.low_stock ? 'number-negative' : ''">
              {{ qty(row.stock_qty) }}
            </b>
            {{ row.unit }}
          </template>
        </el-table-column>
        <el-table-column label="安全库存" width="110" align="right">
          <template #default="{ row }">
            {{ qty(row.min_stock) }} {{ row.unit }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.low_stock ? 'danger' : 'success'" size="small">
              {{ row.low_stock ? '需补货' : '正常' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">
              编辑
            </el-button>
            <el-button link type="danger" @click="remove(row)">
              停用
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-drawer
      v-model="filterDrawer"
      :title="`筛选${scopeLabel}`"
      size="min(420px, 92vw)"
    >
      <el-form label-position="top">
        <el-form-item v-if="!isProduct" label="备料方式">
          <el-select
            v-model="filters.supplyMode"
            clearable
            placeholder="全部方式"
            style="width: 100%"
          >
            <el-option label="库存备料" value="STOCK" />
            <el-option label="按单即买" value="BUY_TO_ORDER" />
          </el-select>
        </el-form-item>
        <el-form-item label="库存状态">
          <el-select
            v-model="filters.stockStatus"
            clearable
            placeholder="全部状态"
            style="width: 100%"
          >
            <el-option
              :label="isProduct ? '库存偏低' : '需要补货'"
              value="LOW"
            />
            <el-option label="库存正常" value="NORMAL" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="isProduct" label="BOM 状态">
          <el-select
            v-model="filters.bomStatus"
            clearable
            placeholder="全部状态"
            style="width: 100%"
          >
            <el-option label="已配置 BOM" value="CONFIGURED" />
            <el-option label="未配置 BOM" value="EMPTY" />
          </el-select>
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
      class="product-edit-drawer"
      :title="editingId ? `编辑${scopeLabel}` : `新建${scopeLabel}`"
      :size="isProduct ? 'min(720px, 96vw)' : 'min(560px, 94vw)'"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <div class="form-grid">
          <el-form-item :label="`${scopeLabel}编码`" prop="sku">
            <el-input
              v-model="form.sku"
              :placeholder="isProduct ? '例如 FG-CTRL-01' : '例如 P-MOTOR-001'"
            />
          </el-form-item>
          <el-form-item :label="`${scopeLabel}名称`" prop="name">
            <el-input v-model="form.name" :placeholder="`请输入${scopeLabel}名称`" />
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
          <el-form-item v-if="isProduct" label="销售单价">
            <el-input-number v-model="form.sale_price" :min="0" :precision="2" :controls="false" style="width:100%" />
          </el-form-item>
          <el-form-item v-else label="安全库存">
            <QuantityInput v-model="form.min_stock" :min="0" :unit="form.unit" />
          </el-form-item>
        </div>
        <el-form-item v-if="!isProduct" label="备料方式">
          <el-radio-group v-model="form.supply_mode">
            <el-radio-button value="STOCK">
              库存备料
            </el-radio-button>
            <el-radio-button value="BUY_TO_ORDER">
              按单即买
            </el-radio-button>
          </el-radio-group>
        </el-form-item>
        <div v-if="isProduct" class="form-grid form-grid-three">
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
        <div v-if="isProduct" class="section-label">
          <span>BOM 材料清单</span><el-button size="small" plain @click="addComponent">
            <el-icon><Plus /></el-icon>添加一行
          </el-button>
        </div>
        <el-table v-if="isProduct" :data="form.components" border>
          <el-table-column label="组成原料" min-width="260">
            <template #default="{ row }">
              <el-select v-model="row.part_id" filterable placeholder="选择材料" style="width:100%">
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
        <el-alert v-if="isProduct && !form.components.length" title="当前产品没有 BOM。仍可保存，但不能执行按 BOM 生产入库。" type="warning" :closable="false" style="margin-top:10px" />
      </el-form>
      <template #footer>
        <div class="drawer-action-bar">
          <el-button @click="drawer = false">
            取消
          </el-button><el-button type="primary" :loading="saving" @click="save">
            保存{{ scopeLabel }}
          </el-button>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.catalog-card-head {
  align-items: center;
}

.catalog-head-actions {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-left: auto;
}

.catalog-count {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  white-space: nowrap;
}

.operation-scope-switch {
  width: 128px;
  min-width: 128px;
  max-width: 128px;
  margin: 0;
  align-self: center;
  flex: none;
}

@media (max-width: 640px) {
  .catalog-head-actions {
    gap: 8px;
  }

  .catalog-count {
    display: none;
  }
}
</style>
