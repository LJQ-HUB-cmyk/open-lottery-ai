<template>
  <div class="analysis-page">
    <!-- ===== 开奖规则卡片 ===== -->
    <el-card class="rule-card" shadow="hover">
      <el-row :gutter="16" align="middle">
        <el-col :xs="24" :sm="12">
          <div class="rule-item">
            <span class="rule-dot ssq-dot">●</span>
            <span class="rule-name">双色球</span>
            <span class="rule-text">周二、四、日开奖</span>
            <el-tag size="small" type="info" round>每周3期</el-tag>
          </div>
        </el-col>
        <el-col :xs="24" :sm="12">
          <div class="rule-item">
            <span class="rule-dot dlt-dot">●</span>
            <span class="rule-name">大乐透</span>
            <span class="rule-text">周一、三、六开奖</span>
            <el-tag size="small" type="info" round>每周3期</el-tag>
          </div>
        </el-col>
      </el-row>

      <div v-if="upcoming" class="upcoming-info">
        <span class="upcoming-icon">📌</span>
        <span class="upcoming-text">
          下一期 <strong>{{ lotteryInfo?.name || '彩票' }}</strong>：
          <span class="draw-date">{{ upcoming.next_draw_date }}</span>
          （{{ upcoming.next_draw_weekday }}）
        </span>
        <el-tag v-if="upcoming.is_today" type="success" size="default" effect="dark" round>
          🎯 今天开奖！
        </el-tag>
        <el-tag v-else type="info" size="default" round>
          还有 {{ upcoming.days_until }} 天
        </el-tag>
      </div>
    </el-card>

    <!-- ===== 工具栏 ===== -->
    <el-card class="toolbar-card" shadow="hover">
      <div class="toolbar">
        <div class="toolbar-left">
          <el-radio-group v-model="lotteryType" @change="fetchData" size="default">
            <el-radio-button value="ssq">🟥 双色球</el-radio-button>
            <el-radio-button value="dlt">🟧 大乐透</el-radio-button>
          </el-radio-group>
        </div>
        <div class="toolbar-right">
          <el-button size="default" @click="fetchData" :loading="loading" type="primary" plain>
            <el-icon><Refresh /></el-icon> 刷新
          </el-button>
          <el-badge :value="total" :hidden="total === 0" type="primary">
            <span class="total-text">今日预测 {{ total }} 条</span>
          </el-badge>
        </div>
      </div>
    </el-card>

    <!-- ===== 加载状态 ===== -->
    <div v-if="loading" class="loading-container">
      <el-icon class="is-loading"><Loading /></el-icon>
      <span>加载中...</span>
    </div>

    <!-- ===== 内容区域 ===== -->
    <div v-else>
      <!-- ---- 数据概况 ---- -->
      <div v-if="frequency" class="overview-box">
        <div class="overview-header">
          <span class="overview-icon">📊</span>
          <span class="overview-title">数据概况</span>
        </div>
        <el-row :gutter="16">
          <el-col :xs="12" :sm="6">
            <div class="overview-item">
              <div class="overview-value">{{ frequency.total_count }}</div>
              <div class="overview-label">总预测记录数</div>
            </div>
          </el-col>
          <el-col :xs="12" :sm="6">
            <div class="overview-item">
              <div class="overview-value">{{ frequency.total_count > 0 ? '今日' : '-' }}</div>
              <div class="overview-label">预测日期</div>
            </div>
          </el-col>
          <el-col :xs="12" :sm="6">
            <div class="overview-item">
              <div class="overview-value">{{ frequency.total_count > 0 ? '1-' + frequency.total_count : '-' }}</div>
              <div class="overview-label">模型范围</div>
            </div>
          </el-col>
          <el-col :xs="12" :sm="6">
            <div class="overview-item">
              <div class="overview-value">{{ qualityScoreRange }}</div>
              <div class="overview-label">质量评分范围</div>
            </div>
          </el-col>
        </el-row>
      </div>

      <!-- ---- 最优推荐 ---- -->
      <div v-if="recommendation" class="recommendation-box">
        <div class="recommendation-header">
          <div class="header-left">
            <span class="rec-icon">⭐</span>
            <span class="rec-title">最优推荐号码</span>
          </div>
          <el-tag type="success" size="small" round class="confidence-tag">
            置信度 {{ (recommendation.confidence * 100).toFixed(1) }}%
          </el-tag>
        </div>
        <div class="rec-desc">基于 频率分析 + 质量评分加权 的智能推荐</div>

        <div class="recommend-numbers">
          <div class="number-row">
            <span class="label">🔴 红球</span>
            <div class="number-group">
              <span v-for="r in recommendation.red" :key="r" class="ball ball-red">
                {{ String(r).padStart(2, '0') }}
              </span>
            </div>
          </div>
          <div class="number-row">
            <span class="label">🔵 蓝球</span>
            <div class="number-group">
              <span v-if="Array.isArray(recommendation.blue)" v-for="b in recommendation.blue" :key="b" class="ball ball-blue">
                {{ String(b).padStart(2, '0') }}
              </span>
              <span v-else class="ball ball-blue">
                {{ String(recommendation.blue).padStart(2, '0') }}
              </span>
            </div>
          </div>
        </div>

        <div class="confidence-bar">
          <span class="confidence-label">综合置信度</span>
          <el-progress
            :percentage="Math.round((recommendation.confidence || 0) * 100)"
            :color="confidenceColor"
            :stroke-width="8"
            :format="() => (recommendation.confidence * 100).toFixed(1) + '%'"
            style="flex:1;"
          />
        </div>
      </div>

      <!-- ---- 建议投注组合 ---- -->
      <div v-if="frequency && frequency.total_count > 0" class="combinations-box">
        <div class="combinations-header">
          <span class="combinations-icon">🎯</span>
          <span class="combinations-title">建议投注组合</span>
        </div>
        <el-row :gutter="16">
          <el-col :xs="24" :sm="8">
            <div class="comb-item gold">
              <div class="comb-rank">🥇 最优组合</div>
              <div class="comb-desc">基于频率 + 评分加权</div>
              <div class="comb-numbers">
                <span class="comb-label">红球</span>
                <span class="comb-red" v-for="r in getCombination('gold').red" :key="r">{{ String(r).padStart(2, '0') }}</span>
              </div>
              <div class="comb-numbers">
                <span class="comb-label">蓝球</span>
                <span class="comb-blue" v-for="b in getCombination('gold').blue" :key="b">{{ String(b).padStart(2, '0') }}</span>
              </div>
              <div class="comb-confidence">置信度：{{ (recommendation?.confidence || 0) * 100 }}%</div>
            </div>
          </el-col>
          <el-col :xs="24" :sm="8">
            <div class="comb-item silver">
              <div class="comb-rank">🥈 高评分模型</div>
              <div class="comb-desc">最高质量评分模型</div>
              <div class="comb-numbers">
                <span class="comb-label">红球</span>
                <span class="comb-red" v-for="r in getCombination('silver').red" :key="r">{{ String(r).padStart(2, '0') }}</span>
              </div>
              <div class="comb-numbers">
                <span class="comb-label">蓝球</span>
                <span class="comb-blue" v-for="b in getCombination('silver').blue" :key="b">{{ String(b).padStart(2, '0') }}</span>
              </div>
              <div class="comb-confidence">评分：{{ getCombination('silver').score }}</div>
            </div>
          </el-col>
          <el-col :xs="24" :sm="8">
            <div class="comb-item bronze">
              <div class="comb-rank">🥉 综合稳妥</div>
              <div class="comb-desc">频率 + 覆盖均衡</div>
              <div class="comb-numbers">
                <span class="comb-label">红球</span>
                <span class="comb-red" v-for="r in getCombination('bronze').red" :key="r">{{ String(r).padStart(2, '0') }}</span>
              </div>
              <div class="comb-numbers">
                <span class="comb-label">蓝球</span>
                <span class="comb-blue" v-for="b in getCombination('bronze').blue" :key="b">{{ String(b).padStart(2, '0') }}</span>
              </div>
              <div class="comb-confidence">综合推荐</div>
            </div>
          </el-col>
        </el-row>
      </div>

      <!-- ---- 复试分析卡片 ---- -->
      <div v-if="fushiPlans && fushiPlans.length > 0" class="fushi-box">
        <div class="fushi-header">
          <span class="fushi-icon">🎲</span>
          <span class="fushi-title">复试最优方案</span>
          <el-tag v-if="fushiDate" type="info" size="small" round>期 {{ fushiDate }}</el-tag>
          <el-tag v-if="fushiPlans[0]?.freq_support" type="success" size="small" round>
            {{ fushiPlans[0].freq_support }} 条频率支撑
          </el-tag>
        </div>

        <el-row :gutter="12">
          <el-col v-for="plan in fushiPlans" :key="plan.pattern" :xs="24" :sm="12" :md="6">
            <div class="fushi-plan">
              <div class="plan-header">
                <span class="plan-pattern">{{ plan.pattern }}</span>
                <el-tag v-if="plan.prize_level" type="danger" size="small" effect="dark">
                  {{ plan.prize_level }}
                </el-tag>
                <el-tag v-else-if="plan.is_history_hit" type="warning" size="small">
                  历史中过奖
                </el-tag>
              </div>

              <div class="plan-pool">
                <span class="pool-label">🔴 红球池 ({{ plan.red_pool.length }})</span>
                <div class="pool-balls">
                  <span v-for="r in plan.red_pool" :key="r" class="ball ball-red ball-tiny">
                    {{ String(r).padStart(2, '0') }}
                  </span>
                </div>
              </div>
              <div class="plan-pool">
                <span class="pool-label">🔵 蓝球池 ({{ plan.blue_pool.length }})</span>
                <div class="pool-balls">
                  <span v-for="b in plan.blue_pool" :key="b" class="ball ball-blue ball-tiny">
                    {{ String(b).padStart(2, '0') }}
                  </span>
                </div>
              </div>

              <div class="plan-stats">
                <div class="stat-item">
                  <span class="stat-label">注数</span>
                  <span class="stat-value">{{ plan.bet_count }}</span>
                </div>
                <div class="stat-item">
                  <span class="stat-label">金额</span>
                  <span class="stat-value">¥{{ plan.bet_amount }}</span>
                </div>
              </div>

              <el-button
                size="small"
                type="primary"
                plain
                block
                @click="toggleCombo(plan)"
              >
                {{ expandedCombo === plan.pattern ? '收起全部注' : `展开全部注 (${plan.bet_count})` }}
              </el-button>

              <div v-if="expandedCombo === plan.pattern" class="combo-list">
                <div
                  v-for="(combo, i) in plan.combo_detail"
                  :key="i"
                  class="combo-item"
                >
                  <span class="combo-num">{{ i + 1 }}.</span>
                  <template v-for="r in combo.red" :key="'r'+r">
                    <span class="ball ball-red ball-tiny">{{ String(r).padStart(2, '0') }}</span>
                  </template>
                  <span class="combo-plus">+</span>
                  <template v-if="Array.isArray(combo.blue)" v-for="b in combo.blue" :key="'b'+b">
                    <span class="ball ball-blue ball-tiny">{{ String(b).padStart(2, '0') }}</span>
                  </template>
                  <span v-else class="ball ball-blue ball-tiny">{{ String(combo.blue).padStart(2, '0') }}</span>
                </div>
              </div>
            </div>
          </el-col>
        </el-row>
      </div>

      <!-- ---- 今日开奖结果对比 ---- -->
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
              <span v-for="r in result.red" :key="r" class="ball ball-red" :class="{ 'ball-matched': recommendation?.red?.includes(r) }">
                {{ String(r).padStart(2, '0') }}
                <span v-if="recommendation?.red?.includes(r)" class="match-mark">✓</span>
              </span>
            </div>
          </div>
          <div class="number-row">
            <span class="label">蓝球</span>
            <div class="number-group">
              <template v-if="Array.isArray(result.blue)">
                <span v-for="b in result.blue" :key="b" class="ball ball-blue" :class="{ 'ball-matched': recommendation?.blue?.includes?.(b) }">
                  {{ String(b).padStart(2, '0') }}
                  <span v-if="recommendation?.blue?.includes?.(b)" class="match-mark">✓</span>
                </span>
              </template>
              <span v-else class="ball ball-blue" :class="{ 'ball-matched': recommendation?.blue === result.blue }">
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
            <span class="match-total">/ {{ lotteryType === 'ssq' ? 6 : 5 }}</span>
          </div>
          <div class="match-divider"></div>
          <div class="match-item">
            <span class="match-label">蓝球命中</span>
            <span class="match-count match-blue">{{ matchCount.blue }}</span>
            <span class="match-total">/ {{ lotteryType === 'ssq' ? 1 : 2 }}</span>
          </div>
          <div class="match-divider"></div>
          <div class="match-item">
            <span class="match-label">总命中率</span>
            <span class="match-count match-total-rate">{{ matchRate }}%</span>
          </div>
        </div>
      </div>

      <!-- ===== 新增：被剔除预测明细（可折叠） ===== -->
      <!-- 相似度剔除功能已移除：所有预测全部保留，不再做历史相似度剔除 -->

      <!-- ---- 号码频率分析 ---- -->
      <div v-if="frequency && frequency.total_count > 0" class="frequency-box">
        <div class="frequency-header">
          <span class="freq-icon">📊</span>
          <span class="freq-title">号码频率分析</span>
          <el-tag type="info" size="small" round>基于 {{ frequency.total_count }} 条预测记录</el-tag>
        </div>

        <!-- 分析结论（动态） -->
        <div class="conclusion-box">
          <div class="conclusion-header">📈 分析结论</div>
          <el-table :data="dynamicConclusionData" border stripe size="small" style="width:100%;">
            <el-table-column prop="conclusion" label="结论" min-width="180" />
            <el-table-column prop="detail" label="说明" />
          </el-table>
        </div>

        <el-row :gutter="20">
          <el-col :span="14" :xs="24">
            <div class="freq-section">
              <div class="freq-subtitle">🔴 红球出现频率 TOP 15</div>
              <div class="freq-chart">
                <div v-for="item in frequency.red_top" :key="item.number" class="freq-bar-row">
                  <span class="freq-number">{{ String(item.number).padStart(2, '0') }}</span>
                  <div class="freq-bar-track">
                    <div class="freq-bar" :style="{ width: item.rate + '%', background: getBarColor(item.rate) }"></div>
                  </div>
                  <span class="freq-rate">{{ item.rate }}%</span>
                  <span class="freq-count">({{ item.count }}次)</span>
                </div>
              </div>
            </div>
          </el-col>
          <el-col :span="10" :xs="24">
            <div class="freq-section">
              <div class="freq-subtitle">🔵 蓝球出现频率</div>
              <div class="freq-chart">
                <div v-for="item in frequency.blue_top" :key="item.number" class="freq-bar-row">
                  <span class="freq-number">{{ String(item.number).padStart(2, '0') }}</span>
                  <div class="freq-bar-track">
                    <div class="freq-bar freq-bar-blue" :style="{ width: item.rate + '%', background: getBlueBarColor(item.rate) }"></div>
                  </div>
                  <span class="freq-rate">{{ item.rate }}%</span>
                  <span class="freq-count">({{ item.count }}次)</span>
                </div>
              </div>
            </div>
          </el-col>
        </el-row>

        <!-- 最高评分模型 -->
        <div class="top-models-section">
          <div class="freq-subtitle">🏆 最高质量评分模型 TOP 10</div>
          <el-table :data="frequency.top_models" border stripe size="small" style="width:100%;">
            <el-table-column prop="quality_score" label="质量评分" width="120">
              <template #default="{ row }">
                <el-tag :type="row.quality_score > 0.85 ? 'success' : 'warning'" size="small">
                  {{ row.quality_score }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="红球" min-width="200">
              <template #default="{ row }">
                <span v-for="r in row.red" :key="r" class="ball ball-red ball-tiny">{{ String(r).padStart(2, '0') }}</span>
              </template>
            </el-table-column>
            <el-table-column label="蓝球" width="120">
              <template #default="{ row }">
                <span v-if="Array.isArray(row.blue)" v-for="b in row.blue" :key="b" class="ball ball-blue ball-tiny">{{ String(b).padStart(2, '0') }}</span>
                <span v-else class="ball ball-blue ball-tiny">{{ String(row.blue).padStart(2, '0') }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="model_name" label="模型" min-width="180" show-overflow-tooltip />
          </el-table>
        </div>
      </div>

      <!-- ---- 空状态 ---- -->
      <div v-if="!recommendation && !result && forecasts.length === 0" class="empty-state">
        <el-empty description="今日暂无预测数据，请先生成预测">
          <el-button type="primary" @click="goToPredict">去生成预测</el-button>
        </el-empty>
      </div>

      <!-- ---- 预测记录列表（新增 all_table_id 列） ---- -->
      <el-card v-if="forecasts.length > 0" class="list-card" shadow="hover">
        <template #header>
          <div class="list-header">
            <span class="list-title">📋 今日预测记录</span>
            <el-tag type="info" size="small" round>共 {{ forecasts.length }} 条</el-tag>
          </div>
        </template>

        <el-table
          :data="paginatedForecasts"
          border
          stripe
          style="width:100%;"
          size="default"
          max-height="500"
        >
          <el-table-column label="红球" min-width="280">
            <template #default="{ row }">
              <span v-for="r in row.red" :key="r" class="ball ball-red ball-small">
                {{ String(r).padStart(2, '0') }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="蓝球" width="140">
            <template #default="{ row }">
              <template v-if="Array.isArray(row.blue)">
                <span v-for="b in row.blue" :key="b" class="ball ball-blue ball-small">
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
                :stroke-width="6"
                style="width:120px;display:inline-block;"
              />
            </template>
          </el-table-column>
          <el-table-column prop="create_time" label="预测时间" width="180" />
          <el-table-column prop="model_version" label="模型版本" width="140" show-overflow-tooltip />
          <!-- 历史相似度 -->
          <el-table-column label="历史相似度" width="180" align="center">
            <template #default="{ row }">
              <div v-if="row.max_similarity != null" style="display:flex; align-items:center; gap:6px;">
                <el-progress
                  :percentage="Math.round(row.max_similarity * 100)"
                  :color="simBarColor(row.max_similarity)"
                  :stroke-width="6"
                  style="width:100px;"
                  :show-text="false"
                />
                <span :style="{ color: simTextColor(row.max_similarity), fontSize: '12px', fontWeight: 600 }">
                  {{ (row.max_similarity * 100).toFixed(1) }}%
                </span>
              </div>
              <span v-else style="color:#c0c4cc;">-</span>
            </template>
          </el-table-column>
          <el-table-column prop="matched_history_issue" label="匹配期号" width="100" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.matched_history_issue" size="small" type="info">{{ row.matched_history_issue }}</el-tag>
              <span v-else style="color:#c0c4cc;">-</span>
            </template>
          </el-table-column>
          <!-- 新增：全组合表 ID（未导入全组合表时隐藏整列） -->
          <el-table-column v-if="hasAllTableIds" prop="all_table_id" label="全组合ID" width="100" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.all_table_id" size="small" type="info">{{ row.all_table_id }}</el-tag>
              <span v-else style="color:#c0c4cc;">-</span>
            </template>
          </el-table-column>
        </el-table>

        <div class="pagination-wrapper">
          <el-pagination
            v-model:current-page="currentPage"
            v-model:page-size="pageSize"
            :page-sizes="[10, 20, 50, 100]"
            :total="forecasts.length"
            layout="total, sizes, prev, pager, next"
            small
            @size-change="onPageSizeChange"
            @current-change="onPageChange"
          />
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getTodayAnalysis, getFushiList } from '@/api/analysis'
import { Loading, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

const router = useRouter()
const loading = ref(false)
const lotteryType = ref('ssq')
const forecasts = ref([])
const recommendation = ref(null)
const result = ref(null)
const total = ref(0)
const upcoming = ref(null)
const lotteryInfo = ref(null)
const frequency = ref(null)
// 全组合表是否已导入（空表时隐藏全组合ID列）
const hasAllTableIds = ref(false)
// 相似度阈值（仅用于列表相似度条着色，不再做剔除）
const similarityThresholdValue = ref(0.4)

// 复试分析
const fushiPlans = ref([])       // 四档方案 [{pattern, red_pool, blue_pool, bet_count, ...}]
const fushiDate = ref('')        // 当前方案对应的 forecast_date
const expandedCombo = ref('')    // 展开某档的全部注

// 分页
const currentPage = ref(1)
const pageSize = ref(10)

const paginatedForecasts = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  const end = start + pageSize.value
  return forecasts.value.slice(start, end)
})

const qualityScoreRange = computed(() => {
  if (!frequency.value || frequency.value.total_count === 0) return '-'
  const scores = forecasts.value.map(f => f.quality_score || 0)
  const min = Math.min(...scores)
  const max = Math.max(...scores)
  return `${min.toFixed(3)} - ${max.toFixed(3)}`
})

// ---- 动态分析结论 ----
const dynamicConclusionData = computed(() => {
  if (!frequency.value || frequency.value.total_count === 0) return []
  const redTop = frequency.value.red_top || []
  const blueTop = frequency.value.blue_top || []
  const conclusions = []
  if (redTop.length > 0) {
    const top = redTop[0]
    conclusions.push({
      conclusion: `🔴 红球 ${String(top.number).padStart(2,'0')} 极热`,
      detail: `出现率 ${top.rate}%，远高于其他号码`
    })
  }
  const stable = redTop.filter(item => item.rate >= 20)
  if (stable.length >= 3) {
    const nums = stable.slice(0,3).map(i => String(i.number).padStart(2,'0')).join('、')
    conclusions.push({
      conclusion: `🔴 红球 ${nums} 稳定`,
      detail: `出现率均超过 20%`
    })
  }
  if (blueTop.length > 0) {
    const top = blueTop[0]
    conclusions.push({
      conclusion: `🔵 蓝球 ${String(top.number).padStart(2,'0')} 超热`,
      detail: `出现率 ${top.rate}%，蓝球首选`
    })
  }
  if (blueTop.length > 1) {
    const second = blueTop[1]
    conclusions.push({
      conclusion: `🔵 蓝球 ${String(second.number).padStart(2,'0')} 次热`,
      detail: `出现率 ${second.rate}%，蓝球次选`
    })
  }
  conclusions.push({
    conclusion: '📊 质量评分范围',
    detail: qualityScoreRange.value
  })
  return conclusions
})

const goToPredict = () => { router.push('/predict') }

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

const matchRate = computed(() => {
  const total = 7
  const matched = matchCount.value.red + matchCount.value.blue
  return Math.round((matched / total) * 100)
})

const confidenceColor = computed(() => {
  const pct = (recommendation.value?.confidence || 0) * 100
  if (pct >= 70) return '#67C23A'
  if (pct >= 50) return '#E6A23C'
  return '#909399'
})

const getScoreColor = (score) => {
  const pct = score * 100
  if (pct >= 70) return '#67C23A'
  if (pct >= 50) return '#E6A23C'
  return '#909399'
}

const getBarColor = (rate) => {
  if (rate >= 30) return '#f56c6c'
  if (rate >= 20) return '#e6a23c'
  return '#409EFF'
}
const getBlueBarColor = (rate) => {
  if (rate >= 30) return '#409EFF'
  if (rate >= 20) return '#67C23A'
  return '#909399'
}

// ---- 投注组合 ----
const getCombination = (type) => {
  const defaultRed = [1, 2, 3, 4, 5]
  const defaultBlue = [1, 2]
  if (!frequency.value || frequency.value.total_count === 0) {
    return { red: defaultRed, blue: defaultBlue, score: '-' }
  }
  const redTop = frequency.value.red_top || []
  const blueTop = frequency.value.blue_top || []
  const redNums = redTop.map(r => r.number)
  const blueNums = blueTop.map(b => b.number)
  const topModel = frequency.value.top_models?.[0]

  if (type === 'gold') {
    const red = redNums.slice(0, 5)
    while (red.length < 5) {
      const missing = Math.floor(Math.random() * 35) + 1
      if (!red.includes(missing)) red.push(missing)
    }
    red.sort((a, b) => a - b)
    const blue = blueNums.slice(0, 2)
    while (blue.length < 2) {
      const missing = Math.floor(Math.random() * 12) + 1
      if (!blue.includes(missing)) blue.push(missing)
    }
    blue.sort((a, b) => a - b)
    return { red, blue, score: (recommendation.value?.confidence || 0) * 100 }
  }

  if (type === 'silver') {
    if (topModel) {
      return { red: topModel.red, blue: topModel.blue, score: topModel.quality_score }
    }
    const red = redNums.slice(0, 5)
    while (red.length < 5) {
      const missing = Math.floor(Math.random() * 35) + 1
      if (!red.includes(missing)) red.push(missing)
    }
    red.sort((a, b) => a - b)
    const blue = blueNums.slice(0, 2)
    while (blue.length < 2) {
      const missing = Math.floor(Math.random() * 12) + 1
      if (!blue.includes(missing)) blue.push(missing)
    }
    blue.sort((a, b) => a - b)
    return { red, blue, score: '-' }
  }

  // bronze
  const red = [redNums[0] || 1, redNums[2] || 3, redNums[3] || 4, redNums[4] || 5, redNums[5] || 6]
  while (red.length < 5) {
    const missing = Math.floor(Math.random() * 35) + 1
    if (!red.includes(missing)) red.push(missing)
  }
  red.sort((a, b) => a - b)
  const blue = [blueNums[0] || 1, blueNums[1] || 2]
  while (blue.length < 2) {
    const missing = Math.floor(Math.random() * 12) + 1
    if (!blue.includes(missing)) blue.push(missing)
  }
  blue.sort((a, b) => a - b)
  return { red, blue, score: '-' }
}

// ---- 获取数据 ----
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
    frequency.value = res.frequency
    hasAllTableIds.value = !!res.has_all_table_ids
    similarityThresholdValue.value = res.similarity_threshold_value || 0.4
    currentPage.value = 1
    if (res.message) ElMessage.info(res.message)

    // 同时加载已有的复试方案（拿最新一期）
    await _loadLatestFushi()
  } catch (e) {
    console.error('加载分析数据失败:', e)
    ElMessage.error('加载数据失败：' + (e.message || '未知错误'))
  } finally {
    loading.value = false
  }
}

// ---- 复试相关 ----

const _loadLatestFushi = async () => {
  try {
    const res = await getFushiList(lotteryType.value, null, 3)
    if (res.items && res.items.length > 0) {
      const first = res.items[0]   // 最新一期
      fushiDate.value = first.forecast_date
      fushiPlans.value = first.patterns || []
    } else {
      fushiPlans.value = []
      fushiDate.value = ''
    }
  } catch (e) {
    console.warn('加载复试列表失败（忽略）:', e?.message)
  }
}

const toggleCombo = (plan) => {
  expandedCombo.value = expandedCombo.value === plan.pattern ? '' : plan.pattern
}

// 预测列表相似度颜色（基于动态阈值）
const simBarColor = (sim) => {
  const t = similarityThresholdValue.value
  if (sim >= t) return '#f56c6c'
  if (sim >= t * 0.8) return '#e6a23c'
  return '#67C23A'
}
const simTextColor = (sim) => {
  const t = similarityThresholdValue.value
  if (sim >= t) return '#f56c6c'
  if (sim >= t * 0.8) return '#e6a23c'
  return '#67C23A'
}

const onPageChange = (page) => { currentPage.value = page }
const onPageSizeChange = (size) => {
  pageSize.value = size
  currentPage.value = 1
}

onMounted(fetchData)
</script>

<style scoped>
.analysis-page {
  padding: 16px;
  max-width: 1400px;
  margin: 0 auto;
}

/* 规则卡片 */
.rule-card {
  margin-bottom: 16px;
  border-radius: 12px;
}
.rule-card :deep(.el-card__body) { padding: 14px 20px; }
.rule-item { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.rule-dot { font-size: 14px; margin-right: 2px; }
.ssq-dot { color: #f56c6c; }
.dlt-dot { color: #e6a23c; }
.rule-name { font-weight: 600; font-size: 14px; color: #303133; }
.rule-text { color: #606266; font-size: 13px; }

.upcoming-info {
  margin-top: 10px;
  padding: 8px 14px;
  background: #f0f9ff;
  border-radius: 6px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.upcoming-icon { font-size: 16px; }
.upcoming-text { font-size: 14px; color: #303133; }
.draw-date { color: #409EFF; font-weight: bold; }

/* 工具栏 */
.toolbar-card {
  margin-bottom: 16px;
  border-radius: 12px;
}
.toolbar-card :deep(.el-card__body) { padding: 10px 16px; }
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}
.toolbar-left { display: flex; align-items: center; }
.toolbar-right { display: flex; align-items: center; gap: 12px; }
.total-text { color: #606266; font-size: 14px; margin-left: 4px; }

/* 加载状态 */
.loading-container {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 60px 0;
  font-size: 16px;
  color: #409EFF;
  gap: 10px;
}

/* 数据概况 */
.overview-box {
  background: #fff;
  padding: 16px 20px;
  border-radius: 12px;
  margin-bottom: 16px;
  border: 1px solid #ebeef5;
}
.overview-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.overview-icon { font-size: 18px; }
.overview-title { font-size: 17px; font-weight: 600; color: #303133; }
.overview-item {
  text-align: center;
  padding: 8px 0;
  background: #f5f7fa;
  border-radius: 8px;
}
.overview-value { font-size: 24px; font-weight: 700; color: #409EFF; }
.overview-label { font-size: 13px; color: #909399; margin-top: 2px; }

/* 最优推荐 */
.recommendation-box {
  background: linear-gradient(135deg, #f0f9ff 0%, #e3f0fa 100%);
  padding: 18px 22px 20px;
  border-radius: 12px;
  margin-bottom: 16px;
  border-left: 4px solid #409EFF;
}
.recommendation-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}
.header-left { display: flex; align-items: center; gap: 8px; }
.rec-icon { font-size: 18px; }
.rec-title { font-size: 17px; font-weight: 600; color: #303133; }
.confidence-tag { flex-shrink: 0; }
.rec-desc { font-size: 13px; color: #909399; margin-bottom: 12px; }

/* 投注组合 */
.combinations-box {
  background: #fff;
  padding: 16px 20px;
  border-radius: 12px;
  margin-bottom: 16px;
  border: 1px solid #ebeef5;
}
.combinations-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.combinations-icon { font-size: 18px; }
.combinations-title { font-size: 17px; font-weight: 600; color: #303133; }
.comb-item {
  padding: 14px 16px;
  border-radius: 10px;
  text-align: center;
  height: 100%;
}
.comb-item.gold { background: linear-gradient(135deg, #fff7e6, #fdebd0); border: 1px solid #f5dab1; }
.comb-item.silver { background: linear-gradient(135deg, #f5f7fa, #e8eaed); border: 1px solid #dcdfe6; }
.comb-item.bronze { background: linear-gradient(135deg, #fdf6ec, #f5dab1); border: 1px solid #e6c8a0; }
.comb-rank { font-weight: 700; font-size: 16px; }
.comb-desc { font-size: 12px; color: #909399; margin: 2px 0 10px; }
.comb-numbers { margin: 4px 0; display: flex; justify-content: center; flex-wrap: wrap; gap: 4px; }
.comb-label { font-size: 12px; color: #909399; margin-right: 4px; font-weight: 600; }
.comb-red, .comb-blue {
  display: inline-block;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  text-align: center;
  line-height: 28px;
  font-size: 12px;
  font-weight: 700;
  color: #fff;
}
.comb-red { background: linear-gradient(145deg, #f56c6c, #d94a4a); }
.comb-blue { background: linear-gradient(145deg, #409EFF, #2b7fd4); }
.comb-confidence { font-size: 13px; color: #606266; margin-top: 6px; font-weight: 600; }

/* 号码球 */
.ball {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border-radius: 50%;
  font-size: 15px;
  font-weight: 700;
  color: #fff;
  margin: 0 3px;
  position: relative;
  transition: all 0.2s;
}
.ball-red { background: linear-gradient(145deg, #f56c6c, #d94a4a); box-shadow: 0 2px 6px rgba(245, 108, 108, 0.35); }
.ball-blue { background: linear-gradient(145deg, #409EFF, #2b7fd4); box-shadow: 0 2px 6px rgba(64, 158, 255, 0.35); }
.ball-matched { box-shadow: 0 0 0 3px #67C23A, 0 2px 10px rgba(103, 194, 58, 0.45); transform: scale(1.04); }
.ball-small { width: 30px; height: 30px; font-size: 12px; margin: 0 2px; }
.ball-tiny { width: 26px; height: 26px; font-size: 11px; margin: 0 1px; }
.match-mark {
  position: absolute;
  top: -5px;
  right: -5px;
  font-size: 10px;
  color: #67C23A;
  background: #fff;
  border-radius: 50%;
  width: 14px;
  height: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 1px 3px rgba(0,0,0,0.15);
}

.number-row {
  display: flex;
  align-items: center;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.number-row:last-child { margin-bottom: 0; }
.label { font-weight: 600; color: #606266; width: 56px; flex-shrink: 0; font-size: 14px; }
.number-group { display: flex; flex-wrap: wrap; gap: 3px; }

/* 置信度 */
.confidence-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed rgba(0,0,0,0.08);
}
.confidence-label { font-size: 13px; color: #606266; white-space: nowrap; }
.confidence-bar .el-progress { flex: 1; }

/* 开奖结果 */
.result-box {
  background: linear-gradient(135deg, #fdf6ec 0%, #faefe2 100%);
  padding: 18px 22px 20px;
  border-radius: 12px;
  margin-bottom: 16px;
  border-left: 4px solid #e6a23c;
}
.result-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}
.result-icon { font-size: 18px; }
.result-title { font-size: 17px; font-weight: 600; color: #303133; }
.result-numbers .number-row { margin-bottom: 6px; }

/* 命中统计 */
.match-summary {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px dashed rgba(0,0,0,0.1);
}
.match-item { display: flex; align-items: center; gap: 4px; }
.match-label { font-size: 13px; color: #606266; }
.match-count { font-size: 20px; font-weight: 700; }
.match-red { color: #f56c6c; }
.match-blue { color: #409EFF; }
.match-total-rate { color: #67C23A; font-size: 22px; }
.match-total { color: #909399; font-size: 13px; }
.match-divider { width: 1px; height: 24px; background: #dcdfe6; }

/* 频率分析 */
.frequency-box {
  background: #fff;
  padding: 18px 22px 20px;
  border-radius: 12px;
  margin-bottom: 16px;
  border: 1px solid #ebeef5;
}

.frequency-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.freq-icon { font-size: 18px; }
.freq-title { font-size: 17px; font-weight: 600; color: #303133; }
.freq-subtitle { font-size: 14px; font-weight: 600; color: #606266; margin-bottom: 10px; }
.freq-section { margin-bottom: 16px; }
.freq-chart { max-height: 350px; overflow-y: auto; padding-right: 4px; }
.freq-chart::-webkit-scrollbar { width: 4px; }
.freq-chart::-webkit-scrollbar-thumb { background: #dcdfe6; border-radius: 4px; }
.freq-bar-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 0;
  font-size: 13px;
}
.freq-number { font-weight: 600; color: #303133; width: 28px; text-align: center; flex-shrink: 0; }
.freq-bar-track { flex: 1; height: 16px; background: #f5f7fa; border-radius: 4px; overflow: hidden; position: relative; }
.freq-bar { height: 100%; border-radius: 4px; transition: width 0.6s ease; }
.freq-bar-blue { background: linear-gradient(90deg, #409EFF, #2171c7) !important; }
.freq-rate { font-weight: 600; width: 44px; text-align: right; flex-shrink: 0; font-size: 12px; }
.freq-count { color: #909399; font-size: 11px; width: 50px; flex-shrink: 0; }

/* 分析结论 */
.conclusion-box {
  background: #f5f7fa;
  padding: 12px 16px;
  border-radius: 8px;
  margin-bottom: 16px;
}
.conclusion-header { font-weight: 700; font-size: 15px; color: #303133; margin-bottom: 8px; }

.top-models-section {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #ebeef5;
}

/* 空状态 */
.empty-state { padding: 40px 0; background: #fff; border-radius: 12px; }

/* 预测列表 */
.list-card {
  border-radius: 12px;
}
.list-card :deep(.el-card__header) {
  padding: 12px 18px;
  border-bottom: 1px solid #ebeef5;
}
.list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.list-title { font-size: 15px; font-weight: 600; color: #303133; }
.list-card :deep(.el-table) {
  border-radius: 8px;
  overflow: hidden;
}
.list-card :deep(.el-table th) {
  background: #f5f7fa;
}

/* 分页 */
.pagination-wrapper {
  display: flex;
  justify-content: flex-end;
  padding-top: 14px;
  margin-top: 6px;
  border-top: 1px solid #ebeef5;
}
.pagination-wrapper :deep(.el-pagination) {
  padding: 0;
}

/* 复试分析卡片 */
.fushi-box {
  background: linear-gradient(135deg, #e6f7ff 0%, #bae7ff 100%);
  padding: 18px 22px 20px;
  border-radius: 12px;
  margin-bottom: 16px;
  border-left: 4px solid #1890ff;
}
.fushi-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.fushi-icon { font-size: 18px; }
.fushi-title { font-size: 17px; font-weight: 600; color: #303133; }

.fushi-plan {
  background: #fff;
  border: 1px solid #d9d9d9;
  border-radius: 10px;
  padding: 12px 14px;
  height: 100%;
  margin-bottom: 12px;
  transition: all 0.2s;
}
.fushi-plan:hover {
  border-color: #1890ff;
  box-shadow: 0 2px 8px rgba(24, 144, 255, 0.15);
}

.plan-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.plan-pattern {
  font-weight: 700;
  font-size: 18px;
  color: #1890ff;
  background: #e6f7ff;
  padding: 2px 10px;
  border-radius: 4px;
}

.plan-pool { margin-bottom: 8px; }
.pool-label {
  font-size: 12px;
  color: #606266;
  font-weight: 600;
  display: block;
  margin-bottom: 4px;
}
.pool-balls { display: flex; flex-wrap: wrap; gap: 3px; }

.plan-stats {
  display: flex;
  justify-content: space-around;
  margin: 10px 0;
  padding: 8px 0;
  border-top: 1px dashed #e8e8e8;
  border-bottom: 1px dashed #e8e8e8;
}
.stat-item { text-align: center; }
.stat-label { font-size: 11px; color: #909399; display: block; }
.stat-value { font-size: 16px; font-weight: 700; color: #f56c6c; }

.combo-list {
  margin-top: 10px;
  max-height: 320px;
  overflow-y: auto;
  padding: 8px;
  background: #f5f7fa;
  border-radius: 6px;
  border: 1px solid #ebeef5;
}
.combo-item {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 3px 4px;
  font-size: 12px;
  border-bottom: 1px dashed #ebeef5;
}
.combo-item:last-child { border-bottom: none; }
.combo-num {
  color: #909399;
  width: 28px;
  flex-shrink: 0;
  font-size: 11px;
}
.combo-plus {
  color: #c0c4cc;
  font-weight: 700;
  margin: 0 2px;
}

/* 响应式 */
@media (max-width: 768px) {
  .analysis-page { padding: 8px; }
  .toolbar { flex-direction: column; align-items: stretch; }
  .toolbar-left { justify-content: center; }
  .toolbar-right { justify-content: center; }
  .recommendation-box, .result-box, .frequency-box, .overview-box, .combinations-box { padding: 14px 16px; }
  .number-row { flex-direction: column; align-items: flex-start; gap: 4px; }
  .label { width: auto; }
  .match-summary { flex-wrap: wrap; gap: 8px; }
  .match-divider { display: none; }
  .ball { width: 32px; height: 32px; font-size: 13px; }
  .ball-small { width: 26px; height: 26px; font-size: 11px; }
  .ball-tiny { width: 22px; height: 22px; font-size: 10px; }
  .upcoming-info { flex-direction: column; align-items: flex-start; }
  .rule-item { flex-wrap: wrap; }
  .freq-bar-row { font-size: 12px; }
  .freq-number { width: 22px; }
  .freq-rate { width: 36px; font-size: 11px; }
  .freq-count { width: 40px; font-size: 10px; }
  .comb-item { margin-bottom: 12px; }
  .pagination-wrapper { justify-content: center; }
  .pagination-wrapper :deep(.el-pagination) .el-pagination__total {
    display: none;
  }
}
</style>