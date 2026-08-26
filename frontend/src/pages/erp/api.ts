import { onActivated, onBeforeUnmount, onDeactivated, onMounted } from "vue"
import { getToken, removeToken } from "@/common/utils/local-storage"

const clientId = crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`

function redirectToLogin() {
  const base = import.meta.env.BASE_URL || "/"
  window.location.href = `${base.endsWith("/") ? base : `${base}/`}#/login`
}

export class ApiError extends Error {
  status: number
  detail: unknown

  constructor(status: number, message: string, detail: unknown = null) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.detail = detail
  }
}

async function responseError(response: Response) {
  let detail: unknown = null
  let message = `请求失败（${response.status}）`
  try {
    const data = await response.json()
    detail = data.detail
    if (typeof detail === "string") {
      message = detail
    } else if (detail && typeof detail === "object" && "message" in detail) {
      message = String((detail as { message: unknown }).message)
    }
  } catch {
    // Keep the HTTP fallback message.
  }
  return new ApiError(response.status, message, detail)
}

function bearerHeaders(extra: Record<string, string> = {}) {
  const token = getToken()
  return {
    "X-ERP-Client-ID": clientId,
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...extra
  }
}

export async function api<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...bearerHeaders(),
      ...(options.headers as Record<string, string> | undefined || {})
    }
  })
  if (response.status === 401) {
    removeToken()
    redirectToLogin()
  }
  if (!response.ok) throw await responseError(response)
  return response.status === 204 ? (undefined as T) : response.json()
}

/** 下载文件：带 Bearer 头取回二进制（浏览器直链无法携带 Authorization）。 */
export async function apiBlob(path: string, options: RequestInit = {}): Promise<Blob> {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...bearerHeaders(),
      ...(options.headers as Record<string, string> | undefined || {})
    }
  })
  if (response.status === 401) {
    removeToken()
    redirectToLogin()
  }
  if (!response.ok) throw await responseError(response)
  return response.blob()
}

export interface DataChangeEvent {
  id: number
  source: string
  occurred_at: string
}

const liveRefreshSubscribers = new Set<(event: DataChangeEvent) => void>()
let sharedEventSource: EventSource | undefined

function startEventSource() {
  if (sharedEventSource || !liveRefreshSubscribers.size) return
  sharedEventSource = new EventSource("/api/events")
  sharedEventSource.addEventListener("data-change", (message) => {
    const event = JSON.parse((message as MessageEvent).data) as DataChangeEvent
    if (event.source === clientId) return
    liveRefreshSubscribers.forEach(subscriber => subscriber(event))
  })
}

function stopEventSourceIfIdle() {
  if (liveRefreshSubscribers.size) return
  sharedEventSource?.close()
  sharedEventSource = undefined
}

export function useLiveRefresh(
  refresh: () => void | Promise<void>,
  accepts: (event: DataChangeEvent) => boolean = () => true
) {
  let timer: ReturnType<typeof setTimeout> | undefined
  let refreshing = false
  let pending = false

  const scheduleRefresh = () => {
    if (timer) clearTimeout(timer)
    timer = setTimeout(async () => {
      if (refreshing) {
        pending = true
        return
      }
      refreshing = true
      try {
        await refresh()
      } finally {
        refreshing = false
        if (pending) {
          pending = false
          scheduleRefresh()
        }
      }
    }, 250)
  }

  const subscriber = (event: DataChangeEvent) => {
    if (accepts(event)) scheduleRefresh()
  }
  let subscribed = false
  const subscribe = () => {
    if (subscribed) return
    subscribed = true
    liveRefreshSubscribers.add(subscriber)
    startEventSource()
  }
  const unsubscribe = () => {
    if (!subscribed) return
    subscribed = false
    liveRefreshSubscribers.delete(subscriber)
    stopEventSourceIfIdle()
  }

  onBeforeUnmount(() => {
    if (timer) clearTimeout(timer)
    unsubscribe()
  })
  onMounted(subscribe)
  onActivated(subscribe)
  onDeactivated(unsubscribe)
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

export function formatDate(value?: string) {
  if (!value) return "-"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "-"
  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0")
  ].join("-")
}

export const txLabels: Record<string, string> = {
  OPENING: "期初库存",
  PURCHASE_IN: "采购入库",
  GENERAL_IN: "普通入库",
  MANUAL_IN: "成品入库",
  ASSEMBLY_IN: "生产入库",
  SEMI_FINISHED_IN: "半成品入库",
  PROCESS_OUT: "外协加工出库",
  PROCESS_RETURN_IN: "外协回厂入库",
  SALE_RETURN_IN: "客户退货入库",
  PRODUCTION_OUT: "生产领料出库",
  PRODUCTION_RETURN: "生产退料入库",
  MANUAL_OUT: "手工出库",
  GENERAL_OUT: "普通出库",
  SALE_OUT: "客单出库",
  SAMPLE_ADJUST: "样品调整",
  REVERSAL: "冲销"
}

export const statusMap: Record<string, { label: string, type: string }> = {
  DRAFT: { label: "草稿", type: "info" },
  CONFIRMED: { label: "检查库存", type: "primary" },
  WAITING_MATERIALS: { label: "待生产 / 备货", type: "warning" },
  READY_TO_SHIP: { label: "待出库", type: "success" },
  PARTIALLY_SHIPPED: { label: "部分出库", type: "warning" },
  FULFILLED: { label: "已出库", type: "success" },
  CANCELLED: { label: "已取消", type: "danger" }
}
