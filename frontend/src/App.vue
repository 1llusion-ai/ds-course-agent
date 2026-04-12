<template>
  <router-view class="app-container" />
</template>

<style>
@import './styles/main.scss';

html, body, #app {
  height: 100%;
  margin: 0;
  overflow: hidden;
}

.app-container {
  width: 100%;
  height: 100%;
  display: block;
  overflow-y: auto;
}
</style>
