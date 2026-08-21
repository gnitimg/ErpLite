<script setup lang="ts">
import { ElMessage, ElMessageBox } from "element-plus"
import { computed, nextTick, onMounted, ref } from "vue"
import { api, productQty, useLiveRefresh } from "./api"

const HOUR_MS = 60 * 60 * 1000
const DAY_MS = 24 * HOUR_MS
const LANE_LABEL_WIDTH = 112

const loading = ref(false)
const saving = ref(false)
const drawerVisible = ref(false)
const drawerTab = ref("pending")
const draggedRunId = ref<number | null>(null)
const timelineScroll = ref<HTMLElement>()
const runs = ref<any[]>([])
const lineCount = ref(1)
const autoSnap = ref(true)
const pixelsPerDay = ref(112)

const activeRuns = computed(() =>
  runs.value.filter(row => ["PLANNED", "RUNNING"].includes(row.status))
)
const pendingRuns = computed(() =>
  activeRuns.value.filter(row => row.status === "PLANNED" && !row.schedule_locked)
)
const confirmedRuns = computed(() =>
  activeRuns.value.filter(row => row.status === "PLANNED" && row.schedule_locked)
)
const runningRuns = computed(() =>
  activeRuns.value.filter(row => row.status === "RUNNING")
)
const lines = computed(() =>
  Array.from({ length: lineCount.value }, (_, index) => index + 1)
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
    left: `${left}px`,
    width: `${width}px`,
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

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    const [settings, productionRuns] = await Promise.all([
      api<any>("/api/system/production-settings"),
      api<any[]>("/api/production/runs")
    ])
    lineCount.value = Math.max(Number(settings.line_count || 1), 1)
    autoSnap.value = settings.schedule_auto_snap !== false
    runs.value = productionRuns
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    if (!silent) loading.value = false
  }
}

function startDrag(event: DragEvent, run: any) {
  if (run.status !== "PLANNED") return
  draggedRunId.value = run.id
  event.dataTransfer?.setData("text/plain", String(run.id))
  if (event.dataTransfer) event.dataTransfer.effectAllowed = "move"
}

async function dropRun(event: DragEvent, lineSlot: number) {
  event.preventDefault()
  const runId = Number(
    event.dataTransfer?.getData("text/plain") || draggedRunId.value
  )
  const track = event.currentTarget as HTMLElement
  const run = runs.value.find(row => row.id === runId)
  if (!run || run.status !== "PLANNED") return

  const offset = Math.max(event.clientX - track.getBoundingClientRect().left, 0)
  const rawDate = new Date(
    timelineStart.value.getTime() + offset / pixelsPerDay.value * DAY_MS
  )
  const requested = autoSnap.value
    ? snappedDate(rawDate, lineSlot, run.id)
    : rawDate
  const nextHour = new Date()
  nextHour.setMinutes(0, 0, 0)
  nextHour.setHours(nextHour.getHours() + 1)
  const plannedStart = requested < nextHour ? nextHour : requested

  saving.value = true
  try {
    await api(`/api/production/runs/${run.id}/schedule`, {
      method: "PUT",
      body: JSON.stringify({
        line_slot: lineSlot,
        planned_start_at: plannedStart.toISOString()
      })
    })
    ElMessage.success(`${run.product_name} 已安排到生产位 ${lineSlot}`)
    await load(true)
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    saving.value = false
    draggedRunId.value = null
  }
}

function snappedDate(rawDate: Date, lineSlot: number, runId: number) {
  const dayOffset = (rawDate.getTime() - timelineStart.value.getTime()) / DAY_MS
  const candidates = [
    timelineStart.value.getTime() + Math.round(dayOffset) * DAY_MS
  ]
  for (const row of runsOnLine(lineSlot)) {
    if (row.id === runId || (!row.schedule_locked && row.status !== "RUNNING")) {
      continue
    }
    candidates.push(new Date(row.planned_start_at).getTime())
    candidates.push(new Date(row.planned_end_at).getTime())
  }
  const nearest = candidates.reduce((best, candidate) =>
    Math.abs(candidate - rawDate.getTime()) < Math.abs(best - rawDate.getTime())
      ? candidate
      : best
  )
  return new Date(nearest)
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

async function recalculate() {
  loading.value = true
  try {
    await api("/api/production/plan/recalculate", { method: "POST" })
    ElMessage.success("建议排期已重算，人工确认的时间块保持不变")
    await load(true)
  } catch (error: any) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
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

onMounted(async () => {
  await load()
  await scrollToNow()
})
useLiveRefresh(() => load(true))
</script>

<template>
  <div class="erp-page scheduling-page">
    <div class="page-toolbar">
      <div class="toolbar-group">
        <el-alert
          title="排产图按日期显示；时间块长度根据生产数量和该产品的单日单机有效产量计算。"
          type="info"
          :closable="false"
          show-icon
        />
      </div>
      <div class="toolbar-right">
        <el-button-group>
          <el-button :disabled="pixelsPerDay <= 72" @click="zoom(-16)">缩小</el-button>
          <el-button @click="scrollToNow">现在</el-button>
          <el-button :disabled="pixelsPerDay >= 200" @click="zoom(16)">放大</el-button>
        </el-button-group>
        <el-tag :type="autoSnap ? 'success' : 'info'" effect="plain">
          {{ autoSnap ? "自动吸附" : "自由拖动" }}
        </el-tag>
        <el-button :loading="loading" @click="recalculate">
          <el-icon><Refresh /></el-icon>重算建议
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
          {{ lineCount }} 个生产位 · {{ pendingRuns.length }} 个待确认批次 ·
          {{ confirmedRuns.length }} 个已确认批次
        </span>
      </div>
      <div ref="timelineScroll" class="timeline-scroll">
        <div
          class="timeline-grid"
          :style="{ width: `${timelineWidth + LANE_LABEL_WIDTH}px` }"
        >
          <div class="axis-row">
            <div class="lane-label axis-label">日期</div>
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
              <strong>生产位 {{ lineSlot }}</strong>
              <span>{{ runsOnLine(lineSlot).length }} 个批次</span>
            </div>
            <div
              class="lane-track"
              :style="{
                width: `${timelineWidth}px`,
                '--day-width': `${pixelsPerDay}px`
              }"
              @dragover.prevent
              @drop="dropRun($event, lineSlot)"
            >
              <div
                v-if="nowOffset >= 0 && nowOffset <= timelineWidth"
                class="now-line"
                :style="{ left: `${nowOffset}px` }"
              />
              <div
                v-for="run in runsOnLine(lineSlot)"
                :key="run.id"
                class="schedule-block"
                :class="{
                  suggested: run.status === 'PLANNED' && !run.schedule_locked,
                  confirmed: run.status === 'PLANNED' && run.schedule_locked,
                  running: run.status === 'RUNNING'
                }"
                :style="blockStyle(run)"
                :draggable="run.status === 'PLANNED'"
                @dragstart="startDrag($event, run)"
                @click="openRuns(run.schedule_locked ? 'confirmed' : 'pending')"
              >
                <strong>{{ run.product_name }}</strong>
                <span>
                  {{ productQty(run.planned_quantity) }} {{ run.unit }} ·
                  {{ durationLabel(run) }}
                </span>
                <em v-if="run.status === 'RUNNING'">生产中</em>
                <em v-else-if="run.schedule_locked">已确认</em>
                <em v-else>建议</em>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div class="timeline-legend">
        <span><i class="legend-dot suggested-dot" />系统建议，可拖动确认</span>
        <span><i class="legend-dot confirmed-dot" />人工确认，可继续拖动</span>
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
        <el-tab-pane :label="`待确认 ${pendingRuns.length}`" name="pending">
          <el-empty
            v-if="!pendingRuns.length"
            description="当前没有待确认的建议排期"
          />
          <div v-else class="run-list">
            <article
              v-for="run in pendingRuns"
              :key="run.id"
              class="run-card pending-card"
              :style="{ '--block-hue': `${productHue(run.product_id)}` }"
              draggable="true"
              @dragstart="startDrag($event, run)"
            >
              <div class="run-card-head">
                <strong>{{ run.product_name }}</strong>
                <el-tag size="small" effect="plain">拖至时间轴</el-tag>
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
            </article>
          </div>
        </el-tab-pane>
        <el-tab-pane :label="`已确认 ${confirmedRuns.length}`" name="confirmed">
          <el-empty v-if="!confirmedRuns.length" description="暂无人工确认排期" />
          <div v-else class="run-list">
            <article
              v-for="run in confirmedRuns"
              :key="run.id"
              class="run-card confirmed-card"
              :style="{ '--block-hue': `${productHue(run.product_id)}` }"
              draggable="true"
              @dragstart="startDrag($event, run)"
            >
              <div class="run-card-head">
                <strong>{{ run.product_name }}</strong>
                <el-button link type="primary" @click="unlockSchedule(run)">
                  恢复自动
                </el-button>
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
                <el-tag type="warning" size="small">生产中</el-tag>
              </div>
              <span>{{ run.product_sku }} · 生产位 {{ run.line_slot }}</span>
              <small>预计 {{ formatDate(run.planned_end_at) }} 完成</small>
            </article>
          </div>
        </el-tab-pane>
      </el-tabs>
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
  background-image:
    repeating-linear-gradient(
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
  user-select: none;
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

@media (max-width: 900px) {
  .page-toolbar .el-alert {
    min-width: 100%;
  }

  .timeline-scroll {
    max-height: none;
  }
}
</style>
