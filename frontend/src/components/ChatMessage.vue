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
      <div class="message-content">{{ message.content }}</div>

      <div v-if="message.sources?.length" class="message-source">
        <span>📚</span><span>来源：{{ message.sources[0].reference }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({ message: { type: Object, required: true }})
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