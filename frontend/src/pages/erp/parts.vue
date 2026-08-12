<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { api, money, qty } from './api'
import ListToolbar from './components/ListToolbar.vue'

const loading = ref(false)
const saving = ref(false)
const drawer = ref(false)
const filterDrawer = ref(false)
const keyword = ref('')
const rows = ref<any[]>([])
const filters = reactive({ stockStatus: '', supplyMode: '' })
const activeFilterCount = computed(() => Number(Boolean(filters.stockStatus)) + Number(Boolean(filters.supplyMode)))
const formRef = ref<FormInstance>()
const editingId = ref<number | null>(null)
const emptyForm = () => ({ sku: '', name: '', unit: '件', spec: '', cost_price: 0, min_stock: 0, supply_mode: 'STOCK' })
const form = reactive(emptyForm())
const rules: FormRules = {
  sku: [{ required: true, message: '请输入零件编码', trigger: 'blur' }],
  name: [{ required: true, message: '请输入零件名称', trigger: 'blur' }],
}

async function load() {
  loading.value = true
  const params = new URLSearchParams()
  if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
  if (filters.stockStatus) params.set('stock_status', filters.stockStatus)
  if (filters.supplyMode) params.set('supply_mode', filters.supplyMode)
  try { rows.value = await api(`/api/parts?${params}`) }
  catch (error: any) { ElMessage.error(error.message) }
  finally { loading.value = false }
}
function applyFilters() { filterDrawer.value = false; load() }
function resetFilters() { filters.stockStatus = ''; filters.supplyMode = ''; applyFilters() }
function openCreate() {
  editingId.value = null
  Object.assign(form, emptyForm())
  drawer.value = true
}
function openEdit(row: any) {
  editingId.value = row.id
  Object.assign(form, { sku: row.sku, name: row.name, unit: row.unit, spec: row.spec, cost_price: row.cost_price, min_stock: row.min_stock, supply_mode: row.supply_mode || 'STOCK' })
  drawer.value = true
}
async function save() {
  if (!await formRef.value?.validate().catch(() => false)) return
  saving.value = true
  try {
    await api(editingId.value ? `/api/parts/${editingId.value}` : '/api/parts', { method: editingId.value ? 'PUT' : 'POST', body: JSON.stringify(form) })
    ElMessage.success(editingId.value ? '零件已更新' : '零件已创建')
    drawer.value = false
    await load()
  } catch (error: any) { ElMessage.error(error.message) }
  finally { saving.value = false }
}
async function remove(row: any) {
  try {
    await ElMessageBox.confirm(`确定停用“${row.name}”吗？`, '停用零件', { type: 'warning' })
    await api(`/api/parts/${row.id}`, { method: 'DELETE' })
    ElMessage.success('零件已停用')
    await load()
  } catch (error: any) { if (error !== 'cancel') ElMessage.error(error.message) }
}
onMounted(load)
</script>

<template>
  <div class="erp-page">
    <ListToolbar v-model="keyword" placeholder="搜索零件编码或名称" :filter-count="activeFilterCount" :loading="loading" @search="load" @filter="filterDrawer=true" @refresh="load">
      <el-button type="primary" @click="openCreate"><el-icon><Plus /></el-icon>新建零件</el-button>
    </ListToolbar>
    <div class="content-card">
      <div class="card-head"><h3>零件档案</h3><span>共 {{ rows.length }} 项</span></div>
      <el-table v-loading="loading" :data="rows">
        <el-table-column label="零件" min-width="190"><template #default="{ row }"><div class="sku-cell"><strong>{{ row.name }}</strong><span class="mono">{{ row.sku }}</span></div></template></el-table-column>
        <el-table-column prop="spec" label="规格" min-width="150"><template #default="{ row }">{{ row.spec || '-' }}</template></el-table-column>
        <el-table-column label="单位" width="70" prop="unit" />
        <el-table-column label="备料方式" width="105"><template #default="{ row }"><el-tag :type="row.supply_mode === 'BUY_TO_ORDER' ? 'warning' : 'info'" effect="plain" size="small">{{ row.supply_mode === 'BUY_TO_ORDER' ? '按单即买' : '库存备料' }}</el-tag></template></el-table-column>
        <el-table-column label="成本价" width="110" align="right"><template #default="{ row }">{{ money(row.cost_price) }}</template></el-table-column>
        <el-table-column label="当前库存" width="115" align="right"><template #default="{ row }"><b :class="row.low_stock ? 'number-negative' : ''">{{ qty(row.stock_qty) }}</b> {{ row.unit }}</template></el-table-column>
        <el-table-column label="安全库存" width="100" align="right"><template #default="{ row }">{{ qty(row.min_stock) }}</template></el-table-column>
        <el-table-column label="状态" width="85"><template #default="{ row }"><el-tag :type="row.low_stock ? 'danger' : 'success'" effect="light" size="small">{{ row.low_stock ? '需补货' : '正常' }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="130" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openEdit(row)">编辑</el-button><el-button link type="danger" @click="remove(row)">停用</el-button></template></el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="filterDrawer" title="筛选零件" size="min(420px, 92vw)">
      <el-form label-position="top">
        <el-form-item label="备料方式"><el-select v-model="filters.supplyMode" clearable placeholder="全部方式" style="width:100%"><el-option label="库存备料" value="STOCK" /><el-option label="按单即买" value="BUY_TO_ORDER" /></el-select></el-form-item>
        <el-form-item label="库存状态"><el-select v-model="filters.stockStatus" clearable placeholder="全部状态" style="width:100%"><el-option label="需要补货" value="LOW" /><el-option label="库存正常" value="NORMAL" /></el-select></el-form-item>
        <div class="filter-drawer-footer"><el-button @click="resetFilters">重置</el-button><el-button type="primary" @click="applyFilters">应用筛选</el-button></div>
      </el-form>
    </el-drawer>

    <el-drawer v-model="drawer" :title="editingId ? '编辑零件' : '新建零件'" size="min(520px, 92vw)">
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <div class="form-grid">
          <el-form-item label="零件编码" prop="sku"><el-input v-model="form.sku" placeholder="例如 P-MOTOR-001" /></el-form-item>
          <el-form-item label="零件名称" prop="name"><el-input v-model="form.name" placeholder="请输入名称" /></el-form-item>
          <el-form-item label="规格型号"><el-input v-model="form.spec" placeholder="尺寸、型号等" /></el-form-item>
          <el-form-item label="计量单位"><el-input v-model="form.unit" placeholder="件 / 个 / 米" /></el-form-item>
          <el-form-item label="参考成本"><el-input-number v-model="form.cost_price" :min="0" :precision="2" :controls="false" style="width:100%" /></el-form-item>
          <el-form-item label="安全库存"><el-input-number v-model="form.min_stock" :min="0" :precision="2" :controls="false" style="width:100%" /></el-form-item>
          <el-form-item class="span-2" label="备料方式"><el-radio-group v-model="form.supply_mode"><el-radio-button value="STOCK">库存备料</el-radio-button><el-radio-button value="BUY_TO_ORDER">按单即买</el-radio-button></el-radio-group><div class="form-help">库存备料用于常备零件；按单即买会在客单缺料清单中明确提示按订单采购。</div></el-form-item>
        </div>
        <div class="drawer-footer"><el-button @click="drawer=false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存零件</el-button></div>
      </el-form>
    </el-drawer>
  </div>
</template>
