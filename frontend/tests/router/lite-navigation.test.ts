import { describe, expect, it } from "vitest"
import { constantRoutes } from "@/router"

function topLevelTitle(route: (typeof constantRoutes)[number]) {
  if (route.path === "/") return route.children?.[0]?.meta?.title
  return route.meta?.title
}

describe("Lite V1 navigation contract", () => {
  it("exposes only the seven daily operating concepts", () => {
    const visibleTitles = constantRoutes
      .filter(route => !route.meta?.hidden)
      .map(topLevelTitle)

    expect(visibleTitles).toEqual([
      "总览",
      "订单",
      "生产排期",
      "库存",
      "采购",
      "财务",
      "设置"
    ])
  })

  it("keeps Full routes compatible but hidden from Lite navigation", () => {
    const hiddenPaths = constantRoutes
      .filter(route => route.meta?.hidden)
      .map(route => route.path)

    expect(hiddenPaths).toEqual(expect.arrayContaining([
      "/master-data",
      "/warehouse",
      "/operations",
      "/logs",
      "/system"
    ]))
  })
})
