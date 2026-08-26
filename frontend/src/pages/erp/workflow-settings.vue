<script setup lang="ts">
import type { RouteRecordRaw } from "vue-router"
import { ElMessage } from "element-plus"
import { computed, onMounted, reactive, ref } from "vue"
import { usePermissionStore } from "@/pinia/stores/permission"
import {
  useUserStore,
  type NavigationConfig
} from "@/pinia/stores/user"
import { api } from "./api"
import InfoTip from "./components/InfoTip.vue"

interface NumberRule {
  document_type: string
  label: string
  prefix: string
  next_number: number
  digits: number
  preview: string
}

interface RolePermission {
  role: string
  label: string
  read: boolean
  business_write: boolean
  system_admin: boolean
  description: string
}

interface NavigationItem {
  path: string
  title: string
  visible: boolean
  protected: boolean
  children: Array<{ path: string, title: string }>
}

const flowSteps = [
  { index: "01", title: "接单", text: "创建客户订单并确认交期", to: "/lite-orders/list" },
  { index: "02", title: "备料", text: "查看缺口并登记采购到货", to: "/lite-purchase/requirements" },
  { index: "03", title: "排产", text: "安排生产位并确认开始日期", to: "/lite-production/schedule" },
  { index: "04", title: "完工", text: "审核实际产量及外协流转", to: "/lite-production/completion" },
  { index: "05", title: "交付", text: "开出库单并形成销售单据", to: "/lite-stock-documents/list" },
  { index: "06", title: "结算", text: "核对应收、收款和客户余额", to: "/lite-finance" }
]

const defaultRootOrder = [
  "/",
  "/lite-orders",
  "/lite-purchase",
  "/lite-production",
  "/lite-inventory",
  "/lite-stock-documents",
  "/lite-finance",
  "/lite-catalog",
  "/lite-settings"
]

const activeTab = ref("workflow")
const loading = ref(false)
const savingNumbers = ref(false)
const savingNavigation = ref(false)
const numberRules = ref<NumberRule[]>([])
const rolePermissions = ref<RolePermission[]>([])
const navigationItems = ref<NavigationItem[]>([])
const draggedRoot = ref<number | null>(null)
const draggedChild = reactive({ rootPath: "", index: -1 })
const userStore = useUserStore()
const permissionStore = usePermissionStore()
const isAdmin = computed(() => userStore.roles.includes("ADMIN"))

function routeTitle(route: RouteRecordRaw) {
  return String(route.meta?.title || route.name || route.path)
}

function applyOrder<T extends { path: string }>(items: T[], order: string[]) {
  const positions = new Map(order.map((path, index) => [path, index]))
  return [...items].sort((left, right) =>
    (positions.get(left.path) ?? Number.MAX_SAFE_INTEGER)
    - (positions.get(right.path) ?? Number.MAX_SAFE_INTEGER)
  )
}

function buildNavigationItems() {
  const config = userStore.navigationConfig
  const roots = permissionStore.routes
    .filter(route => !route.meta?.hidden)
    .map(route => ({
      path: route.path,
      title: route.path === "/" ? "工作台" : routeTitle(route),
      visible: !config.hidden_roots.includes(route.path),
      protected: ["/", "/lite-settings"].includes(route.path),
      children: applyOrder(
        (route.children || [])
          .filter(child => !child.meta?.hidden)
          .map(child => ({ path: child.path, title: routeTitle(child) })),
        config.child_order[route.path] || []
      )
    }))
  const rootOrder = config.root_order.length
    ? config.root_order
    : defaultRootOrder
  navigationItems.value = applyOrder(roots, rootOrder)
}

function moveItem<T>(rows: T[], from: number, to: number) {
  if (from < 0 || to < 0 || from === to) return
  const [item] = rows.splice(from, 1)
  rows.splice(to, 0, item)
}

function dropRoot(targetIndex: number) {
  if (draggedRoot.value === null) return
  moveItem(navigationItems.value, draggedRoot.value, targetIndex)
  draggedRoot.value = null
}

function startChildDrag(rootPath: string, index: number) {
  draggedChild.rootPath = rootPath
  draggedChild.index = index
}

function dropChild(root: NavigationItem, targetIndex: number) {
  if (draggedChild.rootPath !== root.path) return
  moveItem(root.children, draggedChild.index, targetIndex)
  draggedChild.rootPath = ""
  draggedChild.index = -1
}

function navigationPayload(): NavigationConfig {
  return {
    root_order: navigationItems.value.map(item => item.path),
    hidden_roots: navigationItems.value
      .filter(item => !item.visible && !item.protected)
      .map(item => item.path),
    child_order: Object.fromEntries(
      navigationItems.value.map(item => [
        item.path,
        item.children.map(child => child.path)
      ])
    )
  }
}

async function saveNavigation() {
  savingNavigation.value = true
  try {
    const payload = navigationPayload()
    await api("/api/v1/users/me/navigation", {
      method: "PUT",
      body: JSON.stringify(payload)
    })
    userStore.setNavigationConfig(payload)
    ElMessage.success("侧栏布局已保存")
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    savingNavigation.value = false
  }
}

async function resetNavigation() {
  userStore.setNavigationConfig({ root_order: [], hidden_roots: [], child_order: {} })
  buildNavigationItems()
  await saveNavigation()
}

async function saveNumberRules() {
  if (!isAdmin.value) return
  savingNumbers.value = true
  try {
    numberRules.value = await api("/api/system/document-numbering", {
      method: "PUT",
      body: JSON.stringify({
        rules: numberRules.value.map(rule => ({
          document_type: rule.document_type,
          prefix: rule.prefix,
          next_number: Number(rule.next_number),
          digits: Number(rule.digits)
        }))
      })
    })
    ElMessage.success("单号规则已保存，新建单据将立即使用")
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    savingNumbers.value = false
  }
}

function numberPreview(rule: NumberRule) {
  const prefix = String(rule.prefix || "").toUpperCase()
  return `${prefix}${Number(rule.next_number || 1)
    .toString()
    .padStart(Number(rule.digits || 6), "0")}`
}

onMounted(async () => {
  loading.value = true
  buildNavigationItems()
  try {
    const [rules, roles] = await Promise.all([
      api<NumberRule[]>("/api/system/document-numbering"),
      api<RolePermission[]>("/api/system/role-permissions")
    ])
    numberRules.value = rules
    rolePermissions.value = roles
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="erp-page workflow-settings-page" v-loading="loading">
    <el-tabs v-model="activeTab" class="settings-tabs">
      <el-tab-pane label="流程顺序" name="workflow" />
      <el-tab-pane label="单号规则" name="numbers" />
      <el-tab-pane label="角色权限" name="roles" />
      <el-tab-pane label="侧栏布局" name="navigation" />
    </el-tabs>

    <section v-if="activeTab === 'workflow'" class="content-card workflow-card">
      <div class="card-head">
        <h3>
          标准业务顺序
          <InfoTip content="这是默认主流程；退货、外协和盘点属于对应阶段的例外处理，不再占用主流程入口。" />
        </h3>
      </div>
      <div class="workflow-track">
        <router-link
          v-for="step in flowSteps"
          :key="step.index"
          :to="step.to"
          class="workflow-step"
        >
          <span>{{ step.index }}</span>
          <strong>{{ step.title }}</strong>
          <small>{{ step.text }}</small>
        </router-link>
      </div>
      <div class="exception-grid">
        <article>
          <strong>库存不足</strong>
          <span>采购需求或自主生产计划承接，不允许用负库存掩盖。</span>
        </article>
        <article>
          <strong>需要外协</strong>
          <span>完工进入半成品，外协回厂后再转成品并等待交付。</span>
        </article>
        <article>
          <strong>客户退货</strong>
          <span>从客户订单登记，按行决定是否退回成品库存。</span>
        </article>
      </div>
    </section>

    <section v-else-if="activeTab === 'numbers'" class="content-card">
      <div class="card-head">
        <h3>
          单号生成规则
          <InfoTip content="已有单据编号保持不变；保存后仅影响下一张新单。相同前缀下待用号不能向前回退，以避免重复。" />
        </h3>
        <el-button
          type="primary"
          :disabled="!isAdmin"
          :loading="savingNumbers"
          @click="saveNumberRules"
        >
          保存单号规则
        </el-button>
      </div>
      <el-table :data="numberRules" row-key="document_type">
        <el-table-column prop="label" label="业务单据" min-width="150" />
        <el-table-column label="前缀" min-width="170">
          <template #default="{ row }">
            <el-input
              v-model="row.prefix"
              :disabled="!isAdmin"
              maxlength="12"
              placeholder="可留空"
              @input="row.prefix = String(row.prefix).toUpperCase().replace(/[^A-Z0-9-]/g, '')"
            />
          </template>
        </el-table-column>
        <el-table-column label="待用号码" min-width="180">
          <template #default="{ row }">
            <el-input-number
              v-model="row.next_number"
              :disabled="!isAdmin"
              :min="1"
              :max="9999999999"
              :controls="false"
              style="width: 100%"
            />
          </template>
        </el-table-column>
        <el-table-column label="数字位数" width="150">
          <template #default="{ row }">
            <el-select v-model="row.digits" :disabled="!isAdmin">
              <el-option v-for="digits in 8" :key="digits + 2" :label="`${digits + 2} 位`" :value="digits + 2" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="下一张预览" min-width="190">
          <template #default="{ row }">
            <span class="number-preview">{{ numberPreview(row) }}</span>
          </template>
        </el-table-column>
      </el-table>
      <p v-if="!isAdmin" class="permission-note">当前账号可查看规则；只有管理员可以修改。</p>
    </section>

    <section v-else-if="activeTab === 'roles'" class="content-card">
      <div class="card-head">
        <h3>
          角色权限边界
          <InfoTip content="权限由后端统一校验；隐藏按钮只能改善界面，不能替代接口鉴权。" />
        </h3>
      </div>
      <el-table :data="rolePermissions" row-key="role">
        <el-table-column prop="label" label="身份" width="130">
          <template #default="{ row }"><el-tag>{{ row.label }}</el-tag></template>
        </el-table-column>
        <el-table-column label="查看" width="100" align="center">
          <template #default="{ row }"><el-icon :color="row.read ? '#22a06b' : '#c0c4cc'"><Check /></el-icon></template>
        </el-table-column>
        <el-table-column label="业务操作" width="120" align="center">
          <template #default="{ row }"><el-icon :color="row.business_write ? '#22a06b' : '#c0c4cc'"><Check v-if="row.business_write" /><Close v-else /></el-icon></template>
        </el-table-column>
        <el-table-column label="系统管理" width="120" align="center">
          <template #default="{ row }"><el-icon :color="row.system_admin ? '#22a06b' : '#c0c4cc'"><Check v-if="row.system_admin" /><Close v-else /></el-icon></template>
        </el-table-column>
        <el-table-column prop="description" label="权限说明" min-width="360" />
      </el-table>
    </section>

    <section v-else class="content-card navigation-card">
      <div class="card-head">
        <h3>
          我的侧栏布局
          <InfoTip content="拖动分组或二级菜单调整顺序；工作台和设置为固定入口，不能隐藏。此设置跟随当前账号。" />
        </h3>
        <div>
          <el-button @click="resetNavigation">恢复默认</el-button>
          <el-button type="primary" :loading="savingNavigation" @click="saveNavigation">保存布局</el-button>
        </div>
      </div>
      <div class="navigation-list">
        <article
          v-for="(root, rootIndex) in navigationItems"
          :key="root.path"
          class="navigation-group"
          draggable="true"
          @dragstart="draggedRoot = rootIndex"
          @dragover.prevent
          @drop="dropRoot(rootIndex)"
        >
          <header>
            <el-icon class="drag-handle"><Rank /></el-icon>
            <strong>{{ root.title }}</strong>
            <el-switch
              v-model="root.visible"
              :disabled="root.protected"
              active-text="显示"
              inactive-text="隐藏"
            />
          </header>
          <div v-if="root.children.length" class="navigation-children">
            <div
              v-for="(child, childIndex) in root.children"
              :key="child.path"
              draggable="true"
              @dragstart.stop="startChildDrag(root.path, childIndex)"
              @dragover.prevent.stop
              @drop.stop="dropChild(root, childIndex)"
            >
              <el-icon><Rank /></el-icon>
              <span>{{ child.title }}</span>
            </div>
          </div>
        </article>
      </div>
    </section>
  </div>
</template>

<style scoped>
.settings-tabs {
  padding: 0 20px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  background: var(--el-bg-color);
}
.settings-tabs :deep(.el-tabs__header) { margin: 0; }
.settings-tabs :deep(.el-tabs__content) { display: none; }
.workflow-track {
  display: grid;
  grid-template-columns: repeat(6, minmax(130px, 1fr));
  gap: 0;
  padding: 24px;
}
.workflow-step {
  position: relative;
  display: grid;
  min-height: 116px;
  padding: 18px 18px 16px;
  color: inherit;
  border: 1px solid var(--el-border-color-lighter);
  border-right: 0;
  background: color-mix(in srgb, var(--el-color-primary) 3%, var(--el-bg-color));
  transition: transform .18s ease, background .18s ease;
}
.workflow-step:first-child { border-radius: 8px 0 0 8px; }
.workflow-step:last-child { border-right: 1px solid var(--el-border-color-lighter); border-radius: 0 8px 8px 0; }
.workflow-step:hover { z-index: 2; transform: translateY(-3px); background: color-mix(in srgb, var(--el-color-primary) 8%, var(--el-bg-color)); }
.workflow-step > span { color: var(--el-color-primary); font-family: ui-monospace, Consolas, monospace; font-size: 12px; }
.workflow-step strong { align-self: end; font-size: 17px; }
.workflow-step small { margin-top: 6px; color: var(--el-text-color-secondary); line-height: 1.45; }
.exception-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; padding: 0 24px 24px; }
.exception-grid article { display: grid; gap: 5px; padding: 14px 16px; border-left: 3px solid var(--el-color-warning); background: var(--el-fill-color-light); }
.exception-grid span { color: var(--el-text-color-secondary); font-size: 13px; }
.number-preview { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-weight: 700; letter-spacing: .04em; }
.permission-note { margin: 16px 24px 22px; color: var(--el-text-color-secondary); font-size: 13px; }
.navigation-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; padding: 20px 24px 24px; }
.navigation-group { overflow: hidden; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; background: var(--el-bg-color); }
.navigation-group > header { display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 10px; padding: 13px 15px; background: var(--el-fill-color-light); cursor: grab; }
.drag-handle, .navigation-children .el-icon { color: var(--el-text-color-placeholder); cursor: grab; }
.navigation-children { display: grid; padding: 7px 14px 12px 38px; }
.navigation-children > div { display: flex; align-items: center; gap: 9px; min-height: 36px; padding: 0 8px; border-bottom: 1px dashed var(--el-border-color-lighter); cursor: grab; }
.navigation-children > div:last-child { border-bottom: 0; }
@media (max-width: 1050px) {
  .workflow-track { grid-template-columns: repeat(3, 1fr); gap: 10px; }
  .workflow-step, .workflow-step:first-child, .workflow-step:last-child { border: 1px solid var(--el-border-color-lighter); border-radius: 8px; }
}
@media (max-width: 720px) {
  .workflow-track, .exception-grid, .navigation-list { grid-template-columns: 1fr; }
}
</style>
