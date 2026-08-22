import { api } from "./api"

export interface PrintSettings {
  paper_preset: string
  width_mm: number
  height_mm: number
}

export const defaultPrintSettings: PrintSettings = {
  paper_preset: "A4_LANDSCAPE",
  width_mm: 297,
  height_mm: 210
}

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

  let pageStyle = document.querySelector<HTMLStyleElement>("#erp-print-page-size")
  if (!pageStyle) {
    pageStyle = document.createElement("style")
    pageStyle.id = "erp-print-page-size"
    document.head.appendChild(pageStyle)
  }
  pageStyle.textContent = `@page { size: ${width}mm ${height}mm; margin: 0; }`
}

export async function printWithSavedSize() {
  let settings = defaultPrintSettings
  try {
    settings = await api<PrintSettings>("/api/system/print-settings")
  } catch {
    // 数据库暂不可用时仍允许按默认 A4 横向打印。
  }
  applyPrintSettings(settings)

  const previousTitle = document.title
  const restoreTitle = () => {
    document.title = previousTitle
  }
  document.title = "\u200B"
  window.addEventListener("afterprint", restoreTitle, { once: true })
  requestAnimationFrame(() => window.print())
}
