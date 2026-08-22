<script setup lang="ts">
import { LayoutModeEnum } from "@@/constants/app-key"
import { useTheme, type ThemeName } from "@@/composables/useTheme"
import { removeLayoutsConfig, setActiveThemeName } from "@@/utils/local-storage"
import { useSettingsStore } from "@/pinia/stores/settings"

const settingsStore = useSettingsStore()
const { themeList, activeThemeName, initTheme, setTheme } = useTheme()
initTheme()

const themeMeta: Record<ThemeName, { label: string; sidebar: string; surface: string; primary: string }> = {
  normal: { label: "清爽浅色", sidebar: "#0b2135", surface: "#f4f6f8", primary: "#409eff" },
  dark: { label: "深色护眼", sidebar: "#141414", surface: "#202124", primary: "#409eff" },
  "dark-blue": { label: "深蓝专业", sidebar: "#071a2d", surface: "#0e2439", primary: "#2f8cff" },
}

const switches = [
  { key: "showTagsView", label: "显示页面标签" },
  { key: "showLogo", label: "显示系统标识" },
  { key: "fixedHeader", label: "固定顶部栏" },
  { key: "showFooter", label: "显示页脚" },
  { key: "showNotify", label: "显示消息入口" },
  { key: "showScreenfull", label: "显示全屏入口" },
  { key: "showSearchMenu", label: "显示菜单搜索" },
] as const

function chooseTheme(event: MouseEvent, name: ThemeName) {
  setTheme(event, name)
}

function resetTheme() {
  removeLayoutsConfig()
  setActiveThemeName("normal")
  location.reload()
}
</script>

<template>
  <div class="erp-page theme-page">
    <div class="theme-heading">
      <div><h2>主题设置</h2></div>
      <el-button @click="$router.back()"><el-icon><ArrowLeft /></el-icon>返回</el-button>
    </div>

    <div class="theme-layout">
      <div class="theme-settings">
        <section class="content-card theme-section">
          <div class="card-head"><h3>外观主题</h3></div>
          <div class="theme-options">
            <button v-for="theme in themeList" :key="theme.name" class="theme-option" :class="{ active: activeThemeName === theme.name }" @click="chooseTheme($event, theme.name)">
              <span class="theme-swatch" :style="{ background: themeMeta[theme.name].surface }"><i :style="{ background: themeMeta[theme.name].sidebar }" /><b :style="{ background: themeMeta[theme.name].primary }" /></span>
              <strong>{{ themeMeta[theme.name].label }}</strong><small>{{ theme.title }}</small>
            </button>
          </div>
        </section>

        <section class="content-card theme-section">
          <div class="card-head"><h3>导航布局</h3></div>
          <el-radio-group v-model="settingsStore.layoutMode" class="layout-choices">
            <el-radio-button :value="LayoutModeEnum.Left">左侧导航</el-radio-button>
            <el-radio-button :value="LayoutModeEnum.Top">顶部导航</el-radio-button>
            <el-radio-button :value="LayoutModeEnum.LeftTop">混合导航</el-radio-button>
          </el-radio-group>
        </section>

        <section class="content-card theme-section">
          <div class="card-head"><h3>界面元素</h3></div>
          <div class="theme-switches"><label v-for="item in switches" :key="item.key"><span>{{ item.label }}</span><el-switch v-model="settingsStore[item.key]" /></label></div>
          <el-button class="reset-theme" plain type="danger" @click="resetTheme"><el-icon><RefreshLeft /></el-icon>恢复默认设置</el-button>
        </section>
      </div>

      <aside class="content-card theme-preview-card">
        <div class="card-head"><h3>实时预览</h3></div>
        <div class="theme-preview" :class="`layout-${settingsStore.layoutMode}`" :style="{ '--preview-sidebar': themeMeta[activeThemeName].sidebar, '--preview-surface': themeMeta[activeThemeName].surface, '--preview-primary': themeMeta[activeThemeName].primary }">
          <div class="preview-top"><i /><span /><span /><b /></div>
          <div class="preview-body"><nav><strong>ErpLite</strong><i class="active" /><i /><i /><i /></nav><main><div class="preview-title"><span /><button /></div><div class="preview-metrics"><i /><i /><i /></div><div class="preview-table"><b /><span v-for="n in 5" :key="n" /></div></main></div>
        </div>
      </aside>
    </div>
  </div>
</template>

<style lang="scss" scoped>
.theme-heading { display:flex; align-items:flex-start; justify-content:space-between; margin-bottom:18px; h2{margin:0;font-size:22px} p{margin:7px 0 0;color:var(--el-text-color-secondary);font-size:13px} }
.theme-layout { display:grid; grid-template-columns:minmax(0,1fr) minmax(360px,.78fr); gap:18px; align-items:start; }
.theme-settings { display:grid; gap:18px; }
.theme-section { padding-bottom:20px; }
.theme-options { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; padding:20px; }
.theme-option { padding:12px; border:1px solid var(--el-border-color); background:var(--el-bg-color); border-radius:9px; text-align:left; cursor:pointer; color:var(--el-text-color-primary); &.active{border-color:var(--el-color-primary);box-shadow:0 0 0 2px var(--el-color-primary-light-8)} strong,small{display:block} strong{margin-top:10px;font-size:13px} small{margin-top:3px;color:var(--el-text-color-secondary)} }
.theme-swatch { height:74px; display:block; position:relative; border-radius:6px; overflow:hidden; border:1px solid rgb(127 127 127 / 16%); i{position:absolute;inset:0 auto 0 0;width:28%;} b{position:absolute;left:36%;top:18px;width:45%;height:8px;border-radius:4px;} }
.layout-choices { padding:20px; }
.theme-switches { padding:10px 20px 4px; display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:0 28px; label{display:flex;align-items:center;justify-content:space-between;padding:10px 0;border-bottom:1px solid var(--el-border-color-lighter);font-size:13px;} }
.reset-theme { margin:16px 20px 0; }
.theme-preview-card { position:sticky; top:20px; }
.theme-preview { margin:20px; height:390px; overflow:hidden; border-radius:10px; background:var(--preview-surface); box-shadow:0 15px 42px rgb(0 0 0 / 12%); }
.preview-top { height:42px; display:flex;align-items:center;gap:8px;padding:0 14px;background:#fff; i{width:70px;height:8px;background:#dbe0e5;border-radius:5px} span{width:8px;height:8px;border-radius:50%;background:#dbe0e5} span:first-of-type{margin-left:auto} b{width:24px;height:24px;border-radius:50%;background:var(--preview-primary)} }
.preview-body { display:flex;height:calc(100% - 42px); nav{width:92px;padding:18px 10px;background:var(--preview-sidebar);strong{color:#fff;font-size:10px} i{display:block;height:8px;margin-top:20px;border-radius:4px;background:rgb(255 255 255 / 24%)} i.active{background:var(--preview-primary)}} main{flex:1;padding:20px;} }
.preview-title { display:flex;justify-content:space-between; span{width:100px;height:11px;background:rgb(127 127 127 / 25%);border-radius:5px} button{width:55px;height:20px;border:0;border-radius:4px;background:var(--preview-primary)} }
.preview-metrics { display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:18px;i{height:62px;background:rgb(255 255 255 / 72%);border-radius:6px;} }
.preview-table { margin-top:12px;padding:12px;background:rgb(255 255 255 / 76%);border-radius:6px;b{display:block;width:38%;height:8px;background:rgb(127 127 127 / 22%);border-radius:4px}span{display:block;height:1px;margin-top:28px;background:rgb(127 127 127 / 18%)} }
.layout-top .preview-body, .layout-left-top .preview-body { position:relative; padding-top:26px; &::before{content:"";position:absolute;inset:0 0 auto 0;height:26px;background:var(--preview-sidebar)} }
.layout-top .preview-body nav { display:none; }
.preview-note { margin:0 20px 20px;color:var(--el-text-color-secondary);font-size:12px;line-height:1.7; }
@media(max-width:1000px){.theme-layout{grid-template-columns:1fr}.theme-preview-card{position:static}.theme-options{grid-template-columns:1fr}.theme-switches{grid-template-columns:1fr}}
</style>
