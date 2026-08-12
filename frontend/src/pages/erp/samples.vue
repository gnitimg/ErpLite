<script setup lang="ts">
import { ElMessage } from "element-plus"
import { onMounted, reactive, ref } from "vue"
import { api, productQty, useLiveRefresh } from "./api"
import ListToolbar from "./components/ListToolbar.vue"
import QuantityInput from "./components/QuantityInput.vue"

const loading = ref(false)
const saving = ref(false)
const drawer = ref(false)
const keyword = ref("")
const rows = ref<any[]>([])
const editingId = ref<number>()
const selectedProduct = ref<any>()
const form = reactive({ stock_qty: 0 })

async function load(silent = false) {
  if (!silent) loading.value = true
  const params = new URLSearchParams()
  if (keyword.value.trim()) params.set("keyword", keyword.value.trim())
  try {
    rows.value = await api(`/api/samples?${params}`)
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    if (!silent) loading.value = false
  }
}

function openEdit(row: any) {
  editingId.value = row.id
  selectedProduct.value = row
  form.stock_qty = Math.max(
    Math.round(Number(row.sample_stock_qty) || 0),
    0
  )
  drawer.value = true
}

async function save() {
  if (!editingId.value) return
  saving.value = true
  try {
    await api(`/api/samples/${editingId.value}`, {
      method: "PUT",
      body: JSON.stringify({ stock_qty: form.stock_qty })
    })
    ElMessage.success("样品库存已更新")
    drawer.value = false
    await load()
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    saving.value = false
  }
}

onMounted(load)
useLiveRefresh(() => load(true))
</script>

<template>
  <div class="erp-page">
    <ListToolbar
      v-model="keyword"
      placeholder="搜索产品编码、名称或规格"
      :loading="loading"
      :show-filter="false"
      @search="load"
      @refresh="load"
    />

    <div class="content-card">
      <div class="card-head">
        <div>
          <h3>样品库存</h3>
          <span>跟随产品目录自动生成；新产品默认 300，无样品时仍显示为 0</span>
        </div>
        <span>共 {{ rows.length }} 项</span>
      </div>
      <el-table v-loading="loading" :data="rows">
        <el-table-column label="产品" min-width="210">
          <template #default="{ row }">
            <div class="sku-cell">
              <strong>{{ row.name }}</strong>
              <span class="mono">{{ row.sku }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="规格" prop="spec" min-width="180">
          <template #default="{ row }">
            {{ row.spec || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="单位" prop="unit" width="90" />
        <el-table-column label="样品结存" width="170" align="right">
          <template #default="{ row }">
            <strong
              :class="{ 'number-negative': Number(row.sample_stock_qty) === 0 }"
            >
              {{ productQty(row.sample_stock_qty) }}
            </strong>
            {{ row.unit }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">
              调整库存
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-drawer
      v-model="drawer"
      title="调整样品库存"
      size="min(520px, 92vw)"
    >
      <el-form :model="form" label-position="top">
        <el-descriptions
          v-if="selectedProduct"
          :column="1"
          border
          class="drawer-summary"
        >
          <el-descriptions-item label="产品">
            {{ selectedProduct.name }}
          </el-descriptions-item>
          <el-descriptions-item label="产品编码">
            {{ selectedProduct.sku }}
          </el-descriptions-item>
          <el-descriptions-item label="规格">
            {{ selectedProduct.spec || '-' }}
          </el-descriptions-item>
        </el-descriptions>
        <el-form-item label="样品结存" style="margin-top: 18px">
          <QuantityInput
            v-model="form.stock_qty"
            integer
            :min="0"
            :unit="selectedProduct?.unit"
          />
          <div class="form-help">
            数量为 0 时仍会保留在列表中并以红色提示；修改不会影响产品库存。
          </div>
        </el-form-item>
        <div class="drawer-footer">
          <el-button @click="drawer = false">
            取消
          </el-button>
          <el-button type="primary" :loading="saving" @click="save">
            保存库存
          </el-button>
        </div>
      </el-form>
    </el-drawer>
  </div>
</template>
