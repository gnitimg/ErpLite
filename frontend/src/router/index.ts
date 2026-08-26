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
    path: "/appearance",
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
          title: "总览",
          svgIcon: "dashboard",
          affix: true
        }
      }
    ]
  },
  {
    path: "/master-data",
    component: Layouts,
    redirect: { path: "/lite-settings/items", query: { scope: "PART" } },
    name: "MasterData",
    meta: {
      title: "物料目录",
      elIcon: "Collection",
      alwaysShow: true,
      hidden: true
    },
    children: [
      {
        path: "parts",
        redirect: to => ({
          path: "/lite-settings/items",
          query: { ...to.query, scope: "PART" }
        }),
        meta: { hidden: true }
      },
      {
        path: "products",
        redirect: to => ({
          path: "/lite-settings/items",
          query: { ...to.query, scope: "PRODUCT" }
        }),
        meta: { hidden: true }
      },
      {
        path: "production-resources",
        redirect: { path: "/lite-settings/items", query: { scope: "PRODUCT" } },
        meta: { hidden: true }
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
    meta: { title: "库存管理", elIcon: "House", alwaysShow: true, hidden: true },
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
        path: "reconciliation",
        component: () => import("@/pages/erp/stock-reconciliation.vue"),
        name: "StockReconciliation",
        meta: { title: "库存盘点与对账", elIcon: "Histogram", keepAlive: true }
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
      alwaysShow: true,
      hidden: true
    },
    children: [
      {
        path: "orders",
        component: () => import("@/pages/erp/orders.vue"),
        name: "Orders",
        meta: { title: "客户订单", elIcon: "Tickets", keepAlive: true }
      },
      {
        path: "purchase",
        component: () => import("@/pages/erp/purchase.vue"),
        name: "PurchaseRequirements",
        meta: { title: "待购买", elIcon: "ShoppingCart", keepAlive: true }
      },
      {
        path: "scheduling",
        component: () => import("@/pages/erp/scheduling.vue"),
        name: "Scheduling",
        meta: { title: "订单排产", elIcon: "Calendar", keepAlive: true }
      },
      {
        path: "production",
        component: () => import("@/pages/erp/production.vue"),
        name: "Production",
        meta: { title: "生产入库", elIcon: "Tools", keepAlive: true }
      },
      {
        path: "external-processing",
        component: () => import("@/pages/erp/external-processing.vue"),
        name: "ExternalProcessing",
        meta: { title: "外协加工", elIcon: "Van", keepAlive: true }
      },
      {
        path: "stock-operations",
        component: () => import("@/pages/erp/stock-document.vue"),
        name: "StockOperations",
        meta: { title: "出入库作业", elIcon: "Sort", keepAlive: true }
      },
      {
        path: "purchase-arrival",
        component: () => import("@/pages/erp/purchase-arrival.vue"),
        name: "PurchaseArrival",
        meta: { title: "采购到货", elIcon: "Goods", keepAlive: true }
      },
      {
        path: "finance",
        component: () => import("@/pages/erp/finance.vue"),
        name: "Finance",
        meta: { title: "财务管理", elIcon: "Money", keepAlive: true }
      }
    ]
  },
  {
    path: "/logs",
    component: Layouts,
    redirect: "/logs/stock",
    name: "LogManagement",
    meta: {
      title: "单据 / 日志",
      elIcon: "Document",
      alwaysShow: true,
      hidden: true
    },
    children: [
      {
        path: "inbound-documents",
        component: () => import("@/pages/erp/documents.vue"),
        name: "InboundDocuments",
        meta: { title: "入库单", elIcon: "DocumentAdd", documentDirection: "inbound", keepAlive: true }
      },
      {
        path: "outbound-documents",
        component: () => import("@/pages/erp/documents.vue"),
        name: "OutboundDocuments",
        meta: { title: "出库单", elIcon: "DocumentRemove", documentDirection: "outbound", keepAlive: true }
      },
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
      alwaysShow: true,
      hidden: true
    },
    children: [
      {
        path: "production",
        component: () => import("@/pages/erp/production-settings.vue"),
        name: "ProductionSettings",
        meta: { title: "生产设置", elIcon: "SetUp", keepAlive: true }
      },
      {
        path: "print",
        component: () => import("@/pages/erp/print-settings.vue"),
        name: "PrintSettings",
        meta: { title: "打印设置", elIcon: "Printer", keepAlive: true }
      },
      {
        path: "backups",
        component: () => import("@/pages/erp/backups.vue"),
        name: "Backups",
        meta: { title: "数据备份", elIcon: "RefreshLeft" }
      },
      {
        path: "users",
        component: () => import("@/pages/erp/users.vue"),
        name: "Users",
        meta: { title: "用户管理", elIcon: "User", keepAlive: true }
      },
      {
        path: "calendar",
        component: () => import("@/pages/erp/production-calendar.vue"),
        name: "ProductionCalendar",
        meta: { title: "生产日历", elIcon: "Calendar", keepAlive: true }
      }
    ]
  },
  {
    path: "/lite-orders",
    component: Layouts,
    redirect: "/lite-orders/list",
    name: "LiteOrdersRoot",
    meta: { title: "销售", elIcon: "Tickets", alwaysShow: true },
    children: [
      {
        path: "list",
        component: () => import("@/pages/erp/orders.vue"),
        name: "LiteOrders",
        meta: { title: "客户订单", keepAlive: true }
      },
      {
        path: "documents",
        component: () => import("@/pages/erp/documents.vue"),
        name: "LiteSalesDocuments",
        meta: { title: "销售出库与退货", documentContext: "sales", documentDirection: "outbound", keepAlive: true }
      },
      {
        path: "finance",
        component: () => import("@/pages/erp/finance.vue"),
        name: "LiteFinance",
        meta: { title: "应收与收款", keepAlive: true }
      }
    ]
  },
  {
    path: "/lite-production",
    component: Layouts,
    redirect: "/lite-production/schedule",
    name: "LiteProductionRoot",
    meta: { title: "生产", elIcon: "Calendar", alwaysShow: true },
    children: [
      {
        path: "schedule",
        component: () => import("@/pages/erp/scheduling.vue"),
        name: "LiteScheduling",
        meta: { title: "排产看板", keepAlive: true }
      },
      {
        path: "completion",
        component: () => import("@/pages/erp/production.vue"),
        name: "LiteProductionCompletion",
        meta: { title: "完工登记", keepAlive: true }
      },
      {
        path: "external-processing",
        component: () => import("@/pages/erp/external-processing.vue"),
        name: "LiteExternalProcessing",
        meta: { title: "外协加工", keepAlive: true }
      }
    ]
  },
  {
    path: "/lite-inventory",
    component: Layouts,
    redirect: "/lite-inventory/overview",
    name: "LiteInventoryRoot",
    meta: { title: "库存", elIcon: "House", alwaysShow: true },
    children: [
      {
        path: "overview",
        component: () => import("@/pages/erp/inventory.vue"),
        name: "LiteInventoryOverview",
        meta: { title: "库存总览", inventoryKind: "ALL", keepAlive: true }
      },
      {
        path: "operations",
        redirect: to => ({ path: "/lite-stock-documents/list", query: to.query }),
        meta: { hidden: true }
      },
      {
        path: "samples",
        component: () => import("@/pages/erp/samples.vue"),
        name: "LiteSamples",
        meta: { title: "样品库存", keepAlive: true }
      },
      {
        path: "stocktake",
        component: () => import("@/pages/erp/stock-reconciliation.vue"),
        name: "LiteStocktake",
        meta: { title: "盘点与对账", keepAlive: true }
      },
      {
        path: "history",
        redirect: "/lite-stock-documents/history",
        meta: { hidden: true }
      },
      {
        path: "materials",
        redirect: { path: "/lite-inventory/overview", query: { tab: "materials" } },
        meta: { hidden: true }
      },
      {
        path: "products",
        redirect: { path: "/lite-inventory/overview", query: { tab: "products" } },
        meta: { hidden: true }
      },
      {
        path: "reconciliation",
        redirect: "/lite-inventory/stocktake",
        meta: { hidden: true }
      },
      {
        path: "documents",
        redirect: { path: "/lite-stock-documents/list", query: { direction: "inbound" } },
        meta: { hidden: true }
      },
      {
        path: "movements",
        redirect: "/lite-stock-documents/history",
        meta: { hidden: true }
      }
    ]
  },
  {
    path: "/lite-stock-documents",
    component: Layouts,
    redirect: "/lite-stock-documents/list",
    name: "LiteStockDocumentsRoot",
    meta: { title: "出入库", elIcon: "Sort", alwaysShow: true },
    children: [
      {
        path: "list",
        component: () => import("@/pages/erp/documents.vue"),
        name: "LiteStockDocuments",
        meta: {
          title: "库存单据",
          documentContext: "inventory",
          documentDirection: "both",
          keepAlive: true
        }
      },
      {
        path: "history",
        component: () => import("@/pages/erp/inventory-history.vue"),
        name: "LiteInventoryHistory",
        meta: { title: "库存流水", stockView: "history", keepAlive: true }
      }
    ]
  },
  {
    path: "/lite-purchase",
    component: Layouts,
    redirect: "/lite-purchase/requirements",
    name: "LitePurchaseRoot",
    meta: { title: "采购", elIcon: "ShoppingCart", alwaysShow: true },
    children: [
      {
        path: "requirements",
        component: () => import("@/pages/erp/purchase.vue"),
        name: "LitePurchaseRequirements",
        meta: { title: "采购需求", keepAlive: true }
      },
      {
        path: "arrivals",
        component: () => import("@/pages/erp/purchase-arrival.vue"),
        name: "LitePurchaseArrival",
        meta: { title: "到货登记", keepAlive: true }
      }
    ]
  },
  {
    path: "/lite-finance",
    component: Layouts,
    redirect: to => ({ path: "/lite-orders/finance", query: to.query }),
    name: "LiteFinanceLegacyRoot",
    meta: { hidden: true },
    children: [
      {
        path: "receivables",
        redirect: to => ({ path: "/lite-orders/finance", query: to.query }),
        meta: { hidden: true }
      }
    ]
  },
  {
    path: "/lite-catalog",
    component: Layouts,
    redirect: to => ({ path: "/lite-settings/items", query: to.query }),
    name: "LiteCatalogLegacyRoot",
    meta: { hidden: true },
    children: [
      {
        path: "items",
        redirect: to => ({ path: "/lite-settings/items", query: to.query }),
        meta: { hidden: true }
      },
      {
        path: "products",
        redirect: to => ({
          path: "/lite-settings/items",
          query: { ...to.query, scope: "PRODUCT" }
        }),
        meta: { hidden: true }
      },
      {
        path: "materials",
        redirect: to => ({
          path: "/lite-settings/items",
          query: { ...to.query, scope: "PART" }
        }),
        meta: { hidden: true }
      }
    ]
  },
  {
    path: "/lite-settings",
    component: Layouts,
    redirect: "/lite-settings/items",
    name: "LiteSettingsRoot",
    meta: { title: "资料与设置", elIcon: "Setting", alwaysShow: true },
    children: [
      {
        path: "items",
        component: () => import("@/pages/erp/products.vue"),
        name: "LiteCatalogItems",
        meta: { title: "物料资料", keepAlive: true }
      },
      {
        path: "workflow",
        component: () => import("@/pages/erp/workflow-settings.vue"),
        name: "LiteWorkflowSettings",
        meta: { title: "业务规则", keepAlive: true }
      },
      {
        path: "production",
        component: () => import("@/pages/erp/production-parameters.vue"),
        name: "LiteProductionParameters",
        meta: { title: "生产参数", keepAlive: true }
      },
      {
        path: "system",
        component: () => import("@/pages/erp/system-management.vue"),
        name: "LiteSystemManagement",
        meta: { title: "系统维护", keepAlive: true }
      },
      {
        path: "products",
        redirect: { path: "/lite-settings/items", query: { scope: "PRODUCT" } },
        meta: { hidden: true }
      },
      {
        path: "materials",
        redirect: { path: "/lite-settings/items", query: { scope: "PART" } },
        meta: { hidden: true }
      },
      {
        path: "calendar",
        redirect: { path: "/lite-settings/production", query: { tab: "calendar" } },
        meta: { hidden: true }
      },
      {
        path: "print",
        redirect: { path: "/lite-settings/system", query: { tab: "print" } },
        meta: { hidden: true }
      },
      {
        path: "backups",
        redirect: { path: "/lite-settings/system", query: { tab: "backups" } },
        meta: { hidden: true }
      },
      {
        path: "users",
        redirect: { path: "/lite-settings/system", query: { tab: "users" } },
        meta: { hidden: true }
      },
      {
        path: "logs",
        redirect: { path: "/lite-settings/system", query: { tab: "logs" } },
        meta: { hidden: true }
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
