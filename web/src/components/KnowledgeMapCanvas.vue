<template>
  <section class="constellation" aria-label="三维知识网络">
    <div
      ref="container"
      class="constellation__canvas"
      :class="{ 'constellation__canvas--ready': sceneReady }"
      role="img"
      aria-label="拖动旋转、滚轮缩放的三维知识图谱，也可用左侧列表选择知识点"
    />
    <div v-if="failure" class="constellation__failure" role="status">三维视图暂时无法加载，仍可通过左侧知识点列表浏览。</div>
    <div v-else class="constellation__controls" aria-label="三维视图控制">
      <button type="button" :aria-pressed="rotating" :aria-label="rotating ? '暂停旋转' : '自动旋转'" :title="rotating ? '暂停旋转' : '自动旋转'" @click="toggleRotation">
        <el-icon><VideoPause v-if="rotating" /><VideoPlay v-else /></el-icon>
      </button>
      <span />
      <button type="button" aria-label="放大图谱" title="放大" @click="zoom(0.8)"><el-icon><ZoomIn /></el-icon></button>
      <button type="button" aria-label="缩小图谱" title="缩小" @click="zoom(1.25)"><el-icon><ZoomOut /></el-icon></button>
      <button type="button" aria-label="重置视角" title="重置视角" @click="overview"><el-icon><RefreshRight /></el-icon></button>
    </div>
  </section>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RefreshRight, VideoPause, VideoPlay, ZoomIn, ZoomOut } from '@element-plus/icons-vue'
import ForceGraph3D from '3d-force-graph'
import { chapterColor, learningStateMeta, neighborsOf, relationTypes, sceneGraphData } from '../utils/knowledgeMap'
import { createNodeObjects } from '../utils/knowledgeScene'

const props = defineProps({
  graph: { type: Object, required: true },
  selectedId: { type: String, default: '' },
  chapter: { type: String, default: '' },
  showPersonalState: { type: Boolean, default: false },
  enabledRelations: { type: Array, required: true }
})
const emit = defineEmits(['select', 'ready'])
const container = ref(null)
const failure = ref(false)
const rotating = ref(false)
const sceneReady = ref(false)
let graph3d
let observer
let objects
let sceneData
let hoveredId = ''
let firstLayout = true
const motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)')
const reducedMotion = ref(motionPreference.matches)
const cameraDuration = () => reducedMotion.value ? 0 : 650
const endId = end => typeof end === 'object' ? end.id : end
const colorChannels = new Map()

function rgba(color, opacity) {
  let channels = colorChannels.get(color)
  if (!channels) {
    const value = Number.parseInt(color.slice(1), 16)
    channels = `${value >> 16},${(value >> 8) & 255},${value & 255}`
    colorChannels.set(color, channels)
  }
  return `rgba(${channels},${opacity})`
}

function activeIds() {
  if (props.selectedId) return neighborsOf(props.graph, props.selectedId, props.enabledRelations)
  return new Set(sceneData.nodes.filter(node => !props.chapter || node.chapter === props.chapter).map(node => node.id))
}

function colorFor(node) {
  return props.showPersonalState && node.kind !== 'chapter'
    ? learningStateMeta(node.state).color
    : chapterColor(node.chapter)
}

function updateAppearance() {
  if (!graph3d || !sceneData) return
  const active = activeIds()
  const emphasized = Boolean(props.selectedId || props.chapter)
  for (const node of sceneData.nodes) {
    const object = objects.objects.get(node.id)
    if (!object) continue
    const relevant = !emphasized || active.has(node.id)
    const selected = node.id === props.selectedId
    object.sphere.material.color.set(colorFor(node))
    object.sphere.material.opacity = relevant ? 1 : 0.16
    object.ring.material.color.set(colorFor(node))
    object.ring.material.opacity = selected ? 0.72 : 0
    object.group.visible = true
    object.label.visible = node.id === hoveredId
      || selected
      || node.kind === 'chapter'
      || (Boolean(props.selectedId) && relevant)
      || (Boolean(props.chapter) && relevant && node.degree >= 5)
      || (!emphasized && node.degree >= 10)
    object.label.material.opacity = selected ? 1 : (node.kind === 'chapter' ? 0.9 : 0.78)
  }
  graph3d.linkVisibility(link => props.enabledRelations.includes(link.kind))
    .linkColor(link => {
      const relevant = active.has(endId(link.source)) && active.has(endId(link.target))
      const opacity = emphasized ? (relevant ? 0.62 : 0.035) : (link.kind === 'part_of' ? 0.12 : 0.22)
      const color = link.kind === 'part_of'
        ? chapterColor(link.source.chapter)
        : (relationTypes[link.kind] || relationTypes.related_to).color
      return rgba(color, opacity)
    })
    .linkWidth(link => props.selectedId && [endId(link.source), endId(link.target)].includes(props.selectedId) ? 0.45 : 0.12)
    .linkDirectionalArrowLength(link => link.kind === 'prerequisite_of' ? 2 : 0)
}

function stopRotation() {
  rotating.value = false
  if (graph3d) graph3d.controls().autoRotate = false
}

function focusSelection(animate = true) {
  if (!graph3d || !sceneData) return
  stopRotation()
  updateAppearance()
  const duration = animate ? cameraDuration() : 0
  const selected = sceneData.nodes.find(node => node.id === props.selectedId)
  if (selected) {
    const camera = graph3d.cameraPosition()
    const dx = camera.x - selected.x, dy = camera.y - selected.y, dz = camera.z - selected.z
    const distance = Math.hypot(dx, dy, dz) || 1
    graph3d.cameraPosition({ x: selected.x + dx / distance * 135, y: selected.y + dy / distance * 135, z: selected.z + dz / distance * 135 }, selected, duration)
  } else if (props.chapter) {
    focusChapter(animate)
  } else {
    overview(animate)
  }
}

function focusChapter(animate = true) {
  const nodes = sceneData.nodes.filter(node => node.chapter === props.chapter)
  if (!nodes.length) return
  const axes = ['x', 'y', 'z']
  const center = Object.fromEntries(axes.map(axis => {
    const values = nodes.map(node => node[axis])
    return [axis, (Math.min(...values) + Math.max(...values)) / 2]
  }))
  const radius = Math.max(...nodes.map(node => Math.hypot(node.x - center.x, node.y - center.y, node.z - center.z)))
  const camera = graph3d.cameraPosition()
  const dx = camera.x - center.x
  const dy = camera.y - center.y
  const dz = camera.z - center.z
  const currentDistance = Math.hypot(dx, dy, dz) || 1
  const targetDistance = Math.min(360, Math.max(175, radius * 2.2))
  graph3d.cameraPosition({
    x: center.x + dx / currentDistance * targetDistance,
    y: center.y + dy / currentDistance * targetDistance,
    z: center.z + dz / currentDistance * targetDistance
  }, center, animate ? cameraDuration() : 0)
}

function overview(animate = true) {
  if (!graph3d) return
  stopRotation()
  graph3d.zoomToFit(0, 36)
  const camera = graph3d.cameraPosition()
  const target = graph3d.controls().target
  const zoomFactor = 0.7
  graph3d.cameraPosition({
    x: target.x + (camera.x - target.x) * zoomFactor,
    y: target.y + (camera.y - target.y) * zoomFactor,
    z: target.z + (camera.z - target.z) * zoomFactor
  }, target, animate ? cameraDuration() : 0)
}

function toggleRotation() {
  rotating.value = !rotating.value
  if (graph3d) graph3d.controls().autoRotate = rotating.value
}

function zoom(factor) {
  if (!graph3d) return
  const camera = graph3d.cameraPosition()
  const target = graph3d.controls().target
  graph3d.cameraPosition({ x: target.x + (camera.x - target.x) * factor, y: target.y + (camera.y - target.y) * factor, z: target.z + (camera.z - target.z) * factor }, target, cameraDuration())
}

function visibilityChanged() {
  if (!graph3d) return
  if (document.hidden) graph3d.pauseAnimation()
  else graph3d.resumeAnimation()
}

function motionPreferenceChanged(event) {
  reducedMotion.value = event.matches
  if (event.matches) stopRotation()
}

function teardown() {
  observer?.disconnect()
  observer = undefined
  document.removeEventListener('visibilitychange', visibilityChanged)
  motionPreference.removeEventListener('change', motionPreferenceChanged)
  graph3d?._destructor()
  graph3d = undefined
  objects?.dispose()
  objects = undefined
}

watch(() => [props.selectedId, props.chapter], focusSelection)
watch(() => [props.showPersonalState, props.enabledRelations], updateAppearance, { deep: true })

onMounted(async () => {
  try {
    await document.fonts.ready
    if (!container.value) return
    objects = createNodeObjects()
    sceneData = sceneGraphData(props.graph)
    graph3d = new ForceGraph3D(container.value, { controlType: 'orbit', rendererConfig: { antialias: true, alpha: true } })
      .width(container.value.clientWidth).height(container.value.clientHeight)
      .backgroundColor('rgba(0,0,0,0)').showNavInfo(false)
      .nodeThreeObject(node => objects.create(node, colorFor(node)))
      .nodeLabel(node => { const label = document.createElement('span'); label.textContent = `${node.name} · ${node.chapter}`; return label })
      .linkOpacity(1).linkResolution(4).enableNodeDrag(false)
      .warmupTicks(100).cooldownTicks(70)
      .onNodeClick(node => emit('select', node.id))
      .onNodeHover(node => { hoveredId = node?.id || ''; updateAppearance() })
      .onEngineStop(() => {
        if (firstLayout) {
          firstLayout = false
          focusSelection(false)
          window.requestAnimationFrame(() => {
            sceneReady.value = true
            emit('ready')
          })
        }
      })
    graph3d.d3Force('charge').strength(-28)
    graph3d.d3Force('link').distance(link => link.kind === 'part_of' ? 36 : 130).strength(link => link.kind === 'part_of' ? 0.55 : 0.025)
    graph3d.d3Force('center', null)
    graph3d.controls().enableDamping = true
    graph3d.controls().autoRotateSpeed = 0.35
    graph3d.graphData(sceneData)
    graph3d.cameraPosition({ x: 330, y: 130, z: 700 })
    updateAppearance()
    observer = new ResizeObserver(() => {
      graph3d.width(container.value.clientWidth).height(container.value.clientHeight)
    })
    observer.observe(container.value)
    document.addEventListener('visibilitychange', visibilityChanged)
    motionPreference.addEventListener('change', motionPreferenceChanged)
    visibilityChanged()
  } catch (error) {
    teardown()
    failure.value = true
    console.warn('Knowledge map renderer unavailable:', error.message)
  }
})

onBeforeUnmount(teardown)
</script>

<style scoped>
.constellation { position: relative; width: 100%; height: 100%; min-height: 420px; }
.constellation__canvas { position: absolute; inset: 0; visibility: hidden; }
.constellation__canvas--ready { visibility: visible; }
.constellation__controls { position: absolute; top: 14px; right: 14px; display: flex; align-items: center; gap: 2px; padding: 4px; border: 1px solid #e7e5e4; border-radius: 7px; background: rgba(255,255,255,.9); box-shadow: 0 4px 14px rgba(28,25,23,.06); }
.constellation__controls button { display: grid; place-items: center; width: 30px; height: 30px; padding: 0; color: #57534e; border: 0; background: transparent; border-radius: 5px; cursor: pointer; }
.constellation__controls button:hover, .constellation__controls button[aria-pressed="true"] { color: #1c1917; background: #f5f5f4; }
.constellation__controls > span { width: 1px; height: 18px; margin: 0 2px; background: #e7e5e4; }
.constellation__failure { position: absolute; top: 40%; left: 15%; right: 15%; padding: 20px; color: #78716c; text-align: center; font-size: 13px; line-height: 1.8; }
:global(html.theme-dark) .constellation__controls { color: var(--dark-text-muted); background: rgba(42,42,42,.92); border-color: var(--dark-border); box-shadow: none; }
:global(html.theme-dark) .constellation__controls button { color: var(--dark-text-muted); }
:global(html.theme-dark) .constellation__controls button:hover,
:global(html.theme-dark) .constellation__controls button[aria-pressed="true"] { color: var(--dark-text); background: var(--dark-hover); }
:global(html.theme-dark) .constellation__controls > span { background: var(--dark-border); }
@media (max-width: 720px) { .constellation { min-height: 430px; } .constellation__controls { top: 10px; right: 10px; } }
</style>
