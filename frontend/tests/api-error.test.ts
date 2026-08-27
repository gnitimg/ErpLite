import { describe, expect, it } from "vitest"
import { backendErrorMessage, validationDetailMessage } from "../src/common/utils/api-error"

describe("api error messages", () => {
  it("formats FastAPI validation details with a readable field label", () => {
    expect(validationDetailMessage([
      {
        type: "greater_than_equal",
        loc: ["body", "rules", 0, "next_number"],
        msg: "Input should be greater than or equal to 0",
        ctx: { ge: 0 }
      }
    ])).toBe("待用号码不能小于 0")
  })

  it("keeps a backend string detail", () => {
    expect(backendErrorMessage({ detail: "需要管理员权限" }, "请求失败"))
      .toBe("需要管理员权限")
  })
})
