<script setup lang="ts">
import { ElMessage } from "element-plus"
import { computed, onMounted, ref, watch } from "vue"
import { useRoute } from "vue-router"
import { api, formatTime, money, productQty, qty, txLabels, useLiveRefresh } from "./api"

const route = useRoute()
const loading = ref(false)
const rows = ref<any[]>([])
const detail = ref<any>(null)
const drawer = ref(false)
const direction = computed(() => String(route.meta.documentDirection || "inbound").toLowerCase())
const title = computed(() => direction.value === "inbound" ? "入库单" : "出库单")
async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    rows.value = await api(`/api/documents/${direction.value}`)
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    if (!silent) loading.value = false
  }
}
function open(row: any) {
  detail.value = row; drawer.value = true
}
function printDocument() {
  window.print()
}
onMounted(load)
watch(direction, () => load())
useLiveRefresh(() => load(true))
</script>

<template>
  <div class="erp-page document-page">
    <div class="page-toolbar">
      <div class="toolbar-group">
        <el-button :loading="loading" @click="load()">
          <el-icon><Refresh /></el-icon>刷新
        </el-button>
      </div><router-link to="/operations/stock-operations">
        <el-button type="primary">
          {{ direction === 'inbound' ? '开入库单' : '办理出库' }}
        </el-button>
      </router-link>
    </div>
    <section class="content-card">
      <div class="card-head">
        <h3>{{ title }}</h3><span>单据内容使用发生时快照，后续主数据修改不会改变历史</span>
      </div><el-table v-loading="loading" :data="rows" empty-text="暂无单据">
        <el-table-column prop="transaction_no" label="单号" min-width="190">
          <template #default="{ row }">
            <span class="mono">{{ row.transaction_no }}</span>
          </template>
        </el-table-column><el-table-column label="业务类型" width="120">
          <template #default="{ row }">
            {{ txLabels[row.transaction_type] || row.transaction_type }}
          </template>
        </el-table-column>
        <el-table-column prop="related_order_no" label="关联订单" min-width="160" />
        <el-table-column
          prop="related_production_run_no"
          label="生产批次"
          min-width="160"
        />
        <el-table-column label="发生时间" width="175">
          <template #default="{ row }">
            {{ formatTime(row.occurred_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button link type="primary" @click="open(row)">
              查看
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>
    <el-drawer
      v-model="drawer"
      class="document-drawer"
      :title="`${title} · ${detail?.transaction_no || ''}`"
      size="min(820px, 98vw)"
    >
      <div v-if="detail" class="print-sheet">
        <h1>{{ direction === 'inbound' ? '入 库 单' : '出 库 单' }}</h1><el-descriptions :column="2" border>
          <el-descriptions-item label="单号">
            {{ detail.transaction_no }}
          </el-descriptions-item><el-descriptions-item label="日期">
            {{ formatTime(detail.occurred_at) }}
          </el-descriptions-item><el-descriptions-item label="订单号">
            {{ detail.related_order_no || '-' }}
          </el-descriptions-item><el-descriptions-item label="生产批次">
            {{ detail.related_production_run_no || '-' }}
          </el-descriptions-item><el-descriptions-item label="客户" :span="2">
            {{ detail.counterparty_name || '-' }}
          </el-descriptions-item><el-descriptions-item label="电话">
            {{ detail.counterparty_phone || '-' }}
          </el-descriptions-item><el-descriptions-item label="地址">
            {{ detail.counterparty_address || '-' }}
          </el-descriptions-item>
        </el-descriptions>
        <el-table :data="detail.lines" border style="margin-top:18px">
          <el-table-column prop="sku" label="编码" width="130" />
          <el-table-column prop="name" label="物料" min-width="150" />
          <el-table-column prop="spec" label="规格" min-width="120" />
          <el-table-column label="数量" width="110" align="right">
            <template #default="{ row }">
              {{
                row.kind === 'PRODUCT'
                  ? productQty(Math.abs(row.quantity_change))
                  : qty(Math.abs(row.quantity_change))
              }}
            </template>
          </el-table-column>
          <el-table-column prop="unit" label="单位" width="70" />
          <el-table-column label="单价" width="110" align="right">
            <template #default="{ row }">
              {{ row.unit_price == null ? '-' : money(row.unit_price) }}
            </template>
          </el-table-column>
        </el-table><p class="document-notes">
          备注：{{ detail.notes || '-' }}
        </p>
      </div><template #footer>
        <el-button @click="drawer = false">
          关闭
        </el-button><el-button type="primary" @click="printDocument">
          打印 A4
        </el-button>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.print-sheet h1 {
  margin: 0 0 22px;
  text-align: center;
  font-size: 24px;
  letter-spacing: 8px;
}
.document-notes {
  margin-top: 18px;
  color: var(--el-text-color-regular);
}
@media print {
  :global(body *) {
    visibility: hidden !important;
  }
  .print-sheet,
  .print-sheet * {
    visibility: visible !important;
  }
  .print-sheet {
    position: fixed;
    inset: 0;
    width: 210mm;
    min-height: 297mm;
    padding: 15mm;
    color: #000;
    background: #fff;
  }
}
</style>
