<template>
  <div class="chat-input-wrapper" :class="{ 'chat-input-wrapper--hero': hero }">
    <div class="input-container">
      <textarea
        v-model="inputText"
        rows="1"
        class="input-field"
        :placeholder="placeholder"
        @keydown.enter="handleEnterKey"
        @input="autoResize"
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
import { computed, ref, nextTick } from 'vue'

const props = defineProps({
  loading: Boolean,
  hero: Boolean,
  webSearchEnabled: Boolean,
  webSearchHint: {
    type: String,
    default: ''
  }
})
const emit = defineEmits(['send', 'toggle-web-search', 'cancel'])

const inputText = ref('')
const textareaRef = ref(null)
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

function handleSend() {
  const text = inputText.value.trim()
  if (!text || props.loading) return
  emit('send', text, { webSearch: props.webSearchEnabled })
  inputText.value = ''
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
  gap: 10px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(255, 255, 255, 0.92));
  border: 1px solid rgba(148, 163, 184, 0.26);
  border-radius: 22px;
  padding: 14px 14px 14px 18px;
  box-shadow:
    0 20px 50px rgba(15, 23, 42, 0.10),
    0 1px 0 rgba(255, 255, 255, 0.88) inset;
  backdrop-filter: blur(18px);
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.chat-input-wrapper--hero .input-container {
  border-color: rgba(15, 23, 42, 0.07);
  border-radius: 28px;
  padding: 20px 18px 16px 22px;
  box-shadow:
    0 24px 70px rgba(15, 23, 42, 0.10),
    0 1px 0 rgba(255, 255, 255, 0.92) inset;
}

.input-container:focus-within {
  border-color: rgba(79, 70, 229, 0.46);
  box-shadow:
    0 24px 60px rgba(79, 70, 229, 0.13),
    0 0 0 4px rgba(79, 70, 229, 0.08);
  transform: translateY(-1px);
}

.input-field {
  width: 100%;
  background: transparent;
  border: none;
  outline: none;
  resize: none;
  font-size: 16px;
  line-height: 1.68;
  color: #44403c;
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
  color: #a8a29e;
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
  height: 34px;
  padding: 0 13px;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.30);
  background: rgba(255, 255, 255, 0.78);
  color: #64748b;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  flex-shrink: 0;
  font: inherit;
  font-size: 12px;
  font-weight: 800;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.05);
  transition: all 0.18s ease;
}

.web-search-toggle:hover:not(:disabled) {
  color: #2563eb;
  border-color: rgba(37, 99, 235, 0.36);
  transform: translateY(-1px);
}

.web-search-toggle--active {
  color: #0f766e;
  border-color: rgba(15, 118, 110, 0.34);
  background: linear-gradient(135deg, rgba(240, 253, 250, 0.96), rgba(239, 246, 255, 0.96));
  box-shadow: 0 12px 24px rgba(15, 118, 110, 0.12);
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
  height: 36px;
  padding: 0 15px;
}

.send-btn {
  width: 44px;
  height: 44px;
  border-radius: 15px;
  background: linear-gradient(135deg, #4f46e5 0%, #2563eb 52%, #0f766e 100%);
  color: white;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
  flex-shrink: 0;
  box-shadow: 0 14px 28px rgba(37, 99, 235, 0.25);
}

.send-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 18px 34px rgba(37, 99, 235, 0.32);
}

.send-btn--stop {
  background: linear-gradient(135deg, #64748b, #475569);
  box-shadow: 0 12px 24px rgba(71, 85, 105, 0.22);
}

.send-btn--stop:hover {
  box-shadow: 0 16px 30px rgba(71, 85, 105, 0.30);
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
  color: #94a3b8;
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
