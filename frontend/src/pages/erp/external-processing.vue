<script setup lang="ts">
import { ElMessage } from "element-plus"
import { computed, onMounted, reactive, ref } from "vue"
import { api, formatDate, productQty, useLiveRefresh } from "./api"
import QuantityInput from "./components/QuantityInput.vue"

const loading = ref(false)
const saving = ref(false)
const products = ref<any[]>([])
const batches = ref<any[]>([])
const sendDrawer = ref(false)
const returnDrawer = ref(false)
const activeBatch = ref<any>(null)
const today = () => new Date().toISOString().slice(0, 10)
const sendForm = reactive({ product_id: undefined as number | undefined, quantity: 1, supplier: "", occurred_date: today(), notes: "" })
const returnForm = reactive({ quantity: 1, occurred_date: today(), notes: "" })
const activeProduct = computed(() => products.value.find(row => row.id === sendForm.product_id))

const statusMeta: Record<string, { label: string, type: string }> = {
  SENT: { label: "加工中", type: "warning" },
  PARTIALLY_RETURNED: { label: "部分回厂", type: "primary" },
  RETURNED: { label: "已回厂", type: "success" }
}

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    const result = await api("/api/external-processing")
    products.value = result.products
    batches.value = result.batches
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    if (!silent) loading.value = false
  }
}

function openSend(row?: any) {
  sendForm.product_id = row?.id
  sendForm.quantity = Math.max(Number(row?.semi_finished_qty || 1), 1)
  sendForm.supplier = ""
  sendForm.occurred_date = today()
  sendForm.notes = ""
  sendDrawer.value = true
}

function openReturn(row: any) {
  activeBatch.value = row
  returnForm.quantity = Number(row.remaining_quantity)
  returnForm.occurred_date = today()
  returnForm.notes = ""
  returnDrawer.value = true
}

async function submitSend() {
  if (!activeProduct.value) return ElMessage.warning("请选择产品")
  if (Number(sendForm.quantity) > Number(activeProduct.value.semi_finished_qty)) {
    return ElMessage.warning("送出数量不能超过半成品库存")
  }
  saving.value = true
  try {
    await api("/api/external-processing/send", { method: "POST", body: JSON.stringify(sendForm) })
    ElMessage.success("半成品已送出，外协出库单已生成")
    sendDrawer.value = false
    await load()
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    saving.value = false
  }
}

async function submitReturn() {
  saving.value = true
  try {
    await api(`/api/external-processing/${activeBatch.value.id}/return`, {
      method: "POST",
      body: JSON.stringify(returnForm)
    })
    ElMessage.success("外协产品已回厂并进入成品库存，客单预留已自动重算")
    returnDrawer.value = false
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
    <div class="page-toolbar">
      <div class="toolbar-group">
        <el-button :loading="loading" @click="load()">
          <el-icon><Refresh /></el-icon>刷新
        </el-button>
      </div>
      <el-button type="primary" @click="openSend()">
        外协送出
      </el-button>
    </div>

    <section class="content-card">
      <div class="card-head">
        <h3>半成品与外协在途</h3>
      </div>
      <el-table v-loading="loading" :data="products" empty-text="尚未在产品目录配置外协工序">
        <el-table-column label="产品" min-width="220">
          <template #default="{ row }">
            <div class="sku-cell"><strong>{{ row.name }}</strong><span>{{ row.sku }}</span></div>
          </template>
        </el-table-column>
        <el-table-column prop="external_process_name" label="外协工序" min-width="150" />
        <el-table-column label="半成品待送" width="130" align="right">
          <template #default="{ row }"><b>{{ productQty(row.semi_finished_qty) }} {{ row.unit }}</b></template>
        </el-table-column>
        <el-table-column label="加工在途" width="125" align="right">
          <template #default="{ row }"><b>{{ productQty(row.processing_qty) }} {{ row.unit }}</b></template>
        </el-table-column>
        <el-table-column label="成品库存" width="125" align="right">
          <template #default="{ row }">{{ productQty(row.stock_qty) }} {{ row.unit }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :disabled="!row.semi_finished_qty" @click="openSend(row)">送出</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <section class="content-card">
      <div class="card-head">
        <h3>外协批次</h3>
      </div>
      <el-table v-loading="loading" :data="batches" empty-text="暂无外协批次">
        <el-table-column prop="batch_no" label="批次号" min-width="185" />
        <el-table-column label="产品 / 工序" min-width="220">
          <template #default="{ row }">
            <div class="sku-cell"><strong>{{ row.product_name }}</strong><span>{{ row.process_name }}</span></div>
          </template>
        </el-table-column>
        <el-table-column prop="supplier" label="外协单位" min-width="150">
          <template #default="{ row }">{{ row.supplier || '-' }}</template>
        </el-table-column>
        <el-table-column label="送出 / 已回" width="150" align="right">
          <template #default="{ row }">{{ productQty(row.quantity) }} / {{ productQty(row.returned_quantity) }} {{ row.unit }}</template>
        </el-table-column>
        <el-table-column label="送出日期" width="120">
          <template #default="{ row }">{{ formatDate(row.sent_at) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="105">
          <template #default="{ row }">
            <el-tag :type="statusMeta[row.status]?.type as any" size="small">{{ statusMeta[row.status]?.label || row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.remaining_quantity" link type="success" @click="openReturn(row)">确认回厂</el-button>
            <span v-else class="muted">已完成</span>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-drawer v-model="sendDrawer" title="外协加工送出" size="min(520px, 96vw)">
      <el-form label-position="top">
        <el-form-item label="半成品" required>
          <el-select v-model="sendForm.product_id" filterable placeholder="选择待加工产品" style="width:100%">
            <el-option
              v-for="product in products"
              :key="product.id"
              :label="`${product.sku} · ${product.name}（待送 ${productQty(product.semi_finished_qty)}）`"
              :value="product.id"
              :disabled="!product.semi_finished_qty"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="加工工序"><el-input :model-value="activeProduct?.external_process_name || ''" disabled /></el-form-item>
        <el-form-item label="送出数量" required>
          <QuantityInput v-model="sendForm.quantity" integer :min="1" :max="Number(activeProduct?.semi_finished_qty || 1)" :unit="activeProduct?.unit" />
        </el-form-item>
        <el-form-item label="外协单位"><el-input v-model="sendForm.supplier" placeholder="加工商名称（可选）" /></el-form-item>
        <el-form-item label="送出日期"><el-date-picker v-model="sendForm.occurred_date" value-format="YYYY-MM-DD" style="width:100%" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="sendForm.notes" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <div class="drawer-footer"><el-button @click="sendDrawer = false">取消</el-button><el-button type="primary" :loading="saving" @click="submitSend">确认送出并生成出库单</el-button></div>
    </el-drawer>

    <el-drawer v-model="returnDrawer" title="外协加工回厂" size="min(520px, 96vw)">
      <el-descriptions v-if="activeBatch" :column="1" border>
        <el-descriptions-item label="产品">{{ activeBatch.product_sku }} · {{ activeBatch.product_name }}</el-descriptions-item>
        <el-descriptions-item label="工序">{{ activeBatch.process_name }}</el-descriptions-item>
        <el-descriptions-item label="尚未回厂">{{ productQty(activeBatch.remaining_quantity) }} {{ activeBatch.unit }}</el-descriptions-item>
      </el-descriptions>
      <el-form label-position="top" style="margin-top:20px">
        <el-form-item label="本次合格回厂数量" required>
          <QuantityInput v-model="returnForm.quantity" integer :min="1" :max="Number(activeBatch?.remaining_quantity || 1)" :unit="activeBatch?.unit" />
        </el-form-item>
        <el-form-item label="回厂日期"><el-date-picker v-model="returnForm.occurred_date" value-format="YYYY-MM-DD" style="width:100%" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="returnForm.notes" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <div class="drawer-footer"><el-button @click="returnDrawer = false">取消</el-button><el-button type="primary" :loading="saving" @click="submitReturn">确认回厂并入成品库</el-button></div>
    </el-drawer>
  </div>
</template>
