<script setup>
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <div class="ep-page not-found">
    <el-result icon="warning" title="页面不存在" sub-title="链接可能已失效。">
      <template #extra>
        <el-button type="primary" @click="router.push('/')">回到首页</el-button>
      </template>
    </el-result>
  </div>
</template>

<style scoped>
.not-found {
  display: grid;
  place-items: center;
  min-height: 60vh;
}
</style>
