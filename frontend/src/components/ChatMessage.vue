<template>
  <div class="message-wrapper" :class="{ 'user-message': message.role === 'user' }">
    <div class="avatar" :class="message.role === 'user' ? 'user-avatar' : 'ai-avatar'">
      <img v-if="message.role === 'user'" src="/avatar/Student.png" alt="学生" class="avatar-img" />
      <img v-else src="/avatar/Assistant.png" alt="AI助手" class="avatar-img" />
    </div>

    <div class="message-bubble" :class="message.role === 'user' ? 'user-bubble' : 'ai-bubble'">
      <div v-if="message.role === 'user'" class="message-content">
        {{ message.content }}
      </div>

      <template v-else-if="message.isLoading && !message.content">
        <div class="message-content loading-content">
          <span class="loading-dot"></span>
          <span class="loading-dot"></span>
          <span class="loading-dot"></span>
        </div>
      </template>

      <template v-else>
        <!-- 流式生成期间显示纯文本，避免频繁重渲染 markdown/katex -->
        <div v-if="message.isLoading" class="message-content">{{ message.content }}</div>
        <div v-else class="message-content markdown-body" v-html="renderedContent"></div>
        <div v-if="message.isLoading" class="streaming-status">
          <span class="streaming-pulse"></span>
          <span>生成中</span>
        </div>
      </template>

      <div v-if="message.sources?.length" class="message-source">
        <span>📚来源：</span><span>{{ renderedSources }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { marked } from 'marked'
import katex from 'katex'
import 'katex/dist/katex.min.css'

const props = defineProps({
  message: {
    type: Object,
    required: true
  }
})

function renderMarkdownWithMath(text) {
  if (!text) {
    return ''
  }

  const blockMath = []
  const inlineMath = []
  let content = text

  // 处理块级公式: $$...$$ 和 [\...]...\ (LaTeX 风格)
  content = content.replace(/\$\$([\s\S]*?)\$\$/g, (_, code) => {
    blockMath.push(code.trim())
    return `<BLOCK_MATH_${blockMath.length - 1}>`
  })

  // 处理 LaTeX 风格的 \[\]...\ 块级公式 (AI使用的格式)
  content = content.replace(/\\\[\s*([\s\S]*?)\\\]\s*/g, (_, code) => {
    blockMath.push(code.trim())
    return `<BLOCK_MATH_${blockMath.length - 1}>`
  })

  content = content.replace(/(?<!\$)\$(?!\$)([^\$\n]+?)\$(?!\$)/g, (_, code) => {
    inlineMath.push(code.trim())
    return `<INLINE_MATH_${inlineMath.length - 1}>`
  })

  let html = marked.parse(content, { breaks: true, gfm: true })

  blockMath.forEach((code, index) => {
    try {
      html = html.replace(
        `<BLOCK_MATH_${index}>`,
        katex.renderToString(code, { throwOnError: false, displayMode: true })
      )
    } catch (error) {
      html = html.replace(`<BLOCK_MATH_${index}>`, `<pre>${code}</pre>`)
    }
  })

  inlineMath.forEach((code, index) => {
    try {
      html = html.replace(
        `<INLINE_MATH_${index}>`,
        katex.renderToString(code, { throwOnError: false, displayMode: false })
      )
    } catch (error) {
      html = html.replace(`<INLINE_MATH_${index}>`, `<code>${code}</code>`)
    }
  })

  return html
}

const renderedContent = computed(() => renderMarkdownWithMath(props.message.content || ''))

const renderedSources = computed(() => {
  const refs = props.message.sources?.map(source => source.reference).filter(Boolean) ?? []
  return refs.join('；')
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
  flex-shrink: 0;
  overflow: hidden;
}

.avatar-img {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  object-fit: cover;
}

.user-avatar {
  color: #fff;
  background: linear-gradient(135deg, #f59e0b 0%, #ea580c 100%);
}

.ai-avatar {
  color: #fff;
  background: linear-gradient(135deg, #2563eb 0%, #0f766e 100%);
}

.message-bubble {
  max-width: 72%;
  padding: 12px 16px;
  border-radius: 18px;
  box-shadow: 0 12px 28px rgba(28, 25, 23, 0.04);
}

.user-bubble {
  color: #fff;
  background: linear-gradient(135deg, #1d4ed8 0%, #2563eb 100%);
  border-top-right-radius: 6px;
}

.ai-bubble {
  color: #1c1917;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(231, 229, 228, 0.92);
  border-top-left-radius: 6px;
}

.message-content {
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
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
  border-radius: 50%;
  background: #a8a29e;
  animation: bubble-bounce 1.4s infinite ease-in-out both;
}

.loading-dot:nth-child(1) {
  animation-delay: -0.32s;
}

.loading-dot:nth-child(2) {
  animation-delay: -0.16s;
}

.streaming-status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(37, 99, 235, 0.08);
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 600;
}

.streaming-pulse {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
  animation: pulse 1.2s infinite ease-in-out;
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
    transform: scale(0.9);
    opacity: 0.45;
  }

  50% {
    transform: scale(1.1);
    opacity: 1;
  }
}

.markdown-body {
  white-space: normal;
}

.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  margin: 12px 0 8px;
  font-weight: 700;
  line-height: 1.4;
}

.markdown-body :deep(h1) {
  font-size: 18px;
}

.markdown-body :deep(h2) {
  font-size: 16px;
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

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 8px 0;
  padding-left: 20px;
}

.markdown-body :deep(li) {
  margin: 4px 0;
}

.markdown-body :deep(a) {
  color: #1d4ed8;
  text-decoration: underline;
}

.markdown-body :deep(code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  background: #f5f5f4;
  color: #111827;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
}

.markdown-body :deep(pre) {
  margin: 10px 0;
  padding: 12px;
  overflow-x: auto;
  border-radius: 10px;
  background: #f5f5f4;
}

.markdown-body :deep(pre code) {
  padding: 0;
  background: transparent;
}

.markdown-body :deep(blockquote) {
  margin: 10px 0;
  padding-left: 12px;
  border-left: 3px solid #d6d3d1;
  color: #57534e;
}

.markdown-body :deep(.katex-display) {
  margin: 8px 0;
  overflow-x: auto;
  overflow-y: hidden;
}

.markdown-body :deep(.katex) {
  font-size: 1em;
}

.message-source {
  display: flex;
  gap: 8px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid rgba(0, 0, 0, 0.08);
  font-size: 12px;
  color: #57534e;
}

.user-bubble .message-source {
  color: rgba(255, 255, 255, 0.86);
  border-top-color: rgba(255, 255, 255, 0.2);
}
</style>
