<template>
  <div class="chat-input-wrapper" :class="{ 'chat-input-wrapper--hero': hero }">
    <div class="input-container">
      <textarea
        v-model="inputText"
        rows="1"
        class="input-field"
        :placeholder="placeholder"
        @keydown.enter="handleEnterKey"
        @input="handleInput"
        ref="textareaRef"
      />
      <div class="composer-toolbar" :class="{ 'composer-toolbar--hero': hero }">
        <div class="composer-toolbar-left">
          <button
            type="button"
            class="web-search-toggle"
            :class="{ 'web-search-toggle--active': webSearchEnabled }"
            :aria-pressed="webSearchEnabled"
            :title="webSearchEnabled ? '联网搜索已开启' : '开启联网搜索'"
            :disabled="loading"
            @click="handleToggleWebSearch"
          >
            <svg class="web-search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <circle cx="12" cy="12" r="9" stroke-width="1.9" />
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.9" d="M3.6 9h16.8M3.6 15h16.8M12 3c2.2 2.4 3.3 5.4 3.3 9S14.2 18.6 12 21M12 3C9.8 5.4 8.7 8.4 8.7 12s1.1 6.6 3.3 9" />
            </svg>
            <span class="web-search-label">联网搜索</span>
          </button>
          <div v-if="!hero" class="input-hint">
            <span>Enter 发送 · Shift+Enter 换行</span>
            <span>{{ webSearchHintText }}</span>
          </div>
        </div>
        <button
          type="button"
          class="send-btn"
          :class="{ 'send-btn--stop': loading }"
          :disabled="!loading && !inputText.trim()"
          :aria-label="loading ? '停止生成' : '发送消息'"
          :title="loading ? '停止生成' : '发送消息'"
          @click="handlePrimaryAction"
        >
          <svg v-if="loading" class="stop-icon" viewBox="0 0 24 24" aria-hidden="true">
            <rect x="7.5" y="7.5" width="9" height="9" rx="1.8" fill="currentColor" />
          </svg>
          <svg v-else class="send-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.2" d="M5 12h14M12 5l7 7-7 7"/>
          </svg>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, nextTick, watch } from 'vue'

const props = defineProps({
  loading: Boolean,
  hero: Boolean,
  webSearchEnabled: Boolean,
  initialText: { type: String, default: '' },
  webSearchHint: {
    type: String,
    default: ''
  }
})
const emit = defineEmits(['send', 'toggle-web-search', 'cancel'])

const inputText = ref('')
const textareaRef = ref(null)
const initialTextApplied = ref('')
const userEdited = ref(false)

watch(() => props.initialText, value => {
  if (!userEdited.value && (!inputText.value || inputText.value === initialTextApplied.value)) {
    inputText.value = value
    initialTextApplied.value = value
    autoResize()
  }
}, { immediate: true })
const placeholder = computed(() => props.hero
  ? '问一个数据科学问题、公式推导或代码练习...'
  : '问一个课程概念、公式推导或代码问题...'
)
const webSearchHintText = computed(() => (
  props.webSearchHint || (props.webSearchEnabled ? '将使用外部搜索结果' : '基于教材与学习画像回答')
))

function autoResize() {
  nextTick(() => {
    const t = textareaRef.value
    if (t) {
      t.style.height = 'auto'
      t.style.height = Math.min(t.scrollHeight, 120) + 'px'
    }
  })
}

function handleInput() {
  userEdited.value = true
  autoResize()
}

function handleSend() {
  const text = inputText.value.trim()
  if (!text || props.loading) return
  const restoreDraft = () => {
    if (inputText.value.trim()) return
    inputText.value = text
    userEdited.value = true
    autoResize()
    nextTick(() => textareaRef.value?.focus())
  }
  emit('send', text, { webSearch: props.webSearchEnabled }, restoreDraft)
  inputText.value = ''
  userEdited.value = false
  initialTextApplied.value = ''
  nextTick(() => {
    if (textareaRef.value) textareaRef.value.style.height = 'auto'
  })
}

function handleToggleWebSearch() {
  if (props.loading) return
  emit('toggle-web-search', !props.webSearchEnabled)
}

function handleCancel() {
  emit('cancel')
}

function handlePrimaryAction() {
  if (props.loading) {
    handleCancel()
    return
  }
  handleSend()
}

function handleEnterKey(event) {
  if (event.shiftKey || event.isComposing) {
    return
  }
  event.preventDefault()
  handleSend()
}
</script>

<style scoped>
.chat-input-wrapper {
  width: 100%;
  max-width: var(--chat-thread-width, 820px);
  margin: 0 auto;
}

.chat-input-wrapper--hero {
  max-width: 800px;
}

.input-container {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
  background: var(--surface-raised);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 12px 12px 10px 14px;
  box-shadow: var(--shadow-sm);
  transition: border-color 160ms ease, box-shadow 160ms ease;
}

.chat-input-wrapper--hero .input-container {
  border-radius: 18px;
  padding: 16px 14px 12px 18px;
  box-shadow: var(--shadow-sm);
}

.input-container:focus-within {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--focus-ring);
}

.input-field {
  width: 100%;
  background: transparent;
  border: none;
  outline: none;
  resize: none;
  font-size: 16px;
  line-height: 1.68;
  color: var(--text);
  min-height: 34px;
  max-height: 150px;
  font-family: inherit;
  padding: 4px 0;
  box-sizing: border-box;
}

.chat-input-wrapper--hero .input-field {
  min-height: 66px;
  font-size: 17px;
}

.input-field::placeholder {
  color: var(--text-faint);
}

.composer-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 0;
  padding: 0;
}

.composer-toolbar--hero {
  justify-content: space-between;
}

.composer-toolbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  flex: 1;
}

.web-search-toggle {
  height: 32px;
  padding: 0 10px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  flex-shrink: 0;
  font: inherit;
  font-size: 12px;
  font-weight: 650;
  box-shadow: none;
  transition: color 160ms ease, background 160ms ease, border-color 160ms ease;
}

.web-search-toggle:hover:not(:disabled) {
  color: var(--text);
  background: var(--surface-hover);
  border-color: var(--border-strong);
}

.web-search-toggle--active {
  color: var(--accent);
  border-color: var(--accent);
  background: var(--accent-subtle);
  box-shadow: none;
}

.web-search-toggle:disabled {
  opacity: 0.52;
  cursor: not-allowed;
}

.web-search-icon {
  width: 16px;
  height: 16px;
}

.chat-input-wrapper--hero .web-search-toggle {
  height: 34px;
  padding: 0 11px;
}

.send-btn {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-sm);
  background: var(--accent);
  color: var(--accent-contrast);
  border: 1px solid var(--accent);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 160ms ease, border-color 160ms ease;
  flex-shrink: 0;
  box-shadow: none;
}

.send-btn:hover:not(:disabled) {
  background: var(--accent-hover);
  border-color: var(--accent-hover);
}

.send-btn--stop {
  background: var(--text);
  border-color: var(--text);
  box-shadow: none;
}

.send-btn--stop:hover {
  background: var(--text-muted);
  border-color: var(--text-muted);
}

.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.send-icon {
  width: 20px;
  height: 20px;
}

.stop-icon {
  width: 20px;
  height: 20px;
}

.input-hint {
  display: flex;
  justify-content: flex-start;
  gap: 14px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--text-faint);
  margin-top: 0;
  min-width: 0;
}


@media (max-width: 560px) {
  .composer-toolbar {
    gap: 10px;
  }

  .web-search-toggle {
    padding: 0 12px;
  }

  .input-hint {
    display: none;
  }
}
</style>
