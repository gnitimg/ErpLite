<script setup lang="ts">
import { ElMessage } from "element-plus"
import { onMounted, ref } from "vue"
import { api, qty, useLiveRefresh } from "./api"

const loading = ref(false)
const rows = ref<any[]>([])
async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    rows.value = await api("/api/purchase/requirements")
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
      </div><router-link to="/operations/stock-operations">
        <el-button type="primary">
          办理采购入库
        </el-button>
      </router-link>
    </div>
    <section class="content-card">
      <div class="card-head">
        <h3>待购买零件</h3>
      </div>
      <el-table v-loading="loading" :data="rows" empty-text="当前没有零件采购缺口">
        <el-table-column label="零件" min-width="220">
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
        <el-table-column label="总需求" width="125" align="right">
          <template #default="{ row }">
            {{ qty(row.total_required) }} {{ row.unit }}
          </template>
        </el-table-column>
        <el-table-column label="待购买" width="130" align="right">
          <template #default="{ row }">
            <b class="number-negative">{{ qty(row.shortage_quantity) }} {{ row.unit }}</b>
          </template>
        </el-table-column>
        <el-table-column label="供应模式" width="120">
          <template #default="{ row }">
            <el-tag size="small" :type="row.supply_mode === 'BUY_TO_ORDER' ? 'warning' : 'info'">
              {{ row.supply_mode === 'BUY_TO_ORDER' ? '按单即买' : '库存备料' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="involved_products" label="涉及产品" min-width="240" />
      </el-table>
    </section>
  </div>
</template>
