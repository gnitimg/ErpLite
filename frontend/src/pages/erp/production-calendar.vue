<script setup lang="ts">
import { ElMessage, ElMessageBox } from "element-plus"
import { onMounted, ref, reactive } from "vue"
import { api, formatTime, useLiveRefresh } from "./api"
import ListToolbar from "./components/ListToolbar.vue"

interface CalendarException {
  id: number
  exception_date: string
  is_working_day: boolean
  note: string
}

const loading = ref(false)
const rows = ref<CalendarException[]>([])
const dialog = ref(false)
const form = reactive({ exception_date: "", is_working_day: false, note: "" })

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    rows.value = await api("/api/system/calendar/exceptions")
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    if (!silent) loading.value = false
  }
}

async function save() {
  try {
    await api("/api/system/calendar/exceptions", {
      method: "POST",
      body: JSON.stringify(form)
    })
    ElMessage.success("日历例外已保存")
    dialog.value = false
    await load()
  } catch (error: any) {
    ElMessage.error(error.message)
  }
}

async function remove(row: CalendarException) {
  try {
    await ElMessageBox.confirm(`确认删除 ${row.exception_date} 的日历例外？`, "删除", { type: "warning" })
    await api(`/api/system/calendar/exceptions/${row.id}`, { method: "DELETE" })
    ElMessage.success("已删除")
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
    <ListToolbar :loading="loading" @refresh="load">
      <el-button type="primary" @click="dialog = true; form.exception_date = ''; form.is_working_day = false; form.note = ''">
        <el-icon><Plus /></el-icon>新增例外
      </el-button>
    </ListToolbar>

    <el-alert class="list-page-alert" title="生产日历例外用于标记节假日（不生产）或临时调班日（生产）。排产算法会跳过非工作日。" type="info" :closable="false" show-icon />

    <div class="content-card">
      <div class="card-head">
        <h3>生产日历例外</h3><span>标记节假日和临时调班日</span>
      </div>
      <el-table v-loading="loading" :data="rows" row-key="id" empty-text="暂无日历例外">
        <el-table-column label="日期" prop="exception_date" width="160" />
        <el-table-column label="类型" width="120">
          <template #default="{ row }">
            <el-tag :type="row.is_working_day ? 'success' : 'danger'" size="small">{{ row.is_working_day ? '调班生产' : '休息日' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="备注" prop="note" min-width="200" />
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button link type="danger" @click="remove(row as any)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialog" title="新增日历例外" width="460px">
      <el-form label-position="top">
        <el-form-item label="日期"><el-date-picker v-model="form.exception_date" type="date" value-format="YYYY-MM-DD" style="width:100%" /></el-form-item>
        <el-form-item label="是否生产"><el-switch v-model="form.is_working_day" active-text="生产" inactive-text="休息" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.note" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="save">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>
