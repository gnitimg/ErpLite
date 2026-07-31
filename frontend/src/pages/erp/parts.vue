<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { api, money, qty } from './api'

const loading = ref(false)
const saving = ref(false)
const drawer = ref(false)
const keyword = ref('')
const rows = ref<any[]>([])
const formRef = ref<FormInstance>()
const editingId = ref<number | null>(null)
const emptyForm = () => ({ sku: '', name: '', unit: '件', spec: '', cost_price: 0, min_stock: 0 })
const form = reactive(emptyForm())
const rules: FormRules = {
  sku: [{ required: true, message: '请输入零件编码', trigger: 'blur' }],
  name: [{ required: true, message: '请输入零件名称', trigger: 'blur' }],
}

async function load() {
  loading.value = true
  try { rows.value = await api(`/api/parts?keyword=${encodeURIComponent(keyword.value)}`) }
  catch (error: any) { ElMessage.error(error.message) }
  finally { loading.value = false }
}
function openCreate() {
  editingId.value = null
  Object.assign(form, emptyForm())
  drawer.value = true
}
function openEdit(row: any) {
  editingId.value = row.id
  Object.assign(form, { sku: row.sku, name: row.name, unit: row.unit, spec: row.spec, cost_price: row.cost_price, min_stock: row.min_stock })
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
  <div>
    <div class="page-toolbar">
      <div class="toolbar-group">
        <el-input v-model="keyword" clearable placeholder="搜索编码或名称" style="width:260px" @keyup.enter="load" @clear="load"><template #prefix><el-icon><Search /></el-icon></template></el-input>
        <el-button @click="load">查询</el-button>
      </div>
      <el-button type="primary" @click="openCreate"><el-icon><Plus /></el-icon>新建零件</el-button>
    </div>
    <div class="content-card">
      <div class="card-head"><h3>零件档案</h3><span>共 {{ rows.length }} 项</span></div>
      <el-table v-loading="loading" :data="rows">
        <el-table-column label="零件" min-width="190"><template #default="{ row }"><div class="sku-cell"><strong>{{ row.name }}</strong><span class="mono">{{ row.sku }}</span></div></template></el-table-column>
        <el-table-column prop="spec" label="规格" min-width="150"><template #default="{ row }">{{ row.spec || '-' }}</template></el-table-column>
        <el-table-column label="单位" width="70" prop="unit" />
        <el-table-column label="成本价" width="110" align="right"><template #default="{ row }">{{ money(row.cost_price) }}</template></el-table-column>
        <el-table-column label="当前库存" width="115" align="right"><template #default="{ row }"><b :class="row.low_stock ? 'number-negative' : ''">{{ qty(row.stock_qty) }}</b> {{ row.unit }}</template></el-table-column>
        <el-table-column label="安全库存" width="100" align="right"><template #default="{ row }">{{ qty(row.min_stock) }}</template></el-table-column>
        <el-table-column label="状态" width="85"><template #default="{ row }"><el-tag :type="row.low_stock ? 'danger' : 'success'" effect="light" size="small">{{ row.low_stock ? '需补货' : '正常' }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="130" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openEdit(row)">编辑</el-button><el-button link type="danger" @click="remove(row)">停用</el-button></template></el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="drawer" :title="editingId ? '编辑零件' : '新建零件'" size="min(520px, 92vw)">
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <div class="form-grid">
          <el-form-item label="零件编码" prop="sku"><el-input v-model="form.sku" placeholder="例如 P-MOTOR-001" /></el-form-item>
          <el-form-item label="零件名称" prop="name"><el-input v-model="form.name" placeholder="请输入名称" /></el-form-item>
          <el-form-item label="规格型号"><el-input v-model="form.spec" placeholder="尺寸、型号等" /></el-form-item>
          <el-form-item label="计量单位"><el-input v-model="form.unit" placeholder="件 / 个 / 米" /></el-form-item>
          <el-form-item label="参考成本"><el-input-number v-model="form.cost_price" :min="0" :precision="2" :controls="false" style="width:100%" /></el-form-item>
          <el-form-item label="安全库存"><el-input-number v-model="form.min_stock" :min="0" :precision="2" :controls="false" style="width:100%" /></el-form-item>
        </div>
        <div class="drawer-footer"><el-button @click="drawer=false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存零件</el-button></div>
      </el-form>
    </el-drawer>
  </div>
</template>
