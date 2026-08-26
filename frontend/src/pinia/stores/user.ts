import { changePasswordApi } from "@@/apis/auth"
import { getCurrentUserApi } from "@@/apis/users"
import { setToken as _setToken, getToken, removeToken } from "@@/utils/local-storage"
import { pinia } from "@/pinia"
import { resetRouter, router } from "@/router"
import { useSettingsStore } from "./settings"
import { useTagsViewStore } from "./tags-view"

export interface NavigationConfig {
  root_order: string[]
  hidden_roots: string[]
  child_order: Record<string, string[]>
}

function emptyNavigationConfig(): NavigationConfig {
  return {
    root_order: [],
    hidden_roots: [],
    child_order: {}
  }
}

const retiredNavigationRoots = new Set(["/lite-finance", "/lite-catalog"])

function uniquePaths(paths: string[]) {
  return [...new Set(paths)]
}

function normalizeNavigationConfig(
  value?: Partial<NavigationConfig> | null
): NavigationConfig {
  const source = {
    ...emptyNavigationConfig(),
    ...(value || {})
  }
  const childOrder = Object.fromEntries(
    Object.entries(source.child_order || {}).map(([key, paths]) => [
      key,
      uniquePaths([...(paths || [])])
    ])
  )
  delete childOrder["/lite-finance"]
  delete childOrder["/lite-catalog"]

  const salesOrder = childOrder["/lite-orders"] || []
  if (salesOrder.length) {
    childOrder["/lite-orders"] = uniquePaths([
      ...salesOrder.filter(path => path !== "finance"),
      "finance"
    ])
  }

  const settingsOrder = childOrder["/lite-settings"] || []
  if (settingsOrder.length) {
    childOrder["/lite-settings"] = uniquePaths([
      "items",
      ...settingsOrder.filter(path => path !== "items")
    ])
  }

  return {
    root_order: uniquePaths(source.root_order || [])
      .filter(path => !retiredNavigationRoots.has(path)),
    hidden_roots: uniquePaths(source.hidden_roots || [])
      .filter(path => !retiredNavigationRoots.has(path)),
    child_order: childOrder
  }
}

export const useUserStore = defineStore("user", () => {
  const token = ref<string>(getToken() || "")

  const roles = ref<string[]>([])

  const permissions = ref<string[]>([])

  const username = ref<string>("")

  const navigationConfig = ref<NavigationConfig>(emptyNavigationConfig())

  /** 首次登录强制改密标志：为 true 时由布局层弹出不可关闭的改密对话框 */
  const mustChangePassword = ref<boolean>(false)

  const isGotUserInfo = ref<boolean>(false)

  const tagsViewStore = useTagsViewStore()

  const settingsStore = useSettingsStore()

  // 设置 Token
  const setToken = (value: string) => {
    _setToken(value)
    token.value = value
  }

  // 获取用户详情
  const getInfo = async () => {
    const { data } = await getCurrentUserApi()
    username.value = data.username
    roles.value = data.roles ?? []
    permissions.value = data.permissions ?? []
    mustChangePassword.value = Boolean(data.must_change_password)
    navigationConfig.value = normalizeNavigationConfig(data.navigation_config)
    // 防止路由守卫逻辑进入无限循环
    isGotUserInfo.value = true
  }

  // 修改当前用户自己的密码（首次登录强制改密走同一入口）
  const changePassword = async (oldPassword: string, newPassword: string) => {
    await changePasswordApi({ old_password: oldPassword, new_password: newPassword })
    mustChangePassword.value = false
  }

  // 模拟用户变化
  const changeUser = (value: string) => {
    const newToken = `token-${value}`
    token.value = newToken
    _setToken(newToken)
    // 用刷新页面代替重新登录
    location.reload()
  }

  const setNavigationConfig = (value: NavigationConfig) => {
    navigationConfig.value = normalizeNavigationConfig(value)
  }

  // 登出
  const logout = () => {
    resetToken()
    resetRouter()
    resetTagsView()
    // 重定向到登录页
    router.replace("/login")
  }

  // 重置 Token
  const resetToken = () => {
    removeToken()
    token.value = ""
    roles.value = []
    permissions.value = []
    mustChangePassword.value = false
    navigationConfig.value = emptyNavigationConfig()
    isGotUserInfo.value = false
  }

  // 重置 Visited Views 和 Cached Views
  const resetTagsView = () => {
    if (!settingsStore.cacheTagsView) {
      tagsViewStore.delAllVisitedViews()
      tagsViewStore.delAllCachedViews()
    }
  }

  return {
    token,
    roles,
    permissions,
    username,
    navigationConfig,
    mustChangePassword,
    isGotUserInfo,
    setToken,
    getInfo,
    changePassword,
    changeUser,
    setNavigationConfig,
    logout,
    resetToken
  }
})

/**
 * @description 在 SPA 应用中可用于在 pinia 实例被激活前使用 store
 * @description 在 SSR 应用中可用于在 setup 外使用 store
 */
export function useUserStoreOutside() {
  return useUserStore(pinia)
}
