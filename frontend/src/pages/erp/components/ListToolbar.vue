<script setup lang="ts">
withDefaults(defineProps<{
  placeholder?: string
  filterCount?: number
  loading?: boolean
  showFilter?: boolean
}>(), {
  placeholder: "搜索关键词",
  filterCount: 0,
  loading: false,
  showFilter: true
})

const emit = defineEmits<{
  search: []
  filter: []
  refresh: []
}>()

const keyword = defineModel<string>({ default: "" })
</script>

<template>
  <div class="page-toolbar list-toolbar">
    <div class="toolbar-group list-actions">
      <el-input
        v-model="keyword"
        clearable
        class="list-search"
        :placeholder="placeholder"
        @keyup.enter="emit('search')"
        @clear="emit('search')"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
      <el-badge v-if="showFilter" :value="filterCount" :hidden="!filterCount" class="filter-badge">
        <el-button @click="emit('filter')">
          <el-icon><Filter /></el-icon>筛选
        </el-button>
      </el-badge>
      <el-button :loading="loading" @click="emit('refresh')">
        <el-icon><Refresh /></el-icon>刷新
      </el-button>
    </div>
    <div v-if="$slots.default" class="toolbar-right">
      <slot />
    </div>
  </div>
</template>
