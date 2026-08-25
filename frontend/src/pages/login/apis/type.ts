export interface LoginRequestData {
  /** 用户名 */
  username: string
  /** 密码 */
  password: string
}

export type LoginResponseData = ApiResponseData<{
  token: string
  username: string
  display_name: string
  role: string
  /** 首次登录强制改密标志 */
  must_change_password?: boolean
}>
