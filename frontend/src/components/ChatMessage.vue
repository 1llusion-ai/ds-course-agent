<template>
  <div class="message-wrapper" :class="{ 'user-message': message.role === 'user' }">
    <div class="avatar"
      :class="message.role === 'user' ? 'user-avatar' : 'ai-avatar'"
    >
      {{ message.role === 'user' ? '我' : '🤖' }}
    </div>

    <div class="message-bubble"
      :class="message.role === 'user' ? 'user-bubble' : 'ai-bubble'"
    >
      <div v-if="message.role === 'user'" class="message-content">{{ message.content }}</div>
      <div v-else-if="message.isLoading" class="message-content loading-content">
        <span class="loading-dot"></span>
        <span class="loading-dot"></span>
        <span class="loading-dot"></span>
      </div>
      <div v-else class="message-content markdown-body" v-html="renderedContent"></div>

      <div v-if="message.sources?.length" class="message-source">
        <span>📚</span><span>{{ renderedSources }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { marked } from 'marked'
import katex from 'katex'
import 'katex/dist/katex.min.css'

const props = defineProps({ message: { type: Object, required: true }})

function renderMarkdownWithMath(text) {
  const inlineMath = []
  const blockMath = []

  let t = text

  // 1. 兼容 LLM 误用的 [ ... ] 块级公式（单独成行且含 LaTeX 特征）
  t = t.replace(/(?:^|\n)\[(\n[\s\S]*?\n)\](?=\n|$)/g, (match, code) => {
    if (/[\\^_=]|\\(frac|sum|int|lambda|alpha|beta|Delta|times|cdot|pm|leq|geq)/.test(code)) {
      blockMath.push(code.trim())
      return `\n<BLOCK_MATH_${blockMath.length - 1}>\n`
    }
    return match
  })

  // 2. 提取标准块级公式 $$...$$
  t = t.replace(/\$\$([\s\S]*?)\$\$/g, (_, code) => {
    blockMath.push(code.trim())
    return `<BLOCK_MATH_${blockMath.length - 1}>`
  })

  // 3. 提取行内公式 $...$（避免匹配 $$$ 或连续$）
  t = t.replace(/(?<!\$)\$(?!\$)([^\$\n]+?)\$(?!\$)/g, (_, code) => {
    inlineMath.push(code.trim())
    return `<INLINE_MATH_${inlineMath.length - 1}>`
  })

  // 4. Markdown 渲染
  let html = marked.parse(t, { breaks: true, gfm: true })

  // 5. 恢复块级公式
  blockMath.forEach((code, i) => {
    try {
      const rendered = katex.renderToString(code, { throwOnError: false, displayMode: true })
      html = html.replace(`<BLOCK_MATH_${i}>`, rendered)
    } catch (e) {
      html = html.replace(`<BLOCK_MATH_${i}>`, `<pre>${code}</pre>`)
    }
  })

  // 6. 恢复行内公式
  inlineMath.forEach((code, i) => {
    try {
      const rendered = katex.renderToString(code, { throwOnError: false, displayMode: false })
      html = html.replace(`<INLINE_MATH_${i}>`, rendered)
    } catch (e) {
      html = html.replace(`<INLINE_MATH_${i}>`, `<code>${code}</code>`)
    }
  })

  return html
}

const renderedContent = computed(() => {
  if (!props.message.content) return ''
  return renderMarkdownWithMath(props.message.content)
})

const renderedSources = computed(() => {
  const refs = props.message.sources?.map(source => source.reference).filter(Boolean) ?? []
  return refs.length ? `来源：${refs.join('；')}` : ''
})
</script>

<style scoped>
.message-wrapper {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.message-wrapper.user-message {
  flex-direction: row-reverse;
}

.avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 500;
  flex-shrink: 0;
}

.user-avatar {
  background: linear-gradient(135deg, #fbbf24 0%, #f97316 100%);
  color: white;
}

.ai-avatar {
  background: linear-gradient(135deg, #6366f1 0%, #7c3aed 100%);
  color: white;
}

.message-bubble {
  max-width: 70%;
  padding: 12px 16px;
  border-radius: 16px;
}

.user-bubble {
  background: #4f46e5;
  color: white;
  border-top-right-radius: 4px;
}

.ai-bubble {
  background: white;
  border: 1px solid #e7e5e4;
  border-top-left-radius: 4px;
}

.message-content {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
}

.loading-content {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 24px;
}

.loading-dot {
  width: 8px;
  height: 8px;
  background: #a8a29e;
  border-radius: 50%;
  animation: bubble-bounce 1.4s infinite ease-in-out both;
}

.loading-dot:nth-child(1) { animation-delay: -0.32s; }
.loading-dot:nth-child(2) { animation-delay: -0.16s; }

@keyframes bubble-bounce {
  0%, 80%, 100% { transform: scale(0); }
  40% { transform: scale(1); }
}

.user-bubble .message-content {
  white-space: pre-wrap;
}

.markdown-body {
  white-space: normal;
}

.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  margin: 12px 0 8px;
  font-weight: 600;
  line-height: 1.4;
}

.markdown-body :deep(h1) { font-size: 18px; }
.markdown-body :deep(h2) { font-size: 16px; }
.markdown-body :deep(h3) { font-size: 15px; }
.markdown-body :deep(h4) { font-size: 14px; }

.markdown-body :deep(p) {
  margin: 8px 0;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 8px 0;
  padding-left: 20px;
}

.markdown-body :deep(li) {
  margin: 4px 0;
}

.markdown-body :deep(strong) {
  font-weight: 600;
}

.markdown-body :deep(a) {
  color: #4f46e5;
  text-decoration: underline;
}

.markdown-body :deep(code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  background: #f5f5f4;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
  color: #1c1917;
}

.markdown-body :deep(pre) {
  background: #f5f5f4;
  padding: 12px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 8px 0;
}

.markdown-body :deep(pre code) {
  background: transparent;
  padding: 0;
}

.markdown-body :deep(blockquote) {
  margin: 8px 0;
  padding-left: 12px;
  border-left: 3px solid #d6d3d1;
  color: #57534e;
}

/* KaTeX 公式样式微调 */
.markdown-body :deep(.katex-display) {
  margin: 8px 0;
  overflow-x: auto;
  overflow-y: hidden;
}

.markdown-body :deep(.katex) {
  font-size: 1em;
}

.message-source {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid rgba(0,0,0,0.1);
  font-size: 12px;
  opacity: 0.7;
  display: flex;
  align-items: center;
  gap: 4px;
}

.user-bubble .message-source {
  border-top-color: rgba(255,255,255,0.2);
}
</style>
