<script setup lang="ts">
import type { FormInstance, FormRules } from "element-plus"
import { ElMessage, ElMessageBox } from "element-plus"
import { onMounted, reactive, ref } from "vue"
import { api, productQty } from "./api"
import ListToolbar from "./components/ListToolbar.vue"
import QuantityInput from "./components/QuantityInput.vue"

const loading = ref(false)
const saving = ref(false)
const drawer = ref(false)
const keyword = ref("")
const rows = ref<any[]>([])
const formRef = ref<FormInstance>()
const editingId = ref<number | null>(null)
const emptyForm = () => ({ sku: "", name: "", spec: "", unit: "件", stock_qty: 300 })
const form = reactive(emptyForm())
const rules: FormRules = {
  sku: [{ required: true, message: "请输入样品编码", trigger: "blur" }],
  name: [{ required: true, message: "请输入样品名称", trigger: "blur" }]
}

async function load() {
  loading.value = true
  const params = new URLSearchParams()
  if (keyword.value.trim()) params.set("keyword", keyword.value.trim())
  try {
    rows.value = await api(`/api/samples?${params}`)
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  Object.assign(form, emptyForm())
  drawer.value = true
}

function openEdit(row: any) {
  editingId.value = row.id
  Object.assign(form, {
    sku: row.sku,
    name: row.name,
    spec: row.spec,
    unit: row.unit,
    stock_qty: Math.max(Math.round(Number(row.stock_qty) || 0), 0)
  })
  drawer.value = true
}

async function save() {
  if (!await formRef.value?.validate().catch(() => false)) return
  saving.value = true
  try {
    const path = editingId.value ? `/api/samples/${editingId.value}` : "/api/samples"
    await api(path, {
      method: editingId.value ? "PUT" : "POST",
      body: JSON.stringify(form)
    })
    ElMessage.success(editingId.value ? "样品已更新" : "样品已创建，默认库存已登记")
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
    await ElMessageBox.confirm(`确定停用“${row.name}”吗？`, "停用样品", { type: "warning" })
    await api(`/api/samples/${row.id}`, { method: "DELETE" })
    ElMessage.success("样品已停用")
    await load()
  } catch (error: any) {
    if (error !== "cancel") ElMessage.error(error.message)
  }
}

onMounted(load)
</script>

<template>
  <div class="erp-page">
    <ListToolbar
      v-model="keyword"
      placeholder="搜索样品编码、名称或规格"
      :loading="loading"
      :show-filter="false"
      @search="load"
      @refresh="load"
    >
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>新建样品
      </el-button>
    </ListToolbar>

    <div class="content-card">
      <div class="card-head">
        <div>
          <h3>样品库存</h3>
          <span>新建时默认 300 件，可按实际结存直接调整</span>
        </div>
        <span>共 {{ rows.length }} 项</span>
      </div>
      <el-table v-loading="loading" :data="rows">
        <el-table-column label="样品" min-width="210">
          <template #default="{ row }">
            <div class="sku-cell">
              <strong>{{ row.name }}</strong><span class="mono">{{ row.sku }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="规格" prop="spec" min-width="180">
          <template #default="{ row }">
            {{ row.spec || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="单位" prop="unit" width="90" />
        <el-table-column label="当前库存" width="170" align="right">
          <template #default="{ row }">
            <strong>{{ productQty(row.stock_qty) }}</strong> {{ row.unit }}
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
      v-model="drawer"
      :title="editingId ? '编辑样品与库存' : '新建样品'"
      size="min(520px, 92vw)"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <div class="form-grid">
          <el-form-item label="样品编码" prop="sku">
            <el-input v-model="form.sku" placeholder="例如 SAMPLE-001" />
          </el-form-item>
          <el-form-item label="样品名称" prop="name">
            <el-input v-model="form.name" placeholder="请输入名称" />
          </el-form-item>
          <el-form-item label="规格型号">
            <el-input v-model="form.spec" placeholder="颜色、尺寸或版本等" />
          </el-form-item>
          <el-form-item label="计量单位">
            <el-input v-model="form.unit" placeholder="件" />
          </el-form-item>
          <el-form-item class="span-2" label="样品库存">
            <QuantityInput v-model="form.stock_qty" integer :min="0" />
            <div class="form-help">
              新建样品默认 300 件；修改数量会自动生成“样品调整”库存流水，原始记录不会被覆盖。
            </div>
          </el-form-item>
        </div>
        <div class="drawer-footer">
          <el-button @click="drawer = false">
            取消
          </el-button>
          <el-button type="primary" :loading="saving" @click="save">
            保存样品
          </el-button>
        </div>
      </el-form>
    </el-drawer>
  </div>
</template>
