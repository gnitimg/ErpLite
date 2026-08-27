const FIELD_LABELS: Record<string, string> = {
  prefix: "前缀",
  next_number: "待用号码",
  digits: "数字位数",
  rules: "单号规则",
  username: "用户名",
  password: "密码",
  quantity: "数量"
}

interface ValidationIssue {
  type?: string
  loc?: unknown[]
  msg?: string
  ctx?: Record<string, unknown>
}

export function validationDetailMessage(detail: unknown) {
  if (!Array.isArray(detail)) return ""
  const messages = detail
    .map((item) => {
      if (!item || typeof item !== "object") return ""
      const error = item as ValidationIssue
      const field = String(error.loc?.at(-1) || "")
      const label = FIELD_LABELS[field] || field || "请求参数"
      if (error.type === "greater_than_equal") {
        return `${label}不能小于 ${String(error.ctx?.ge ?? "")}`
      }
      if (error.type === "less_than_equal") {
        return `${label}不能大于 ${String(error.ctx?.le ?? "")}`
      }
      return error.msg ? `${label}：${error.msg}` : ""
    })
    .filter(Boolean)
  return messages.join("；")
}

export function backendErrorMessage(data: unknown, fallback: string) {
  if (!data || typeof data !== "object") return fallback
  const detail = (data as { detail?: unknown }).detail
  if (typeof detail === "string") return detail
  if (detail && typeof detail === "object" && "message" in detail) {
    return String((detail as { message: unknown }).message)
  }
  return validationDetailMessage(detail) || fallback
}
