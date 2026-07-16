<template>
  <div class="chat-input-wrapper">
    <div class="input-container">
      <textarea
        v-model="inputText"
        rows="1"
        class="input-field"
        placeholder="问一个课程概念、公式推导或代码问题..."
        @keydown.enter="handleEnterKey"
        @input="autoResize"
        ref="textareaRef"
      />
      <button
        class="send-btn"
        :disabled="!inputText.trim() || loading"
        @click="handleSend"
      >
        <svg v-if="!loading" class="send-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.2" d="M5 12h14M12 5l7 7-7 7"/>
        </svg>
        <span v-else class="send-loader"></span>
      </button>
    </div>
    <div class="input-hint">
      <span>Enter 发送 · Shift+Enter 换行</span>
      <span>基于教材与学习画像回答</span>
    </div>
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
  max-width: 980px;
  margin: 0 auto;
}

.input-container {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(255, 255, 255, 0.92));
  border: 1px solid rgba(148, 163, 184, 0.26);
  border-radius: 22px;
  padding: 12px 14px 12px 18px;
  box-shadow:
    0 20px 50px rgba(15, 23, 42, 0.10),
    0 1px 0 rgba(255, 255, 255, 0.88) inset;
  backdrop-filter: blur(18px);
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.input-container:focus-within {
  border-color: rgba(79, 70, 229, 0.46);
  box-shadow:
    0 24px 60px rgba(79, 70, 229, 0.13),
    0 0 0 4px rgba(79, 70, 229, 0.08);
  transform: translateY(-1px);
}

.input-field {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  resize: none;
  font-size: 15px;
  line-height: 1.65;
  color: #44403c;
  min-height: 28px;
  max-height: 150px;
  font-family: inherit;
  padding: 4px 0;
}

.input-field::placeholder {
  color: #a8a29e;
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

.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.send-icon {
  width: 20px;
  height: 20px;
}

.send-loader {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255, 255, 255, 0.42);
  border-top-color: #fff;
  border-radius: 999px;
  animation: input-spin 0.8s linear infinite;
}

.input-hint {
  display: flex;
  justify-content: center;
  gap: 14px;
  flex-wrap: wrap;
  font-size: 12px;
  color: #94a3b8;
  margin-top: 10px;
}

@keyframes input-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
