export async function api<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {})
    }
  })
  if (!response.ok) {
    let message = `请求失败（${response.status}）`
    try {
      const data = await response.json()
      message = typeof data.detail === "string" ? data.detail : message
    } catch {
      // Keep the HTTP fallback message.
    }
    throw new Error(message)
  }
  return response.status === 204 ? (undefined as T) : response.json()
}

export function money(value: number | string = 0) {
  return new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY" }).format(Number(value))
}

export function compactQty(value: number | string = 0, maximumFractionDigits = 3) {
  const amount = Math.abs(Number(value) || 0)
  if (amount >= 10000) {
    return `${new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 3 }).format(amount / 10000)}万`
  }
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits }).format(amount)
}

export const qty = (value: number | string = 0) => compactQty(value, 3)

export const productQty = (value: number | string = 0) => compactQty(value, 0)

export function stockQty(value: number | string = 0, integer = false) {
  return compactQty(Math.max(Number(value) || 0, 0), integer ? 0 : 3)
}

export const formatTime = (value?: string) => value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "-"

export const txLabels: Record<string, string> = {
  OPENING: "期初库存",
  PURCHASE_IN: "采购入库",
  MANUAL_IN: "成品入库",
  ASSEMBLY_IN: "生产入库",
  MANUAL_OUT: "手工出库",
  SALE_OUT: "客单出库",
  SAMPLE_ADJUST: "样品调整"
}

export const statusMap: Record<string, { label: string, type: string }> = {
  DRAFT: { label: "草稿", type: "info" },
  CONFIRMED: { label: "检查库存", type: "primary" },
  WAITING_MATERIALS: { label: "缺料待采购", type: "warning" },
  READY_TO_SHIP: { label: "待出库", type: "success" },
  FULFILLED: { label: "已出库", type: "success" },
  CANCELLED: { label: "已取消", type: "danger" }
}
