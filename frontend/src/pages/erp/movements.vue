<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, formatTime, money, qty, txLabels } from './api'

const loading = ref(false)
const saving = ref(false)
const drawer = ref(false)
const mode = ref<'inbound' | 'outbound'>('inbound')
const items = ref<any[]>([])
const rows = ref<any[]>([])
const form = reactive({ item_id: undefined as number | undefined, quantity: 1, unit_cost: 0, notes: '', consume_bom: true })
const selected = computed(() => items.value.find(item => item.id === form.item_id))

async function load() {
  loading.value = true
  try { [items.value, rows.value] = await Promise.all([api('/api/inventory'), api('/api/stock/transactions')]) }
  catch (error: any) { ElMessage.error(error.message) }
  finally { loading.value = false }
}
function open(type: 'inbound' | 'outbound') {
  mode.value = type
  Object.assign(form, { item_id: undefined, quantity: 1, unit_cost: 0, notes: '', consume_bom: true })
  drawer.value = true
}
function onItemChange() { form.unit_cost = selected.value?.cost_price || 0 }
async function save() {
  if (!form.item_id || form.quantity <= 0) return ElMessage.warning('请选择物料并填写数量')
  saving.value = true
  try {
    await api(`/api/stock/${mode.value}`, { method: 'POST', body: JSON.stringify(form) })
    ElMessage.success(mode.value === 'inbound' ? '入库已完成' : '出库已完成')
    drawer.value = false
    await load()
  } catch (error: any) { ElMessage.error(error.message) }
  finally { saving.value = false }
}
onMounted(load)
</script>

<template>
  <div class="erp-page">
    <div class="page-toolbar">
      <div class="toolbar-group"><el-alert title="库存修改必须通过业务流水，系统会自动阻止负库存。" type="info" :closable="false" show-icon /></div>
      <div class="toolbar-group"><el-button @click="open('outbound')"><el-icon><TopRight /></el-icon>办理出库</el-button><el-button type="primary" @click="open('inbound')"><el-icon><BottomLeft /></el-icon>办理入库</el-button></div>
    </div>
    <div class="content-card">
      <div class="card-head"><h3>库存流水</h3><span>最近 {{ rows.length }} 条</span></div>
      <el-table v-loading="loading" :data="rows">
        <el-table-column label="流水号 / 时间" min-width="190"><template #default="{ row }"><div class="sku-cell"><strong class="mono">{{ row.transaction_no }}</strong><span>{{ formatTime(row.occurred_at) }}</span></div></template></el-table-column>
        <el-table-column label="业务类型" width="110"><template #default="{ row }"><el-tag effect="plain" size="small" :type="row.transaction_type.includes('OUT') ? 'warning' : row.transaction_type === 'OPENING' ? 'info' : 'success'">{{ txLabels[row.transaction_type] || row.transaction_type }}</el-tag></template></el-table-column>
        <el-table-column label="物料明细" min-width="320"><template #default="{ row }"><div class="tx-lines"><span v-for="line in row.lines" :key="line.id" class="tx-line">{{ line.name }} <b :class="line.quantity_change > 0 ? 'number-positive' : 'number-negative'">{{ line.quantity_change > 0 ? '+' : '' }}{{ qty(line.quantity_change) }} {{ line.unit }}</b></span></div></template></el-table-column>
        <el-table-column label="关联客单" width="155"><template #default="{ row }"><span class="mono">{{ row.related_order_no || '-' }}</span></template></el-table-column>
        <el-table-column label="备注" min-width="150"><template #default="{ row }"><span class="muted">{{ row.notes || '-' }}</span></template></el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="drawer" :title="mode === 'inbound' ? '办理入库' : '办理出库'" size="min(520px, 94vw)">
      <el-form label-position="top">
        <el-form-item label="物料"><el-select v-model="form.item_id" filterable placeholder="选择零件或产品" style="width:100%" @change="onItemChange"><el-option-group label="零件"><el-option v-for="item in items.filter(x => x.kind === 'PART')" :key="item.id" :label="`${item.sku} · ${item.name}（库存 ${qty(item.stock_qty)}）`" :value="item.id" /></el-option-group><el-option-group label="产品"><el-option v-for="item in items.filter(x => x.kind === 'PRODUCT')" :key="item.id" :label="`${item.sku} · ${item.name}（库存 ${qty(item.stock_qty)}）`" :value="item.id" /></el-option-group></el-select></el-form-item>
        <div class="form-grid">
          <el-form-item :label="`数量${selected ? `（${selected.unit}）` : ''}`"><el-input-number v-model="form.quantity" :min="0.001" :precision="3" :controls="false" style="width:100%" /></el-form-item>
          <el-form-item v-if="mode === 'inbound'" label="入库单位成本"><el-input-number v-model="form.unit_cost" :min="0" :precision="2" :controls="false" style="width:100%" /></el-form-item>
        </div>
        <el-form-item v-if="mode === 'inbound' && selected?.kind === 'PRODUCT'"><el-switch v-model="form.consume_bom" active-text="按 BOM 扣减组成零件" /></el-form-item>
        <el-alert v-if="mode === 'inbound' && selected?.kind === 'PRODUCT' && form.consume_bom" title="这是生产入库：增加成品库存，并按产品 BOM × 入库数量扣减零件。" type="warning" :closable="false" show-icon style="margin-bottom:18px" />
        <el-alert v-if="mode === 'outbound' && selected" :title="`当前可用库存：${qty(selected.stock_qty)} ${selected.unit}`" type="info" :closable="false" style="margin-bottom:18px" />
        <el-form-item label="备注"><el-input v-model="form.notes" type="textarea" :rows="3" :placeholder="mode === 'inbound' ? '供应商、批次或生产说明' : '领用人、用途或其他说明'" /></el-form-item>
        <div v-if="selected" class="line-total">预计库存变化 <strong :class="mode === 'inbound' ? 'number-positive' : 'number-negative'">{{ mode === 'inbound' ? '+' : '-' }}{{ qty(form.quantity) }} {{ selected.unit }}</strong><div v-if="mode === 'inbound'" class="muted" style="font-size:11px;margin-top:4px">金额 {{ money(form.quantity * form.unit_cost) }}</div></div>
        <div class="drawer-footer"><el-button @click="drawer=false">取消</el-button><el-button type="primary" :loading="saving" @click="save">确认{{ mode === 'inbound' ? '入库' : '出库' }}</el-button></div>
      </el-form>
    </el-drawer>
  </div>
</template>
