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
const MAX_LOGO_BYTES = 200 * 1024
const headerModeOptions = [
  { value: "none", label: "不显示" },
  { value: "name", label: "仅厂名" },
  { value: "logo", label: "仅 Logo" },
  { value: "both", label: "厂名 + Logo" }
]

function chooseHeaderMode(value: string | number | boolean | undefined) {
  form.header_mode = (value as typeof form.header_mode) || "none"
  if ((value === "name" || value === "both") && !form.company_name.trim()) {
    ElMessage.info("请填写厂名，页眉才会显示")
  }
}

function onLogoFile(file: File) {
  if (!file.type.startsWith("image/")) {
    ElMessage.error("请选择图片文件（PNG/JPG/SVG）")
    return false
  }
  if (file.size > MAX_LOGO_BYTES) {
    ElMessage.error("Logo 图片不能超过 200KB，请压缩后再上传")
    return false
  }
  const reader = new FileReader()
  reader.onload = () => {
    form.logo = String(reader.result)
    if (form.header_mode === "none") form.header_mode = "logo"
  }
  reader.readAsDataURL(file)
  return false
}
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
        height_mm: Number(form.height_mm),
        header_mode: form.header_mode,
        company_name: form.company_name,
        logo: form.logo
      })
    }))
    applyPrintSettings(form)
    ElMessage.success("打印设置已保存，入库单和出库单将统一使用该格式")
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
          <el-divider />
          <el-form-item label="单据页眉（左上角）">
            <el-radio-group :model-value="form.header_mode" @change="chooseHeaderMode">
              <el-radio-button v-for="item in headerModeOptions" :key="item.value" :value="item.value">
                {{ item.label }}
              </el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item v-if="form.header_mode === 'name' || form.header_mode === 'both'" label="厂名">
            <el-input v-model="form.company_name" maxlength="100" show-word-limit placeholder="显示在单据左上角" />
          </el-form-item>
          <el-form-item v-if="form.header_mode === 'logo' || form.header_mode === 'both'" label="Logo 图片">
            <div class="logo-field">
              <img v-if="form.logo" :src="form.logo" class="logo-preview" alt="Logo 预览">
              <el-upload
                :auto-upload="false"
                :show-file-list="false"
                accept="image/*"
                :on-change="(file: any) => onLogoFile(file.raw)"
              >
                <el-button>{{ form.logo ? '更换 Logo' : '上传 Logo' }}</el-button>
              </el-upload>
              <el-button v-if="form.logo" text type="danger" @click="form.logo = ''">移除</el-button>
            </div>
            <p class="field-help">支持 PNG/JPG/SVG，原始图片不超过 200KB；打印时按比例缩放显示。</p>
          </el-form-item>
          <p v-if="form.updated_at" class="updated-at">最近更新：{{ formatTime(form.updated_at) }}</p>
        </el-form>
      </section>

      <aside class="content-card preview-card">
        <div class="card-head"><h3>尺寸预览</h3><span>{{ form.width_mm }} × {{ form.height_mm }} mm</span></div>
        <div class="preview-stage">
          <div class="paper-preview" :style="previewStyle">
            <div class="pv-head">
              <div class="pv-brand">
                <img v-if="form.logo && (form.header_mode === 'logo' || form.header_mode === 'both')" :src="form.logo" alt="">
                <span v-if="form.company_name && (form.header_mode === 'name' || form.header_mode === 'both')">{{ form.company_name }}</span>
              </div>
              <div class="pv-title">入 库 单</div>
              <div class="pv-no">NO. 编号</div>
            </div>
            <div class="pv-info"><span>客户：________</span><span class="pv-date">年 月 日</span></div>
            <table class="pv-table">
              <thead><tr><th class="w-idx">序号</th><th>物料及规格型号</th><th class="w-qty">数量</th><th class="w-unit">单位</th><th class="w-price">单价</th><th class="w-sub">小计</th><th>备注</th></tr></thead>
              <tbody><tr v-for="row in 5" :key="row"><td :class="{ idx: true }">{{ row }}</td><td /><td /><td /><td /><td /><td /></tr></tbody>
              <tfoot><tr><td colspan="2" class="pv-total">合计金额（人民币）　¥0.00</td><td class="pv-remark" colspan="5">备注：</td></tr></tfoot>
            </table>
            <div class="pv-sign"><span>制单：________</span><span>仓管：________</span><span>审核：________</span></div>
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
.logo-field { display: flex; align-items: center; gap: 12px; }
.logo-preview { max-height: 48px; max-width: 160px; object-fit: contain; border: 1px solid var(--el-border-color-lighter); border-radius: 4px; padding: 2px; background: #fff; }
.updated-at { margin-top: 18px; }
.preview-card { position: sticky; top: 20px; }
.preview-stage { min-height: 430px; padding: 28px; display: flex; align-items: center; justify-content: center; background: var(--el-fill-color-lighter); }
.paper-preview { max-width: 100%; max-height: 360px; padding: 7%; display: flex; flex-direction: column; border: 1px solid var(--el-border-color); background: #fff; box-shadow: 0 14px 34px rgb(0 0 0 / 12%); color: #243247; }
/* 预览与真实单据同构：6 等份页眉、7 列表格、合计行、签栏 */
.pv-head { display: grid; grid-template-columns: repeat(12, 1fr); align-items: center; min-height: 34px; }
.pv-brand { grid-column: 1 / 4; justify-self: start; display: flex; align-items: center; gap: 4px; min-width: 0; overflow: hidden; }
.pv-brand img { max-height: 26px; max-width: 70px; object-fit: contain; }
.pv-brand span { font-size: 12px; font-weight: 700; white-space: nowrap; }
.pv-title { grid-column: 5 / 9; text-align: center; font-size: clamp(14px, 1.8vw, 22px); font-weight: 700; letter-spacing: .3em; text-indent: .3em; }
.pv-no { grid-column: 11 / 13; justify-self: start; font-size: 10px; }
.pv-info { display: flex; justify-content: space-between; padding: 4px 0 8px; border-bottom: 1px solid #999; font-size: 11px; }
.pv-table { width: 100%; border-collapse: collapse; table-layout: fixed; border: 2px solid #999; }
.pv-table th, .pv-table td { border: 1px solid #999; padding: 3px 4px; font-size: 10px; font-weight: 400; text-align: center; }
.pv-table th { font-weight: 700; }
.pv-table tbody td { height: 22px; }
.pv-table .w-idx { width: 8%; }
.pv-table .w-qty { width: 11%; }
.pv-table .w-unit { width: 8%; }
.pv-table .w-price { width: 11%; }
.pv-table .w-sub { width: 11%; }
.pv-table td.idx { font-size: 10px; color: #333; }
.pv-table tfoot td { height: 22px; font-weight: 700; text-align: left; }
.pv-sign { display: flex; justify-content: space-between; margin-top: 12%; font-size: 11px; }
@media (max-width: 1000px) { .settings-layout { grid-template-columns: 1fr; } .preview-card { position: static; } }
</style>
