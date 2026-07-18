<template>
  <div
    class="message-wrapper"
    :class="{
      'user-message': message.role === 'user',
      'assistant-message': message.role !== 'user'
    }"
  >
    <div
      class="message-bubble"
      :class="[
        message.role === 'user' ? 'user-bubble' : 'ai-bubble',
        { 'is-loading': message.isLoading, 'is-error': message.isError }
      ]"
    >
      <template v-if="message.role === 'user'">
        <div class="message-content user-content">
          {{ message.content }}
        </div>
      </template>

      <template v-else>
        <template v-if="message.isLoading && !message.content">
          <div class="message-content loading-content" aria-live="polite">
            <span class="loading-dot"></span>
            <span class="loading-dot"></span>
            <span class="loading-dot"></span>
            <span class="loading-label">{{ currentProgressMessage || '正在思考并组织答案…' }}</span>
          </div>
        </template>

        <template v-else>
          <div
            class="message-content markdown-body"
            :class="{ 'is-streaming': message.isLoading }"
            v-html="renderedContent"
            @click="handleMarkdownClick"
          ></div>
        </template>
      </template>


      <div v-if="sourceChips.length" class="source-panel">
        <button
          v-if="webSourceCards.length"
          type="button"
          class="web-source-block"
          @click="openWebSources"
        >
          <span class="web-source-block__favicons" aria-hidden="true">
            <span
              v-for="source in webSourceFavicons"
              :key="source.key"
              class="web-source-block__favicon"
            >
              <span class="web-source-block__favicon-fallback">🌐</span>
              <img
                class="web-source-block__favicon-img"
                :src="source.favicon"
                :alt="source.domain || source.label"
                @error="$event.target.style.display = 'none'"
              />
            </span>
            <span v-if="!webSourceFavicons.length" class="web-source-block__favicon">
              <span class="web-source-block__favicon-fallback">🌐</span>
            </span>
          </span>
          <span class="web-source-block__body">
            <span class="web-source-block__title">{{ webSourceCards.length }} 个网页</span>
          </span>
          <span class="web-source-block__arrow">›</span>
        </button>
        <details v-if="courseSourceChips.length" class="course-source-disclosure">
          <summary class="course-source-summary">
            <span class="course-source-summary__icons" aria-hidden="true">
              <span
                v-for="source in courseSourcePreview"
                :key="source.key"
                class="course-source-summary__icon"
              >
                {{ source.icon }}
              </span>
            </span>
            <span class="course-source-summary__body">
              <span class="course-source-summary__title">{{ courseSourceChips.length }} 个课程来源</span>
            </span>
            <span class="course-source-summary__arrow">›</span>
          </summary>

          <div class="source-chips source-chips--compact">
            <component
              :is="source.url ? 'a' : 'span'"
              v-for="source in courseSourceChips"
              :key="source.key"
              class="source-chip"
              :href="source.url || undefined"
              target="_blank"
              rel="noopener noreferrer"
              :title="source.title"
            >
              <span class="source-chip__icon">{{ source.icon }}</span>
              <span class="source-chip__text">{{ source.label }}</span>
              <span v-if="source.detail" class="source-chip__detail">{{ source.detail }}</span>
            </component>
          </div>
        </details>
      </div>

      <div v-if="message.role !== 'user' && message.content && !message.isLoading" class="assistant-actions">
        <button
          type="button"
          class="assistant-action-button"
          :class="{
            'assistant-action-button--success': messageCopyState === 'success',
            'assistant-action-button--error': messageCopyState === 'error'
          }"
          :aria-label="messageCopyLabel"
          @click="copyAssistantMessage"
        >
          <span class="assistant-action-button__icon" aria-hidden="true">⧉</span>
          <span>{{ messageCopyLabel }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import 'katex/dist/katex.min.css'

import { isJavascriptUrl, renderMarkdownWithEnhancements } from '../utils/markdown'
import { domainFromUrl, faviconUrl } from '../utils/url'

const props = defineProps({
  message: {
    type: Object,
    required: true
  }
})

const emit = defineEmits(['open-sources'])

const messageCopyState = ref('idle')
let messageCopyTimer = null

const messageCopyLabel = computed(() => {
  if (messageCopyState.value === 'success') return '已复制'
  if (messageCopyState.value === 'error') return '复制失败'
  return '复制'
})

const ROUTE_LABELS = {
  agent: 'Agent',
  code_review: '代码审查',
  direct: '直接回答',
  fallback: '兜底回答',
  generic_agent: '通用答疑',
  graph: '知识图谱',
  grounded_rag: '教材检索',
  kg: '知识图谱',
  learning_path: '学习路径',
  memory: '学习记忆',
  misconception: '误区纠偏',
  rag: '课程知识库',
  retrieval: '课程知识库',
  search: '检索增强',
  schedule: '课程安排',
  skill: '学习策略',
  tool: '工具调用',
  web_search: '联网搜索'
}

const PROGRESS_PHASE_LABELS = {
  web_search: '联网搜索',
  web_search_start: '联网搜索',
  web_search_results: '搜索结果',
  web_fetch_start: '浏览网页',
  web_fetch_page_done: '已浏览',
  web_fetch_done: '浏览完成',
  web_answer_start: '生成回答'
}

function extractRouteValue(route) {
  if (!route) return ''
  if (typeof route === 'string') return route
  if (typeof route === 'object') {
    return route.label || route.name || route.route || route.type || route.id || ''
  }
  return String(route)
}

function formatRoute(route) {
  const raw = extractRouteValue(route).trim()
  if (!raw) return ''
  const key = raw.toLowerCase().replace(/[\s-]+/g, '_')
  return ROUTE_LABELS[key] || raw.replace(/[_-]+/g, ' ')
}

function normalizeSourceList(rawSources) {
  if (!rawSources) return []
  if (Array.isArray(rawSources)) return rawSources
  return [rawSources]
}

function safeExternalUrl(value) {
  if (!value || isJavascriptUrl(value)) return ''
  return String(value)
}

function sourceText(source, index) {
  if (typeof source === 'string') return source
  const metadata = source?.metadata || {}
  if (source?.source === 'web' || source?.url || source?.href || source?.link) {
    return (
      source?.title ||
      source?.name ||
      source?.label ||
      metadata.title ||
      metadata.source ||
      source?.reference ||
      `网页 ${index + 1}`
    )
  }
  return (
    source?.reference ||
    source?.title ||
    source?.name ||
    source?.label ||
    source?.source ||
    source?.id ||
    source?.chunk_id ||
    metadata.reference ||
    metadata.title ||
    metadata.source ||
    `来源 ${index + 1}`
  )
}

function sourceDetail(source) {
  if (!source || typeof source === 'string') return ''
  if (typeof source.score === 'number') return `${Math.round(source.score * 100)}%`
  if (source.source === 'web') {
    return [source.provider, source.published_at].filter(Boolean).join(' · ')
  }
  return source.section || source.page || source.metadata?.section || source.metadata?.page || ''
}

function sourceIcon(source) {
  if (!source || typeof source === 'string') return '📚'
  return source.source === 'web' || source.url ? '🌐' : '📚'
}

function sourceUrl(source) {
  if (!source || typeof source === 'string') return ''
  return safeExternalUrl(source.url || source.href || source.link || source.metadata?.url || source.metadata?.href)
}

function sourceIdFromSource(source, fallbackIndex) {
  if (!source || typeof source === 'string') return fallbackIndex + 1
  const metadata = source.metadata || {}
  const candidates = [
    source.source_id,
    source.sourceId,
    source.index,
    metadata.source_id,
    metadata.sourceId
  ]
  for (const candidate of candidates) {
    const value = Number(candidate)
    if (Number.isFinite(value) && value > 0) return value
  }
  const reference = String(source.reference || metadata.reference || '')
  const match = reference.match(/^\s*\[(\d{1,3})\]/)
  if (match) {
    const value = Number(match[1])
    if (Number.isFinite(value) && value > 0) return value
  }
  return fallbackIndex + 1
}

function linkCitationReferences(html, citationMap) {
  if (!html || !citationMap?.size || typeof window === 'undefined' || typeof DOMParser === 'undefined') {
    return html
  }

  const parser = new DOMParser()
  const doc = parser.parseFromString(`<div data-citation-root>${html}</div>`, 'text/html')
  const root = doc.body.firstElementChild
  if (!root) return html

  const excludedSelector = 'a, code, pre, kbd, samp, script, style, button'
  const walker = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const nodes = []
  while (walker.nextNode()) {
    const node = walker.currentNode
    if (!node.nodeValue || !/\[\d{1,3}\]/.test(node.nodeValue)) continue
    if (node.parentElement?.closest(excludedSelector)) continue
    nodes.push(node)
  }

  nodes.forEach(node => {
    const text = node.nodeValue || ''
    const fragment = doc.createDocumentFragment()
    let lastIndex = 0
    let replaced = false

    text.replace(/\[(\d{1,3})\]/g, (match, rawNumber, offset) => {
      const source = citationMap.get(Number(rawNumber))
      if (!source?.url) return match

      if (offset > lastIndex) {
        fragment.appendChild(doc.createTextNode(text.slice(lastIndex, offset)))
      }

      const anchor = doc.createElement('a')
      anchor.href = source.url
      anchor.target = '_blank'
      anchor.rel = 'noopener noreferrer'
      anchor.className = 'citation-link'
      anchor.textContent = match
      anchor.title = source.title || source.domain || source.url
      fragment.appendChild(anchor)

      lastIndex = offset + match.length
      replaced = true
      return match
    })

    if (!replaced) return
    if (lastIndex < text.length) {
      fragment.appendChild(doc.createTextNode(text.slice(lastIndex)))
    }
    node.parentNode?.replaceChild(fragment, node)
  })

  return root.innerHTML
}

function formatProgressPhase(phase) {
  if (!phase) return ''
  const key = String(phase).toLowerCase().replace(/[\s-]+/g, '_')
  if (PROGRESS_PHASE_LABELS[key]) return PROGRESS_PHASE_LABELS[key]
  const text = String(phase).replace(/[_-]+/g, ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}


const progressItems = computed(() => {
  const eventArray = Array.isArray(props.message.progressEvents)
    ? props.message.progressEvents
    : Array.isArray(props.message.progress_events)
      ? props.message.progress_events
      : []

  const rawItems = eventArray.length
    ? eventArray
    : props.message.progress
      ? [props.message.progress]
      : props.message.isLoading
        ? [{ phase: 'thinking', message: '正在思考并组织答案…' }]
        : []

  return rawItems.map((item, index) => {
    const value = typeof item === 'string' ? { message: item } : (item || {})
    const phase = formatProgressPhase(value.phase || value.status || value.type)
    const route = formatRoute(value.route)
    const message = value.message || phase || route || '处理中…'

    return {
      key: `${index}-${message}-${phase}-${route}`,
      message
    }
  })
})

const currentProgressMessage = computed(() => {
  const items = progressItems.value
  return items.length ? items[items.length - 1].message : ''
})


const sourceChips = computed(() => {
  const rawSources = normalizeSourceList(props.message.sources || props.message.metadata?.sources)
  const seen = new Set()

  return rawSources
    .map((source, index) => {
      const label = String(sourceText(source, index)).trim()
      const url = sourceUrl(source)
      const detail = sourceDetail(source)
      const key = `${label}-${url || detail || index}`

	    return {
	        key,
	        sourceId: sourceIdFromSource(source, index),
	        label,
	        detail,
	        icon: sourceIcon(source),
        url,
        title: detail ? `${label} · ${detail}` : label,
        raw: source,
        isWeb: Boolean(source && typeof source !== 'string' && (source.source === 'web' || url))
      }
    })
    .filter(source => {
      if (!source.label || seen.has(source.key)) return false
      seen.add(source.key)
      return true
    })
})

const webSourceCards = computed(() => (
  sourceChips.value
    .filter(source => source.isWeb && source.url)
    .map((source, index) => {
      const raw = source.raw && typeof source.raw === 'object' ? source.raw : {}
      const domain = raw.domain || domainFromUrl(source.url)

      return {
        ...source,
        index: index + 1,
        sourceId: source.sourceId || sourceIdFromSource(raw, index),
        domain,
        snippet: raw.snippet || raw.summary || raw.description || '',
        provider: raw.provider || '',
        published_at: raw.published_at || raw.publishedAt || '',
        fetched: raw.fetched,
        final_url: raw.final_url || '',
        favicon: faviconUrl(source.url, domain)
      }
    })
))

const courseSourceChips = computed(() => sourceChips.value.filter(source => !source.isWeb))

const webSourceFavicons = computed(() => webSourceCards.value.filter(source => source.favicon).slice(0, 3))

const courseSourcePreview = computed(() => courseSourceChips.value.slice(0, 3))

const citationSourceMap = computed(() => {
  const items = new Map()
  webSourceCards.value.forEach((source, index) => {
    const id = Number(source.sourceId || sourceIdFromSource(source.raw, index))
    const url = safeExternalUrl(source.final_url || source.url)
    if (Number.isFinite(id) && id > 0 && url && !items.has(id)) {
      items.set(id, {
        url,
        title: source.label,
        domain: source.domain
      })
    }
  })
  return items
})

const renderedContent = ref('')
let renderFrameId = null

function renderMessageContent() {
  const html = renderMarkdownWithEnhancements(props.message.content || '')
  if (props.message.isLoading) {
    return html
  }
  return linkCitationReferences(html, citationSourceMap.value)
}

function flushRenderedContent() {
  renderFrameId = null
  renderedContent.value = renderMessageContent()
}

function scheduleRenderedContentUpdate() {
  if (renderFrameId !== null && typeof window !== 'undefined' && typeof window.cancelAnimationFrame === 'function') {
    window.cancelAnimationFrame(renderFrameId)
    renderFrameId = null
  }

  const canRaf = typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function'
  if (!props.message.isLoading || !canRaf) {
    flushRenderedContent()
    return
  }

  renderFrameId = window.requestAnimationFrame(flushRenderedContent)
}

watch(
  () => [props.message.content || '', Boolean(props.message.isLoading), citationSourceMap.value],
  scheduleRenderedContentUpdate,
  { immediate: true, flush: 'post' }
)

function openWebSources() {
  if (!webSourceCards.value.length) return
  emit('open-sources', {
    title: `搜索来源 · ${webSourceCards.value.length} 个网页`,
    sources: webSourceCards.value
  })
}

async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text)
    return
  }

  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.top = '-9999px'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()

  try {
    const successful = document.execCommand('copy')
    if (!successful) {
      throw new Error('copy command failed')
    }
  } finally {
    document.body.removeChild(textarea)
  }
}

function setCopyState(button, text, isError = false) {
  const label = button.querySelector('.copy-label')
  const original = button.dataset.originalLabel || label?.textContent || '复制'
  button.dataset.originalLabel = original
  button.classList.toggle('code-copy--success', !isError)
  button.classList.toggle('code-copy--error', isError)
  if (label) label.textContent = text

  window.setTimeout(() => {
    button.classList.remove('code-copy--success', 'code-copy--error')
    const currentLabel = button.querySelector('.copy-label')
    if (currentLabel) currentLabel.textContent = button.dataset.originalLabel || '复制'
  }, 1400)
}

async function handleMarkdownClick(event) {
  const target = event.target
  if (!(target instanceof Element)) return

  const button = target.closest('.code-copy')
  if (!button) return

  event.preventDefault()
  const block = button.closest('.code-block')
  const code = block?.querySelector('pre code')?.innerText || ''

  try {
    await copyText(code)
    setCopyState(button, '已复制')
  } catch (error) {
    setCopyState(button, '复制失败', true)
  }
}

async function copyAssistantMessage() {
  if (!props.message.content) return

  if (messageCopyTimer) {
    window.clearTimeout(messageCopyTimer)
    messageCopyTimer = null
  }

  try {
    await copyText(props.message.content)
    messageCopyState.value = 'success'
  } catch (error) {
    messageCopyState.value = 'error'
  }

  messageCopyTimer = window.setTimeout(() => {
    messageCopyState.value = 'idle'
    messageCopyTimer = null
  }, 1400)
}

onBeforeUnmount(() => {
  if (messageCopyTimer) {
    window.clearTimeout(messageCopyTimer)
  }
  if (renderFrameId !== null && typeof window !== 'undefined' && typeof window.cancelAnimationFrame === 'function') {
    window.cancelAnimationFrame(renderFrameId)
  }
})
</script>

<style scoped>
.message-wrapper {
  display: flex;
  align-items: flex-start;
  width: 100%;
}

.message-wrapper.user-message {
  justify-content: flex-end;
}

.message-wrapper.assistant-message {
  justify-content: center;
}

.message-bubble {
  max-width: min(78%, 880px);
  padding: 12px 16px;
  border-radius: 18px;
}

.user-bubble {
  max-width: min(68%, 720px);
  color: #1c1917;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.97) 0%, rgba(255, 252, 247, 0.93) 100%);
  border: 1px solid rgba(226, 232, 240, 0.92);
  border-radius: 18px 18px 6px 18px;
  box-shadow: 0 16px 36px rgba(28, 25, 23, 0.06);
  backdrop-filter: blur(12px);
}

.ai-bubble {
  position: relative;
  width: min(100%, var(--chat-thread-width, 820px));
  max-width: min(100%, var(--chat-thread-width, 820px));
  padding: 2px 0 0;
  color: #1c1917;
  background: transparent;
  border: 0;
  border-radius: 0;
  box-shadow: none;
}

.ai-bubble::before {
  display: none;
}

.ai-bubble > * {
  position: relative;
}

.ai-bubble.is-error {
  padding-left: 14px;
  border-left: 3px solid rgba(248, 113, 113, 0.78);
}

.message-content {
  font-size: 15.5px;
  line-height: 1.72;
  white-space: pre-wrap;
  word-break: break-word;
}

.user-content {
  color: inherit;
}

.loading-content {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 26px;
}

.loading-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #94a3b8;
  animation: bubble-bounce 1.4s infinite ease-in-out both;
}

.loading-dot:nth-child(1) {
  animation-delay: -0.32s;
}

.loading-dot:nth-child(2) {
  animation-delay: -0.16s;
}

.loading-label {
  margin-left: 4px;
  color: #57534e;
  font-size: 13px;
  font-weight: 650;
}

@keyframes bubble-bounce {
  0%, 80%, 100% {
    transform: scale(0);
  }

  40% {
    transform: scale(1);
  }
}

.markdown-body {
  white-space: normal;
  color: #1f2937;
  font-size: 15.5px;
}

.markdown-body.is-streaming::after {
  content: '';
  display: inline-block;
  width: 7px;
  height: 1.1em;
  margin-left: 3px;
  vertical-align: -0.18em;
  border-radius: 999px;
  background: #2563eb;
  animation: caret-blink 1s infinite;
}

@keyframes caret-blink {
  0%, 45% {
    opacity: 1;
  }

  46%, 100% {
    opacity: 0;
  }
}

.markdown-body :deep(*) {
  box-sizing: border-box;
}

.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  margin: 16px 0 8px;
  color: #111827;
  font-weight: 800;
  line-height: 1.35;
  letter-spacing: -0.015em;
}

.markdown-body :deep(h1:first-child),
.markdown-body :deep(h2:first-child),
.markdown-body :deep(h3:first-child),
.markdown-body :deep(h4:first-child),
.markdown-body :deep(p:first-child) {
  margin-top: 0;
}

.markdown-body :deep(h1) {
  font-size: 22px;
}

.markdown-body :deep(h2) {
  padding-bottom: 5px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.95);
  font-size: 19px;
}

.markdown-body :deep(h3) {
  font-size: 17px;
}

.markdown-body :deep(h4) {
  font-size: 16px;
}

.markdown-body :deep(p) {
  margin: 8px 0;
}

.markdown-body :deep(strong) {
  color: #0f172a;
  font-weight: 800;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 8px 0;
  padding-left: 22px;
}

.markdown-body :deep(li) {
  margin: 4px 0;
  padding-left: 2px;
}

.markdown-body :deep(li::marker) {
  color: #2563eb;
  font-weight: 700;
}

.markdown-body :deep(a) {
  color: #1d4ed8;
  font-weight: 650;
  text-decoration: none;
  border-bottom: 1px solid rgba(37, 99, 235, 0.28);
}

.markdown-body :deep(a:hover) {
  color: #0f766e;
  border-bottom-color: rgba(15, 118, 110, 0.35);
}

.markdown-body :deep(.citation-link) {
  display: inline-flex;
  align-items: center;
  margin: 0 1px;
  padding: 0 4px;
  border: 1px solid rgba(37, 99, 235, 0.18);
  border-radius: 999px;
  background: rgba(37, 99, 235, 0.07);
  color: #1d4ed8;
  font-size: 0.86em;
  font-weight: 800;
  line-height: 1.35;
  vertical-align: 0.05em;
}

.markdown-body :deep(.citation-link:hover) {
  background: rgba(15, 118, 110, 0.1);
  color: #0f766e;
}

.markdown-body :deep(code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
  background: rgba(37, 99, 235, 0.08);
  color: #0f172a;
  padding: 2px 6px;
  border: 1px solid rgba(37, 99, 235, 0.09);
  border-radius: 6px;
  font-size: 0.92em;
}

.markdown-body :deep(.code-block) {
  margin: 14px 0;
  overflow: hidden;
  border: 1px solid rgba(203, 213, 225, 0.9);
  border-radius: 14px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.96));
  box-shadow: 0 14px 30px rgba(15, 23, 42, 0.08);
}

.markdown-body :deep(.code-block__header) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px 8px 12px;
  border-bottom: 1px solid rgba(203, 213, 225, 0.82);
  background: linear-gradient(180deg, rgba(248, 250, 252, 0.98), rgba(241, 245, 249, 0.95));
}

.markdown-body :deep(.code-block__footer) {
  display: flex;
  justify-content: flex-end;
  padding: 8px 10px;
  border-top: 1px solid rgba(203, 213, 225, 0.82);
  background: rgba(248, 250, 252, 0.96);
}

.markdown-body :deep(.code-block__lang) {
  color: #475569;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.markdown-body :deep(.code-copy) {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 28px;
  padding: 5px 10px;
  color: #475569;
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  cursor: pointer;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(203, 213, 225, 0.88);
  border-radius: 8px;
  transition: color 0.16s ease, background 0.16s ease, border-color 0.16s ease, transform 0.16s ease;
}

.markdown-body :deep(.code-copy:hover) {
  color: #0f172a;
  background: rgba(239, 246, 255, 0.96);
  border-color: rgba(147, 197, 253, 0.78);
  transform: translateY(-1px);
}

.markdown-body :deep(.code-copy--success) {
  color: #166534;
  background: rgba(220, 252, 231, 0.82);
  border-color: rgba(74, 222, 128, 0.34);
}

.markdown-body :deep(.code-copy--error) {
  color: #b91c1c;
  background: rgba(254, 226, 226, 0.84);
  border-color: rgba(248, 113, 113, 0.34);
}

.markdown-body :deep(.code-block__pre) {
  margin: 0;
  padding: 14px 16px;
  overflow-x: auto;
  color: #0f172a;
  background:
    radial-gradient(circle at top left, rgba(59, 130, 246, 0.08), transparent 34%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.96));
  border-radius: 0;
}

.markdown-body :deep(.code-block__pre code) {
  display: block;
  min-width: max-content;
  padding: 0;
  color: inherit;
  background: transparent;
  border: 0;
  border-radius: 0;
  font-size: 13px;
  line-height: 1.65;
  white-space: pre;
}

.markdown-body :deep(pre:not(.code-block__pre)) {
  margin: 12px 0;
  padding: 12px;
  overflow-x: auto;
  border-radius: 12px;
  background: #f8fafc;
  border: 1px solid rgba(226, 232, 240, 0.9);
}

.markdown-body :deep(pre:not(.code-block__pre) code) {
  padding: 0;
  background: transparent;
  border: 0;
}

.markdown-body :deep(.token-comment) {
  color: #94a3b8;
  font-style: italic;
}

.markdown-body :deep(.token-string) {
  color: #0f766e;
}

.markdown-body :deep(.token-keyword) {
  color: #2563eb;
  font-weight: 800;
}

.markdown-body :deep(.token-function) {
  color: #b45309;
}

.markdown-body :deep(.token-number) {
  color: #dc2626;
}

.markdown-body :deep(blockquote) {
  margin: 12px 0;
  padding: 9px 12px;
  color: #475569;
  background: rgba(248, 250, 252, 0.86);
  border-left: 4px solid #60a5fa;
  border-radius: 0 12px 12px 0;
}

.markdown-body :deep(table) {
  display: block;
  width: 100%;
  margin: 12px 0;
  overflow-x: auto;
  border-collapse: collapse;
  font-size: 13px;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  padding: 8px 10px;
  border: 1px solid rgba(226, 232, 240, 0.95);
}

.markdown-body :deep(th) {
  color: #0f172a;
  background: #f8fafc;
  font-weight: 800;
}

.markdown-body :deep(tr:nth-child(even) td) {
  background: rgba(248, 250, 252, 0.58);
}

.markdown-body :deep(hr) {
  height: 1px;
  margin: 16px 0;
  border: 0;
  background: linear-gradient(90deg, transparent, rgba(148, 163, 184, 0.55), transparent);
}

.markdown-body :deep(.katex-display) {
  margin: 12px 0;
  padding: 10px 12px;
  overflow-x: auto;
  overflow-y: hidden;
  border-radius: 12px;
  background: rgba(248, 250, 252, 0.86);
  border: 1px solid rgba(226, 232, 240, 0.86);
}

.markdown-body :deep(.katex) {
  font-size: 1.03em;
}

.markdown-body :deep(.math-fallback) {
  color: #be123c;
  background: rgba(244, 63, 94, 0.08);
  border-color: rgba(244, 63, 94, 0.14);
}

.markdown-body :deep(.math-fallback--block) {
  margin: 12px 0;
  white-space: pre-wrap;
}

.source-panel {
  display: grid;
  gap: 6px;
  align-items: start;
  margin-top: 8px;
}

.source-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.source-chips--compact {
  max-width: min(100%, 560px);
  margin-top: 6px;
  gap: 5px;
}

.web-source-block {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  width: fit-content;
  max-width: min(100%, 210px);
  min-height: 34px;
  padding: 6px 8px;
  color: #1f2937;
  text-align: left;
  background: rgba(248, 250, 252, 0.96);
  border: 1px solid rgba(203, 213, 225, 0.86);
  border-radius: 999px;
  cursor: pointer;
  transition: transform 0.16s ease, border-color 0.16s ease, background 0.16s ease, box-shadow 0.16s ease;
}

.course-source-disclosure {
  width: fit-content;
  max-width: 100%;
}

.course-source-summary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  width: fit-content;
  max-width: min(100%, 210px);
  min-height: 34px;
  padding: 6px 8px;
  color: #1f2937;
  list-style: none;
  background: rgba(248, 250, 252, 0.90);
  border: 1px solid rgba(203, 213, 225, 0.72);
  border-radius: 999px;
  cursor: pointer;
  transition: transform 0.16s ease, border-color 0.16s ease, background 0.16s ease, box-shadow 0.16s ease;
}

.course-source-summary::-webkit-details-marker {
  display: none;
}

.course-source-summary:hover {
  background: rgba(239, 246, 255, 0.80);
  border-color: rgba(37, 99, 235, 0.22);
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.05);
  transform: translateY(-1px);
}

.web-source-block:hover {
  background: rgba(239, 246, 255, 0.92);
  border-color: rgba(37, 99, 235, 0.28);
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.07);
  transform: translateY(-1px);
}

.web-source-block__favicons {
  display: flex;
  align-items: center;
  min-width: 22px;
  height: 22px;
  flex: 0 0 auto;
}

.course-source-summary__icons {
  display: flex;
  align-items: center;
  min-width: 22px;
  height: 22px;
  flex: 0 0 auto;
}

.web-source-block__favicon {
  position: relative;
  width: 22px;
  height: 22px;
  border: 2px solid rgba(248, 250, 252, 0.98);
  border-radius: 999px;
  background: #fff;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.10);
  overflow: hidden;
}

.course-source-summary__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  position: relative;
  width: 22px;
  height: 22px;
  border: 2px solid rgba(248, 250, 252, 0.98);
  border-radius: 999px;
  background: #fff;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.08);
  font-size: 12px;
  line-height: 1;
}

.course-source-summary__icon + .course-source-summary__icon {
  margin-left: -7px;
}

.web-source-block__favicon-fallback {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  line-height: 1;
}

.web-source-block__favicon-img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.web-source-block__favicon + .web-source-block__favicon {
  margin-left: -7px;
}

.web-source-block__body {
  min-width: 0;
  flex: 0 1 auto;
}

.course-source-summary__body {
  min-width: 0;
  flex: 0 1 auto;
}

.web-source-block__title {
  display: block;
  overflow: hidden;
  color: #0f172a;
  font-size: 12px;
  font-weight: 850;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.course-source-summary__title {
  display: block;
  overflow: hidden;
  color: #334155;
  font-size: 12px;
  font-weight: 800;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.web-source-block__arrow {
  color: #64748b;
  font-size: 16px;
  font-weight: 800;
}

.course-source-summary__arrow {
  color: #64748b;
  font-size: 16px;
  font-weight: 800;
  transition: transform 0.16s ease;
}

.course-source-disclosure[open] .course-source-summary__arrow {
  transform: rotate(90deg);
}

.source-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  max-width: 100%;
  padding: 5px 9px;
  color: #334155;
  font-size: 12px;
  font-weight: 700;
  text-decoration: none;
  background: rgba(248, 250, 252, 0.95);
  border: 1px solid rgba(203, 213, 225, 0.82);
  border-radius: 999px;
}

.source-chips--compact .source-chip {
  max-width: min(100%, 280px);
  padding: 3px 7px;
  color: #64748b;
  font-size: 11px;
  font-weight: 650;
  background: rgba(248, 250, 252, 0.64);
  border-color: rgba(203, 213, 225, 0.58);
}

.source-chip[href]:hover {
  color: #1d4ed8;
  border-color: rgba(37, 99, 235, 0.28);
  background: rgba(37, 99, 235, 0.06);
}

.source-chip__text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-chip__detail {
  color: #64748b;
  font-weight: 650;
}

.assistant-actions {
  display: flex;
  justify-content: flex-start;
  margin-top: 10px;
}

.assistant-action-button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 30px;
  padding: 5px 10px;
  color: #78716c;
  font-size: 12px;
  font-weight: 750;
  line-height: 1;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 999px;
  cursor: pointer;
  transition: color 0.16s ease, background 0.16s ease, border-color 0.16s ease, transform 0.16s ease;
}

.assistant-action-button:hover {
  color: #292524;
  background: rgba(245, 245, 244, 0.86);
  border-color: rgba(214, 211, 209, 0.88);
  transform: translateY(-1px);
}

.assistant-action-button--success {
  color: #15803d;
  background: rgba(220, 252, 231, 0.78);
  border-color: rgba(74, 222, 128, 0.34);
}

.assistant-action-button--error {
  color: #b91c1c;
  background: rgba(254, 226, 226, 0.82);
  border-color: rgba(248, 113, 113, 0.34);
}

.assistant-action-button__icon {
  font-size: 13px;
  line-height: 1;
}

.user-bubble .source-panel {
  color: #475569;
  border-top-color: rgba(148, 163, 184, 0.18);
}




















@media (max-width: 760px) {
  .message-bubble {
    max-width: calc(100% - 52px);
  }

  .markdown-body :deep(.code-block__header) {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
