<template>
  <div class="page-container">
    <div class="placeholder-card">
      <div class="icon-glow">📊</div>
      <h2>工作台</h2>
      <p class="desc">您当前项目的测试设计与执行总览，正在进行模块对接。</p>
      <div class="badge">TestWeave Core</div>
    </div>
  </div>
</template>

<script setup lang="ts">
// Workbench Page Container
</script>

<style scoped>
.page-container {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 400px;
  width: 100%;
}

.placeholder-card {
  background: rgba(30, 41, 59, 0.4);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 16px;
  padding: 40px;
  text-align: center;
  max-width: 480px;
  width: 100%;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
}

.icon-glow {
  font-size: 48px;
  margin-bottom: 20px;
  filter: drop-shadow(0 0 10px rgba(99, 102, 241, 0.5));
}

h2 {
  color: #f1f5f9;
  font-size: 24px;
  margin-bottom: 12px;
  font-weight: 600;
}

.desc {
  color: #94a3b8;
  font-size: 14px;
  line-height: 1.6;
  margin-bottom: 24px;
}

.badge {
  display: inline-block;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.2), rgba(139, 92, 246, 0.2));
  border: 1px solid rgba(99, 102, 241, 0.3);
  color: #a5b4fc;
  padding: 6px 16px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.5px;
}
</style>
