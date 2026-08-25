<script setup lang="ts">
import { ElMessage, ElMessageBox } from "element-plus"
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from "vue"
import { api, productQty, useLiveRefresh } from "./api"

const HOUR_MS = 60 * 60 * 1000
const DAY_MS = 24 * HOUR_MS
const LANE_LABEL_WIDTH = 112

const loading = ref(false)
const saving = ref(false)
const drawerVisible = ref(false)
const createDrawerVisible = ref(false)
const drawerTab = ref("pending")
const draggedRunId = ref<number | null>(null)
const pointerDrag = ref<{
  runId: number
  pointerId: number
  originClientX: number
  originScrollLeft: number
  sourceStartOffset: number
  sourceLineSlot: number
  moved: boolean
} | null>(null)
const suppressRunClick = ref(false)
const dropPreview = ref<{
  lineSlot: number
  left: number
  width: number
  label: string
  startAt: number
} | null>(null)
const pointerVisual = ref<{
  lineSlot: number
  left: number
  width: number
} | null>(null)
const timelineScroll = ref<HTMLElement>()
const runs = ref<any[]>([])
const products = ref<any[]>([])
const lineCount = ref(1)
const autoSnap = ref(true)
const pixelsPerDay = ref(112)
const today = () => new Date().toISOString().slice(0, 10)
const manualForm = reactive({
  product_id: undefined as number | undefined,
  planned_quantity: 1,
  line_slot: 1,
  planned_start_date: today(),
  notes: ""
})

const activeRuns = computed(() =>
  runs.value.filter(row => ["PLANNED", "RUNNING"].includes(row.status))
)
const pendingRuns = computed(() =>
  activeRuns.value.filter(row =>
    row.status === "PLANNED"
    && !row.schedule_locked
    && row.source_type !== "REPLENISHMENT"
  )
)
const confirmedRuns = computed(() =>
  activeRuns.value.filter(row =>
    row.status === "PLANNED"
    && row.schedule_locked
    && row.source_type !== "REPLENISHMENT"
  )
)
const manualRuns = computed(() =>
  activeRuns.value.filter(row =>
    row.status === "PLANNED" && row.source_type === "REPLENISHMENT"
  )
)
const runningRuns = computed(() =>
  activeRuns.value.filter(row => row.status === "RUNNING")
)
const lines = computed(() =>
  Array.from({ length: lineCount.value }, (_, index) => index + 1)
)
const selectedProduct = computed(() =>
  products.value.find(row => row.id === manualForm.product_id)
)

const timelineStart = computed(() => {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const starts = activeRuns.value.map(row => new Date(row.planned_start_at).getTime())
  const earliest = starts.length ? Math.min(...starts) : today.getTime()
  return new Date(Math.min(today.getTime(), earliest))
})
const timelineEnd = computed(() => {
  const minimum = timelineStart.value.getTime() + 14 * DAY_MS
  const ends = activeRuns.value.map(row => new Date(row.planned_end_at).getTime())
  const latest = ends.length ? Math.max(...ends) + 2 * DAY_MS : minimum
  return new Date(Math.max(minimum, latest))
})
const totalDays = computed(() =>
  Math.ceil((timelineEnd.value.getTime() - timelineStart.value.getTime()) / DAY_MS)
)
const timelineWidth = computed(() => totalDays.value * pixelsPerDay.value)
const axisTicks = computed(() =>
  Array.from({ length: totalDays.value + 1 }, (_, day) => ({
    day,
    label: formatDate(new Date(timelineStart.value.getTime() + day * DAY_MS))
  }))
)
const nowOffset = computed(() =>
  (Date.now() - timelineStart.value.getTime()) / DAY_MS * pixelsPerDay.value
)
const pointerPreviewRun = computed(() =>
  runs.value.find(row => row.id === pointerDrag.value?.runId)
)

function runsOnLine(lineSlot: number) {
  return activeRuns.value.filter(row => Number(row.line_slot) === lineSlot)
}

function durationHours(run: any) {
  return Math.max(
    (new Date(run.planned_end_at).getTime()
      - new Date(run.planned_start_at).getTime()) / HOUR_MS,
    1 / 60
  )
}

function blockStyle(run: any) {
  const start = new Date(run.planned_start_at).getTime()
  const left = (start - timelineStart.value.getTime()) / DAY_MS * pixelsPerDay.value
  const width = Math.max(durationHours(run) / 24 * pixelsPerDay.value, 18)
  return {
    "left": `${left}px`,
    "width": `${width}px`,
    "--block-hue": `${productHue(run.product_id)}`
  }
}

function productHue(productId: number) {
  return (Number(productId || 0) * 47 + 198) % 360
}

function durationLabel(run: any) {
  const hours = durationHours(run)
  if (hours < 24) return `${Math.max(Math.round(hours), 1)} 小时`
  return `${(hours / 24).toFixed(hours >= 240 ? 0 : 1)} 天`
}

function formatDate(value: string | Date) {
  const date = value instanceof Date ? value : new Date(value)
  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0")
  ].join("-")
}

function materialShortageText(run: any) {
  return (run.material_shortages || [])
    .map((row: any) => `${row.name}缺 ${productQty(row.shortage_quantity)} ${row.unit}`)
    .join("；")
}

function localDateTime(value: Date) {
  return `${formatDate(value)}T${[
    String(value.getHours()).padStart(2, "0"),
    String(value.getMinutes()).padStart(2, "0"),
    String(value.getSeconds()).padStart(2, "0")
  ].join(":")}`
}

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    const [settings, productionRuns, productRows] = await Promise.all([
      api<any>("/api/system/production-settings"),
      api<any[]>("/api/production/runs"),
      api<any[]>("/api/products")
    ])
    lineCount.value = Math.max(Number(settings.line_count || 1), 1)
    autoSnap.value = settings.schedule_auto_snap !== false
    runs.value = productionRuns
    products.value = productRows.filter(row => row.active !== false)
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    if (!silent) loading.value = false
  }
}

function startDrag(event: DragEvent, run: any) {
  if (run.status !== "PLANNED") return
  draggedRunId.value = run.id
  dropPreview.value = null
  event.dataTransfer?.setData("text/plain", String(run.id))
  if (event.dataTransfer) event.dataTransfer.effectAllowed = "move"
}

function draggedRun(event: DragEvent) {
  const runId = Number(
    event.dataTransfer?.getData("text/plain") || draggedRunId.value
  )
  return runs.value.find(row => row.id === runId)
}

function dropStartForEvent(event: DragEvent, lineSlot: number, run: any) {
  const track = event.currentTarget as HTMLElement
  const pointerOffset = event.clientX - track.getBoundingClientRect().left
  return dropStartForOffset(pointerOffset, lineSlot, run)
}

function dropStartForOffset(pointerOffset: number, lineSlot: number, run: any) {
  const blockStartOffset = Math.min(
    Math.max(pointerOffset, 0),
    timelineWidth.value
  )
  const pointerTime = timelineStart.value.getTime()
    + blockStartOffset / pixelsPerDay.value * DAY_MS
  const rawStart = new Date(pointerTime)
  const requested = autoSnap.value
    ? snappedDate(rawStart, lineSlot, run)
    : rawStart
  const nextMinute = new Date()
  nextMinute.setSeconds(0, 0)
  nextMinute.setMinutes(nextMinute.getMinutes() + 1)
  return requested < nextMinute ? nextMinute : requested
}

function previewDrop(event: DragEvent, lineSlot: number) {
  event.preventDefault()
  const run = draggedRun(event)
  if (!run || run.status !== "PLANNED") return
  const plannedStart = dropStartForEvent(event, lineSlot, run)
  const duration = Math.max(
    new Date(run.planned_end_at).getTime()
      - new Date(run.planned_start_at).getTime(),
    60 * 1000
  )
  dropPreview.value = {
    lineSlot,
    left: (plannedStart.getTime() - timelineStart.value.getTime())
      / DAY_MS * pixelsPerDay.value,
    width: Math.max(duration / DAY_MS * pixelsPerDay.value, 18),
    label: `落点 ${formatDate(plannedStart)}`,
    startAt: plannedStart.getTime()
  }
  if (event.dataTransfer) event.dataTransfer.dropEffect = "move"
}

function finishDrag() {
  draggedRunId.value = null
  dropPreview.value = null
  pointerVisual.value = null
}

function setDropPreview(run: any, lineSlot: number, plannedStart: Date) {
  const duration = Math.max(
    new Date(run.planned_end_at).getTime()
      - new Date(run.planned_start_at).getTime(),
    60 * 1000
  )
  dropPreview.value = {
    lineSlot,
    left: (plannedStart.getTime() - timelineStart.value.getTime())
      / DAY_MS * pixelsPerDay.value,
    width: Math.max(duration / DAY_MS * pixelsPerDay.value, 18),
    label: `开始 ${formatDate(plannedStart)}`,
    startAt: plannedStart.getTime()
  }
}

function setPointerVisual(run: any, lineSlot: number, rawLeft: number) {
  const duration = Math.max(
    new Date(run.planned_end_at).getTime()
      - new Date(run.planned_start_at).getTime(),
    60 * 1000
  )
  pointerVisual.value = {
    lineSlot,
    left: Math.min(Math.max(rawLeft, 0), timelineWidth.value),
    width: Math.max(duration / DAY_MS * pixelsPerDay.value, 18)
  }
}

async function saveSchedule(run: any, lineSlot: number, plannedStart: Date) {
  saving.value = true
  try {
    const updated = await api<any>(`/api/production/runs/${run.id}/schedule`, {
      method: "PUT",
      body: JSON.stringify({
        line_slot: lineSlot,
        planned_start_at: localDateTime(plannedStart)
      })
    })
    ElMessage.success(
      `${run.product_name} 已安排到生产位 ${lineSlot}，开始日期 ${formatDate(updated.planned_start_at)}`
    )
    if (!updated.materials_ready) {
      ElMessage.warning(`排期已保存；开工前请补料：${materialShortageText(updated)}`)
    }
    await load(true)
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    saving.value = false
    finishDrag()
  }
}

async function dropRun(event: DragEvent, lineSlot: number) {
  event.preventDefault()
  const run = draggedRun(event)
  if (!run || run.status !== "PLANNED") return
  const plannedStart = dropPreview.value?.lineSlot === lineSlot
    ? new Date(dropPreview.value.startAt)
    : dropStartForEvent(event, lineSlot, run)

  await saveSchedule(run, lineSlot, plannedStart)
}

function snappedDate(rawDate: Date, lineSlot: number, run: any) {
  const duration = Math.max(
    new Date(run.planned_end_at).getTime()
      - new Date(run.planned_start_at).getTime(),
    60 * 1000
  )
  const dayOffset = (rawDate.getTime() - timelineStart.value.getTime()) / DAY_MS
  const gridCandidate = timelineStart.value.getTime()
    + Math.floor(dayOffset) * DAY_MS
  const otherRuns = runsOnLine(lineSlot).filter(row => row.id !== run.id)
  const conflicts = (candidate: number) => otherRuns.some(row => {
    const rowStart = new Date(row.planned_start_at).getTime()
    const rowEnd = new Date(row.planned_end_at).getTime()
    return candidate < rowEnd && candidate + duration > rowStart
  })
  const edgeCandidates: number[] = []
  for (const row of runsOnLine(lineSlot)) {
    if (row.id === run.id) continue
    const rowStart = new Date(row.planned_start_at).getTime()
    const rowEnd = new Date(row.planned_end_at).getTime()
    // 前贴：当前块结束位置贴住现有块开始；后贴：当前块起点贴住现有块结束。
    edgeCandidates.push(rowStart - duration, rowEnd)
  }
  const validEdges = [...new Set(edgeCandidates)]
    .filter(candidate => !conflicts(candidate))
    .sort((left, right) =>
      Math.abs(left - rawDate.getTime()) - Math.abs(right - rawDate.getTime())
    )
  const nearestEdge = validEdges[0]
  const snapThreshold = 28 / pixelsPerDay.value * DAY_MS
  if (nearestEdge !== undefined
      && (Math.abs(nearestEdge - rawDate.getTime()) <= snapThreshold
        || conflicts(rawDate.getTime()))) {
    return new Date(nearestEdge)
  }
  if (!conflicts(gridCandidate)) return new Date(gridCandidate)
  return new Date(nearestEdge ?? gridCandidate)
}

function laneAtPoint(clientX: number, clientY: number) {
  const lane = document.elementsFromPoint(clientX, clientY)
    .map(element => element.closest(".lane-track"))
    .find(Boolean) as HTMLElement | undefined
  const lineSlot = Number(lane?.dataset.lineSlot)
  return Number.isInteger(lineSlot) && lineSlot > 0 ? lineSlot : null
}

function autoScrollTimeline(clientX: number) {
  const scroll = timelineScroll.value
  if (!scroll) return
  const rect = scroll.getBoundingClientRect()
  const edge = 44
  if (clientX < rect.left + edge) scroll.scrollLeft -= 18
  if (clientX > rect.right - edge) scroll.scrollLeft += 18
}

function removePointerListeners() {
  window.removeEventListener("pointermove", moveTimelineBlock)
  window.removeEventListener("pointerup", finishTimelineBlock)
  window.removeEventListener("pointercancel", cancelTimelineBlock)
  document.body.classList.remove("timeline-pointer-dragging")
}

function startTimelineBlock(event: PointerEvent, run: any) {
  if (run.status !== "PLANNED" || event.button !== 0 || saving.value) return
  event.preventDefault()
  const sourceStartOffset = (new Date(run.planned_start_at).getTime()
    - timelineStart.value.getTime()) / DAY_MS * pixelsPerDay.value
  pointerDrag.value = {
    runId: run.id,
    pointerId: event.pointerId,
    originClientX: event.clientX,
    originScrollLeft: timelineScroll.value?.scrollLeft || 0,
    sourceStartOffset,
    sourceLineSlot: Number(run.line_slot),
    moved: false
  }
  draggedRunId.value = run.id
  dropPreview.value = null
  pointerVisual.value = null
  document.body.classList.add("timeline-pointer-dragging")
  window.addEventListener("pointermove", moveTimelineBlock, { passive: false })
  window.addEventListener("pointerup", finishTimelineBlock)
  window.addEventListener("pointercancel", cancelTimelineBlock)
}

function moveTimelineBlock(event: PointerEvent) {
  const state = pointerDrag.value
  if (!state || event.pointerId !== state.pointerId) return
  const run = runs.value.find(row => row.id === state.runId)
  if (!run) return cancelTimelineBlock()
  const deltaX = event.clientX - state.originClientX
  if (!state.moved && Math.abs(deltaX) < 4) return
  event.preventDefault()
  state.moved = true
  autoScrollTimeline(event.clientX)
  const scrollDelta = (timelineScroll.value?.scrollLeft || 0) - state.originScrollLeft
  const blockStartOffset = state.sourceStartOffset + deltaX + scrollDelta
  const lineSlot = laneAtPoint(event.clientX, event.clientY)
    ?? dropPreview.value?.lineSlot
    ?? state.sourceLineSlot
  setPointerVisual(run, lineSlot, blockStartOffset)
  const plannedStart = dropStartForOffset(blockStartOffset, lineSlot, run)
  setDropPreview(run, lineSlot, plannedStart)
}

async function finishTimelineBlock(event: PointerEvent) {
  const state = pointerDrag.value
  if (!state || event.pointerId !== state.pointerId) return
  const run = runs.value.find(row => row.id === state.runId)
  const preview = dropPreview.value ? { ...dropPreview.value } : null
  removePointerListeners()
  pointerDrag.value = null
  if (!state.moved || !run || !preview) {
    finishDrag()
    return
  }
  event.preventDefault()
  suppressRunClick.value = true
  await saveSchedule(run, preview.lineSlot, new Date(preview.startAt))
  window.setTimeout(() => {
    suppressRunClick.value = false
  }, 0)
}

function cancelTimelineBlock() {
  removePointerListeners()
  pointerDrag.value = null
  finishDrag()
}

function openTimelineRun(run: any) {
  if (suppressRunClick.value) return
  openRuns(run.status === "RUNNING"
    ? "running"
    : run.source_type === "REPLENISHMENT"
      ? "manual"
      : run.schedule_locked ? "confirmed" : "pending")
}

async function unlockSchedule(run: any) {
  try {
    await ElMessageBox.confirm(
      `恢复“${run.product_name}”为系统自动建议排期吗？`,
      "恢复自动排期",
      { type: "warning" }
    )
    await api(`/api/production/runs/${run.id}/schedule`, { method: "DELETE" })
    ElMessage.success("已恢复自动建议排期")
    await load(true)
  } catch (error: any) {
    if (error !== "cancel") ElMessage.error(error.message)
  }
}

function zoom(delta: number) {
  pixelsPerDay.value = Math.min(Math.max(pixelsPerDay.value + delta, 72), 200)
}

async function scrollToNow() {
  await nextTick()
  if (!timelineScroll.value) return
  timelineScroll.value.scrollLeft = Math.max(
    nowOffset.value - timelineScroll.value.clientWidth / 3 + LANE_LABEL_WIDTH,
    0
  )
}

function openRuns(tab = "pending") {
  drawerTab.value = tab
  drawerVisible.value = true
}

function disablePastDate(value: Date) {
  const current = new Date()
  current.setHours(0, 0, 0, 0)
  return value.getTime() < current.getTime()
}

function openCreatePlan() {
  manualForm.product_id = undefined
  manualForm.planned_quantity = 1
  manualForm.line_slot = 1
  manualForm.planned_start_date = today()
  manualForm.notes = ""
  createDrawerVisible.value = true
}

async function createManualPlan() {
  if (!manualForm.product_id) return ElMessage.warning("请选择产品")
  if (!Number.isInteger(Number(manualForm.planned_quantity))
      || Number(manualForm.planned_quantity) <= 0) {
    return ElMessage.warning("计划数量必须是正整数")
  }
  if (!Number(selectedProduct.value?.daily_capacity || 0)) {
    return ElMessage.warning("该产品未设置单机日产能，请先在产品目录中配置")
  }
  saving.value = true
  try {
    await api("/api/production/runs/manual", {
      method: "POST",
      body: JSON.stringify(manualForm)
    })
    ElMessage.success("自主生产计划已加入排产图")
    createDrawerVisible.value = false
    await load(true)
    openRuns("manual")
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    saving.value = false
  }
}

async function cancelManualRun(run: any) {
  try {
    await ElMessageBox.confirm(
      `确认取消自主计划“${run.run_no}”吗？`,
      "取消生产计划",
      { type: "warning" }
    )
    await api(`/api/production/runs/${run.id}/status`, {
      method: "PUT",
      body: JSON.stringify({ status: "CANCELLED" })
    })
    ElMessage.success("自主生产计划已取消")
    await load(true)
  } catch (error: any) {
    if (error !== "cancel") ElMessage.error(error.message)
  }
}

onMounted(async () => {
  await load()
  await scrollToNow()
})
onUnmounted(removePointerListeners)
useLiveRefresh(() => load(true))
</script>

<template>
  <div class="erp-page scheduling-page">
    <div class="page-toolbar">
      <div class="toolbar-group">
        <el-alert
          title="排产图按日期显示；时间块长度根据生产数量和产品目录中的单机日产量计算。"
          type="info"
          :closable="false"
          show-icon
        />
      </div>
      <div class="toolbar-right">
        <el-button-group>
          <el-button :disabled="pixelsPerDay <= 72" @click="zoom(-16)">
            缩小
          </el-button>
          <el-button @click="scrollToNow">
            现在
          </el-button>
          <el-button :disabled="pixelsPerDay >= 200" @click="zoom(16)">
            放大
          </el-button>
        </el-button-group>
        <el-button @click="openCreatePlan">
          新建生产计划
        </el-button>
        <el-button type="primary" @click="openRuns()">
          <el-badge :value="pendingRuns.length" :hidden="!pendingRuns.length">
            <span>待排产</span>
          </el-badge>
        </el-button>
      </div>
    </div>

    <div class="content-card schedule-card" v-loading="loading || saving">
      <div class="card-head">
        <h3>订单排产</h3>
        <span>
          {{ lineCount }} 个生产位 · {{ pendingRuns.length }} 个系统建议 ·
          {{ manualRuns.length }} 个自主计划 · {{ runningRuns.length }} 个生产中
        </span>
      </div>
      <div ref="timelineScroll" class="timeline-scroll">
        <div
          class="timeline-grid"
          :style="{ width: `${timelineWidth + LANE_LABEL_WIDTH}px` }"
        >
          <div class="axis-row">
            <div class="lane-label axis-label">
              日期
            </div>
            <div class="axis-track" :style="{ width: `${timelineWidth}px` }">
              <div
                v-for="tick in axisTicks"
                :key="tick.day"
                class="axis-tick"
                :style="{ left: `${tick.day * pixelsPerDay}px` }"
              >
                <span>{{ tick.label }}</span>
              </div>
            </div>
          </div>

          <div v-for="lineSlot in lines" :key="lineSlot" class="lane-row">
            <div class="lane-label">
              <strong>{{ lineSlot }} 号机</strong>
              <span>{{ runsOnLine(lineSlot).length }} 个批次</span>
            </div>
            <div
              class="lane-track"
              :data-line-slot="lineSlot"
              :style="{
                'width': `${timelineWidth}px`,
                '--day-width': `${pixelsPerDay}px`,
              }"
              @dragover="previewDrop($event, lineSlot)"
              @drop="dropRun($event, lineSlot)"
            >
              <div
                v-if="nowOffset >= 0 && nowOffset <= timelineWidth"
                class="now-line"
                :style="{ left: `${nowOffset}px` }"
              />
              <div
                v-if="dropPreview?.lineSlot === lineSlot"
                class="drop-preview"
                :style="{
                  left: `${dropPreview.left}px`,
                  width: `${dropPreview.width}px`,
                }"
              >
                <span>{{ dropPreview.label }}</span>
              </div>
              <div
                v-if="pointerVisual?.lineSlot === lineSlot && pointerPreviewRun"
                class="schedule-block pointer-visual"
                :style="{
                  left: `${pointerVisual.left}px`,
                  width: `${pointerVisual.width}px`,
                  '--block-hue': `${productHue(pointerPreviewRun.product_id)}`,
                }"
              >
                <strong>{{ pointerPreviewRun.product_name }}</strong>
                <span>
                  {{ productQty(pointerPreviewRun.planned_quantity) }}
                  {{ pointerPreviewRun.unit }} · {{ durationLabel(pointerPreviewRun) }}
                </span>
              </div>
              <div
                v-for="run in runsOnLine(lineSlot)"
                :key="run.id"
                class="schedule-block"
                :class="{
                  suggested: run.status === 'PLANNED' && !run.schedule_locked,
                  confirmed: run.status === 'PLANNED' && run.schedule_locked,
                  manual: run.source_type === 'REPLENISHMENT',
                  running: run.status === 'RUNNING',
                  'is-pointer-dragging': pointerDrag?.runId === run.id
                    && pointerDrag?.moved,
                }"
                :style="blockStyle(run)"
                @pointerdown="startTimelineBlock($event, run)"
                @click="openTimelineRun(run)"
              >
                <strong>{{ run.product_name }}</strong>
                <span>
                  {{ productQty(run.planned_quantity) }} {{ run.unit }} ·
                  {{ durationLabel(run) }}
                </span>
                <em v-if="run.status === 'RUNNING'">生产中</em>
                <em v-else-if="!run.materials_ready" class="shortage-mark">缺料</em>
                <em v-else-if="run.source_type === 'REPLENISHMENT'">自主计划</em>
                <em v-else-if="run.schedule_locked">人工调整</em>
                <em v-else>建议</em>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div class="timeline-legend">
        <span><i class="legend-dot suggested-dot" />系统建议：来自未满足客单</span>
        <span><i class="legend-dot manual-dot" />自主计划：用于主动补库存</span>
        <span><i class="legend-dot confirmed-dot" />已人工排定，可继续拖动</span>
        <span><i class="legend-dot running-dot" />正在生产，不可拖动</span>
      </div>
    </div>

    <el-drawer
      v-model="drawerVisible"
      title="排产批次"
      size="min(520px, 94vw)"
      :modal="false"
    >
      <el-tabs v-model="drawerTab">
        <el-tab-pane :label="`系统建议 ${pendingRuns.length}`" name="pending">
          <el-empty
            v-if="!pendingRuns.length"
            description="当前没有系统建议排期"
          />
          <div v-else class="run-list">
            <article
              v-for="run in pendingRuns"
              :key="run.id"
              class="run-card pending-card"
              :style="{ '--block-hue': `${productHue(run.product_id)}` }"
              draggable="true"
              @dragstart="startDrag($event, run)"
              @dragend="finishDrag"
            >
              <div class="run-card-head">
                <strong>{{ run.product_name }}</strong>
                <el-button link type="primary" @click="$router.push('/lite-production/completion')">
                  登记完工
                </el-button>
              </div>
              <span>{{ run.product_sku }} · {{ run.run_no }}</span>
              <div class="run-metrics">
                <b>{{ productQty(run.planned_quantity) }} {{ run.unit }}</b>
                <span>{{ durationLabel(run) }}</span>
                <span>建议生产位 {{ run.line_slot }}</span>
              </div>
              <small>
                建议 {{ formatDate(run.planned_start_at) }} 至
                {{ formatDate(run.planned_end_at) }}
              </small>
              <el-alert
                v-if="!run.materials_ready"
                :title="materialShortageText(run)"
                type="warning"
                :closable="false"
                show-icon
              />
            </article>
          </div>
        </el-tab-pane>
        <el-tab-pane :label="`已人工排定 ${confirmedRuns.length}`" name="confirmed">
          <el-empty v-if="!confirmedRuns.length" description="暂无已人工排定批次" />
          <div v-else class="run-list">
            <article
              v-for="run in confirmedRuns"
              :key="run.id"
              class="run-card confirmed-card"
              :style="{ '--block-hue': `${productHue(run.product_id)}` }"
              draggable="true"
              @dragstart="startDrag($event, run)"
              @dragend="finishDrag"
            >
              <div class="run-card-head">
                <strong>{{ run.product_name }}</strong>
                <div>
                  <el-button link type="primary" @click="$router.push('/lite-production/completion')">
                    登记完工
                  </el-button>
                  <el-button link @click="unlockSchedule(run)">
                    恢复自动
                  </el-button>
                </div>
              </div>
              <span>{{ run.product_sku }} · {{ run.run_no }}</span>
              <div class="run-metrics">
                <b>{{ productQty(run.planned_quantity) }} {{ run.unit }}</b>
                <span>生产位 {{ run.line_slot }}</span>
                <span>模具位 {{ run.mold_slot }}</span>
              </div>
              <small>
                {{ formatDate(run.planned_start_at) }} 至
                {{ formatDate(run.planned_end_at) }}
              </small>
              <el-alert
                v-if="!run.materials_ready"
                :title="materialShortageText(run)"
                type="warning"
                :closable="false"
                show-icon
              />
            </article>
          </div>
        </el-tab-pane>
        <el-tab-pane :label="`自主计划 ${manualRuns.length}`" name="manual">
          <el-empty
            v-if="!manualRuns.length"
            description="暂无主动补库存计划，可点击页面上方“新建生产计划”"
          />
          <div v-else class="run-list">
            <article
              v-for="run in manualRuns"
              :key="run.id"
              class="run-card manual-card"
              :style="{ '--block-hue': `${productHue(run.product_id)}` }"
              draggable="true"
              @dragstart="startDrag($event, run)"
              @dragend="finishDrag"
            >
              <div class="run-card-head">
                <strong>{{ run.product_name }}</strong>
                <div>
                  <el-button link type="primary" @click="$router.push('/lite-production/completion')">
                    登记完工
                  </el-button>
                  <el-button link type="danger" @click="cancelManualRun(run)">
                    取消
                  </el-button>
                </div>
              </div>
              <span>{{ run.product_sku }} · {{ run.run_no }} · 主动补库存</span>
              <div class="run-metrics">
                <b>{{ productQty(run.planned_quantity) }} {{ run.unit }}</b>
                <span>生产位 {{ run.line_slot }}</span>
                <span>{{ durationLabel(run) }}</span>
              </div>
              <small>
                {{ formatDate(run.planned_start_at) }} 至
                {{ formatDate(run.planned_end_at) }}
                <template v-if="run.notes"> · {{ run.notes }}</template>
              </small>
              <el-alert
                v-if="!run.materials_ready"
                :title="materialShortageText(run)"
                type="warning"
                :closable="false"
                show-icon
              />
            </article>
          </div>
        </el-tab-pane>
        <el-tab-pane :label="`生产中 ${runningRuns.length}`" name="running">
          <el-empty v-if="!runningRuns.length" description="当前没有生产中批次" />
          <div v-else class="run-list">
            <article
              v-for="run in runningRuns"
              :key="run.id"
              class="run-card running-card"
            >
              <div class="run-card-head">
                <strong>{{ run.product_name }}</strong>
                <el-tag type="warning" size="small">
                  生产中
                </el-tag>
              </div>
              <span>{{ run.product_sku }} · 生产位 {{ run.line_slot }}</span>
              <small>预计 {{ formatDate(run.planned_end_at) }} 完成</small>
            </article>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-drawer>

    <el-drawer
      v-model="createDrawerVisible"
      title="新建自主生产计划"
      size="min(520px, 94vw)"
    >
      <el-alert
        title="用于主动补充成品库存；若存在同产品的客单缺口，系统会优先按交期分配本批次，剩余数量完工后进入自由库存。"
        type="info"
        :closable="false"
        show-icon
      />
      <el-form label-position="top" class="create-plan-form">
        <el-form-item label="产品" required>
          <el-select
            v-model="manualForm.product_id"
            filterable
            placeholder="按编码或名称选择产品"
            style="width: 100%"
          >
            <el-option
              v-for="product in products"
              :key="product.id"
              :label="`${product.sku} · ${product.name}`"
              :value="product.id"
            >
              <div class="product-option">
                <span>{{ product.sku }} · {{ product.name }}</span>
                <small>
                  {{ product.daily_capacity > 0
                    ? `日产能 ${productQty(product.daily_capacity)} ${product.unit}`
                    : '未配置日产能' }}
                </small>
              </div>
            </el-option>
          </el-select>
        </el-form-item>
        <el-alert
          v-if="selectedProduct && !Number(selectedProduct.daily_capacity || 0)"
          title="该产品的单机日产能为 0，请先在产品目录编辑产品后再排产。"
          type="warning"
          :closable="false"
          show-icon
        />
        <div class="form-grid">
          <el-form-item label="计划数量" required>
            <el-input-number
              v-model="manualForm.planned_quantity"
              :min="1"
              :precision="0"
              style="width: 100%"
            />
          </el-form-item>
          <el-form-item label="生产位" required>
            <el-select v-model="manualForm.line_slot" style="width: 100%">
              <el-option
                v-for="line in lines"
                :key="line"
                :label="`${line} 号机`"
                :value="line"
              />
            </el-select>
          </el-form-item>
        </div>
        <el-form-item label="计划开始日期" required>
          <el-date-picker
            v-model="manualForm.planned_start_date"
            type="date"
            value-format="YYYY-MM-DD"
            :disabled-date="disablePastDate"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="manualForm.notes" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <div class="drawer-footer">
        <el-button @click="createDrawerVisible = false">
          取消
        </el-button>
        <el-button type="primary" :loading="saving" @click="createManualPlan">
          创建并加入排产图
        </el-button>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.page-toolbar .el-alert {
  min-width: min(680px, 55vw);
}

.schedule-card {
  overflow: hidden;
}

.timeline-scroll {
  overflow: auto;
  max-height: calc(100vh - 300px);
  min-height: 310px;
  border-top: 1px solid var(--el-border-color-lighter);
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.timeline-grid {
  position: relative;
  min-width: 100%;
}

.axis-row,
.lane-row {
  display: flex;
}

.axis-row {
  position: sticky;
  top: 0;
  z-index: 8;
  height: 46px;
  background: var(--el-bg-color);
  border-bottom: 1px solid var(--el-border-color);
}

.lane-row {
  height: 60px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.lane-label {
  position: sticky;
  left: 0;
  z-index: 6;
  box-sizing: border-box;
  display: flex;
  flex: 0 0 112px;
  flex-direction: column;
  justify-content: center;
  width: 112px;
  padding: 0 14px;
  background: var(--el-bg-color);
  border-right: 1px solid var(--el-border-color);
}

.lane-label strong {
  font-size: 14px;
}

.lane-label span {
  margin-top: 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.axis-label {
  z-index: 10;
  color: var(--el-text-color-regular);
  font-weight: 600;
}

.axis-track,
.lane-track {
  position: relative;
  flex: 0 0 auto;
}

.axis-tick {
  position: absolute;
  top: 0;
  bottom: 0;
  border-left: 1px solid var(--el-border-color-lighter);
}

.axis-tick span {
  position: absolute;
  top: 14px;
  left: 8px;
  width: 110px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  white-space: nowrap;
}

.lane-track {
  background-color: var(--el-fill-color-extra-light);
  background-image: repeating-linear-gradient(
    to right,
    transparent 0,
    transparent calc(var(--day-width) - 1px),
    var(--el-border-color) calc(var(--day-width) - 1px),
    var(--el-border-color) var(--day-width)
  );
}

.lane-track:hover {
  background-color: var(--el-color-primary-light-9);
}

.now-line {
  position: absolute;
  top: 0;
  bottom: 0;
  z-index: 4;
  width: 2px;
  background: var(--el-color-danger);
  pointer-events: none;
}

.drop-preview {
  position: absolute;
  top: 5px;
  z-index: 7;
  box-sizing: border-box;
  height: 50px;
  background: color-mix(in srgb, var(--el-color-primary) 12%, transparent);
  border: 2px dashed var(--el-color-primary);
  border-radius: 7px;
  pointer-events: none;
}

.drop-preview span {
  position: absolute;
  top: 50%;
  left: 8px;
  padding: 2px 6px;
  color: var(--el-color-primary-dark-2);
  background: rgb(255 255 255 / 88%);
  border-radius: 4px;
  font-size: 11px;
  white-space: nowrap;
  transform: translateY(-50%);
}

.schedule-block {
  position: absolute;
  top: 9px;
  z-index: 3;
  box-sizing: border-box;
  height: 42px;
  padding: 5px 8px;
  overflow: hidden;
  color: hsl(var(--block-hue), 42%, 24%);
  background: hsl(var(--block-hue), 72%, 87%);
  border: 1px solid hsl(var(--block-hue), 60%, 62%);
  border-radius: 7px;
  box-shadow: 0 2px 5px rgb(0 0 0 / 8%);
  cursor: grab;
  touch-action: none;
  user-select: none;
}

.schedule-block.is-pointer-dragging {
  opacity: 0.2;
}

.schedule-block.pointer-visual {
  z-index: 6;
  cursor: grabbing;
  opacity: 0.88;
  pointer-events: none;
  box-shadow: 0 6px 16px rgb(0 0 0 / 18%);
}

.schedule-block:active {
  cursor: grabbing;
}

.schedule-block strong,
.schedule-block span {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.schedule-block strong {
  font-size: 13px;
}

.schedule-block span {
  margin-top: 1px;
  font-size: 11px;
  opacity: 0.82;
}

.schedule-block em {
  position: absolute;
  top: 5px;
  right: 6px;
  padding: 1px 4px;
  background: rgb(255 255 255 / 72%);
  border-radius: 3px;
  font-size: 10px;
  font-style: normal;
}

.schedule-block.suggested {
  background: hsl(var(--block-hue), 65%, 94%);
  border-style: dashed;
}

.schedule-block.running {
  color: #633c04;
  background: var(--el-color-warning-light-7);
  border-color: var(--el-color-warning);
  cursor: default;
}

.timeline-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 22px;
  padding: 14px 20px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.timeline-legend span {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}

.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 3px;
}

.suggested-dot {
  background: var(--el-color-primary-light-8);
  border: 1px dashed var(--el-color-primary);
}

.confirmed-dot {
  background: var(--el-color-primary-light-5);
}

.schedule-block em.shortage-mark {
  color: var(--el-color-danger);
  background: var(--el-color-danger-light-9);
}

.manual-dot {
  background: var(--el-color-success-light-5);
}

.running-dot {
  background: var(--el-color-warning-light-5);
}

.run-list {
  display: grid;
  gap: 12px;
}

.run-card {
  --block-hue: 210;
  display: grid;
  gap: 8px;
  padding: 15px 16px;
  background: var(--el-fill-color-extra-light);
  border: 1px solid var(--el-border-color-lighter);
  border-left: 4px solid hsl(var(--block-hue), 58%, 55%);
  border-radius: 8px;
}

.pending-card,
.confirmed-card {
  cursor: grab;
}

.run-card-head,
.run-metrics {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.run-card > span,
.run-card small,
.run-metrics span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.run-metrics {
  justify-content: flex-start;
}

.run-metrics b {
  margin-right: auto;
}

.running-card {
  border-left-color: var(--el-color-warning);
}

.manual-card {
  border-left-color: var(--el-color-success);
  cursor: grab;
}

.schedule-block.manual {
  background: var(--el-color-success-light-8);
  border-color: var(--el-color-success);
}

.schedule-block.running.manual {
  color: #633c04;
  background: var(--el-color-warning-light-7);
  border-color: var(--el-color-warning);
}

.create-plan-form {
  margin-top: 20px;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.product-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
}

.product-option small {
  color: var(--el-text-color-secondary);
}

@media (max-width: 900px) {
  .page-toolbar .el-alert {
    min-width: 100%;
  }

  .timeline-scroll {
    max-height: none;
  }

  .form-grid {
    grid-template-columns: 1fr;
    gap: 0;
  }
}
</style>
