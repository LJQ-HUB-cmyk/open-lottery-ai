<template>
  <div class="trend-page">
    <!-- ===== 工具栏 ===== -->
    <div class="trend-toolbar">
      <el-radio-group v-model="lotteryType" size="default" @change="loadTrend">
        <el-radio-button value="ssq">🟥 双色球</el-radio-button>
        <el-radio-button value="dlt">🟧 大乐透</el-radio-button>
      </el-radio-group>
      <el-select v-model="periods" size="default" style="width:160px;" @change="loadTrend">
        <el-option :value="30" label="最近 30 期" />
        <el-option :value="50" label="最近 50 期" />
        <el-option :value="100" label="最近 100 期" />
        <el-option :value="200" label="最近 200 期" />
        <el-option :value="300" label="最近 300 期" />
      </el-select>
      <el-button type="primary" plain :loading="loading" @click="loadTrend">
        <el-icon><Refresh /></el-icon> 刷新
      </el-button>
    </div>

    <!-- ===== 加载中 ===== -->
    <div v-if="loading" class="trend-loading">
      <el-icon class="is-loading"><Loading /></el-icon>
      <span>走势数据加载中...</span>
    </div>

    <template v-else-if="trendData">
      <!-- ===== 概览卡片 ===== -->
      <div class="trend-summary">
        <div class="summary-card">
          <div class="summary-value">{{ trendData.periods }}</div>
          <div class="summary-label">统计窗口（期）</div>
        </div>
        <div class="summary-card">
          <div class="summary-value">{{ trendData.total_history }}</div>
          <div class="summary-label">历史总期数</div>
        </div>
        <div class="summary-card">
          <div class="summary-value" style="font-size:18px;">{{ trendData.latest_issue }}</div>
          <div class="summary-label">最新期号（{{ trendData.latest_date }}）</div>
        </div>
        <div class="summary-card">
          <div class="summary-value" style="color:#f56c6c;">{{ trendData.summary.avg_sum }}</div>
          <div class="summary-label">{{ redName }}平均和值</div>
        </div>
        <div class="summary-card">
          <div class="summary-value" style="color:#409EFF;">{{ trendData.summary.avg_span }}</div>
          <div class="summary-label">{{ redName }}平均跨度</div>
        </div>
      </div>

      <!-- ===== 冷热号 ===== -->
      <div class="hot-cold-box">
        <div class="hc-section">
          <span class="hc-title">🔥 {{ redName }}热号 TOP5</span>
          <el-tag
            v-for="item in trendData.summary.hot_red"
            :key="'hr' + item.number"
            class="hc-tag ball-red-tag"
            size="large"
            effect="dark"
          >
            {{ String(item.number).padStart(2, '0') }} · {{ item.count }}次
          </el-tag>
        </div>
        <div class="hc-section">
          <span class="hc-title">❄️ {{ redName }}冷号（遗漏最久）TOP5</span>
          <el-tag
            v-for="item in trendData.summary.cold_red"
            :key="'cr' + item.number"
            class="hc-tag ball-gray-tag"
            size="large"
          >
            {{ String(item.number).padStart(2, '0') }} · 漏{{ item.missing }}期
          </el-tag>
        </div>
        <div class="hc-section">
          <span class="hc-title">🔥 {{ blueName }}热号 TOP5</span>
          <el-tag
            v-for="item in trendData.summary.hot_blue"
            :key="'hb' + item.number"
            class="hc-tag ball-blue-tag"
            size="large"
            effect="dark"
          >
            {{ String(item.number).padStart(2, '0') }} · {{ item.count }}次
          </el-tag>
        </div>
        <div class="hc-section">
          <span class="hc-title">❄️ {{ blueName }}冷号（遗漏最久）TOP5</span>
          <el-tag
            v-for="item in trendData.summary.cold_blue"
            :key="'cb' + item.number"
            class="hc-tag ball-gray-tag"
            size="large"
          >
            {{ String(item.number).padStart(2, '0') }} · 漏{{ item.missing }}期
          </el-tag>
        </div>
      </div>

      <!-- ===== 频率图表 ===== -->
      <el-row :gutter="16">
        <el-col :xs="24" :md="12">
          <div class="chart-card">
            <div class="chart-title">🔴 {{ redName }}号码出现频率</div>
            <div ref="redFreqRef" class="chart-box chart-tall"></div>
          </div>
        </el-col>
        <el-col :xs="24" :md="12">
          <div class="chart-card">
            <div class="chart-title">🔵 {{ blueName }}号码出现频率</div>
            <div ref="blueFreqRef" class="chart-box chart-tall"></div>
          </div>
        </el-col>
      </el-row>

      <!-- ===== 遗漏图表 ===== -->
      <el-row :gutter="16">
        <el-col :xs="24" :md="12">
          <div class="chart-card">
            <div class="chart-title">🔴 {{ redName }}当前遗漏期数</div>
            <div ref="redMissRef" class="chart-box chart-tall"></div>
          </div>
        </el-col>
        <el-col :xs="24" :md="12">
          <div class="chart-card">
            <div class="chart-title">🔵 {{ blueName }}当前遗漏期数</div>
            <div ref="blueMissRef" class="chart-box chart-tall"></div>
          </div>
        </el-col>
      </el-row>

      <!-- ===== 和值/跨度走势 ===== -->
      <div class="chart-card">
        <div class="chart-title">📈 {{ redName }}和值 / 跨度走势（最近 {{ trendData.periods }} 期）</div>
        <div ref="trendLineRef" class="chart-box chart-wide"></div>
      </div>

      <!-- ===== 形态分布 ===== -->
      <el-row :gutter="16">
        <el-col :xs="24" :md="12">
          <div class="chart-card">
            <div class="chart-title">⚖️ 奇偶分布（窗口累计）</div>
            <div ref="oddEvenRef" class="chart-box chart-pie"></div>
          </div>
        </el-col>
        <el-col :xs="24" :md="12">
          <div class="chart-card">
            <div class="chart-title">📏 大小分布（窗口累计）</div>
            <div ref="bigSmallRef" class="chart-box chart-pie"></div>
          </div>
        </el-col>
      </el-row>
    </template>

    <el-empty v-else description="暂无走势数据" />
  </div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import * as echarts from 'echarts'
import { Loading, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getTrendData } from '@/api/data'

const lotteryType = ref('ssq')
const periods = ref(100)
const loading = ref(false)
const trendData = ref(null)

// 红蓝名称随彩种切换
const redName = ref('红球')
const blueName = ref('蓝球')

// 图表 DOM 引用
const redFreqRef = ref(null)
const blueFreqRef = ref(null)
const redMissRef = ref(null)
const blueMissRef = ref(null)
const trendLineRef = ref(null)
const oddEvenRef = ref(null)
const bigSmallRef = ref(null)

// 图表实例缓存
const chartInstances = {}

const ensureChart = (key, el) => {
  if (!chartInstances[key] && el) {
    chartInstances[key] = echarts.init(el)
  }
  return chartInstances[key]
}

// 遗漏柱条颜色：遗漏越久越红
const missBarColor = (val) => {
  if (val === 0) return '#67C23A'
  if (val <= 4) return '#95d475'
  if (val <= 8) return '#e6a23c'
  return '#f56c6c'
}

// 频率柱状图配置
const buildFreqOption = (freqData, color, name) => {
  const labels = freqData.map(i => String(i.number).padStart(2, '0'))
  const values = freqData.map(i => i.count)
  const avg = values.reduce((a, b) => a + b, 0) / (values.length || 1)
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 40, right: 16, top: 30, bottom: 48 },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { interval: 0, rotate: labels.length > 20 ? 45 : 0, fontSize: 10 }
    },
    yAxis: { type: 'value', name: '出现次数', minInterval: 1 },
    series: [{
      name,
      type: 'bar',
      data: values,
      itemStyle: { color, borderRadius: [3, 3, 0, 0] },
      markLine: {
        silent: true,
        data: [{ type: 'average', name: '平均' }],
        lineStyle: { color: '#909399', type: 'dashed' },
        label: { formatter: `平均 ${avg.toFixed(1)}`, fontSize: 10 }
      }
    }]
  }
}

// 遗漏柱状图配置
const buildMissOption = (missData, name) => {
  const labels = missData.map(i => String(i.number).padStart(2, '0'))
  const values = missData.map(i => ({
    value: i.missing,
    itemStyle: { color: missBarColor(i.missing), borderRadius: [3, 3, 0, 0] }
  }))
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => `${params[0].name} 号<br/>${name}遗漏：<b>${params[0].value}</b> 期`
    },
    grid: { left: 40, right: 16, top: 30, bottom: 48 },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { interval: 0, rotate: labels.length > 20 ? 45 : 0, fontSize: 10 }
    },
    yAxis: { type: 'value', name: '遗漏期数', minInterval: 1 },
    series: [{ name, type: 'bar', data: values }]
  }
}

// 和值/跨度走势折线配置
const buildTrendLineOption = (trend) => {
  const labels = trend.map(t => t.issue_num)
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['和值', '跨度'], top: 0 },
    grid: { left: 48, right: 48, top: 34, bottom: 56 },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { rotate: 30, fontSize: 10 }
    },
    yAxis: [
      { type: 'value', name: '和值', position: 'left' },
      { type: 'value', name: '跨度', position: 'right' }
    ],
    dataZoom: [
      { type: 'inside', start: 0, end: 100 },
      { type: 'slider', height: 18, bottom: 18 }
    ],
    series: [
      {
        name: '和值',
        type: 'line',
        data: trend.map(t => t.sum),
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2, color: '#f56c6c' },
        itemStyle: { color: '#f56c6c' },
        areaStyle: { color: 'rgba(245,108,108,0.08)' }
      },
      {
        name: '跨度',
        type: 'line',
        yAxisIndex: 1,
        data: trend.map(t => t.span),
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2, color: '#409EFF' },
        itemStyle: { color: '#409EFF' }
      }
    ]
  }
}

// 饼图配置
const buildPieOption = (data, title) => {
  return {
    tooltip: { trigger: 'item', formatter: '{b}：{c}（{d}%）' },
    legend: { bottom: 0 },
    title: { text: title, left: 'center', top: 4, textStyle: { fontSize: 13, color: '#909399' } },
    series: [{
      type: 'pie',
      radius: ['42%', '66%'],
      center: ['50%', '52%'],
      label: { formatter: '{b}\n{d}%', fontSize: 12 },
      data: data
    }]
  }
}

// 渲染全部图表
const renderCharts = () => {
  nextTick(() => {
    const d = trendData.value
    if (!d) return

    ensureChart('redFreq', redFreqRef.value)?.setOption(buildFreqOption(d.red.frequency, '#f56c6c', redName.value), true)
    ensureChart('blueFreq', blueFreqRef.value)?.setOption(buildFreqOption(d.blue.frequency, '#409EFF', blueName.value), true)
    ensureChart('redMiss', redMissRef.value)?.setOption(buildMissOption(d.red.missing, redName.value), true)
    ensureChart('blueMiss', blueMissRef.value)?.setOption(buildMissOption(d.blue.missing, blueName.value), true)
    ensureChart('trendLine', trendLineRef.value)?.setOption(buildTrendLineOption(d.trend), true)
    ensureChart('oddEven', oddEvenRef.value)?.setOption(buildPieOption([
      { name: '奇数', value: d.summary.odd_even.odd, itemStyle: { color: '#f56c6c' } },
      { name: '偶数', value: d.summary.odd_even.even, itemStyle: { color: '#409EFF' } }
    ], `${redName}奇偶比`), true)
    ensureChart('bigSmall', bigSmallRef.value)?.setOption(buildPieOption([
      { name: '大数', value: d.summary.big_small.big, itemStyle: { color: '#e6a23c' } },
      { name: '小数', value: d.summary.big_small.small, itemStyle: { color: '#67C23A' } }
    ], `${redName}大小比`), true)

    // 容器尺寸就绪后重排
    Object.values(chartInstances).forEach(c => c.resize())
  })
}

// 加载走势数据
const loadTrend = async () => {
  loading.value = true
  redName.value = lotteryType.value === 'ssq' ? '红球' : '前区'
  blueName.value = lotteryType.value === 'ssq' ? '蓝球' : '后区'
  try {
    trendData.value = await getTrendData(lotteryType.value, periods.value)
  } catch (e) {
    console.error('走势数据加载失败:', e)
    ElMessage.error('走势数据加载失败：' + (e.message || '未知错误'))
    trendData.value = null
  } finally {
    loading.value = false
  }
  // 关键时序：loading 置 false 后模板才从加载态切换到内容态、图表容器才挂载，
  // 必须等到这一轮 DOM 更新完成后再 init/setOption，否则容器 ref 为 null 图表空白
  await nextTick()
  if (trendData.value) renderCharts()
}

// 窗口尺寸变化时重绘
const handleResize = () => {
  Object.values(chartInstances).forEach(c => c && c.resize())
}

onMounted(() => {
  loadTrend()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  Object.values(chartInstances).forEach(c => c && c.dispose())
})
</script>

<style scoped>
.trend-page {
  padding: 4px 0;
}

.trend-toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 18px;
  flex-wrap: wrap;
}

.trend-loading {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 50px;
  justify-content: center;
  color: #909399;
}

/* 概览卡片 */
.trend-summary {
  display: flex;
  gap: 14px;
  margin-bottom: 18px;
  flex-wrap: wrap;
}
.summary-card {
  flex: 1;
  min-width: 130px;
  background: #f5f7fa;
  border-radius: 10px;
  padding: 14px 10px;
  text-align: center;
  border: 1px solid #ebeef5;
}
.summary-value {
  font-size: 24px;
  font-weight: 700;
  color: #303133;
}
.summary-label {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

/* 冷热号 */
.hot-cold-box {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.hc-section {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.hc-title {
  font-size: 13px;
  font-weight: 600;
  color: #606266;
  min-width: 190px;
}
.hc-tag {
  border-radius: 16px;
  font-weight: 600;
}
.ball-red-tag {
  background: linear-gradient(145deg, #f56c6c, #d94a4a);
  border-color: transparent;
}
.ball-blue-tag {
  background: linear-gradient(145deg, #409EFF, #2b7fd4);
  border-color: transparent;
}
.ball-gray-tag {
  background: #f4f4f5;
  border-color: #dcdfe6;
  color: #909399;
}

/* 图表卡片 */
.chart-card {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 16px;
}
.chart-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
  padding-left: 8px;
  border-left: 3px solid #409EFF;
}
.chart-box {
  width: 100%;
}
.chart-tall {
  height: 300px;
}
.chart-wide {
  height: 340px;
}
.chart-pie {
  height: 260px;
}

/* 移动端 */
@media (max-width: 768px) {
  .chart-tall { height: 240px; }
  .chart-wide { height: 280px; }
  .chart-pie { height: 220px; }
  .summary-card { min-width: calc(33.33% - 10px); }
  .hc-title { min-width: 100%; }
}
</style>
