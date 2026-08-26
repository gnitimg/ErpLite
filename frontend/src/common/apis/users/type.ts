export interface NavigationConfig {
  root_order: string[]
  hidden_roots: string[]
  child_order: Record<string, string[]>
}

export type CurrentUserResponseData = ApiResponseData<{
  username: string
  roles: string[]
  permissions?: string[]
  /** 首次登录强制改密标志：为 true 时前端弹不可关闭改密对话框 */
  must_change_password?: boolean
  navigation_config?: NavigationConfig
}>
