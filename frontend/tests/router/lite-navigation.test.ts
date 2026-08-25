import { describe, expect, it } from "vitest"
import { constantRoutes } from "@/router"

function topLevelTitle(route: (typeof constantRoutes)[number]) {
  if (route.path === "/") return route.children?.[0]?.meta?.title
  return route.meta?.title
}

function routeByPath(path: string) {
  const route = constantRoutes.find(item => item.path === path)
  if (!route) throw new Error(`Missing route: ${path}`)
  return route
}

function visibleChildTitles(path: string) {
  return routeByPath(path).children
    ?.filter(child => !child.meta?.hidden)
    .map(child => child.meta?.title)
}

function hiddenChildPaths(path: string) {
  return routeByPath(path).children
    ?.filter(child => child.meta?.hidden)
    .map(child => child.path)
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

  it("groups daily tasks into no more than four second-level entries", () => {
    expect(visibleChildTitles("/lite-orders")).toEqual(["客户订单", "销售单据"])
    expect(visibleChildTitles("/lite-production")).toEqual(["排产看板", "完工登记"])
    expect(visibleChildTitles("/lite-inventory")).toEqual(["库存总览", "出入库", "盘点", "库存记录"])
    expect(visibleChildTitles("/lite-purchase")).toEqual(["采购需求", "到货登记"])
    expect(visibleChildTitles("/lite-settings")).toEqual(["产品与 BOM", "原料资料", "生产参数", "系统管理"])

    for (const path of ["/lite-orders", "/lite-production", "/lite-inventory", "/lite-purchase", "/lite-settings"]) {
      expect(visibleChildTitles(path)?.length).toBeLessThanOrEqual(4)
    }
  })

  it("renders finance as a direct top-level destination", () => {
    const finance = routeByPath("/lite-finance")
    const visibleChildren = finance.children?.filter(child => !child.meta?.hidden) ?? []

    expect(finance.meta?.alwaysShow).not.toBe(true)
    expect(visibleChildren).toHaveLength(1)
    expect(visibleChildren[0].path).toBe("")
    expect(visibleChildren[0].meta?.title).toBe("财务")
  })

  it("keeps replaced Lite entry points as hidden compatibility redirects", () => {
    expect(hiddenChildPaths("/lite-inventory")).toEqual([
      "materials",
      "products",
      "reconciliation",
      "documents",
      "movements"
    ])
    expect(hiddenChildPaths("/lite-settings")).toEqual([
      "calendar",
      "print",
      "backups",
      "users",
      "logs"
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
