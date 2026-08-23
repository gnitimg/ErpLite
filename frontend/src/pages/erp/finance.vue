<script setup lang="ts">
import { ElMessage, ElMessageBox } from "element-plus"
import { onMounted, ref, computed, reactive } from "vue"
import { api, formatTime, useLiveRefresh } from "./api"
import ListToolbar from "./components/ListToolbar.vue"

interface Receivable {
  id: number
  receivable_no: string
  order_id: number
  order_no: string
  customer_name: string
  amount: number
  settled_amount: number
  remaining_amount: number
  credit_offset_amount: number
  status: string
  created_at: string
  related_stock_transaction_id: number | null
}

interface Payment {
  id: number
  payment_no: string
  customer_name: string
  amount: number
  allocated_amount: number
  payment_date: string
  method: string
  notes: string
  created_at: string
}

interface CustomerCredit {
  id: number
  credit_no: string
  order_id: number | null
  order_return_id: number | null
  receivable_id: number | null
  customer_name: string
  amount: number
  settled_amount: number
  remaining_amount: number
  kind: string
  status: string
  notes: string
  created_at: string
}

const loading = ref(false)
const tab = ref("receivables")
const keyword = ref("")
const receivableRows = ref<Receivable[]>([])
const paymentRows = ref<Payment[]>([])
const creditRows = ref<CustomerCredit[]>([])
const paymentDialog = ref(false)
const allocateDialog = ref(false)
const settleDialog = ref(false)
const paymentForm = reactive({ customer_name: "", amount: 0, payment_date: "", method: "TRANSFER", notes: "" })
const allocateForm = reactive({ payment_id: 0, receivable_id: 0, amount: 0 })
const settleForm = reactive({ credit_id: 0, settled_amount: 0, notes: "" })
const availableReceivables = ref<Receivable[]>([])

const statusLabels: Record<string, string> = { OPEN: "待核销", PARTIAL: "部分核销", SETTLED: "已结清", CANCELLED: "已取消" }
const statusTypes: Record<string, string> = { OPEN: "primary", PARTIAL: "warning", SETTLED: "success", CANCELLED: "info" }
const methodLabels: Record<string, string> = { TRANSFER: "银行转账", CASH: "现金", OTHER: "其他" }
const kindLabels: Record<string, string> = { OFFSET_RECEIVABLE: "冲减应收", REFUND_DUE: "应退现金" }

const rows = computed<(Receivable | Payment | CustomerCredit)[]>(() => {
  if (tab.value === "receivables") return receivableRows.value
  if (tab.value === "credits") return creditRows.value
  return paymentRows.value
})

const filteredRows = computed(() => {
  const token = keyword.value.trim().toLowerCase()
  return rows.value.filter((row) => {
    if (!token) return true
    if (tab.value === "receivables") {
      const r = row as Receivable
      return `${r.receivable_no} ${r.order_no} ${r.customer_name}`.toLowerCase().includes(token)
    }
    if (tab.value === "credits") {
      const c = row as CustomerCredit
      return `${c.credit_no} ${c.customer_name}`.toLowerCase().includes(token)
    }
    const p = row as Payment
    return `${p.payment_no} ${p.customer_name}`.toLowerCase().includes(token)
  })
})

const openReceivables = computed(() => receivableRows.value.filter(r => r.status !== "CANCELLED"))
const totalReceivable = computed(() => openReceivables.value.reduce((s, r) => s + (r.remaining_amount ?? (r.amount - (r.settled_amount || 0))), 0))
const totalSettled = computed(() => openReceivables.value.reduce((s, r) => s + (r.settled_amount || 0), 0))
const totalCreditDue = computed(() => creditRows.value.filter(c => c.status === "OPEN").reduce((s, c) => s + (c.amount - (c.settled_amount || 0)), 0))

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    const [receivables, payments, credits] = await Promise.all([
      api<Receivable[]>("/api/finance/receivables"),
      api<Payment[]>("/api/finance/payments"),
      api<CustomerCredit[]>("/api/finance/credits")
    ])
    receivableRows.value = receivables
    paymentRows.value = payments
    creditRows.value = credits
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    if (!silent) loading.value = false
  }
}

async function createPayment() {
  try {
    await api("/api/finance/payments", {
      method: "POST",
      body: JSON.stringify(paymentForm)
    })
    ElMessage.success("收款记录已创建")
    paymentDialog.value = false
    await load()
  } catch (error: any) {
    ElMessage.error(error.message)
  }
}

async function openAllocateDialog(payment: Payment) {
  availableReceivables.value = await api("/api/finance/receivables")
  availableReceivables.value = availableReceivables.value.filter((r: Receivable) => (r.status === "OPEN" || r.status === "PARTIAL") && r.customer_name === payment.customer_name)
  allocateForm.payment_id = payment.id
  allocateForm.receivable_id = 0
  allocateForm.amount = payment.amount - payment.allocated_amount
  allocateDialog.value = true
}

function onAllocateReceivableChange() {
  const payment = paymentRows.value.find(p => p.id === allocateForm.payment_id)
  const receivable = availableReceivables.value.find(r => r.id === allocateForm.receivable_id)
  if (!payment || !receivable) return
  const paymentRemaining = payment.amount - (payment.allocated_amount || 0)
  const receivableRemaining = receivable.remaining_amount ?? (receivable.amount - (receivable.settled_amount || 0))
  allocateForm.amount = Math.min(paymentRemaining, receivableRemaining)
}

async function allocatePayment() {
  try {
    await api(`/api/finance/payments/${allocateForm.payment_id}/allocate`, {
      method: "POST",
      body: JSON.stringify({ receivable_id: allocateForm.receivable_id, amount: allocateForm.amount })
    })
    ElMessage.success("核销成功")
    allocateDialog.value = false
    await load()
  } catch (error: any) {
    ElMessage.error(error.message)
  }
}

async function openSettleDialog(credit: CustomerCredit) {
  settleForm.credit_id = credit.id
  settleForm.settled_amount = credit.amount - (credit.settled_amount || 0)
  settleForm.notes = ""
  settleDialog.value = true
}

async function settleCredit() {
  try {
    await api(`/api/finance/credits/${settleForm.credit_id}/settle`, {
      method: "POST",
      body: JSON.stringify({ settled_amount: settleForm.settled_amount, notes: settleForm.notes })
    })
    ElMessage.success("退款登记完成")
    settleDialog.value = false
    await load()
  } catch (error: any) {
    ElMessage.error(error.message)
  }
}

onMounted(load)
useLiveRefresh(() => load(true))
</script>

<template>
  <div class="erp-page">
    <div class="metric-grid" style="grid-template-columns:repeat(3,minmax(0,1fr))">
      <div class="metric-card">
        <div>
          <div class="metric-label">应收余额</div>
          <div class="metric-value">{{ totalReceivable.toFixed(2) }}</div>
          <div class="metric-note">未核销应收合计</div>
        </div>
        <div class="metric-icon"><el-icon><Coin /></el-icon></div>
      </div>
      <div class="metric-card">
        <div>
          <div class="metric-label">已核销金额</div>
          <div class="metric-value">{{ totalSettled.toFixed(2) }}</div>
          <div class="metric-note">已收款核销合计</div>
        </div>
        <div class="metric-icon"><el-icon><Wallet /></el-icon></div>
      </div>
      <div class="metric-card">
        <div>
          <div class="metric-label">应退客户</div>
          <div class="metric-value">{{ totalCreditDue.toFixed(2) }}</div>
          <div class="metric-note">未结清客户贷项</div>
        </div>
        <div class="metric-icon"><el-icon><RefreshLeft /></el-icon></div>
      </div>
    </div>

    <el-tabs v-model="tab" @tab-change="() => load()">
      <el-tab-pane label="应收账款" name="receivables" />
      <el-tab-pane label="收款记录" name="payments" />
      <el-tab-pane label="客户贷项" name="credits" />
    </el-tabs>

    <ListToolbar v-model="keyword" :placeholder="tab === 'receivables' ? '搜索应收编号、订单、客户' : tab === 'credits' ? '搜索贷项编号、客户' : '搜索收款编号、客户'" :loading="loading" @refresh="load">
      <el-button v-if="tab === 'payments'" type="primary" @click="paymentDialog = true">
        <el-icon><Plus /></el-icon>新建收款
      </el-button>
    </ListToolbar>

    <div class="content-card">
      <el-table v-loading="loading" :data="filteredRows" row-key="id" empty-text="暂无数据">
        <template v-if="tab === 'receivables'">
          <el-table-column label="应收编号" prop="receivable_no" width="160" />
          <el-table-column label="订单编号" prop="order_no" width="140" />
          <el-table-column label="客户" prop="customer_name" min-width="120" />
          <el-table-column label="应收金额" prop="amount" width="120" align="right" />
          <el-table-column label="已核销" prop="settled_amount" width="120" align="right" />
          <el-table-column label="贷项冲减" width="120" align="right">
            <template #default="{ row }">{{ (row.credit_offset_amount || 0).toFixed(2) }}</template>
          </el-table-column>
          <el-table-column label="剩余" width="120" align="right">
            <template #default="{ row }">{{ (row.remaining_amount ?? (row.amount - row.settled_amount)).toFixed(2) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="(statusTypes[row.status] as any) || 'info'" size="small">{{ statusLabels[row.status] || row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="创建时间" width="170">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
        </template>
        <template v-else-if="tab === 'credits'">
          <el-table-column label="贷项编号" prop="credit_no" width="160" />
          <el-table-column label="客户" prop="customer_name" min-width="120" />
          <el-table-column label="类型" width="100">
            <template #default="{ row }">{{ kindLabels[row.kind] || row.kind }}</template>
          </el-table-column>
          <el-table-column label="金额" prop="amount" width="120" align="right" />
          <el-table-column label="已处理" prop="settled_amount" width="120" align="right" />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="(statusTypes[row.status] as any) || 'info'" size="small">{{ statusLabels[row.status] || row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="创建时间" width="170">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <el-button v-if="row.status === 'OPEN'" link type="primary" @click="openSettleDialog(row as any)">登记退款</el-button>
            </template>
          </el-table-column>
        </template>
        <template v-else>
          <el-table-column label="收款编号" prop="payment_no" width="160" />
          <el-table-column label="客户" prop="customer_name" min-width="120" />
          <el-table-column label="收款金额" prop="amount" width="120" align="right" />
          <el-table-column label="已核销" prop="allocated_amount" width="120" align="right" />
          <el-table-column label="收款方式" width="100">
            <template #default="{ row }">{{ methodLabels[row.method] || row.method }}</template>
          </el-table-column>
          <el-table-column label="收款日期" prop="payment_date" width="120" />
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <el-button v-if="row.allocated_amount < row.amount" link type="primary" @click="openAllocateDialog(row as any)">核销</el-button>
            </template>
          </el-table-column>
        </template>
      </el-table>
    </div>

    <el-dialog v-model="paymentDialog" title="新建收款" width="480px">
      <el-form label-position="top">
        <el-form-item label="客户名称"><el-input v-model="paymentForm.customer_name" /></el-form-item>
        <el-form-item label="收款金额"><el-input-number v-model="paymentForm.amount" :min="0" :precision="2" style="width:100%" /></el-form-item>
        <el-form-item label="收款日期"><el-date-picker v-model="paymentForm.payment_date" type="date" value-format="YYYY-MM-DD" style="width:100%" /></el-form-item>
        <el-form-item label="收款方式">
          <el-select v-model="paymentForm.method" style="width:100%">
            <el-option label="银行转账" value="TRANSFER" />
            <el-option label="现金" value="CASH" />
            <el-option label="其他" value="OTHER" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注"><el-input v-model="paymentForm.notes" type="textarea" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="paymentDialog = false">取消</el-button>
        <el-button type="primary" @click="createPayment">确认</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="allocateDialog" title="核销应收" width="480px">
      <el-form label-position="top">
        <el-form-item label="选择应收">
          <el-select v-model="allocateForm.receivable_id" style="width:100%" placeholder="选择待核销应收" @change="onAllocateReceivableChange">
            <el-option v-for="r in availableReceivables" :key="r.id" :label="`${r.receivable_no} - ${r.customer_name} (余${(r.remaining_amount ?? (r.amount - r.settled_amount)).toFixed(2)})`" :value="r.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="核销金额"><el-input-number v-model="allocateForm.amount" :min="0" :precision="2" style="width:100%" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="allocateDialog = false">取消</el-button>
        <el-button type="primary" @click="allocatePayment">确认核销</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="settleDialog" title="登记客户退款" width="480px">
      <el-form label-position="top">
        <el-form-item label="退款金额"><el-input-number v-model="settleForm.settled_amount" :min="0" :precision="2" style="width:100%" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="settleForm.notes" type="textarea" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="settleDialog = false">取消</el-button>
        <el-button type="primary" @click="settleCredit">确认登记</el-button>
      </template>
    </el-dialog>
  </div>
</template>
