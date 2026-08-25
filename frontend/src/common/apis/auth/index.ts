import type * as Auth from "./type"
import { request } from "@/http/axios"

/** 修改当前登录用户自己的密码 */
export function changePasswordApi(data: Auth.ChangePasswordRequestData) {
  return request<Auth.ChangePasswordResponseData>({
    url: "auth/change-password",
    method: "post",
    data
  })
}
