<script setup lang="ts">
import { ElMessage } from "element-plus"
import { onMounted, reactive, ref } from "vue"
import { api, formatTime, useLiveRefresh } from "./api"
import InfoTip from "./components/InfoTip.vue"

const loading = ref(false)
const saving = ref(false)
const form = reactive({
  line_count: 1,
  schedule_auto_snap: true,
  updated_at: ""
})

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    Object.assign(form, await api("/api/system/production-settings"))
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    if (!silent) loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    Object.assign(form, await api("/api/system/production-settings", {
      method: "PUT",
      body: JSON.stringify({
        line_count: form.line_count,
        schedule_auto_snap: form.schedule_auto_snap
      })
    }))
    ElMessage.success("基本参数已保存，客单 ETA 已自动重算")
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
      <div />
      <div class="toolbar-right">
        <el-button :loading="loading" @click="() => load()">
          <el-icon><Refresh /></el-icon>刷新
        </el-button>
        <el-button type="primary" :loading="saving" @click="save">
          保存设置
        </el-button>
      </div>
    </div>

    <div class="content-card settings-card" v-loading="loading">
      <div class="card-head">
        <h3>
          基本参数
          <InfoTip content="生产位只作为并行排产槽位；这些全局参数会影响未完成客单的预计完成日期。" />
        </h3>
      </div>
      <el-form label-position="top" class="settings-form">
        <el-form-item label="并行生产线数量" required>
          <el-input-number
            v-model="form.line_count"
            :min="1"
            :max="100"
            :precision="0"
            style="width: 220px"
          />
        </el-form-item>
        <el-form-item label="排产图拖动方式">
          <el-checkbox v-model="form.schedule_auto_snap">
            开启自动吸附
          </el-checkbox>

        </el-form-item>
        <!-- <div class="slot-preview">
          <div class="preview-label">排产槽位预览</div>
          <div class="slot-list">
            <el-tag
              v-for="slot in form.line_count"
              :key="slot"
              effect="plain"
            >
              生产位 {{ slot }}
            </el-tag>
          </div>
        </div>
        <div v-if="form.updated_at" class="updated-at">
          最近更新：{{ formatTime(form.updated_at) }}
        </div> -->
      </el-form>
    </div>
  </div>
</template>

<style scoped>
.page-toolbar .el-alert {
  min-width: min(620px, 60vw);
}

.settings-form {
  max-width: 720px;
  padding: 24px;
}

.field-help,
.updated-at {
  margin-top: 8px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.6;
}

.slot-preview {
  margin-top: 8px;
  padding: 18px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}

.preview-label {
  margin-bottom: 12px;
  color: var(--el-text-color-regular);
  font-weight: 600;
}

.slot-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.updated-at {
  margin-top: 18px;
}
</style>
