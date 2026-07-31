<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, money, qty, statusMap } from './api'

const loading = ref(false)
const saving = ref(false)
const drawer = ref(false)
const filterDrawer = ref(false)
const rows = ref<any[]>([])
const products = ref<any[]>([])
const keyword = ref('')
const filters = reactive({ status: '', dateRange: [] as string[] })
const form = reactive({ customer_name: '', customer_phone: '', customer_address: '', order_date: new Date().toISOString().slice(0, 10), notes: '', items: [] as any[] })
const total = computed(() => form.items.reduce((sum, line) => sum + Number(line.quantity || 0) * Number(line.unit_price || 0), 0))
const activeFilterCount = computed(() => Number(Boolean(filters.status)) + Number(filters.dateRange.length === 2))

async function load() {
  loading.value = true
  const params = new URLSearchParams()
  if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
  if (filters.status) params.set('status', filters.status)
  if (filters.dateRange.length === 2) {
    params.set('start_date', filters.dateRange[0])
    params.set('end_date', filters.dateRange[1])
  }
  try { [rows.value, products.value] = await Promise.all([api(`/api/orders?${params}`), api('/api/products')]) }
  catch (error: any) { ElMessage.error(error.message) }
  finally { loading.value = false }
}
function applyFilters() { filterDrawer.value = false; load() }
function resetFilters() { filters.status = ''; filters.dateRange = []; applyFilters() }
function openCreate() {
  Object.assign(form, { customer_name: '', customer_phone: '', customer_address: '', order_date: new Date().toISOString().slice(0, 10), notes: '', items: [] })
  form.items.push({ product_id: undefined, quantity: 1, unit_price: 0 })
  drawer.value = true
}
function addLine() { form.items.push({ product_id: undefined, quantity: 1, unit_price: 0 }) }
function productChanged(line: any) { const product = products.value.find(x => x.id === line.product_id); line.unit_price = product?.sale_price || 0 }
async function save() {
  if (!form.customer_name.trim()) return ElMessage.warning('请输入客户名称')
  if (!form.items.length || form.items.some(line => !line.product_id || line.quantity <= 0)) return ElMessage.warning('请完整填写产品明细')
  saving.value = true
  try {
    await api('/api/orders', { method: 'POST', body: JSON.stringify(form) })
    ElMessage.success('客单已创建'); drawer.value = false; await load()
  } catch (error: any) { ElMessage.error(error.message) }
  finally { saving.value = false }
}
async function action(row: any, type: 'confirm' | 'fulfill' | 'cancel') {
  const labels = { confirm: '确认客单', fulfill: '确认出库并扣减成品库存', cancel: '取消客单' }
  try {
    await ElMessageBox.confirm(`确定${labels[type]}“${row.order_no}”吗？`, '客单操作', { type: type === 'cancel' ? 'warning' : 'info' })
    await api(`/api/orders/${row.id}/${type}`, { method: 'POST' })
    ElMessage.success(labels[type] + '成功'); await load()
  } catch (error: any) { if (error !== 'cancel') ElMessage.error(error.message) }
}
onMounted(load)
</script>

<template>
  <div class="erp-page orders-page">
    <div class="page-toolbar">
      <div class="toolbar-group list-actions">
        <el-input v-model="keyword" clearable class="list-search" placeholder="搜索客单号、客户名称或电话" @keyup.enter="load" @clear="load"><template #prefix><el-icon><Search /></el-icon></template></el-input>
        <el-badge :value="activeFilterCount" :hidden="!activeFilterCount" class="filter-badge"><el-button @click="filterDrawer=true"><el-icon><Filter /></el-icon>筛选</el-button></el-badge>
        <el-button @click="load"><el-icon><Refresh /></el-icon>刷新</el-button>
      </div>
      <el-button type="primary" @click="openCreate"><el-icon><Plus /></el-icon>新建客单</el-button>
    </div>
    <div class="content-card">
      <div class="card-head"><h3>客户订单</h3><span>出库后自动写入库存流水</span></div>
      <el-table v-loading="loading" :data="rows" row-key="id" empty-text="暂无符合条件的客户订单">
        <el-table-column type="expand"><template #default="{ row }"><div style="padding:8px 45px 18px"><el-descriptions :column="3" size="small" border><el-descriptions-item label="联系电话">{{ row.customer_phone || '-' }}</el-descriptions-item><el-descriptions-item label="送货地址" :span="2">{{ row.customer_address || '-' }}</el-descriptions-item><el-descriptions-item label="备注" :span="3">{{ row.notes || '-' }}</el-descriptions-item></el-descriptions><el-table :data="row.items" size="small" border style="margin-top:12px"><el-table-column prop="product_sku" label="产品编码" /><el-table-column prop="product_name" label="产品名称" /><el-table-column label="数量" align="right"><template #default="{ row: line }">{{ qty(line.quantity) }}</template></el-table-column><el-table-column label="单价" align="right"><template #default="{ row: line }">{{ money(line.unit_price) }}</template></el-table-column><el-table-column label="小计" align="right"><template #default="{ row: line }">{{ money(line.line_total) }}</template></el-table-column></el-table></div></template></el-table-column>
        <el-table-column label="客单号" min-width="185"><template #default="{ row }"><span class="mono">{{ row.order_no }}</span></template></el-table-column>
        <el-table-column label="客户" min-width="170"><template #default="{ row }"><div class="sku-cell"><strong>{{ row.customer_name }}</strong><span>{{ row.customer_phone || '未留电话' }}</span></div></template></el-table-column>
        <el-table-column prop="order_date" label="订单日期" width="115" />
        <el-table-column label="产品数" width="90" align="right"><template #default="{ row }">{{ row.items.length }} 项</template></el-table-column>
        <el-table-column label="订单金额" width="125" align="right"><template #default="{ row }"><strong>{{ money(row.total_amount) }}</strong></template></el-table-column>
        <el-table-column label="状态" width="90"><template #default="{ row }"><el-tag :type="statusMap[row.status]?.type as any" size="small">{{ statusMap[row.status]?.label || row.status }}</el-tag></template></el-table-column>
        <el-table-column label="操作" min-width="205" fixed="right"><template #default="{ row }"><el-button v-if="row.status === 'DRAFT'" link type="primary" @click="action(row,'confirm')">确认</el-button><el-button v-if="['DRAFT','CONFIRMED'].includes(row.status)" link type="success" @click="action(row,'fulfill')">出库</el-button><el-button v-if="['DRAFT','CONFIRMED'].includes(row.status)" link type="danger" @click="action(row,'cancel')">取消</el-button><span v-if="['FULFILLED','CANCELLED'].includes(row.status)" class="muted">已完结</span></template></el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="filterDrawer" title="筛选客户订单" size="min(420px, 92vw)">
      <el-form label-position="top">
        <el-form-item label="订单状态"><el-select v-model="filters.status" clearable placeholder="全部状态" style="width:100%"><el-option v-for="(meta, key) in statusMap" :key="key" :label="meta.label" :value="key" /></el-select></el-form-item>
        <el-form-item label="订单日期"><el-date-picker v-model="filters.dateRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" range-separator="至" style="width:100%" /></el-form-item>
        <div class="filter-drawer-footer"><el-button @click="resetFilters">重置</el-button><el-button type="primary" @click="applyFilters">应用筛选</el-button></div>
      </el-form>
    </el-drawer>

    <el-drawer v-model="drawer" title="新建客户订单" size="min(760px, 96vw)">
      <el-form label-position="top">
        <div class="form-grid">
          <el-form-item label="客户名称" required><el-input v-model="form.customer_name" placeholder="公司或联系人名称" /></el-form-item>
          <el-form-item label="联系电话"><el-input v-model="form.customer_phone" placeholder="手机或座机" /></el-form-item>
          <el-form-item label="订单日期"><el-date-picker v-model="form.order_date" type="date" value-format="YYYY-MM-DD" style="width:100%" /></el-form-item>
          <el-form-item label="送货地址"><el-input v-model="form.customer_address" /></el-form-item>
          <el-form-item class="span-2" label="备注"><el-input v-model="form.notes" type="textarea" :rows="2" /></el-form-item>
        </div>
        <div class="section-label"><span>产品明细</span><el-button size="small" plain @click="addLine"><el-icon><Plus /></el-icon>添加产品</el-button></div>
        <el-table :data="form.items" border>
          <el-table-column label="产品" min-width="260"><template #default="{ row: line }"><el-select v-model="line.product_id" filterable placeholder="选择产品" style="width:100%" @change="productChanged(line)"><el-option v-for="product in products" :key="product.id" :label="`${product.sku} · ${product.name}（库存 ${qty(product.stock_qty)}）`" :value="product.id" :disabled="form.items.some(x => x !== line && x.product_id === product.id)" /></el-select></template></el-table-column>
          <el-table-column label="数量" width="125"><template #default="{ row: line }"><el-input-number v-model="line.quantity" :min="0.001" :precision="3" :controls="false" style="width:100%" /></template></el-table-column>
          <el-table-column label="单价" width="135"><template #default="{ row: line }"><el-input-number v-model="line.unit_price" :min="0" :precision="2" :controls="false" style="width:100%" /></template></el-table-column>
          <el-table-column label="小计" width="105" align="right"><template #default="{ row: line }">{{ money(line.quantity * line.unit_price) }}</template></el-table-column>
          <el-table-column width="58"><template #default="{ $index }"><el-button link type="danger" @click="form.items.splice($index,1)"><el-icon><Delete /></el-icon></el-button></template></el-table-column>
        </el-table>
        <div class="line-total">订单合计 <strong>{{ money(total) }}</strong></div>
        <div class="drawer-footer"><el-button @click="drawer=false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存为草稿</el-button></div>
      </el-form>
    </el-drawer>
  </div>
</template>
