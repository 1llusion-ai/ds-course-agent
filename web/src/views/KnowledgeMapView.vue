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
      :class="{ 'map-workspace--inspector-open': selectedNode }"
    >
      <aside class="map-index" aria-label="知识点导航">
        <label class="map-search">
          <el-icon><Search /></el-icon>
          <input v-model="search" aria-label="搜索知识点" placeholder="搜索 KC 或别名" />
          <button v-if="search" type="button" aria-label="清空搜索" title="清空搜索" @click="search = ''">
            <el-icon><Close /></el-icon>
          </button>
        </label>

        <div class="map-index__scroll">
          <div class="map-index__heading">
            <span>课程结构</span>
            <small>{{ kcCount }} KC</small>
          </div>
          <button type="button" class="map-overview" :class="{ active: !chapter }" @click="selectChapter('')">
            <el-icon><Connection /></el-icon>
            <span>全部章节</span>
            <small>{{ graph.chapters.length }}</small>
          </button>
          <div
            v-for="item in graph.chapters"
            :key="item.chapter"
            class="map-chapter-group"
          >
            <button
              type="button"
              class="map-chapter"
              :class="{ active: chapter === item.chapter }"
              :aria-expanded="chapter === item.chapter"
              @click="selectChapter(item.chapter)"
            >
              <i :style="{ background: chapterColor(item.chapter) }" />
              <span>{{ item.title }}</span>
              <small>{{ item.kc_count }}</small>
              <el-icon class="map-chapter__chevron"><ArrowRight /></el-icon>
            </button>
            <div v-if="chapter === item.chapter && !search.trim()" class="map-chapter-kcs">
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

          <div v-if="search.trim()" class="map-index__heading map-index__heading--concepts">
            <span>搜索结果</span>
            <small>{{ listedNodes.length }}</small>
          </div>
          <p v-if="search.trim() && !listedNodes.length" class="map-empty">没有找到匹配的知识点。</p>
          <button
            v-for="node in search.trim() ? listedNodes : []"
            :key="node.canonical_id"
            type="button"
            class="map-concept"
            :class="{ active: selectedId === node.canonical_id }"
            @click="selectNode(node.canonical_id)"
          >
            <span>{{ node.display_name }}</span>
            <small v-if="search.trim()">{{ node.chapter }}</small>
          </button>
        </div>
      </aside>

      <section class="map-stage" aria-label="知识图谱浏览区">
        <div class="map-stage__toolbar">
          <div>
            <p>知识地图 · {{ chapter ? '章节视图' : '课程全景' }}</p>
            <h2>{{ chapter ? chapterTitle : '全部知识关系' }}</h2>
          </div>
          <div class="map-stage__stats">
            <span><strong>{{ visibleKcCount }}</strong> KC</span>
            <span><strong>{{ visibleRelationCount }}</strong> 关系</span>
          </div>
        </div>

        <div class="map-filterbar">
          <div class="map-relation-filters" aria-label="关系筛选">
            <label v-for="(meta, key) in relationTypes" :key="key" :class="{ active: enabledRelations.includes(key) }">
              <input v-model="enabledRelations" type="checkbox" :value="key" />
              <i :style="{ background: meta.color }" />
              {{ meta.label }}
            </label>
          </div>
          <div class="map-view-options">
            <label><span>学习状态</span><el-switch v-model="showPersonalState" size="small" /></label>
            <el-button text :disabled="!selectedId && !chapter" @click="localOnly = !localOnly">
              <el-icon><Aim /></el-icon>
              {{ localOnly ? '显示全部' : '聚焦关联' }}
            </el-button>
          </div>
        </div>

        <p v-if="notice" class="map-notice" role="status">{{ notice }}</p>
        <div class="map-canvas-wrap">
          <KnowledgeMapCanvas
            :graph="graph"
            :chapter="chapter"
            :selected-id="selectedId"
            :enabled-relations="enabledRelations"
            :local-only="localOnly"
            :show-personal-state="showPersonalState"
            @select="selectNode"
          />
        </div>
        <div v-if="showPersonalState" class="map-state-legend">
          <span v-for="(meta, key) in learningStates" :key="key"><i :style="{ background: meta.color }" />{{ meta.label }}</span>
        </div>
      </section>

      <Transition name="map-inspector">
        <aside v-if="selectedNode" class="map-inspector" aria-label="知识点详情">
          <div class="map-detail__heading">
            <span><i :style="{ background: chapterColor(selectedNode.chapter) }" />{{ selectedNode.chapter }}</span>
            <button
              type="button"
              aria-label="收起知识点详情面板"
              title="收起详情面板"
              @click="selectedId = ''"
            >
              <span class="map-panel-toggle-icon" aria-hidden="true" />
            </button>
          </div>
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
            <el-button type="primary" @click="ask(false)">讨论这个概念</el-button>
            <el-button plain @click="ask(true)">做一道理解题</el-button>
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
        </aside>
      </Transition>
    </div>
  </main>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Aim, ArrowRight, Close, Connection, Search } from '@element-plus/icons-vue'
import { knowledgeMapApi } from '../api/knowledgeMap'
import KnowledgeMapCanvas from '../components/KnowledgeMapCanvas.vue'
import { chapterColor, learningStateMeta, learningStates, neighborsOf, questionForNode, relationTypes } from '../utils/knowledgeMap'

const route = useRoute()
const router = useRouter()
const graph = ref(null)
const loading = ref(true)
const error = ref('')
const notice = ref('')
const search = ref('')
const chapter = ref('')
const selectedId = ref('')
const localOnly = ref(false)
const showPersonalState = ref(false)
const enabledRelations = ref(Object.keys(relationTypes))
const byId = computed(() => new Map((graph.value?.nodes || []).map(node => [node.canonical_id, node])))
const concepts = computed(() => graph.value?.nodes.filter(node => node.node_type === 'kc') || [])
const kcCount = computed(() => concepts.value.length)
const chapterTitle = computed(() => graph.value.chapters.find(item => item.chapter === chapter.value)?.title)
const scopedNodeIds = computed(() => {
  if (selectedId.value) return neighborsOf(graph.value, selectedId.value, enabledRelations.value)
  if (!chapter.value) return new Set(graph.value.nodes.map(node => node.canonical_id))
  return new Set(graph.value.nodes.filter(node => node.chapter === chapter.value).map(node => node.canonical_id))
})
const visibleKcCount = computed(() => concepts.value.filter(node => scopedNodeIds.value.has(node.canonical_id)).length)
const visibleRelationCount = computed(() => {
  const ids = scopedNodeIds.value
  return graph.value.edges.filter(edge => enabledRelations.value.includes(edge.relation_type) && ids.has(edge.source) && ids.has(edge.target)).length
})
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
  for (const edge of graph.value.edges) {
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
  notice.value = ''
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
  notice.value = ''
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
onMounted(load)
</script>

<style scoped src="../styles/knowledge-map.css"></style>
<style scoped src="../styles/knowledge-map-detail.css"></style>
