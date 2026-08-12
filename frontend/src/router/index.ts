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
const templateConstantRoutes: RouteRecordRaw[] = [
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
        meta: { title: "产品与 BOM", elIcon: "Box", keepAlive: true }
      },
      {
        path: "samples",
        component: () => import("@/pages/erp/samples.vue"),
        name: "Samples",
        meta: { title: "样品库存", elIcon: "Present", keepAlive: true }
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
        path: "production",
        component: () => import("@/pages/erp/production.vue"),
        name: "Production",
        meta: { title: "产品生产", elIcon: "Tools", keepAlive: true }
      },
      {
        path: "operations",
        component: () => import("@/pages/erp/movements.vue"),
        name: "StockOperations",
        meta: { title: "出入库作业", elIcon: "Sort", stockView: "operations", keepAlive: true }
      },
      {
        path: "movements",
        component: () => import("@/pages/erp/movements.vue"),
        name: "StockMovements",
        meta: { title: "库存流水", elIcon: "List", stockView: "history", keepAlive: true }
      },
      {
        path: "inventory",
        redirect: "/warehouse/parts-inventory",
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
        path: "movements",
        redirect: "/warehouse/operations",
        meta: { hidden: true }
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
  },
  {
    path: "/demo",
    component: Layouts,
    redirect: "/demo/unocss",
    name: "Demo",
    meta: {
      title: "示例集合",
      elIcon: "DataBoard"
    },
    children: [
      {
        path: "unocss",
        component: () => import("@/pages/demo/unocss/index.vue"),
        name: "UnoCSS",
        meta: {
          title: "UnoCSS"
        }
      },
      {
        path: "element-plus",
        component: () => import("@/pages/demo/element-plus/index.vue"),
        name: "ElementPlus",
        meta: {
          title: "Element Plus",
          keepAlive: true
        }
      },
      {
        path: "vxe-table",
        component: () => import("@/pages/demo/vxe-table/index.vue"),
        name: "VxeTable",
        meta: {
          title: "Vxe Table",
          keepAlive: true
        }
      },
      {
        path: "level2",
        component: () => import("@/pages/demo/level2/index.vue"),
        redirect: "/demo/level2/level3",
        name: "Level2",
        meta: {
          title: "二级路由",
          alwaysShow: true
        },
        children: [
          {
            path: "level3",
            component: () => import("@/pages/demo/level2/level3/index.vue"),
            name: "Level3",
            meta: {
              title: "三级路由",
              keepAlive: true
            }
          }
        ]
      },
      {
        path: "composable-demo",
        redirect: "/demo/composable-demo/use-fetch-select",
        name: "ComposableDemo",
        meta: {
          title: "组合式函数"
        },
        children: [
          {
            path: "use-fetch-select",
            component: () => import("@/pages/demo/composable-demo/use-fetch-select.vue"),
            name: "UseFetchSelect",
            meta: {
              title: "useFetchSelect"
            }
          },
          {
            path: "use-fullscreen-loading",
            component: () => import("@/pages/demo/composable-demo/use-fullscreen-loading.vue"),
            name: "UseFullscreenLoading",
            meta: {
              title: "useFullscreenLoading"
            }
          },
          {
            path: "use-watermark",
            component: () => import("@/pages/demo/composable-demo/use-watermark.vue"),
            name: "UseWatermark",
            meta: {
              title: "useWatermark"
            }
          }
        ]
      }
    ]
  },
  {
    path: "/link",
    meta: {
      title: "文档链接",
      elIcon: "Link"
    },
    children: [
      {
        path: "https://juejin.cn/post/7445151895121543209",
        component: () => {},
        name: "Link1",
        meta: {
          title: "中文文档"
        }
      },
      {
        path: "https://juejin.cn/column/7207659644487139387",
        component: () => {},
        name: "Link2",
        meta: {
          title: "新手教程"
        }
      },
      {
        path: "https://juejin.cn/column/7046214632771420196",
        component: () => {},
        name: "Link3",
        meta: {
          title: "周边资讯"
        }
      }
    ]
  }
]

/** 模板演示与文档路由保留在源码中，但不注册到 ERP 菜单。 */
const disabledConstantPaths = new Set(["/demo", "/link"])
export const constantRoutes: RouteRecordRaw[] = templateConstantRoutes.filter(route => !disabledConstantPaths.has(route.path))

/**
 * @name 动态路由
 * @description 用来放置有权限 (roles / permissions 属性) 的路由
 * @description 必须带有唯一的 Name 属性
 */
export const disabledDynamicRoutes: RouteRecordRaw[] = [
  {
    path: "/permission",
    component: Layouts,
    redirect: "/permission/page-level",
    name: "Permission",
    meta: {
      title: "权限演示",
      elIcon: "Lock",
      alwaysShow: true
    },
    children: [
      {
        path: "page-level",
        component: () => import("@/pages/demo/permission/page-level.vue"),
        name: "PermissionPageLevel",
        meta: {
          title: "页面级",
          // 在路由中设置角色来控制访问
          roles: ["admin"],
          // 在路由中设置权限标识字符来控制访问
          permissions: ["permission:page-level"]
        }
      },
      {
        path: "button-level",
        component: () => import("@/pages/demo/permission/button-level.vue"),
        name: "PermissionButtonLevel",
        meta: {
          title: "按钮级",
          // 如果未设置，则不限制该页面的访问
          roles: undefined,
          // 在路由中设置权限标识字符来控制访问
          permissions: ["permission:button-level"]
        }
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
