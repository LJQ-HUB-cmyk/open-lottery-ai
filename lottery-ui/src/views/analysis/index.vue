<template>
  <div class="analysis-page">
    <!-- 开奖规则卡片 -->
    <el-card class="rule-card" shadow="hover">
      <el-row :gutter="20" align="middle">
        <el-col :span="12">
          <div class="rule-item">
            <el-tag type="danger" size="large" effect="dark">双色球</el-tag>
            <span class="rule-text">每周二、四、日开奖</span>
            <el-tag size="small" type="info" round>每周3期</el-tag>
          </div>
        </el-col>
        <el-col :span="12">
          <div class="rule-item">
            <el-tag type="warning" size="large" effect="dark">大乐透</el-tag>
            <span class="rule-text">每周一、三、六开奖</span>
            <el-tag size="small" type="info" round>每周3期</el-tag>
          </div>
        </el-col>
      </el-row>
      <div v-if="upcoming" class="upcoming-info">
        <span class="upcoming-icon">🔶</span>
        <span class="upcoming-text">
          下一期 <strong>{{ lotteryInfo?.name || '彩票' }}</strong>：
          <span class="draw-date">{{ upcoming.next_draw_date }}</span>
          （{{ upcoming.next_draw_weekday }}）
        </span>
        <el-tag v-if="upcoming.is_today" type="success" size="default" effect="dark" round>
          📅 今天开奖！
        </el-tag>
        <el-tag v-else type="info" size="default" round>
          还有 {{ upcoming.days_until }} 天
        </el-tag>
      </div>
    </el-card>

    <!-- 彩种切换 + 工具栏 -->
    <el-card class="toolbar-card" shadow="hover">
      <div class="toolbar">
        <div class="toolbar-left">
          <el-radio-group v-model="lotteryType" @change="fetchData" size="large">
            <el-radio-button label="ssq">
              <span class="lottery-label">🟥 双色球</span>
            </el-radio-button>
            <el-radio-button label="dlt">
              <span class="lottery-label">🟧 大乐透</span>
            </el-radio-button>
          </el-radio-group>
        </div>
        <div class="toolbar-right">
          <el-button size="default" @click="fetchData" :loading="loading" type="primary" plain>
            <el-icon><Refresh /></el-icon> 刷新
          </el-button>
          <span class="total-badge">
            <el-badge :value="total" :hidden="total === 0" type="primary">
              <span class="total-text">今日预测</span>
            </el-badge>
          </span>
        </div>
      </div>
    </el-card>

    <!-- 加载中 -->
    <div v-if="loading" class="loading-container">
      <el-icon class="is-loading"><Loading /></el-icon>
      <span>加载中...</span>
    </div>

    <div v-else>
      <!-- 最优推荐 -->
      <div v-if="recommendation" class="recommendation-box">
        <div class="recommendation-header">
          <span class="recommendation-icon">⭐</span>
          <span class="recommendation-title">最优推荐</span>
          <el-tag type="success" size="small" round class="confidence-tag">
            置信度 {{ (recommendation.confidence * 100).toFixed(1) }}%
          </el-tag>
        </div>
        <div class="recommend-numbers">
          <div class="number-row">
            <span class="label">红球</span>
            <div class="number-group">
              <span
                v-for="r in recommendation.red"
                :key="r"
                class="ball ball-red"
              >
                {{ String(r).padStart(2, '0') }}
              </span>
            </div>
          </div>
          <div class="number-row">
            <span class="label">蓝球</span>
            <div class="number-group">
              <span
                v-if="Array.isArray(recommendation.blue)"
                v-for="b in recommendation.blue"
                :key="b"
                class="ball ball-blue"
              >
                {{ String(b).padStart(2, '0') }}
              </span>
              <span v-else class="ball ball-blue">
                {{ String(recommendation.blue).padStart(2, '0') }}
              </span>
            </div>
          </div>
        </div>
        <!-- 置信度进度条 -->
        <div class="confidence-bar">
          <span class="confidence-label">综合置信度</span>
          <el-progress
            :percentage="Math.round((recommendation.confidence || 0) * 100)"
            :color="confidenceColor"
            :stroke-width="10"
            :format="() => (recommendation.confidence * 100).toFixed(1) + '%'"
            style="flex:1;"
          />
        </div>
      </div>

      <!-- 今日开奖结果对比 -->
      <div v-if="result" class="result-box">
        <div class="result-header">
          <span class="result-icon">🎯</span>
          <span class="result-title">今日开奖结果</span>
          <el-tag type="warning" size="small" round>期号 {{ result.issue_num }}</el-tag>
        </div>
        <div class="result-numbers">
          <div class="number-row">
            <span class="label">红球</span>
            <div class="number-group">
              <span
                v-for="r in result.red"
                :key="r"
                class="ball ball-red"
                :class="{ 'ball-matched': recommendation?.red?.includes(r) }"
              >
                {{ String(r).padStart(2, '0') }}
                <span v-if="recommendation?.red?.includes(r)" class="match-mark">✓</span>
              </span>
            </div>
          </div>
          <div class="number-row">
            <span class="label">蓝球</span>
            <div class="number-group">
              <template v-if="Array.isArray(result.blue)">
                <span
                  v-for="b in result.blue"
                  :key="b"
                  class="ball ball-blue"
                  :class="{ 'ball-matched': recommendation?.blue?.includes?.(b) }"
                >
                  {{ String(b).padStart(2, '0') }}
                  <span v-if="recommendation?.blue?.includes?.(b)" class="match-mark">✓</span>
                </span>
              </template>
              <span
                v-else
                class="ball ball-blue"
                :class="{ 'ball-matched': recommendation?.blue === result.blue }"
              >
                {{ String(result.blue).padStart(2, '0') }}
                <span v-if="recommendation?.blue === result.blue" class="match-mark">✓</span>
              </span>
            </div>
          </div>
        </div>
        <div v-if="recommendation" class="match-summary">
          <div class="match-item">
            <span class="match-label">红球命中</span>
            <span class="match-count match-red">{{ matchCount.red }}</span>
            <span class="match-total">/ 6</span>
          </div>
          <div class="match-divider"></div>
          <div class="match-item">
            <span class="match-label">蓝球命中</span>
            <span class="match-count match-blue">{{ matchCount.blue }}</span>
            <span class="match-total">/ 1</span>
          </div>
          <div class="match-divider"></div>
          <div class="match-item">
            <span class="match-label">总命中率</span>
            <span class="match-count match-total-rate">{{ matchRate }}%</span>
          </div>
        </div>
      </div>

      <div v-if="!recommendation && !result && forecasts.length === 0" class="empty-state">
        <el-empty description="今日暂无预测数据，请先生成预测" />
      </div>

      <!-- 预测记录列表 -->
      <el-card v-if="forecasts.length > 0" class="list-card" shadow="hover">
        <template #header>
          <div class="list-header">
            <span class="list-title">📋 今日预测记录</span>
            <el-tag type="info" size="small" round>共 {{ forecasts.length }} 条</el-tag>
          </div>
        </template>
        <el-table :data="forecasts" border stripe style="width:100%;" size="default">
          <el-table-column label="红球" min-width="280">
            <template #default="{ row }">
              <span
                v-for="r in row.red"
                :key="r"
                class="ball ball-red ball-small"
              >
                {{ String(r).padStart(2, '0') }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="蓝球" width="140">
            <template #default="{ row }">
              <template v-if="Array.isArray(row.blue)">
                <span
                  v-for="b in row.blue"
                  :key="b"
                  class="ball ball-blue ball-small"
                >
                  {{ String(b).padStart(2, '0') }}
                </span>
              </template>
              <span v-else class="ball ball-blue ball-small">
                {{ String(row.blue).padStart(2, '0') }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="quality_score" label="质量评分" width="160">
            <template #default="{ row }">
              <el-progress
                :percentage="Math.round((row.quality_score || 0) * 100)"
                :color="getScoreColor(row.quality_score || 0)"
                :stroke-width="8"
                style="width:120px;display:inline-block;"
              />
            </template>
          </el-table-column>
          <el-table-column prop="create_time" label="预测时间" width="180" />
          <el-table-column prop="model_version" label="模型版本" width="140" />
        </el-table>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getTodayAnalysis } from '@/api/analysis'
import { Refresh, Loading } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

const loading = ref(false)
const lotteryType = ref('ssq')
const forecasts = ref([])
const recommendation = ref(null)
const result = ref(null)
const total = ref(0)
const upcoming = ref(null)
const lotteryInfo = ref(null)

// 匹配数量
const matchCount = computed(() => {
  if (!recommendation.value || !result.value) return { red: 0, blue: 0 }

  const recRed = recommendation.value.red || []
  const resRed = result.value.red || []
  const redMatch = recRed.filter(r => resRed.includes(r)).length

  let blueMatch = 0
  const recBlue = recommendation.value.blue
  const resBlue = result.value.blue

  if (Array.isArray(recBlue) && Array.isArray(resBlue)) {
    blueMatch = recBlue.filter(b => resBlue.includes(b)).length
  } else if (!Array.isArray(recBlue) && !Array.isArray(resBlue)) {
    blueMatch = recBlue === resBlue ? 1 : 0
  } else {
    if (Array.isArray(recBlue) && !Array.isArray(resBlue)) {
      blueMatch = recBlue.includes(resBlue) ? 1 : 0
    } else if (!Array.isArray(recBlue) && Array.isArray(resBlue)) {
      blueMatch = resBlue.includes(recBlue) ? 1 : 0
    }
  }

  return { red: redMatch, blue: blueMatch }
})

// 命中率
const matchRate = computed(() => {
  const total = 7
  const matched = matchCount.value.red + matchCount.value.blue
  return Math.round((matched / total) * 100)
})

// 置信度颜色
const confidenceColor = computed(() => {
  const pct = (recommendation.value?.confidence || 0) * 100
  if (pct >= 70) return '#67C23A'
  if (pct >= 50) return '#E6A23C'
  return '#909399'
})

// 获取评分颜色
const getScoreColor = (score) => {
  const pct = score * 100
  if (pct >= 70) return '#67C23A'
  if (pct >= 50) return '#E6A23C'
  return '#909399'
}

// 获取数据
const fetchData = async () => {
  loading.value = true
  try {
    const res = await getTodayAnalysis(lotteryType.value)
    forecasts.value = res.forecasts || []
    recommendation.value = res.recommendation
    result.value = res.result
    total.value = res.total || 0
    upcoming.value = res.upcoming
    lotteryInfo.value = res.lottery_info

    if (res.message) {
      ElMessage.info(res.message)
    }
  } catch (e) {
    console.error('加载分析数据失败:', e)
    ElMessage.error('加载数据失败：' + (e.message || '未知错误'))
  } finally {
    loading.value = false
  }
}

onMounted(fetchData)
</script>

<style scoped>
.analysis-page {
  padding: 16px;
  max-width: 1400px;
  margin: 0 auto;
}

/* ===== 开奖规则卡片 ===== */
.rule-card {
  margin-bottom: 16px;
  border-radius: 12px;
}
.rule-card :deep(.el-card__body) {
  padding: 16px 20px;
}
.rule-item {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.rule-text {
  color: #606266;
  font-size: 14px;
}

.upcoming-info {
  margin-top: 12px;
  padding: 10px 16px;
  background: #f0f9ff;
  border-radius: 8px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}
.upcoming-icon {
  font-size: 18px;
}
.upcoming-text {
  font-size: 15px;
  color: #303133;
}
.draw-date {
  color: #409EFF;
  font-weight: bold;
  font-size: 16px;
}

/* ===== 工具栏卡片 ===== */
.toolbar-card {
  margin-bottom: 16px;
  border-radius: 12px;
}
.toolbar-card :deep(.el-card__body) {
  padding: 12px 20px;
}
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}
.toolbar-left {
  display: flex;
  align-items: center;
}
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 16px;
}
.lottery-label {
  font-weight: 500;
}
.total-badge {
  display: flex;
  align-items: center;
}
.total-text {
  color: #909399;
  font-size: 14px;
  margin-right: 4px;
}

/* ===== 加载状态 ===== */
.loading-container {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 60px 0;
  font-size: 18px;
  color: #409EFF;
  gap: 12px;
}

/* ===== 最优推荐 ===== */
.recommendation-box {
  background: linear-gradient(135deg, #f0f9ff 0%, #d9ecff 100%);
  padding: 20px 24px 24px;
  border-radius: 12px;
  margin-bottom: 16px;
  border: 1px solid #b3d8ff;
}
.recommendation-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}
.recommendation-icon {
  font-size: 20px;
}
.recommendation-title {
  font-size: 18px;
  font-weight: bold;
  color: #303133;
}
.confidence-tag {
  margin-left: auto;
}

/* ===== 号码球 ===== */
.ball {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  font-size: 16px;
  font-weight: bold;
  color: #fff;
  margin: 0 4px;
  position: relative;
  transition: all 0.2s;
}
.ball-red {
  background: linear-gradient(145deg, #f56c6c, #c0392b);
  box-shadow: 0 2px 8px rgba(245, 108, 108, 0.4);
}
.ball-blue {
  background: linear-gradient(145deg, #409EFF, #2171c7);
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.4);
}
.ball-matched {
  box-shadow: 0 0 0 3px #67C23A, 0 2px 12px rgba(103, 194, 58, 0.5);
  transform: scale(1.05);
}
.ball-small {
  width: 32px;
  height: 32px;
  font-size: 13px;
  margin: 0 2px;
}
.match-mark {
  position: absolute;
  top: -6px;
  right: -6px;
  font-size: 12px;
  color: #67C23A;
  background: #fff;
  border-radius: 50%;
  width: 16px;
  height: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 1px 4px rgba(0,0,0,0.15);
}

.number-row {
  display: flex;
  align-items: center;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.number-row:last-child {
  margin-bottom: 0;
}
.label {
  font-weight: bold;
  color: #606266;
  width: 50px;
  flex-shrink: 0;
  font-size: 14px;
}
.number-group {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
}

/* ===== 置信度进度条 ===== */
.confidence-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px dashed rgba(0,0,0,0.08);
}
.confidence-label {
  font-size: 14px;
  color: #606266;
  white-space: nowrap;
}
.confidence-bar .el-progress {
  flex: 1;
}

/* ===== 开奖结果 ===== */
.result-box {
  background: linear-gradient(135deg, #fdf6ec 0%, #fde8d0 100%);
  padding: 20px 24px 24px;
  border-radius: 12px;
  margin-bottom: 16px;
  border: 1px solid #f5dab1;
}
.result-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}
.result-icon {
  font-size: 20px;
}
.result-title {
  font-size: 18px;
  font-weight: bold;
  color: #303133;
}
.result-numbers .number-row {
  margin-bottom: 8px;
}

.match-summary {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 20px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px dashed rgba(0,0,0,0.1);
}
.match-item {
  display: flex;
  align-items: center;
  gap: 6px;
}
.match-label {
  font-size: 14px;
  color: #606266;
}
.match-count {
  font-size: 22px;
  font-weight: bold;
}
.match-red {
  color: #f56c6c;
}
.match-blue {
  color: #409EFF;
}
.match-total-rate {
  color: #67C23A;
  font-size: 24px;
}
.match-total {
  color: #909399;
  font-size: 14px;
}
.match-divider {
  width: 1px;
  height: 28px;
  background: #dcdfe6;
}

/* ===== 空状态 ===== */
.empty-state {
  padding: 40px 0;
  background: #fff;
  border-radius: 12px;
}

/* ===== 预测列表 ===== */
.list-card {
  border-radius: 12px;
}
.list-card :deep(.el-card__header) {
  padding: 14px 20px;
  border-bottom: 1px solid #ebeef5;
}
.list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.list-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}
.list-card :deep(.el-table) {
  border-radius: 8px;
  overflow: hidden;
}
.list-card :deep(.el-table th) {
  background: #f5f7fa;
}

/* ===== 响应式 ===== */
@media (max-width: 768px) {
  .analysis-page {
    padding: 8px;
  }
  .toolbar {
    flex-direction: column;
    align-items: stretch;
    gap: 10px;
  }
  .toolbar-left {
    justify-content: center;
  }
  .toolbar-right {
    justify-content: center;
  }
  .recommendation-box,
  .result-box {
    padding: 16px;
  }
  .number-row {
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
  }
  .label {
    width: auto;
  }
  .match-summary {
    flex-wrap: wrap;
    gap: 10px;
  }
  .match-divider {
    display: none;
  }
  .ball {
    width: 34px;
    height: 34px;
    font-size: 14px;
  }
  .ball-small {
    width: 28px;
    height: 28px;
    font-size: 12px;
  }
  .upcoming-info {
    flex-direction: column;
    align-items: flex-start;
  }
  .rule-item {
    flex-wrap: wrap;
  }
}
</style>