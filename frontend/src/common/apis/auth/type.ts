export interface ChangePasswordRequestData {
  /** 原密码 */
  old_password: string
  /** 新密码（≥8 位且同时包含字母与数字） */
  new_password: string
}

export type ChangePasswordResponseData = ApiResponseData<{ ok: boolean }>
