<template>
  <section class="assessment-question" :aria-labelledby="`question-${question.id}`">
    <div class="assessment-question__number">第 {{ number }} 题</div>
    <h2 :id="`question-${question.id}`">{{ question.stem }}</h2>
    <div class="assessment-options" role="radiogroup" :aria-label="`第 ${number} 题选项`">
      <button
        v-for="option in question.options"
        :key="option.id"
        type="button"
        class="assessment-option"
        :class="{ 'assessment-option--selected': modelValue === option.id }"
        role="radio"
        :aria-checked="modelValue === option.id"
        @click="$emit('update:modelValue', option.id)"
      >
        <span class="assessment-option__key">{{ option.id }}</span>
        <span>{{ option.text }}</span>
      </button>
    </div>
  </section>
</template>

<script setup>
defineProps({
  question: { type: Object, required: true },
  number: { type: Number, required: true },
  modelValue: { type: String, default: '' }
})

defineEmits(['update:modelValue'])
</script>
