import type { RouteRecordRaw } from "vue-router"
import { createRouter } from "vue-router"
import { DASHBOARD_PATH, REDIRECT_PATH, routerConfig } from "@/router/config"
import { registerNavigationGuard } from "@/router/guard"
import { flatMultiLevelRoutes } from "./helper"

const Layouts = () => import("@/layouts/index.vue")

/**
 * @name 常驻路由
 * @description 除了 redirect/403/404/login 等隐藏页面，其他页面建议设置唯一的 Name 属性
 */
export const constantRoutes: RouteRecordRaw[] = [
  {
    path: REDIRECT_PATH,
    component: Layouts,
    meta: {
      hidden: true
    },
    children: [
      {
        path: ":path(.*)",
        component: () => import("@/pages/redirect/index.vue")
      }
    ]
  },
  {
    path: "/403",
    component: () => import("@/pages/error/403.vue"),
    meta: {
      hidden: true
    }
  },
  {
    path: "/404",
    component: () => import("@/pages/error/404.vue"),
    meta: {
      hidden: true
    },
    alias: "/:pathMatch(.*)*"
  },
  {
    path: "/login",
    component: () => import("@/pages/login/index.vue"),
    meta: {
      hidden: true
    }
  },
  {
    path: "/settings",
    component: Layouts,
    meta: { hidden: true },
    children: [
      {
        path: "theme",
        component: () => import("@/pages/settings/theme.vue"),
        name: "ThemeSettings",
        meta: { title: "主题设置", hidden: true }
      }
    ]
  },
  {
    path: "/",
    component: Layouts,
    redirect: DASHBOARD_PATH,
    children: [
      {
        path: "dashboard",
        component: () => import("@/pages/erp/dashboard.vue"),
        name: "Dashboard",
        meta: {
          title: "工作台",
          svgIcon: "dashboard",
          affix: true
        }
      }
    ]
  },
  {
    path: "/master-data",
    component: Layouts,
    redirect: "/master-data/parts",
    name: "MasterData",
    meta: {
      title: "物料目录",
      elIcon: "Collection",
      alwaysShow: true
    },
    children: [
      {
        path: "parts",
        component: () => import("@/pages/erp/parts.vue"),
        name: "Parts",
        meta: { title: "零件目录", elIcon: "Cpu", keepAlive: true }
      },
      {
        path: "products",
        component: () => import("@/pages/erp/products.vue"),
        name: "Products",
        meta: { title: "产品目录", elIcon: "Box", keepAlive: true }
      },
      {
        path: "samples",
        redirect: "/warehouse/samples",
        meta: { hidden: true }
      }
    ]
  },
  {
    path: "/warehouse",
    component: Layouts,
    redirect: "/warehouse/parts-inventory",
    name: "Warehouse",
    meta: { title: "库存管理", elIcon: "House", alwaysShow: true },
    children: [
      {
        path: "parts-inventory",
        component: () => import("@/pages/erp/inventory.vue"),
        name: "PartsInventory",
        meta: { title: "零件库存", elIcon: "Cpu", inventoryKind: "PART", keepAlive: true }
      },
      {
        path: "products-inventory",
        component: () => import("@/pages/erp/inventory.vue"),
        name: "ProductsInventory",
        meta: { title: "产品库存", elIcon: "Box", inventoryKind: "PRODUCT", keepAlive: true }
      },
      {
        path: "samples",
        component: () => import("@/pages/erp/samples.vue"),
        name: "Samples",
        meta: { title: "样品库存", elIcon: "Present", keepAlive: true }
      },
      {
        path: "inventory",
        redirect: "/warehouse/parts-inventory",
        meta: { hidden: true }
      },
      {
        path: "production",
        redirect: "/operations/production",
        meta: { hidden: true }
      },
      {
        path: "operations",
        redirect: "/operations/stock-operations",
        meta: { hidden: true }
      },
      {
        path: "movements",
        redirect: "/logs/stock",
        meta: { hidden: true }
      }
    ]
  },
  {
    path: "/operations",
    component: Layouts,
    redirect: "/operations/orders",
    name: "BusinessOperations",
    meta: {
      title: "业务处理",
      elIcon: "Tickets",
      alwaysShow: true
    },
    children: [
      {
        path: "orders",
        component: () => import("@/pages/erp/orders.vue"),
        name: "Orders",
        meta: { title: "客户订单", elIcon: "Tickets", keepAlive: true }
      },
      {
        path: "production",
        component: () => import("@/pages/erp/production.vue"),
        name: "Production",
        meta: { title: "产品生产", elIcon: "Tools", keepAlive: true }
      },
      {
        path: "stock-operations",
        component: () => import("@/pages/erp/movements.vue"),
        name: "StockOperations",
        meta: { title: "出入库作业", elIcon: "Sort", stockView: "operations", keepAlive: true }
      }
    ]
  },
  {
    path: "/logs",
    component: Layouts,
    redirect: "/logs/stock",
    name: "LogManagement",
    meta: {
      title: "操作日志",
      elIcon: "Document",
      alwaysShow: true
    },
    children: [
      {
        path: "stock",
        component: () => import("@/pages/erp/movements.vue"),
        name: "StockMovements",
        meta: { title: "库存流水", elIcon: "List", stockView: "history", keepAlive: true }
      },
      {
        path: "system",
        component: () => import("@/pages/erp/operation-logs.vue"),
        name: "OperationLogs",
        meta: { title: "系统操作日志", elIcon: "Tickets", keepAlive: true }
      }
    ]
  },
  {
    path: "/system",
    component: Layouts,
    redirect: "/system/backups",
    name: "SystemManagement",
    meta: {
      title: "系统管理",
      elIcon: "Setting",
      alwaysShow: true
    },
    children: [
      {
        path: "backups",
        component: () => import("@/pages/erp/backups.vue"),
        name: "Backups",
        meta: { title: "数据备份", elIcon: "RefreshLeft" }
      }
    ]
  }
]

/** 小型本地 ERP 暂不启用模板的权限演示路由。 */
export const dynamicRoutes: RouteRecordRaw[] = []

/** 路由实例 */
export const router = createRouter({
  history: routerConfig.history,
  routes: routerConfig.thirdLevelRouteCache ? flatMultiLevelRoutes(constantRoutes) : constantRoutes
})

/** 重置路由 */
export function resetRouter() {
  try {
    // 注意：所有动态路由路由必须带有 Name 属性，否则可能会不能完全重置干净
    router.getRoutes().forEach((route) => {
      const { name, meta } = route
      if (name && (meta.roles?.length || meta.permissions?.length)) {
        router.hasRoute(name) && router.removeRoute(name)
      }
    })
  } catch {
    // 强制刷新浏览器也行，只是交互体验不是很好
    location.reload()
  }
}

// 注册路由导航守卫
registerNavigationGuard(router)
