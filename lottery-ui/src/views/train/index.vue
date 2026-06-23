<template>
  <div class="train-container">
    <el-card>
      <template #header>⚙️ 训练配置</template>
      <el-form label-width="120px" label-position="top" class="train-form">
        <el-form-item label="彩种">
          <el-radio-group v-model="lotteryType">
            <el-radio label="ssq">双色球</el-radio>
            <el-radio label="dlt">大乐透</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="训练轮数">
          <el-input-number v-model="epochs" :min="1" :max="200" style="width: 100%" />
        </el-form-item>
        <el-form-item label="批次大小">
          <el-input-number v-model="batchSize" :min="1" :max="128" style="width: 100%" />
        </el-form-item>
        <el-form-item label="序列长度">
          <el-input-number v-model="seqLen" :min="10" :max="100" style="width: 100%" />
        </el-form-item>
        <el-form-item label="学习率">
          <el-input-number v-model="learningRate" :step="0.0001" :precision="4" style="width: 100%" />
        </el-form-item>
        <el-form-item>
          <div class="btn-group">
            <el-button type="primary" @click="handleStart" :loading="trainStore.loading">开始训练</el-button>
            <el-button @click="handleCheckStatus" :disabled="!trainStore.taskId">查询状态</el-button>
            <el-button @click="handleReset">重置</el-button>
          </div>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card v-if="trainStore.taskId" style="margin-top:20px">
      <template #header>📊 训练状态</template>
      <div class="status-content">
        <p><strong>任务 ID：</strong>{{ trainStore.taskId }}</p>
        <p><strong>状态：</strong>
          <el-tag :type="statusTagType">{{ statusText }}</el-tag>
        </p>
        <pre v-if="trainStore.status?.result" class="result-pre">{{ JSON.stringify(trainStore.status.result, null, 2) }}</pre>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onUnmounted } from 'vue'
import { useTrainStore } from '@/store'
import { ElMessage } from 'element-plus'

const trainStore = useTrainStore()

const lotteryType = ref('ssq')
const epochs = ref(50)
const batchSize = ref(32)
const seqLen = ref(30)
const learningRate = ref(0.0001)

const statusText = computed(() => {
  const s = trainStore.status?.status
  const map = { pending: '等待中', running: '训练中...', completed: '已完成 ✅', failed: '失败 ❌' }
  return map[s] || '未知'
})
const statusTagType = computed(() => {
  const s = trainStore.status?.status
  const map = { completed: 'success', failed: 'danger', running: 'warning' }
  return map[s] || 'info'
})

let pollTimer = null

const pollStatus = async () => {
  if (!trainStore.taskId) return
  try {
    const res = await trainStore.fetchStatus(trainStore.taskId)
    if (res.status === 'completed' || res.status === 'failed') {
      ElMessage.info(`训练${res.status === 'completed' ? '完成' : '失败'}`)
      return
    }
    pollTimer = setTimeout(pollStatus, 5000)
  } catch {
    pollTimer = setTimeout(pollStatus, 5000)
  }
}

const handleStart = async () => {
  try {
    const params = {
      lottery_type: lotteryType.value,
      epochs: epochs.value,
      batch_size: batchSize.value,
      seq_len: seqLen.value,
      learning_rate: learningRate.value
    }
    await trainStore.start(params)
    ElMessage.success(`任务已提交，ID: ${trainStore.taskId}`)
    pollStatus()
  } catch (e) {
    ElMessage.error('提交失败：' + e.message)
  }
}

const handleCheckStatus = async () => {
  if (!trainStore.taskId) return
  await trainStore.fetchStatus(trainStore.taskId)
  ElMessage.info(`当前状态: ${trainStore.status?.status}`)
}

const handleReset = () => {
  trainStore.reset()
  if (pollTimer) clearTimeout(pollTimer)
  lotteryType.value = 'ssq'
  epochs.value = 50
  batchSize.value = 32
  seqLen.value = 30
  learningRate.value = 0.0001
}

onUnmounted(() => {
  if (pollTimer) clearTimeout(pollTimer)
})
</script>

<style scoped>
.train-container {
  padding: 0;
}
.train-form .el-form-item {
  margin-bottom: 18px;
}
/* 按钮组在小屏换行并均匀分布 */
.btn-group {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.btn-group .el-button {
  flex: 1 0 auto;
  min-width: 80px;
}
.status-content {
  font-size: 14px;
  line-height: 1.8;
}
.result-pre {
  background: #f5f7fa;
  padding: 10px;
  border-radius: 4px;
  overflow-x: auto;
  font-size: 13px;
}

/* 移动端调整标签位置（label在上） */
@media (max-width: 768px) {
  .train-form .el-form-item {
    margin-bottom: 14px;
  }
  .train-form .el-form-item__label {
    padding-bottom: 4px;
  }
}
</style>