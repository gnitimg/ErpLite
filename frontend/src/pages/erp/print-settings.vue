<script setup lang="ts">
import { ElMessage } from "element-plus"
import { computed, onMounted, reactive, ref } from "vue"
import { api, formatTime, useLiveRefresh } from "./api"
import { applyPrintSettings, defaultPrintSettings } from "./print"
import InfoTip from "./components/InfoTip.vue"

const presets = [
  { value: "A4_LANDSCAPE", label: "A4 横向", width: 297, height: 210 },
  { value: "A4_PORTRAIT", label: "A4 纵向", width: 210, height: 297 },
  { value: "A5_LANDSCAPE", label: "A5 横向", width: 210, height: 148 },
  { value: "A5_PORTRAIT", label: "A5 纵向", width: 148, height: 210 },
  { value: "CONTINUOUS_HALF", label: "二等分连续纸 241 × 140 mm", width: 241, height: 140 },
  { value: "CONTINUOUS_THIRD", label: "三等分连续纸 241 × 93 mm", width: 241, height: 93 },
  { value: "CUSTOM", label: "自定义尺寸", width: 297, height: 210 }
]
const loading = ref(false)
const saving = ref(false)
const form = reactive({
  ...defaultPrintSettings,
  updated_at: ""
})
const previewStyle = computed(() => {
  const ratio = Number(form.width_mm) / Math.max(Number(form.height_mm), 1)
  return ratio >= 1
    ? { width: "100%", aspectRatio: String(ratio) }
    : { height: "360px", aspectRatio: String(ratio) }
})

function choosePreset(value: string) {
  form.paper_preset = value
  const preset = presets.find(item => item.value === value)
  if (preset && value !== "CUSTOM") {
    form.width_mm = preset.width
    form.height_mm = preset.height
  }
}

function useCustomSize() {
  form.paper_preset = "CUSTOM"
}

function swapDimensions() {
  const width = form.width_mm
  form.width_mm = form.height_mm
  form.height_mm = width
  form.paper_preset = "CUSTOM"
}

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    Object.assign(form, await api("/api/system/print-settings"))
    applyPrintSettings(form)
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    if (!silent) loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    Object.assign(form, await api("/api/system/print-settings", {
      method: "PUT",
      body: JSON.stringify({
        paper_preset: form.paper_preset,
        width_mm: Number(form.width_mm),
        height_mm: Number(form.height_mm)
      })
    }))
    applyPrintSettings(form)
    ElMessage.success("打印尺寸已保存，入库单和出库单将统一使用该尺寸")
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
  <div class="erp-page print-settings-page">
    <div class="page-toolbar">
      <div />
      <div class="toolbar-right">
        <el-button :loading="loading" @click="() => load()"><el-icon><Refresh /></el-icon>刷新</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存设置</el-button>
      </div>
    </div>

    <div class="settings-layout" v-loading="loading">
      <section class="content-card settings-card">
        <div class="card-head">
          <h3>
            打印设置
            <InfoTip content="设置全局应用于出入库单；打印机驱动的纸张尺寸应保持一致，页面会按宽度等比缩放。" />
          </h3>
        </div>
        <el-form label-position="top" class="settings-form">
          <el-form-item label="常用单据尺寸">
            <el-select :model-value="form.paper_preset" style="width: 100%" @change="choosePreset">
              <el-option v-for="item in presets" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <div class="dimension-fields">
            <el-form-item label="宽度（mm）" required>
              <el-input-number v-model="form.width_mm" :min="50" :max="500" :precision="1" :controls="false" @change="useCustomSize" />
            </el-form-item>
            <el-button class="swap-button" plain @click="swapDimensions"><el-icon><Switch /></el-icon>宽高互换</el-button>
            <el-form-item label="高度（mm）" required>
              <el-input-number v-model="form.height_mm" :min="50" :max="500" :precision="1" :controls="false" @change="useCustomSize" />
            </el-form-item>
          </div>
          <p class="field-help">网页会以 A4 横向单据为基础等比缩放，表格、字号和间距比例保持不变；浏览器打印页边距固定为 0，由单据内部保留安全留白。</p>
          <p v-if="form.updated_at" class="updated-at">最近更新：{{ formatTime(form.updated_at) }}</p>
        </el-form>
      </section>

      <aside class="content-card preview-card">
        <div class="card-head"><h3>尺寸预览</h3><span>{{ form.width_mm }} × {{ form.height_mm }} mm</span></div>
        <div class="preview-stage">
          <div class="paper-preview" :style="previewStyle">
            <div class="preview-title">入 库 单</div>
            <div class="preview-meta"><i /><i /><i /></div>
            <div class="preview-table"><b v-for="row in 5" :key="row" /></div>
            <div class="preview-signatures"><i /><i /><i /></div>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.page-toolbar .el-alert { min-width: min(680px, 62vw); }
.settings-layout { display: grid; grid-template-columns: minmax(420px, .9fr) minmax(420px, 1.1fr); gap: 18px; align-items: start; }
.settings-form { padding: 24px; }
.dimension-fields { display: grid; grid-template-columns: 1fr auto 1fr; gap: 14px; align-items: end; }
.dimension-fields :deep(.el-input-number) { width: 100%; }
.swap-button { margin-bottom: 18px; }
.field-help, .updated-at { color: var(--el-text-color-secondary); font-size: 13px; line-height: 1.7; }
.updated-at { margin-top: 18px; }
.preview-card { position: sticky; top: 20px; }
.preview-stage { min-height: 430px; padding: 28px; display: flex; align-items: center; justify-content: center; background: var(--el-fill-color-lighter); }
.paper-preview { max-width: 100%; max-height: 360px; padding: 7%; display: flex; flex-direction: column; border: 1px solid var(--el-border-color); background: #fff; box-shadow: 0 14px 34px rgb(0 0 0 / 12%); color: #243247; }
.preview-title { text-align: center; font-size: clamp(12px, 2vw, 22px); font-weight: 700; letter-spacing: .35em; }
.preview-meta { display: grid; grid-template-columns: 2fr 1fr 1fr; gap: 5%; margin: 8% 0 5%; }
.preview-meta i, .preview-signatures i { display: block; height: 3px; background: #cbd3df; }
.preview-table { flex: 1; border: 1px solid #b8c2d0; }
.preview-table b { display: block; height: 18%; border-bottom: 1px solid #d9dee7; }
.preview-signatures { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8%; margin-top: 7%; }
@media (max-width: 1000px) { .settings-layout { grid-template-columns: 1fr; } .preview-card { position: static; } }
</style>
