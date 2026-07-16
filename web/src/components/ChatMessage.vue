<template>
  <div class="message-wrapper" :class="{ 'user-message': message.role === 'user' }">
    <div
      class="message-bubble"
      :class="[
        message.role === 'user' ? 'user-bubble' : 'ai-bubble',
        { 'is-loading': message.isLoading, 'is-error': message.isError }
      ]"
    >
      <div v-if="message.role !== 'user' && (routeBadge || message.isLoading)" class="message-topline">
        <span v-if="routeBadge" class="route-badge" :title="`Route: ${routeBadge}`">
          <span class="route-dot"></span>
          {{ routeBadge }}
        </span>
        <span v-if="message.isLoading" class="live-badge">
          <span class="live-pulse"></span>
          正在生成
        </span>
      </div>

      <div v-if="message.role === 'user'" class="message-content user-content">
        {{ message.content }}
      </div>

      <template v-else-if="message.isLoading && !message.content">
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

      <details v-if="showProgressTimeline" class="progress-disclosure">
        <summary class="progress-summary">
          <span class="progress-summary__left">
            <span class="progress-summary__chevron">›</span>
            <span>{{ message.isLoading ? currentProgressMessage || '正在处理...' : '查看执行过程' }}</span>
          </span>
          <span class="progress-summary__meta">{{ progressSummary }}</span>
        </summary>

        <div class="progress-timeline" aria-live="polite">
          <div
            v-for="(item, index) in progressItems"
            :key="item.key"
            class="progress-step"
            :class="{
              'progress-step--active': message.isLoading && index === progressItems.length - 1,
              'progress-step--done': !message.isLoading || index < progressItems.length - 1
            }"
          >
            <span class="progress-step__marker"></span>
            <div class="progress-step__body">
              <div class="progress-step__title">{{ item.message }}</div>
              <div v-if="item.phase || item.route || item.time" class="progress-step__meta">
                <span v-if="item.phase">{{ item.phase }}</span>
                <span v-if="item.route">{{ item.route }}</span>
                <span v-if="item.time">{{ item.time }}</span>
              </div>
            </div>
          </div>
        </div>
      </details>

      <div v-if="sourceChips.length" class="source-panel">
        <div class="source-panel__label">来源</div>
        <div class="source-chips">
          <component
            :is="source.url ? 'a' : 'span'"
            v-for="source in sourceChips"
            :key="source.key"
            class="source-chip"
            :href="source.url || undefined"
            target="_blank"
            rel="noopener noreferrer"
            :title="source.title"
          >
            <span class="source-chip__icon">📚</span>
            <span class="source-chip__text">{{ source.label }}</span>
            <span v-if="source.detail" class="source-chip__detail">{{ source.detail }}</span>
          </component>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import 'katex/dist/katex.min.css'

import { isJavascriptUrl, renderMarkdownWithEnhancements } from '../utils/markdown'

const props = defineProps({
  message: {
    type: Object,
    required: true
  }
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
  tool: '工具调用'
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
  return source.section || source.page || source.metadata?.section || source.metadata?.page || ''
}

function sourceUrl(source) {
  if (!source || typeof source === 'string') return ''
  return safeExternalUrl(source.url || source.href || source.link || source.metadata?.url || source.metadata?.href)
}

function formatProgressPhase(phase) {
  if (!phase) return ''
  const text = String(phase).replace(/[_-]+/g, ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

function formatProgressTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

const renderedContent = computed(() => renderMarkdownWithEnhancements(props.message.content || ''))

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
      message,
      phase,
      route,
      time: formatProgressTime(value.timestamp || value.time || value.created_at)
    }
  })
})

const currentProgressMessage = computed(() => {
  const items = progressItems.value
  return items.length ? items[items.length - 1].message : ''
})

const progressSummary = computed(() => {
  const count = progressItems.value.length
  const route = routeBadge.value
  return [count ? `${count} 步` : '', route].filter(Boolean).join(' · ')
})

const hasExplicitProgressEvents = computed(() => (
  Array.isArray(props.message.progressEvents) && props.message.progressEvents.length > 0
) || (
  Array.isArray(props.message.progress_events) && props.message.progress_events.length > 0
))

const showProgressTimeline = computed(() => (
  props.message.role !== 'user' &&
  progressItems.value.length > 0 &&
  (props.message.isLoading || hasExplicitProgressEvents.value)
))

const routeBadge = computed(() => {
  const items = progressItems.value
  const lastProgressRoute = items.length ? items[items.length - 1].route : ''
  return formatRoute(
    props.message.route ||
    props.message.metadata?.route ||
    props.message.progress?.route ||
    lastProgressRoute
  )
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
        label,
        detail,
        url,
        title: detail ? `${label} · ${detail}` : label
      }
    })
    .filter(source => {
      if (!source.label || seen.has(source.key)) return false
      seen.add(source.key)
      return true
    })
    .slice(0, 8)
})

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
</script>

<style scoped>
.message-wrapper {
  display: flex;
  align-items: flex-start;
}

.message-wrapper.user-message {
  justify-content: flex-end;
}

.message-wrapper:not(.user-message) {
  justify-content: flex-start;
}

.message-bubble {
  max-width: min(78%, 880px);
  padding: 12px 16px;
  border-radius: 18px;
  box-shadow: 0 16px 36px rgba(28, 25, 23, 0.06);
}

.user-bubble {
  color: #fff;
  background: linear-gradient(135deg, #1d4ed8 0%, #2563eb 100%);
}

.ai-bubble {
  position: relative;
  color: #1c1917;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.97) 0%, rgba(255, 252, 247, 0.93) 100%);
  border: 1px solid rgba(226, 232, 240, 0.92);
  backdrop-filter: blur(12px);
}

.ai-bubble::before {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  border-radius: inherit;
  background: linear-gradient(135deg, rgba(37, 99, 235, 0.08), transparent 36%, rgba(15, 118, 110, 0.06));
}

.ai-bubble > * {
  position: relative;
}

.ai-bubble.is-error {
  border-color: rgba(248, 113, 113, 0.42);
  background: linear-gradient(180deg, rgba(255, 247, 247, 0.98) 0%, rgba(255, 255, 255, 0.94) 100%);
}

.message-topline {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}

.route-badge,
.live-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 22px;
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.01em;
}

.route-badge {
  color: #1d4ed8;
  background: rgba(37, 99, 235, 0.08);
  border: 1px solid rgba(37, 99, 235, 0.12);
}

.route-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: linear-gradient(135deg, #2563eb, #14b8a6);
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
}

.live-badge {
  color: #0f766e;
  background: rgba(20, 184, 166, 0.1);
  border: 1px solid rgba(20, 184, 166, 0.16);
}

.live-pulse {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: currentColor;
  animation: pulse 1.25s infinite ease-in-out;
}

.message-content {
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

.progress-disclosure {
  margin-top: 12px;
}

.progress-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 34px;
  padding: 7px 10px;
  color: #475569;
  list-style: none;
  background: rgba(248, 250, 252, 0.74);
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 999px;
  cursor: pointer;
  transition: background 0.16s ease, border-color 0.16s ease;
}

.progress-summary::-webkit-details-marker {
  display: none;
}

.progress-summary:hover {
  background: rgba(239, 246, 255, 0.82);
  border-color: rgba(37, 99, 235, 0.18);
}

.progress-summary__left {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  font-size: 12px;
  font-weight: 800;
}

.progress-summary__left span:last-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.progress-summary__chevron {
  display: inline-grid;
  place-items: center;
  width: 18px;
  height: 18px;
  color: #2563eb;
  background: rgba(37, 99, 235, 0.08);
  border-radius: 999px;
  transition: transform 0.16s ease;
}

.progress-disclosure[open] .progress-summary__chevron {
  transform: rotate(90deg);
}

.progress-summary__meta {
  flex-shrink: 0;
  color: #64748b;
  font-size: 11px;
  font-weight: 750;
}

.progress-timeline {
  display: grid;
  gap: 0;
  margin-top: 8px;
  padding: 10px 12px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 14px;
  background: rgba(248, 250, 252, 0.72);
}

.progress-step {
  position: relative;
  display: grid;
  grid-template-columns: 16px minmax(0, 1fr);
  gap: 9px;
  padding: 0 0 10px;
  color: #64748b;
}

.progress-step:last-child {
  padding-bottom: 0;
}

.progress-step:not(:last-child)::after {
  content: '';
  position: absolute;
  top: 16px;
  bottom: -1px;
  left: 7px;
  width: 2px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.25);
}

.progress-step__marker {
  width: 12px;
  height: 12px;
  margin-top: 4px;
  border-radius: 999px;
  border: 2px solid rgba(148, 163, 184, 0.55);
  background: #fff;
  z-index: 1;
}

.progress-step--done .progress-step__marker {
  border-color: #14b8a6;
  background: #14b8a6;
  box-shadow: inset 0 0 0 2px #fff;
}

.progress-step--active .progress-step__marker {
  border-color: #2563eb;
  background: #2563eb;
  box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.12);
  animation: pulse 1.2s infinite ease-in-out;
}

.progress-step__title {
  color: #334155;
  font-size: 13px;
  font-weight: 700;
  line-height: 1.45;
}

.progress-step__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 3px;
  font-size: 11px;
  color: #64748b;
}

.progress-step__meta span {
  padding: 1px 6px;
  border-radius: 999px;
  background: rgba(226, 232, 240, 0.8);
}

@keyframes bubble-bounce {
  0%, 80%, 100% {
    transform: scale(0);
  }

  40% {
    transform: scale(1);
  }
}

@keyframes pulse {
  0%, 100% {
    transform: scale(0.92);
    opacity: 0.58;
  }

  50% {
    transform: scale(1.08);
    opacity: 1;
  }
}

.markdown-body {
  white-space: normal;
  color: #1f2937;
  font-size: 14px;
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
  font-size: 20px;
}

.markdown-body :deep(h2) {
  padding-bottom: 5px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.95);
  font-size: 17px;
}

.markdown-body :deep(h3) {
  font-size: 15px;
}

.markdown-body :deep(h4) {
  font-size: 14px;
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
  border: 1px solid rgba(15, 23, 42, 0.12);
  border-radius: 14px;
  background: #0f172a;
  box-shadow: 0 14px 30px rgba(15, 23, 42, 0.12);
}

.markdown-body :deep(.code-block__header) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px 8px 12px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.18);
  background: linear-gradient(180deg, rgba(30, 41, 59, 0.98), rgba(15, 23, 42, 0.96));
}

.markdown-body :deep(.code-block__lang) {
  color: #cbd5e1;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.markdown-body :deep(.code-copy) {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 8px;
  color: #cbd5e1;
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  cursor: pointer;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 8px;
  transition: color 0.16s ease, background 0.16s ease, border-color 0.16s ease, transform 0.16s ease;
}

.markdown-body :deep(.code-copy:hover) {
  color: #fff;
  background: rgba(37, 99, 235, 0.38);
  border-color: rgba(96, 165, 250, 0.45);
  transform: translateY(-1px);
}

.markdown-body :deep(.code-copy--success) {
  color: #dcfce7;
  background: rgba(22, 163, 74, 0.35);
  border-color: rgba(74, 222, 128, 0.45);
}

.markdown-body :deep(.code-copy--error) {
  color: #fee2e2;
  background: rgba(220, 38, 38, 0.35);
  border-color: rgba(248, 113, 113, 0.45);
}

.markdown-body :deep(.code-block__pre) {
  margin: 0;
  padding: 14px 16px;
  overflow-x: auto;
  color: #dbeafe;
  background:
    radial-gradient(circle at top left, rgba(37, 99, 235, 0.17), transparent 32%),
    #0f172a;
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
  color: #86efac;
}

.markdown-body :deep(.token-keyword) {
  color: #93c5fd;
  font-weight: 800;
}

.markdown-body :deep(.token-function) {
  color: #fde68a;
}

.markdown-body :deep(.token-number) {
  color: #fca5a5;
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
  gap: 7px;
  margin-top: 12px;
  padding-top: 11px;
  border-top: 1px solid rgba(148, 163, 184, 0.18);
}

.source-panel__label {
  color: #64748b;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.source-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
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

.user-bubble .source-panel {
  color: rgba(255, 255, 255, 0.86);
  border-top-color: rgba(255, 255, 255, 0.2);
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
