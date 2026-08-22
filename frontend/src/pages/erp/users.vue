<script setup lang="ts">
import { ElMessage, ElMessageBox } from "element-plus"
import { onMounted, ref, reactive } from "vue"
import { api, formatTime, useLiveRefresh } from "./api"
import ListToolbar from "./components/ListToolbar.vue"

interface UserRow {
  id: number
  username: string
  display_name: string
  role: string
  active: boolean
  created_at: string
}

const loading = ref(false)
const keyword = ref("")
const rows = ref<UserRow[]>([])
const dialog = ref(false)
const editing = ref<UserRow | null>(null)
const form = reactive({ username: "", password: "", display_name: "", role: "OPERATOR" })

const roleLabels: Record<string, string> = { ADMIN: "管理员", OPERATOR: "操作员", VIEWER: "只读" }

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    rows.value = await api("/api/users")
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    if (!silent) loading.value = false
  }
}

function openCreate() {
  editing.value = null
  form.username = ""
  form.password = ""
  form.display_name = ""
  form.role = "OPERATOR"
  dialog.value = true
}

function openEdit(row: UserRow) {
  editing.value = row
  form.username = row.username
  form.password = ""
  form.display_name = row.display_name
  form.role = row.role
  dialog.value = true
}

async function save() {
  try {
    if (editing.value) {
      await api(`/api/users/${editing.value.id}`, {
        method: "PUT",
        body: JSON.stringify({ display_name: form.display_name, role: form.role, active: true, password: form.password || undefined })
      })
      ElMessage.success("用户已更新")
    } else {
      await api("/api/users", {
        method: "POST",
        body: JSON.stringify(form)
      })
      ElMessage.success("用户已创建")
    }
    dialog.value = false
    await load()
  } catch (error: any) {
    ElMessage.error(error.message)
  }
}

async function deactivate(row: UserRow) {
  try {
    await ElMessageBox.confirm(`确认停用用户 ${row.username}？`, "停用用户", { type: "warning" })
    await api(`/api/users/${row.id}`, {
      method: "PUT",
      body: JSON.stringify({ display_name: row.display_name, role: row.role, active: false })
    })
    ElMessage.success("用户已停用")
    await load()
  } catch (error: any) {
    if (error !== "cancel" && error !== "close") ElMessage.error(error.message)
  }
}

onMounted(load)
useLiveRefresh(() => load(true))
</script>

<template>
  <div class="erp-page">
    <ListToolbar v-model="keyword" placeholder="搜索用户名" :loading="loading" @refresh="load">
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>新建用户
      </el-button>
    </ListToolbar>

    <div class="content-card">
      <div class="card-head">
        <h3>用户管理</h3><span>管理系统用户和角色权限</span>
      </div>
      <el-table v-loading="loading" :data="rows.filter(r => r.username.includes(keyword.trim()))" row-key="id" empty-text="暂无用户">
        <el-table-column label="用户名" prop="username" width="160" />
        <el-table-column label="显示名" prop="display_name" min-width="120" />
        <el-table-column label="角色" width="120">
          <template #default="{ row }">
            <el-tag size="small">{{ roleLabels[row.role] || row.role }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.active ? 'success' : 'info'" size="small">{{ row.active ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row as any)">编辑</el-button>
            <el-button v-if="row.active" link type="danger" @click="deactivate(row as any)">停用</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialog" :title="editing ? '编辑用户' : '新建用户'" width="460px">
      <el-form label-position="top">
        <el-form-item label="用户名"><el-input v-model="form.username" :disabled="!!editing" /></el-form-item>
        <el-form-item :label="editing ? '新密码（留空则不变）' : '密码'"><el-input v-model="form.password" type="password" show-password /></el-form-item>
        <el-form-item label="显示名"><el-input v-model="form.display_name" /></el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role" style="width:100%">
            <el-option label="管理员" value="ADMIN" />
            <el-option label="操作员" value="OPERATOR" />
            <el-option label="只读" value="VIEWER" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="save">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>
