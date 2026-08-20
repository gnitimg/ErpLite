<script setup lang="ts">
import { ElMessage, ElMessageBox } from "element-plus"
import { computed, onMounted, reactive, ref } from "vue"
import { api, productQty, useLiveRefresh } from "./api"

const loading = ref(false)
const saving = ref(false)
const activeTab = ref("capabilities")
const lines = ref<any[]>([])
const molds = ref<any[]>([])
const products = ref<any[]>([])
const capabilities = ref<any[]>([])
const resourceDrawer = ref(false)
const capabilityDrawer = ref(false)
const resourceKind = ref<"line" | "mold">("line")
const editingResourceId = ref<number | null>(null)
const editingCapabilityId = ref<number | null>(null)
const resourceForm = reactive({ code: "", name: "", active: true })
const capabilityForm = reactive({
  product_id: undefined as number | undefined,
  line_id: undefined as number | undefined,
  mold_id: undefined as number | undefined,
  nominal_daily_capacity: 1,
  safety_factor: 0.85,
  active: true
})
const effectiveCapacity = computed(() =>
  Number(capabilityForm.nominal_daily_capacity || 0) * Number(capabilityForm.safety_factor || 0)
)

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    [lines.value, molds.value, products.value, capabilities.value] = await Promise.all([
      api("/api/production/lines"),
      api("/api/production/molds"),
      api("/api/products"),
      api("/api/production/capabilities")
    ])
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    if (!silent) loading.value = false
  }
}

function openResource(kind: "line" | "mold", row?: any) {
  resourceKind.value = kind
  editingResourceId.value = row?.id || null
  Object.assign(resourceForm, row
    ? { code: row.code, name: row.name, active: row.active }
    : { code: "", name: "", active: true })
  resourceDrawer.value = true
}

async function saveResource() {
  if (!resourceForm.code.trim() || !resourceForm.name.trim()) return ElMessage.warning("请填写编码和名称")
  const path = resourceKind.value === "line" ? "lines" : "molds"
  saving.value = true
  try {
    await api(`/api/production/${path}${editingResourceId.value ? `/${editingResourceId.value}` : ""}`, {
      method: editingResourceId.value ? "PUT" : "POST",
      body: JSON.stringify(resourceForm)
    })
    resourceDrawer.value = false
    ElMessage.success("生产资源已保存")
    await load()
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    saving.value = false
  }
}

function openCapability(row?: any) {
  editingCapabilityId.value = row?.id || null
  Object.assign(capabilityForm, row
    ? {
        product_id: row.product_id,
        line_id: row.line_id,
        mold_id: row.mold_id,
        nominal_daily_capacity: row.nominal_daily_capacity,
        safety_factor: row.safety_factor,
        active: row.active
      }
    : {
        product_id: undefined,
        line_id: undefined,
        mold_id: undefined,
        nominal_daily_capacity: 1,
        safety_factor: 0.85,
        active: true
      })
  capabilityDrawer.value = true
}

async function saveCapability() {
  if (!capabilityForm.product_id || !capabilityForm.line_id || !capabilityForm.mold_id) {
    return ElMessage.warning("请选择产品、生产线和模具")
  }
  saving.value = true
  try {
    await api(`/api/production/capabilities${editingCapabilityId.value ? `/${editingCapabilityId.value}` : ""}`, {
      method: editingCapabilityId.value ? "PUT" : "POST",
      body: JSON.stringify(capabilityForm)
    })
    capabilityDrawer.value = false
    ElMessage.success("生产能力已保存，客单 ETA 已重新计算")
    await load()
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    saving.value = false
  }
}

async function disableCapability(row: any) {
  try {
    await ElMessageBox.confirm(`确定停用“${row.product_name} / ${row.line_code} / ${row.mold_code}”吗？`, "停用生产能力", { type: "warning" })
    await api(`/api/production/capabilities/${row.id}`, { method: "DELETE" })
    ElMessage.success("生产能力已停用，客单 ETA 已重新计算")
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
    <div class="page-toolbar">
      <div class="toolbar-group">
        <el-alert title="日产能力按“产品 × 生产线 × 模具”维护，不再写在产品目录中。" type="info" :closable="false" show-icon />
      </div>
      <div class="toolbar-right">
        <el-button :loading="loading" @click="() => load()"><el-icon><Refresh /></el-icon>刷新</el-button>
        <el-button type="primary" @click="openCapability()"><el-icon><Plus /></el-icon>新增生产能力</el-button>
      </div>
    </div>
    <div class="content-card">
      <div class="card-head">
        <h3>生产资源</h3><span>维护 ETA 模拟所需的物理资源与有效日产能力</span>
      </div>
      <el-tabs v-model="activeTab">
        <el-tab-pane name="capabilities" label="生产能力">
          <el-table v-loading="loading" :data="capabilities" empty-text="暂无生产能力配置">
            <el-table-column label="产品" min-width="190">
              <template #default="{ row }"><div class="sku-cell"><strong>{{ row.product_name }}</strong><span class="mono">{{ row.product_sku }}</span></div></template>
            </el-table-column>
            <el-table-column label="生产线" min-width="150"><template #default="{ row }">{{ row.line_code }} · {{ row.line_name }}</template></el-table-column>
            <el-table-column label="模具" min-width="150"><template #default="{ row }">{{ row.mold_code }} · {{ row.mold_name }}</template></el-table-column>
            <el-table-column label="标称日产" width="120" align="right"><template #default="{ row }">{{ productQty(row.nominal_daily_capacity) }}</template></el-table-column>
            <el-table-column label="安全系数" width="105" align="right"><template #default="{ row }">{{ Math.round(row.safety_factor * 100) }}%</template></el-table-column>
            <el-table-column label="有效日产" width="120" align="right"><template #default="{ row }"><b>{{ productQty(row.effective_daily_capacity) }}</b></template></el-table-column>
            <el-table-column label="状态" width="80"><template #default="{ row }"><el-tag :type="row.active ? 'success' : 'info'" size="small">{{ row.active ? '启用' : '停用' }}</el-tag></template></el-table-column>
            <el-table-column label="操作" width="120" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openCapability(row)">编辑</el-button><el-button v-if="row.active" link type="danger" @click="disableCapability(row)">停用</el-button></template></el-table-column>
          </el-table>
        </el-tab-pane>
        <el-tab-pane name="lines" label="生产线">
          <div class="tab-actions"><el-button type="primary" @click="openResource('line')"><el-icon><Plus /></el-icon>新增生产线</el-button></div>
          <el-table :data="lines"><el-table-column prop="code" label="编码" width="160" /><el-table-column prop="name" label="名称" min-width="220" /><el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="row.active ? 'success' : 'info'" size="small">{{ row.active ? '启用' : '停用' }}</el-tag></template></el-table-column><el-table-column label="操作" width="90"><template #default="{ row }"><el-button link type="primary" @click="openResource('line', row)">编辑</el-button></template></el-table-column></el-table>
        </el-tab-pane>
        <el-tab-pane name="molds" label="模具">
          <div class="tab-actions"><el-button type="primary" @click="openResource('mold')"><el-icon><Plus /></el-icon>新增模具</el-button></div>
          <el-table :data="molds"><el-table-column prop="code" label="编码" width="160" /><el-table-column prop="name" label="名称" min-width="220" /><el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="row.active ? 'success' : 'info'" size="small">{{ row.active ? '启用' : '停用' }}</el-tag></template></el-table-column><el-table-column label="操作" width="90"><template #default="{ row }"><el-button link type="primary" @click="openResource('mold', row)">编辑</el-button></template></el-table-column></el-table>
        </el-tab-pane>
      </el-tabs>
    </div>

    <el-drawer v-model="resourceDrawer" :title="`${editingResourceId ? '编辑' : '新增'}${resourceKind === 'line' ? '生产线' : '模具'}`" size="min(460px, 94vw)">
      <el-form label-position="top"><el-form-item label="编码" required><el-input v-model="resourceForm.code" /></el-form-item><el-form-item label="名称" required><el-input v-model="resourceForm.name" /></el-form-item><el-form-item label="状态"><el-switch v-model="resourceForm.active" active-text="启用" /></el-form-item><div class="drawer-footer"><el-button @click="resourceDrawer = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveResource">保存</el-button></div></el-form>
    </el-drawer>
    <el-drawer v-model="capabilityDrawer" :title="editingCapabilityId ? '编辑生产能力' : '新增生产能力'" size="min(560px, 94vw)">
      <el-form label-position="top">
        <el-form-item label="产品" required><el-select v-model="capabilityForm.product_id" filterable style="width:100%"><el-option v-for="row in products" :key="row.id" :label="`${row.sku} · ${row.name}`" :value="row.id" /></el-select></el-form-item>
        <div class="form-grid"><el-form-item label="生产线" required><el-select v-model="capabilityForm.line_id" filterable style="width:100%"><el-option v-for="row in lines.filter(x => x.active)" :key="row.id" :label="`${row.code} · ${row.name}`" :value="row.id" /></el-select></el-form-item><el-form-item label="模具" required><el-select v-model="capabilityForm.mold_id" filterable style="width:100%"><el-option v-for="row in molds.filter(x => x.active)" :key="row.id" :label="`${row.code} · ${row.name}`" :value="row.id" /></el-select></el-form-item><el-form-item label="标称日产量" required><el-input-number v-model="capabilityForm.nominal_daily_capacity" :min="1" :precision="0" :controls="false" style="width:100%" /></el-form-item><el-form-item label="安全系数"><el-input-number v-model="capabilityForm.safety_factor" :min="0.01" :max="1" :step="0.05" :precision="2" style="width:100%" /></el-form-item></div>
        <el-alert :title="`ETA 按有效日产 ${productQty(effectiveCapacity)} 件计算`" type="success" :closable="false" show-icon />
        <el-form-item label="状态" style="margin-top:18px"><el-switch v-model="capabilityForm.active" active-text="启用" /></el-form-item>
        <div class="drawer-footer"><el-button @click="capabilityDrawer = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveCapability">保存并重算 ETA</el-button></div>
      </el-form>
    </el-drawer>
  </div>
</template>

<style scoped>
.page-toolbar .el-alert { min-width: min(560px, 60vw); }
.tab-actions { padding: 0 0 14px; display: flex; justify-content: flex-end; }
</style>
