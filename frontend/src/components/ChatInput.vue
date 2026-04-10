<template>
  <div class="chat-input-wrapper">
    <div class="input-container">
      <textarea
        v-model="inputText"
        rows="1"
        class="input-field"
        placeholder="输入问题，按 Enter 发送..."
        @keydown.enter.prevent="handleSend"
        @input="autoResize"
        ref="textareaRef"
      />
      <button
        class="send-btn"
        :disabled="!inputText.trim() || loading"
        @click="handleSend"
      >
        <svg v-if="!loading" class="send-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 12h14M12 5l7 7-7 7"/>
        </svg>
        <span v-else>...</span>
      </button>
    </div>
    <p class="input-hint">AI 助手基于课程教材回答，仅供参考</p>
  </div>
</template>

<script setup>
import { ref, nextTick } from 'vue'

const props = defineProps({ loading: Boolean })
const emit = defineEmits(['send'])

const inputText = ref('')
const textareaRef = ref(null)

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
  emit('send', text)
  inputText.value = ''
  nextTick(() => {
    if (textareaRef.value) textareaRef.value.style.height = 'auto'
  })
}
</script>

<style scoped>
.chat-input-wrapper {
  width: 100%;
}

.input-container {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  background: white;
  border: 1px solid #e7e5e4;
  border-radius: 16px;
  padding: 12px 16px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05), 0 4px 12px rgba(0,0,0,0.04);
}

.input-field {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  resize: none;
  font-size: 14px;
  line-height: 1.5;
  color: #44403c;
  min-height: 24px;
  max-height: 120px;
  font-family: inherit;
}

.input-field::placeholder {
  color: #a8a29e;
}

.send-btn {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: #4f46e5;
  color: white;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
  flex-shrink: 0;
}

.send-btn:hover:not(:disabled) {
  background: #4338ca;
}

.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.send-icon {
  width: 20px;
  height: 20px;
}

.input-hint {
  text-align: center;
  font-size: 12px;
  color: #a8a29e;
  margin-top: 8px;
  margin-bottom: 0;
}
</style>
