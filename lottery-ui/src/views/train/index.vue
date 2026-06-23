<template>
  <div class="train-container">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>⚙️ 训练配置</span>
          <el-button type="text" @click="showHelp = !showHelp" style="font-size:14px;">
            {{ showHelp ? '收起参数说明 ▲' : '展开参数说明 ▼' }}
          </el-button>
        </div>
      </template>

      <!-- 参数说明表格 -->
      <el-collapse-transition>
        <div v-show="showHelp" class="help-table">
          <el-table :data="helpData" border size="small" style="width:100%;">
            <el-table-column prop="param" label="参数" width="120" />
            <el-table-column prop="desc" label="说明" />
            <el-table-column prop="range" label="取值范围" width="160" />
            <el-table-column prop="recommend" label="推荐值" width="140" />
          </el-table>
        </div>
      </el-collapse-transition>

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
          <el-input-number v-model="seqLen" :min="10" :max="3000" style="width: 100%" />
        </el-form-item>
        <el-form-item label="学习率">
          <el-input-number v-model="learningRate" :step="0.0001" :precision="4" style="width: 100%" />
        </el-form-item>
        <el-form-item label="训练前更新数据">
          <el-switch v-model="withFetch" active-text="开启" inactive-text="关闭" />
          <span style="margin-left:10px;color:#909399;font-size:12px;">开启后将先抓取最新开奖数据</span>
        </el-form-item>
        <el-form-item>
          <div class="btn-group">
            <el-button type="primary" @click="handleStart" :loading="trainStore.loading">
              {{ withFetch ? '一键完整训练' : '开始训练' }}
            </el-button>
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
        <p v-if="trainStore.status?.meta?.stage">
          <strong>当前阶段：</strong>
          <el-tag size="small" :type="stageTagType">{{ stageText }}</el-tag>
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
const epochs = ref(200)
const batchSize = ref(128)
const seqLen = ref(10)
const learningRate = ref(0.0001)
const withFetch = ref(true)
const showHelp = ref(false)

// 参数说明数据
const helpData = [
  {
    param: '彩种',
    desc: '选择要训练的彩票类型',
    range: '双色球 / 大乐透',
    recommend: '按需选择'
  },
  {
    param: '训练轮数',
    desc: '训练迭代轮数，越大模型越收敛',
    range: '1 - 200',
    recommend: '50 - 100'
  },
  {
    param: '批次大小',
    desc: '每次迭代使用的样本数',
    range: '1 - 128',
    recommend: '32 - 64'
  },
  {
    param: '序列长度',
    desc: '使用多少期历史数据预测下一期',
    range: '10 - 3000',
    recommend: '30 - 50'
  },
  {
    param: '学习率',
    desc: '模型参数更新步长，太大震荡，太小收敛慢',
    range: '0.0001 - 0.01',
    recommend: '0.0001'
  },
  {
    param: '更新数据',
    desc: '训练前是否先抓取最新开奖数据',
    range: '开启 / 关闭',
    recommend: '开启'
  }
]

// 状态文本
const statusText = computed(() => {
  const s = trainStore.status?.status
  const map = {
    pending: '等待中',
    running: '训练中...',
    completed: '已完成 ✅',
    failed: '失败 ❌',
    fetching: '数据更新中...'
  }
  return map[s] || '未知'
})

const statusTagType = computed(() => {
  const s = trainStore.status?.status
  const map = {
    completed: 'success',
    failed: 'danger',
    running: 'warning',
    fetching: 'warning'
  }
  return map[s] || 'info'
})

// 阶段信息
const stageText = computed(() => {
  const stage = trainStore.status?.meta?.stage
  const map = { fetch: '抓取数据', train: '训练模型', done: '已完成' }
  return map[stage] || '未知'
})

const stageTagType = computed(() => {
  const stage = trainStore.status?.meta?.stage
  const map = { fetch: 'warning', train: 'primary', done: 'success' }
  return map[stage] || 'info'
})

let pollTimer = null

const pollStatus = async () => {
  if (!trainStore.taskId) return
  try {
    const res = await trainStore.fetchStatus(trainStore.taskId)
    const status = res.status
    if (status === 'completed' || status === 'failed' || status === 'SUCCESS' || status === 'FAILURE') {
      ElMessage.info(`训练${status === 'completed' || status === 'SUCCESS' ? '完成' : '失败'}`)
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
      learning_rate: learningRate.value,
      with_fetch: withFetch.value
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
  withFetch.value = true
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

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.help-table {
  margin-bottom: 20px;
  padding: 12px 0;
  border-top: 1px solid #ebeef5;
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
  .help-table {
    font-size: 12px;
  }
}
</style>