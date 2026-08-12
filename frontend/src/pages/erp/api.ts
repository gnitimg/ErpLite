export async function api<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  })
  if (!response.ok) {
    let message = `请求失败（${response.status}）`
    try {
      const data = await response.json()
      message = typeof data.detail === 'string' ? data.detail : message
    } catch {
      // Keep the HTTP fallback message.
    }
    throw new Error(message)
  }
  return response.status === 204 ? (undefined as T) : response.json()
}

export const money = (value: number | string = 0) =>
  new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY' }).format(Number(value))

export const qty = (value: number | string = 0) =>
  new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 3 }).format(Number(value))

export const productQty = (value: number | string = 0) =>
  new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 }).format(Number(value))

export const formatTime = (value?: string) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-'

export const txLabels: Record<string, string> = {
  OPENING: '期初库存', PURCHASE_IN: '采购入库', MANUAL_IN: '成品入库', ASSEMBLY_IN: '生产入库', MANUAL_OUT: '手工出库', SALE_OUT: '客单出库',
}

export const statusMap: Record<string, { label: string; type: string }> = {
  DRAFT: { label: '草稿', type: 'info' },
  CONFIRMED: { label: '检查库存', type: 'primary' },
  WAITING_MATERIALS: { label: '缺料待采购', type: 'warning' },
  READY_TO_SHIP: { label: '待出库', type: 'success' },
  FULFILLED: { label: '已出库', type: 'success' },
  CANCELLED: { label: '已取消', type: 'danger' },
}
