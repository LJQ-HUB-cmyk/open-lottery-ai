<template>
  <div class="predict-container">
    <el-card>
      <template #header>🔮 生成预测</template>
      <el-form label-width="120px" label-position="top" class="predict-form">
        <el-form-item label="彩种">
          <el-radio-group v-model="lotteryType" @change="loadModels">
            <el-radio label="ssq">双色球</el-radio>
            <el-radio label="dlt">大乐透</el-radio>
          </el-radio-group>
        </el-form-item>
        <!-- 新增：模型选择 -->
        <el-form-item label="选择模型">
          <el-select
            v-model="selectedModel"
            placeholder="请先选择彩种，然后选择模型"
            style="width:100%;"
            filterable
            :disabled="!lotteryType || modelOptions.length === 0"
          >
            <el-option
              v-for="item in modelOptions"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
          <div style="color:#909399;font-size:12px;margin-top:4px;">
            提示：选择您想使用的模型文件，必须选择一个
          </div>
        </el-form-item>
        <el-form-item>
          <div class="btn-group">
            <el-button type="primary" @click="handlePredict" :loading="predictStore.loading" :disabled="!selectedModel">
              预测
            </el-button>
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
        <p><strong>使用模型：</strong><el-tag size="small" type="info">{{ predictStore.result.model_name || selectedModel || '未知' }}</el-tag></p>
      </div>
    </el-card>

    <el-alert v-if="predictStore.error" type="error" :title="predictStore.error" show-icon closable @close="predictStore.clear()" style="margin-top:20px" />
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { usePredictStore } from '@/store'
import { listModels } from '@/api/model'
import { ElMessage } from 'element-plus'

const predictStore = usePredictStore()
const lotteryType = ref('ssq')
const selectedModel = ref('')
const modelOptions = ref([])

// 加载模型列表（根据彩种过滤）
const loadModels = async () => {
  try {
    const res = await listModels()
    const allModels = res.models || []
    // 根据彩种过滤：只显示对应的 .pt 文件（ssq_*.pt 或 dlt_*.pt）
    const prefix = lotteryType.value
    const filtered = allModels
      .filter(name => name.endsWith('.pt') && name.startsWith(prefix))
      .map(name => ({
        value: name,
        label: name.replace('.pt', '').replace(/_/g, ' ').replace(/ssq|dlt/g, '') // 美化显示
      }))
    modelOptions.value = filtered
    // 如果当前选中的模型不在列表中，清空
    if (!filtered.some(item => item.value === selectedModel.value)) {
      selectedModel.value = ''
    }
    if (filtered.length === 0) {
      ElMessage.warning(`当前彩种 ${lotteryType.value === 'ssq' ? '双色球' : '大乐透'} 暂无可用模型，请先训练`)
    }
  } catch (e) {
    console.error('加载模型列表失败:', e)
  }
}

// 切换彩种时重新加载模型
watch(lotteryType, () => {
  loadModels()
})

// 执行预测
const handlePredict = async () => {
  if (!selectedModel.value) {
    ElMessage.warning('请先选择一个模型')
    return
  }
  try {
    await predictStore.predict({
      lottery_type: lotteryType.value,
      model_name: selectedModel.value
    })
    ElMessage.success('预测成功')
  } catch (e) {
    // 错误已在 store 中处理
  }
}

const handleClear = () => {
  predictStore.clear()
}

// 页面加载时自动加载模型列表
onMounted(() => {
  loadModels()
})
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