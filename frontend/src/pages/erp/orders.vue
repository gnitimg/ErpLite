<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, money, qty, statusMap } from './api'
import ListToolbar from './components/ListToolbar.vue'

const loading = ref(false)
const saving = ref(false)
const drawer = ref(false)
const filterDrawer = ref(false)
const workflowDrawer = ref(false)
const workflowLoading = ref(false)
const workflow = ref<any>(null)
const activeOrder = ref<any>(null)
const rows = ref<any[]>([])
const products = ref<any[]>([])
const keyword = ref('')
const filters = reactive({ status: '', dateRange: [] as string[] })
const form = reactive({ customer_name: '', customer_phone: '', customer_address: '', order_date: new Date().toISOString().slice(0, 10), required_date: new Date().toISOString().slice(0, 10), notes: '', items: [] as any[] })
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
  Object.assign(form, { customer_name: '', customer_phone: '', customer_address: '', order_date: new Date().toISOString().slice(0, 10), required_date: new Date().toISOString().slice(0, 10), notes: '', items: [] })
  form.items.push({ product_id: undefined, quantity: 1, reference_price: 0, unit_price: 0 })
  drawer.value = true
}
function addLine() { form.items.push({ product_id: undefined, quantity: 1, reference_price: 0, unit_price: 0 }) }
function productChanged(line: any) { const product = products.value.find(x => x.id === line.product_id); line.reference_price = product?.sale_price || 0; line.unit_price = product?.sale_price || 0 }
function disableRequiredDate(value: Date) { return value < new Date(form.order_date + 'T00:00:00') }
async function save() {
  if (!form.customer_name.trim()) return ElMessage.warning('请输入客户名称')
  if (!form.required_date || form.required_date < form.order_date) return ElMessage.warning('请选择不早于订单日期的要求交期')
  if (!form.items.length || form.items.some(line => !line.product_id || line.quantity <= 0)) return ElMessage.warning('请完整填写产品明细')
  saving.value = true
  try {
    await api('/api/orders', { method: 'POST', body: JSON.stringify(form) })
    ElMessage.success('客单已创建'); drawer.value = false; await load()
  } catch (error: any) { ElMessage.error(error.message) }
  finally { saving.value = false }
}
async function openWorkflow(row: any) {
  activeOrder.value = row
  workflowDrawer.value = true
  workflowLoading.value = true
  try { workflow.value = await api(`/api/orders/${row.id}/availability`) }
  catch (error: any) { ElMessage.error(error.message) }
  finally { workflowLoading.value = false }
}
async function action(row: any, type: 'confirm' | 'prepare' | 'fulfill' | 'cancel') {
  const labels = { confirm: '确认客单并检查库存', prepare: '重新检查零件并完成生产备货', fulfill: '确认产品出库', cancel: '取消客单' }
  try {
    await ElMessageBox.confirm(`确定${labels[type]}“${row.order_no}”吗？`, '客单操作', { type: type === 'cancel' ? 'warning' : 'info' })
    await api(`/api/orders/${row.id}/${type}`, { method: 'POST' })
    ElMessage.success(labels[type] + '成功'); await load()
    if (workflowDrawer.value && activeOrder.value?.id === row.id) await openWorkflow(rows.value.find(x => x.id === row.id) || row)
  } catch (error: any) { if (error !== 'cancel') ElMessage.error(error.message) }
}
onMounted(load)
</script>

<template>
  <div class="erp-page orders-page">
    <ListToolbar v-model="keyword" placeholder="搜索客单号、客户名称或电话" :filter-count="activeFilterCount" :loading="loading" @search="load" @filter="filterDrawer=true" @refresh="load">
      <el-button type="primary" @click="openCreate"><el-icon><Plus /></el-icon>新建客单</el-button>
    </ListToolbar>
    <div class="content-card">
      <div class="card-head"><h3>客户订单</h3><span>出库后自动写入库存流水</span></div>
      <el-table v-loading="loading" :data="rows" row-key="id" empty-text="暂无符合条件的客户订单">
        <el-table-column label="客单号" min-width="185"><template #default="{ row }"><span class="mono">{{ row.order_no }}</span></template></el-table-column>
        <el-table-column label="客户" min-width="170"><template #default="{ row }"><div class="sku-cell"><strong>{{ row.customer_name }}</strong><span>{{ row.customer_phone || '未留电话' }}</span></div></template></el-table-column>
        <el-table-column prop="order_date" label="订单日期" width="115" />
        <el-table-column prop="required_date" label="要求交期" width="115" />
        <el-table-column label="产品数" width="90" align="right"><template #default="{ row }">{{ row.items.length }} 项</template></el-table-column>
        <el-table-column label="订单金额" width="125" align="right"><template #default="{ row }"><strong>{{ money(row.total_amount) }}</strong></template></el-table-column>
        <el-table-column label="状态" width="90"><template #default="{ row }"><el-tag :type="statusMap[row.status]?.type as any" size="small">{{ statusMap[row.status]?.label || row.status }}</el-tag></template></el-table-column>
        <el-table-column label="操作" min-width="245" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openWorkflow(row)">详情</el-button><el-button v-if="row.status === 'DRAFT'" link @click="action(row,'confirm')">确认</el-button><el-button v-if="row.status === 'READY_TO_SHIP'" link type="success" @click="action(row,'fulfill')">出库</el-button><el-button v-if="!['FULFILLED','CANCELLED'].includes(row.status)" link type="danger" @click="action(row,'cancel')">取消</el-button><span v-if="['FULFILLED','CANCELLED'].includes(row.status)" class="muted">已完结</span></template></el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="filterDrawer" title="筛选客户订单" size="min(420px, 92vw)">
      <el-form label-position="top">
        <el-form-item label="订单状态"><el-select v-model="filters.status" clearable placeholder="全部状态" style="width:100%"><el-option v-for="(meta, key) in statusMap" :key="key" :label="meta.label" :value="key" /></el-select></el-form-item>
        <el-form-item label="订单日期"><el-date-picker v-model="filters.dateRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" range-separator="至" style="width:100%" /></el-form-item>
        <div class="filter-drawer-footer"><el-button @click="resetFilters">重置</el-button><el-button type="primary" @click="applyFilters">应用筛选</el-button></div>
      </el-form>
    </el-drawer>

    <el-drawer v-model="workflowDrawer" :title="`客单备货 · ${activeOrder?.order_no || ''}`" size="min(760px, 96vw)">
      <div v-loading="workflowLoading">
        <el-descriptions v-if="activeOrder" :column="2" border size="small" style="margin-bottom:16px"><el-descriptions-item label="客户">{{ activeOrder.customer_name }}</el-descriptions-item><el-descriptions-item label="联系电话">{{ activeOrder.customer_phone || '-' }}</el-descriptions-item><el-descriptions-item label="订单日期">{{ activeOrder.order_date }}</el-descriptions-item><el-descriptions-item label="要求交期"><b>{{ activeOrder.required_date }}</b></el-descriptions-item><el-descriptions-item label="送货地址" :span="2">{{ activeOrder.customer_address || '-' }}</el-descriptions-item><el-descriptions-item label="备注" :span="2">{{ activeOrder.notes || '-' }}</el-descriptions-item></el-descriptions>
        <div class="section-label"><span>产品与成交价格</span></div>
        <el-table v-if="activeOrder" :data="activeOrder.items" border size="small" style="margin-bottom:16px"><el-table-column label="产品" min-width="170"><template #default="{ row }"><div class="sku-cell"><strong>{{ row.product_name }}</strong><span>{{ row.product_sku }}</span></div></template></el-table-column><el-table-column label="数量" width="75" align="right"><template #default="{ row }">{{ qty(row.quantity) }}</template></el-table-column><el-table-column label="参考价" width="100" align="right"><template #default="{ row }">{{ money(row.reference_price) }}</template></el-table-column><el-table-column label="本单价格" width="105" align="right"><template #default="{ row }"><b>{{ money(row.unit_price) }}</b></template></el-table-column><el-table-column label="折扣" width="75" align="right"><template #default="{ row }">{{ row.discount_rate }}%</template></el-table-column><el-table-column label="优惠" width="100" align="right"><template #default="{ row }">{{ money(row.discount_amount) }}</template></el-table-column><el-table-column label="小计" width="105" align="right"><template #default="{ row }">{{ money(row.line_total) }}</template></el-table-column></el-table>
        <div v-if="workflow" class="workflow-panel">
          <div class="workflow-steps"><div class="workflow-step active">1 接单</div><div class="workflow-step" :class="{ active: workflow.status !== 'DRAFT' }">2 检查产品库存</div><div class="workflow-step" :class="{ active: ['WAITING_MATERIALS','READY_TO_SHIP','FULFILLED'].includes(workflow.status) }">3 零件采购/备料</div><div class="workflow-step" :class="{ active: ['READY_TO_SHIP','FULFILLED'].includes(workflow.status) }">4 生产并预留</div><div class="workflow-step" :class="{ active: workflow.status === 'FULFILLED' }">5 产品出库</div></div>
          <div class="workflow-summary"><el-tag :type="statusMap[workflow.status]?.type as any">{{ statusMap[workflow.status]?.label || workflow.status }}</el-tag><el-tag v-if="workflow.next_action === 'PURCHASE'" type="warning">下一步：采购缺料</el-tag><el-tag v-else-if="workflow.next_action === 'WAIT_PRIORITY'" type="warning">等待更近交期客单优先备货</el-tag><el-tag v-else-if="workflow.next_action === 'PRODUCE'" type="primary">下一步：生产入库</el-tag><el-tag v-else-if="workflow.next_action === 'SHIP'" type="success">下一步：产品出库</el-tag><el-tag v-else-if="workflow.next_action === 'CONFIGURE_BOM'" type="danger">需要配置 BOM</el-tag></div>
          <el-alert v-if="workflow.missing_bom.length" :title="`有 ${workflow.missing_bom.length} 个缺货产品未配置 BOM，暂不能自动生产。`" type="error" :closable="false" show-icon />
        </div>
        <div class="section-label"><span>产品库存与预留</span></div>
        <el-table v-if="workflow" :data="workflow.product_lines" border size="small"><el-table-column label="产品" min-width="170"><template #default="{ row }"><div class="sku-cell"><strong>{{ row.name }}</strong><span>{{ row.sku }}</span></div></template></el-table-column><el-table-column label="交期优先级" width="105" align="center"><template #default="{ row }"><el-tag :type="row.waiting_for_earlier_orders ? 'warning' : 'success'" size="small">第 {{ row.priority_rank }} / {{ row.priority_total }} 位</el-tag></template></el-table-column><el-table-column label="订单数量" width="90" align="right"><template #default="{ row }">{{ qty(row.ordered_quantity) }}</template></el-table-column><el-table-column label="已预留" width="85" align="right"><template #default="{ row }"><b class="number-positive">{{ qty(row.reserved_quantity) }}</b></template></el-table-column><el-table-column label="需生产" width="85" align="right"><template #default="{ row }"><b :class="row.production_required ? 'number-negative' : ''">{{ qty(row.production_required) }}</b></template></el-table-column></el-table>
        <div class="section-label"><span>零件需求与采购</span><span class="muted">按 BOM 汇总缺货产品所需零件</span></div>
        <el-table v-if="workflow" :data="workflow.material_lines" border size="small" empty-text="无需额外生产或暂无 BOM 零件需求"><el-table-column label="零件" min-width="180"><template #default="{ row }"><div class="sku-cell"><strong>{{ row.name }}</strong><span>{{ row.sku }}</span></div></template></el-table-column><el-table-column label="备料方式" width="105"><template #default="{ row }"><el-tag :type="row.supply_mode === 'BUY_TO_ORDER' ? 'warning' : 'info'" size="small" effect="plain">{{ row.supply_mode === 'BUY_TO_ORDER' ? '按单即买' : '库存备料' }}</el-tag></template></el-table-column><el-table-column label="需要" width="90" align="right"><template #default="{ row }">{{ qty(row.required_quantity) }}</template></el-table-column><el-table-column label="现有" width="90" align="right"><template #default="{ row }">{{ qty(row.available_stock) }}</template></el-table-column><el-table-column label="缺口" width="90" align="right"><template #default="{ row }"><b :class="row.shortage_quantity ? 'number-negative' : 'number-positive'">{{ qty(row.shortage_quantity) }}</b></template></el-table-column></el-table>
        <div v-if="workflow && !['FULFILLED','CANCELLED'].includes(workflow.status)" class="drawer-footer"><el-button v-if="workflow.status === 'WAITING_MATERIALS'" type="primary" @click="action(activeOrder,'prepare')">零件已入库，重新检查并生产</el-button><el-button v-if="workflow.status === 'READY_TO_SHIP'" type="success" @click="action(activeOrder,'fulfill')">确认产品出库</el-button></div>
      </div>
    </el-drawer>

    <el-drawer v-model="drawer" title="新建客户订单" size="min(760px, 96vw)">
      <el-form label-position="top">
        <div class="form-grid">
          <el-form-item label="客户名称" required><el-input v-model="form.customer_name" placeholder="公司或联系人名称" /></el-form-item>
          <el-form-item label="联系电话"><el-input v-model="form.customer_phone" placeholder="手机或座机" /></el-form-item>
          <el-form-item label="订单日期"><el-date-picker v-model="form.order_date" type="date" value-format="YYYY-MM-DD" style="width:100%" /></el-form-item>
          <el-form-item label="要求交期" required><el-date-picker v-model="form.required_date" type="date" value-format="YYYY-MM-DD" :disabled-date="disableRequiredDate" style="width:100%" /></el-form-item>
          <el-form-item label="送货地址"><el-input v-model="form.customer_address" /></el-form-item>
          <el-form-item class="span-2" label="备注"><el-input v-model="form.notes" type="textarea" :rows="2" /></el-form-item>
        </div>
        <div class="section-label"><span>产品明细</span><el-button size="small" plain @click="addLine"><el-icon><Plus /></el-icon>添加产品</el-button></div>
        <el-table :data="form.items" border>
          <el-table-column label="产品" min-width="260"><template #default="{ row: line }"><el-select v-model="line.product_id" filterable placeholder="选择产品" style="width:100%" @change="productChanged(line)"><el-option v-for="product in products" :key="product.id" :label="`${product.sku} · ${product.name}（库存 ${qty(product.stock_qty)}）`" :value="product.id" :disabled="form.items.some(x => x !== line && x.product_id === product.id)" /></el-select></template></el-table-column>
          <el-table-column label="数量" width="125"><template #default="{ row: line }"><el-input-number v-model="line.quantity" :min="0.001" :precision="3" :controls="false" style="width:100%" /></template></el-table-column>
          <el-table-column label="参考价" width="105" align="right"><template #default="{ row: line }">{{ money(line.reference_price || 0) }}</template></el-table-column>
          <el-table-column label="本单价格" width="135"><template #default="{ row: line }"><el-input-number v-model="line.unit_price" :min="0" :precision="2" :controls="false" style="width:100%" /></template></el-table-column>
          <el-table-column label="折扣" width="80" align="right"><template #default="{ row: line }">{{ line.reference_price ? Math.round(line.unit_price / line.reference_price * 100) : 100 }}%</template></el-table-column>
          <el-table-column label="小计" width="105" align="right"><template #default="{ row: line }">{{ money(line.quantity * line.unit_price) }}</template></el-table-column>
          <el-table-column width="58"><template #default="{ $index }"><el-button link type="danger" @click="form.items.splice($index,1)"><el-icon><Delete /></el-icon></el-button></template></el-table-column>
        </el-table>
        <div class="line-total">订单合计 <strong>{{ money(total) }}</strong></div>
        <div class="drawer-footer"><el-button @click="drawer=false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存为草稿</el-button></div>
      </el-form>
    </el-drawer>
  </div>
</template>
