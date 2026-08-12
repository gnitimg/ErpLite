<script setup lang="ts">
import { ref, watch } from "vue"
import { compactQty } from "../api"

const props = withDefaults(defineProps<{
  modelValue: number
  integer?: boolean
  min?: number
  unit?: string
}>(), {
  integer: false,
  min: 0,
  unit: ""
})

const emit = defineEmits<{
  "update:modelValue": [value: number]
}>()

const focused = ref(false)
const displayValue = ref("")

function format(value: number) {
  return compactQty(value, props.integer ? 0 : 3)
}

function parse(value: string) {
  const text = value.trim().replaceAll(",", "").replaceAll("，", "")
  const multiplier = text.endsWith("万") ? 10000 : 1
  const number = Number(text.replace(/万$/, "")) * multiplier
  if (!Number.isFinite(number)) return props.modelValue
  const normalized = props.integer ? Math.round(number) : Math.round(number * 1000) / 1000
  return Math.max(normalized, props.min)
}

function syncDisplay() {
  displayValue.value = focused.value ? String(props.modelValue) : format(props.modelValue)
}

function onInput(value: string) {
  displayValue.value = value
  emit("update:modelValue", parse(value))
}

function onFocus() {
  focused.value = true
  displayValue.value = String(props.modelValue)
}

function onBlur() {
  focused.value = false
  const value = parse(displayValue.value)
  emit("update:modelValue", value)
  displayValue.value = format(value)
}

watch(
  () => props.modelValue,
  () => {
    if (!focused.value) syncDisplay()
  },
  { immediate: true }
)
</script>

<template>
  <el-input
    :model-value="displayValue"
    inputmode="decimal"
    @blur="onBlur"
    @focus="onFocus"
    @update:model-value="onInput"
  >
    <template v-if="unit" #append>
      {{ unit }}
    </template>
  </el-input>
</template>
