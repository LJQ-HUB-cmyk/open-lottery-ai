<template>
  <div class="predict-container">
    <el-card>
      <template #header>🔮 生成预测</template>
      <el-form label-width="120px" label-position="top" class="predict-form">
        <el-form-item label="彩种">
          <el-radio-group v-model="lotteryType">
            <el-radio label="ssq">双色球</el-radio>
            <el-radio label="dlt">大乐透</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item>
          <div class="btn-group">
            <el-button type="primary" @click="handlePredict" :loading="predictStore.loading">预测</el-button>
            <el-button @click="handleClear">清空结果</el-button>
          </div>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card v-if="predictStore.result" style="margin-top:20px">
      <template #header>📋 预测结果</template>
      <div class="result-content">
        <p><strong>彩种：</strong>{{ predictStore.result.lottery_type === 'ssq' ? '双色球' : '大乐透' }}</p>
        <p><strong>预测日期：</strong>{{ predictStore.result.forecast_date }}</p>
        <p class="ball-row">
          <strong>红球（前区）：</strong>
          <el-tag v-for="r in predictStore.result.red" :key="r" size="default" class="result-tag">{{ r }}</el-tag>
        </p>
        <p class="ball-row">
          <strong>蓝球（后区）：</strong>
          <el-tag v-for="b in predictStore.result.blue" :key="b" size="default" type="danger" class="result-tag">{{ b }}</el-tag>
        </p>
        <p><strong>质量评分：</strong>{{ predictStore.result.quality_score }}</p>
        <p><strong>模型版本：</strong>{{ predictStore.result.model_version }}</p>
      </div>
    </el-card>

    <el-alert v-if="predictStore.error" type="error" :title="predictStore.error" show-icon closable @close="predictStore.clear()" style="margin-top:20px" />
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { usePredictStore } from '@/store'
import { ElMessage } from 'element-plus'

const predictStore = usePredictStore()
const lotteryType = ref('ssq')

const handlePredict = async () => {
  try {
    await predictStore.predict({ lottery_type: lotteryType.value })
    ElMessage.success('预测成功')
  } catch (e) {
    ElMessage.error('预测失败：' + e.message)
  }
}

const handleClear = () => {
  predictStore.clear()
}
</script>

<style scoped>
.predict-container {
  padding: 0;
}
.predict-form .el-form-item {
  margin-bottom: 18px;
}
.btn-group {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.btn-group .el-button {
  flex: 1 0 auto;
  min-width: 80px;
}
.result-content {
  font-size: 14px;
  line-height: 1.8;
}
.ball-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.result-tag {
  margin: 2px 0;
}

@media (max-width: 768px) {
  .predict-form .el-form-item {
    margin-bottom: 14px;
  }
  .result-content {
    font-size: 13px;
  }
  .result-tag {
    font-size: 13px;
    padding: 0 10px;
    height: 28px;
  }
}
</style>