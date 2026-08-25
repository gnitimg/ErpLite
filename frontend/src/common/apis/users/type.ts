export type CurrentUserResponseData = ApiResponseData<{
  username: string
  roles: string[]
  permissions?: string[]
  /** 首次登录强制改密标志：为 true 时前端弹不可关闭改密对话框 */
  must_change_password?: boolean
}>
