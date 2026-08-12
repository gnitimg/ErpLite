<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, formatTime, money, productQty, qty, txLabels } from './api'
import ListToolbar from './components/ListToolbar.vue'

const route = useRoute()
const loading = ref(false)
const saving = ref(false)
const drawer = ref(false)
const detailDrawer = ref(false)
const filterDrawer = ref(false)
const mode = ref<'inbound' | 'outbound'>('inbound')
const items = ref<any[]>([])
const rows = ref<any[]>([])
const activeTransaction = ref<any>(null)
const keyword = ref('')
const filters = reactive({ transactionType: '', dateRange: [] as string[] })
const form = reactive({ item_id: undefined as number | undefined, quantity: 1, unit_cost: 0, notes: '' })
const isHistory = computed(() => route.meta.stockView === 'history')
const selected = computed(() => items.value.find(item => item.id === form.item_id))
const activeFilterCount = computed(() => Number(Boolean(filters.transactionType)) + Number(filters.dateRange.length === 2))
const quantityText = (item: any, value: number) => item?.kind === 'PRODUCT' ? productQty(value) : qty(value)
const inboundItems = computed(() => items.value.filter(item => item.kind === 'PART' || item.kind === 'PRODUCT'))
const outboundItems = computed(() => items.value)

async function load() {
  loading.value = true
  const params = new URLSearchParams()
  if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
  if (filters.transactionType) params.set('transaction_type', filters.transactionType)
  if (filters.dateRange.length === 2) { params.set('start_date', filters.dateRange[0]); params.set('end_date', filters.dateRange[1]) }
  try { [items.value, rows.value] = await Promise.all([api('/api/inventory'), api(`/api/stock/transactions?${params}`)]) }
  catch (error: any) { ElMessage.error(error.message) }
  finally { loading.value = false }
}
function applyFilters() { filterDrawer.value = false; load() }
function resetFilters() { filters.transactionType = ''; filters.dateRange = []; applyFilters() }
function open(type: 'inbound' | 'outbound', item?: any) {
  mode.value = type
  Object.assign(form, { item_id: item?.id, quantity: 1, unit_cost: item?.cost_price || 0, notes: '' })
  drawer.value = true
}
function onItemChange() { form.unit_cost = selected.value?.cost_price || 0; form.quantity = 1 }
function openDetail(row: any) { activeTransaction.value = row; detailDrawer.value = true }
async function save() {
  if (!selected.value || form.quantity <= 0) return ElMessage.warning('请选择物料并填写数量')
  if (selected.value.kind === 'PRODUCT' && !Number.isInteger(form.quantity)) return ElMessage.warning('产品数量必须为正整数')
  if (!form.notes.trim()) return ElMessage.warning('请填写本次出入库作业的备注信息')
  const verb = mode.value === 'inbound' ? '入库' : '出库'
  try {
    await ElMessageBox.confirm(`确认将 ${quantityText(selected.value, form.quantity)} ${selected.value.unit}“${selected.value.name}”办理${verb}吗？`, `确认${verb}作业`, { type: 'warning' })
    saving.value = true
    await api(`/api/stock/${mode.value}`, { method: 'POST', body: JSON.stringify({ ...form, consume_bom: false }) })
    ElMessage.success(`${verb}作业已完成并生成库存流水`)
    drawer.value = false
    await load()
  } catch (error: any) { if (error !== 'cancel') ElMessage.error(error.message) }
  finally { saving.value = false }
}
onMounted(load)
watch(() => route.name, load)
</script>

<template>
  <div class="erp-page stock-work-page">
    <template v-if="!isHistory">
      <div class="stock-operation-hero">
        <div><h2>出入库作业</h2><p>采购到货、其他入库、生产领料或日常领用均从这里办理；产品生产请使用独立生产作业。</p></div>
        <el-button @click="load"><el-icon><Refresh /></el-icon>刷新库存</el-button>
      </div>
      <div class="stock-operation-grid">
        <button class="stock-operation-card inbound" type="button" @click="open('inbound')"><span class="stock-operation-icon"><el-icon><BottomLeft /></el-icon></span><span><strong>办理入库</strong><small>零件采购到货、成品盘盈或其他入库</small></span><el-icon class="stock-operation-arrow"><ArrowRight /></el-icon></button>
        <button class="stock-operation-card outbound" type="button" @click="open('outbound')"><span class="stock-operation-icon"><el-icon><TopRight /></el-icon></span><span><strong>办理出库</strong><small>零件领用、产品非客单出库或库存调整</small></span><el-icon class="stock-operation-arrow"><ArrowRight /></el-icon></button>
      </div>
      <div class="content-card">
        <div class="card-head"><h3>当前物料库存</h3><span>提交作业前请确认物料和可用结存</span></div>
        <el-table v-loading="loading" :data="items" height="420">
          <el-table-column label="物料" min-width="230"><template #default="{ row }"><div class="sku-cell"><strong>{{ row.name }}</strong><span class="mono">{{ row.sku }} · {{ row.spec || '无规格' }}</span></div></template></el-table-column>
          <el-table-column label="类型" width="90"><template #default="{ row }"><el-tag :type="row.kind === 'PRODUCT' ? 'primary' : 'info'" size="small" effect="plain">{{ row.kind === 'PRODUCT' ? '产品' : '零件' }}</el-tag></template></el-table-column>
          <el-table-column label="实时结存" width="135" align="right"><template #default="{ row }"><b :class="row.low_stock ? 'number-negative' : 'number-positive'">{{ quantityText(row, row.stock_qty) }}</b> {{ row.unit }}</template></el-table-column>
          <el-table-column label="可用库存" width="125" align="right"><template #default="{ row }">{{ quantityText(row, row.available_qty ?? row.stock_qty) }} {{ row.unit }}</template></el-table-column>
          <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="row.low_stock ? 'danger' : 'success'" size="small">{{ row.low_stock ? '库存预警' : '正常' }}</el-tag></template></el-table-column>
          <el-table-column label="快捷作业" width="150" fixed="right"><template #default="{ row }"><el-button link type="success" @click="open('inbound', row)">入库</el-button><el-button link type="warning" @click="open('outbound', row)">出库</el-button></template></el-table-column>
        </el-table>
      </div>
    </template>

    <template v-else>
      <ListToolbar v-model="keyword" placeholder="搜索流水号、物料编码/名称或备注" :filter-count="activeFilterCount" :loading="loading" @search="load" @filter="filterDrawer=true" @refresh="load" />
      <div class="content-card">
        <div class="card-head"><h3>库存流水</h3><span>最近 {{ rows.length }} 条 · 点击详情查看完整物料和业务信息</span></div>
        <el-table v-loading="loading" :data="rows">
          <el-table-column label="流水号" min-width="190"><template #default="{ row }"><span class="mono">{{ row.transaction_no }}</span></template></el-table-column>
          <el-table-column label="发生时间" width="175"><template #default="{ row }"><span class="muted">{{ formatTime(row.occurred_at) }}</span></template></el-table-column>
          <el-table-column label="业务类型" width="120"><template #default="{ row }"><el-tag effect="plain" size="small" :type="row.transaction_type.includes('OUT') ? 'warning' : row.transaction_type === 'OPENING' ? 'info' : 'success'">{{ txLabels[row.transaction_type] || row.transaction_type }}</el-tag></template></el-table-column>
          <el-table-column label="物料摘要" min-width="300"><template #default="{ row }"><span>{{ row.lines[0]?.name || '-' }}</span><span v-if="row.lines.length > 1" class="muted"> 等 {{ row.lines.length }} 项</span><b v-if="row.lines.length === 1" :class="row.lines[0].quantity_change > 0 ? 'number-positive' : 'number-negative'"> {{ row.lines[0].quantity_change > 0 ? '+' : '' }}{{ quantityText(row.lines[0], row.lines[0].quantity_change) }} {{ row.lines[0].unit }}</b></template></el-table-column>
          <el-table-column label="操作" width="90" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openDetail(row)">详情</el-button></template></el-table-column>
        </el-table>
      </div>
    </template>

    <el-drawer v-model="filterDrawer" title="筛选库存流水" size="min(420px, 92vw)"><el-form label-position="top"><el-form-item label="业务类型"><el-select v-model="filters.transactionType" clearable placeholder="全部类型" style="width:100%"><el-option v-for="(label, key) in txLabels" :key="key" :label="label" :value="key" /></el-select></el-form-item><el-form-item label="发生日期"><el-date-picker v-model="filters.dateRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" range-separator="至" style="width:100%" /></el-form-item><div class="filter-drawer-footer"><el-button @click="resetFilters">重置</el-button><el-button type="primary" @click="applyFilters">应用筛选</el-button></div></el-form></el-drawer>

    <el-drawer v-model="drawer" :title="mode === 'inbound' ? '办理入库作业' : '办理出库作业'" size="min(600px, 96vw)">
      <el-form label-position="top">
        <el-alert :title="mode === 'inbound' ? '产品生产请前往“产品生产”页面；这里的产品入库不会扣减 BOM 零件。' : '产品出库会校验客单预留，已预留库存不能被其他作业占用。'" type="info" :closable="false" show-icon style="margin-bottom:20px" />
        <el-form-item label="物料" required><el-select v-model="form.item_id" filterable placeholder="按编码或名称选择物料" style="width:100%" @change="onItemChange"><el-option-group label="零件"><el-option v-for="item in (mode === 'inbound' ? inboundItems : outboundItems).filter(x => x.kind === 'PART')" :key="item.id" :label="`${item.sku} · ${item.name}（库存 ${qty(item.stock_qty)}）`" :value="item.id" /></el-option-group><el-option-group label="产品"><el-option v-for="item in (mode === 'inbound' ? inboundItems : outboundItems).filter(x => x.kind === 'PRODUCT')" :key="item.id" :label="`${item.sku} · ${item.name}（可用 ${productQty(item.available_qty)}）`" :value="item.id" /></el-option-group></el-select></el-form-item>
        <div class="form-grid"><el-form-item :label="`作业数量${selected ? `（${selected.unit}）` : ''}`" required><el-input-number v-model="form.quantity" :min="selected?.kind === 'PRODUCT' ? 1 : 0.001" :step="selected?.kind === 'PRODUCT' ? 1 : 0.001" :step-strictly="selected?.kind === 'PRODUCT'" :precision="selected?.kind === 'PRODUCT' ? 0 : 3" style="width:100%" /></el-form-item><el-form-item v-if="mode === 'inbound'" label="入库单位成本"><el-input-number v-model="form.unit_cost" :min="0" :precision="2" :controls="false" style="width:100%" /></el-form-item></div>
        <div v-if="selected" class="stock-operation-preview"><div><span>当前结存</span><strong>{{ quantityText(selected, selected.stock_qty) }} {{ selected.unit }}</strong></div><div v-if="selected.kind === 'PRODUCT'"><span>客单预留</span><strong>{{ productQty(selected.reserved_qty) }} {{ selected.unit }}</strong></div><div><span>作业后预计</span><strong :class="mode === 'outbound' && form.quantity > (selected.available_qty ?? selected.stock_qty) ? 'number-negative' : ''">{{ quantityText(selected, Number(selected.stock_qty) + (mode === 'inbound' ? Number(form.quantity) : -Number(form.quantity))) }} {{ selected.unit }}</strong></div></div>
        <el-form-item label="作业备注" required><el-input v-model="form.notes" type="textarea" :rows="4" :placeholder="mode === 'inbound' ? '请填写供应商、批次、到货单号或入库原因' : '请填写领用部门、领用人、用途或出库原因'" /></el-form-item>
        <div v-if="selected && mode === 'inbound'" class="line-total">入库金额 <strong>{{ money(form.quantity * form.unit_cost) }}</strong></div>
        <div class="drawer-footer"><el-button @click="drawer=false">取消</el-button><el-button type="primary" :loading="saving" @click="save">确认{{ mode === 'inbound' ? '入库' : '出库' }}</el-button></div>
      </el-form>
    </el-drawer>

    <el-drawer v-model="detailDrawer" title="库存流水详情" size="min(720px, 96vw)">
      <template v-if="activeTransaction"><el-descriptions :column="2" border><el-descriptions-item label="流水号" :span="2"><span class="mono">{{ activeTransaction.transaction_no }}</span></el-descriptions-item><el-descriptions-item label="业务类型">{{ txLabels[activeTransaction.transaction_type] || activeTransaction.transaction_type }}</el-descriptions-item><el-descriptions-item label="发生时间">{{ formatTime(activeTransaction.occurred_at) }}</el-descriptions-item><el-descriptions-item label="关联客单" :span="2"><span class="mono">{{ activeTransaction.related_order_no || '无' }}</span></el-descriptions-item><el-descriptions-item label="备注" :span="2">{{ activeTransaction.notes || '无' }}</el-descriptions-item></el-descriptions><div class="detail-section-head"><strong>物料变化明细</strong><span>正数表示入库，负数表示出库</span></div><el-table :data="activeTransaction.lines" border><el-table-column label="物料" min-width="200"><template #default="{ row }"><div class="sku-cell"><strong>{{ row.name }}</strong><span class="mono">{{ row.sku }} · {{ row.kind === 'PRODUCT' ? '产品' : '零件' }}</span></div></template></el-table-column><el-table-column label="数量变化" width="130" align="right"><template #default="{ row }"><b :class="row.quantity_change > 0 ? 'number-positive' : 'number-negative'">{{ row.quantity_change > 0 ? '+' : '' }}{{ quantityText(row, row.quantity_change) }} {{ row.unit }}</b></template></el-table-column><el-table-column label="单位成本" width="120" align="right"><template #default="{ row }">{{ money(row.unit_cost) }}</template></el-table-column><el-table-column label="变动金额" width="130" align="right"><template #default="{ row }">{{ money(Math.abs(row.quantity_change * row.unit_cost)) }}</template></el-table-column></el-table></template>
    </el-drawer>
  </div>
</template>
