<script setup lang="ts">
import { ElMessage, ElMessageBox } from "element-plus"
import { computed, onMounted, reactive, ref } from "vue"
import { useRouter } from "vue-router"
import { api, productQty, useLiveRefresh } from "./api"

const router = useRouter()
const loading = ref(false)
const saving = ref(false)
const products = ref<any[]>([])
const capabilities = ref<any[]>([])
const capabilityDrawer = ref(false)
const editingCapabilityId = ref<number | null>(null)
const capabilityForm = reactive({
  product_id: undefined as number | undefined,
  nominal_daily_capacity: 1,
  safety_factor: 0.85,
  active: true
})
const effectiveCapacity = computed(() =>
  Number(capabilityForm.nominal_daily_capacity || 0)
  * Number(capabilityForm.safety_factor || 0)
)

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    [products.value, capabilities.value] = await Promise.all([
      api("/api/products"),
      api("/api/production/capabilities")
    ])
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    if (!silent) loading.value = false
  }
}

function openCapability(row?: any) {
  editingCapabilityId.value = row?.id || null
  Object.assign(capabilityForm, row
    ? {
        product_id: row.product_id,
        nominal_daily_capacity: row.nominal_daily_capacity,
        safety_factor: row.safety_factor,
        active: row.active
      }
    : {
        product_id: undefined,
        nominal_daily_capacity: 1,
        safety_factor: 0.85,
        active: true
      })
  capabilityDrawer.value = true
}

async function saveCapability() {
  if (!capabilityForm.product_id) return ElMessage.warning("请选择产品")
  saving.value = true
  try {
    await api(
      `/api/production/capabilities${editingCapabilityId.value
        ? `/${editingCapabilityId.value}`
        : ""}`,
      {
        method: editingCapabilityId.value ? "PUT" : "POST",
        body: JSON.stringify(capabilityForm)
      }
    )
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
    await ElMessageBox.confirm(
      `确定停用“${row.product_name}”的生产能力吗？`,
      "停用生产能力",
      { type: "warning" }
    )
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
        <el-alert
          title="每个产品只需维护单日单机产量；模具数在产品目录维护，产线总数在系统管理中统一设置。"
          type="info"
          :closable="false"
          show-icon
        />
      </div>
      <div class="toolbar-right">
        <el-button @click="router.push('/system/production')">生产设置</el-button>
        <el-button :loading="loading" @click="() => load()">
          <el-icon><Refresh /></el-icon>刷新
        </el-button>
        <el-button type="primary" @click="openCapability()">
          <el-icon><Plus /></el-icon>新增生产能力
        </el-button>
      </div>
    </div>
    <div class="content-card">
      <div class="card-head">
        <h3>生产能力</h3>
        <span>按产品维护单日单机产量，排产时自动计算时间块长度</span>
      </div>
      <el-table
        v-loading="loading"
        :data="capabilities"
        empty-text="暂无生产能力配置"
      >
        <el-table-column label="产品" min-width="240">
          <template #default="{ row }">
            <div class="sku-cell">
              <strong>{{ row.product_name }}</strong>
              <span class="mono">
                {{ row.product_sku }} · {{ row.mold_count }} 套模具
              </span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="单日单机产量" width="145" align="right">
          <template #default="{ row }">
            {{ productQty(row.nominal_daily_capacity) }}
          </template>
        </el-table-column>
        <el-table-column label="安全系数" width="105" align="right">
          <template #default="{ row }">
            {{ Math.round(row.safety_factor * 100) }}%
          </template>
        </el-table-column>
        <el-table-column label="单机有效日产" width="145" align="right">
          <template #default="{ row }">
            <b>{{ productQty(row.effective_daily_capacity) }}</b>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.active ? 'success' : 'info'" size="small">
              {{ row.active ? "启用" : "停用" }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openCapability(row)">编辑</el-button>
            <el-button
              v-if="row.active"
              link
              type="danger"
              @click="disableCapability(row)"
            >
              停用
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-drawer
      v-model="capabilityDrawer"
      :title="editingCapabilityId ? '编辑生产能力' : '新增生产能力'"
      size="min(560px, 94vw)"
    >
      <el-form label-position="top">
        <el-form-item label="产品" required>
          <el-select
            v-model="capabilityForm.product_id"
            filterable
            :disabled="Boolean(editingCapabilityId)"
            style="width: 100%"
          >
            <el-option
              v-for="row in products"
              :key="row.id"
              :label="`${row.sku} · ${row.name}（${row.mold_count || 1} 套模具）`"
              :value="row.id"
            />
          </el-select>
        </el-form-item>
        <div class="form-grid">
          <el-form-item label="单日单机产量" required>
            <el-input-number
              v-model="capabilityForm.nominal_daily_capacity"
              :min="1"
              :precision="0"
              :controls="false"
              style="width: 100%"
            />
          </el-form-item>
          <el-form-item label="安全系数">
            <el-input-number
              v-model="capabilityForm.safety_factor"
              :min="0.01"
              :max="1"
              :step="0.05"
              :precision="2"
              style="width: 100%"
            />
          </el-form-item>
        </div>
        <el-alert
          :title="`计入安全系数后，单机有效日产 ${productQty(effectiveCapacity)} 件`"
          type="success"
          :closable="false"
          show-icon
        />
        <el-form-item label="状态" style="margin-top: 18px">
          <el-switch v-model="capabilityForm.active" active-text="启用" />
        </el-form-item>
        <div class="drawer-footer">
          <el-button @click="capabilityDrawer = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="saveCapability">
            保存并重算 ETA
          </el-button>
        </div>
      </el-form>
    </el-drawer>
  </div>
</template>

<style scoped>
.page-toolbar .el-alert {
  min-width: min(640px, 60vw);
}
</style>
