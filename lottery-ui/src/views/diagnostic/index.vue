<template>
  <div class="diagnostic-page">
    <!-- ===== 说明卡片 ===== -->
    <el-card class="intro-card" shadow="never">
      <div class="intro">
        <span class="intro-icon">🔬</span>
        <div class="intro-text">
          <div class="intro-title">双向验证诊断 · 诚实评估</div>
          <div class="intro-desc">
            以随机基线（超几何分布）作为零假设，仅在严格样本外区间上给模型打分。
            只有「正向」与「反向」模型都显著好于随机，才判定存在可外推信号；
            否则诚实地告诉你：当前模型并未跑赢随机。
          </div>
        </div>
      </div>
    </el-card>

    <!-- ===== 工具栏 ===== -->
    <el-card class="toolbar-card" shadow="hover">
      <div class="toolbar">
        <div class="toolbar-left">
          <el-radio-group v-model="lotteryType" @change="runDiagnostic" size="default">
            <el-radio-button value="ssq">🟥 双色球</el-radio-button>
            <el-radio-button value="dlt">🟧 大乐透</el-radio-button>
          </el-radio-group>
          <el-select
            v-model="nPeriods"
            size="default"
            class="period-select"
            @change="runDiagnostic"
          >
            <el-option :value="30" label="回测 30 期" />
            <el-option :value="50" label="回测 50 期" />
            <el-option :value="100" label="回测 100 期" />
            <el-option :value="200" label="回测 200 期" />
          </el-select>
        </div>
        <div class="toolbar-right">
          <el-button type="primary" plain :loading="loading" @click="runDiagnostic">
            <el-icon><Refresh /></el-icon> 重新诊断
          </el-button>
        </div>
      </div>
    </el-card>

    <!-- ===== 加载状态 ===== -->
    <div v-if="loading" class="loading-container">
      <el-icon class="is-loading"><Loading /></el-icon>
      <span>正在执行双向回测与一致性诊断，请稍候…</span>
    </div>

    <!-- ===== 报告主体 ===== -->
    <template v-else-if="report">
      <!-- ---- 结论卡片 ---- -->
      <el-card class="conclusion-card" :class="'conclusion-' + conclusion.type" shadow="hover">
        <div class="conclusion-head">
          <span class="conclusion-icon">{{ conclusion.icon }}</span>
          <div class="conclusion-main">
            <div class="conclusion-label">
              {{ conclusion.text }}
              <el-tag :type="conclusion.type" effect="dark" size="small" round>
                {{ report.conclusion.status }}
              </el-tag>
            </div>
            <div class="conclusion-message">{{ report.conclusion.message }}</div>
            <div v-if="report.conclusion.interpretation" class="conclusion-interpretation">
              {{ report.conclusion.interpretation }}
            </div>
          </div>
        </div>
        <div class="conclusion-meta">
          <span>期号 {{ report.latest_issue }}</span>
          <el-divider direction="vertical" />
          <span>回测 {{ report.n_periods }} 期</span>
          <el-divider direction="vertical" />
          <span>正向模型 {{ forwardCount }} 个 / 反向模型 {{ backwardCount }} 个</span>
        </div>
      </el-card>

      <!-- ---- 随机基线卡片 ---- -->
      <el-card class="section-card" shadow="hover">
        <template #header>
          <div class="section-header">
            <span class="section-icon">🎲</span>
            <span class="section-title">随机基线（零假设）</span>
            <el-tag size="small" type="info" round>
              蒙特卡洛 {{ mcTrials }} 次交叉验证
            </el-tag>
          </div>
        </template>
        <el-table :data="baselineRows" border stripe size="small" style="width:100%">
          <el-table-column prop="name" label="位置" width="110" />
          <el-table-column label="期望命中 E" width="130">
            <template #default="{ row }">{{ fmt(row.E) }}</template>
          </el-table-column>
          <el-table-column label="标准差 SD" width="130">
            <template #default="{ row }">{{ fmt(row.SD) }}</template>
          </el-table-column>
          <el-table-column label="蒙特卡洛 E" width="130">
            <template #default="{ row }">
              {{ fmt(row.mcE) }}
              <span class="diff-badge" :class="row.diffE < 0.01 ? 'diff-ok' : 'diff-bad'">
                Δ{{ fmt(row.diffE) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="95% 显著阈值" min-width="150">
            <template #default="{ row }">
              <el-tag type="warning" size="small" effect="plain">
                ≥ {{ fmt(row.threshold) }}
              </el-tag>
              <span class="threshold-note">（每期平均命中数须高于此）</span>
            </template>
          </el-table-column>
        </el-table>
        <div class="baseline-note">
          解析值（超几何分布公式）与蒙特卡洛模拟结果一致，说明基线与判定标准可靠。
        </div>
      </el-card>

      <!-- ---- 双向一致性卡片 ---- -->
      <el-card class="section-card" shadow="hover">
        <template #header>
          <div class="section-header">
            <span class="section-icon">⚖️</span>
            <span class="section-title">双向一致性判定</span>
          </div>
        </template>
        <el-row :gutter="16">
          <el-col :xs="24" :sm="12">
            <div class="direction-box" :class="forwardSignificant ? 'box-signal' : 'box-nosignal'">
              <div class="direction-name">➡️ 正向模型 (forward)</div>
              <div class="direction-sub">输入前 N 期 → 预测下一期</div>
              <div class="direction-result">
                <el-tag :type="forwardSignificant ? 'success' : 'info'" effect="dark" size="small">
                  {{ forwardSignificant ? '存在显著模型' : '未跑赢随机' }}
                </el-tag>
                <span class="direction-count">{{ forwardCount }} 个模型</span>
              </div>
            </div>
          </el-col>
          <el-col :xs="24" :sm="12">
            <div class="direction-box" :class="backwardSignificant ? 'box-signal' : 'box-nosignal'">
              <div class="direction-name">⬅️ 反向模型 (backward)</div>
              <div class="direction-sub">输入后 N 期 → 反推上一期</div>
              <div class="direction-result">
                <el-tag :type="backwardSignificant ? 'success' : 'info'" effect="dark" size="small">
                  {{ backwardSignificant ? '存在显著模型' : '未跑赢随机' }}
                </el-tag>
                <span class="direction-count">{{ backwardCount }} 个模型</span>
              </div>
            </div>
          </el-col>
        </el-row>
        <el-alert
          class="consistency-alert"
          :type="consistencyAlert.type"
          :title="consistencyAlert.title"
          :description="consistencyAlert.desc"
          :closable="false"
          show-icon
        />
      </el-card>

      <!-- ---- 模型明细 ---- -->
      <el-card v-for="dir in ['forward', 'backward']" :key="dir" class="section-card" shadow="hover">
        <template #header>
          <div class="section-header">
            <span class="section-icon">{{ dir === 'forward' ? '➡️' : '⬅️' }}</span>
            <span class="section-title">{{ dir === 'forward' ? '正向模型明细' : '反向模型明细' }}</span>
            <el-tag size="small" type="info" round>
              严格样本外（仅统计训练截止期号之后的期次）
            </el-tag>
          </div>
        </template>
        <el-table
          v-if="directionRows(dir).length"
          :data="directionRows(dir)"
          border
          stripe
          size="small"
          style="width:100%"
        >
          <el-table-column prop="run_id" label="模型" min-width="200" show-overflow-tooltip />
          <el-table-column prop="train_end_issue" label="训练截止期号" width="120" />
          <el-table-column label="样本外平均命中" width="140">
            <template #default="{ row }">{{ fmt(row.mean_hit_per_period, 4) }}</template>
          </el-table-column>
          <el-table-column label="随机期望" width="100">
            <template #default="{ row }">{{ fmt(row.baseline_E, 4) }}</template>
          </el-table-column>
          <el-table-column label="lift" width="110">
            <template #default="{ row }">
              <span :class="row.lift_ci.lift >= 0 ? 'lift-pos' : 'lift-neg'">
                {{ row.lift_ci.lift >= 0 ? '+' : '' }}{{ fmt(row.lift_ci.lift, 4) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="95% 置信区间" min-width="160">
            <template #default="{ row }">
              [{{ fmt(row.lift_ci.ci_low, 3) }}, {{ fmt(row.lift_ci.ci_high, 3) }}]
            </template>
          </el-table-column>
          <el-table-column label="评估期数" width="100">
            <template #default="{ row }">{{ row.periods_evaluated }}</template>
          </el-table-column>
          <el-table-column label="判定" width="110">
            <template #default="{ row }">
              <el-tag :type="row.lift_ci.significant ? 'success' : 'info'" size="small">
                {{ row.lift_ci.significant ? '显著' : '不显著' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-else :description="`当前无${dir === 'forward' ? '正向' : '反向'}模型或未生成评分`" />
      </el-card>
    </template>

    <el-empty v-else description="点击「重新诊断」开始评估当前模型" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { getDiagnostic } from '@/api/predict'
import { Loading, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

const loading = ref(false)
const lotteryType = ref('ssq')
const nPeriods = ref(50)
const report = ref(null)

// 结论状态映射
const STATUS_MAP = {
  SIGNAL_DETECTED: { type: 'success', icon: '✅', text: '检测到可外推信号' },
  NO_SIGNAL: { type: 'info', icon: '🧊', text: '无可靠信号（与随机无异）' },
  INCONSISTENT: { type: 'warning', icon: '⚠️', text: '双向不一致（理论异常）' },
  NO_MODELS: { type: 'info', icon: '📭', text: '暂无可用模型' },
  BACKTEST_FAILED: { type: 'danger', icon: '❌', text: '回测失败' }
}

const conclusion = computed(() => {
  const status = report.value?.conclusion?.status || 'NO_SIGNAL'
  return STATUS_MAP[status] || { type: 'info', icon: '❔', text: '未知状态' }
})

const forwardCount = computed(() => report.value?.model_groups?.forward?.count ?? 0)
const backwardCount = computed(() => report.value?.model_groups?.backward?.count ?? 0)

const forwardSignificant = computed(
  () => !!report.value?.consistency_check?.forward_any_significant
)
const backwardSignificant = computed(
  () => !!report.value?.consistency_check?.backward_any_significant
)

const mcTrials = computed(() => report.value?.baseline?.montecarlo_20k?.trials ?? 0)

const redLabel = computed(() => (lotteryType.value === 'ssq' ? '红球' : '前区'))
const blueLabel = computed(() => (lotteryType.value === 'ssq' ? '蓝球' : '后区'))

const baselineRows = computed(() => {
  const b = report.value?.baseline
  if (!b) return []
  const a = b.analytical
  const c = b.confidence
  const m = b.montecarlo_20k || {}
  return [
    {
      name: redLabel.value,
      E: a.red.E, SD: a.red.SD,
      mcE: m.red_E, diffE: Math.abs(a.red.E - (m.red_E ?? a.red.E)),
      threshold: c.red.threshold_95
    },
    {
      name: blueLabel.value,
      E: a.blue.E, SD: a.blue.SD,
      mcE: m.blue_E, diffE: Math.abs(a.blue.E - (m.blue_E ?? a.blue.E)),
      threshold: c.blue.threshold_95
    },
    {
      name: '合计',
      E: a.total.E, SD: a.total.SD,
      mcE: m.total_E, diffE: Math.abs(a.total.E - (m.total_E ?? a.total.E)),
      threshold: c.total.threshold_95
    }
  ]
})

const consistencyAlert = computed(() => {
  const c = report.value?.consistency_check
  if (!c) return { type: 'info', title: '暂无判定数据', desc: '' }
  if (c.consistent_both) {
    return {
      type: 'success',
      title: '双向一致：两方向都存在显著优于随机的模型',
      desc: '理论上可能存在可外推规律。建议多轮留出期重复评估交叉验证，避免单次偶然。'
    }
  }
  if (c.consistent_neither) {
    return {
      type: 'info',
      title: '双向一致：两方向都未跑赢随机',
      desc: '当前所有模型的样本外表现与纯随机无法区分。这是诚实结论——建议停止在噪音上过拟合。'
    }
  }
  return {
    type: 'warning',
    title: '双向不一致：仅单方向出现显著模型',
    desc: '理论上不应发生，疑似数据泄漏或回测区间错误，请检查模型的训练截止期号是否正确。'
  }
})

function directionRows(dir) {
  const rows = report.value?.direction_evals?.[dir]
  return Array.isArray(rows) ? rows : []
}

function fmt(v, digits = 3) {
  if (v === null || v === undefined || Number.isNaN(v)) return '-'
  return Number(v).toFixed(digits)
}

async function runDiagnostic() {
  loading.value = true
  try {
    report.value = await getDiagnostic(lotteryType.value, { nPeriods: nPeriods.value })
  } catch (e) {
    ElMessage.error('诊断失败：' + (e?.message || '未知错误'))
  } finally {
    loading.value = false
  }
}

onMounted(runDiagnostic)
</script>

<style scoped>
.diagnostic-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 说明卡片 */
.intro-card {
  background: linear-gradient(135deg, #ecf5ff 0%, #f5f7fa 100%);
  border: 1px solid #d9ecff;
}
.intro {
  display: flex;
  gap: 14px;
  align-items: flex-start;
}
.intro-icon {
  font-size: 28px;
  line-height: 1;
}
.intro-title {
  font-size: 18px;
  font-weight: bold;
  color: #303133;
  margin-bottom: 6px;
}
.intro-desc {
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
}

/* 工具栏 */
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}
.toolbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.period-select {
  width: 140px;
}

/* 加载 */
.loading-container {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 60px 0;
  color: #909399;
}

/* 结论卡片 */
.conclusion-card {
  border-left: 6px solid #909399;
}
.conclusion-success {
  border-left-color: #67c23a;
  background: #f0f9eb;
}
.conclusion-info {
  border-left-color: #909399;
  background: #f4f4f5;
}
.conclusion-warning {
  border-left-color: #e6a23c;
  background: #fdf6ec;
}
.conclusion-danger {
  border-left-color: #f56c6c;
  background: #fef0f0;
}
.conclusion-head {
  display: flex;
  gap: 14px;
  align-items: flex-start;
}
.conclusion-icon {
  font-size: 32px;
  line-height: 1.2;
}
.conclusion-label {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 18px;
  font-weight: bold;
  color: #303133;
}
.conclusion-message {
  margin-top: 8px;
  font-size: 14px;
  color: #303133;
  line-height: 1.6;
}
.conclusion-interpretation {
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
}
.conclusion-meta {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px dashed #dcdfe6;
  font-size: 13px;
  color: #606266;
}

/* 区块卡片 */
.section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.section-icon {
  font-size: 18px;
}
.section-title {
  font-size: 16px;
  font-weight: bold;
  color: #303133;
  margin-right: 8px;
}

/* 基线 */
.diff-badge {
  font-size: 11px;
  margin-left: 6px;
  padding: 0 4px;
  border-radius: 3px;
}
.diff-ok {
  color: #67c23a;
  background: #f0f9eb;
}
.diff-bad {
  color: #f56c6c;
  background: #fef0f0;
}
.threshold-note {
  font-size: 12px;
  color: #909399;
  margin-left: 6px;
}
.baseline-note {
  margin-top: 12px;
  font-size: 12px;
  color: #909399;
}

/* 方向盒 */
.direction-box {
  border-radius: 8px;
  padding: 16px;
  border: 1px solid #ebeef5;
}
.box-signal {
  background: #f0f9eb;
  border-color: #c2e7b0;
}
.box-nosignal {
  background: #f4f4f5;
  border-color: #e9e9eb;
}
.direction-name {
  font-size: 15px;
  font-weight: bold;
  color: #303133;
}
.direction-sub {
  font-size: 12px;
  color: #909399;
  margin: 6px 0 12px;
}
.direction-result {
  display: flex;
  align-items: center;
  gap: 12px;
}
.direction-count {
  font-size: 13px;
  color: #606266;
}
.consistency-alert {
  margin-top: 16px;
}

/* 明细表格 */
.lift-pos {
  color: #67c23a;
  font-weight: bold;
}
.lift-neg {
  color: #f56c6c;
  font-weight: bold;
}

@media (max-width: 768px) {
  .toolbar {
    flex-direction: column;
    align-items: stretch;
  }
  .conclusion-label {
    font-size: 16px;
  }
}
</style>
