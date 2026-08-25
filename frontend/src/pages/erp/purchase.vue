<script setup lang="ts">
import { ElMessage } from "element-plus"
import { computed, onMounted, ref } from "vue"
import { api, qty, useLiveRefresh } from "./api"

const loading = ref(false)
const rows = ref<any[]>([])
const commitments = ref<any[]>([])
const viewRows = computed(() => rows.value.map((row: any) => {
  const planned = commitments.value.filter((item: any) => item.part_id === row.part_id)
  return {
    ...row,
    committed_quantity: planned.reduce((total: number, item: any) => total + Number(item.quantity || 0), 0),
    expected_arrival_at: planned
      .map((item: any) => item.expected_arrival_at)
      .filter(Boolean)
      .sort()[0] || null
  }
}))
async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    const [requirements, plannedCommitments] = await Promise.all([
      api("/api/purchase/requirements"),
      api("/api/purchase/commitments?status=PLANNED")
    ])
    rows.value = requirements
    commitments.value = plannedCommitments
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    if (!silent) loading.value = false
  }
}
onMounted(load)
useLiveRefresh(() => load(true))
</script>

<template>
  <div class="erp-page">
    <div class="page-toolbar">
      <div class="toolbar-group">
        <el-button :loading="loading" @click="load()">
          <el-icon><Refresh /></el-icon>刷新
        </el-button>
      </div><router-link to="/lite-purchase/arrivals">
        <el-button type="primary">
          登记采购与到货
        </el-button>
      </router-link>
    </div>
    <section class="content-card">
      <div class="card-head">
        <h3>采购缺口与预计到货</h3><span>只按生产缺口计算原料需求，采购承诺会进入 ETA 时间线</span>
      </div>
      <el-table v-loading="loading" :data="viewRows" empty-text="当前没有原料采购缺口">
        <el-table-column label="原料" min-width="220">
          <template #default="{ row }">
            <div class="sku-cell">
              <strong>{{ row.name }}</strong><span>{{ row.sku }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="当前库存" width="125" align="right">
          <template #default="{ row }">
            {{ qty(row.current_stock) }} {{ row.unit }}
          </template>
        </el-table-column>
        <el-table-column label="生产需求" width="125" align="right">
          <template #default="{ row }">
            {{ qty(row.total_required) }} {{ row.unit }}
          </template>
        </el-table-column>
        <el-table-column label="采购缺口" width="130" align="right">
          <template #default="{ row }">
            <b class="number-negative">{{ qty(row.shortage_quantity) }} {{ row.unit }}</b>
          </template>
        </el-table-column>
        <el-table-column label="已登记采购" width="130" align="right">
          <template #default="{ row }">
            {{ qty(row.committed_quantity) }} {{ row.unit }}
          </template>
        </el-table-column>
        <el-table-column label="最近预计到货" width="140">
          <template #default="{ row }">
            <span :class="row.expected_arrival_at ? '' : 'number-negative'">
              {{ row.expected_arrival_at?.slice(0, 10) || '尚未登记' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="involved_products" label="用于生产" min-width="220" />
      </el-table>
    </section>
  </div>
</template>
