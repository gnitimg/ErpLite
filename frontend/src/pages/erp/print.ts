import { reactive } from "vue"
import { api } from "./api"

export interface PrintSettings {
  paper_preset: string
  width_mm: number
  height_mm: number
  header_mode: "none" | "name" | "logo" | "both"
  company_name: string
  logo: string
}

export const defaultPrintSettings: PrintSettings = {
  paper_preset: "A4_LANDSCAPE",
  width_mm: 297,
  height_mm: 210,
  header_mode: "none",
  company_name: "",
  logo: ""
}

/** 当前打印页眉品牌（厂名/Logo），由打印设置驱动，单据模板直接渲染。 */
export const printBrand = reactive({
  mode: "none" as PrintSettings["header_mode"],
  company_name: "",
  logo: ""
})

const DESIGN_WIDTH_MM = 277

export function applyPrintSettings(settings: PrintSettings) {
  const width = Math.max(50, Number(settings.width_mm) || 297)
  const height = Math.max(50, Number(settings.height_mm) || 210)
  const margin = width < 120 || height < 120 ? 4 : 8
  const scale = Math.min(1, Math.max((width - margin * 2) / DESIGN_WIDTH_MM, 0.2))
  const root = document.documentElement
  root.style.setProperty("--erp-print-page-width", `${width}mm`)
  root.style.setProperty("--erp-print-page-height", `${height}mm`)
  root.style.setProperty("--erp-print-margin", `${margin}mm`)
  root.style.setProperty("--erp-print-scale", String(scale))

  printBrand.mode = settings.header_mode || "none"
  printBrand.company_name = settings.company_name || ""
  printBrand.logo = settings.logo || ""

  let pageStyle = document.querySelector<HTMLStyleElement>("#erp-print-page-size")
  if (!pageStyle) {
    pageStyle = document.createElement("style")
    pageStyle.id = "erp-print-page-size"
    document.head.appendChild(pageStyle)
  }
  pageStyle.textContent = `@page { size: ${width}mm ${height}mm; margin: 0; }`
}

/** 页眉是否显示厂名 / Logo（供模板计算布局）。 */
export const showBrandName = () => printBrand.mode === "name" || printBrand.mode === "both"
export const showBrandLogo = () => (printBrand.mode === "logo" || printBrand.mode === "both") && Boolean(printBrand.logo)

export async function printWithSavedSize(printTarget?: HTMLElement) {
  let settings: PrintSettings = defaultPrintSettings
  try {
    settings = { ...defaultPrintSettings, ...await api<PrintSettings>("/api/system/print-settings") }
  } catch {
    // 数据库暂不可用时仍允许按默认 A4 横向打印。
  }
  applyPrintSettings(settings)

  const previousTitle = document.title
  const restoreTitle = () => {
    document.title = previousTitle
  }
  document.title = "\u200B"

  if (!printTarget) {
    window.addEventListener("afterprint", restoreTitle, { once: true })
    requestAnimationFrame(() => window.print())
    return
  }

  // 弹层（抽屉/对话框）里的单据会受上层定位元素与内联宽度影响而偏移、裁切；
  // 打印期间把单据节点搬到 body 下，让它以打印页为定位基准，结束后放回原处。
  const parent = printTarget.parentNode
  if (!parent) {
    window.addEventListener("afterprint", restoreTitle, { once: true })
    requestAnimationFrame(() => window.print())
    return
  }
  const marker = document.createComment("erp-print-anchor")
  parent.insertBefore(marker, printTarget)
  document.body.appendChild(printTarget)

  let restored = false
  const restore = () => {
    if (restored || !marker.parentNode) return
    restored = true
    parent.insertBefore(printTarget, marker)
    marker.remove()
    restoreTitle()
  }
  window.addEventListener("afterprint", restore, { once: true })
  requestAnimationFrame(() => window.print())
  // 兜底：个别环境 afterprint 不触发，避免单据留在 body 下。
  setTimeout(restore, 60000)
}
