<script lang="ts" setup>
import { useLayoutMode } from "@@/composables/useLayoutMode"

interface Props {
  collapse?: boolean
}

const { collapse = true } = defineProps<Props>()

const { isLeft, isTop } = useLayoutMode()
</script>

<template>
  <div class="layout-logo-container" :class="{ 'collapse': collapse, 'layout-mode-top': isTop }">
    <transition name="layout-logo-fade">
      <router-link v-if="collapse" key="collapse" to="/">
        <span class="layout-logo">仓</span>
      </router-link>
      <router-link v-else key="expand" to="/">
        <span class="layout-logo-text" :class="{ dark: isLeft }"><b>仓</b> 简仓 ERP</span>
      </router-link>
    </transition>
  </div>
</template>

<style lang="scss" scoped>
.layout-logo-container {
  position: relative;
  width: 100%;
  height: var(--v3-header-height);
  display: flex;
  justify-content: center;
  overflow: hidden;
  a {
    display: flex;
    align-items: center;
    .layout-logo {
      display: none;
    }
    .layout-logo-text { color: var(--el-text-color-primary); font-size: 17px; font-weight: 650; white-space: nowrap; }
    .layout-logo-text.dark { color: #f3f6ff; }
    .layout-logo-text b { margin-right: 8px; padding: 5px 7px; color: #fff; border-radius: 7px; background: var(--el-color-primary); }
  }
}

.layout-mode-top {
  height: var(--v3-navigationbar-height);
}

.collapse {
  a {
    .layout-logo {
      width: 32px;
      height: 32px;
      display: inline-block;
      color: #fff;
      line-height: 32px;
      text-align: center;
      font-weight: 700;
      border-radius: 8px;
      background: var(--el-color-primary);
    }
    .layout-logo-text {
      display: none;
    }
  }
}
</style>
