<template>
  <main class="knowledge-map-page">
    <div v-if="loading" class="map-message" role="status">正在加载知识地图…</div>
    <div v-else-if="error" class="map-message" role="alert">
      {{ error }}
      <el-button plain @click="load">重新加载</el-button>
    </div>
    <div
      v-else-if="graph"
      class="map-workspace"
    >
      <section class="map-stage" aria-label="知识图谱浏览区">
        <div class="map-stage__toolbar">
          <div class="map-stage__toolbar-actions">
            <button
              type="button"
              class="map-toolbar-button"
              :class="{ active: indexOpen }"
              aria-controls="knowledge-map-directory"
              :aria-expanded="indexOpen"
              aria-label="打开知识目录"
              title="知识目录"
              @click="indexOpen = !indexOpen"
            >
              <el-icon><Menu /></el-icon>
            </button>

            <div class="map-status-tabs" role="group" aria-label="知识点学习状态">
              <button
                type="button"
                class="map-status-tab"
                :class="{ active: !showPersonalState }"
                :aria-pressed="!showPersonalState"
                @click="setPersonalState('all')"
              >
                全部
              </button>
              <button
                type="button"
                class="map-status-tab"
                :class="{ active: showPersonalState }"
                :aria-pressed="showPersonalState"
                @click="setPersonalState('highlight')"
              >
                已学
              </button>
            </div>

            <div
              v-if="indexOpen"
              id="knowledge-map-directory"
              class="map-directory-popover"
              aria-label="知识目录"
            >
              <div class="map-directory__header">
                <strong>知识目录</strong>
                <button type="button" aria-label="关闭知识目录" title="关闭知识目录" @click="collapseIndex">
                  <el-icon><Close /></el-icon>
                </button>
              </div>
              <label class="map-search map-directory__search">
                <el-icon><Search /></el-icon>
                <input v-model="search" aria-label="搜索知识点" placeholder="搜索知识点" />
                <button v-if="search" type="button" aria-label="清空搜索" title="清空搜索" @click="search = ''">
                  <el-icon><Close /></el-icon>
                </button>
              </label>
              <div v-if="search.trim()" class="map-search-results map-directory__search-results" aria-label="知识点搜索结果">
                <p v-if="!listedNodes.length" class="map-empty">没有找到匹配的知识点。</p>
                <button
                  v-for="node in listedNodes"
                  :key="node.canonical_id"
                  type="button"
                  class="map-search-result"
                  @click="selectNode(node.canonical_id)"
                >
                  <span>{{ node.display_name }}</span>
                  <small>{{ node.chapter }}</small>
                </button>
              </div>
              <div class="map-directory__scroll">
                <button type="button" class="map-overview" :class="{ active: !chapter }" @click="selectChapter('')">
                  <el-icon><Connection /></el-icon>
                  <span>全部章节</span>
                </button>
                <div v-for="item in graph.chapters" :key="item.chapter" class="map-chapter-group">
                  <button
                    type="button"
                    class="map-chapter"
                    :class="{ active: chapter === item.chapter }"
                    :aria-expanded="chapter === item.chapter"
                    @click="selectChapter(item.chapter)"
                  >
                    <i :style="{ background: chapterColor(item.chapter) }" />
                    <span>{{ item.title }}</span>
                    <el-icon class="map-chapter__chevron"><ArrowRight /></el-icon>
                  </button>
                  <div v-if="chapter === item.chapter" class="map-chapter-kcs">
                    <button
                      v-for="node in chapterNodes(item.chapter)"
                      :key="node.canonical_id"
                      type="button"
                      class="map-concept"
                      :class="{ active: selectedId === node.canonical_id }"
                      @click="selectNode(node.canonical_id)"
                    >
                      <span>{{ node.display_name }}</span>
                    </button>
                  </div>
                </div>
              </div>
            </div>

          </div>
        </div>

        <p v-if="notice" class="map-notice" role="status">{{ notice }}</p>
        <div class="map-canvas-wrap">
          <h1 class="map-canvas-title">知识地图</h1>
          <KnowledgeMapCanvas
            :graph="graph"
            :chapter="chapter"
            :selected-id="selectedId"
            :enabled-relations="enabledRelations"
            :show-personal-state="showPersonalState"
            @select="selectNode"
          />
          <div class="map-canvas-toolbar">
            <div class="map-relation-filters" aria-label="关系筛选">
              <label v-for="(meta, key) in relationTypes" :key="key" :class="{ active: enabledRelations.includes(key) }">
                <input v-model="enabledRelations" type="checkbox" :value="key" />
                <i :style="{ background: meta.color }" />
                {{ meta.label }}
              </label>
            </div>
          </div>
          <div v-if="showPersonalState" class="map-state-legend">
            <span v-for="(meta, key) in learningStates" :key="key"><i :style="{ background: meta.color }" />{{ meta.label }}</span>
          </div>
        </div>
      </section>

      <ResizableSidePanel
        id="knowledge-map-inspector"
        v-model:open="inspectorOpen"
        class="map-inspector"
        side="end"
        label="知识点详情"
        resize-label="调整知识点详情宽度"
        storage-key="ds-course-agent.knowledgeMapInspectorWidth"
        :default-width="310"
        :min-width="260"
        :max-width="520"
      >
        <div class="map-inspector__content">
          <div class="map-detail__heading">
            <span v-if="selectedNode"><i :style="{ background: chapterColor(selectedNode.chapter) }" />{{ selectedNode.chapter }}</span>
            <span v-else>知识点详情</span>
            <button
              type="button"
              aria-controls="knowledge-map-inspector"
              :aria-expanded="inspectorOpen"
              aria-label="收起知识点详情面板"
              title="收起详情面板"
              @click.stop="collapseInspector"
            >
              <PanelToggleIcon side="end" />
            </button>
          </div>
          <template v-if="selectedNode">
            <h2>{{ selectedNode.display_name }}</h2>
            <p v-if="selectedNode.summary" class="map-detail__summary">{{ selectedNode.summary }}</p>
            <div v-if="showPersonalState" class="map-learning-state">
              <i :style="{ background: learningStateMeta(selectedNode.learning_state).color }" />
              {{ learningStateMeta(selectedNode.learning_state).label }}
            </div>

            <section class="map-detail__section">
              <div class="map-detail__section-title"><h3>概念关系</h3><span>{{ relatedConcepts.length }}</span></div>
              <p v-if="!relatedConcepts.length" class="map-empty">当前筛选下没有关联概念。</p>
              <div class="map-neighbors">
                <button v-for="item in relatedConcepts" :key="`${item.node.canonical_id}:${item.kind}`" type="button" @click="selectNode(item.node.canonical_id)">
                  <i :style="{ background: chapterColor(item.node.chapter) }" />
                  <span>{{ item.node.display_name }}<small>{{ relationLabel(item) }}</small></span>
                  <el-icon><ArrowRight /></el-icon>
                </button>
              </div>
            </section>

            <div class="map-actions">
              <button type="button" class="map-action-button map-action-button--primary" @click="ask(false)">
                <span>讨论这个概念</span>
                <el-icon><ArrowRight /></el-icon>
              </button>
              <button type="button" class="map-action-button" @click="ask(true)">
                <span>做一道理解题</span>
                <el-icon><ArrowRight /></el-icon>
              </button>
            </div>

            <details v-if="selectedNode.learning_points.length" class="map-references">
              <summary>教材内容与出处 <span>{{ selectedNode.learning_points.length }}</span></summary>
              <section v-for="point in selectedNode.learning_points" :key="point.title">
                <h3>{{ point.title }}</h3>
                <p>{{ point.objective }}</p>
                <details v-for="source in point.sources" :key="`${source.source_id}:${source.book_page}`">
                  <summary>{{ source.title }} · 第 {{ source.book_page }} 页</summary>
                  <blockquote>{{ source.quote }}</blockquote>
                </details>
              </section>
            </details>
          </template>
          <div v-else class="map-inspector__empty">
            <el-icon><Connection /></el-icon>
            <h2>选择一个 KC</h2>
            <p>从知识目录或知识图谱中选择概念，查看它的关系与学习内容。</p>
          </div>
        </div>
      </ResizableSidePanel>
    </div>
  </main>
</template>

<script setup>
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, Close, Connection, Menu, Search } from '@element-plus/icons-vue'
import { knowledgeMapApi } from '../api/knowledgeMap'
import PanelToggleIcon from '../components/PanelToggleIcon.vue'
import ResizableSidePanel from '../components/ResizableSidePanel.vue'
import { chapterColor, learningStateMeta, learningStates, questionForNode, relationTypes } from '../utils/knowledgeMap'

const KnowledgeMapCanvas = defineAsyncComponent(() => import('../components/KnowledgeMapCanvas.vue'))

const route = useRoute()
const router = useRouter()
const graph = ref(null)
const loading = ref(true)
const error = ref('')
const notice = ref('')
const search = ref('')
const chapter = ref('')
const selectedId = ref('')
const indexOpen = ref(false)
const inspectorOpen = ref(false)
const showPersonalState = ref(false)
const enabledRelations = ref(Object.keys(relationTypes))
const byId = computed(() => new Map((graph.value?.nodes || []).map(node => [node.canonical_id, node])))
const concepts = computed(() => graph.value?.nodes?.filter(node => node.node_type === 'kc') || [])
const selectedNode = computed(() => byId.value.get(selectedId.value))
const listedNodes = computed(() => {
  const needle = search.value.trim().toLowerCase().replace(/\s+/g, '')
  if (!needle && !chapter.value) return []
  return concepts.value.filter(node => needle
    ? [node.display_name, ...node.aliases].some(label => label.toLowerCase().replace(/\s+/g, '').includes(needle))
    : node.chapter === chapter.value)
})
const relatedConcepts = computed(() => {
  const neighbors = new Map()
  for (const edge of graph.value?.edges || []) {
    if (edge.relation_type === 'part_of' || !enabledRelations.value.includes(edge.relation_type)) continue
    if (![edge.source, edge.target].includes(selectedId.value)) continue
    const node = byId.value.get(edge.source === selectedId.value ? edge.target : edge.source)
    const item = { node, kind: edge.relation_type, incoming: edge.target === selectedId.value }
    // Prefer informative typed relations over a duplicate generic association.
    if (!neighbors.has(node.canonical_id) || neighbors.get(node.canonical_id).kind === 'related_to') neighbors.set(node.canonical_id, item)
  }
  return [...neighbors.values()]
})

function relationLabel(item) {
  return item.kind === 'prerequisite_of' ? (item.incoming ? '建议先学' : '后续可学') : relationTypes[item.kind].label
}

function selectChapter(value) {
  chapter.value = chapter.value === value ? '' : value
  selectedId.value = ''
  collapseInspector()
  notice.value = ''
}

function collapseIndex() {
  indexOpen.value = false
}

function collapseInspector() {
  inspectorOpen.value = false
}

function openInspector() {
  inspectorOpen.value = true
}

function setPersonalState(value) {
  showPersonalState.value = value === 'highlight'
}

function chapterNodes(value) {
  return concepts.value.filter(node => node.chapter === value)
}

function selectNode(id) {
  const node = byId.value.get(id)
  if (!node) { notice.value = '这个知识点暂未收录，可通过搜索或目录继续浏览。'; return }
  if (node.node_type === 'chapter') { selectChapter(node.chapter); return }
  if (chapter.value && chapter.value !== node.chapter) chapter.value = node.chapter
  selectedId.value = id
  search.value = ''
  openInspector()
  notice.value = ''
}

function handleDocumentKeydown(event) {
  if (event.key === 'Escape') {
    collapseIndex()
    collapseInspector()
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    graph.value = await knowledgeMapApi.get()
    if (typeof route.query.concept === 'string') selectNode(route.query.concept)
  } catch { error.value = '知识图谱暂时无法加载，请稍后重试。' }
  finally { loading.value = false }
}

function ask(practice) { router.push({ path: '/chat', query: { question: questionForNode(selectedNode.value, practice) } }) }
watch(() => route.query.concept, value => { if (graph.value && typeof value === 'string') selectNode(value) })
onMounted(() => {
  document.addEventListener('keydown', handleDocumentKeydown)
  load()
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', handleDocumentKeydown)
})
</script>

<style src="../styles/knowledge-map.css"></style>
<style src="../styles/knowledge-map-detail.css"></style>
